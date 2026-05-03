#!/usr/bin/env python3
"""Remote-Quansheng 主服务器

FastAPI + WebSocket 服务器
通过 TCP 连接 QDNH 后端，在浏览器端提供电台远程操控。

QDNH 后端 (QDNH.exe) 由 start.bat 独立启动，此服务器仅做 TCP 客户端。
"""

import asyncio
import json
import logging
import struct
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from serial_protocol import SerialProtocol, PacketCmd, build_packet
from radio_control import RadioController
from audio_stream import AudioStreamManager
from qdnh_client import QDNHClient
from config import load_config, save_config

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("server")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# ---- 全局组件 ----
qdnh = QDNHClient()
protocol = SerialProtocol()
config = load_config()
audio_manager = AudioStreamManager()

ws_clients: set[WebSocket] = set()
ws_lock = asyncio.Lock()


def send_serial_packet(cmd: int, *args):
    packet = build_packet(cmd, *args)
    qdnh.send_serial(packet)

radio = RadioController(send_serial_packet)


async def send_key_release():
    """延时发送按键释放码"""
    await asyncio.sleep(0.05)
    radio.send_keypress(19)


# ---- 广播 ----

async def broadcast(msg: dict):
    if not ws_clients:
        return
    text = json.dumps(msg, ensure_ascii=False)
    async with ws_lock:
        dead = set()
        for ws in ws_clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        ws_clients.difference_update(dead)


async def broadcast_state():
    await broadcast({"type": "radio_state", "data": radio.get_state()})


# ---- QDNH回调 ----

qdnh.on_serial_data(lambda data: protocol.feed_bytes(data))
qdnh.on_audio_data(lambda data: audio_manager.on_qdnh_audio(data))

# QDNH断线 → 通知所有浏览器
def on_qdnh_disconnect():
    asyncio.ensure_future(broadcast({"type": "connection", "connected": False}))
    radio._ready = False

qdnh.on_disconnect(on_qdnh_disconnect)


# ---- 串口协议回调 ----

async def on_ui_packet(ui_type, val1, val2, val3, data_len, data):
    msg = {"type": "ui_packet", "ui_type": ui_type}

    if ui_type in (0, 1, 2, 3):
        x, y = val1, val2
        while x > 128: y += 1; x -= 128
        scale = {0: 1.5, 1: val3/6.0, 2: val3/6.0, 3: 2.0}[ui_type]
        bold, thick = ui_type == 2, ui_type in (2, 3)
        msg.update({"subtype": "text", "x": x, "y": y + 1,
                     "scale": scale, "bold": bold, "thick": thick,
                     "text": data.decode("ascii", errors="replace")})
    elif ui_type == 5:
        msg.update({"subtype": "clear", "line_start": val1, "line_end": val2})
    elif ui_type == 6:
        ind = {}
        sb = val1
        if sb & 1:   ind["tx"] = True
        elif sb & 2: ind["rx"] = True
        else:        ind["standby"] = True
        for bit, key in [(8,"noa"),(16,"dtmf"),(32,"fm"),(64,"arrow"),(128,"dwr")]:
            if sb & bit: ind[key] = True
        for bit, key in [(1,"dual_watch"),(2,"xb"),(4,"vox"),(8,"lock"),
                         (16,"keylock"),(32,"power_save")]:
            if val2 & bit: ind[key] = True
        bv = min(data_len * 0.04, 8.4)
        msg.update({"subtype": "status", "indicators": ind,
                     "battery_voltage": round(bv, 2),
                     "battery_percent": round(data_len / 2.1, 0),
                     "code": chr(val3) if val3 else ""})
    elif ui_type == 7:
        msg.update({"subtype": "scroll", "line": val1,
                     "direction": "right" if val2 == 0 else "left"})
    elif ui_type == 8:
        msg.update({"subtype": "signal", "level": val1, "value": val2})
    elif ui_type == 10:
        m = {0:"0",1:"1",2:"2",3:"3",4:"4",5:"5",6:"6",7:"7",8:"8",9:"9",
             10:"A",11:"B",12:"C",13:"D",14:"*",15:"#"}
        msg.update({"subtype": "dtmf", "digit": m.get(val1, "?")})

    await broadcast(msg)

protocol.on_ui_packet(on_ui_packet)


@protocol.on_command(PacketCmd.RegisterInfo)
def on_register(packet: bytearray):
    reg = struct.unpack_from('<H', packet, 4)[0]
    val = struct.unpack_from('<H', packet, 6)[0]
    radio.handle_register_value(reg, val)


# ---- Lifespan ----

async def try_connect_qdnh():
    """尝试连接外部 QDNH 后端 (TCP 客户端模式)

    由 start.bat 独立启动 QDNH.exe, 本函数仅做 TCP 连接。
    最多重试 3 次，每次间隔 2s，等待 QDNH 初始化。
    """
    host = config.get("qdnh_host", "127.0.0.1")
    port = config.get("qdnh_port", 18822)
    password = config.get("qdnh_password", "")

    for attempt in range(3):
        try:
            ok = await qdnh.connect(host, port, password)
            if ok:
                logger.info(f"[{attempt+1}/3] QDNH 连接成功 ({host}:{port})")
                radio.send_keypress(13)  # EXIT
                await asyncio.sleep(0.05)
                radio.send_keypress(19)  # KEY RELEASE
                return
            logger.warning(f"[{attempt+1}/3] QDNH 连接成功但认证失败")
            return
        except ConnectionRefusedError:
            if attempt < 2:
                logger.info(f"[{attempt+1}/3] QDNH 端口未就绪 ({host}:{port}), 2s 后重试...")
                await asyncio.sleep(2)
                continue
            logger.warning(f"[{attempt+1}/3] QDNH 端口无响应, 请确认 QDNH.exe 已通过 start.bat 启动")
        except Exception as e:
            if attempt < 2:
                logger.warning(f"[{attempt+1}/3] 连接异常 ({e}), 2s 后重试...")
                await asyncio.sleep(2)
                continue
            logger.error(f"[{attempt+1}/3] QDNH 连接失败: {e}")
            logger.warning("请手动启动 QDNH.exe 后刷新网页或点击「连接 QDNH」")


# ---- 连接监控与自动重连 ----

async def connection_monitor():
    """后台任务: 每 5 秒检查 QDNH TCP 连接, 断开时自动重连

    解决 QDNH.exe 重启/串口断开/临时故障后连接不恢复的问题。
    """
    host = config.get("qdnh_host", "127.0.0.1")
    port = config.get("qdnh_port", 18822)
    password = config.get("qdnh_password", "")
    while True:
        try:
            await asyncio.sleep(5)
            if not qdnh.connected:
                logger.warning("检测到 QDNH 断开, 自动重连中...")
                await broadcast({"type": "connection", "connected": False,
                                 "reconnecting": True})
                for attempt in range(5):
                    try:
                        ok = await qdnh.connect(host, port, password)
                        if ok:
                            logger.info(f"自动重连成功 ({attempt+1}/5)")
                            radio.send_keypress(13)
                            await asyncio.sleep(0.05)
                            radio.send_keypress(19)
                            await broadcast({"type": "connection",
                                             "connected": True})
                            break
                    except ConnectionRefusedError:
                        if attempt < 4:
                            await asyncio.sleep(2)
                            continue
                        logger.warning("自动重连失败: QDNH 端口无响应")
                    except Exception as e:
                        if attempt < 4:
                            await asyncio.sleep(2)
                            continue
                        logger.error(f"自动重连失败: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"连接监控异常: {e}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Remote-Quansheng 服务器启动中...")
    await try_connect_qdnh()
    monitor_task = asyncio.ensure_future(connection_monitor())
    logger.info("Remote-Quansheng 服务器已启动 (浏览器: http://localhost:8000)")
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except (asyncio.CancelledError, Exception):
        pass
    if radio._ready:
        radio.exit_xvfo()
    audio_manager.stop()
    await qdnh.disconnect()
    logger.info("服务器已关闭")


app = FastAPI(title="Remote-Quansheng", version="2.0.0", lifespan=lifespan)


# ---- REST API ----

@app.get("/api/status")
async def api_status():
    return {
        "qdnh_connected": qdnh.connected,
        "qdnh_serial": qdnh.serial_connected,
        "qdnh_audio": qdnh.audio_connected,
        "radio": radio.get_state(),
        "audio": audio_manager.get_status(),
    }


@app.get("/api/health")
async def api_health():
    """健康检查"""
    return {"status": "ok", "qdnh_connected": qdnh.connected}


@app.post("/api/connect")
async def api_connect(data: dict):
    host = data.get("host", config.get("qdnh_host", "127.0.0.1"))
    port = int(data.get("port", config.get("qdnh_port", 18822)))
    password = data.get("password", config.get("qdnh_password", ""))
    ok = await qdnh.connect(host, port, password)
    if ok:
        config["qdnh_host"] = host
        config["qdnh_port"] = port
        config["qdnh_password"] = password
        save_config(config)
        # 按照QuanshengDock QDNH模式的初始化流程:
        # 发送EXIT(13)清除菜单 + KEY RELEASE(19)释放按键
        radio.send_keypress(13)
        await asyncio.sleep(0.05)
        radio.send_keypress(19)
    await broadcast({"type": "connection", "connected": ok})
    return {"success": ok}


@app.post("/api/disconnect")
async def api_disconnect():
    if radio._ready:
        radio.exit_xvfo()
        await asyncio.sleep(0.05)
    audio_manager.stop()
    await qdnh.disconnect()
    await broadcast({"type": "connection", "connected": False})
    return {"success": True}


@app.post("/api/keypress")
async def api_keypress(data: dict):
    kc = data.get("keycode", 0)
    radio.send_keypress(kc)
    await asyncio.sleep(0.05)
    radio.send_keypress(19)  # key release
    return {"success": True}





@app.post("/api/reconnect-audio")
async def api_reconnect_audio():
    """断开并重连 QDNH 音频 TCP 连接
    
    当 QDNH 音频捕获未启动时 (rx_packets=0), 重连可以触发 QDNH 重新初始化
    """
    logger.info("收到音频重连请求")
    # 停止当前音频流
    audio_manager.stop()
    # 断开音频 TCP 连接
    old_audio_writer = qdnh._audio_writer
    old_audio_reader = qdnh._audio_reader
    qdnh._audio_connected = False
    # 取消旧读取任务
    if qdnh._audio_read_task and not qdnh._audio_read_task.done():
        qdnh._audio_read_task.cancel()
        try:
            await qdnh._audio_read_task
        except (asyncio.CancelledError, Exception):
            pass
        qdnh._audio_read_task = None
    # 关闭旧连接
    if old_audio_writer:
        try:
            old_audio_writer.close()
        except Exception:
            pass
    qdnh._audio_reader = None
    qdnh._audio_writer = None
    # 等待 QDNH 释放端口
    await asyncio.sleep(1)
    # 重新连接
    host = config.get("qdnh_host", "127.0.0.1")
    port = config.get("qdnh_port", 18822)
    password = config.get("qdnh_password", "")
    try:
        ok = await qdnh._connect_audio(host, port, password)
        if ok:
            qdnh._audio_read_task = asyncio.ensure_future(qdnh._audio_read_loop())
            logger.info("音频重连成功")
        else:
            logger.warning("音频重连失败 (认证失败)")
    except Exception as e:
        logger.error(f"音频重连出错: {e}")
        return {"success": False, "error": str(e)}
    await broadcast({"type": "audio_reconnect", "result": ok})
    return {"success": ok}





@app.get("/api/settings")
async def api_settings():
    return {"settings": config}


@app.post("/api/settings")
async def api_save_settings(data: dict):
    for k, v in data.items():
        if k in config:
            config[k] = v
    save_config(config)
    return {"success": True}


# ---- WebSocket ----

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    async with ws_lock:
        ws_clients.add(ws)

    await ws.send_json({"type": "connection", "connected": qdnh.connected})
    await ws.send_json({"type": "radio_state", "data": radio.get_state()})

    # 为此WebSocket创建音频发送协程
    async def send_audio_to_browser(msg: dict):
        try:
            if ws in ws_clients:
                await ws.send_json(msg)
        except Exception:
            pass

    try:
        while True:
            data = await ws.receive_json()
            t = data.get("type", "")

            if t == "keypress":
                kc = data.get("keycode", 0)
                radio.send_keypress(kc)
                asyncio.ensure_future(send_key_release())
            elif t == "toggle_ptt":
                if data.get("pressed"):
                    radio.send_keypress(16)
                else:
                    radio.send_keypress(19)

            # 音频
            elif t == "audio_start":
                audio_manager.set_send_coro(send_audio_to_browser)
                audio_manager.set_qdnh_sender(lambda pcm: qdnh.send_audio(pcm))
                audio_manager.start()
                await ws.send_json({"type": "audio_started"})
            elif t == "audio_stop":
                audio_manager.stop()
                await ws.send_json({"type": "audio_stopped"})
            elif t == "audio_data":
                audio_manager.on_browser_audio(data.get("data", ""))

    except WebSocketDisconnect:
        pass
    finally:
        async with ws_lock:
            ws_clients.discard(ws)


# ---- 静态文件 ----

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Remote-Quansheng</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=config.get("host", "0.0.0.0"),
                port=config.get("port", 8000), reload=False)

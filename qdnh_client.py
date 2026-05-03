"""QDNH TCP客户端 — 连接Quansheng Dock Network Host

QDNH是运行在电台PC上的TCP桥接服务器:
- 端口 N+1 (默认18823): 串口数据透传
- 端口 N   (默认18822): 音频PCM透传

认证: SHA-256挑战-应答
"""

import asyncio
import hashlib
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class QDNHClient:
    """QDNH TCP客户端"""

    def __init__(self):
        self._host: str = "127.0.0.1"
        self._port: int = 18822
        self._password: str = ""

        self._serial_reader: Optional[asyncio.StreamReader] = None
        self._serial_writer: Optional[asyncio.StreamWriter] = None
        self._audio_reader: Optional[asyncio.StreamReader] = None
        self._audio_writer: Optional[asyncio.StreamWriter] = None

        self._on_serial_data: Optional[Callable] = None
        self._on_audio_data: Optional[Callable] = None
        self._on_disconnect: Optional[Callable] = None

        self._serial_connected: bool = False
        self._audio_connected: bool = False
        self._running: bool = False
        self._serial_read_task: Optional[asyncio.Task] = None
        self._audio_read_task: Optional[asyncio.Task] = None

    @property
    def serial_connected(self) -> bool:
        return self._serial_connected

    @property
    def audio_connected(self) -> bool:
        return self._audio_connected

    @property
    def connected(self) -> bool:
        return self._serial_connected

    def on_serial_data(self, callback: Callable[[bytes], None]):
        self._on_serial_data = callback

    def on_audio_data(self, callback: Callable[[bytes], None]):
        self._on_audio_data = callback

    def on_disconnect(self, callback: Callable[[], None]):
        """注册断开回调（串口断开时触发）"""
        self._on_disconnect = callback

    async def connect(self, host: str = "127.0.0.1", port: int = 18822,
                      password: str = "") -> bool:
        """连接QDNH服务器"""
        # 先断开旧连接
        if self._running:
            await self.disconnect()

        self._host = host
        self._port = port
        self._password = password
        self._running = True

        results = await asyncio.gather(
            self._connect_serial(host, port + 1, password),
            self._connect_audio(host, port, password),
            return_exceptions=True,
        )

        serial_ok = results[0] is True
        audio_ok = results[1] is True

        if not serial_ok:
            logger.error(f"串口连接失败: {results[0]}")
        if not audio_ok:
            logger.warning(f"音频连接失败: {results[1]} (无音频功能)")

        if serial_ok:
            self._serial_read_task = asyncio.ensure_future(self._serial_read_loop())
        if audio_ok:
            self._audio_read_task = asyncio.ensure_future(self._audio_read_loop())

        return serial_ok

    async def _authenticate(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter,
                            password: str) -> bool:
        """SHA-256挑战-应答认证"""
        try:
            salt = await asyncio.wait_for(reader.readexactly(32), timeout=5.0)
            pw_bytes = password.encode("utf-8")
            h = hashlib.sha256(pw_bytes + salt).digest()
            writer.write(h)
            await writer.drain()
            return True
        except asyncio.TimeoutError:
            logger.error("认证超时")
            return False
        except Exception as e:
            logger.error(f"认证失败: {e}")
            return False

    async def _connect_serial(self, host: str, port: int,
                              password: str) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0)
            if not await self._authenticate(reader, writer, password):
                self._safe_close(writer)
                return False
            self._serial_reader = reader
            self._serial_writer = writer
            self._serial_connected = True
            logger.info(f"串口透传已连接 {host}:{port}")
            return True
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
            logger.error(f"串口TCP连接失败 {host}:{port}: {e}")
            self._serial_connected = False
            raise

    async def _connect_audio(self, host: str, port: int,
                             password: str) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0)
            if not await self._authenticate(reader, writer, password):
                self._safe_close(writer)
                return False
            self._audio_reader = reader
            self._audio_writer = writer
            self._audio_connected = True
            logger.info(f"音频透传已连接 {host}:{port}")
            return True
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
            logger.warning(f"音频TCP连接失败 {host}:{port}: {e}")
            self._audio_connected = False
            raise

    @staticmethod
    def _safe_close(writer):
        try:
            writer.close()
        except Exception:
            pass

    async def _serial_read_loop(self):
        """串口数据读取循环"""
        while self._running and self._serial_reader:
            try:
                data = await asyncio.wait_for(
                    self._serial_reader.read(4096), timeout=1.0)
                if not data:
                    logger.warning("QDNH串口连接已断开")
                    break
                if self._on_serial_data:
                    self._on_serial_data(data)
            except asyncio.TimeoutError:
                continue
            except (ConnectionResetError, ConnectionAbortedError,
                    BrokenPipeError, OSError):
                logger.warning("QDNH串口连接异常断开")
                break
            except Exception as e:
                logger.error(f"串口读取错误: {e}")
                break

        self._serial_connected = False
        logger.info("串口读取循环结束")
        # 通知上层
        if self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception:
                pass

    async def _audio_read_loop(self):
        """音频数据读取循环"""
        while self._running and self._audio_reader:
            try:
                data = await asyncio.wait_for(
                    self._audio_reader.read(4096), timeout=1.0)
                if not data:
                    logger.warning("QDNH音频连接已断开")
                    break
                if self._on_audio_data:
                    self._on_audio_data(data)
            except asyncio.TimeoutError:
                continue
            except (ConnectionResetError, ConnectionAbortedError,
                    BrokenPipeError, OSError):
                logger.warning("QDNH音频连接异常断开")
                break
            except Exception as e:
                logger.error(f"音频读取错误: {e}")
                break

        self._audio_connected = False
        logger.info("音频读取循环结束")

    def send_serial(self, data: bytes):
        """发送串口数据（通过TCP透传给电台）"""
        if self._serial_writer and self._serial_connected:
            try:
                self._serial_writer.write(data)
            except Exception:
                pass

    def send_audio(self, data: bytes):
        """发送音频数据（通过TCP透传给电台）"""
        if self._audio_writer and self._audio_connected:
            try:
                self._audio_writer.write(data)
            except Exception:
                pass

    async def disconnect(self):
        """断开所有连接"""
        self._running = False

        # 取消读取任务
        for task in [self._serial_read_task, self._audio_read_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        self._serial_read_task = None
        self._audio_read_task = None

        # 关闭writer（先close，不wait_for_closed，避免Windows Proactor错误）
        for writer in [self._serial_writer, self._audio_writer]:
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass

        self._serial_reader = None
        self._serial_writer = None
        self._audio_reader = None
        self._audio_writer = None
        self._serial_connected = False
        self._audio_connected = False
        logger.info("QDNH连接已断开")

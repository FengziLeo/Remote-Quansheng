"""音频流模块 — QDNH PCM ↔ 浏览器 WebSocket 转发

音频格式: 16-bit PCM, 22050 Hz, mono (与QDNH一致)
使用 asyncio.Queue 实现生产者-消费者模式。
"""

import asyncio
import base64
import logging
import time

logger = logging.getLogger(__name__)

AUDIO_CHUNK = 960  # 每次发送的采样数 (~43.5ms at 22050Hz)
CHUNK_BYTES = AUDIO_CHUNK * 2  # 16-bit = 2 bytes/sample


class AudioStreamManager:
    """QDNH音频流转发器"""

    def __init__(self):
        self._active = False
        self._send_coro = None     # async callable(msg) → 发给浏览器
        self._qdnh_sender = None   # sync callable(pcm_bytes) → 发给QDNH
        self._audio_buffer = bytearray()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._consumer_task = None

        # 诊断计数器
        self._rx_bytes = 0
        self._rx_packets = 0
        self._tx_chunks = 0
        self._tx_errors = 0
        self._start_time = 0.0

    @property
    def active(self) -> bool:
        return self._active

    def set_send_coro(self, coro_func):
        """设置异步发送回调: async def func(msg) -> None"""
        self._send_coro = coro_func

    def set_qdnh_sender(self, sender):
        """设置QDNH音频发送回调: func(pcm_bytes)"""
        self._qdnh_sender = sender

    def start(self):
        """启动音频流转发"""
        self._active = True
        self._audio_buffer.clear()
        self._rx_bytes = 0
        self._rx_packets = 0
        self._tx_chunks = 0
        self._tx_errors = 0
        self._start_time = time.time()

        # 启动消费者任务（不断从队列取数据并发送到浏览器）
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.ensure_future(self._consumer_loop())

        logger.info("音频流转发已启动")

    def stop(self):
        """停止音频流转发"""
        self._active = False

    async def _consumer_loop(self):
        """消费者循环: 从队列取编码后的音频数据, 异步发送到浏览器"""
        while self._active:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if self._send_coro:
                    try:
                        await self._send_coro(msg)
                        self._tx_chunks += 1
                    except Exception as e:
                        self._tx_errors += 1
                        logger.warning(f"音频发送到浏览器失败: {e}")
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"音频消费者异常: {e}")
                await asyncio.sleep(0.1)

    def on_qdnh_audio(self, pcm_data: bytes):
        """QDNH→浏览器: 积累PCM数据, 按块编码后入队"""
        if not self._active or not self._send_coro:
            return

        self._rx_bytes += len(pcm_data)
        self._rx_packets += 1

        self._audio_buffer.extend(pcm_data)
        while len(self._audio_buffer) >= CHUNK_BYTES:
            chunk = bytes(self._audio_buffer[:CHUNK_BYTES])
            self._audio_buffer = self._audio_buffer[CHUNK_BYTES:]
            encoded = base64.b64encode(chunk).decode("ascii")
            try:
                self._queue.put_nowait({"type": "audio_data", "data": encoded})
            except asyncio.QueueFull:
                # 队列满, 丢弃最旧的数据
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self._queue.put_nowait({"type": "audio_data", "data": encoded})
                except Exception:
                    pass

        # 每 10000 个接收包打印一次诊断 (调试用, 默认关闭)
        if self._rx_packets % 10000 == 0 and self._rx_packets > 0:
            elapsed = time.time() - self._start_time
            rate = self._rx_bytes / elapsed / 1024 if elapsed > 0 else 0
            logger.info(
                f"音频诊断: RX={self._rx_packets}包/{self._rx_bytes}B "
                f"({rate:.0f} KB/s) "
                f"TX={self._tx_chunks}块 "
                f"ERR={self._tx_errors} "
                f"buf={len(self._audio_buffer)}B"
            )

    def on_browser_audio(self, b64_data: str):
        """浏览器→QDNH: 解码base64并转发"""
        if not self._active or not self._qdnh_sender:
            return
        try:
            data = base64.b64decode(b64_data)
            self._qdnh_sender(data)
        except Exception as e:
            logger.error(f"浏览器音频解码失败: {e}")

    def get_status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time > 0 else 0
        rate = self._rx_bytes / elapsed / 1024 if elapsed > 0 else 0
        return {
            "active": self._active,
            "rx_packets": self._rx_packets,
            "rx_bytes": self._rx_bytes,
            "rx_rate_kbps": round(rate, 1),
            "tx_chunks": self._tx_chunks,
            "tx_errors": self._tx_errors,
            "consumer_alive": self._consumer_task is not None and not self._consumer_task.done(),
            "buffer_bytes": len(self._audio_buffer),
        }

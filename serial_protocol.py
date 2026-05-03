"""串口协议模块 - 实现QuanshengDock的串口通信协议

协议格式:
  帧: 0xAB 0xCD [LenLSB] [LenMSB] [CmdLSB] [CmdMSB] [PrmLenLSB] [PrmLenMSB] [Data...] [CrcLSB] [CrcMSB] 0xDC 0xBA
  XOR加密: 使用16字节密钥
  CRC: CRC-16-CCITT (多项式 0x1021)
  UI数据包: 以0xB5为前缀, 后续字节: uiType, val1, val2, val3, dataLen, [data...]
"""

import struct
import logging
import asyncio
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

# XOR加密密钥
XOR_ARRAY = bytes([0x16, 0x6c, 0x14, 0xe6, 0x2e, 0x91, 0x0d, 0x40,
                   0x21, 0x35, 0xd5, 0x40, 0x13, 0x03, 0xe9, 0x80])


class PacketCmd:
    Hello           = 0x0514
    ImHere          = 0x0515
    ReadEeprom      = 0x051B
    ReadEepromReply = 0x051C
    WriteEeprom     = 0x051D
    WriteEepromReply= 0x051E
    GetRssi         = 0x0527
    RssiInfo        = 0x0528
    KeyPress        = 0x0801
    GetScreen       = 0x0803
    Scan            = 0x0808
    ScanAdjust      = 0x0809
    ScanReply       = 0x0908
    WriteRegisters  = 0x0850
    ReadRegisters   = 0x0851
    RegisterInfo    = 0x0951
    WriteGPIO       = 0x0860
    ReadGPIO        = 0x0861
    GPIOInfo        = 0x0961
    GPIOPulse       = 0x0862
    EnterHardwareMode = 0x0870
    ExitHardwareMode  = 0x0871
    SetReportReg    = 0x0872


def xor_byte(b: int, pos: int) -> int:
    return b ^ XOR_ARRAY[pos & 15]


def crc16_ccitt(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc <<= 1
            if crc > 0xffff:
                crc ^= 0x1021
                crc &= 0xffff
    return crc


def build_packet(cmd: int, *args) -> bytes:
    """构建数据包"""
    data = bytearray(256)
    data[0] = 0xAB
    data[1] = 0xCD
    data[4] = cmd & 0xFF
    data[5] = (cmd >> 8) & 0xFF

    idx = 8
    for val in args:
        if isinstance(val, list) and all(isinstance(x, int) for x in val):
            for u in val:
                struct.pack_into('<I', data, idx, u)
                idx += 4
        elif isinstance(val, (bytes, bytearray)):
            for b in val:
                data[idx] = b
                idx += 1
        elif isinstance(val, int):
            if abs(val) <= 0xFFFF:
                data[idx] = val & 0xFF
                data[idx + 1] = (val >> 8) & 0xFF
                idx += 2
            else:
                struct.pack_into('<I', data, idx, val)
                idx += 4

    prm_len = idx - 8
    data[6] = prm_len & 0xFF
    data[7] = (prm_len >> 8) & 0xFF

    crc = 0
    xor_cnt = 0
    for i in range(4, idx):
        crc = crc16_ccitt(bytes([data[i]]), crc)
        data[i] = xor_byte(data[i], xor_cnt)
        xor_cnt += 1

    data[idx] = xor_byte(crc & 0xFF, xor_cnt)
    data[idx + 1] = xor_byte((crc >> 8) & 0xFF, xor_cnt + 1)
    idx += 2

    data[idx] = 0xDC
    data[idx + 1] = 0xBA
    idx += 2

    data_len = idx - 8
    data[2] = data_len & 0xFF
    data[3] = (data_len >> 8) & 0xFF

    return bytes(data[:idx])


UiPacketCallback = Callable[[int, int, int, int, int, bytes], Awaitable[None]]


class SerialProtocol:
    """串口协议解析器 — 支持数据包和UI数据包"""

    def __init__(self):
        self._byte_buffer = bytearray()
        self._ui_callbacks: list[UiPacketCallback] = []
        self._cmd_callbacks: dict[int, list[Callable]] = {}
        self._ui_task: Optional[asyncio.Task] = None

    def on_ui_packet(self, callback: UiPacketCallback):
        self._ui_callbacks.append(callback)

    def on_command(self, cmd: int):
        def decorator(fn):
            if cmd not in self._cmd_callbacks:
                self._cmd_callbacks[cmd] = []
            self._cmd_callbacks[cmd].append(fn)
            return fn
        return decorator

    def feed_bytes(self, data: bytes):
        """喂入字节数据，由内部状态机处理"""
        self._byte_buffer.extend(data)
        self._process_buffer()

    def _read_byte(self) -> int:
        """从缓冲区读取一个字节，缓冲区空时返回-1"""
        if self._byte_buffer:
            return self._byte_buffer.pop(0)
        return -1

    def _process_buffer(self):
        """处理缓冲区中的数据"""
        while len(self._byte_buffer) > 0:
            b = self._byte_buffer[0]
            if b == 0xAB:
                result = self._try_parse_packet()
                if result is None:
                    return  # 数据不完整，等待更多
                elif result is False:
                    self._byte_buffer.pop(0)  # 无效，跳过
            elif b == 0xB5:
                result = self._try_parse_ui_packet()
                if result is None:
                    return  # 数据不完整，等待更多
                elif result is False:
                    self._byte_buffer.pop(0)  # 无效数据，跳过
            else:
                self._byte_buffer.pop(0)

    def _try_parse_packet(self):  # -> True=成功, False=无效, None=不完整
        """尝试解析一个数据包。True=成功, False=无效, None=不完整"""
        buf = self._byte_buffer
        if len(buf) < 12:
            return None

        if buf[0] != 0xAB or buf[1] != 0xCD:
            return False

        pkt_len = buf[2] | (buf[3] << 8)
        if pkt_len < 4 or pkt_len > 2048:
            return False

        total = pkt_len + 8
        if len(buf) < total:
            return None  # 等待更多数据

        # 提取数据包并解密
        raw = bytes(buf[:total])
        data = bytearray(pkt_len)

        xor_cnt = 0
        # 解密从索引4开始的数据
        for i in range(4, 4 + pkt_len):
            data[i - 4] = xor_byte(raw[i], xor_cnt)
            xor_cnt += 1

        # 验证CRC
        crc_calc = 0
        for b in data:
            crc_calc = crc16_ccitt(bytes([b]), crc_calc)

        crc_idx = 4 + pkt_len
        crc_recv = xor_byte(raw[crc_idx], xor_cnt) | (xor_byte(raw[crc_idx + 1], xor_cnt + 1) << 8)

        if crc_calc != crc_recv:
            buf.pop(0)
            return False

        # 验证帧尾: 0xDC 0xBA
        if raw[total - 2] != 0xDC or raw[total - 1] != 0xBA:
            buf.pop(0)
            return False

        # 解析命令
        cmd = struct.unpack_from('<H', data, 0)[0]
        if cmd in self._cmd_callbacks:
            for cb in self._cmd_callbacks[cmd]:
                try:
                    cb(data)
                except Exception as e:
                    logger.error(f"命令回调错误 cmd=0x{cmd:04X}: {e}")

        # 从缓冲区移除已解析的字节
        del buf[:total]
        return True

    def _try_parse_ui_packet(self):  # -> True=成功, False=无效, None=不完整
        """尝试解析UI数据包。
        返回 True: 成功解析
        返回 False: 无效数据（应丢弃首字节）
        返回 None: 数据不完整（等待更多数据）
        """
        buf = self._byte_buffer
        if len(buf) < 6:
            return None  # 头部不完整，等待更多数据
        if buf[0] != 0xB5:
            return False  # 不是UI包

        ui_type = buf[1]
        val1 = buf[2]
        val2 = buf[3]
        val3 = buf[4]
        data_len = buf[5]

        header_len = 6
        data_bytes = data_len  # 始终消费 data_len 字节, 避免缓冲区错位
        total = header_len + data_bytes

        if len(buf) < total:
            return None  # 数据不完整，等待更多数据

        ui_data = bytes(buf[header_len:total])

        for cb in self._ui_callbacks:
            try:
                asyncio.ensure_future(
                    cb(ui_type, val1, val2, val3, data_len, ui_data)
                )
            except Exception as e:
                logger.error(f"UI回调错误 type={ui_type}: {e}")

        del buf[:total]
        return True

    def reset(self):
        self._byte_buffer.clear()

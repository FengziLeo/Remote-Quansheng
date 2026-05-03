"""电台控制模块 - 高级无线电控制功能

封装BK4819芯片的寄存器级控制和XVFO操作
频率范围: 0.01 - 1300 MHz
"""

import logging
from serial_protocol import PacketCmd

logger = logging.getLogger(__name__)

# 调制模式
MODULATION_MODES = {
    0: "FM",
    1: "AM",
    2: "USB",
    3: "BYP",
    4: "RAW",
    100: "CW1",
    101: "CW2",
    102: "DTMF",
}

# 带宽设置 (寄存器值)
BANDWIDTHS = {
    "WIDE":  18856,
    "NARROW": 18440,
    "THIN":   13912,
    "UWIDE":  32620,
    "ULOW":   88,
}

BANDWIDTH_NAMES = ["WIDE", "NARROW", "THIN", "UWIDE", "ULOW"]

# 步进值 (MHz)
STEPS = [
    0.00001, 0.00005, 0.00010, 0.00025, 0.00050,
    0.00100, 0.00125, 0.00250, 0.00500, 0.00625,
    0.00833, 0.00900, 0.01000, 0.01250, 0.01500,
    0.02000, 0.02500, 0.03000, 0.05000, 0.10000,
    0.12500, 0.20000, 0.25000, 0.50000,
]

STEP_NAMES = [
    "0.01k", "0.05k", "0.10k", "0.25k", "0.5k",
    "1k", "1.25k", "2.5k", "5k", "6.25k",
    "8.33k", "9k", "10k", "12.5k", "15k",
    "20k", "25k", "30k", "50k", "100k",
    "125k", "200k", "250k", "500k",
]

# 亚音编码类型
TONE_TYPES = {
    0: "NONE",
    1: "CTCSS",
    2: "DCS",
    3: "RDCS",
}

# 标准CTCSS频率 (Hz)
CTCSS_FREQS = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4,
    88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9,
    114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
    151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8,
    250.3, 254.1,
]


class RadioController:
    """电台高级控制器

    管理XVFO模式下的频率、模式、带宽、功率、亚音等设置
    """

    def __init__(self, send_func):
        """
        Args:
            send_func: 发送数据包的回调函数 (cmd, *args)
        """
        self._send = send_func
        self._rx_freq: float = 145.000
        self._tx_freq: float = 145.000
        self._mode: int = 0          # 0=FM, 1=AM, 2=USB, 3=BYP, 4=RAW
        self._bandwidth: int = 0     # 0=WIDE, 1=NARROW, 2=THIN, 3=UWIDE, 4=ULOW
        self._step_idx: int = 12     # 默认10k步进
        self._squelch: float = 30.0
        self._tx_power: float = 100.0
        self._tone_type: int = 0     # 0=NONE, 1=CTCSS, 2=DCS, 3=RDCS
        self._tone_idx: int = 0      # CTCSS频率索引
        self._rx_tone_type: int = 0
        self._rx_tone_idx: int = 0
        self._compander: int = 0     # 0=OFF, 1=RX, 2=TX, 3=BOTH
        self._auto_squelch: int = 0  # 0=手动, 1-4=自动级别
        self._mic_gain: int = 12
        self._vox: bool = False
        self._tx_lock: bool = False
        self._open_squelch: bool = False
        self._tx_is_rx: bool = True
        self._quantizing: bool = False
        self._rf_gain_on: bool = False
        self._rf_gain: int = 21
        self._ready: bool = False
        self._current_rssi: float = 0.0
        self._current_freq: int = 0  # 当前频率原始值 (由 0x38/0x39 寄存器组装)
        self._dtmf_log: str = ""
        self._detected_code: str = ""

        # 寄存器缓存
        self._reg30 = 0
        self._reg31 = 0
        self._reg33 = 0

    @property
    def rx_freq(self) -> float:
        return self._rx_freq

    @property
    def tx_freq(self) -> float:
        return self._tx_freq

    @property
    def mode(self) -> int:
        return self._mode

    @property
    def mode_name(self) -> str:
        return MODULATION_MODES.get(self._mode, "???")

    @property
    def bandwidth_name(self) -> str:
        return BANDWIDTH_NAMES[self._bandwidth] if self._bandwidth < len(BANDWIDTH_NAMES) else "???"

    @property
    def step_name(self) -> str:
        return STEP_NAMES[self._step_idx] if self._step_idx < len(STEP_NAMES) else "???"

    @property
    def step_value(self) -> float:
        return STEPS[self._step_idx] if self._step_idx < len(STEPS) else 0.01

    @property
    def squelch(self) -> float:
        return self._squelch

    @property
    def tx_power(self) -> float:
        return self._tx_power

    @property
    def tone_type_name(self) -> str:
        return TONE_TYPES.get(self._tone_type, "NONE")

    @property
    def ctcss_freq(self) -> float:
        if self._tone_idx < len(CTCSS_FREQS):
            return CTCSS_FREQS[self._tone_idx]
        return 0.0

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def rssi(self) -> float:
        return self._current_rssi

    def get_state(self) -> dict:
        """获取当前所有状态"""
        return {
            "rx_freq": self._rx_freq,
            "tx_freq": self._tx_freq,
            "mode": self._mode,
            "mode_name": self.mode_name,
            "bandwidth": self._bandwidth,
            "bandwidth_name": self.bandwidth_name,
            "step_idx": self._step_idx,
            "step_name": self.step_name,
            "step_value": self.step_value,
            "squelch": self._squelch,
            "tx_power": self._tx_power,
            "tone_type": self._tone_type,
            "tone_type_name": self.tone_type_name,
            "tone_idx": self._tone_idx,
            "ctcss_freq": self.ctcss_freq,
            "rx_tone_type": self._rx_tone_type,
            "rx_tone_idx": self._rx_tone_idx,
            "compander": self._compander,
            "auto_squelch": self._auto_squelch,
            "mic_gain": self._mic_gain,
            "vox": self._vox,
            "tx_lock": self._tx_lock,
            "open_squelch": self._open_squelch,
            "tx_is_rx": self._tx_is_rx,
            "quantizing": self._quantizing,
            "rf_gain_on": self._rf_gain_on,
            "rf_gain": self._rf_gain,
            "ready": self._ready,
            "rssi": self._current_rssi,
            "dtmf_log": self._dtmf_log,
            "detected_code": self._detected_code,
        }

    # ==================== 初始化/释放 ====================

    def enter_xvfo(self):
        """进入XVFO扩展模式"""
        self._send(PacketCmd.EnterHardwareMode)

    def send_hello(self, timestamp: int = 0x12345678):
        """发送Hello握手"""
        self._send(PacketCmd.Hello, timestamp)

    def exit_xvfo(self):
        """退出XVFO模式"""
        self._send(PacketCmd.ExitHardwareMode)
        self._ready = False

    def aquire(self):
        """初始化XVFO：进入硬件模式 + Hello + 读取初始寄存器"""
        self.enter_xvfo()
        self.send_hello()
        self.set_modulation()
        self.set_bandwidth()
        # 读取初始寄存器
        self._send(PacketCmd.ReadRegisters, 7,
                   0x38, 0x39, 0x33, 0x73, 0x30, 0x31, 0)

    # ==================== 频率控制 ====================

    def set_frequency(self, freq_mhz: float):
        """设置接收频率 (MHz)"""
        freq_mhz = max(0.01, min(1300.0, freq_mhz))
        self._rx_freq = freq_mhz
        if self._tx_is_rx:
            self._tx_freq = freq_mhz

        freq = int(round(freq_mhz * 100000))

        self._reg33 &= 0b1111111111100111
        if freq < 28000000:
            self._reg33 |= 0b100
        else:
            self._reg33 |= 0b1000

        self._send(PacketCmd.WriteRegisters, 5,
                   0x38, freq & 0xFFFF,
                   0x39, (freq >> 16) & 0xFFFF,
                   0x33, self._reg33,
                   0x30, 0,
                   0x30, self._reg30)

    def step_up(self):
        """频率步进增加"""
        self.set_frequency(self._rx_freq + self.step_value)

    def step_down(self):
        """频率步进减少"""
        self.set_frequency(self._rx_freq - self.step_value)

    # ==================== 模式/带宽/步进 ====================

    def set_mode(self, mode: int):
        """设置调制模式 0=FM,1=AM,2=USB,3=BYP,4=RAW,100=CW1,101=CW2,102=DTMF"""
        self._mode = mode
        self.set_modulation()

    def set_modulation(self):
        """写入调制模式到芯片"""
        vfom = 2 if self._mode == 100 else 0 if self._mode >= 101 else self._mode
        self._send(0x872, 1, vfom)
        val = 0xbb20 if self._mode >= 100 else 0x3b20
        self._send(PacketCmd.WriteRegisters, 1, 0x50, val)

    def set_bandwidth(self, bw_idx: int = None):
        """设置带宽 0=WIDE,1=NARROW,2=THIN,3=UWIDE,4=ULOW"""
        if bw_idx is not None:
            self._bandwidth = min(4, max(0, bw_idx))
        bw_val = list(BANDWIDTHS.values())[self._bandwidth]
        self._send(PacketCmd.WriteRegisters, 1, 0x43, bw_val)

    def toggle_bandwidth(self):
        """切换带宽"""
        self._bandwidth = (self._bandwidth + 1) % 5
        self.set_bandwidth()

    def set_step(self, idx: int):
        """设置步进索引"""
        self._step_idx = min(len(STEPS) - 1, max(0, idx))

    def toggle_step(self, direction: int):
        """切换步进 +1或-1"""
        self._step_idx = (self._step_idx + direction) % len(STEPS)

    def toggle_mode(self):
        """切换调制模式"""
        mapping = [0, 1, 2, 3, 4, 100, 101]
        try:
            cur = mapping.index(self._mode)
            self._mode = mapping[(cur + 1) % len(mapping)]
        except ValueError:
            self._mode = 0
        self.set_modulation()

    # ==================== 静噪/功率/增益 ====================

    def set_squelch(self, level: float):
        """设置静噪级别 0-100"""
        self._squelch = max(0, min(100, level))

    def toggle_open_squelch(self):
        """切换强制打开静噪（监听）"""
        self._open_squelch = not self._open_squelch

    def set_tx_power(self, pct: float):
        """设置发射功率百分比 0-100"""
        self._tx_power = max(0, min(100, pct))
        freq = int(round(self._tx_freq * 100000))
        pwr = int(self._tx_power * 2.55)
        val = (0x88 if freq < 2800000 else 0xa2) | (pwr << 8)
        self._send(PacketCmd.WriteRegisters, 1, 0x36, val)

    def set_rf_gain(self, enabled: bool, level: int = 21):
        """设置RF增益"""
        self._rf_gain_on = enabled
        self._rf_gain = level

    # ==================== 亚音编码 ====================

    def set_tone_type(self, tone_type: int, tx: bool = True):
        """设置亚音类型 0=NONE,1=CTCSS,2=DCS,3=RDCS"""
        if tx:
            self._tone_type = tone_type
        else:
            self._rx_tone_type = tone_type

    def set_ctcss(self, idx: int, tx: bool = True):
        """设置CTCSS频率索引"""
        if tx:
            self._tone_idx = idx
        else:
            self._rx_tone_idx = idx

    def toggle_tone_type(self, tx: bool = True):
        """循环切换亚音类型"""
        if tx:
            self._tone_type = (self._tone_type + 1) % 4
        else:
            self._rx_tone_type = (self._rx_tone_type + 1) % 4

    # ==================== VOX/PTT/Compander ====================

    def toggle_vox(self):
        """切换VOX"""
        self._vox = not self._vox

    def toggle_compander(self):
        """切换压扩器"""
        self._compander = (self._compander + 1) % 4
        if self._compander == 0:
            self._reg31 &= 0xfff7
            self._send(PacketCmd.WriteRegisters, 1, 0x31, self._reg31)

    def toggle_tx_is_rx(self):
        """切换发射频率跟随接收"""
        self._tx_is_rx = not self._tx_is_rx
        if self._tx_is_rx:
            self._tx_freq = self._rx_freq

    # ==================== 键盘模拟 ====================

    def send_keypress(self, keycode: int):
        """发送按键
        常用键码：
        0-9: 数字键
        10: Menu/Enter
        11: Up
        12: Down
        13: Back/Exit
        14: BAND
        15: A/B
        16: PTT pressed
        19: PTT released
        20: VFO/MR
        21: FC
        22: SL/SR
        23: TX PWR
        24: FM
        25: VOX
        26: R
        27: CALL
        28: F
        29: SCAN
        """
        self._send(PacketCmd.KeyPress, keycode)

    # ==================== EEPROM频道读写 ====================

    def read_eeprom(self, offset: int, size: int):
        """读取EEPROM"""
        self._send(PacketCmd.ReadEeprom, offset, size)

    def write_eeprom(self, offset: int, data: bytes):
        """写入EEPROM"""
        self._send(PacketCmd.WriteEeprom, offset, data)

    # ==================== GPIO控制 ====================

    def gpio_set(self, port: int, pin: int, state: bool):
        """设置GPIO"""
        self._send(PacketCmd.WriteGPIO, port, pin, 1 if state else 0)

    # ==================== 回调处理 ====================

    def handle_register_value(self, register: int, value: int):
        """处理Registernfo回调"""
        if register == 0x00:
            self._rx_freq = (self._current_freq or 14500000) / 100000.0
            if self._tx_is_rx:
                self._tx_freq = self._rx_freq
            self._ready = True
        elif register == 0x30:
            if self._reg30 == 0:
                self._reg30 = value
        elif register == 0x31:
            self._reg31 = value
        elif register == 0x33:
            self._reg33 = value
        elif register == 0x38:
            self._current_freq = value
        elif register == 0x39:
            self._current_freq |= (value << 16)
        elif register == 0x67:
            self._current_rssi = (value & 0x1ff) / 3.2

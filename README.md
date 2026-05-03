# Remote-Quansheng

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![English](https://img.shields.io/badge/Readme-English-blue)](README_EN.md)

> **English**: [README_EN.md](README_EN.md)

基于 Web 的 **Quansheng UV-K5** 电台远程操控面板。通过浏览器远程控制电台，实时 LCD 屏幕同步、双向音频、完整键盘操控。

本项目是 [QuanshengDock](https://github.com/nicsure/QuanshengDock) 生态中的 Web 前端方案，以 [QDNH](https://github.com/nicsure/QDNH) 为后端桥接，实现对 UV-K5 电台的远程操控。无需安装任何桌面软件，打开浏览器即可操作。

> **许可证**：GNU AGPL v3 — 详见 [LICENSE](LICENSE)。  
> 任何使用、修改或以此提供服务者，**必须开源**其全部修改后的源代码。

## 项目架构

```
QDNH.exe (串口 ↔ TCP)            ← 固件桥接后端
    ↓ TCP (端口 18822/18823)
Remote-Quansheng (Python/FastAPI)  ← Web 服务端
    ↓ WebSocket
浏览器 (HTML/JS/CSS)              ← 远程操控面板
```

## 依赖

### 1. 电台固件

UV-K5 电台需刷写 **Quansheng Dock Firmware**：

- [quansheng-dock-fw](https://github.com/nicsure/quansheng-dock-fw)
- 刷写后电台通过串口与后端通信

### 2. AIOC 硬件（或自行改造）

电台与电脑间需要音频/串口转接硬件：

- **推荐方案**：[AIOC (Audio-IO-Control)](https://github.com/nicsure/QuanshengDock#hardware-requirements)
- 或参考 [QuanshengDock 硬件需求](https://github.com/nicsure/QuanshengDock#hardware-requirements) 自行改造电台的 K 头接口

### 3. 后端桥接程序

需要 **QDNH (Quansheng Dock Network Host)** 在本地运行：

- [QDNH](https://github.com/nicsure/QDNH)
- 下载 `QDNH_x64_0.02.01q.exe`（或更新版本）并独立运行
- 配置 COM 端口连接电台，开启 TCP 服务（默认端口 18822）

## 快速开始

### 1. 启动 QDNH 后端

运行 `QDNH.exe`，配置串口连接电台，确保 TCP 端口 18822 已开启。

### 2. 启动 Web 服务器

```bash
pip install -r requirements.txt
python server.py
```

或双击 `start.bat`。

### 3. 打开浏览器

访问 [http://localhost:8000](http://localhost:8000)

## 配置

打开浏览器后点击 **设置** 按钮可配置：

| 配置项 | 说明 |
|--------|------|
| QDNH 地址 | 默认为 `127.0.0.1`（本机） |
| QDNH 端口 | 默认为 `18822` |
| 密码 | 留空则不认证；QDNH 中配置密码后需在此填写 |
| 呼号 | 选填 |
| LCD 背景色 / 前景色 | 自定义屏幕显示颜色 |

## 功能

- LCD 屏幕实时同步渲染（精确对齐 QDNH 协议）
- 音频接收/发射（双向，需麦克风权限）
- 全键盘操控（与 UV-K5 物理布局一致）
- PTT 按键（按住说话）
- 信号强度表、TX/RX/STBY 状态指示、电量显示
- 连接状态监控与自动重连

## TODO

- [ ] 支持 APRS 收发

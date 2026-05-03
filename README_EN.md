# Remote-Quansheng

[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)
[![中文](https://img.shields.io/badge/Readme-中文-green)](README.md)

A web-based **Quansheng UV-K5** radio remote control panel. Control your radio from a browser with real-time LCD sync, bidirectional audio, and full keyboard access.

This project is a Web frontend solution within the [QuanshengDock](https://github.com/nicsure/QuanshengDock) ecosystem. It uses [QDNH](https://github.com/nicsure/QDNH) as the backend bridge to remotely control the UV-K5 transceiver. No desktop software installation required — just open a browser.

> **License**: GNU AGPL v3 — see [LICENSE](LICENSE).  
> Anyone who uses, modifies, or provides a service based on this project **must open source** all modified source code.

## Architecture

```
QDNH.exe (COM8 ↔ TCP)            ← Firmware bridge backend
    ↓ TCP (port 18822/18823)
Remote-Quansheng (Python/FastAPI)  ← Web server
    ↓ WebSocket
Browser (HTML/JS/CSS)            ← Remote control panel
```

## Prerequisites

### 1. Radio Firmware

The UV-K5 radio must be flashed with **Quansheng Dock Firmware**:

- [quansheng-dock-fw](https://github.com/nicsure/quansheng-dock-fw)
- After flashing, the radio communicates over serial (default COM8)

### 2. AIOC Hardware (or DIY modification)

An audio/serial interface between the radio and PC is required:

- **Recommended**: [AIOC (Audio-IO-Control)](https://github.com/nicsure/QuanshengDock#hardware-requirements)
- Alternatively, see [QuanshengDock Hardware Requirements](https://github.com/nicsure/QuanshengDock#hardware-requirements) for DIY modification of the radio's K-head interface

### 3. Backend Bridge (QDNH)

**QDNH (Quansheng Dock Network Host)** must be running on your local machine:

- [QDNH](https://github.com/nicsure/QDNH)
- Download `QDNH_x64_0.02.01q.exe` (or newer) and run it independently
- Configure the COM port to connect to the radio, enable TCP service (default port 18822)

## Quick Start

### 1. Start QDNH Backend

Run `QDNH.exe`, configure the serial port to connect to the radio, and ensure TCP port 18822 is open.

### 2. Start Web Server

```bash
pip install -r requirements.txt
python server.py
```

Or double-click `start.bat`.

### 3. Open Browser

Navigate to [http://localhost:8000](http://localhost:8000)

## Configuration

Click the **Settings** button in the browser to configure:

| Setting | Description |
|---------|-------------|
| QDNH Host | Default `127.0.0.1` (localhost) |
| QDNH Port | Default `18822` |
| Password | Leave empty for no auth; fill if QDNH has a password set |
| Callsign | Optional |
| LCD Background / Foreground | Customize screen color |

## Features

- Real-time LCD screen rendering (aligned precisely with QDNH protocol)
- Bidirectional audio (requires microphone permission)
- Full keyboard control (matching UV-K5 physical layout)
- PTT button (push-to-talk)
- Signal strength meter, TX/RX/STBY status indicator, battery level
- Connection monitoring with auto-reconnect
- Audio stream watchdog with error notification

## TODO

- [ ] APRS transmit / receive support

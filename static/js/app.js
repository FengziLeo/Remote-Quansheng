/* ===== app.js - 主应用逻辑 ===== */
const App = {
  ws: null, connected: false, state: {},
  audioWatchdogTimer: null,
  audioStuckCount: 0,

  _autoAudioReady: false,  // 连接成功后准备自动启动音频, 等待首次用户点击

  init() {
    this.bindUI();
    this.connectWS();
    this.loadSettings().then(() => { this.autoConnect(); });
    LCD.init();
    Keypad.init();
    Audio.init();
    this.startAudioWatchdog();
    // 首次用户点击时自动启动音频（Chrome 要求手势触发 AudioContext）
    document.addEventListener('click', () => this._onFirstClick(), { once: true });
  },

  _onFirstClick() {
    if (this._autoAudioReady && this.connected && !Audio.started) {
      console.log('首次点击, 自动启动音频');
      Audio.start().catch(e => console.warn('自动启动音频失败:', e));
    }
  },

  async autoConnect() {
    const host = document.getElementById('cfg-host').value;
    const port = parseInt(document.getElementById('cfg-port').value);
    if (host && port) {
      console.log('自动连接 QDNH: ' + host + ':' + port);
      const r = await this.api('/api/connect', 'POST', {
        host: host,
        port: port,
        password: document.getElementById('cfg-password').value,
      });
      if (r && r.success) {
        console.log('QDNH 自动连接成功');
        this._autoAudioReady = true;  // 准备就绪, 等待首次点击自动启动
      }
    }
  },

  $ (id) { return document.getElementById(id); },

  /* ---- WebSocket ---- */
  connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws.onopen = () => { console.log('WS connected'); };
    this.ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch(e) { return; }
      try { this.handleMsg(m); } catch(e) { console.error('handleMsg error:', e); }
    };
    this.ws.onclose = () => { setTimeout(() => this.connectWS(), 3000); };
  },

  send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN)
      this.ws.send(JSON.stringify(msg));
  },

  async api(p, m='GET', d=null) {
    try {
      const o = { method: m, headers: {'Content-Type':'application/json'} };
      if (d) o.body = JSON.stringify(d);
      const r = await fetch(p, o);
      return await r.json();
    } catch(e) { console.error(p, e); return null; }
  },

  /* ---- 音频看门狗: 每3秒检查音频是否有数据流入 ---- */
  startAudioWatchdog() {
    this.audioWatchdogTimer = setInterval(() => {
      this.checkAudioStuck();
    }, 3000);
  },

  async checkAudioStuck() {
    if (!Audio.started || !this.connected) {
      this.hideAudioWarning();
      return;
    }
    const d = await this.api('/api/status');
    if (!d || !d.audio) return;
    const a = d.audio;
    // 检查是否有音频数据流入
    const btn = document.getElementById('btn-reconnect-audio');
    if (a.rx_packets > 0) {
      // 音频数据正常
      this.audioStuckCount = 0;
      this.hideAudioWarning();
      if (btn) btn.style.display = 'none';
    } else {
      // 无音频数据
      this.audioStuckCount++;
      if (this.audioStuckCount >= 3) { // 约9秒无数据
        this.showAudioWarning();
        if (btn) btn.style.display = 'inline-block';
      }
    }
    console.log('音频状态: packets=' + a.rx_packets + ' rate=' + a.rx_rate_kbps + ' KB/s');
  },

  showAudioWarning() {
    const el = document.getElementById('audio-warning');
    if (el) el.style.display = 'block';
  },

  hideAudioWarning() {
    const el = document.getElementById('audio-warning');
    if (el) el.style.display = 'none';
  },

  /* ---- 消息处理 ---- */
  handleMsg(m) {
    switch (m.type) {
      case 'connection':
        this.connected = m.connected;
        if (m.reconnecting) {
          this.safeSet('conn-dot', el => { el.className = 'connection-dot'; el.style.background = '#ffaa00'; });
          this.safeSet('quick-info', el => el.textContent = '重连中...');
        } else {
          this.safeSet('conn-dot', el => el.className = 'connection-dot ' + (m.connected ? 'online' : ''));
          this.safeSet('quick-info', el => el.textContent = m.connected ? '已连接' : '未连接');
        }
        if (m.connected) this.safeSet('settings-modal', el => el.classList.add('hidden'));
        this.audioStuckCount = 0;
        break;
      case 'radio_state':
        this.state = m.data || {};
        this.updateStatusBar(this.state);
        break;
      case 'ui_packet':
        LCD.handleUiPacket(m);
        break;
      case 'audio_data':
        Audio.playPcmData(m.data);
        break;
      case 'audio_started':
        Audio.onStarted();
        break;
      case 'audio_stopped':
        Audio.onStopped();
        this.hideAudioWarning();
        break;
      case 'audio_reconnect':
        console.log('音频重连结果:', m.result ? '成功' : '失败');
        break;

    }
  },

  safeSet(id, fn) {
    const el = document.getElementById(id);
    if (el) try { fn(el); } catch(e) {}
  },

  updateStatusBar(s) {
    if (!s) return;
    this.safeSet('s-meter-fill', el => el.style.width = Math.min(100, (s.rssi || 0)) + '%');

    this.safeSet('led-tx', el => {
      if (s.open_squelch) { el.className = 'led-indicator rx'; el.textContent = 'RX'; }
      else if (s.vox)     { el.className = 'led-indicator tx'; el.textContent = 'TX'; }
      else                { el.className = 'led-indicator'; el.textContent = 'STBY'; }
    });

    this.safeSet('battery-level', el => el.style.width = Math.min(100, (s.battery_percent || 75)) + '%');
    this.safeSet('battery-text', el => el.textContent = (s.battery_voltage || 8.0).toFixed(1) + 'V');
  },

  /* ---- UI绑定 ---- */
  bindUI() {
    const $ = (id) => document.getElementById(id);

    $('btn-settings').addEventListener('click', () => {
      $('settings-modal').classList.remove('hidden');
    });
    $('btn-close-modal').addEventListener('click', () => {
      $('settings-modal').classList.add('hidden');
    });

    // 连接
    $('btn-connect').addEventListener('click', async () => {
      $('btn-connect').textContent = '连接中...';
      $('btn-connect').disabled = true;
      try {
        await this.api('/api/connect', 'POST', {
          host: $('cfg-host').value,
          port: parseInt($('cfg-port').value),
          password: $('cfg-password').value,
        });
      } finally {
        $('btn-connect').textContent = '连接 QDNH';
        $('btn-connect').disabled = false;
      }
    });
    $('btn-disconnect').addEventListener('click', () => {
      this.api('/api/disconnect', 'POST');
    });

    // 音频重连
    $('btn-reconnect-audio').addEventListener('click', async () => {
      const btn = $('btn-reconnect-audio');
      btn.textContent = '重连中...';
      btn.disabled = true;
      try {
        await this.api('/api/reconnect-audio', 'POST');
        // 自动重启音频
        Audio.stop();
        await new Promise(r => setTimeout(r, 500));
        Audio.start();
        this.audioStuckCount = 0;
        this.hideAudioWarning();
      } catch(e) {
        console.error('音频重连失败:', e);
      } finally {
        btn.textContent = '🔄 重连音频';
        btn.disabled = false;
      }
    });

    // 保存设置
    $('btn-save-cfg').addEventListener('click', async () => {
      const s = {
        qdnh_host: $('cfg-host').value,
        qdnh_port: parseInt($('cfg-port').value) || 18822,
        qdnh_password: $('cfg-password').value,
        callsign: $('cfg-callsign').value,
        lcd_bg_color: $('cfg-lcd-bg').value,
        lcd_fg_color: $('cfg-lcd-fg').value,
      };
      await this.api('/api/settings', 'POST', s);
      LCD.setColors(s.lcd_bg_color, s.lcd_fg_color);
      $('settings-modal').classList.add('hidden');
    });

    // LCD颜色实时预览
    $('cfg-lcd-bg').addEventListener('input', (e) => {
      LCD.setColors(e.target.value, $('cfg-lcd-fg').value);
    });
    $('cfg-lcd-fg').addEventListener('input', (e) => {
      LCD.setColors($('cfg-lcd-bg').value, e.target.value);
    });

    // 点击弹窗外部关闭
    $('settings-modal').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) e.currentTarget.classList.add('hidden');
    });
  },

  async loadSettings() {
    const d = await this.api('/api/settings');
    if (!d || !d.settings) return;
    const s = d.settings;
    const $ = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    $('cfg-host', s.qdnh_host || '127.0.0.1');
    $('cfg-port', s.qdnh_port || 18822);
    $('cfg-password', s.qdnh_password || '');
    $('cfg-callsign', s.callsign || '');
    $('cfg-lcd-bg', s.lcd_bg_color || '#0a1a0a');
    $('cfg-lcd-fg', s.lcd_fg_color || '#00ff66');
    LCD.setColors(s.lcd_bg_color || '#0a1a0a', s.lcd_fg_color || '#00ff66');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());

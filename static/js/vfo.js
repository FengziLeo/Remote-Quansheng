/* ===== vfo.js - VFO面板控制 ===== */

const VFO = {
  /* CTCSS频率列表 */
  ctcssFreqs: [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4,
    88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2, 110.9,
    114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2,
    151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3, 173.8,
    177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8,
    250.3, 254.1,
  ],

  /* 步进选项 */
  steps: [
    0.00001, 0.00005, 0.00010, 0.00025, 0.00050,
    0.00100, 0.00125, 0.00250, 0.00500, 0.00625,
    0.00833, 0.00900, 0.01000, 0.01250, 0.01500,
    0.02000, 0.02500, 0.03000, 0.05000, 0.10000,
    0.12500, 0.20000, 0.25000, 0.50000,
  ],

  stepNames: [
    "0.01k","0.05k","0.10k","0.25k","0.5k",
    "1k","1.25k","2.5k","5k","6.25k",
    "8.33k","9k","10k","12.5k","15k",
    "20k","25k","30k","50k","100k",
    "125k","200k","250k","500k",
  ],

  init() {
    this.bindStepSelect();
    this.bindToneSelect();
    this.bindEvents();
  },

  bindStepSelect() {
    const sel = document.getElementById('vfo-step');
    sel.innerHTML = this.stepNames.map((n, i) =>
      `<option value="${i}">${n}</option>`).join('');
    sel.value = '12'; // 默认10k
  },

  bindToneSelect() {
    const txSel = document.getElementById('vfo-tx-tone-val');
    const rxSel = document.getElementById('vfo-rx-tone-val');
    const opts = this.ctcssFreqs.map((f, i) =>
      `<option value="${i}">${f.toFixed(1)} Hz</option>`).join('');
    txSel.innerHTML = opts;
    rxSel.innerHTML = opts;
  },

  bindEvents() {
    // 频率输入
    document.getElementById('vfo-rx-freq').addEventListener('change', (e) => {
      const freq = parseFloat(e.target.value);
      if (!isNaN(freq)) App.send({ type: 'set_frequency', freq });
    });
    document.getElementById('vfo-tx-freq').addEventListener('change', (e) => {
      const freq = parseFloat(e.target.value);
      if (!isNaN(freq)) {
        App.send({ type: 'set_frequency', freq, is_tx: true });
      }
    });

    // TX=RX按钮
    document.getElementById('btn-tx-is-rx').addEventListener('click', () => {
      const rxEl = document.getElementById('vfo-rx-freq');
      document.getElementById('vfo-tx-freq').value = rxEl.value;
      App.send({ type: 'set_frequency', freq: parseFloat(rxEl.value) });
    });

    // 步进按钮
    document.getElementById('btn-step-up').addEventListener('click', () => {
      App.api('/api/step-up', 'POST');
    });
    document.getElementById('btn-step-down').addEventListener('click', () => {
      App.api('/api/step-down', 'POST');
    });
    document.getElementById('vfo-step').addEventListener('change', (e) => {
      App.send({ type: 'set_step', index: parseInt(e.target.value) });
    });

    // 模式
    document.getElementById('vfo-mode').addEventListener('change', (e) => {
      App.send({ type: 'set_mode', mode: parseInt(e.target.value) });
    });
    document.getElementById('btn-toggle-mode').addEventListener('click', () => {
      const sel = document.getElementById('vfo-mode');
      const modes = ['0','1','2','3','4'];
      let idx = modes.indexOf(sel.value);
      idx = (idx + 1) % modes.length;
      sel.value = modes[idx];
      sel.dispatchEvent(new Event('change'));
    });

    // 带宽
    document.getElementById('vfo-bandwidth').addEventListener('change', (e) => {
      App.send({ type: 'set_bandwidth', bandwidth: parseInt(e.target.value) });
    });

    // 静噪滑块
    const squelchSlider = document.getElementById('vfo-squelch');
    squelchSlider.addEventListener('input', (e) => {
      document.getElementById('squelch-val').textContent = e.target.value;
    });
    squelchSlider.addEventListener('change', (e) => {
      App.send({ type: 'set_squelch', level: parseInt(e.target.value) });
    });

    // 功率滑块
    const powerSlider = document.getElementById('vfo-power');
    powerSlider.addEventListener('input', (e) => {
      document.getElementById('power-val').textContent = e.target.value;
    });
    powerSlider.addEventListener('change', (e) => {
      App.send({ type: 'set_tx_power', power: parseInt(e.target.value) });
    });

    // 亚音
    document.getElementById('vfo-tx-tone-type').addEventListener('change', (e) => {
      App.send({ type: 'set_tone_type', tone_type: parseInt(e.target.value), tx: true });
    });
    document.getElementById('vfo-rx-tone-type').addEventListener('change', (e) => {
      App.send({ type: 'set_tone_type', tone_type: parseInt(e.target.value), tx: false });
    });
    document.getElementById('vfo-tx-tone-val').addEventListener('change', (e) => {
      App.send({ type: 'set_tone_value', index: parseInt(e.target.value), tx: true });
    });
    document.getElementById('vfo-rx-tone-val').addEventListener('change', (e) => {
      App.send({ type: 'set_tone_value', index: parseInt(e.target.value), tx: false });
    });

    // 快捷控制按钮
    document.querySelectorAll('.quick-controls .btn[data-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const keycode = parseInt(btn.dataset.key);
        if (btn.id === 'btn-ptt') return; // PTT由keypad处理
        if (btn.id === 'btn-monitor') {
          App.send({ type: 'toggle_monitor' });
        } else if (btn.id === 'btn-vox') {
          App.send({ type: 'toggle_vox' });
          App.send({ type: 'keypress', keycode });
        } else {
          App.send({ type: 'keypress', keycode });
        }
      });
    });
  },

  /* 从服务器状态更新VFO面板 */
  updateDisplay(state) {
    document.getElementById('vfo-rx-freq').value = state.rx_freq?.toFixed(5) || '145.00000';
    document.getElementById('vfo-tx-freq').value = state.tx_freq?.toFixed(5) || '145.00000';
    document.getElementById('vfo-mode').value = String(state.mode || 0);
    document.getElementById('vfo-bandwidth').value = String(state.bandwidth || 0);
    document.getElementById('vfo-squelch').value = state.squelch || 30;
    document.getElementById('squelch-val').textContent = Math.round(state.squelch || 30);
    document.getElementById('vfo-power').value = state.tx_power || 100;
    document.getElementById('power-val').textContent = Math.round(state.tx_power || 100);
    document.getElementById('vfo-step').value = String(state.step_idx || 12);
    document.getElementById('vfo-tx-tone-type').value = String(state.tone_type || 0);
    document.getElementById('vfo-rx-tone-type').value = String(state.rx_tone_type || 0);
    document.getElementById('vfo-tx-tone-val').value = String(state.tone_idx || 0);
    document.getElementById('vfo-rx-tone-val').value = String(state.rx_tone_idx || 0);
  },
};

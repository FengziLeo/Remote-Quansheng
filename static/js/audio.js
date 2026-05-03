/* ===== audio.js - Web Audio API 音频 =====
 *
 * QDNH 音频格式: 16-bit PCM, 22050 Hz, mono
 * 浏览器端需要以 22050 Hz 创建 AudioBuffer, 由浏览器自动重采样
 */
const Audio = {
  ctx: null, gain: null, active: false, started: false,
  micStream: null, micProc: null, micActive: false,
  pktCount: 0,

  // QDNH 音频采样率 (固定 22050 Hz)
  QDNH_RATE: 22050,
  // 音频调度时间 (保证连续播放无断裂)
  nextTime: null,

  init() {
    const btn = document.getElementById('btn-audio');
    if (btn) btn.addEventListener('click', () => {
      this.active ? this.stop() : this.start();
    });
  },

  async start() {
    try {
      // AudioContext 必须在用户手势(click)中创建, 否则 Chrome 会阻止
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      console.log('AudioContext 创建: ' + this.ctx.state + ' @' + this.ctx.sampleRate + 'Hz');

      if (this.ctx.state === 'suspended') {
        await this.ctx.resume();
      }
      // 再次检查 — resume() 可能被浏览器阻止
      if (this.ctx.state === 'suspended') {
        throw new Error('AudioContext 被浏览器阻止, 请点击页面后重试');
      }

      this.gain = this.ctx.createGain();
      this.gain.gain.value = 0.8;
      this.gain.connect(this.ctx.destination);

      this.pktCount = 0;
      this.nextTime = null;
      this.active = true;
      this.started = true;
      App.send({ type: 'audio_start' });

      // 可选麦克风
      try { await this.startMic(); } catch(e) {
        console.warn('麦克风不可用, 仅收听模式');
      }

      this.updateUI(true);
    } catch(e) {
      console.error('音频启动失败:', e);
      if (e.message.includes('AudioContext')) {
        alert('音频启动失败: 浏览器阻止了自动播放。\n请点击页面后再点「启动音频」');
      } else {
        alert('音频启动失败: ' + e.message);
      }
      this.cleanup();
    }
  },

  async startMic() {
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount:1, echoCancellation:false, noiseSuppression:false, autoGainControl:false },
      video: false,
    });
    const micSrc = this.ctx.createMediaStreamSource(this.micStream);
    this.micProc = this.ctx.createScriptProcessor(960, 1, 1);
    micSrc.connect(this.micProc);
    this.micProc.connect(this.ctx.destination);
    this.micProc.onaudioprocess = (e) => {
      if (!this.active || !this.micActive) return;
      const input = e.inputBuffer.getChannelData(0);
      const i16 = new Int16Array(input.length);
      for (let i=0; i<input.length; i++)
        i16[i]=Math.max(-32768,Math.min(32767,input[i]*32768));
      const bytes = new Uint8Array(i16.buffer);
      let bin=''; for(let i=0;i<bytes.length;i++) bin+=String.fromCharCode(bytes[i]);
      App.send({type:'audio_data', data:btoa(bin)});
    };
    this.micActive = true;
    console.log('麦克风就绪');
  },

  async playPcmData(b64) {
    if (!this.ctx || !this.active) return;
    try {
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume();
      }

      // Base64 → Int16Array → Float32Array
      const bin = atob(b64);
      if (!bin || bin.length === 0) return;
      const bytes = new Uint8Array(bin.length);
      for (let i=0; i<bin.length; i++) bytes[i]=bin.charCodeAt(i);
      const i16 = new Int16Array(bytes.buffer);
      if (i16.length === 0) return;
      const f32 = new Float32Array(i16.length);
      for (let i=0; i<i16.length; i++) f32[i]=i16[i]/32768;

      // 以 QDNH 采样率 (22050 Hz) 创建 AudioBuffer
      // 浏览器自动重采样到 AudioContext 的实际采样率
      const buf = this.ctx.createBuffer(1, f32.length, this.QDNH_RATE);
      buf.getChannelData(0).set(f32);

      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.gain);

      // 顺序调度: 保证块与块之间连续无断裂
      const now = this.ctx.currentTime;
      if (this.nextTime === null || this.nextTime < now) {
        this.nextTime = now;
      }
      src.start(this.nextTime);
      this.nextTime += f32.length / this.QDNH_RATE;

      this.pktCount++;
      if (this.pktCount <= 5) {
        console.log('音频 #' + this.pktCount +
          ' rate=' + this.QDNH_RATE +
          ' smp=' + f32.length +
          ' t=' + this.nextTime.toFixed(3));
      }
    } catch(e) {
      console.error('Audio playPcmData error:', e);
    }
  },

  updateUI(on) {
    const btn = document.getElementById('btn-audio');
    if (!btn) return;
    btn.textContent = on ? '\u23F9 停止音频' : '\uD83C\uDFA4 启动音频';
    btn.style.background = on ? '#882222' : '';
  },

  onStarted() {
    this.active = true;
    this.updateUI(true);
    console.log('音频流已连接');
  },
  onStopped() { this.updateUI(false); },

  stop() {
    App.send({type:'audio_stop'});
    this.cleanup();
    this.updateUI(false);
  },

  cleanup() {
    this.active = false; this.started = false; this.micActive = false;
    this.nextTime = null;
    if (this.micProc) { try{this.micProc.disconnect();}catch(e){} this.micProc=null; }
    if (this.micStream) { this.micStream.getTracks().forEach(t=>t.stop()); this.micStream=null; }
    if (this.ctx) { this.ctx.close(); this.ctx=null; this.gain=null; }
    this.pktCount = 0;
  },
};

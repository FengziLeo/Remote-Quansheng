/* ===== lcd.js - LCD渲染 =====
 *
 * 完全遵循 QuanshengDock / Comms.cs:
 *   DrawText(col, line, height, text)  → top = line * 64 (C#) / line * LINE_H (前端)
 *   ClearLines(from, to)               → 清除 line*LINE_H 区域
 *
 * 文本 (ui_type 0-3): 服务端 y = 电台线号 + 1 → virtY = y * LINE_H
 *   电台线0 → 前端 y=1 → virtY=1*8=8  (内容第一行)
 * 状态 (ui_type 6):   line=0 → virtY=0
 * 清除 (ui_type 5):   电台线号直传 (0-5) → virtY = 线号 * LINE_H
 *
 * 注意: 文本有 +1 偏移, 电台最后一行(线5)前端在 y=6.
 *   Clear 需扩展一行以覆盖偏移后的最后文本.
 */

const LCD = {
  c: null, ctx: null,
  w: 800, h: 400, dpr: 1,
  bg: '#0a1a0a', fg: '#00ff66',

  VIRT_W: 128,
  VIRT_H: 64,
  LINE_H: 8,   // 每行 8 虚拟像素

  _drawLog: [],

  init() {
    this.c = document.getElementById('lcd-canvas');
    if (!this.c) return;
    this.ctx = this.c.getContext('2d');
    this.resize();
    window.addEventListener('resize', () => { this.resize(); this.replayAll(); });
  },

  resize() {
    const bezel = this.c.parentElement;
    if (!bezel) return;
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    const cssW = bezel.clientWidth - 20;
    this.w = Math.floor(cssW * dpr);
    this.h = Math.floor(this.w / 2);
    this.c.width = this.w;
    this.c.height = this.h;
    this.c.style.width = cssW + 'px';
    this.c.style.height = (cssW / 2) + 'px';
    this.clear();
  },

  scaleX(v) { return (v / this.VIRT_W) * this.w; },
  scaleY(v) { return (v / this.VIRT_H) * this.h; },
  scaleW(v) { return (v / this.VIRT_W) * this.w; },

  clear() { if (!this.ctx) return; this.ctx.fillStyle=this.bg; this.ctx.fillRect(0,0,this.w,this.h); },
  setColors(bg,fg) { this.bg=bg; this.fg=fg; this.clear(); this.replayAll(); },

  replayAll() {
    this.clear();
    this._drawLog.forEach(cmd => { if (!cmd._del) this._exec(cmd); });
  },
  _exec(cmd) {
    switch (cmd.t) {
      case 'text':   this._text(cmd.x,cmd.y,cmd.h,cmd.txt,cmd.b,cmd.k); break;
      case 'scroll': this._scroll(cmd.l,cmd.d); break;
    }
  },

  handleUiPacket(m) {
    try {
      switch (m.subtype) {
        case 'text':
          this._text(m.x, m.y, m.scale, m.text, m.bold, m.thick);
          this._log({t:'text',x:m.x,y:m.y,h:m.scale,txt:m.text,b:m.bold,k:m.thick});
          break;
        case 'clear':   this._clear(m.line_start, m.line_end); break;
        case 'status':  this._status(m.indicators, m.battery_voltage, m.battery_percent, m.code); break;
        case 'scroll':  this._scroll(m.line, m.direction); this._log({t:'scroll',l:m.line,d:m.direction}); break;
        case 'signal':  this._signal(m.level, m.value); break;
      }
    } catch(e) { console.error('LCD:', e); }
  },

  _log(data) {
    data._del = false;
    this._drawLog.push(data);
    if (this._drawLog.length > 200) this._drawLog = this._drawLog.slice(-100);
  },

  /* ========== DrawText ==========
   * top = line * LINE_H  (不做减1, 与 C# line*64 一致)
   *   line=0: 状态栏     top=0
   *   line=1: 第一内容行  top=8
   *   line=6: 最后内容行  top=48
   */
  _text(col, line, height, text, bold, thick) {
    const ctx = this.ctx; if (!ctx) return;
    const virtX = Math.min(126, Math.max(0, col || 0));
    // 限制 line 6 以内 (48+8=56 < 64 ✓)
    const virtY = Math.min(56, Math.max(0, (line || 0) * this.LINE_H));
    const sz = Math.max(3, this.LINE_H * Math.max(0.5, height || 1));
    const px = this.scaleX(virtX);
    const py = this.scaleY(virtY);
    const fs = Math.max(4, Math.round(this.scaleW(sz)));

    ctx.font = `${bold?'bold ':''}${fs}px Consolas,"Courier New",monospace`;
    ctx.textBaseline = 'top';
    const t = String(text||'');
    const tw = Math.ceil(this.scaleW(t.length * sz * 0.65));
    // 擦除背景(仅文字区域)
    ctx.fillStyle = this.bg;
    ctx.fillRect(px, py-1, tw+2, Math.ceil(this.scaleW(sz*1.1)));
    ctx.fillStyle = this.fg;
    ctx.fillText(t, px, py);
    if (thick) ctx.fillText(t, px+Math.round(fs*0.04), py);
  },

  /* ========== ClearLines ==========
   * 状态行(line 0): 由 _status 自清除, clear 只清理日志避免闪烁
   * 内容行(line 1-6): C# i*64, 扩展一行覆盖 +1 偏移
   */
  _clear(a, b) {
    const ctx = this.ctx; if (!ctx) return;
    let from = Math.max(0, a||0);
    let to = Math.min(5, b||a||0);
    if (from > to) return;

    // 状态行由 _status 自管理, 跳过 canvas 清除防闪烁
    if (from === 0) {
      if (to === 0) {
        // clear(0,0): 只清日志, 不碰 canvas
        this._drawLog.forEach(cmd => { if (cmd.t === 'text' && cmd.y === 0) cmd._del = true; });
        return;
      }
      // clear(0,5): 从 line 1 开始清除
      from = 1;
    }
    if (from > to) return;

    // 清到底部时, 直接清到画布底边(覆盖大字号超出部分)
    if (to >= 5) {
      const y1 = this.scaleY(from * this.LINE_H);
      ctx.fillStyle = this.bg;
      ctx.fillRect(0, y1, this.w, this.h - y1);
      const maxY = 7; // 确保覆盖 y=6 及可能的 y=7
      this._drawLog.forEach(cmd => {
        if (cmd.t === 'text' && cmd.y >= from && cmd.y <= maxY) cmd._del = true;
      });
    } else {
      const y1 = this.scaleY(from * this.LINE_H);
      const y2 = this.scaleY((to + 1) * this.LINE_H);
      ctx.fillStyle = this.bg;
      ctx.fillRect(0, y1, this.w, y2 - y1);
      this._drawLog.forEach(cmd => {
        if (cmd.t === 'text' && cmd.y >= from && cmd.y <= to) cmd._del = true;
      });
    }
  },

  /* ========== Status ==========
   * C#: DrawText(col, 0, 0.5, text)
   * 自己清除状态行区域, 不依赖 clear 包——避免闪烁
   */
  _status(ind, bv, bp, code) {
    if (!this.ctx || !ind) return;
    // 删除旧状态行日志
    this._drawLog.forEach(cmd => { if (cmd.t === 'text' && cmd.y === 0) cmd._del = true; });
    // 物理清除状态行 (line 0)
    this.ctx.fillStyle = this.bg;
    this.ctx.fillRect(0, 0, this.w, this.scaleY(this.LINE_H));

    const items = [
      [0,  0.5, ind.tx?'TX':ind.rx?'RX':ind.standby?'SB':''],
      ind.noa   ? [8,  0.5, 'NOA']   : null,
      ind.dtmf  ? [19, 0.5, 'DTMF']  : null,
      ind.fm    ? [33, 0.5, 'FM']    : null,
      code      ? [42, 0.5, String(code)] : null,
      ind.arrow ? [48, 0.5, '<']     : null,
      ind.dwr   ? [56, 0.5, 'DWR']   : null,
      [93, 0.5, `BAT${(bv||0).toFixed(1)}V`],
    ].filter(Boolean);

    items.forEach(([col, ht, txt]) => {
      this._text(col, 0, ht, txt);
      this._log({t:'text',x:col,y:0,h:ht,txt:txt,b:false,k:false});
    });
  },

  _scroll(line, dir) { this._text(0, line, 1, dir==='right'?'>':'<'); },

  _signal(level, over) {
    const el = document.getElementById('s-meter-fill');
    if (el) el.style.width = Math.min(100, (level/15)*100)+'%';
  },
};

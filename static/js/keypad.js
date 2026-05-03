/* ===== keypad.js - UV-K5 正确键盘布局 ===== */
const Keypad = {
  // UV-K5 物理键盘布局:
  // Row1: M/A(10)   ▲/B(11)    ▼/C(12)    EXIT/D(13)
  // Row2: 1/BAND(1) 2/A/B(2)   3/V/M(3)   */SCAN(14)
  // Row3: 4/FC(4)   5/SL/SR(5) 6/TXP(6)   0/FM(0)
  // Row4: 7/VOX(7)  8/R(8)     9/CALL(9)  F/#/Lock(15)
  // PTT(16)
  keys: [
    {label:'M/A', kc:10}, {label:'▲', kc:11},   {label:'▼', kc:12},   {label:'EXIT', kc:13},
    {label:'1', kc:1, sub:'BAND'},  {label:'2', kc:2, sub:'A/B'},  {label:'3', kc:3, sub:'V/M'},  {label:'*', kc:14, sub:'SCAN'},
    {label:'4', kc:4, sub:'FC'},    {label:'5', kc:5, sub:'SL'},   {label:'6', kc:6, sub:'TXP'},  {label:'0', kc:0, sub:'FM'},
    {label:'7', kc:7, sub:'VOX'},   {label:'8', kc:8, sub:'R'},    {label:'9', kc:9, sub:'CALL'}, {label:'F', kc:15, sub:'#', cls:'key-func'},
    {label:'PTT', kc:16, cls:'key-ptt key-wide'},
  ],

  init() {
    const ctr = document.getElementById('keypad');
    ctr.innerHTML = '';

    this.keys.forEach(k => {
      const btn = document.createElement('button');
      btn.className = 'key-btn ' + (k.cls || '');
      btn.innerHTML = k.label + (k.sub ? `<small>${k.sub}</small>` : '');

      if (k.label === 'PTT') {
        btn.addEventListener('mousedown', () => {
          btn.classList.add('pressed');
          App.send({ type: 'toggle_ptt', pressed: true });
        });
        btn.addEventListener('mouseup', () => {
          btn.classList.remove('pressed');
          App.send({ type: 'toggle_ptt', pressed: false });
        });
        btn.addEventListener('mouseleave', () => {
          if (btn.classList.contains('pressed')) {
            btn.classList.remove('pressed');
            App.send({ type: 'toggle_ptt', pressed: false });
          }
        });
        btn.addEventListener('touchstart', (e) => {
          e.preventDefault();
          btn.classList.add('pressed');
          App.send({ type: 'toggle_ptt', pressed: true });
        });
        btn.addEventListener('touchend', (e) => {
          e.preventDefault();
          btn.classList.remove('pressed');
          App.send({ type: 'toggle_ptt', pressed: false });
        });
      } else {
        btn.addEventListener('click', () => {
          btn.classList.add('pressed');
          setTimeout(() => btn.classList.remove('pressed'), 80);
          // 发送按键码（服务端会自动补 key release 19）
          App.send({ type: 'keypress', keycode: k.kc });
        });
      }
      ctr.appendChild(btn);
    });
  },
};

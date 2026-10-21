(() => {
  const script = document.currentScript;
  const service = new URL(script.src).origin;
  const integrate = script.dataset.integrate === 'replica' && location.origin === service;
  if (document.getElementById('iasc-intake-launcher')) return;
  const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = service + '/static/widget.css'; document.head.append(style);
  const launcher = document.createElement('button'); launcher.id = 'iasc-intake-launcher'; launcher.type = 'button';
  launcher.textContent = '✳  Bantu susun laporan'; launcher.setAttribute('aria-expanded','false'); launcher.setAttribute('aria-controls','iasc-intake-panel');
  const panel = document.createElement('section'); panel.id = 'iasc-intake-panel'; panel.hidden = true; panel.setAttribute('aria-label','Asisten penyusunan draft laporan'); panel.setAttribute('role','dialog');
  const header = document.createElement('header');
  const title = document.createElement('span'); title.textContent = 'Asisten AI · Simulasi Lokal';
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','Tutup asisten');
  const frame = document.createElement('iframe'); frame.title = 'Chatbot penyusunan draft laporan';
  frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-downloads allow-forms'); frame.referrerPolicy = 'no-referrer';
  header.append(title,close); panel.append(header,frame); document.body.append(launcher,panel);
  function toggle(open) {
    panel.hidden = !open; launcher.setAttribute('aria-expanded',String(open));
    if (open) { if (!frame.src) frame.src = service + '/widget/iasc-ai-widget.html?embed=1' + (integrate ? '&bridge=1' : ''); close.focus(); }
    else launcher.focus();
  }
  launcher.addEventListener('click', () => toggle(panel.hidden)); close.addEventListener('click', () => toggle(false));
  panel.addEventListener('keydown', event => { if (event.key === 'Escape') toggle(false); });
  window.addEventListener('message',event=>{if(event.source===frame.contentWindow&&event.origin===service&&event.data?.type==='iasc-intake:close')toggle(false);});
  if(new URLSearchParams(location.search).get('assistant')==='1')toggle(true);
  window.addEventListener('message', event => {
    if (!integrate || event.source !== frame.contentWindow || event.origin !== service || !['iasc-intake:apply','iasc-intake:apply-v1'].includes(event.data?.type)) return;
    const data = event.data.data;
    if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).length > 16) return;
    document.dispatchEvent(new CustomEvent(event.data.type, {detail:{data,evidence:event.data.evidence,session_id:event.data.session_id}}));
    toggle(false);
  });
})();

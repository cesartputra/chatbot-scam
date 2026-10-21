(() => {
  const script = document.currentScript;
  const service = new URL(script.src).origin;
  const integrate = script.dataset.integrate === 'replica' && location.origin === service;
  if (document.getElementById('iasc-intake-launcher')) return;
  const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = service + '/static/widget.css'; document.head.append(style);
  const launcher = document.createElement('button'); launcher.id = 'iasc-intake-launcher'; launcher.type = 'button';
  launcher.innerHTML = '<span aria-hidden="true">✦</span><span>Help Center IASC<small>Asisten laporan · Demo lokal</small></span>';
  launcher.setAttribute('aria-expanded','false'); launcher.setAttribute('aria-controls','iasc-intake-panel');
  const panel = document.createElement('section'); panel.id = 'iasc-intake-panel'; panel.hidden = true;
  panel.setAttribute('aria-label','Asisten Help Center IASC, simulasi lokal'); panel.setAttribute('role','dialog');
  const header = document.createElement('header');
  const title = document.createElement('span'); title.innerHTML = '<b>Help Center IASC</b><small><i aria-hidden="true"></i> Asisten siap membantu · Simulasi</small>';
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','Tutup asisten');
  const frame = document.createElement('iframe'); frame.title = 'Percakapan Help Center IASC';
  frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-downloads allow-forms'); frame.referrerPolicy = 'no-referrer';
  header.append(title,close); panel.append(header,frame); document.body.append(launcher,panel);
  function toggle(open) {
    panel.hidden = !open; launcher.setAttribute('aria-expanded',String(open)); document.body.classList.toggle('iasc-assistant-open',open);
    if (open) { if (!frame.src) frame.src = service + '/widget/iasc-ai-widget.html?embed=1' + (integrate ? '&bridge=1' : ''); close.focus(); }
    else launcher.focus();
  }
  launcher.addEventListener('click', () => toggle(panel.hidden)); close.addEventListener('click', () => toggle(false));
  panel.addEventListener('keydown', event => { if (event.key === 'Escape') toggle(false); });
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== service) return;
    if (event.data?.type === 'iasc-intake:close') return toggle(false);
    if (!integrate || event.data?.type !== 'iasc-intake:progress') return;
    const data = event.data;
    if (typeof data.session_id !== 'string' || !Number.isSafeInteger(data.revision) || !Array.isArray(data.dom_patches)) return;
    document.dispatchEvent(new CustomEvent('iasc-intake:progress', {detail:data}));
  });
  document.addEventListener('iasc-intake:progress-applied', event => {
    if (!integrate || !frame.contentWindow) return;
    frame.contentWindow.postMessage({type:'iasc-intake:progress-applied', ...event.detail}, service);
  });
  if (new URLSearchParams(location.search).get('assistant') === '1') toggle(true);
})();

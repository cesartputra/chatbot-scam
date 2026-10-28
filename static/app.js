const $ = (id) => document.getElementById(id);
const PHASES = ['Pihak pelapor', 'Pihak terlapor', 'Kejadian', 'Transaksi', 'Tinjau draft'];
let config, draft, sessionId, busy = false, editing = null, imageUrl = null, evidenceFile = null;
const embedded = location.pathname === '/widget';
if (embedded) document.body.classList.add('embedded');
const bridge = embedded && new URLSearchParams(location.search).get('bridge') === '1';
$('apply-host').hidden = !bridge;

async function api(path, options = {}) {
  const response = await fetch('/api/' + path, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Isian belum sesuai. Periksa kembali.');
  return body;
}
function jsonOptions(method, value) { return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }; }
async function work(action, status = 'Sebentar, sedang memproses…') {
  if (busy) return;
  busy = true; $('error').hidden = true;
  $('assistant-mode').textContent = status;
  for (const button of document.querySelectorAll('button')) button.disabled = true;
  $('message').disabled = true; $('evidence-input').disabled = true; $('reviewed').disabled = true;
  $('composer').classList.add('loading');
  try { await action(); }
  catch (error) { $('error').textContent = error.message || 'Layanan belum merespons. Silakan coba lagi.'; $('error').hidden = false; }
  finally {
    busy = false;
    for (const button of document.querySelectorAll('button')) button.disabled = false;
    $('message').disabled = false; $('evidence-input').disabled = false;
    $('composer').classList.remove('loading');
    if (config) $('assistant-mode').textContent = config.mode === 'remote' ? 'Vision AI + pengisian data terstruktur' : 'OCR + percakapan terarah';
    if (draft) render();
  }
}
function bubble(text, kind = 'assistant', metadata = {}) {
  if (kind === 'user') $('chat').querySelector('.welcome')?.remove();
  const div = document.createElement('div'); div.className = 'bubble ' + kind;
  if (kind === 'assistant') {
    const labels = [];
    if (Array.isArray(metadata.grounded_faq_ids) && metadata.grounded_faq_ids.length) labels.push('📘 Panduan Resmi IASC OJK');
    if (metadata.guardrail_triggered === true) labels.push('🛡️ Fokus Pelaporan IASC');
    for (const label of labels) { const badge = document.createElement('div'); badge.className = 'review-notice'; badge.textContent = label; div.append(badge); }
  }
  div.append(document.createTextNode(text)); $('chat').append(div); $('chat').scrollTop = $('chat').scrollHeight;
}
function welcome() {
  const container = document.createElement('div'); container.className = 'bubble welcome';
  container.innerHTML = '<div class="welcome-icon" aria-hidden="true">✳</div><h3>Kita mulai pelan-pelan.</h3><p>Saya bantu menyiapkan draft laporan Anda.<br>Mulai dengan bukti transfer, atau langsung bercerita.</p><ol><li><span>1</span>Unggah bukti, data transaksi akan dibaca.</li><li><span>2</span>Lengkapi data yang belum tersedia lewat chat.</li><li><span>3</span>Periksa ringkasan, lalu unduh draft Anda.</li></ol><button type="button" class="demo-button" id="demo">Coba bukti transfer dummy <span>↗</span></button><p class="welcome-foot">Contoh fiktif tersedia. Tidak ada transaksi atau laporan nyata.</p>';
  $('chat').append(container); $('demo').addEventListener('click', demo);
}
function displayValue(field, value) {
  if (value == null) return field.required ? 'Belum diisi' : 'Opsional · belum diisi';
  if (field.key === 'nominal') return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value);
  if (field.key === 'kategori_modus') return config.choices[value] || value;
  if (field.key === 'waktu_transaksi') return new Intl.DateTimeFormat('id-ID', {dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Jakarta'}).format(new Date(value)) + ' WIB';
  return String(value);
}
function render() {
  const required = config.fields.filter(f => f.required);
  const filled = required.length - draft.missing.length;
  $('progress-text').textContent = `${filled} / ${required.length}`;
  $('progress').max = required.length; $('progress').value = filled;
  const currentPhase = draft.missing.length ? config.fields.find(f => f.key === draft.missing[0]).phase : 5;
  $('phases').replaceChildren();
  PHASES.forEach((label, index) => {
    const phase = index + 1;
    const fields = config.fields.filter(f => f.phase === phase && f.required);
    const done = phase < 5 && fields.every(f => draft.data[f.key] != null);
    const li = document.createElement('li'); li.className = done ? 'done' : (phase === currentPhase ? 'active' : '');
    if (phase === currentPhase) li.setAttribute('aria-current', 'step');
    const number = document.createElement('span'); number.className = 'phase-number'; number.textContent = done ? '✓' : phase;
    const text = document.createElement('span'); text.textContent = label; li.append(number, text); $('phases').append(li);
  });
  $('field-list').replaceChildren();
  PHASES.slice(0, 4).forEach((phaseLabel, index) => {
    const group = document.createElement('div'); group.className = 'field-group';
    const title = document.createElement('h3'); title.textContent = `${String(index+1).padStart(2,'0')} / ${phaseLabel}`; group.append(title);
    config.fields.filter(f => f.phase === index + 1).forEach(field => {
      const row = document.createElement('div'); row.className = 'field-row' + (draft.data[field.key] == null ? ' empty' : '');
      const details = document.createElement('div');
      const label = document.createElement('div'); label.className = 'label'; label.textContent = field.label;
      const source = draft.sources[field.key];
      if (source) { const tag = document.createElement('span'); tag.className = 'source ' + source; tag.textContent = source === 'ai' ? 'AI · cek' : source === 'ocr' ? 'OCR · cek' : source; label.append(tag); }
      const value = document.createElement('div'); value.className = 'value'; value.textContent = displayValue(field, draft.data[field.key]);
      details.append(label, value);
      const edit = document.createElement('button'); edit.textContent = '↗'; edit.setAttribute('aria-label', 'Edit ' + field.label); edit.addEventListener('click', () => openEdit(field)); edit.disabled = busy;
      row.append(details, edit); group.append(row);
    });
    $('field-list').append(group);
  });
  $('json-output').textContent = JSON.stringify({schema_version:'poc-0.1',mode:'DRAFT_ONLY',submitted:false,data:draft.data}, null, 2);
  $('reviewed').disabled = busy || draft.missing.length > 0;
  $('download').disabled = busy || draft.missing.length > 0 || !$('reviewed').checked;
  $('apply-host').disabled = busy || !Object.values(draft.data).some(value => value != null);
  $('review-help').textContent = draft.missing.length ? `${draft.missing.length} data inti lagi. Anda bisa mengedit isian kapan saja.` : 'Data inti lengkap. Periksa seluruh isian sebelum mengunduh.';
  $('quick-replies').replaceChildren();
  if (draft.missing.length) {
    const field = config.fields.find(f => f.key === draft.missing[0]);
    const examples = field.key === 'kategori_modus' ? Object.keys(config.choices) : [field.example];
    for (const example of examples) {
      const button = document.createElement('button');
      button.textContent = field.key === 'kategori_modus' ? config.choices[example] : 'Isi contoh: ' + (example.length > 35 ? 'kronologi dummy' : example);
      button.disabled = busy; button.addEventListener('click', () => sendMessage(example)); $('quick-replies').append(button);
    }
    $('message').placeholder = field.key === 'waktu_transaksi' ? 'Contoh: 2026-10-19 10:00' : 'Tulis jawaban Anda…';
  }
  const faqs = Array.isArray(draft.faq_quick_asks) ? draft.faq_quick_asks : [];
  for (const faq of faqs.filter(item => typeof item?.label === 'string' && typeof item.text === 'string' && item.text.trim()).slice(0,2)) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = faq.label;
    button.disabled = busy; button.addEventListener('click', () => sendMessage(faq.text)); $('quick-replies').append(button);
  }
  $('evidence-count').textContent = draft.evidence ? '1' : '0';
  $('evidence-empty').hidden = !!draft.evidence;
  $('evidence-result').hidden = !draft.evidence;
  if (draft.evidence) $('ocr-text').textContent = draft.evidence.text;
}
function adopt(next) { draft = next; $('reviewed').checked = false; render(); }
async function sendMessage(text) {
  text = text.trim(); if (!text) return;
  await work(async () => {
    const next = await api(`sessions/${sessionId}/messages`, jsonOptions('POST', { text }));
    bubble(text, 'user'); adopt(next); bubble(next.reply, 'assistant', next); $('message').value = '';
  });
}
async function upload(file, name = file.name) {
  if (!file) return;
  await work(async () => {
    if (file.size > 3*1024*1024) throw new Error('Ukuran gambar maksimum 3 MB.');
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('Pilih gambar PNG, JPG, atau WebP.');
    const next = await api(`sessions/${sessionId}/evidence`, {method:'POST',headers:{'Content-Type':file.type},body:file});
    if (imageUrl) URL.revokeObjectURL(imageUrl); imageUrl = URL.createObjectURL(file); evidenceFile = file; $('evidence-preview').src = imageUrl;
    bubble('▧ ' + name, 'user'); adopt(next); bubble(next.reply, 'assistant', next); selectTab('data');
  }, 'Membaca bukti transfer…');
  $('evidence-input').value = '';
}
async function demo() {
  if (busy) return;
  try {
    const response = await fetch('/fixtures/bukti-dummy.png'); if (!response.ok) throw new Error('Contoh bukti belum tersedia.');
    await upload(new File([await response.blob()], 'bukti-transfer-dummy.png', {type:'image/png'}));
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
}
function openEdit(field) {
  if (busy) return;
  editing = field;
  $('edit-title').textContent = 'Periksa & koreksi'; $('edit-label').textContent = field.label;
  $('edit-value').type = ['email','tel','datetime-local'].includes(field.type) ? field.type : 'text';
  $('edit-value').hidden = field.type === 'select'; $('edit-category').hidden = field.type !== 'select';
  const value = draft.data[field.key];
  $('edit-value').value = field.key === 'waktu_transaksi' && value ? value.slice(0,16) : (value ?? '');
  $('edit-category').value = value || '';
  $('edit-hint').textContent = field.required ? 'Isian inti. Kosongkan untuk menghapus nilainya.' : 'Isian opsional. Boleh dikosongkan.';
  $('edit-dialog').showModal();
}
function selectTab(name) {
  for (const button of document.querySelectorAll('[data-tab]')) {
    const selected = button.dataset.tab === name; button.setAttribute('aria-selected', selected); button.tabIndex = selected ? 0 : -1;
    $(button.dataset.tab + '-view').hidden = !selected;
  }
}
document.querySelectorAll('[data-tab]').forEach(button => {
  button.addEventListener('click', () => selectTab(button.dataset.tab));
  button.addEventListener('keydown', event => {
    const names = ['data','evidence','json']; let index = names.indexOf(button.dataset.tab);
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault(); index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    selectTab(names[index]); $('tab-' + names[index]).focus();
  });
});
$('composer').addEventListener('submit', event => { event.preventDefault(); sendMessage($('message').value); });
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('composer').requestSubmit(); } });
$('evidence-input').addEventListener('change', event => upload(event.target.files[0]));
$('upload-secondary').addEventListener('click', () => $('evidence-input').click());
$('reviewed').addEventListener('change', () => render());
for (const id of ['close-edit','cancel-edit']) $(id).addEventListener('click', () => $('edit-dialog').close());
$('edit-form').addEventListener('submit', event => {
  event.preventDefault();
  const field = editing, value = field.type === 'select' ? $('edit-category').value : $('edit-value').value;
  work(async () => {
    const next = await api(`sessions/${sessionId}`, jsonOptions('PATCH', { values: { [field.key]: value || null } }));
    adopt(next); $('edit-dialog').close(); bubble(field.label + ' sudah diperbarui.');
  }).then(() => { if (!$('error').hidden && $('edit-dialog').open) { $('edit-hint').textContent = $('error').textContent; } });
});
$('download').addEventListener('click', () => work(async () => {
  const payload = await api(`sessions/${sessionId}/draft`, jsonOptions('POST',{reviewed:$('reviewed').checked}));
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)], {type:'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'iasc-draft-dummy.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  bubble('Draft JSON sudah diunduh. Tidak ada laporan yang dikirim dan tidak ada rekening yang diblokir.');
}));
$('reset').addEventListener('click', () => work(async () => {
  const next = await api('sessions', {method:'POST'});
  const oldSession = sessionId; sessionId = next.session_id;
  adopt(next); $('chat').replaceChildren(); welcome();
  if (imageUrl) URL.revokeObjectURL(imageUrl); imageUrl = null; evidenceFile = null; $('evidence-preview').removeAttribute('src');
  selectTab('data');
  // Keep the new session usable even if deletion of an expired old session returns 404.
  await api(`sessions/${oldSession}`, {method:'DELETE'}).catch(() => {});
}));
$('apply-host').addEventListener('click', () => {
  if (bridge && !busy && window.parent !== window) window.parent.postMessage({type:'iasc-intake:apply',data:draft.data,evidence:evidenceFile},location.origin);
});
work(async () => {
  config = await api('config');
  for (const [value, label] of Object.entries({'':'Pilih kategori',...config.choices})) {
    const option = document.createElement('option'); option.value = value; option.textContent = label; $('edit-category').append(option);
  }
  const next = await api('sessions', {method:'POST'}); sessionId = next.session_id; adopt(next); welcome();
  $('engine').textContent = config.mode === 'remote' ? 'AI Gateway aktif' : 'OCR lokal';
  $('assistant-mode').textContent = config.mode === 'remote' ? 'Vision AI + pengisian data terstruktur' : 'OCR + percakapan terarah';
  $('privacy-note').textContent = config.mode === 'remote' ? 'Mode remote · data diteruskan ke AI Gateway terkonfigurasi' : 'Diproses lokal · gambar dihapus setelah OCR';
  if (!config.ocr_available && config.mode === 'local') bubble('OCR belum tersedia di server ini. Anda tetap bisa mengisi data lewat chat atau tombol edit.');
});

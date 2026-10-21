import {localDate, amount, fileError, emptyReport} from './report-core.mjs';

const FORBIDDEN = new Set(['__proto__', 'prototype', 'constructor']);
const ONE = {apakah_mengalami_sendiri:'pelapor.sendiri', jenis_kelamin:'pelapor.jenis_kelamin', kewarganegaraan_pelapor:'pelapor.kewarganegaraan', nama_pelapor:'pelapor.nama', tempat_lahir_pelapor:'pelapor.tempat_lahir', tanggal_lahir_pelapor:'pelapor.tanggal_lahir', agama_pelapor:'pelapor.agama', pekerjaan_pelapor:'pelapor.pekerjaan', kode_negara_telepon_pelapor:'pelapor.kode_telepon', nomor_telepon_pelapor:'pelapor.telepon', konfirmasi_nomor_telepon_pelapor:'pelapor.konfirmasi_telepon', email_pelapor:'pelapor.email', konfirmasi_email_pelapor:'pelapor.konfirmasi_email', jenis_identitas:'pelapor.jenis_identitas', nomor_identitas:'pelapor.nomor_identitas', provinsi_domisili_pelapor:'pelapor.provinsi', kota_domisili_pelapor:'pelapor.kota', alamat_pelapor:'pelapor.alamat', upload_kartu_identitas_korban:'files.identitas'};
const THREE = {tanggal_dan_waktu_kejadian:'kejadian.tanggal', kronologi_kejadian_penipuan:'kejadian.kronologi', upload_bukti_pendukung_kejadian:'files.kejadian', upload_laporan_kepolisian:'files.polisi'};
const FOUR = {nama_penyelenggara_layanan_korban:'transaksi.bank', nomor_rekening_akun_korban:'transaksi.rekening', nama_pemilik_rekening_akun_korban:'transaksi.nama', bukti_kepemilikan_rekening_akun_korban:'files.rekening'};
const TERLAPOR = {kode_nomor_terlapor:'kode', nomor_terlapor:'nomor', nama_terlapor:'nama', upload_bukti_komunikasi:'file'};
const MEDIA = {sumber_media_informasi_penipuan:'sumber', detail_sumber_media_informasi_penipuan:'detail', upload_bukti_sumber_media:'file'};
const BANK = {nama_penyelenggara:'bank', nomor_rekening_akun:'rekening', nama_pemilik_rekening_akun:'nama'};
const DETAIL = {waktu_transaksi:'waktu', nominal_transaksi:'nominal', upload_bukti_pendukung_kejadian:'file'};
const read = (object, path) => path.split('.').reduce((value, key) => value?.[key], object);

export function simulationResult(result) {
  return Boolean(result && result.simulated === true && result.submitted === false && /^SIM-[A-Za-z0-9_-]{1,100}$/.test(result.ticket_number || ''));
}
export function sessionFileUrl(meta, sessionId, origin) {
  if (!meta || typeof meta !== 'object' || !/^[A-Za-z0-9_-]{16,128}$/.test(sessionId || '')) return null;
  try {
    const url = new URL(meta.url || '', origin);
    if (url.origin !== origin || url.search || url.hash || url.username || url.password || ![url.pathname, url.origin + url.pathname].includes(meta.url)) return null;
    const prefix = '/api/v1/session/' + sessionId + '/files/';
    if (!url.pathname.startsWith(prefix) || !/^[A-Za-z0-9_-]{16,128}$/.test(url.pathname.slice(prefix.length))) return null;
    if (meta.file_id && url.pathname.slice(prefix.length) !== meta.file_id) return null;
    return url.href;
  } catch { return null; }
}
export function mapCanonicalPatch(patch) {
  if (!patch || patch.op !== 'set' || typeof patch.path !== 'string' || patch.path.length > 250) return null;
  const parts = patch.path.replace(/\[(\d+)\]/g, '.$1').split('.');
  if (parts.some(part => FORBIDDEN.has(part) || !/^[A-Za-z_][A-Za-z0-9_]*$|^(?:0|[1-9]\d?)$/.test(part))) return null;
  const step = Number(parts[0]?.slice(5));
  let path, list = null, index = null, detail = null;
  if (parts.length === 2) {
    path = ({1:ONE, 3:THREE, 4:FOUR, 5:{setuju_syarat_dan_ketentuan:'reviewed', captcha_question:'captcha_question', captcha_answer:'captcha_answer'}}[step] || {})[parts[1]];
  } else if (step === 2 && parts.length === 4 && /^\d+$/.test(parts[2])) {
    list = parts[1] === 'daftar_informasi_terlapor' ? 'terlapor' : parts[1] === 'daftar_sumber_media_penipuan' ? 'media' : null;
    index = Number(parts[2]);
    const key = (list === 'terlapor' ? TERLAPOR : list === 'media' ? MEDIA : {})[parts[3]];
    if (key && list) path = `${list}.${index}.${key}`;
  } else if (step === 4 && parts[1] === 'daftar_penyelenggara_terlapor' && /^\d+$/.test(parts[2] || '')) {
    list = 'transaksi.penerima'; index = Number(parts[2]);
    if (parts.length === 4 && BANK[parts[3]]) path = `${list}.${index}.${BANK[parts[3]]}`;
    if (parts.length === 6 && parts[3] === 'daftar_rincian_transaksi' && /^\d+$/.test(parts[4]) && DETAIL[parts[5]]) {
      detail = Number(parts[4]); path = `${list}.${index}.details.${detail}.${DETAIL[parts[5]]}`;
    }
  }
  if (!path || index >= 50 || detail >= 50) return null;
  let value = patch.value;
  const file = path.startsWith('files.') || path.endsWith('.file');
  if (file) { if (value !== null && (!value || typeof value !== 'object' || Array.isArray(value))) return null; }
  else if (path === 'reviewed') { if (typeof value !== 'boolean') return null; }
  else {
    if (typeof value !== 'string' && !(path.endsWith('.nominal') && typeof value === 'number')) return null;
    if (String(value).length > 4000) return null;
    value = typeof value === 'string' ? value.trim() : value;
    if (path === 'pelapor.sendiri') { if (!['Ya, saya sendiri', 'Tidak, saya mewakili korban'].includes(value)) return null; value = value.startsWith('Ya') ? 'ya' : 'tidak'; }
    if (path.endsWith('.kode') || path === 'pelapor.kode_telepon') value = value.match(/\+\d{1,4}/)?.[0] || value;
    if (path === 'pelapor.tanggal_lahir') value = localDate(value);
    if (path === 'kejadian.tanggal' || path.endsWith('.waktu')) value = localDate(value, true);
    if (path.endsWith('.nominal')) {
      if (typeof value === 'string' && /^\d+(\.\d{1,2})?$/.test(value)) value = Number(value);
      value = amount(value); if (value === null) return null;
    }
  }
  return {path, value, step, list, index, detail, file, canonicalPath:parts.join('.')};
}

export function flattenPatches(patches) {
  if (!Array.isArray(patches) || patches.length > 300) throw new Error('Daftar perubahan formulir tidak valid.');
  const output = [];
  const visit = (path, value, depth = 0) => {
    if (output.length >= 300 || depth > 8) throw new Error('Daftar perubahan formulir terlalu besar.');
    const patch = {op:'set', path, value};
    if (mapCanonicalPatch(patch)) { output.push(patch); return; }
    if (value && typeof value === 'object') for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN.has(key)) throw new Error('Jalur perubahan formulir tidak aman.');
      visit(path + '.' + key, child, depth + 1);
    }
  };
  for (const patch of patches) {
    if (!patch || patch.op !== 'set' || typeof patch.path !== 'string') throw new Error('Perubahan formulir tidak dikenali.');
    if (patch.path.split('.').some(key => FORBIDDEN.has(key))) throw new Error('Jalur perubahan formulir tidak aman.');
    visit(patch.path, patch.value);
  }
  return output;
}

export function createProgressState() { return {sessionId:null, revision:-1, manual:new Set(), auto:new Map(), rows:new Map(), details:new Map(), retired:new Set()}; }
export function resetProgressReport(report, state) {
  const defaults = emptyReport();
  const locked = path => [...state.manual].some(key => path === key || path.startsWith(key + '.'));
  const lists = ['terlapor', 'media', 'transaksi.penerima'];
  for (const [path, value] of state.auto) {
    if (lists.some(list => path.startsWith(list + '.'))) continue;
    if (read(report, path) !== value) state.manual.add(path);
    if (!locked(path)) assign(report, path, read(defaults, path));
  }
  for (const list of lists) {
    const owned = new Set([...state.rows].filter(([key]) => key.startsWith(list + '.')).map(([, index]) => index));
    const previous = read(report, list), kept = [], indices = new Map();
    previous.forEach((row, index) => {
      const prefix = list + '.' + index;
      const changed = [...state.auto].some(([path, value]) => path.startsWith(prefix + '.') && read(report, path) !== value);
      const manual = locked(prefix) || [...state.manual].some(path => path.startsWith(prefix + '.')) || changed;
      if (!owned.has(index) || manual) { indices.set(index, kept.length); kept.push(row); }
      if (changed) state.manual.add(prefix);
    });
    assign(report, list, kept);
    const manual = new Set();
    for (const path of state.manual) {
      if (!path.startsWith(list + '.')) { manual.add(path); continue; }
      const rest = path.slice(list.length + 1), [rawIndex] = rest.split('.'), index = Number(rawIndex);
      if (indices.has(index)) manual.add(list + '.' + indices.get(index) + rest.slice(rawIndex.length));
    }
    state.manual = manual;
  }
  report.reviewed = false;
}
export function acceptProgress(state, message) {
  if (!message || !/^[A-Za-z0-9_-]{16,128}$/.test(message.session_id || '') || !Number.isSafeInteger(message.revision) || message.revision < 0 || !Number.isInteger(message.active_wizard_step) || message.active_wizard_step < 1 || message.active_wizard_step > 5) return false;
  if (state.retired.has(message.session_id)) return false;
  if (state.sessionId && state.sessionId !== message.session_id) { state.retired.add(state.sessionId); state.revision = -1; state.auto.clear(); state.rows.clear(); state.details.clear(); }
  if (message.revision <= state.revision) return false;
  state.sessionId = message.session_id;
  return true;
}
function assign(object, path, value) {
  const keys = path.split('.'); let target = object;
  for (const key of keys.slice(0, -1)) target = target[key];
  target[keys.at(-1)] = value;
}
export function applyProgressPatch(report, patch, state, {resolveFile = () => null, result = null} = {}) {
  const mapped = mapCanonicalPatch(patch);
  if (!mapped) return {applied:false, reason:'invalid'};
  if ((mapped.path === 'reviewed' || mapped.path === 'captcha_answer') && !simulationResult(result)) return {applied:false, reason:'consent'};
  let path = mapped.path;
  if (mapped.list) {
    if (state.manual.has(mapped.list)) return {applied:false, reason:'manual', path};
    const key = mapped.list + '.' + mapped.index;
    if (!state.rows.has(key)) {
      const rows = read(report, mapped.list);
      state.rows.set(key, rows.length);
      rows.push(mapped.list === 'terlapor' ? {kode:'', nomor:'', nama:'', file:null} : mapped.list === 'media' ? {sumber:'', detail:'', file:null} : {bank:'', rekening:'', nama:'', details:[]});
    }
    const localIndex = state.rows.get(key);
    path = path.replace(mapped.list + '.' + mapped.index, mapped.list + '.' + localIndex);
    if (mapped.detail !== null) {
      const details = report.transaksi.penerima[localIndex].details;
      const detailKey = key + '.' + mapped.detail;
      if (!state.details.has(detailKey)) { state.details.set(detailKey, details.length); details.push({waktu:'', nominal:'', file:null}); }
      path = path.replace('.details.' + mapped.detail + '.', '.details.' + state.details.get(detailKey) + '.');
    }
  }
  const current = read(report, path);
  if (state.manual.has(path)) return {applied:false, reason:'manual', path, proposed:mapped.value, current};
  if (state.auto.has(path) && current !== state.auto.get(path)) return {applied:false, reason:'manual', path, proposed:mapped.value, current};
  let value = mapped.value;
  if (mapped.file && value !== null) { value = resolveFile(value); if (!value || fileError(value, path === 'files.identitas' ? 1 : 2)) return {applied:false, reason:'file', path}; }
  if (current === value) return {applied:false, reason:'unchanged', path, step:mapped.step};
  assign(report, path, value); state.auto.set(path, value);
  if (path !== 'reviewed' && path !== 'captcha_answer' && path !== 'captcha_question') report.reviewed = false;
  return {applied:true, path, value, step:mapped.step};
}

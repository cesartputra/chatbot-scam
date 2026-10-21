import {PHASES,BANKS,CITIES,PELAPOR_FIELDS,emptyReport,amount,amountInput,fileError,validatePhase,validateRecord,metadata,applyChat,applyChatV1,referencesFile} from './report-core.mjs';

const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const report=emptyReport();
let phase=1, highest=1, recordType=null, recordIndex=null, recordDraft=null, candidate={}, latestPayload=null;
const expires=Date.now()+60*60*1000;
const get=(object,path)=>path.split('.').reduce((value,key)=>value?.[key],object);
function set(object,path,value){const keys=path.split('.');if(keys.some(k=>['__proto__','constructor','prototype'].includes(k)))return;let target=object;for(const key of keys.slice(0,-1))target=target[key];target[keys.at(-1)]=value;}
function options(values,current,placeholder='-- Pilih --'){
  const all=[...new Set([...(values||[]),...(current&&!values?.includes(current)?[current]:[])])];
  return `<option value="">${esc(placeholder)}</option>`+all.map(value=>`<option value="${esc(value)}" ${value===current?'selected':''}>${esc(value)}</option>`).join('');
}
function field(path,label,type='text',values=null,required=true,object=report){
  const raw=get(object,path)??'',value=path.endsWith('.nominal')?amountInput(raw):raw, id='field-'+path.replaceAll('.','-');
  let control;
  if(type==='textarea')control=`<textarea class="form-control" id="${id}" data-field="${path}" rows="3" maxlength="4000">${esc(value)}</textarea>`;
  else if(type==='select')control=`<select class="form-select" id="${id}" data-field="${path}">${options(values,value,'-- Pilih '+label.replace(' Pelapor','')+' --')}</select>`;
  else if(type==='phone'){
    const code=path.endsWith('konfirmasi_telepon')?'konfirmasi_kode_telepon':'kode_telepon';
    control=`<div class="phone-input"><select class="form-select" data-field="pelapor.${code}" aria-label="Kode ${esc(label)}">${['+62','+60','+65','+1','+61'].map(c=>`<option value="${c}" ${report.pelapor[code]===c?'selected':''}>${{'+62':'Indonesia','+60':'Malaysia','+65':'Singapura','+1':'Amerika Serikat','+61':'Australia'}[c]} (${c})</option>`).join('')}</select><input class="form-control" type="tel" id="${id}" data-field="${path}" value="${esc(value)}" maxlength="15"></div><div class="form-text">Contoh: 81234567890</div>`;
  } else if(type==='city'){
    const cities=CITIES[report.pelapor.provinsi]||[];
    control=`<select class="form-select" id="${id}" data-field="${path}">${options(cities,value,'-- Pilih Kota --')}<option value="__manual__">Kota lainnya (isi manual)</option></select>`;
  } else control=`<input class="form-control" id="${id}" data-field="${path}" type="${type}" value="${esc(value)}" ${type==='date'?'max="'+new Date().toLocaleDateString('en-CA')+'"':''} maxlength="${type==='email'?200:500}">`;
  return `<div class="field"><label class="form-label" for="${id}">${esc(label)}${required?'<span class="required">*</span>':''}</label>${control}</div>`;
}
function upload(path,label,limit=2,required=true,object=report){
  const file=get(object,path),id='file-'+path.replaceAll('.','-');
  return `<div class="field"><label class="form-label" for="${id}">${esc(label)}${required?'<span class="required">*</span>':''}</label><input class="form-control" type="file" id="${id}" data-file="${path}" data-limit="${limit}" accept="application/pdf,image/jpeg,image/png">${file?`<p class="file-name">File yang sudah dipilih: ${esc(file.name)} <button type="button" class="btn btn-sm btn-link text-danger" data-clear-file="${path}">Hapus lampiran</button></p>`:''}<div class="form-text">Format PDF, JPG, PNG. Maks ${limit}MB.</div></div>`;
}
function table(headers,rows){return `<div class="table-wrap"><table class="table table-bordered"><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${headers.length}" class="table-empty">Belum ada data</td></tr>`}</tbody></table></div>`;}
function actions(type,index){return `<div class="icon-actions"><button class="btn btn-danger" type="button" data-edit="${type}:${index}" aria-label="Edit ${type} ${index+1}">✎</button><button class="btn btn-danger" type="button" data-delete="${type}:${index}" aria-label="Hapus ${type} ${index+1}">▤</button></div>`;}
function sourceList(type){return type==='penerima'?report.transaksi.penerima:report[type];}
function showErrors(errors,id='report-errors'){
  const node=$(id);node.replaceChildren();node.hidden=!errors.length;
  if(errors.length){const list=document.createElement('ul');list.className='mb-0';for(const error of errors){const li=document.createElement('li');li.textContent=error;list.append(li);}node.append(list);node.scrollIntoView({block:'nearest'});}
}
function notice(text){$('report-notice').textContent=text;$('report-notice').hidden=!text;}
function collect(root,object){for(const input of root.querySelectorAll('[data-field]'))set(object,input.dataset.field,input.value.trim());}
function pelaporHTML(){
  const p=report.pelapor;
  let html=`<div class="field self-field"><label class="form-label">Apakah anda sendiri yang mengalami penipuan? <span class="required">*</span></label><div class="radio-options"><label><input type="radio" name="sendiri" value="ya" ${p.sendiri==='ya'?'checked':''}> Ya, saya sendiri</label><label><input type="radio" name="sendiri" value="tidak" ${p.sendiri==='tidak'?'checked':''}> Tidak, saya mewakili korban</label></div></div>`;
  html+=upload('files.identitas','Upload Kartu Identitas Korban',1);
  if(p.sendiri==='tidak')html+=`<fieldset><legend>Informasi Korban yang Diwakili</legend>${field('korban.nama','Nama Korban')}${field('korban.identitas','Nomor Identitas Korban')}${field('korban.hubungan','Hubungan dengan Korban')}${upload('files.kuasa','Upload Surat Kuasa',1)}</fieldset>`;
  html+=`<div class="field"><label class="form-label">Jenis Kelamin <span class="required">*</span></label><div class="radio-options"><label><input type="radio" name="jenis_kelamin" value="Laki-laki" ${p.jenis_kelamin==='Laki-laki'?'checked':''}> Laki-laki</label><label><input type="radio" name="jenis_kelamin" value="Perempuan" ${p.jenis_kelamin==='Perempuan'?'checked':''}> Perempuan</label></div></div>`;
  for(const [key,label,type,values] of PELAPOR_FIELDS)html+=field('pelapor.'+key,label,type,values);
  return html;
}
function terlaporHTML(){
  return `<button type="button" class="btn btn-danger" data-add="terlapor">＋ Tambah Informasi Terlapor</button>`+
    table(['No','Nomor Terlapor','Nama Terlapor','Bukti Komunikasi','Aksi'],report.terlapor.map((row,i)=>`<tr><td>${i+1}</td><td>${esc(row.kode)} ${esc(row.nomor)}</td><td>${esc(row.nama)}</td><td><button type="button" class="btn btn-danger" data-preview="terlapor:${i}">Lihat Bukti</button></td><td>${actions('terlapor',i)}</td></tr>`))+
    `<button type="button" class="btn btn-danger" data-add="media">＋ Tambah Sumber / Media Informasi Penipuan</button>`+
    table(['No','Sumber / Media Informasi Penipuan','Detail Sumber / Media Informasi Penipuan','Bukti Sumber / Media Informasi Penipuan','Aksi'],report.media.map((row,i)=>`<tr><td>${i+1}</td><td>${esc(row.sumber)}</td><td>${esc(row.detail)}</td><td><button type="button" class="btn btn-danger" data-preview="media:${i}">Lihat Bukti</button></td><td>${actions('media',i)}</td></tr>`));
}
function kejadianHTML(){return field('kejadian.tanggal','Tanggal dan Waktu Kejadian','datetime-local')+field('kejadian.kronologi','Kronologi Kejadian Penipuan','textarea')+'<div class="text-end small text-secondary mb-3" id="character-count">'+report.kejadian.kronologi.length+' / 4000</div>'+upload('files.kejadian','Upload Bukti Pendukung Kejadian')+upload('files.polisi','Upload Laporan Kepolisian',2,false);}
function transaksiHTML(){
  return '<p>Apabila anda menggunakan lebih dari 1 Rekening yang digunakan untuk bertransaksi kepada pelaku scam, harap untuk membuat laporan baru sehingga dapat ditindaklanjuti.</p>'+field('transaksi.bank','Nama Penyelenggara Layanan Korban','select',BANKS)+field('transaksi.rekening','Nomor Rekening / Akun Korban')+field('transaksi.nama','Nama Pemilik Rekening / Akun Korban')+upload('files.rekening','Bukti Kepemilikan Rekening / Akun Korban')+
    '<button type="button" class="btn btn-danger" data-add="penerima">Tambah Informasi Penyelenggara Terlapor</button>'+
    table(['No','Nama Penyelenggara','Nomor Rekening / Akun','Nama Pemilik Rekening / Akun','Aksi'],report.transaksi.penerima.map((row,i)=>`<tr><td>${i+1}</td><td>${esc(row.bank)}</td><td>${esc(row.rekening)}</td><td>${esc(row.nama)}</td><td>${actions('penerima',i)}</td></tr>`));
}
function reviewHTML(){
  const sender=report.transaksi;
  let html='<p>Ringkasan Laporan</p><div class="report-summary"><h5>Sumber Transaksi Korban</h5>';
  html+=table(['Penyelenggara Layanan','Pemilik Rekening','Nomor Rekening / Akun'],[`<tr><td>${esc(sender.bank)}</td><td>${esc(sender.nama)}</td><td>${esc(sender.rekening)}</td></tr>`]);
  html+='<h5>Melaporkan Lembaga Penyedia Layanan Terlapor</h5>'+table(['Penyelenggara Layanan','Pemilik Rekening','Nomor Rekening / Akun'],sender.penerima.map(row=>`<tr><td>${esc(row.bank)}</td><td>${esc(row.nama)}</td><td>${esc(row.rekening)}</td></tr>`))+'</div>';
  html+='<p class="terms-label">Syarat dan Ketentuan</p><div class="terms-box" tabindex="0"><h1>Syarat & Ketentuan</h1><p><b>Dokumen simulasi lokal.</b> Ini bukan persetujuan terhadap layanan resmi IASC. Data dan dokumen yang dipakai harus berupa contoh fiktif.</p>';
  const terms=[['Definisi','Aplikasi ini adalah replika antarmuka untuk menguji proses pelaporan dan chatbot.'],['Tujuan Pelaporan','Proses hanya menyusun data dummy dan tidak menginstruksikan pemblokiran atau pengembalian dana.'],['Pernyataan dan Jaminan Pelapor','Periksa isian dan bukti yang dipilih. Jangan memasukkan identitas, rekening, atau dokumen pribadi nyata.'],['Kewajiban Pelapor','Lengkapi data wajib agar alur simulasi dapat dijalankan. Semua hasil OCR harus ditinjau kembali.'],['Batasan Tanggung Jawab','Tidak ada laporan resmi yang dibuat. Simulasi tidak memberikan jaminan penyelamatan dana.'],['Pelaporan ke Penegak Hukum','Simulasi ini tidak menggantikan pelaporan melalui kanal resmi lembaga berwenang.'],['Penggunaan Data','Hasil simulasi disimpan pada localStorage browser ini. Lampiran hanya disimpan sebagai metadata, bukan file asli.'],['Penutup','Centang pernyataan di bawah hanya menandakan Anda meninjau contoh data lokal.']];
  terms.forEach(([title,text],i)=>html+=`<h4>Pasal ${i+1}: ${title}</h4><p>${text}</p>`);
  return html+'</div><label class="review-label"><input id="review-local" type="checkbox" '+(report.reviewed?'checked':'')+'> <span>Saya menyatakan kesediaan untuk melapor dan memberikan informasi dengan benar. <small>(Simulasi data dummy.)</small></span></label><div class="captcha-demo"><span class="captcha-art">CAPTCHA DEMO</span><input class="form-control" aria-label="Captcha simulasi" placeholder="Dinonaktifkan di demo" disabled></div><p class="local-only-note">Penyelesaian hanya menyimpan hasil simulasi pada browser ini. Tidak ada laporan yang dikirim ke IASC.</p>';
}
function render(){
  if(phase!==5)report.reviewed=false;
  document.querySelector('.demo-toolbar span').textContent='Data belum disimpan sampai simulasi selesai.';
  $('phase-title').textContent=PHASES[phase-1];
  $('report-stepper').innerHTML=PHASES.map((title,i)=>`<button type="button" role="tab" aria-selected="${phase===i+1}" ${i+1>highest?'disabled':''} class="${phase===i+1?'active':''}" data-step="${i+1}"><span>${i+1}</span><span>${title}</span></button>`).join('');
  const body=[pelaporHTML,terlaporHTML,kejadianHTML,transaksiHTML,reviewHTML][phase-1]();
  $('phase-form').innerHTML=body+`<div class="form-actions">${phase>1?'<button type="button" class="btn btn-danger" id="previous">Kembali</button>':''}${phase<5?'<button type="submit" class="btn btn-danger" id="next">Lanjut</button>':'<button type="button" class="btn btn-outline-danger" id="download-local">Unduh Draft JSON</button><button type="button" class="btn btn-secondary" disabled>Kirim Laporan Penipuan</button><button type="submit" class="btn btn-danger" id="save-local">Simpan Simulasi Lokal</button>'}</div>`;
  $('report-errors').hidden=true;
  document.title=PHASES[phase-1]+' — IASC Lokal';
}
function capture(){collect($('phase-form'),report);if(phase===1){report.pelapor.sendiri=$('phase-form').querySelector('[name="sendiri"]:checked')?.value||'ya';report.pelapor.jenis_kelamin=$('phase-form').querySelector('[name="jenis_kelamin"]:checked')?.value||'';}if(phase===5&&$('review-local'))report.reviewed=$('review-local').checked;}
function go(target,push=true){
  capture();
  if(target>phase){for(let n=1;n<target;n++){const errors=validatePhase(report,n);if(errors.length){if(n!==phase){phase=n;render();}showErrors(errors);return;}}}
  phase=target;highest=Math.max(highest,phase);render();
  if(push)history.pushState({phase},'','/Guest/LaporanV2?step='+phase);
  $('replica-report').scrollIntoView({block:'start'});
}
function openRecord(type,index=null){
  capture();recordType=type;recordIndex=index;
  const current=index===null?null:sourceList(type)[index];
  recordDraft=current?{...current,...(current.details?{details:current.details.map(d=>({...d}))}:{})}:type==='terlapor'?{kode:'+62',nomor:candidate.terlapor_kontak||'',nama:candidate.terlapor_nama||'',file:null}:type==='media'?{sumber:'',detail:'',file:null}:{bank:'',rekening:'',nama:'',details:[{waktu:'',nominal:'',file:null}]};
  renderRecord();$('record-dialog').showModal();
}
function renderRecord(){
  const row=recordDraft;
  $('record-dialog-title').textContent=recordType==='terlapor'?'Tambah Informasi Terlapor':recordType==='media'?'Tambah Sumber / Media Informasi Penipuan':'Tambah Penyelenggara Terlapor';
  let html;
  if(recordType==='terlapor')html=field('kode','Kode Nomor Terlapor','select',['+62','+60','+65','+1'],true,row)+field('nomor','Nomor Terlapor','tel',null,true,row)+'<p class="form-text">Contoh: 81234567890. Pastikan nomor sesuai dengan bukti komunikasi.</p>'+field('nama','Nama Terlapor','text',null,true,row)+upload('file','Upload Bukti Komunikasi',2,true,row);
  else if(recordType==='media')html=field('sumber','Sumber Informasi / Media Informasi Penipuan','select',['Instagram','Website','Tiktok','Tokopedia','Media Lainnya','Shopee'],true,row)+field('detail','Detail Sumber Informasi / Media Informasi Penipuan','text',null,true,row)+'<p class="form-text">Dapat diisi dengan username atau link sumber/media informasi penipuan.</p>'+upload('file','Upload Bukti Sumber / Media Informasi Penipuan',2,true,row);
  else {
    html=field('bank','Nama Penyelenggara','select',BANKS,true,row)+field('rekening','Nomor Rekening / Akun','text',null,true,row)+field('nama','Nama Pemilik Rekening / Akun','text',null,true,row);
    html+=row.details.map((detail,i)=>`<div class="detail-transaction"><div class="detail-title"><span>Transaksi ${i+1}</span>${row.details.length>1?`<button type="button" class="btn btn-sm btn-outline-danger" data-remove-detail="${i}">Hapus</button>`:''}</div>${field('details.'+i+'.waktu','Waktu Transaksi','datetime-local',null,true,row)}${field('details.'+i+'.nominal','Nominal Transaksi','text',null,true,row)}${upload('details.'+i+'.file','Upload Bukti Pendukung Kejadian',2,true,row)}</div>`).join('');
    html+='<button type="button" class="btn btn-danger" id="add-detail">Tambah Informasi Transaksi</button>';
  }
  $('record-fields').innerHTML=html;$('record-errors').hidden=true;
}
async function attachment(file,limit){
  const error=fileError(file,limit);if(error)throw new Error(error);
  const bytes=new Uint8Array(await file.slice(0,8).arrayBuffer());
  const valid=file.type==='application/pdf'?new TextDecoder().decode(bytes).startsWith('%PDF-'):file.type==='image/png'?[137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n):bytes[0]===255&&bytes[1]===216&&bytes[2]===255;
  if(!valid)throw new Error('Isi file tidak sesuai format gambar atau PDF.');
  return {name:file.name,size:file.size,type:file.type,blob:file,url:URL.createObjectURL(file)};
}
function preview(file){
  const node=$('preview-content');node.replaceChildren();
  if(!file){node.textContent='Lampiran tidak tersedia.';}
  else if(file.type.startsWith('image/')){const image=document.createElement('img');image.src=file.url;image.alt=file.name;node.append(image);}
  else{const text=document.createElement('p');text.textContent=file.name+' · PDF dipilih sebagai lampiran simulasi.';node.append(text);}
  $('preview-dialog').showModal();
}
function payload(){return {schema_version:'local-replica-0.2',id:'SIM-'+Date.now().toString(36).toUpperCase()+'-'+crypto.randomUUID().slice(0,6).toUpperCase(),generated_at:new Date().toISOString(),simulated:true,submitted:false,data:metadata(report)};}
function download(value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=(value.id||'iasc-draft-lokal')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function finish(){
  const errors=[1,2,3,4,5].flatMap(n=>validatePhase(report,n));if(errors.length)return showErrors(errors);
  latestPayload=payload();
  try{const existing=JSON.parse(localStorage.getItem('iasc-local-reports')||'[]');if(!Array.isArray(existing))throw new Error();localStorage.setItem('iasc-local-reports',JSON.stringify([...existing,latestPayload]));}
  catch{return showErrors(['Browser tidak dapat menyimpan simulasi. Unduh Draft JSON untuk menyimpan salinan data Anda.']);}
  $('phase-title').textContent='Simulasi Laporan Selesai';
  document.title='Simulasi Laporan Selesai — IASC Lokal';
  document.querySelector('.demo-toolbar span').textContent='Simulasi tersimpan di browser ini.';
  $('phase-form').innerHTML=`<div class="alert alert-success"><h5>Data simulasi berhasil disimpan di browser ini.</h5><p>Nomor Laporan Simulasi:</p><p class="success-number">${esc(latestPayload.id)}</p><p class="mb-0">Tidak ada laporan yang dikirim ke IASC dan tidak ada pemblokiran rekening.</p></div><div class="form-actions"><button class="btn btn-danger" id="download-result" type="button">Unduh Hasil Simulasi</button><a class="btn btn-outline-danger" href="/Guest/CekLaporan?id=${encodeURIComponent(latestPayload.id)}">Cek Laporan Simulasi</a><a href="/" class="btn btn-secondary">Kembali ke Beranda</a></div>`;
  $('phase-form').scrollIntoView({block:'center'});
}
$('phase-form').addEventListener('input',event=>{if(event.target.matches('[data-field]')){set(report,event.target.dataset.field,event.target.value.trim());report.reviewed=false;}if(event.target.dataset.field==='kejadian.kronologi')$('character-count').textContent=event.target.value.length+' / 4000';});
$('phase-form').addEventListener('change',event=>{
  const target=event.target;
  if(target.name==='sendiri'){capture();render();}
  if(target.name==='jenis_kelamin')report.pelapor.jenis_kelamin=target.value;
  if(target.id==='review-local')report.reviewed=target.checked;
  if(target.dataset.field==='pelapor.provinsi'){capture();report.pelapor.kota='';render();}
  if(target.dataset.field==='pelapor.kota'&&target.value==='__manual__'){
    const input=document.createElement('input');input.id=target.id;input.dataset.field='pelapor.kota';input.className='form-control';input.placeholder='Ketik nama kota / kabupaten';input.maxLength=100;target.replaceWith(input);input.focus();report.pelapor.kota='';
  }
});
async function fileChanged(event,object,errorId){
  const input=event.target;if(!input.dataset.file||!input.files[0])return;
  try{const value=await attachment(input.files[0],Number(input.dataset.limit));const previous=get(object,input.dataset.file);set(object,input.dataset.file,value);if(previous?.url&&!referencesFile(report,previous)&&!referencesFile(recordDraft,previous))URL.revokeObjectURL(previous.url);showErrors([],errorId);if(errorId==='record-errors'){collect($('record-fields'),recordDraft);renderRecord();}else{capture();render();}}
  catch(error){input.value='';showErrors([error.message],errorId);}
}
$('phase-form').addEventListener('change',event=>fileChanged(event,report,'report-errors'));
$('record-form').addEventListener('change',event=>fileChanged(event,recordDraft,'record-errors'));
$('phase-form').addEventListener('submit',event=>{event.preventDefault();capture();if(Date.now()>expires)return showErrors(['Waktu pengisian berakhir. Unduh draft terlebih dahulu, lalu mulai laporan baru.']);phase===5?finish():go(phase+1);});
$('report-stepper').addEventListener('click',event=>{const button=event.target.closest('[data-step]');if(button&&!button.disabled)go(Number(button.dataset.step));});
$('phase-form').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.id==='previous')return go(phase-1);
  if(button.id==='download-local')return download(payload());
  if(button.id==='download-result')return download(latestPayload);
  if(button.dataset.add)return openRecord(button.dataset.add);
  if(button.dataset.edit){const [type,index]=button.dataset.edit.split(':');return openRecord(type,Number(index));}
  if(button.dataset.delete){const [type,index]=button.dataset.delete.split(':');if(confirm('Hapus baris data dummy ini dari simulasi?')){sourceList(type).splice(Number(index),1);render();}return;}
  if(button.dataset.preview){const [type,index]=button.dataset.preview.split(':');return preview(sourceList(type)[Number(index)].file);}
  if(button.dataset.clearFile){capture();set(report,button.dataset.clearFile,null);render();}
});
$('record-form').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.id==='add-detail'){collect($('record-fields'),recordDraft);recordDraft.details.push({waktu:'',nominal:'',file:null});renderRecord();}
  if(button.dataset.removeDetail){collect($('record-fields'),recordDraft);recordDraft.details.splice(Number(button.dataset.removeDetail),1);renderRecord();}
  if(button.dataset.clearFile){collect($('record-fields'),recordDraft);set(recordDraft,button.dataset.clearFile,null);renderRecord();}
});
$('record-form').addEventListener('submit',event=>{
  event.preventDefault();collect($('record-fields'),recordDraft);const errors=validateRecord(recordType,recordDraft);if(errors.length)return showErrors(errors,'record-errors');
  if(recordType==='penerima')recordDraft.details.forEach(detail=>detail.nominal=amount(detail.nominal));
  const list=sourceList(recordType);if(recordIndex===null)list.push(recordDraft);else list[recordIndex]=recordDraft;
  $('record-dialog').close();render();notice('Data berhasil disimpan pada formulir lokal.');
});
for(const id of ['close-record','cancel-record'])$(id).addEventListener('click',()=>$('record-dialog').close());
$('close-preview').addEventListener('click',()=>$('preview-dialog').close());
$('fill-dummy').addEventListener('click',async()=>{
  const button=$('fill-dummy');button.disabled=true;
  try{
    const response=await fetch('/fixtures/bukti-dummy.png');if(!response.ok)throw new Error('Contoh lampiran belum tersedia.');
    const blob=await response.blob();
    const file=await attachment(new File([blob],'lampiran-dummy.png',{type:'image/png'}),1);
    Object.assign(report.pelapor,{sendiri:'ya',jenis_kelamin:'Laki-laki',kewarganegaraan:'Indonesia',nama:'PELAPOR DUMMY PENGUJIAN',tempat_lahir:'Kota Dummy',tanggal_lahir:'1990-10-01',agama:'Tidak Diketahui',pekerjaan:'Penguji Dummy',telepon:'80000000000',konfirmasi_telepon:'80000000000',email:'pelapor.dummy@example.com',konfirmasi_email:'pelapor.dummy@example.com',jenis_identitas:'KTP',nomor_identitas:'0000000000000000',provinsi:'DKI Jakarta',kota:'Kota Adm. Jakarta Pusat',alamat:'Alamat dummy untuk pengujian formulir, bukan alamat orang nyata.'});
    report.files={identitas:file,kejadian:file,rekening:file};
    report.terlapor=[{kode:'+62',nomor:'80000000001',nama:'TERLAPOR DUMMY - BUKAN ORANG NYATA',file}];
    report.media=[{sumber:'Website',detail:'https://example.com/dummy-test - DATA FIKTIF',file}];
    report.kejadian={tanggal:'2026-10-19T10:00',kronologi:'DATA DUMMY UNTUK PENGUJIAN. Pada 19 Oktober 2026, pelapor melakukan transfer fiktif untuk penawaran barang contoh. Tidak ada kejadian atau tuduhan nyata.'};
    report.transaksi={bank:'BNI',rekening:'0000000000',nama:'PEMILIK REKENING DUMMY',penerima:[{bank:'BCA',rekening:'0000000001',nama:'TERLAPOR DUMMY - FIKTIF',details:[{waktu:'2026-10-19T10:00',nominal:100000,file}]}]};
    report.reviewed=false;render();notice('Contoh dummy terisi untuk lima fase. Semua data dan lampiran bersifat fiktif.');
  }catch(error){showErrors([error.message]);}finally{button.disabled=false;}
});
document.addEventListener('iasc-intake:apply',async event=>{
  if(!event.detail?.data||typeof event.detail.data!=='object')return;
  capture();let file=null;
  try{if(event.detail.evidence instanceof Blob&&['image/png','image/jpeg'].includes(event.detail.evidence.type))file=await attachment(new File([event.detail.evidence],'bukti-dari-chatbot.'+(event.detail.evidence.type==='image/png'?'png':'jpg'),{type:event.detail.evidence.type}),2);
    candidate=Object.fromEntries(Object.entries(event.detail.data).filter(([key,value])=>typeof value==='string'||(key==='nominal'&&Number.isSafeInteger(value))));const count=applyChat(report,candidate,file);render();notice(`${count} isian kosong dilengkapi dari chatbot. Isian manual tetap dipertahankan. Periksa hasilnya dan lengkapi lampiran lain yang wajib.`);
  }catch(error){showErrors([error.message]);}
});

document.addEventListener('iasc-intake:apply-v1',async event=>{
  const data=event.detail?.data,sessionId=event.detail?.session_id;
  if(!data||typeof data!=='object'||typeof sessionId!=='string')return;
  capture();
  const files=new Map();
  const key=meta=>meta?.url||meta?.file_url||meta?.storage_url||meta?.id;
  async function visit(value){
    if(!value||typeof value!=='object')return;
    const fileKey=key(value);
    if(fileKey&&typeof fileKey==='string'&&!files.has(fileKey)){
      const url=new URL(value.url||value.file_url||value.storage_url||'',location.origin);
      if(url.origin!==location.origin||!url.pathname.startsWith('/api/v1/session/'+encodeURIComponent(sessionId)+'/'))return;
      const response=await fetch(url,{credentials:'same-origin'});
      if(!response.ok)throw new Error('Lampiran sesi tidak dapat diambil. Buka kembali asisten untuk mengunggah ulang.');
      const blob=await response.blob();
      const filename=value.file_name||value.filename||value.name||'bukti-chatbot.jpg';
      files.set(fileKey,await attachment(new File([blob],filename,{type:blob.type}),2));
      return;
    }
    for(const child of Object.values(value))await visit(child);
  }
  try{
    await visit(data);
    const count=applyChatV1(report,data,meta=>files.get(key(meta))||null);
    highest=1;for(let n=1;n<=4;n++){if(validatePhase(report,n).length)break;highest=n+1;}
    render();notice(`${count} isian dan kelompok data kosong dilengkapi dari asisten. Periksa setiap fase; isian manual dan persetujuan tetap milik Anda. Tidak ada laporan yang dikirim.`);
  }catch(error){showErrors([error.message]);}
});

window.addEventListener('popstate',()=>{const target=Number(new URLSearchParams(location.search).get('step'))||1;if(target>=1&&target<=highest)go(target,false);});
setInterval(()=>{const seconds=Math.max(0,Math.floor((expires-Date.now())/1000));$('countdown').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');},1000);
history.replaceState({phase:1},'','/Guest/LaporanV2?step=1'+(new URLSearchParams(location.search).get('assistant')==='1'?'&assistant=1':''));render();

import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyReport} from '../static/replica/report-core.mjs';
import {mapCanonicalPatch, flattenPatches, applyProgressPatch, createProgressState, resetProgressReport, acceptProgress, sessionFileUrl, simulationResult} from '../static/replica/progressive-fill.mjs';
const patch=(path,value)=>({op:'set',path,value});
const file={name:'bukti.jpg',size:100,type:'image/jpeg',url:'blob:session'};
const result={ticket_number:'SIM-REPORT_001',simulated:true,submitted:false};
const apply=(report,state,path,value,options={})=>applyProgressPatch(report,patch(path,value),state,options);

test('canonical values map to native radio, date, code, and exact decimal fields',()=>{
  assert.equal(mapCanonicalPatch(patch('tahap1.apakah_mengalami_sendiri','Ya, saya sendiri')).value,'ya');
  assert.equal(mapCanonicalPatch(patch('tahap1.tanggal_lahir_pelapor','1 Oktober 1990')).value,'1990-10-01');
  assert.equal(mapCanonicalPatch(patch('tahap1.kode_negara_telepon_pelapor','Indonesia (+62)')).value,'+62');
  const mapped=mapCanonicalPatch(patch('tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi','100000.50'));
  assert.equal(mapped.value,100000.5);assert.equal(mapped.path,'transaksi.penerima.0.details.0.nominal');
  assert.equal(mapCanonicalPatch(patch('tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.0.nominal_transaksi','100000.005')),null);
});
test('progressive corrections replace prior AI values and preserve explicit manual changes',()=>{
  const report=emptyReport(),state=createProgressState();
  assert.equal(apply(report,state,'tahap1.nama_pelapor','OCR PERTAMA').applied,true);
  assert.equal(apply(report,state,'tahap1.nama_pelapor','OCR KOREKSI').applied,true);
  report.pelapor.nama='KOREKSI MANUAL';
  assert.equal(apply(report,state,'tahap1.nama_pelapor','OCR BARU').reason,'manual');
  state.manual.add('pelapor.email');report.pelapor.email='';
  assert.equal(apply(report,state,'tahap1.email_pelapor','baru@example.com').reason,'manual');
  assert.equal(report.pelapor.nama,'KOREKSI MANUAL');
});
test('partial chat rows are completed in place; additional rows append after manual records',()=>{
  const report=emptyReport(),state=createProgressState();report.terlapor.push({nama:'MANUAL',nomor:'81234567890'});
  apply(report,state,'tahap2.daftar_informasi_terlapor.0.nama_terlapor','OCR A');
  assert.equal(report.terlapor.length,2);assert.equal(report.terlapor[1].nomor,'');
  apply(report,state,'tahap2.daftar_informasi_terlapor.0.nomor_terlapor','80000000001');
  apply(report,state,'tahap2.daftar_informasi_terlapor.1.nama_terlapor','OCR B');
  assert.equal(report.terlapor.length,3);assert.equal(report.terlapor[1].nomor,'80000000001');assert.equal(report.terlapor[0].nama,'MANUAL');
  apply(report,state,'tahap2.daftar_informasi_terlapor.0.nama_terlapor','OCR A KOREKSI');assert.equal(report.terlapor.length,3);
});
test('nested receiver and transaction patches append, complete, and retain leading zeroes',()=>{
  const report=emptyReport(),state=createProgressState();
  const base='tahap4.daftar_penyelenggara_terlapor.0.';
  apply(report,state,base+'nomor_rekening_akun','0000000001');
  apply(report,state,base+'daftar_rincian_transaksi.0.nominal_transaksi','100000.50');
  apply(report,state,base+'daftar_rincian_transaksi.0.waktu_transaksi','19 Oktober 2026 10:00:00');
  apply(report,state,base+'daftar_rincian_transaksi.1.nominal_transaksi',200000);
  assert.equal(report.transaksi.penerima.length,1);assert.equal(report.transaksi.penerima[0].rekening,'0000000001');
  assert.equal(report.transaksi.penerima[0].details.length,2);assert.equal(report.transaksi.penerima[0].details[0].waktu,'2026-10-19T10:00');
  assert.equal(report.transaksi.penerima[0].details[0].nominal,100000.5);
});
test('file smart pointers reuse one resolved attachment across communication/media/incident',()=>{
  const report=emptyReport(),state=createProgressState(),meta={file_id:'ABCDEFGHIJKLMNOP',url:'/api/v1/session/ABCDEFGHIJKLMNOP/files/ABCDEFGHIJKLMNOP'};
  for(const path of ['tahap2.daftar_informasi_terlapor.0.upload_bukti_komunikasi','tahap2.daftar_sumber_media_penipuan.0.upload_bukti_sumber_media','tahap3.upload_bukti_pendukung_kejadian'])assert.equal(apply(report,state,path,meta,{resolveFile:()=>file}).applied,true);
  assert.equal(report.terlapor[0].file,report.media[0].file);assert.equal(report.media[0].file,report.files.kejadian);
  assert.equal(apply(report,state,'tahap1.upload_kartu_identitas_korban',meta,{resolveFile:()=>({...file,size:1048577})}).reason,'file');
});
test('evidence fetch URLs cannot leave the exact session or add query, fragment or credentials',()=>{
  const id='ABCDEFGHIJKLMNOP',origin='http://127.0.0.1:8787',path=`/api/v1/session/${id}/files/${id}`;
  assert.equal(sessionFileUrl({url:path,file_id:id},id,origin),origin+path);
  for(const url of ['https://evil.test'+path,path+'?other=session',path+'#fragment',path+'/../'+id,path.replace('/'+id+'/files/','/ZYXWVUTSRQPONMLK/files/'),'http://user@127.0.0.1:8787'+path])assert.equal(sessionFileUrl({url},id,origin),null,url);
  assert.equal(sessionFileUrl({url:path,file_id:'OTHER_FILE_ID_0000'},id,origin),null);
});
test('prototype paths, arbitrary host fields, excessive indexes and malformed patches are rejected',()=>{
  for(const path of ['tahap1.__proto__','__proto__.polluted','tahap1.constructor.name','tahap1.nama','tahap2.daftar_informasi_terlapor.50.nama_terlapor','tahap4.daftar_penyelenggara_terlapor.0.daftar_rincian_transaksi.99.nominal_transaksi'])assert.equal(mapCanonicalPatch(patch(path,'x')),null,path);
  assert.throws(()=>flattenPatches([patch('tahap1.__proto__.polluted','yes')]));
  assert.throws(()=>flattenPatches([{op:'remove',path:'tahap1.nama_pelapor'}]));
  assert.equal({}.polluted,undefined);
});
test('bounded containers flatten into leaf patches instead of replacing whole report lists',()=>{
  const patches=flattenPatches([patch('tahap2.daftar_informasi_terlapor',[{nome:'ignored',nama_terlapor:'A'},{nama_terlapor:'B'}])]);
  assert.equal(patches.length,2);assert.equal(patches[1].path,'tahap2.daftar_informasi_terlapor.1.nama_terlapor');
  assert.throws(()=>flattenPatches(Array.from({length:301},()=>patch('tahap1.nama_pelapor','A'))));
});
test('monotonic revisions deduplicate turns, reset new sessions and reject retired-session replays',()=>{
  const state=createProgressState(),message={session_id:'ABCDEFGHIJKLMNOP',revision:1,active_wizard_step:1};
  assert.equal(acceptProgress(state,message),true);state.revision=message.revision;
  assert.equal(acceptProgress(state,message),false);assert.equal(acceptProgress(state,{...message,revision:0}),false);
  state.manual.add('pelapor.nama');
  assert.equal(acceptProgress(state,{...message,session_id:'ZYXWVUTSRQPONMLK',revision:0}),true);assert.equal(state.revision,-1);assert.equal(state.manual.has('pelapor.nama'),true);
  assert.equal(acceptProgress(state,{...message,revision:99}),false);
  assert.equal(acceptProgress(state,{...message,active_wizard_step:6}),false);
});
test('consent/captcha and ticket rendering are scoped to explicitly simulated, unsubmitted results',()=>{
  const report=emptyReport(),state=createProgressState();
  assert.equal(apply(report,state,'tahap5.setuju_syarat_dan_ketentuan',true).reason,'consent');
  assert.equal(apply(report,state,'tahap5.captcha_answer','78').reason,'consent');
  assert.equal(apply(report,state,'tahap5.captcha_question','78 + 0 =').applied,true);
  assert.equal(apply(report,state,'tahap5.setuju_syarat_dan_ketentuan',true,{result}).applied,true);
  assert.equal(apply(report,state,'tahap5.captcha_answer','78',{result}).applied,true);assert.equal(report.reviewed,true);
  for(const invalid of [{...result,submitted:true},{...result,simulated:false},{...result,ticket_number:'IASC-OFFICIAL'},null])assert.equal(simulationResult(invalid),false);
  assert.equal(simulationResult(result),true);
});

 test('new sessions clear previous AI data and ticket inputs, retain manual fields and edited rows',()=>{
  const report=emptyReport(),state=createProgressState();
  apply(report,state,'tahap1.nama_pelapor','AI NAME');
  apply(report,state,'tahap1.email_pelapor','ai@example.com');
  report.pelapor.email='manual@example.com';state.manual.add('pelapor.email');
  apply(report,state,'tahap2.daftar_informasi_terlapor.0.nama_terlapor','REMOVE AI ROW');
  apply(report,state,'tahap2.daftar_informasi_terlapor.1.nama_terlapor','KEEP EDITED ROW');
  report.terlapor[1].nama='MANUAL EDIT';state.manual.add('terlapor.1.nama');
  apply(report,state,'tahap5.captcha_answer','78',{result});
  resetProgressReport(report,state);
  assert.equal(report.pelapor.nama,'');assert.equal(report.pelapor.email,'manual@example.com');
  assert.equal(report.terlapor.length,1);assert.equal(report.terlapor[0].nama,'MANUAL EDIT');
  assert.equal(state.manual.has('terlapor.0.nama'),true);assert.equal(report.captcha_answer,undefined);assert.equal(report.reviewed,false);
 });

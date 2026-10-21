import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyReport,amount,amountInput,fileError,validatePhase,validateRecord,metadata,applyChat,applyChatV1,localDate,referencesFile} from '../static/replica/report-core.mjs';

const file={name:'DUMMY.png',type:'image/png',size:100,url:'blob:private',blob:{binary:true}};
function ready(){
  const r=emptyReport();
  Object.assign(r.pelapor,{jenis_kelamin:'Laki-laki',nama:'PELAPOR DUMMY',tempat_lahir:'Kota Dummy',tanggal_lahir:'1990-01-01',agama:'Tidak Diketahui',pekerjaan:'Penguji',telepon:'80000000000',konfirmasi_telepon:'80000000000',email:'dummy@example.com',konfirmasi_email:'dummy@example.com',jenis_identitas:'KTP',nomor_identitas:'0000000000000000',provinsi:'DKI Jakarta',kota:'Kota Adm. Jakarta Pusat',alamat:'Alamat dummy'});
  r.files={identitas:file,kejadian:file,rekening:file};
  r.terlapor=[{kode:'+62',nomor:'80000000001',nama:'TERLAPOR DUMMY',file}];
  r.media=[{sumber:'Website',detail:'https://example.com',file}];
  r.kejadian={tanggal:'2026-10-19T10:00',kronologi:'DATA DUMMY, tidak ada kejadian atau transaksi nyata.'};
  r.transaksi={bank:'BANK DEMO A',rekening:'0000000000',nama:'PELAPOR DUMMY',penerima:[{bank:'BANK DEMO B',rekening:'0000000001',nama:'TERLAPOR DUMMY',details:[{waktu:'2026-10-19T10:00',nominal:100000,file}]}]};
  r.reviewed=true;return r;
}
test('empty wizard cannot advance; complete dummy validates all five phases',()=>{
  for(let phase=1;phase<=5;phase++){assert.ok(validatePhase(emptyReport(),phase).length);assert.deepEqual(validatePhase(ready(),phase),[]);}
});
test('confirmation, identity, and representative documents are required',()=>{
  const r=ready();r.pelapor.konfirmasi_email='other@example.com';assert.ok(validatePhase(r,1).some(x=>x.includes('Konfirmasi email')));
  r.pelapor.konfirmasi_email=r.pelapor.email;r.pelapor.nomor_identitas='123';assert.ok(validatePhase(r,1).some(x=>x.includes('16 digit')));
  r.pelapor.nomor_identitas='0000000000000000';r.pelapor.sendiri='tidak';assert.ok(validatePhase(r,1).length);
  r.korban={nama:'KORBAN DUMMY',identitas:'0000000000000001',hubungan:'Kuasa dummy'};r.files.kuasa=file;assert.deepEqual(validatePhase(r,1),[]);
});
test('rupiah parsing rejects ambiguous, negative, zero, and sub-cent amounts',()=>{
  for(const value of ['-1','0','1,5','100.5','1e5','100,005',100.005,Infinity,NaN,true,null,'NaN'])assert.equal(amount(value),null,String(value));
  assert.equal(amount('Rp1.250.000,00'),1250000);assert.equal(amount(100000),100000);
});
test('file size/type, incident chronology, and future dates block advancement',()=>{
  assert.ok(fileError({...file,size:2*1024*1024},1));assert.ok(fileError({...file,type:'text/html'}));
  const r=ready();r.kejadian.kronologi='short';assert.ok(validatePhase(r,3).length);
  r.kejadian.kronologi='Dummy kronologi yang cukup panjang.';r.kejadian.tanggal='2099-01-01T10:00';assert.ok(validatePhase(r,3).length);
});
test('all details in multiple transactions must be valid and attached',()=>{
  const row=ready().transaksi.penerima[0];row.details.push({waktu:'2026-10-19T11:00',nominal:'200.000',file});assert.deepEqual(validateRecord('penerima',row),[]);
  row.details[1].file=null;assert.ok(validateRecord('penerima',row).some(x=>x.includes('Transaksi 2')));
  assert.ok(validateRecord('terlapor',{nomor:'bad',nama:'A',file:null}).length);
});
test('chat only fills empty fields, preserves manual data and leading zeroes',()=>{
  const r=emptyReport();r.pelapor.nama='MANUAL DUMMY';r.transaksi.rekening='0000000009';
  const changed=applyChat(r,{pelapor_nama:'AI NAME',pelapor_email:'dummy@example.com',pelapor_nik:'0000000000000000',rekening_pengirim:'0000000001',bank_pengirim:'BANK DEMO A',bank_penerima:'BANK DEMO B',rekening_penerima:'0000000002',terlapor_nama:'DUMMY',waktu_transaksi:'2026-10-19T10:00:00+07:00',nominal:100000},file);
  assert.ok(changed>0);assert.equal(r.pelapor.nama,'MANUAL DUMMY');assert.equal(r.transaksi.rekening,'0000000009');assert.equal(r.pelapor.nomor_identitas,'0000000000000000');assert.equal(r.pelapor.konfirmasi_email,r.pelapor.email);assert.equal(r.transaksi.penerima[0].rekening,'0000000002');assert.equal(r.reviewed,false);
  assert.equal(applyChat(r,null),0);
  assert.equal(r.transaksi.nama,'');
});
test('incomplete OCR cannot invent a transaction or identity evidence',()=>{
  const r=emptyReport();applyChat(r,{bank_penerima:'BANK DEMO B',rekening_penerima:'0000000001'});
  assert.equal(r.transaksi.penerima.length,0);assert.equal(r.files.identitas,undefined);assert.equal(r.kejadian.tanggal,'');
});
test('saved metadata excludes raw files and object URLs recursively',()=>{
  const result=metadata(ready());const serialized=JSON.stringify(result);
  assert.ok(!serialized.includes('blob:private'));assert.ok(!serialized.includes('binary'));assert.equal(result.files.identitas.name,'DUMMY.png');assert.equal(result.transaksi.penerima[0].details[0].nominal,100000);
});

test('v1 mapping fills five-step replica, reuses evidence, and preserves manual data',()=>{
  const r=emptyReport();r.pelapor.nama='MANUAL';
  const data={tahap1:{nama_pelapor:'AI',jenis_kelamin:'Laki-laki',kewarganegaraan_pelapor:'Indonesia',tempat_lahir_pelapor:'Kota Dummy',tanggal_lahir_pelapor:'1 Oktober 1990',agama_pelapor:'Tidak Diketahui',pekerjaan_pelapor:'Penguji',nomor_telepon_pelapor:'80000000000',email_pelapor:'dummy@example.com',jenis_identitas:'KTP',nomor_identitas:'0000000000000000',provinsi_domisili_pelapor:'DKI Jakarta',kota_domisili_pelapor:'Kota Adm. Jakarta Pusat',alamat_pelapor:'Alamat dummy',upload_kartu_identitas_korban:{file_id:'ktp'}},tahap2:{daftar_informasi_terlapor:[{nomor_terlapor:'80000000001',nama_terlapor:'DUMMY',upload_bukti_komunikasi:{file_id:'chat'}}],daftar_sumber_media_penipuan:[{sumber_media_informasi_penipuan:'WhatsApp',detail_sumber_media_informasi_penipuan:'https://example.com',upload_bukti_sumber_media:{file_id:'chat'}}]},tahap3:{tanggal_dan_waktu_kejadian:'19 Oktober 2026 10:00',kronologi_kejadian_penipuan:'DATA DUMMY untuk pengujian alur, tidak ada transaksi nyata.',upload_bukti_pendukung_kejadian:{file_id:'chat'}},tahap4:{nama_penyelenggara_layanan_korban:'BNI',nomor_rekening_akun_korban:'0000000000',nama_pemilik_rekening_akun_korban:'MANUAL',bukti_kepemilikan_rekening_akun_korban:{file_id:'account'},daftar_penyelenggara_terlapor:[{nama_penyelenggara:'BCA',nomor_rekening_akun:'0000000001',nama_pemilik_rekening_akun:'DUMMY',daftar_rincian_transaksi:[{waktu_transaksi:'19 Oktober 2026 10:00:00',nominal_transaksi:100000,upload_bukti_pendukung_kejadian:{file_id:'transfer'}}]}]}};
  const evidence=new Map(['ktp','chat','account','transfer'].map(id=>[id,{...file,name:id+'.png'}]));
  assert.ok(applyChatV1(r,data,meta=>evidence.get(meta?.file_id))>0);
  assert.equal(r.pelapor.nama,'MANUAL');assert.equal(r.transaksi.rekening,'0000000000');
  assert.equal(r.transaksi.penerima[0].rekening,'0000000001');assert.equal(r.pelapor.konfirmasi_email,r.pelapor.email);
  assert.equal(r.terlapor[0].file,r.media[0].file);assert.equal(r.media[0].file,r.files.kejadian);
  for(let n=1;n<=4;n++)assert.deepEqual(validatePhase(r,n),[]);
  r.transaksi.penerima[0].nama='MANUAL ROW';applyChatV1(r,data,meta=>evidence.get(meta?.file_id));
  assert.equal(r.transaksi.penerima.length,1);assert.equal(r.transaksi.penerima[0].nama,'MANUAL ROW');assert.equal(r.reviewed,false);
});
test('v1 dates use Indonesian month names and absent evidence cannot become an attachment',()=>{
  assert.equal(localDate('19 Oktober 2026 10:00:00',true),'2026-10-19T10:00');
  assert.equal(localDate('1 Oktober 1990'),'1990-10-01');assert.equal(localDate('invalid'),'');
  const r=emptyReport();applyChatV1(r,{tahap1:{upload_kartu_identitas_korban:{file_id:'missing'}}});assert.equal(r.files.identitas,undefined);
});

test('shared evidence URLs stay live while other fields or an uncommitted record use them',()=>{
  const r=emptyReport(),shared={...file};
  r.terlapor=[{nama:'DUMMY',file:shared}];r.media=[{file:shared}];r.files.kejadian=shared;
  r.files.kejadian={...file,url:'blob:new'};assert.equal(referencesFile(r,shared),true);
  const draft={file:{...file,url:'blob:replacement'}};assert.equal(referencesFile(draft,shared),false);
  assert.equal(referencesFile(r.terlapor[0],shared),true);
  r.terlapor=[];r.media=[];assert.equal(referencesFile(r,shared),false);
  assert.equal(referencesFile(null,shared),false);assert.equal(referencesFile(r,null),false);
});

test('fractional rupiah round-trips modal strings without weakening ambiguous manual parsing',()=>{
  for(const value of [0.01,0.29,100000.5,100000.55,9999999999999.99])assert.equal(amount(amountInput(value)),value);
  assert.equal(amount('100.005'),100005);assert.equal(amount('Rp100.000,50'),100000.5);assert.equal(amount(100000.55),100000.55);
  assert.equal(amount('100.000,5'),null);assert.equal(amount('100000.50'),null);assert.equal(amount(0.1+0.2),null);
  assert.equal(amount('10.000.000.000.000,01'),null);
});
test('v1 canonical Decimal money preserves fractional transactions and rejects sub-cent wire values',()=>{
  const data={tahap4:{daftar_penyelenggara_terlapor:[{nama_penyelenggara:'BCA',nomor_rekening_akun:'0000000001',nama_pemilik_rekening_akun:'DUMMY',daftar_rincian_transaksi:[{waktu_transaksi:'19 Oktober 2026 10:00:00',nominal_transaksi:'100000.50',upload_bukti_pendukung_kejadian:{file_id:'transfer'}}]}]}};
  const r=emptyReport();applyChatV1(r,data,()=>file);
  assert.equal(r.transaksi.penerima.length,1);const detail=r.transaksi.penerima[0].details[0];assert.equal(detail.nominal,100000.5);
  detail.nominal=String(amountInput(detail.nominal));assert.deepEqual(validateRecord('penerima',r.transaksi.penerima[0]),[]);assert.equal(amount(detail.nominal),100000.5);
  data.tahap4.daftar_penyelenggara_terlapor[0].daftar_rincian_transaksi[0].nominal_transaksi='100000.005';
  const invalid=emptyReport();applyChatV1(invalid,data,()=>file);assert.equal(invalid.transaksi.penerima.length,0);
});

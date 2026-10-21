export const PHASES = ['Informasi Pihak Pelapor','Informasi Pihak Terlapor','Informasi Kejadian','Informasi Transaksi','Kesediaan Melapor'];
export const BANKS = ['BNI','BRI','BCA','Bank Permata','Bank Mandiri','SMBC','Dana','Gopay','OVO','BSI','Bank Mega','Bank Danamon','Bank DBS Indonesia','Bank QNB','Bank Sinarmas','Bank Jago','Bank OCBC NISP','BTN','Shopeepay','BANK DEMO A','BANK DEMO B'];
export const PROVINCES = ['Aceh','Sumatera Utara','Sumatera Barat','Riau','Jambi','Sumatera Selatan','Bengkulu','Lampung','Kepulauan Bangka Belitung','Kepulauan Riau','DKI Jakarta','Jawa Barat','Jawa Tengah','Daerah Istimewa Yogyakarta','Jawa Timur','Banten','Bali','Nusa Tenggara Barat','Nusa Tenggara Timur','Kalimantan Barat','Kalimantan Tengah','Kalimantan Selatan','Kalimantan Timur','Kalimantan Utara','Sulawesi Utara','Sulawesi Tengah','Sulawesi Selatan','Sulawesi Tenggara','Gorontalo','Sulawesi Barat','Maluku','Maluku Utara','Papua','Papua Barat','Papua Selatan','Papua Tengah','Papua Pegunungan','Papua Barat Daya','Luar Negeri'];
export const CITIES = {
  'DKI Jakarta':['Kabupaten Adm. Kep. Seribu','Kota Adm. Jakarta Pusat','Kota Adm. Jakarta Utara','Kota Adm. Jakarta Barat','Kota Adm. Jakarta Selatan','Kota Adm. Jakarta Timur'],
  'Jawa Barat':['Kota Bandung','Kota Bekasi','Kota Bogor','Kota Depok','Kota Cimahi','Kota Cirebon'],
};
export const PELAPOR_FIELDS = [
  ['kewarganegaraan','Kewarganegaraan Pelapor','select',['Indonesia','Malaysia','Singapura','Amerika Serikat','Australia','Lainnya']],
  ['nama','Nama Pelapor','text'],['tempat_lahir','Tempat Lahir Pelapor','text'],['tanggal_lahir','Tanggal Lahir Pelapor','date'],
  ['agama','Agama Pelapor','select',['Tidak Diketahui','Islam','Katolik','Hindu','Buddha','Konghucu','Protestan']],
  ['pekerjaan','Pekerjaan Pelapor','text'],['telepon','Nomor Telepon Pelapor','phone'],['konfirmasi_telepon','Konfirmasi Nomor Telepon Pelapor','phone'],
  ['email','E-Mail Pelapor','email'],['konfirmasi_email','Konfirmasi E-Mail Pelapor','email'],
  ['jenis_identitas','Jenis Identitas','select',['KTP','Paspor','KITAS','NPWP Badan']],['nomor_identitas','Nomor Identitas','text'],
  ['provinsi','Provinsi Domisili Pelapor','select',PROVINCES],['kota','Kota Domisili Pelapor','city'],['alamat','Alamat Pelapor','textarea'],
];
export function emptyReport() {
  return {pelapor:{sendiri:'ya',jenis_kelamin:'',kewarganegaraan:'Indonesia',kode_telepon:'+62',konfirmasi_kode_telepon:'+62',...Object.fromEntries(PELAPOR_FIELDS.filter(f=>f[0]!=='kewarganegaraan').map(f=>[f[0],'']))},korban:{nama:'',identitas:'',hubungan:''},files:{},terlapor:[],media:[],kejadian:{tanggal:'',kronologi:''},transaksi:{bank:'',rekening:'',nama:'',penerima:[]},reviewed:false};
}
export function amount(value) {
  if(typeof value==='number'){
    if(!Number.isFinite(value)||Number(value.toFixed(2))!==value)return null;
    const cents=Math.round(value*100);
    return Number.isSafeInteger(cents)&&cents>0&&cents<=1_000_000_000_000_000?cents/100:null;
  }
  if(typeof value!=='string')return null;
  const text=value.trim();
  if(!/^(?:Rp\s*)?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{2})?$/i.test(text))return null;
  return amount(Number(text.replace(/^Rp\s*/i,'').replaceAll('.','').replace(',','.')));
}
export function amountInput(value){
  return typeof value==='number'&&amount(value)!==null?value.toFixed(Number.isInteger(value)?0:2).replace('.',','):value;
}
function canonicalAmount(value){
  if(typeof value==='number')return amount(value);
  if(typeof value!=='string'||!/^\d+(?:\.\d{1,2})?$/.test(value))return null;
  const [whole,fraction]=value.split('.');
  return amount(whole+(fraction===undefined?'':','+fraction.padEnd(2,'0')));
}
export function fileError(file,limit=2) {
  if(!file) return 'Lampiran wajib dipilih.';
  if(!['image/png','image/jpeg','application/pdf'].includes(file.type)) return 'Format lampiran harus PDF, JPG, atau PNG.';
  if(file.size<=0||file.size>limit*1024*1024) return `Ukuran lampiran maksimum ${limit} MB dan tidak boleh kosong.`;
  return null;
}
function past(value,now=Date.now()) {const n=Date.parse(value);return Boolean(value)&&Number.isFinite(n)&&n<=now;}
export function validateRecord(type,row) {
  const errors=[];
  if(type==='terlapor') {
    if(!/^[0-9]{8,15}$/.test(row.nomor||'')) errors.push('Nomor terlapor harus terdiri dari 8–15 digit.');
    if((row.nama||'').trim().length<2) errors.push('Nama terlapor wajib diisi.');
    if(fileError(row.file)) errors.push('Bukti komunikasi: '+fileError(row.file));
  } else if(type==='media') {
    if(!row.sumber) errors.push('Pilih sumber / media informasi penipuan.');
    if(!(row.detail||'').trim()) errors.push('Detail sumber / media wajib diisi.');
    if(fileError(row.file)) errors.push('Bukti sumber / media: '+fileError(row.file));
  } else {
    if(!row.bank) errors.push('Pilih penyelenggara terlapor.');
    if(!/^[0-9]{6,30}$/.test(row.rekening||'')) errors.push('Rekening / akun terlapor harus terdiri dari 6–30 digit.');
    if(!(row.nama||'').trim()) errors.push('Nama pemilik rekening terlapor wajib diisi.');
    if(!row.details?.length) errors.push('Tambahkan minimal satu transaksi.');
    for(const [index,detail] of (row.details||[]).entries()) {
      if(!past(detail.waktu)||!/[T ][0-9]{2}:[0-9]{2}/.test(detail.waktu||'')) errors.push(`Transaksi ${index+1}: isi tanggal dan jam yang valid, bukan waktu mendatang.`);
      if(amount(detail.nominal)===null) errors.push(`Transaksi ${index+1}: nominal harus lebih dari nol dengan maksimal dua digit desimal (contoh 100.000,50).`);
      if(fileError(detail.file)) errors.push(`Transaksi ${index+1}: ${fileError(detail.file)}`);
    }
  }
  return errors;
}
export function validatePhase(report,phase) {
  const errors=[], p=report.pelapor;
  if(phase===1) {
    for(const [key,label] of PELAPOR_FIELDS) if(!String(p[key]||'').trim()) errors.push(`${label} wajib diisi.`);
    if(!p.jenis_kelamin) errors.push('Pilih jenis kelamin pelapor.');
    if(!past(p.tanggal_lahir)) errors.push('Tanggal lahir harus valid dan tidak di masa depan.');
    if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p.email)) errors.push('Format email belum sesuai.');
    if(p.email!==p.konfirmasi_email) errors.push('Konfirmasi email tidak sama.');
    if(!/^[0-9]{8,15}$/.test(p.telepon)) errors.push('Nomor telepon harus terdiri dari 8–15 digit.');
    if(p.telepon!==p.konfirmasi_telepon||p.kode_telepon!==p.konfirmasi_kode_telepon) errors.push('Konfirmasi nomor telepon tidak sama.');
    if(p.jenis_identitas==='KTP'&&!/^[0-9]{16}$/.test(p.nomor_identitas)) errors.push('Nomor KTP harus terdiri dari 16 digit.');
    if(fileError(report.files.identitas,1)) errors.push('Kartu identitas korban: '+fileError(report.files.identitas,1));
    if(p.sendiri==='tidak') {
      if(!report.korban.nama||!report.korban.identitas||!report.korban.hubungan) errors.push('Lengkapi nama, identitas, dan hubungan dengan korban yang diwakili.');
      if(fileError(report.files.kuasa,1)) errors.push('Surat kuasa: '+fileError(report.files.kuasa,1));
    }
  }
  if(phase===2) {
    if(!report.terlapor.length) errors.push('Tambahkan minimal satu informasi terlapor.');
    if(!report.media.length) errors.push('Tambahkan minimal satu sumber / media informasi penipuan.');
    report.terlapor.forEach(row=>errors.push(...validateRecord('terlapor',row)));
    report.media.forEach(row=>errors.push(...validateRecord('media',row)));
  }
  if(phase===3) {
    if(!past(report.kejadian.tanggal)||!/[T ][0-9]{2}:[0-9]{2}/.test(report.kejadian.tanggal)) errors.push('Isi tanggal dan waktu kejadian yang valid.');
    if(report.kejadian.kronologi.trim().length<20||report.kejadian.kronologi.length>4000) errors.push('Kronologi harus berisi 20–4000 karakter.');
    if(fileError(report.files.kejadian)) errors.push('Bukti pendukung kejadian: '+fileError(report.files.kejadian));
    if(report.files.polisi&&fileError(report.files.polisi)) errors.push(fileError(report.files.polisi));
  }
  if(phase===4) {
    if(!report.transaksi.bank) errors.push('Pilih penyelenggara layanan korban.');
    if(!/^[0-9]{6,30}$/.test(report.transaksi.rekening)) errors.push('Rekening / akun korban harus terdiri dari 6–30 digit.');
    if(!report.transaksi.nama.trim()) errors.push('Nama pemilik rekening korban wajib diisi.');
    if(fileError(report.files.rekening)) errors.push('Bukti kepemilikan rekening: '+fileError(report.files.rekening));
    if(!report.transaksi.penerima.length) errors.push('Tambahkan minimal satu penyelenggara terlapor.');
    report.transaksi.penerima.forEach(row=>errors.push(...validateRecord('penerima',row)));
  }
  if(phase===5&&!report.reviewed) errors.push('Centang pernyataan tinjauan data simulasi terlebih dahulu.');
  return [...new Set(errors)];
}
export function metadata(report) {return JSON.parse(JSON.stringify(report,(key,value)=>['blob','url'].includes(key)?undefined:value));}
export function applyChat(report,data,evidence=null) {
  if(!data||typeof data!=='object'||Array.isArray(data)) return 0;
  let count=0;
  const set=(target,key,value)=>{if(!target[key]&&typeof value==='string'&&value.trim()&&value.length<=4000){target[key]=value.trim();count++;}};
  const p=report.pelapor;
  for(const [target,source] of [['nama','pelapor_nama'],['email','pelapor_email'],['nomor_identitas','pelapor_nik'],['alamat','pelapor_alamat']]) set(p,target,data[source]);
  if(data.pelapor_nik&&!p.jenis_identitas) set(p,'jenis_identitas','KTP');
  if(typeof data.pelapor_telepon==='string') set(p,'telepon',data.pelapor_telepon.replace(/^\+62/,''));
  if(p.email) set(p,'konfirmasi_email',p.email);
  if(p.telepon) set(p,'konfirmasi_telepon',p.telepon);
  set(report.kejadian,'kronologi',data.kronologi);
  for(const [target,source] of [['bank','bank_pengirim'],['rekening','rekening_pengirim']]) set(report.transaksi,target,data[source]);
  if(!report.transaksi.penerima.length&&typeof data.bank_penerima==='string'&&typeof data.rekening_penerima==='string'&&typeof data.terlapor_nama==='string'&&typeof data.waktu_transaksi==='string'&&Number.isSafeInteger(data.nominal)&&evidence&&!fileError(evidence)) {
    const row={bank:data.bank_penerima,rekening:data.rekening_penerima,nama:data.terlapor_nama,details:[{waktu:data.waktu_transaksi.slice(0,16),nominal:String(data.nominal),rrn:typeof data.rrn==='string'?data.rrn:'',file:evidence}]};
    if(!validateRecord('penerima',row).length){report.transaksi.penerima.push(row);count++;}
  }
  report.reviewed=false;
  return count;
}

const MONTHS_ID=['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
export function localDate(value,withTime=false){
  if(typeof value!=='string')return '';
  if(/^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value))return value.slice(0,withTime?16:10);
  const match=value.match(/^(\d{1,2}) ([A-Za-z]+) (\d{4})(?: (\d{2}:\d{2})(?::\d{2})?)?$/);
  const month=match?MONTHS_ID.findIndex(name=>name.toLowerCase()===match[2].toLowerCase()):-1;
  return month<0?'':`${match[3]}-${String(month+1).padStart(2,'0')}-${match[1].padStart(2,'0')}${withTime?'T'+(match[4]||'00:00'):''}`;
}
export function applyChatV1(report,data,resolveFile=()=>null){
  if(!data||typeof data!=='object'||Array.isArray(data))return 0;
  let count=0;
  const fill=(target,key,value)=>{if((target[key]===undefined||target[key]===null||target[key]==='')&&typeof value==='string'&&value.trim()&&value.length<=4000){target[key]=value.trim();count++;}};
  const file=(target,key,metadata,limit=2)=>{const value=resolveFile(metadata);if(!target[key]&&value&&!fileError(value,limit)){target[key]=value;count++;}};
  const one=data.tahap1||{},two=data.tahap2||{},three=data.tahap3||{},four=data.tahap4||{};
  const p=report.pelapor;
  for(const [key,source] of [['jenis_kelamin','jenis_kelamin'],['kewarganegaraan','kewarganegaraan_pelapor'],['nama','nama_pelapor'],['tempat_lahir','tempat_lahir_pelapor'],['agama','agama_pelapor'],['pekerjaan','pekerjaan_pelapor'],['telepon','nomor_telepon_pelapor'],['email','email_pelapor'],['jenis_identitas','jenis_identitas'],['nomor_identitas','nomor_identitas'],['provinsi','provinsi_domisili_pelapor'],['kota','kota_domisili_pelapor'],['alamat','alamat_pelapor']])fill(p,key,one[source]);
  fill(p,'tanggal_lahir',localDate(one.tanggal_lahir_pelapor));
  fill(p,'konfirmasi_telepon',p.telepon);fill(p,'konfirmasi_email',p.email);
  file(report.files,'identitas',one.upload_kartu_identitas_korban,1);
  if(!report.terlapor.length&&Array.isArray(two.daftar_informasi_terlapor)){
    for(const item of two.daftar_informasi_terlapor.slice(0,50)){
      const row={kode:(item.kode_nomor_terlapor||'').match(/\+\d+/)?.[0]||'+62',nomor:item.nomor_terlapor,nama:item.nama_terlapor,file:resolveFile(item.upload_bukti_komunikasi)};
      if(!validateRecord('terlapor',row).length){report.terlapor.push(row);count++;}
    }
  }
  if(!report.media.length&&Array.isArray(two.daftar_sumber_media_penipuan)){
    for(const item of two.daftar_sumber_media_penipuan.slice(0,50)){
      const row={sumber:item.sumber_media_informasi_penipuan,detail:item.detail_sumber_media_informasi_penipuan,file:resolveFile(item.upload_bukti_sumber_media)};
      if(!validateRecord('media',row).length){report.media.push(row);count++;}
    }
  }
  fill(report.kejadian,'tanggal',localDate(three.tanggal_dan_waktu_kejadian,true));fill(report.kejadian,'kronologi',three.kronologi_kejadian_penipuan);
  file(report.files,'kejadian',three.upload_bukti_pendukung_kejadian);file(report.files,'polisi',three.upload_laporan_kepolisian);
  for(const [key,source] of [['bank','nama_penyelenggara_layanan_korban'],['rekening','nomor_rekening_akun_korban'],['nama','nama_pemilik_rekening_akun_korban']])fill(report.transaksi,key,four[source]);
  file(report.files,'rekening',four.bukti_kepemilikan_rekening_akun_korban);
  if(!report.transaksi.penerima.length&&Array.isArray(four.daftar_penyelenggara_terlapor)){
    for(const item of four.daftar_penyelenggara_terlapor.slice(0,50)){
      const row={bank:item.nama_penyelenggara,rekening:item.nomor_rekening_akun,nama:item.nama_pemilik_rekening_akun,details:(item.daftar_rincian_transaksi||[]).slice(0,50).map(detail=>({waktu:localDate(detail.waktu_transaksi,true),nominal:canonicalAmount(detail.nominal_transaksi),file:resolveFile(detail.upload_bukti_pendukung_kejadian)}))};
      if(!validateRecord('penerima',row).length){report.transaksi.penerima.push(row);count++;}
    }
  }
  report.reviewed=false;
  return count;
}

export function referencesFile(value,file){
  if(!value||typeof value!=='object'||!file?.url)return false;
  if(value.url===file.url)return true;
  return Object.values(value).some(child=>referencesFile(child,file));
}

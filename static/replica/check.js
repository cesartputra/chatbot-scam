const $=id=>document.getElementById(id);
function read(){try{const rows=JSON.parse(localStorage.getItem('iasc-local-reports')||'[]');return Array.isArray(rows)?rows.filter(row=>row&&row.simulated===true&&row.submitted===false&&typeof row.id==='string'):[];}catch{return [];}}
function result(id){
  const row=read().find(row=>row.id===id.trim());const node=$('check-result');node.replaceChildren();
  const box=document.createElement('div');box.className='alert '+(row?'alert-success':'alert-warning');
  if(!row)box.textContent='Nomor simulasi tidak ditemukan pada browser ini.';
  else{
    const heading=document.createElement('h5');heading.textContent='Simulasi tersimpan — belum dikirim ke IASC';
    const number=document.createElement('p');number.className='success-number';number.textContent=row.id;
    const detail=document.createElement('p');detail.textContent=(row.data?.pelapor?.nama||'Pelapor dummy')+' · '+new Date(row.generated_at).toLocaleString('id-ID');
    const button=document.createElement('button');button.className='btn btn-outline-danger btn-sm';button.textContent='Hapus simulasi ini';
    button.addEventListener('click',()=>{if(!confirm('Hapus permanen hasil simulasi ini dari browser?'))return;try{localStorage.setItem('iasc-local-reports',JSON.stringify(read().filter(item=>item.id!==row.id)));location.reload();}catch{box.textContent='Browser tidak dapat menghapus data. Coba pengaturan penyimpanan browser.';}});
    box.append(heading,number,detail,button);
  }
  node.append(box);
}
$('check-form').addEventListener('submit',event=>{event.preventDefault();result($('report-number').value);});
const rows=read();
if(rows.length){const heading=document.createElement('p');heading.textContent='Simulasi pada browser ini:';$('saved-reports').append(heading);for(const row of rows){const button=document.createElement('button');button.type='button';button.className='btn btn-sm btn-outline-danger me-2 mb-2';button.textContent=row.id;button.addEventListener('click',()=>{$('report-number').value=row.id;result(row.id);});$('saved-reports').append(button);}}
const initial=new URLSearchParams(location.search).get('id');if(initial){$('report-number').value=initial;result(initial);}

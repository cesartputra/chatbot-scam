const header = document.getElementById('site-header');
header.innerHTML = `<div class="simulation-strip"><span>SIMULASI LOKAL · Bukan layanan resmi OJK · Gunakan data dummy</span><a href="/widget/iasc-ai-widget.html">Buka asisten ↗</a></div><nav class="navbar navbar-expand-lg bg-white shadow-sm"><div class="container"><a class="navbar-brand d-flex align-items-center gap-2" href="/"><img src="/static/replica/assets/iasc.png" alt="IASC"><img src="/static/replica/assets/pasti.png" alt="Satgas PASTI"></a><button class="navbar-toggler" type="button" id="nav-toggle" aria-expanded="false" aria-controls="site-nav" aria-label="Buka navigasi"><span class="navbar-toggler-icon"></span></button><div class="site-nav" id="site-nav"><a href="/#tentang">Tentang IASC</a><a href="/#privasi">Kebijakan Privasi</a><a href="/#faq">FAQ</a><a href="/#hubungi">Hubungi Kami</a><a class="btn btn-danger btn-sm" href="/Guest/LaporanV2">Laporkan Penipuan</a></div></div></nav>`;
document.getElementById('nav-toggle').addEventListener('click', event => {
  const open = document.getElementById('site-nav').classList.toggle('open');
  event.currentTarget.setAttribute('aria-expanded', String(open));
});
document.getElementById('site-footer').innerHTML = '<p>Replika lokal untuk demonstrasi · Referensi UI: IASC / OJK</p><small>Tidak mengirim laporan, email, atau instruksi pemblokiran rekening.</small>';

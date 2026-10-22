#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f .venv/.requirements-installed ] || ! cmp -s requirements.txt .venv/.requirements-installed; then
  if ! .venv/bin/python -m pip install --timeout 60 --retries 5 -r requirements.txt; then
    cat >&2 <<'MESSAGE'

Instalasi dependensi gagal; server belum dijalankan.
Jika log berisi ConnectionResetError / Connection reset by peer, pip belum
berhasil mengakses indeks paket. Pesan "from versions: none" pada kondisi ini
belum membuktikan versi paket tidak tersedia.
Coba indeks PyPI resmi:
  PIP_INDEX_URL=https://pypi.org/simple bash start.sh
Jika koneksi tetap diputus, coba jaringan lain (misalnya hotspot) dan periksa
konfigurasi proxy/VPN. Jika ada pesan Requires-Python, gunakan Python 3.11+.
MESSAGE
    exit 1
  fi
  cp requirements.txt .venv/.requirements-installed
fi
exec .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port "${PORT:-8787}" --workers 1 --no-access-log

#!/bin/bash
# self-signed cert for 127.0.0.1 (WSL /tmp, 재생 전용)
set -e
D=/root/se_mirror_tls
mkdir -p "$D"
if [ ! -f "$D/cert.pem" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$D/key.pem" -out "$D/cert.pem" -days 14 \
    -subj "/CN=127.0.0.1" -addext "subjectAltName=IP:127.0.0.1" >/dev/null 2>&1
fi
chmod 600 "$D/key.pem"
ls -l "$D"

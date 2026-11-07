#!/bin/bash
# 127.0.0.1 용 self-signed 인증서를 <dir> 에 만든다 (재생 전용, 14일, 저장소 밖 임시 디렉터리에만 - 커밋 금지).
# 사용: gen_cert.sh <dir>
set -e
D="${1:?usage: gen_cert.sh <dir>}"
mkdir -p "$D"
if [ ! -f "$D/cert.pem" ] || [ ! -f "$D/key.pem" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$D/key.pem" -out "$D/cert.pem" -days 14 \
    -subj "/CN=127.0.0.1" -addext "subjectAltName=IP:127.0.0.1" >/dev/null 2>&1
fi
chmod 600 "$D/key.pem"
ls -l "$D"

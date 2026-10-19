#!/bin/sh
# Runs from /docker-entrypoint.d/ before nginx starts. Browsers hand the
# microphone only to a secure page, so the web UI is served over https unless
# STT_WWW_SCHEME says http. A self-signed certificate is enough for live capture
# from an audio device, and this script mints one on the first start when the
# certs directory (bind-mounted from ./data/certs) holds none. The pair is kept,
# so the exception a browser stores for it survives restarts. Mount a real
# certificate under the same two names to replace it.
set -eu

CERT_DIR=/etc/nginx/certs
CERT="$CERT_DIR/stt.crt"
KEY="$CERT_DIR/stt.key"

# An http UI has no listener to use it.
if [ "$(printf '%s' "${STT_WWW_SCHEME:-https}" | tr '[:upper:]' '[:lower:]')" = http ]; then
    exit 0
fi

if [ -s "$CERT" ] && [ -s "$KEY" ]; then
    exit 0
fi

mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -subj "/CN=stt_www" \
    -addext "subjectAltName=DNS:stt_www,DNS:localhost,IP:127.0.0.1" \
    -keyout "$KEY" -out "$CERT" >/dev/null 2>&1
echo "[selfsigned-cert] generated $CERT"

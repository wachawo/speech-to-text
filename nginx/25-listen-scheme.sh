#!/bin/sh
# Runs from /docker-entrypoint.d/ before nginx starts. The web UI has one port,
# and STT_WWW_SCHEME decides what it speaks: https (the default) or http.
# Browsers hand the microphone only to a secure page, so on http the DEVICE tab
# works on localhost alone. The listener goes into a file the server block of
# default.conf includes, because envsubst can fill in a value but not choose
# between two blocks. Anything but the two names stops the container: a typo
# must not quietly serve the UI in the clear.
set -eu

SCHEME=$(printf '%s' "${STT_WWW_SCHEME:-https}" | tr '[:upper:]' '[:lower:]')
LISTEN=/etc/nginx/listen.conf

case "$SCHEME" in
    https)
        cat > "$LISTEN" <<'CONF'
listen 8080 ssl;
ssl_certificate     /etc/nginx/certs/stt.crt;
ssl_certificate_key /etc/nginx/certs/stt.key;
ssl_protocols       TLSv1.2 TLSv1.3;
# Plain http sent to the https port is answered with a redirect to the same
# address over https instead of nginx's 400 page. $http_host keeps the port
# the browser used, which the container cannot know.
error_page 497 =301 https://$http_host$request_uri;
CONF
        ;;
    http)
        echo "listen 8080;" > "$LISTEN"
        ;;
    *)
        echo "[listen-scheme] STT_WWW_SCHEME must be https or http, not '$SCHEME'" >&2
        exit 1
        ;;
esac
echo "[listen-scheme] serving $SCHEME"

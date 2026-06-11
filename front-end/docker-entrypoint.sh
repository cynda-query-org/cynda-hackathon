#!/bin/sh
set -e

: "${BACKEND_URL:?BACKEND_URL env var is required}"

sed -i "s|__BACKEND_URL__|${BACKEND_URL}|g" \
    /usr/share/nginx/html/app.js \
    /usr/share/nginx/html/index.html \
    /usr/share/nginx/html/pages/demo.html \
    /usr/share/nginx/html/pages/login.html \
    /usr/share/nginx/html/pages/connect.html \
    /usr/share/nginx/html/pages/reset.html \
    /usr/share/nginx/html/pages/settings.html \
    /usr/share/nginx/html/pages/dashboard.html

exec /docker-entrypoint.sh "$@"

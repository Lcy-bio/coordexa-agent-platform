#!/bin/sh
set -eu

cat >/usr/share/nginx/html/runtime-config.js <<EOF
window.__COORDEXA_CONFIG__ = {
  apiUrl: "${COORDEXA_API_URL:-/api}"
};
EOF

exec nginx -g "daemon off;"

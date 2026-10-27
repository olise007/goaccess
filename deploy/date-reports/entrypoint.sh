#!/bin/sh
# Supervise the live parser, snapshot API and nginx as one monitoring service.
set -eu
set -- /var/log/apache2/laravel_access.log '--log-format=%h %^[%x] "%r" %s %b "%R" "%u"' \
  '--datetime-format=%d/%b/%Y:%H:%M:%S %z' \
  --real-time-html --output=/usr/share/nginx/html/live.html \
  --ws-url="${WS_URL:?Set WS_URL to the browser-reachable WebSocket address}" --tz=Africa/Lagos
if [ -f /usr/share/GeoIP/dbip-country-lite.mmdb ]; then
  set -- "$@" --geoip-database=/usr/share/GeoIP/dbip-country-lite.mmdb
fi
goaccess "$@" &
live_pid=$!
python3 /opt/monitoring/server.py &
api_pid=$!
nginx -g 'daemon off;' &
nginx_pid=$!
# Any child exit shuts down the container, allowing Docker to restart it.
trap 'kill "$live_pid" "$api_pid" "$nginx_pid" 2>/dev/null || true' INT TERM EXIT
while kill -0 "$live_pid" 2>/dev/null && kill -0 "$api_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
  sleep 1
done
exit 1

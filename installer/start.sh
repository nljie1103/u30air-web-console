#!/system/bin/sh
set -u
BASE=/data/local/tmp/android-web-desktop
ADDR="${1:-192.168.0.1:8765}"
[ -x "$BASE/current" ] || { echo "Missing executable: $BASE/current"; exit 1; }
if [ -f "$BASE/server.pid" ]; then
  PID="$(cat "$BASE/server.pid")"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "Server is already running (PID $PID)"
    exit 0
  fi
fi
if command -v nohup >/dev/null 2>&1; then
  nohup "$BASE/current" -listen "$ADDR" -state-dir "$BASE" >> "$BASE/server.log" 2>&1 < /dev/null &
else
  "$BASE/current" -listen "$ADDR" -state-dir "$BASE" >> "$BASE/server.log" 2>&1 < /dev/null &
fi
echo "Launch requested: $ADDR (PID $!)"

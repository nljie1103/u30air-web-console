#!/system/bin/sh
BASE=/data/local/tmp/android-web-desktop
if [ -f "$BASE/server.pid" ]; then
  PID="$(cat "$BASE/server.pid")"
  if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; fi
  rm -f "$BASE/server.pid"
fi
echo "Stop signal sent"

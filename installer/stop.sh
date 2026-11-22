#!/system/bin/sh
set -u
BASE=/data/local/tmp/android-web-desktop
PIDFILE="$BASE/server.pid"
[ -f "$PIDFILE" ] || { echo "Service is not running"; exit 0; }
PID="$(cat "$PIDFILE")"
case "$PID" in
  ''|*[!0-9]*) echo "Invalid service PID"; exit 1 ;;
esac
[ "$PID" -gt 1 ] || { echo "Unsafe service PID"; exit 1; }
if kill -0 "$PID" 2>/dev/null; then
  # A stale PID might belong to an unrelated system process. Fail closed.
  PROCESS="$(tr '\000' ' ' < "/proc/$PID/cmdline" 2>/dev/null || true)"
  case "$PROCESS" in
    *"$BASE"*) ;;
    *) echo "PID does not belong to this service; refusing to signal it"; exit 1 ;;
  esac
  kill "$PID" 2>/dev/null || { echo "Could not stop service"; exit 1; }
  n=0
  while kill -0 "$PID" 2>/dev/null; do
    n=$((n + 1))
    [ "$n" -lt 30 ] || { echo "Service did not exit"; exit 1; }
    sleep 0.1
  done
fi
rm -f "$PIDFILE"
echo "Service stopped"

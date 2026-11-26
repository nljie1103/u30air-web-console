#!/system/bin/sh
set -eu
BASE=/data/local/tmp/android-web-desktop
ADDR="${1:-192.168.0.1:8765}"
[ -x "$BASE/current" ] || { echo "Missing executable: $BASE/current"; exit 1; }
case "$(readlink "$BASE/current")" in
  releases/[012].*/desktopd)
    if [ -f "$BASE/server.pid" ]; then
      PID="$(cat "$BASE/server.pid")"
      case "$PID" in ''|*[!0-9]*) exit 1 ;; esac
      [ "$PID" -gt 1 ] || exit 1
      if [ -d "/proc/$PID" ]; then
        EXE="$(readlink "/proc/$PID/exe")" || exit 1
        [ "$EXE" = "$BASE/$(readlink "$BASE/current")" ] || { echo "Stale service PID"; exit 1; }
        echo "Server is already running"; exit 1
      fi
    fi ;;
  *)
    STATUS="$("$BASE/current" -service-action status -state-dir "$BASE")" || exit 1
    [ "$STATUS" = stopped ] || { echo "Server is already running"; exit 1; } ;;
esac
if command -v nohup >/dev/null 2>&1; then
  nohup "$BASE/current" -listen "$ADDR" -state-dir "$BASE" >> "$BASE/server.log" 2>&1 < /dev/null &
else
  "$BASE/current" -listen "$ADDR" -state-dir "$BASE" >> "$BASE/server.log" 2>&1 < /dev/null &
fi
echo "Launch requested: $ADDR (PID $!)"

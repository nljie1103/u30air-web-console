#!/system/bin/sh
set -eu
BASE=/data/local/tmp/android-web-desktop
[ -x "$BASE/current" ] || { echo "Missing managed service executable"; exit 1; }
case "$(readlink "$BASE/current")" in
  releases/[012].*/desktopd)
    if [ -f "$BASE/server.pid" ]; then
      PID="$(cat "$BASE/server.pid")"
      case "$PID" in ''|*[!0-9]*) exit 1 ;; esac
      [ "$PID" -gt 1 ] || exit 1
      if [ -d "/proc/$PID" ]; then
        EXE="$(readlink "/proc/$PID/exe")" || exit 1
        [ "$EXE" = "$BASE/$(readlink "$BASE/current")" ] || { echo "Stale service PID"; exit 1; }
        START="$(awk '{print $22}' "/proc/$PID/stat")" || exit 1
        [ -n "$START" ] || exit 1
        [ "$(awk '{print $22}' "/proc/$PID/stat")" = "$START" ] || exit 1
        kill "$PID" || exit 1
        n=0
        while [ -d "/proc/$PID" ] && [ "$(awk '{print $22}' "/proc/$PID/stat" 2>/dev/null || true)" = "$START" ]; do
          n=$((n+1)); [ "$n" -lt 50 ] || exit 1
          sleep 0.1
        done
      fi
      rm -f "$BASE/server.pid" "$BASE/server.identity"
    fi ;;
  *) "$BASE/current" -service-action stop -state-dir "$BASE" ;;
esac
echo "Service stopped"

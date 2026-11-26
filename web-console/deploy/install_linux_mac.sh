#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SERIAL="${1:-}"
IP="${2:-}"
PORT="${3:-8765}"
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] || { echo "Invalid web port"; exit 1; }
PORT=$((10#$PORT))
(( PORT >= 1024 && PORT <= 65535 )) || { echo "Invalid web port"; exit 1; }
private_ipv4() {
  local a b c d
  [[ "$1" =~ ^(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})$ ]] || return 1
  IFS=. read -r a b c d <<< "$1"
  (( a<=255 && b<=255 && c<=255 && d<=255 )) || return 1
  (( a==10 || (a==192 && b==168) || (a==172 && b>=16 && b<=31) ))
}
if [[ -n "$IP" ]]; then private_ipv4 "$IP" || { echo "Invalid private IPv4"; exit 1; }; fi
VER="$(cat VERSION)"
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION"; exit 1; }
command -v adb >/dev/null || { echo "ADB is not installed"; exit 1; }
echo "ADB device list:"
adb devices -l
if [[ -z "$SERIAL" ]]; then
  DEVICES=()
  while IFS= read -r device; do DEVICES+=("$device"); done < <(adb devices | awk '$2=="device" {print $1}')
  if [[ ${#DEVICES[@]} -ne 1 ]]; then echo "Pass the ADB serial as the first argument"; exit 1; fi
  SERIAL="${DEVICES[0]}"
fi
[[ "$(adb -s "$SERIAL" get-state | tr -d '\r')" == "device" ]] || { echo "ADB target unavailable"; exit 1; }
[[ "$(adb -s "$SERIAL" shell getprop ro.product.cpu.abi | tr -d '\r')" == "arm64-v8a" ]] || { echo "ARM64 is required"; exit 1; }
if [[ -z "$IP" ]]; then
  echo "Device LAN IPv4 addresses:"
  adb -s "$SERIAL" shell ip -o -4 addr show || true
  read -rp "Enter the device's private LAN IPv4 address: " IP
fi
private_ipv4 "$IP" || { echo "A private LAN IPv4 is required"; exit 1; }
ASSIGNED="$(adb -s "$SERIAL" shell ip -o -4 addr show | tr -d '\r')"
awk -v ip="$IP" '{split($4,a,"/");if ($3=="inet" && a[1]==ip) found=1} END{exit !found}' <<< "$ASSIGNED" || { echo "IP is not assigned to device"; exit 1; }
BASE=/data/local/tmp/android-web-desktop
CURRENT="$(adb -s "$SERIAL" shell readlink "$BASE/current" 2>/dev/null | tr -d '\r' || true)"
if [[ "$CURRENT" == "releases/$VER/desktopd" ]]; then
  echo "Same version is already installed; use the Windows Manager for a safe reinstall."
  exit 1
fi
adb -s "$SERIAL" shell mkdir -p "$BASE/releases/$VER"
# Upload to temporary paths; never overwrite an executable during transfer.
adb -s "$SERIAL" push desktopd "$BASE/releases/$VER/desktopd.next"
adb -s "$SERIAL" push installer/start.sh "$BASE/start.sh.next"
adb -s "$SERIAL" push installer/stop.sh "$BASE/stop.sh.next"
adb -s "$SERIAL" shell chmod 700 "$BASE/releases/$VER/desktopd.next" "$BASE/start.sh.next" "$BASE/stop.sh.next"
# The candidate performs a single transaction on-device and verifies readiness.
adb -s "$SERIAL" shell "$BASE/releases/$VER/desktopd.next" -deploy-version "$VER" -listen "$IP:$PORT" -state-dir "$BASE"
echo "Web console: http://$IP:$PORT"
echo "Existing login settings preserved. For a first installation, read password.txt using authorized ADB."

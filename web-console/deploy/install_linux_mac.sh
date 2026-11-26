#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SERIAL="${1:-}"
IP="${2:-}"
PORT="${3:-8765}"
VER="$(cat VERSION)"
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid VERSION"; exit 1; }
command -v adb >/dev/null || { echo "ADB is not installed"; exit 1; }
echo "ADB device list:"
adb devices -l
if [[ -z "$SERIAL" ]]; then
  mapfile -t DEVICES < <(adb devices | awk '$2=="device" {print $1}')
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
[[ "$IP" =~ ^(10\.[0-9.]+|192\.168\.[0-9.]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9.]+)$ ]] || { echo "A private LAN IPv4 is required"; exit 1; }
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
if [[ "$CURRENT" =~ ^releases/[0-9]+\.[0-9]+\.[0-9]+/desktopd$ ]]; then
  adb -s "$SERIAL" shell sh "$BASE/stop.sh"
fi
adb -s "$SERIAL" shell mv -f "$BASE/releases/$VER/desktopd.next" "$BASE/releases/$VER/desktopd"
adb -s "$SERIAL" shell mv -f "$BASE/start.sh.next" "$BASE/start.sh"
adb -s "$SERIAL" shell mv -f "$BASE/stop.sh.next" "$BASE/stop.sh"
adb -s "$SERIAL" shell rm -f "$BASE/current.new"
adb -s "$SERIAL" shell ln -s "releases/$VER/desktopd" "$BASE/current.new"
adb -s "$SERIAL" shell mv -f "$BASE/current.new" "$BASE/current"
adb -s "$SERIAL" shell sh "$BASE/start.sh" "$IP:$PORT"
echo "Open http://$IP:$PORT"
sleep 2
echo "Login password:"
adb -s "$SERIAL" shell cat "$BASE/password.txt"

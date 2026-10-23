#!/bin/bash
# macOS/Linux port of pull-sweetlog.ps1. Read-only on the phone (TWRP).
#   ANDROID_SERIAL=<serial> pull-sweetlog.sh NAME
# -> logs/sweetlog-NAME.txt (kernel console ring: last 1025 blocks of USERDATA)
#    logs/pmsg-NAME.txt     (loader + early kernel text, ramoops pmsg)
set -euo pipefail
name=${1:?name, e.g. boot32}
: "${ANDROID_SERIAL:?set ANDROID_SERIAL to the S8 serial (adb devices -l)}"
export ANDROID_SERIAL
repo=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$repo/logs"
size=$(adb shell 'blockdev --getsize64 /dev/block/sda24' | tr -d '\r')
# TWRP's shell arithmetic is 32-bit; 55 GB overflows (it once computed a
# negative skip). Do the division here and pass a literal block count.
skip=$(( size / 4096 - 1025 ))
adb shell "dd if=/dev/block/sda24 of=/tmp/slog.bin bs=4096 skip=$skip count=1025 2>/dev/null"
adb pull /tmp/slog.bin "$repo/logs/sweetlog-$name.bin" >/dev/null
# pmsg survives a warm reboot only; after a forced power cycle pstore is empty.
adb pull /sys/fs/pstore/pmsg-ramoops-0 "$repo/logs/pmsg-$name.txt" >/dev/null ||
	echo "no pmsg-ramoops-0 (pstore empty after this reboot)" >&2
python3 "$repo/tools/sweet-log.py" "$repo/logs/sweetlog-$name.bin" "$repo/logs/sweetlog-$name.txt"
echo "kernel log: logs/sweetlog-$name.txt"
echo "pmsg log:   logs/pmsg-$name.txt"

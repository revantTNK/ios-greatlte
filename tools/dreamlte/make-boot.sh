#!/bin/bash
# Kernel Mach-O -> Galaxy S8 BOOT image.
#   make-boot.sh KERNEL STOCK_BOOT.img OUT.img [boot-args...]
# Default boot-args: one CPU, verbose console, no watchdog; no root device
# yet, so the first trials end in a root-mount panic by design.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
# macOS realpath has no -m (and the output file does not exist yet): resolve in Python.
abspath() { python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
kernel=$(abspath "$1"); stock=$(abspath "$2"); out=$(abspath "$3")
shift 3
# a5touchprobe=0: the A5 touch probe maps Exynos7580 I2C/GPIO; on the S8 its
# first read is a synchronous external abort (boot 8, a5xelte_touch_probe).
args=${*:-debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress wdt=-1 wdt_test=no_user_checkin a5touchprobe=0}
work=$repo/shim/dreamlte/out
mkdir -p "$work"
# The ADT canvas must match the size the kernel presents (SweetFramebuffer).
canvas=1125x2436
[[ " $args " == *" sweetfb_native=1 "* ]] && canvas=1440x2960
# S8_DRAM_MIB: RAM for XNU (default 512, at most 4096 - the whole high DRAM
# bank on the Note 8, 2048 on the S8; tools/mkadt_dreamlte.py).
python3 "$repo/tools/mkadt_dreamlte.py" "$work/dreamlte.adt" --canvas "$canvas" --dram-mib "${S8_DRAM_MIB:-512}"
python3 "$repo/tools/mkpayload.py" "$kernel" "$work/dreamlte.adt" "$work/payload.bin" --cmdline "$args"
bash "$repo/shim/dreamlte/build.sh" "$stock" "$work/payload.bin" "$out"
python3 "$repo/tools/dreamlte_bootimg_info.py" "$out" | head -4

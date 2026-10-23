# ios-greatlte: iOS on the Samsung Galaxy Note 8

**iOS 16.7.16 on the Samsung Galaxy Note 8, Exynos 8895 (`greatlte`): SM-N950F, SM-N950FD and SM-N950N.**

This fork retargets the XNU port from the Galaxy S8 (`dreamlte`) to the Galaxy Note 8. The Note 8 is the same Exynos 8895 platform: same memory map, same 1440×2960 panel path, same S2MPS17 PMIC, same UFS layout. The inherited S8 loader, kernel and iPhone X root filesystem therefore boot on it. The parts that differ are the touch controller (Samsung **y661** instead of the S8's S6SY761), the S Pen, the larger battery and the 6 GiB of RAM.

> **Status (2026-10-23):** with the inherited S8 BOOT image, iOS 16.7.16 boots and renders on the Note 8; the display, buttons and charging indicator work. **Touch does not work yet.** The y661 answers on I2C (`id52 = 0xacb661`, device ID `53 45 b6 61 00`) and its firmware is valid, but the function/sense writes are rejected while it is in low-power mode. An LPM-exit image is flashed and read back; its loader output has not been read yet. Details and exact hashes: [DREAMLTE_PROGRESS.md](DREAMLTE_PROGRESS.md).

> Fork of [iamv4g/galaxios8](https://github.com/iamv4g/galaxios8), itself a fork of [Floppikrob/ios-galaxy-s8](https://github.com/Floppikrob/ios-galaxy-s8). Port history up to S8 boot 31 and all S8 hardware bring-up are from those projects; see [Authors](#authors).

> ⚠️ Experimental bring-up, not a usable phone OS. It is very slow and much is missing (see [Known bugs](#known-bugs)). Installing it **erases the USERDATA partition** (all Android data). Exynos Note 8 only: see [Supported models](#supported-models).

## Supported models

| Model | SoC | Board | State |
| --- | --- | --- | --- |
| **SM-N950F** (international) | Exynos 8895 | `greatlte` | Bring-up target |
| **SM-N950FD** (dual SIM) | Exynos 8895 | `greatlte` | Same board; not separately tested |
| **SM-N950N** (Korea) | Exynos 8895 | `greatlte` | Same board; not separately tested |
| SM-N950U / U1 / W, SM-N9500 / N9508, SC-01K / SCV37 | Snapdragon 835 | `greatqlte` | **Not supported** (different SoC) |
| Galaxy S8 / S8+ (`dreamlte` / `dream2lte`) | Exynos 8895 | — | Not this fork; the S8 is the source port |

Only the Exynos `greatlte` board is targeted. The phone in this fork's tests reports `ro.product.device=greatlte` and `ro.product.model=Galaxy Note8` in TWRP. Android props can lie on ROMs ported from other models, so also check the bootloader version (`N950F…`, `N950N…`) and `/proc/device-tree/model` (it should identify the greatlte board) before writing anything.

## Hardware

Read from Samsung's `exynos8895-greatlte_common.dtsi` (`exynos-linux-stable/greatlte`, `tw90-android`) and measured on the phone where noted.

| Block | Part / address | Notes |
| --- | --- | --- |
| CPU | 4× Cortex-A53 (MPIDR 0x100–0x103) + 4× Mongoose M2 | Same PSCI/GIC-400/26 MHz timer setup as the S8; only the A53s run today |
| RAM | 6 GiB (Samsung spec) | XNU currently gets 512 MiB of the upper bank at `0x880000000` |
| Storage | UFS; BOOT `sda7` = 41 943 040 bytes, USERDATA `sda24` = 55 254 167 552 bytes | Both sizes measured in TWRP on the Note 8 |
| Display | DECON_F `0x12860000`, framebuffer `0xcc000000`, 1440×2960 XRGB, command mode | Same as the S8 |
| Touch | Samsung **y661** (`sec_ts_y661`, firmware `tsp_sec/y661_great.fw`, project `GREAT`/`N950`) at `0x48` on USI09 HSI2C `0x108e0000`, IRQ gpa1-0 | S2MPS17 LDO34 `tsp_io` 1.85 V, LDO35 `tsp_avdd` **3.3 V**. Registers and the 8-byte event format are shared with the S8's S6SY761; `SW_RESET` is 0x42 (S6SY761: 0x12) |
| S Pen | Wacom W9018 on hsi2c_10 `0x10490000` | Not an iOS input path yet |
| PMIC | S2MPS17 over SPEEDY `0x15b50000`: BUCK2/BUCK3, LDO34/35, RTC | Same as the S8 |
| Battery | MAX77865 on `hsi2c_32`: gauge `0x36`, charger `0x69`; 3300 mAh (Samsung spec) | The kernel still reports the S8's 3000 mAh design capacity |
| Buttons | Power, volume up/down, Bixby (ALIVE GPIOs) | Driven by the inherited S8 key map |
| Wi-Fi / BT | Broadcom BCM4361 | No driver |

## What works

Evidence on the **Note 8**:

| Area | State |
| --- | --- |
| Boot | S-Boot → inherited S8 loader in BOOT (`sda7`) → XNU. Image written by `dd` and verified by read-back on the Note 8 |
| Display | 1440×2960 panel comes up with the S8 display path |
| iOS | iPhone X iOS 16.7.16 root filesystem boots and renders; without touch it cannot be used |
| Buttons | Power, volume and Bixby events work |
| Charging | The charging indicator works; the fuel gauge is the same MAX77865 as on the S8 |
| Logs | Loader and kernel log to ramoops (pmsg) and to the 4 MiB ring at the end of USERDATA, read from TWRP |
| Touch | **Not yet.** The controller answers, but the enable sequence fails |

Inherited from the S8 port and verified on an S8, not yet re-verified on the Note 8: 4× A53 SMP, HFS+ root on UFS, the iOS lock screen/home screen, RTC, S6SY761 touch, MAX77865 readings.

## Known bugs

- **No touch on the Note 8.** The y661 is in low-power mode (`0xE4 = 1`); `SENSE_ON` alone does not resume it. The loader/kernel now exit LPM (`0xE4 = 0`), wait for application mode and use the chip-specific reset command, but the result of the flashed image has not been checked. Touch works in TWRP, so panel, IC, rails and the protocol are fine; the fault is in the init sequence.
- **Battery capacity is wrong for this phone.** The kernel hard-codes `SWEET_BAT_MAH 3000` (the S8's battery); the Note 8 has 3300 mAh, so percentages and capacities are off.
- **The S Pen is not supported** (Wacom W9018 is not wired into HID).
- **Very slow and laggy.** All rendering is on the CPU, there is no GPU. About 15 minutes to the lock screen on an S8 with one core.
- Frames tear because DECON scans the panel memory while AppleCLCD copies into it. Patched in the latest S8 commit, not verified on the Note 8.
- The centered iPhone X 1125×2436 presentation is faster; the full-screen 1440×2960 mode (`sweetfb_native=1`) is the default.
- The Mongoose (big) cluster does not start yet. Only 4 A53 cores run.
- No Wi-Fi, Bluetooth, cellular, audio, cameras, sensors, GPS or SEP / Face ID.
- **No GPU.** The Mali-G71 cannot run iOS's Metal / AGX drivers, so hardware graphics is not realistic.
- Security is off: permissive AMFI/sandbox, stub AppleKeyStore. Do not put anything personal on it.

## Roadmap

- [ ] y661 touch: confirm the LPM exit and the `0x61`/`SENSE_ON` writes in the loader, then get coordinate events in XNU
- [ ] Verify the iOS lock screen, home screen and touch on the Note 8
- [ ] Report the Note 8's 3300 mAh design capacity
- [ ] S Pen input (Wacom W9018)
- [ ] Tear-free display on the Note 8 (inherited frame-done copy)
- [ ] Bring up the Mongoose cluster, raise the A53 clock
- [ ] More RAM (512 MiB of 6 GiB today)
- [ ] Wi-Fi (BCM4361): a large job

Help is welcome: issues and pull requests.

## Installation

The flow is the same as the S8 guide, and the tools still carry S8 names (`tools/dreamlte/…`, `shim/dreamlte/…`). Step-by-step: **[docs/s8-install.md](docs/s8-install.md)** (written for the S8; its model check expects `dreamlte`, so use the Note 8 checks above instead). Building on a Mac: **[docs/mac-build.md](docs/mac-build.md)**.

In short:
1. An unlocked Exynos Note 8 (SM-N950F/FD/N) with TWRP and a full partition backup. On this phone, BOOT is `sda7` and USERDATA is `sda24` (verified sizes above); TWRP has no `/dev/block/by-name`.
2. Fork this repository; the XNU kernel is built on GitHub Actions (workflow `xnu`, `MACHINE_CONFIG=A5XELTE`).
3. The iOS root image is built from the iPhone X 16.7.16 IPSW, which you download yourself, and is written to USERDATA.
4. `tools/dreamlte/make-boot.sh` builds the BOOT image (loader + XNU + Apple Device Tree), which is written to `sda7` from TWRP.

## How it boots

```
S-Boot (stock Samsung bootloader, EL1, MMU off)
  -> BOOT partition: shim/dreamlte (inherited loader instead of a Linux Image)
     -> unmasks the DECON trigger, logs to ramoops, wakes UFS
     -> copies XNU + ADT from the ramdisk to 0x880000000, builds boot_args
        -> XNU (xnu-8796, A5XELTE config + patch 0124-dreamlte-s8)
           -> UFS driver -> HFS+ root in USERDATA
              -> dyld + shared cache -> launchd -> backboardd + SpringBoard
                 (on the Note 8: boots and renders; touch waits on the y661)
```

The loader, kernel patch and ADT keep the S8's `dreamlte` names because the kernel device tree is the same Exynos 8895 platform.

## Layout

| Path | What it is |
| --- | --- |
| `shim/dreamlte/` | Loader for S-Boot: `loader.c`, UFS / SMP / touch probes |
| `xnu/patches/` | XNU patches; the S8/Note 8-specific one is `0124-dreamlte-s8.patch` |
| `tools/dreamlte/apply-dreamlte.py` | Generator of patch 0124 |
| `tools/mkadt_dreamlte.py` | Apple Device Tree |
| `tools/dreamlte/make-boot.sh` | Kernel → BOOT image |
| `tools/dreamlte/dreamlte_touch.c` | Kernel touch driver (S6SY761 + y661) |
| `tools/mkiosroot.sh`, `tools/dreamlte/finish-iosroot.sh` | iOS root image build |
| `tools/dreamlte/flash-chunks.ps1`, `flash-chunks.sh` | Writes an image to BOOT / USERDATA in verified chunks (PowerShell, bash for macOS/Linux) |
| `tools/dreamlte/pull-sweetlog.ps1`, `pull-sweetlog.sh` | Pulls the boot logs from TWRP |
| `docs/plan.md`, `docs/spec.md` | Product plan and system specification; `spec.md` has the Note 8 section |
| `DREAMLTE_PROGRESS.md` | **Active port log**: hardware facts, every boot, open work (the handoff file) |
| `docs/history/` | Galaxy A5 2016 (`A5XELTE_PROGRESS.md`, `a5xelte-*.md`) and original SWEET / Redmi Note 10 Pro (`NOTES.md`, `upstream-README.md`) history, kept as reference |

## Authors

- [@Floppikrob](https://github.com/Floppikrob): Galaxy S8 port (original [ios-galaxy-s8](https://github.com/Floppikrob/ios-galaxy-s8))
- [@iamv4g](https://github.com/iamv4g): galaxios8 fork, continued S8 work
- [@MakrSas](https://github.com/MakrSas): contributor, mainline Linux on the S8 ([LinuxS8](https://github.com/MakrSas/LinuxS8))

## Credits

- [orhunnx/ios-a5xelte](https://github.com/orhunnx/ios-a5xelte): the Galaxy A5 2016 port (4 KiB pages, Exynos, S-Boot) this project is based on
- [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): the original iOS 16 port to the Redmi Note 10 Pro (its README: [docs/history/upstream-README.md](docs/history/upstream-README.md))
- [MakrSas/LinuxS8](https://github.com/MakrSas/LinuxS8): mainline Linux on the Galaxy S8, the reference for touch, buttons and UFS
- Mainline Linux (Exynos 8895, HSI2C and S6SY761 drivers), [uniLoader](https://github.com/ivoszbg/uniLoader)
- Samsung's `android_kernel_samsung_universal8895` (`sec_ts_y661`, `exynos8895-greatlte_common.dtsi`) for the Note 8 hardware data
- Apple's open-source releases (xnu, IOHIDFamily, hfs), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), [apfs-fuse](https://github.com/sgan81/apfs-fuse)

iOS belongs to Apple and is not distributed here: download the IPSW yourself.

## License

The XNU patches are derived from XNU and fall under the [APSL 2.0](https://opensource.apple.com/apsl/). Code written after Linux drivers (for example `shim/dreamlte/touch_probe.c`) is GPL-2.0, see the SPDX headers. The upstream projects ios-sweet and ios-a5xelte did not state an overall license, so the remaining files have no separate license yet.

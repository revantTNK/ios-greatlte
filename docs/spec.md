# galaxios8 system specification

What the system is today, how its parts talk to each other, and the facts every change must respect. Measured values carry the boot or file they come from; anything not measured is marked as such. The plan that builds on this is [plan.md](plan.md).

## 1. Target hardware

Galaxy S8, Exynos 8895 (`dreamlte`): SM-G950F (upstream port) and SM-G950N (this fork's test phone). Component list from Samsung's `exynos8895-dreamlte_common.dtsi` (kernel `exynos8895/android_kernel_samsung_universal8895`, branch `lineage-19.1`).

| Block | Part / address | iOS service it has to feed | State |
| --- | --- | --- | --- |
| CPU, little | 4x Cortex-A53, MPIDR 0x100-0x103, CMU_CPUCL1 0x16900000 | XNU scheduler | Running, ~1053 MHz (PLL 0xa0f30311) of 1690 |
| CPU, big | 4x Mongoose M2, MPIDR 0x0-0x3, CMU_CPUCL0 0x16800000 | XNU scheduler | Starts with plain PSCI once GICD is enabled (boot m8); not yet used by XNU |
| Interrupts | GIC-400: GICD 0x10201000, GICC 0x10202000; physical timer PPI 14 (INTID 30), 26 MHz | XNU | Working |
| PMU | 0x16480000 (CPU CONFIGURATION 0x2000 + n*0x80, cluster seq 0x2484, INFORM2/3 0x808/0x80c, SWRESET 0x400) | power, reset | Used for reset-to-recovery |
| RAM | 80000000-bc7fffff, c0000000-ffffffff, 880000000-8ffffffff (about 3.7 GiB) | VM | XNU gets 512 MiB at 0x880000000 |
| Storage | UFS host 0x11120000; BOOT sda7, USERDATA sda24 (LUN 0) | IOMedia, HFS+ root | Read/write, own driver (`sweet_ufs.c`) |
| Display | DECON_F 0x12860000 (trigger 0x70 = 0x1281), IDMA0 scans 0xcc000000, 1440x2960 XRGB, panel in command mode | IOMobileFramebuffer / AppleCLCD | CPU copy per frame |
| GPU | Mali-G71 MP20 | Metal / AGX | Not usable: no iOS driver path |
| Touch | S6SY761 on USI09 HSI2C 0x108e0000, IRQ gpa1-0, rails S2MPS17 LDO34/35 | IOHIDFamily | Working (polled) |
| Keys | ALIVE pinctrl 0x164b0000: power GPA2-4, vol+ GPA0-3, vol- GPA0-4, Bixby GPA0-6 | HID buttons | Working (Bixby = Home) |
| PMIC | S2MPS17 over SPEEDY 0x15b50000: BUCK2 vdd_cpucl0, BUCK3 vdd_cpucl1, LDOs, RTC | power, clock | RTC read, LDO34/35 written, bucks read |
| Battery | MAX77865 on USI13 HSI2C (hsi2c_32): gauge 0x36, charger 0x69, 3000 mAh | IOPMPowerSource | Works on some boots, static fallback on others |
| Audio | Cirrus CS47L93 (madera) + MAX98506 amp, Exynos ABOX DSP | CoreAudio | None |
| Wi-Fi / BT | Broadcom BCM4361 (`samsung,brcm-wlan`) | IO80211, Bluetooth | None |
| GNSS, sensors | BCM4773 behind the SSP sensor hub MCU | CoreLocation, CoreMotion | None |
| Haptics | motor (dreamlte_motor / DRV2624 variant) | Taptic stand-in | None |
| Other | NFC, fingerprint, eSE, cameras (IMX333, 3H1...), modem (Shannon) | | Out of scope |

### Note 8 (greatlte, SM-N950F/N)

Same SoC, memory map, display size and PMIC. Read from Samsung's
`exynos8895-greatlte_common.dtsi` (`exynos-linux-stable/greatlte`,
`tw90-android`):

| Block | Part / address | Difference from the S8 |
| --- | --- | --- |
| Touch | `sec,sec_ts` at 0x48 on the same hsi2c_23 0x108e0000, IRQ gpa1-0, S2MPS17 LDO34/35 | The controller is Samsung's **y661** (`drivers/input/touchscreen/sec_ts_y661`, firmware `tsp_sec/y661_great.fw`, project `GREAT`/`N950`), not the S6SY761. `tsp_avdd` LDO35 is 3.3 V (S8 DT: 3.0 V). Registers and the 8-byte event format are shared; `SW_RESET` is 0x42 (y761: 0x12). |
| S Pen | Wacom W9018 on hsi2c_10 `0x10490000`, IRQ gpa1-? plus `gpe7-2` 3.3 V LDO | Not an iOS input path yet; finger touch is the y661. |

## 2. Partitions and what may be written

Only BOOT (`sda7`, 40 MiB) and USERDATA (`sda24`, 54.8 GiB) are ever written, from TWRP over adb, with an exact read-back hash. EFS (`sda3`), RECOVERY (`sda8`), the bootloader LUNs (`sdb`, `sdc`) and everything else are read-only for this project. TWRP has no `/dev/block/by-name`; the `sdaN` numbers above were checked on both the G950F and the G950N. Backups live in the git-ignored `backup/`.

USERDATA layout: an HFS+ (case-sensitive, journaled, volume `iOSRoot`) image at offset 0 (16 GiB today); the kernel's console log ring in the last 4100 KiB (`SWEETLOG` header, decoded by `tools/sweet-log.py`).

## 3. Boot chain

```
S-Boot (stock, EL1 handoff, MMU off; leaves GICD_CTLR = 0, Mongoose cores off)
  -> BOOT sda7: shim/dreamlte loader (Linux Image header, stock DTBH kept)
       unmasks the DECON trigger; logs to screen + ramoops pmsg
       UFS wake (SSU to W-LUN), S2MPS17 LDO34/35, RTC -> s8rtc=, touch/battery/display probes
       copies the SWEETXNU payload (kernel segments + ADT) to 0x880000000, builds boot_args
  -> XNU xnu-8796.141.3, MACHINE_CONFIG=A5XELTE + patches 0001-0124
       4 KiB pages, Cortex-A53 codegen (no LSE), GIC-400, physical timer
       SweetCPU starts secondaries (PSCI CPU_ON via a low trampoline at 0x8f000000)
       sweet_ufs: rd=ufsroot0 ufsroot=USERDATA -> HFS+ root, rw
  -> launchd (iPhone X 16.7.16 userland, shared cache from the cryptex copy)
       -> backboardd, SpringBoard, ~100 services
```

## 4. Interfaces

### Boot-args (loader appends some; the rest come from `make-boot.sh`)

| Key | Set by | Meaning |
| --- | --- | --- |
| `cpus=N` | user | Logical CPUs to start: 0-3 are A53, 4-7 Mongoose (ADT order) |
| `rd=ufsroot0 ufsroot=USERDATA ufsrw=1 rootrw=1` | user | Root on USERDATA, read/write |
| `sweetfb_native=1` | user | Present 1440x2960 (0: centered 1125x2436); also picks the ADT canvas |
| `sweetfb_hz=N` | user | Cap for the CPU frame copy |
| `a5fb_noconsole=1`, `a5fb_keep_on=1` | user | Console over iOS off; keep the panel on |
| `a5touchprobe=0` | user | Disable the A5 touch probe (aborts on the S8) |
| `wdt=-1 wdt_test=no_user_checkin` | user | No watchdogs |
| `ignition_level=1 launchd_unsecure_cache=1` | user | Shared cache without signature checks |
| `s8rtc=<unix>` | loader | UTC seconds at system-counter zero, from the S2MPS17 RTC |
| `mngs=v.v...` | loader (`MNGS_DIAG` build) | Mongoose diagnostic values, in print order |
| `s8autoreset=N` | user (tests) | Kernel resets into TWRP N s after the UFS log starts |
| `sweetlog=0` | user | Disable the on-disk console log |

### Logs

| Channel | Writer | Reader | Survives |
| --- | --- | --- | --- |
| Screen text | loader, early XNU | camera | nothing |
| ramoops pmsg | loader (0x92004000 for this TWRP, 0x92180000 for the upstream one) | `/sys/fs/pstore/pmsg-ramoops-0` in TWRP | warm resets only (adb reboot, SWRESET), not a forced power cycle |
| USERDATA log ring | XNU console (`sweet_log_thread`, flush every second) | `tools/dreamlte/pull-sweetlog.sh` | everything, until the next XNU boot starts a new ring |
| boot-args in launchd's log | loader | the ring above | as the ring |

### Reset into TWRP without touching the phone

PMU INFORM2 (0x16480808) = 0x12345678, INFORM3 (0x1648080c) = 0x12345674, PMU SWRESET (0x16480400) = 1. This is Samsung's `sec_reboot.c` path; S-Boot consumes INFORM3 and boots RECOVERY. Used by the `MNGS_DIAG` loader (with a loop guard: it will not reset again while the pmsg zone still ends with its own reset line) and by `s8autoreset=N` in the kernel.

## 5. Kernel components (patch 0124 on top of the A5XELTE stack)

| Component | File (in the patched tree) | Role |
| --- | --- | --- |
| SweetCPU | `iokit/Kernel/arm/SweetCPU.cpp` | Secondary start: GICD enable, low trampoline, PSCI CPU_ON |
| SweetFramebuffer / AppleCLCD bridge | display patches 0046/0056/0061/0068/0109 + 0124 | IOSurface swaps copied into 0xcc000000 after DECON frame-done |
| SweetHIDTouch, SweetHIDButtons | 0058/0060 + `dreamlte_touch.c`, `a5xelte_keys.c` | HID event services |
| SweetBattery | 0062 + 0124 | IOPMPowerSource from MAX77865 |
| sweet_ufs | `bsd/dev/sweet_ufs.c` | UFS block device, root, log ring, `s8autoreset` |
| AppleKeyStore stand-in, IOWatchdog stand-in, permissive AMFI/Sandbox | 0035/0038/0040/0050/0106 | Let userland run without SEP |

## 6. Build and release

- Kernel: GitHub Actions `xnu` workflow (macOS runner, ~5 min); artifact `xnu-kernel`.
- Loader and BOOT: native on macOS (`docs/mac-build.md`); CI `loader` workflow checks Linux byte-identity and the macOS build.
- Root image: Lima Ubuntu VM on the Mac (`docs/mac-build.md`), from the user's own IPSW (iPhone10,3/10,6 16.7.16, 20H392).
- Flash: `flash-chunks.sh` (USERDATA, 32 MiB chunks, SHA-256 per chunk), BOOT by `dd` with read-back.

## 7. Safety rules

1. Identify the phone before every write: `ro.product.device` = `dreamlte`, state `recovery`, and the expected serial; never write to a phone with a different SoC.
2. Write only BOOT and USERDATA; verify every write by reading it back.
3. Experiment builds must end in a known state: reset into TWRP, or boot the known-good image; never loop.
4. Keep Apple binaries, device dumps (EFS, S-Boot, logs with identifiers) out of git (`backup/`, `research/`, `logs/` are ignored).
5. Writing a PMIC voltage or a PLL is allowed only with values the hardware already uses on another rail or that Samsung's tables give, and only from a build that resets into TWRP afterwards.

# galaxios8 product plan

Goal: a Galaxy S8 (Exynos, SM-G950F / SM-G950N) that runs iOS 16 well enough to be used as a phone-shaped iOS device every day, installed and updated from a Mac by one command. This plan says what "good enough" means, where the project is, the work streams that close the gap, what to do when an approach fails, and the order to do things in. Facts and interfaces are in [spec.md](spec.md); the sequence and rough dates are in [roadmap.md](roadmap.md); day-to-day evidence goes to [`DREAMLTE_PROGRESS.md`](../DREAMLTE_PROGRESS.md).

## 1. Definition of done

"Smooth like a real product" is measured, not felt. A release must meet every line:

| Area | Target | Today (measured) |
| --- | --- | --- |
| Boot | Lock screen in ≤ 90 s from power-on | ~15 min on 1 core (upstream); 4 cores faster, not timed |
| UI | Home-screen swipe and app launch ≥ 30 fps, no tearing | Laggy; tearing seen in boot 31; frame-done copy untested |
| Touch | Taps and swipes land where the finger is; ≤ 50 ms latency | Works (polled); latency not measured |
| CPU | All 8 cores; clocks raised under thermal control | 8 cores (4 A53 at 1053 MHz, 4 Mongoose at ~1066 MHz), one scheduler cluster |
| Memory | ≥ 2 GiB for XNU | 512 MiB |
| Power | Battery % and charging correct every boot; screen off/on with the power key; brightness control | Gauge read works on some boots only; no sleep, no brightness |
| Input | Power, volume, Home (Bixby), haptic feedback | Keys work; no haptics |
| Audio | Speaker, earpiece, headphones | None |
| Network | Internet access (USB first, Wi-Fi later) | None |
| Apps | Built-in apps work; sideloaded apps install and run | Built-in apps partly; sideload untested |
| Stability | 24 h idle + 2 h use without panic or hang | Not tested |
| Install | `galaxios8 install` on a Mac: checks the phone, backs up, builds, flashes, verifies; `galaxios8 restore` to undo | Manual steps in `docs/mac-build.md` |

Out of scope, said upfront: Apple's own GPU stack (Mali-G71 cannot run Metal/AGX; a GPU path through CoreAnimation's OpenGL ES backend and Mesa Panfrost is the research direction since 2026-10-23, see [gpu-research.md](gpu-research.md)), cellular, cameras, Face ID/Touch ID and the Secure Enclave, App Store purchases, iCloud. Security is permissive (AMFI, sandbox, AppleKeyStore stand-in): the device must not hold personal data.

## 2. Work streams

Priority: P0 = blocks everything else, P1 = core experience, P2 = expected features, P3 = later or research.

### W0 Developer infrastructure (P0)

The speed of every other stream depends on how fast one hardware test cycle is.

- **Done:** loader reset into TWRP (`MNGS_DIAG` build) and the kernel's `s8autoreset=N` (patch 0124): flash, boot, test, come back to TWRP and read logs with nobody at the phone. pmsg zone for this TWRP (0x92004000).
- **Next:** a `tools/dreamlte/cycle.sh` that builds BOOT, flashes with read-back, reboots, waits for TWRP and pulls both logs; one command per experiment. Only after the user agrees, since it writes the phone unattended.
- **USB networking while iOS runs (P0/P1):** SWEET patches 0072-0077 already turn a Qualcomm DWC3 into a USB ECM gadget with live logs. Port them to the Exynos 8895 DWC3 (`usb@10C00000`, PHY `0x10E00000`): live kernel log, `ssh` into iOS, file copy, and later internet over the cable. This removes the TWRP round trip from most tests.
- Symbolication of panics and the user-stack sampler for the S8 (`symbolicate-smp.sh` exists).

### W1 CPU: eight cores and clocks (P0)

- **Done (K2c, K2d):** all eight cores run iOS. Causes fixed: S-Boot leaves the GIC distributor off and the PMU powers cores only on a GIC wake request (CPUn_OPTION bit 8), so plain PSCI CPU_ON works once GICD_CTLR = 1; SweetCPU did not match the `samsung,mongoose-m2` nodes; two scheduler psets deadlocked on pset0's lock, so all cores share one logical cluster for now. Clocks measured: A53 1053 MHz, Mongoose ~1066 MHz.
- **K1:** kernel with the new SweetCPU (GICD on, single CPU_ON, low trampoline), `cpus=4`: the A53s must still come up. **K2:** `cpus=8`.
- Scheduler: describe the two clusters in the ADT (cluster-type for P and E cores) so XNU's AMP scheduler places UI threads on Mongoose.
- Clocks: A53 runs at ~1053 MHz of 1690; Mongoose speed unknown (CMU_CPUCL0 readable once the cluster is on). Options, in order: (a) program the PLLs and the S2MPS17 bucks from Samsung's ASV/LUT tables (`cmucal-vclklut`, `vdd_mngs_*`) at a few fixed steps, from the loader; (b) load Samsung's ACPM DVFS plugin (`exynos8895_acpm_dvfs.fw`, present in S-Boot and loaded by Linux) and talk to it over ACPM IPC; (c) leave the defaults. Any of these needs the thermal sensor (TMU) read first and a hard cap.

Scenarios:
- K2 boots with 8 cores → move on to clocks.
- Mongoose cores start but XNU panics on them (feature or cache differences) → run XNU on Mongoose only with `cpus` masks, read `ID_AA64*`/`CTR_EL0` per cluster, fix the CPU identity patch (0101) and the cache maintenance assumptions.
- They start but hang later (idle/power-down) → disable core power-down in idle (keep WFI only) first, then implement PSCI CPU_SUSPEND properly.

### W2 Memory (P1)

- 2 GiB attempt panicked in `kmem_range_init` (boot 1, upstream). Find why the kernel VA layout does not fit 2 GiB with 4 KiB pages (zone and kmem range sizes are tuned for the A5's 512 MiB), size them for 2 GiB, then add the low banks (0x80000000-0xbc7fffff, 0xc0000000-0xffffffff minus carve-outs) through the ADT memory map.
- Exit: `hw.memsize` ≥ 2 GiB and a Safari-sized app runs without jetsam kills.

### W3 Display and graphics (P1)

With no GPU, CoreAnimation renders on the CPU; the job is to give it fewer pixels and fewer copies.

1. Verify the tearing fix (copy after DECON frame-done).
2. Fewer pixels: present 1125x2436 (works, faster) or lower, and let the display pipeline scale it to 1440x2960. The VG/VGF DPP channels (`dpp@0x12853000`-`0x12856000`) are the scaling candidates; needs a DPP driver path (scaler coefficients, window update). Fallback: integer 2x scale in the copy loop (NEON) from 720x1480.
3. Zero-copy scan-out: point IDMA at the IOSurface instead of copying (boot 28: moving the base with only a global update did nothing; needs the window/shadow update sequence from Samsung's `decon_reg_*`).
4. Vsync from the DECON frame-done interrupt instead of a timer.
5. System settings that cut CPU work: Reduce Motion and Reduce Transparency on by default (root tweaks), no wallpaper parallax.

Scenarios: scaling works → 720p-class rendering at 60 Hz may be reachable; it does not → 1125x2436 plus NEON copy and the settings above.

### W4 Power and battery (P1)

- Battery: find why the gauge read falls back to the static value on some boots (I2C bus state after reset? timing?) and make the driver retry; report charging and AC state.
- Power key: screen off/on (panel sleep in/out over DSIM command mode, DECON stop/start) mapped to iOS lock; this is what makes it feel like a phone.
- Brightness: panel DCS brightness (0x51) over DSIM from IOMobileFramebuffer's brightness calls.
- Idle: WFI on all cores; later PSCI CPU_SUSPEND for core power-down, using the same GIC-wake mechanism found in W1.
- Thermal: TMU read, throttle by capping clocks; never run raised clocks without it.

### W5 Input and haptics (P2)

- Touch from the S6SY761 interrupt (gpa1-0 via the GPIO interrupt controller) instead of polling; multi-touch IDs; edge gestures for the iPhone X home indicator.
- Haptics: the S8 motor (dreamlte_motor / DRV2624 variant) behind a minimal Taptic stand-in.
- Proximity/hall sensor: later (behind the SSP sensor hub).

### W6 Network (P2)

- Internet over USB first: ECM/NCM gadget from W0, the Mac shares its connection; iOS sees an Ethernet interface.
- Wi-Fi (BCM4361): iOS's Wi-Fi stack expects Apple's closed Broadcom drivers. Realistic options are an Ethernet-style interface backed by a ported Broadcom FullMAC driver (PCIe, firmware upload, WPA in the dongle) or nothing. Research item; large.
- Bluetooth: P3.

### W7 Audio (P3)

CS47L93 codec + MAX98506 amp behind the ABOX DSP; an IOAudio/CoreAudio path would need the codec's register setup and an I2S/DMA driver. Start with "speaker plays a test tone" from the loader to prove the path.

### W8 Storage and system (P2)

- Bigger root (32 GiB) and a separate data volume, so app installs fit; keep the log ring at the end of USERDATA.
- Clean up crash-looping or noisy daemons (e.g. assistantd calls AppleKeyStore ~2000 times per boot); each costs CPU on a slow device.
- Time zone and locale defaults (the clock is right but in Cupertino time).

### W9 Apps and userland (P2)

- Sideloading: install an IPA with `installd` under the permissive AMFI; test a few common apps.
- Passcode-only lock with the AppleKeyStore stand-in; document that data is not protected.

### W10 Installer and release (P1)

- `galaxios8` CLI for macOS: detect the phone (model, TWRP, serial), back up BOOT/EFS/RECOVERY, fetch the IPSW from Apple's CDN on the user's machine, build the root in the Lima VM, build BOOT, flash with verification, first boot, and `restore` back to the backup.
- Release artifacts: kernel and loader only; never Apple files.
- User guide in English and Vietnamese.

### W11 Quality (P1, continuous)

- Automated boot test on every kernel change: `s8autoreset` boot, check the log for "4/4" or "8/8 CPUs", `hfs: mounted`, SpringBoard, no panic.
- Metrics per release: time to lock screen, frames per second during a scripted swipe, battery drain per hour.
- 24 h soak before calling a build a release.

## 3. Milestones

| Milestone | Content | Exit criteria |
| --- | --- | --- |
| M0 Reproducible (done) | Mac build, Lima root, flash tools, iOS on the G950N | iOS Settings shows 16.7.16 (boot g2) |
| M1 Fast loop | W0 cycle tool, USB ECM live log + ssh | A kernel change is tested in < 10 min without touching the phone |
| M2 All cores | W1 K1/K2, AMP topology | 8 CPUs online for 1 h without panic |
| M3 Feels like a phone | W3 1-4, W4 power key and brightness, battery fix | Lock screen ≤ 90 s, swipe ≥ 30 fps, screen off/on works |
| M4 Daily use | W2 2 GiB, W5 touch IRQ + haptics, W6 USB internet, W8 | Safari over USB internet, 24 h soak |
| M5 Installer | W10 | A new user installs from a Mac with one command |
| M6 Research | Wi-Fi, audio, clocks via ACPM | Each either shipped or documented as not feasible |

## 4. Next actions

1. Eight cores run (K2c/K2d). Next for W1: a 1 h soak on eight cores, then a proper two-cluster topology (find the pset0 lock recursion) so the scheduler can prefer the Mongoose cores, then clocks.
2. Write `cycle.sh` once the user agrees to unattended flashing.
3. Port the USB ECM gadget patches to the Exynos DWC3.
4. Measure: time to lock screen and swipe fps on the current build, so later gains are numbers.
5. Fix the battery fallback.

## 5. Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| No GPU | UI never as fluid as an iPhone | W3 pixel reduction, settings, more cores and clocks |
| Wrong PMIC/PLL write | Hardware damage | Only values Samsung's tables or other rails use; TMU first; resets into TWRP |
| Bricking BOOT | Phone does not boot | BOOT backup, TWRP intact, download mode untouched |
| Apple licensing | Cannot ship iOS | Ship only our code; the user fetches the IPSW |
| G950N vs G950F differences | Driver works on one only | Both tested before a release; model table in the README |

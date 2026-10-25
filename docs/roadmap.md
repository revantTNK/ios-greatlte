# Feature roadmap and rough timeline

Date: 2026-10-23. Scope: the order to bring up the remaining features of iOS on the
Exynos 8895, starting from reliable touch and ending at a GPU-accelerated UI. This
file owns the **sequence and the rough dates**; the work items themselves live in
[plan.md](plan.md) (streams W0-W11) and [gpu-research.md](gpu-research.md)
(milestones G0-G5), and day-to-day evidence lives in
[`DREAMLTE_PROGRESS.md`](../DREAMLTE_PROGRESS.md).

Labels, as in `gpu-research.md`:

- **[measured]** a number read off the phone or its logs, with the evidence named.
- **[fact]** from a source (Samsung's 4.4 kernel, Mesa, the 20H392 IPSW, our own
  patches), checked here.
- **[estimate]** my judgement. Dates are all estimates and assume the user is
  available for the hand tests; a hardware test that needs eyes on the screen
  cannot be batched.

Current test phone: Galaxy Note 8 (`greatlte`, SM-N950F/N). The kernel, loader and
drivers are shared with the S8 (`dreamlte`); anything S8-only is called out.

## 0. Where we are

| Subsystem | State today | Evidence |
| --- | --- | --- |
| Touch | Works, then the event port wedges after a few minutes of use; the bus kick restores the bus but not the event path, and the wedge now clears by itself after an idle soak (2026-10-25) | ring `logs/sweetlog-8core.txt`: `event read failed`, `wedge (64)` dump, `bus kick: dat 0xf2, after dat 0xf3`, then no touch error for ~650 lines; user report of recovery after idling |
| RAM | 4 GiB on `greatlte` (was 2 GiB; 4 GiB panicked until patch 0126 sized the bootstrap page tables for `ARM_LARGE_MEMORY`) | `vm_page_bootstrap: 258468 free pages` = 16 KiB pages; Note 8 high bank `880000000-97fffffff` |
| CPU | 8 cores run in iOS on `greatlte` (`cpus=8`, 2026-10-25); **one** scheduler cluster, so the scheduler cannot prefer the big cores. Clocks stay at the bootloader's ~1.05 GHz because no `s8lit`/`s8big` ACPM setting is applied; on the S8 A53 1690 / Mongoose 1703 MHz are reachable with a working thermal guard | ring `logs/sweetlog-8core.txt`: `8/8 CPUs initialized, SGI1 verified`, A53 1052-1053 MHz, Mongoose 1066 MHz; c10/c11 clock runs on the S8 |
| Display | iOS presents at **1080x2220** (75 % of the panel, same aspect) on the 1440x2960 DECON_F panel: `SweetFramebuffer` snapshots the IOSurface, a presenter thread CPU-upscales 1080x2220 to 1440x2960 with no side bars and copies to `0xcc000000` at up to 60 Hz (`sweetfb_hz=60`). Native 1440x2960 (`sweetfb_native=1`) still available. The presented size is a boot arg (`sweetfb_logical_w/h`) since `0c2ea33bf` | user report: noticeably bigger and smoother than native; 1125x2436 (an Apple size) black-screened on a `BoundingPathBitmap` abort, 1080x2220 shows a status-bar `rdar:45025538` banner |
| GPU | None. No IOAccelerator, so CoreAnimation falls through Metal and GLES to its software rasterizer; the Mali-G71 is unpowered | `CA::OGL::SW::image_sampler`, `scan_convert` in the samples; `gpu-research.md` sec. 1 |
| Power / input | No screen off/on from the power key, no brightness, battery gauge falls back to a static value on some boots, no haptics | plan.md W4/W5 |
| Elsewhere | No audio, no network, root is 16 GiB in USERDATA | plan.md W6-W8 |

Two of the user's five asks are already in motion: touch reliability (above) and CPU
clocks (c10-c12), which is why the timeline below is mostly about the *order of the
next* things rather than starting from zero.

## 1. Order, and why this order

1. **Touch reliability (P0).** Not only is a phone you cannot touch a demo, every
   other phase is verified by hand. A driver that dies after 7 minutes poisons every
   measurement that follows, so it goes first and the exit criterion is a soak, not a
   build.
2. **Fast loop and numbers (P0.5, parallel).** `tools/dreamlte/cycle.sh` is S8-only
   (it hard-codes the S8 serial and refuses anything that does not report `dreamlte`),
   and every "is it smoother now" question needs a metric. Cheap, and it makes every
   later phase cheaper.
3. **Display scaling and the present path (P1).** The user asked for it, it needs no
   new hardware bring-up, and it removes the largest single CPU cost per frame
   (~14 ms scale + ~5 ms snapshot on a saturated CPU). Half of it is already built
   (`sweetfb_dpp=1`, image `s8-c15-boot.img`) and waiting for a hand test.
4. **Cores and scheduler topology (P1).** With the per-frame CPU cost dropping, the
   remaining lever is where the work runs. All 8 cores boot, but they are one
   scheduler cluster [measured, K2c/K2d]. The S8 daily image already runs `cpus=8`
   with A53 1690 / Mongoose 1703 MHz from the loader's boot args, while the Note 8
   images still run `cpus=4` and default clocks, so the first Note 8 win is to port
   that setting and measure it. This multiplies phases 3, 5 and 6.
5. **GPU: make the Mali do one job, then render CoreAnimation through it (P2,
   research).** The biggest payoff and the biggest risk. The desk work (Mesa
   cross-build, finding the 20H392 vtable addresses) starts immediately and in
   parallel, because it needs no phone.
6. **Metal (P3, optional).** Only meaningful after 5, and it is a "months" item
   (gpu-research.md C). It is deliberately last.
7. **Phone features (interleaved).** Power key/lock, brightness, haptics, USB
   internet, audio, Wi-Fi, bigger root: plan.md streams W4-W8. They are scheduled
   between the big phases, and the power key in particular is cheap and changes how
   the device feels.

## 2. Phases

| Phase | Goal | Exit test | Effort [estimate] | Status |
| --- | --- | --- | --- | --- |
| T1 | Touch survives real use | 1 h of use with no wedge, or an automatic recovery within a few seconds; tap latency <= 50 ms | days | in flight (diagnostic image flashed 2026-10-23) |
| T2 | Fast loop + metrics | A `greatlte` cycle script, live log without TWRP, and numbers for boot time, frames/s and taps/s | days | not started |
| D1 | Cheaper pixels | Hand test of DPP scaling, then 1080x1920 (or 720x1480) rendering, zero-copy scan-out, frame-done vsync | 2-4 weeks | partly built (`s8-c15-boot.img`) |
| C1 | Cores used well | 8/8 CPUs for 1 h, TMU <= 80 C, UI work scheduled on Mongoose, measured gain in frames/s and time-to-lock-screen | 2-4 weeks | clocks done, topology not |
| G1 | The Mali does one job | A write-value job lands a known word in RAM, `JOB_IRQ_RAWSTAT` shows done, `GPU_FAULTSTATUS` clean | 1-3 weeks | not started |
| G2 | A triangle on the GPU | XNU Mali service + Mesa panfrost draws a triangle into an IOSurface shown by SweetFramebuffer | 4-8 weeks | not started |
| G3 | CoreAnimation on the GPU | Home screen drawn through the `GLESContext` bridge (softpipe first, then panfrost), render time logged per frame | 4-8 weeks | not started |
| G4 | GPU hardened | Swipe at 60 fps, 1 h without a GPU hang, thermal step-down wired to the GPU TMU | open-ended | not started |
| G5 | Metal (optional) | Selected Metal apps run through an AIR->NIR plugin bundle | months | stretch |
| P1 | It behaves like a phone | Screen off/on with the power key, brightness control, battery and charging correct every boot, haptics | 3-6 weeks | not started |

### T1 Touch reliability (now)

- [measured 2026-10-23] The wedge is the IC becoming **unaddressable**: the failure
  is in the i2c *write/address* phase (`stage write-done`) with INT_STATUS `0x0` -
  no TRANS_DONE and none of the abort/no-ack/no-device/timeout bits - and every
  later transfer fails the same way, including the IC's own `0x42`/`0x12` reset, so
  an IC-side ladder can never recover it. The battery on the other i2c bus keeps
  working on the same line, and a reboot restores touch: a runtime wedge of the
  controller/clock/pads (or the IC), not damage.
- [measured] The first diagnostic image also carried a bug of ours: it dispatched
  events with the wrong id test (`ev[0] & 3 == 0` is *coordinate*, not status), so
  every finger event was dropped and touch was dead from boot. Fixed in `3cdd1421e`
  along with consuming the boot-complete event and capping IC re-inits (4 per boot,
  60 s apart).
- [next] `3cdd1421e` (run 39989588696) dumps the loader's USI09 registers at the
  wedge - controller CTL/TRAILING/INT_EN/INT_STATUS/FIFO_STATUS, CONF/AUTO_CONF/
  TRANS_STATUS/TIMEOUT/ADDR, PCLK/SCLK/USER_MUX/SYSREG, TOP mux/div/gate, GPE3
  CON/DAT/PUD, GPA1 DAT - and then re-asserts them (`s8ts_bus_recover()`): the only
  recovery open to us while the IC cannot be written to. That decides between
  controller/clock gating and a pad/IC fault.
- Stretch, once the wedge is understood: multi-touch ids (10), edge gestures for the
  home indicator, and reads driven by the gpa1-0 interrupt instead of 8 ms polling
  (plan.md W5). Tap latency measured with a scripted tap and the HID timestamp.

### T2 Fast loop and numbers (parallel)

- A `greatlte` variant of `cycle.sh` (own serial and model guard, `sda7` only, read
  back every write) and the documented USERDATA skip for this TWRP.
- Ported USB ECM gadget on the Exynos DWC3 (`usb@10C00000`), so iOS runs with a live
  log and `ssh` instead of a TWRP round trip (plan.md W0). This is the single biggest
  speed-up for every phase after T1.
- Metrics per build: time to lock screen, frames/s during a scripted swipe, panel
  updates/s, tap latency, battery drain/hour. Without these, "smoother" is an
  opinion.
- Housekeeping that blocks nothing but misleads: `docs/s8-install.md` and
  `docs/mac-build.md` still document `cpus=4` and say "do not go above 4", which
  predates K2 (8 cores) and the clock boot args.

### D1 Display scaling and the present path

1. Hand test `sweetfb_dpp=1` (`s8-c15-boot.img`): does the picture stay correct and
   does the log show the switch from G0 to VGF0? [fact: only VGF0/1 scale; window 5
   is on G0 in S-Boot.]
2. Render fewer pixels: 1125x2436 already works, 1080x1920 or 720x1480 with an
   integer 2x NEON scale is the fallback if DPP misbehaves.
3. Zero-copy scan-out: point IDMA at the IOSurface (boot 28 proved a base move alone
   is not enough; the window/shadow update sequence from Samsung's `decon_reg_*` is
   needed).
4. Vsync from the DECON frame-done interrupt instead of a timer.
5. Settings that cut CPU work by default: Reduce Motion and Reduce Transparency, no
   wallpaper parallax (the root-side script exists; it is not on the phone's root).

Exit: a hand test at >= 30 frames/s while swiping and launching apps, panel >= 55
updates/s, and a measured drop in presenter CPU time. The GPU path (G3) later
replaces steps 2-3, so keep step 1's DPP path independent of the CPU scaler.

### C1 Cores, scheduler and clocks

- **First, the cheap part:** port the S8 daily settings to `greatlte` (`cpus=8`,
  `s8lit=1690000 s8big=1703000`) and measure. The Note 8 currently runs four cores at
  the default A53 clock, so this is the largest single-lever win available and it is
  one boot-arg change. Neither `cpus=8` nor the clock args have been tried on this
  device [fact: the greatlte images carry `cpus=4` and no `s8lit`/`s8big`].
- **Mongoose cores.** All eight boot [measured, K2c/K2d, on the S8], but remaining work
  is L2/non-CPU power, the start order (core 0x000 first) and their true speed [fact:
  the Mongoose clock is unknown, and `FREQ_GET` answers 0, so the PLL has to be read
  back].
- **Topology.** The ADT names logical 4-7 `samsung,mongoose-m2`; XNU's AMP scheduler
  needs two clusters (EE/PE). Today one pset means the UI can land on an A53. Fix the
  pset0 lock recursion, then describe cluster types in the ADT so UI threads prefer
  Mongoose.
- **Clocks.** Daily setting is A53 1690 / Mongoose 1703 MHz with the TMU guard
  (c11); 2002 MHz works but runs at 81 C within a minute (c12), so it stays a
  bench setting. Move the `FREQ_REQ` from the loader's boot args into the kernel (or
  keep the loader path and document it) once the topology work settles.
- Exit: 8/8 online for 1 h, TMU <= 80 C, and a measured frames/s or boot-time gain
  over C1's starting point.

### G1-G5 GPU (research; details in gpu-research.md)

The plan is not Metal and not AGX emulation: CoreAnimation has an OpenGL ES backend,
and HackiOS reports driving it with Mesa behind a replacement `EAGLContext`. On Mali
that becomes Mesa Panfrost plus a small Panfrost-style driver in XNU (G71 is a Job
Manager GPU: no firmware, no signed zap shader, no TrustZone step).

- **G0 (desk, 1-2 weeks, starts now):** cross-build Mesa 25.0.7 (`softpipe,panfrost`,
  OSMesa, no LLVM) for arm64-ios; find the 20H392 addresses of `EAGLServer::renderer`,
  the `GLESContext` vtable, CoreAnimation's GLES shader table and Metal's
  `_deviceArray`; confirm `DYLD_INSERT_LIBRARIES` is honoured for backboardd under our
  AMFI stand-in.
- **G1 (1-3 weeks):** a diagnostic loader or XNU probe that powers `pd_g3d`
  (`0x164840e0`), asks ACPM for 260 MHz (`0x0B040004`), reads `GPU_ID` (expect
  `0x6000xxxx`, which selects the errata set), powers L2 and the shader cores, builds
  one AS0 page table, and runs a single *Write value* job. Exit: the word appears in
  RAM and the fault status is clean. This still writes BOOT, so it needs the user's
  confirmation like every flash.
- **G2 (4-8 weeks):** the XNU Mali service (panfrost UAPI subset, IOSurface import,
  IRQ 92 fences, hang recovery, GPU TMU) and a triangle.
- **G3 (4-8 weeks):** the `EAGLContext` bridge in backboardd, run against softpipe
  first as a correctness check, then panfrost.
- **G4:** the missing CoreAnimation GLES functions (the GLES renderer has shaders for
  fewer than half of CA's ~90 fragment functions), GPU or DPP scale into the panel,
  IRQ-driven fences, thermal, soak.
- **G5 (optional, months):** a Metal plugin bundle with an AIR->NIR frontend. Keep
  expectations level [fact/reported]: HackiOS's corpus report says 321 of 456
  system shader modules compile and none of the 135 visible-function modules do; its
  README says 293 run.

### P1 Power, battery and the phone feel

- Power key: panel sleep in/out over DSIM command mode with DECON stop/start, mapped
  to iOS lock. This is what makes it feel like a phone and it is a prerequisite for
  honest battery numbers.
- Brightness: panel DCS `0x51` over DSIM from IOMobileFramebuffer's brightness calls.
- Battery: make the fuel-gauge read retry instead of falling back to the static value
  (it works on most boots; when it fails the user sees a wrong percentage).
- Haptics: the S8/Note 8 motor behind a minimal Taptic stand-in.
- Then the plan.md streams: USB internet (W6), audio (W7), Wi-Fi research (W6),
  bigger root and data volume (W8), installer (W10).

## 3. Timeline (dates are estimates)

| When | Work | Gate |
| --- | --- | --- |
| Oct 23-29 | T1 touch soak + fix from the diagnostic ring; T2 `greatlte` cycle script; DPP hand test | touch survives 1 h of use |
| Oct 30 - Nov 12 | D1 zero-copy scan-out and 1080p rendering; G0 desk (Mesa build, addresses); C1 topology investigation | hand test >= 30 frames/s |
| Nov 13-26 | G1 "Mali does one job"; C1 L2/power and topology; P1 power key and brightness | G1 job completes; screen off/on works |
| Nov 27 - Jan 7 | G2 XNU Mali driver + triangle; D1 polish and metrics; P1 battery/haptics | photo of a GPU triangle |
| Jan - Feb | G3 CoreAnimation on the GPU (softpipe, then panfrost); G4 hardening; phone streams (USB internet, root) | Home screen drawn by the Mali |
| Mar and later | G4 soak, G5 Metal if the GPU path is holding, audio/Wi-Fi research | 24 h soak before calling a release |

The schedule is dominated by two things that are not on the critical path but are
prerequisites for every hand test: user availability, and T2 (live log over USB). If
T2 lands early, everything after it moves faster.

## 4. Decision gates

| Gate | If it fails | Then |
| --- | --- | --- |
| Touch: the IC never answers, even after reset | The wedge is below the I2C protocol | Do a bus/controller recovery in the display-wake path, or power-cycle the rails only at boot (as now) and accept "reboot to fix" until the GPU phase |
| DPP scaling does not produce a correct picture | Hardware scaling is not usable yet | Keep the CPU scaler at 1125x2436 or lower, and spend the time on zero-copy scan-out instead |
| Two-cluster topology cannot be made to work | XNU's AMP scheduler stays out of reach | Keep one cluster, lean on clocks and pixel reduction; revisit after G3 |
| G1 fails (`GPU_ID` unreadable, no job completion) | The Mali cannot be driven | Stop the GPU track. There is no partial payoff, so the effort goes to D1/C1 and desktop work stops |
| G2 works but G3 does not | The blocker is the GLES bridge, not the driver | Decide then: more userspace work on 20H392, or ship CPU rendering with D1/C1 |

## 5. Risks and non-goals

- **Non-goals:** Apple's AGX/Metal driver stack and any AGX command-stream translation
  (years, no partial payoff); cellular, cameras, Face ID/Touch ID and the Secure
  Enclave; App Store and iCloud. See plan.md sec. 1.
- **Thermal:** raised clocks already reach 81 C at 2002 MHz. Every clock or GPU change
  keeps the TMU guard and a hard cap.
- **Bricking:** only BOOT (`sda7`) and USERDATA (`sda24`) are ever written, with a
  read-back check, and TWRP plus the BOOT backup stay intact.
- **Licensing:** we ship only our own code; the user fetches the IPSW.
- **Estimate drift:** the dates assume the current rate (a kernel change and a hand
  test per day or two). They are not commitments.

## 6. Keeping this honest

- Every phase exit is a number, a log line or a photo; a build that has not run on the
  phone is marked as such.
- Evidence goes into [`DREAMLTE_PROGRESS.md`](../DREAMLTE_PROGRESS.md) as it happens;
  this file changes only when a phase closes or the order changes.
- Facts, reported claims and estimates stay labelled as in `gpu-research.md`.

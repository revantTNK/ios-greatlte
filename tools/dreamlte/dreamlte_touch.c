#if defined(DREAMLTE)
/*
 * Galaxy S8 / Note 8 I2C devices, polled (no XNU interrupt routing for them).
 * The loader (shim/dreamlte) ungates both USI blocks with their clock on
 * OSCCLK, sets USI v1 I2C mode and the pins, and powers the touch rails.
 *
 * Touch: Samsung "sec,sec_ts" at 0x48 on hsi2c_23 (USI09, 0x108e0000), its
 * interrupt gpa1-0 active low. Two controllers use that node:
 *   - S8 (dreamlte, SM-G950F/N): S6SY761 ("y761"), boot 26: status 0x20,
 *     id 0xac3761 via READ_ID 0x52.
 *   - Note 8 (greatlte, SM-N950F/N): "y661" (Samsung's sec_ts_y661 driver,
 *     firmware tsp_sec/y661_great.fw), addressed by READ_DEVICE_ID 0x22.
 * Both share the 8-byte event format and the enable sequence used here
 * (TOUCHFUNCTION 0x30 = TOUCH|PALM|WET, SENSE_ON 0x10), so one driver
 * serves both; only the soft reset differs (y661 0x42, y761 0x12).
 * Event protocol from Samsung sec_ts and mainline s6sy761.c; raw 0..4095
 * axes go to SweetHIDTouch's 1080x1920 grid.
 *
 * Battery: MAX77865 on hsi2c_32 (USI13 second HSI2C, 0x10970000), fuel
 * gauge 0x36 and charger 0x69 (Samsung max77865_fuelgauge.c/_charger.c).
 */
#define S8TS_HSI2C_PA           0x108e0000u
#define S8BAT_HSI2C_PA          0x10970000u
#define S8TS_ALIVE_PA           0x164b0000u
#define S8TS_GPA1_DAT           0x44u
#define S8TS_ADDR               0x48u
#define S8BAT_FG                0x36u
#define S8BAT_CHG               0x69u
#define S8TS_FINGERS            10
#define S8_I2C_CLKIN            26000000u
#define S8_I2C_SCL_HZ           400000u
/* sec_ts command set (identical numbers in sec_ts_y661 and sec_ts) */
#define S8TS_CMD_SENSE_ON       0x10
#define S8TS_CMD_SET_FUNC       0x30
#define S8TS_CMD_SW_RESET_Y661  0x42
#define S8TS_CMD_SW_RESET_Y761  0x12
#define S8TS_READ_FW_INTEGRITY  0x21
#define S8TS_READ_DEVICE_ID     0x22
#define S8TS_READ_PANEL_INFO    0x23
#define S8TS_READ_ID            0x52
#define S8TS_READ_BOOT_STATUS   0x55
#define S8TS_READ_ONE_EVENT     0x60
#define S8TS_READ_ALL_EVENT     0x61
#define S8TS_READ_TS_STATUS     0xaf
#define S8TS_CMD_SET_POWER_MODE 0xe4  /* sec_ts: 0 = touch, 1 = low power */
#define S8TS_POWER_MODE_TOUCH   0x00
#define S8TS_STATUS_APP_MODE    0x20
#define S8TS_FUNC_TOUCH_PALM_WET 0x61u  /* sec_ts default: TOUCH|PALM|WET */

static vm_offset_t s8ts_i2c, s8ts_alive, s8bat_i2c;
static int s8ts_sleep;
static int s8ts_native;         /* sweetfb_native: iOS sees the whole panel */
static int s8ts_scaled;         /* sweetfb_scale=1: 1125x2436 scaled to the panel height */
static int s8ts_poll;           /* s8tspoll=1: ignore the IRQ line, poll the queue */
static int s8ts_raw;            /* s8tsdebug=N: log the first N raw events */
static bool s8ts_down[S8TS_FINGERS];
static uint16_t s8ts_x[S8TS_FINGERS], s8ts_y[S8TS_FINGERS];

/* i2c-exynos5.c: reset, Exynos8895 fast-mode timing, master auto mode. */
static void
s8i2c_reset(vm_offset_t bus)
{
	a5touch_write(bus, 0x00, a5touch_read(bus, 0x00) | (1u << 31));
	a5touch_write(bus, 0x00, a5touch_read(bus, 0x00) & ~(1u << 31));
	unsigned ftl = (a5touch_read(bus, 0x40) >> 16) & 7;
	unsigned temp = S8_I2C_CLKIN / S8_I2C_SCL_HZ - (ftl + 3) * 2;
	unsigned div = temp / 512;
	unsigned cyc = (temp + ((ftl + 3) % (div + 1)) * 2) / (div + 1) - 2;
	unsigned l = cyc * 64 / 100, h = cyc - l;
	a5touch_write(bus, 0x60, l << 24 | l << 16 | l << 8);
	a5touch_write(bus, 0x64, (l / 2) << 24 | l << 8 | h);
	a5touch_write(bus, 0x68, div << 16 | cyc);
	a5touch_write(bus, 0x6c, l / 2);
	a5touch_write(bus, 0x48, a5touch_read(bus, 0x48) & ~(1u << 31));
	a5touch_write(bus, 0x00, 0x9);
	a5touch_write(bus, 0x08, 0xf);
	a5touch_write(bus, 0x40, a5touch_read(bus, 0x40) | (1u << 31));
}

/* INT_STATUS: bit 7 TRANS_DONE, bits 8-11 abort/no-ack/no-dev/timeout. */
static bool
s8i2c_wait_done(vm_offset_t bus)
{
	for (unsigned us = 0; us < 20000; us++) {
		uint32_t s = a5touch_read(bus, 0x24);
		if (s & 0xf80u) {
			a5touch_write(bus, 0x24, s);
			return !(s & 0xf00u);
		}
		delay(1);
	}
	return false;
}

/* Write wlen bytes, then read rlen bytes (repeated start); STOP at the end. */
static bool
s8i2c_xfer(vm_offset_t bus, unsigned addr, const uint8_t *w, unsigned wlen,
    uint8_t *r, unsigned rlen)
{
	a5touch_write(bus, 0x24, a5touch_read(bus, 0x24));
	a5touch_write(bus, 0x70, addr << 10);
	a5touch_write(bus, 0x20, 0xf80u);
	if (wlen) {
		a5touch_write(bus, 0x04, 3);
		a5touch_write(bus, 0x00, 0x9 | 0x80);
		a5touch_write(bus, 0x44, (rlen ? 0 : (1u << 17)) | wlen | (1u << 31));
		for (unsigned i = 0; i < wlen; i++) {
			for (unsigned n = 0; n < 1000 && (a5touch_read(bus, 0x30) & (1u << 7)); n++) {
				delay(1);
			}
			a5touch_write(bus, 0x34, w[i]);
		}
		if (!s8i2c_wait_done(bus)) {
			goto fail;
		}
	}
	if (rlen) {
		a5touch_write(bus, 0x04, 3);
		a5touch_write(bus, 0x00, 0x9 | 0x40);
		a5touch_write(bus, 0x44, (1u << 16) | (1u << 17) | rlen | (1u << 31));
		for (unsigned i = 0; i < rlen; i++) {
			unsigned n = 0;
			while ((a5touch_read(bus, 0x30) & (1u << 24)) && n++ < 20000) {
				delay(1);
			}
			if (a5touch_read(bus, 0x30) & (1u << 24)) {
				goto fail;
			}
			r[i] = (uint8_t)a5touch_read(bus, 0x38);
		}
		if (!s8i2c_wait_done(bus)) {
			goto fail;
		}
	}
	a5touch_write(bus, 0x00, 0x9);
	return true;
fail:
	s8i2c_reset(bus);
	return false;
}

static bool
s8ts_cmd_read(uint8_t cmd, uint8_t *r, unsigned rlen)
{
	return s8i2c_xfer(s8ts_i2c, S8TS_ADDR, &cmd, 1, r, rlen);
}

static void s8ts_wait(unsigned ms);

static bool
s8ts_cmd_write(uint8_t cmd, const uint8_t *w, unsigned wlen)
{
	uint8_t buf[4];
	if (wlen > sizeof(buf) - 1) {
		return false;
	}
	buf[0] = cmd;
	for (unsigned i = 0; i < wlen; i++) {
		buf[i + 1] = w[i];
	}
	return s8i2c_xfer(s8ts_i2c, S8TS_ADDR, buf, wlen + 1, NULL, 0);
}

/* sec_ts_wait_for_ready(SEC_TS_ACK_BOOT_COMPLETE): the IC posts an INFO
 * event (eid 2, status id 0) when its firmware is up. Reads and discards
 * whatever else is queued. */
static bool
s8ts_wait_boot_complete(void)
{
	uint8_t ev[8];
	for (unsigned i = 0; i < 40; i++) {
		if (!s8ts_cmd_read(S8TS_READ_ONE_EVENT, ev, 8) && ev[0]) {
			if (((ev[0] >> 2) & 0xf) == 2 && ev[1] == 0) {
				printf("S8 TOUCH: boot complete event after %u polls\n", i + 1);
				return true;
			}
		}
		s8ts_wait(10);
	}
	return false;
}

/* S-Boot (or a previous iOS boot) can leave the IC in low-power mode
 * (0xE4 = 1). SENSE_ON does not resume scanning then; Samsung's
 * sec_ts_set_lowpowermode(TO_TOUCH_MODE) writes 0xE4 = 0, waits 50 ms and
 * reads it back. */
static void
s8ts_exit_low_power(void)
{
	uint8_t mode = 0xff;
	uint8_t touch = S8TS_POWER_MODE_TOUCH;
	if (!s8ts_cmd_read(S8TS_CMD_SET_POWER_MODE, &mode, 1)) {
		printf("S8 TOUCH: power mode read failed\n");
		return;
	}
	printf("S8 TOUCH: power mode %#x\n", mode);
	if (mode == S8TS_POWER_MODE_TOUCH) {
		return;
	}
	if (!s8ts_cmd_write(S8TS_CMD_SET_POWER_MODE, &touch, 1)) {
		printf("S8 TOUCH: exit low-power failed\n");
		return;
	}
	s8ts_wait(50);
	if (s8ts_cmd_read(S8TS_CMD_SET_POWER_MODE, &mode, 1)) {
		printf("S8 TOUCH: power mode after exit %#x\n", mode);
	}
}

static void
s8ts_report(const uint8_t *ev)
{
	if ((ev[0] & 3) != 0 || !(ev[0] & 0x3c)) {
		return;         /* status/info event, or no touch id */
	}
	unsigned tid = ((ev[0] & 0x3cu) >> 2) - 1;
	unsigned state = (ev[0] & 0xc0u) >> 6;
	if (tid >= S8TS_FINGERS) {
		return;
	}
	unsigned x = ((unsigned)ev[1] << 4) | (ev[3] >> 4);
	unsigned y = ((unsigned)ev[2] << 4) | (ev[3] & 0xf);
	if (s8ts_native) {
		x = x * 1080 / 4096;
		y = y * 1920 / 4096;
	} else if (s8ts_scaled) {
		/* 1125x2436 scaled by 2960/2436 to 1367x2960, centered (36 px bars). */
		int px = ((int)(x * 1440 / 4096) - (1440 - 1367) / 2) * 2436 / 2960;
		int py = (int)(y * 2436 / 4096);
		px = px < 0 ? 0 : (px > 1124 ? 1124 : px);
		py = py < 0 ? 0 : (py > 2435 ? 2435 : py);
		x = (unsigned)px * 1080 / 1125;
		y = (unsigned)py * 1920 / 2436;
	} else {
		/* 1125x2436 is shown centered on the 1440x2960 panel. */
		int px = (int)(x * 1440 / 4096) - (1440 - 1125) / 2;
		int py = (int)(y * 2960 / 4096) - (2960 - 2436) / 2;
		px = px < 0 ? 0 : (px > 1124 ? 1124 : px);
		py = py < 0 ? 0 : (py > 2435 ? 2435 : py);
		x = (unsigned)px * 1080 / 1125;
		y = (unsigned)py * 1920 / 2436;
	}
	if (state == 1 || state == 2) {             /* press, move */
		if (!s8ts_down[tid]) {
			printf("S8 TOUCH: down id=%u x=%u y=%u\n", tid, x, y);
		}
		s8ts_down[tid] = true;
		s8ts_x[tid] = (uint16_t)x;
		s8ts_y[tid] = (uint16_t)y;
		if (tid < 5) {
			sweet_hid_touch((int)tid, 1, (int)x, (int)y);
		}
	} else if (state == 3 && s8ts_down[tid]) { /* release */
		s8ts_down[tid] = false;
		if (tid < 5) {
			sweet_hid_touch((int)tid, 0, s8ts_x[tid], s8ts_y[tid]);
		}
	}
}

static void
s8ts_wait(unsigned ms)
{
	uint64_t deadline;
	clock_interval_to_deadline(ms, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&s8ts_sleep, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}

static void
s8ts_thread(void *arg, wait_result_t result)
{
	uint8_t buf[8 * 32];
	unsigned errors = 0;
	(void)arg;
	(void)result;
	printf("S8 TOUCH: worker started\n");
	for (;;) {
		/* INT is level low while events are queued. Some bring-up
		 * states leave the line high even with events pending (wrong
		 * pin, or an IC that never drives it), so s8tspoll=1 reads the
		 * queue unconditionally. */
		if (!s8ts_poll && (a5touch_read(s8ts_alive, S8TS_GPA1_DAT) & 1u)) {
			s8ts_wait(8);
			continue;
		}
		if (!s8ts_cmd_read(S8TS_READ_ONE_EVENT, buf, 8)) {
			if (++errors <= 8 || !(errors & 255)) {
				printf("S8 TOUCH: event read failed (%u)\n", errors);
			}
			s8ts_wait(20);
			continue;
		}
		if (s8ts_raw > 0 && buf[0]) {
			s8ts_raw--;
			printf("S8 TOUCH: raw %02x %02x %02x %02x %02x %02x %02x %02x\n",
			    buf[0], buf[1], buf[2], buf[3], buf[4], buf[5], buf[6], buf[7]);
		}
		unsigned left = buf[7] & 0x3fu;
		if (buf[0] && left && left < 32 &&
		    !s8ts_cmd_read(S8TS_READ_ALL_EVENT, buf + 8, left * 8)) {   /* READ_ALL_EVENT */
			left = 0;
		}
		if (!buf[0]) {
			s8ts_wait(8);       /* empty queue */
			continue;
		}
		for (unsigned i = 0; i <= left; i++) {
			if (buf[i * 8]) {
				s8ts_report(buf + i * 8);
			}
		}
		errors = 0;
	}
}

static bool
s8bat_read16(unsigned addr, uint8_t reg, uint16_t *value)
{
	uint8_t b[2];
	if (!s8i2c_xfer(s8bat_i2c, addr, &reg, 1, b, 2)) {
		return false;
	}
	*value = (uint16_t)(b[0] | (b[1] << 8));
	return true;
}

/*
 * SweetBattery (patch 0124) calls this every 30 s. 0 = valid sample.
 * MAX77865 fuel gauge: SOCREP 0x06 in 1/256 %, VCELL 0x09 in 78.125 uV,
 * CURRENT 0x0a signed 156.25 uA (0.01 ohm sense, positive = charging).
 * Charger: INT_OK 0xb2 bit 6 CHGIN_OK; DETAILS_01 0xb4 [3:0] 0-2 charging,
 * 3-4 done.
 */
int dreamlte_battery_read(unsigned *percent, unsigned *mv, int *ma,
    int *external, int *charging, int *full);
int
dreamlte_battery_read(unsigned *percent, unsigned *mv, int *ma,
    int *external, int *charging, int *full)
{
	uint16_t soc, vcell, cur;
	uint8_t reg, ok = 0, dtls = 0;
	if (!s8bat_i2c) {
		s8bat_i2c = ml_io_map(S8BAT_HSI2C_PA, 0x1000);
		if (!s8bat_i2c) {
			return -1;
		}
		s8i2c_reset(s8bat_i2c);
	}
	if (!s8bat_read16(S8BAT_FG, 0x06, &soc) || !s8bat_read16(S8BAT_FG, 0x09, &vcell) ||
	    !s8bat_read16(S8BAT_FG, 0x0a, &cur)) {
		return -1;
	}
	reg = 0xb2;
	(void)s8i2c_xfer(s8bat_i2c, S8BAT_CHG, &reg, 1, &ok, 1);
	reg = 0xb4;
	(void)s8i2c_xfer(s8bat_i2c, S8BAT_CHG, &reg, 1, &dtls, 1);
	unsigned pct = (unsigned)(soc >> 8) + ((soc & 0xffu) >= 128 ? 1 : 0);
	*percent = pct > 100 ? 100 : pct;
	*mv = (unsigned)((uint32_t)vcell * 78125u / 1000000u);
	*ma = (int)((int16_t)cur) * 15625 / 100000;
	*external = (ok & 0x40u) != 0;
	dtls &= 0x0f;
	*charging = *external && dtls <= 2;
	*full = *external && (dtls == 3 || dtls == 4);
	return (*mv >= 2800 && *mv <= 4600) ? 0 : -1;
}

/*
 * Test input for unattended smoothness measurements: boot-arg s8swipe=N
 * plays a scripted gesture every N seconds with a sixth finger (id 4)
 * through the same HID path as the panel, starting s8swipe_start seconds
 * (default 300) after the touch driver: the first turn presses Home to wake
 * the screen and swipes up to unlock (run p2: iOS had turned the idle lock
 * screen off, so swipes alone drew nothing); the others are home-screen page
 * swipes left and right, which keep the display awake. (Run p3 pressed Home
 * again every 20 turns; after the first repeat the frame rate collapsed.)
 * Off by default.
 */
extern uint64_t mach_absolute_time(void);
extern void sweet_hid_key(int key, int down);  /* 3 = Home (Menu) */
static unsigned s8ts_swipe_secs, s8ts_swipe_start = 300;

static void
s8ts_swipe(int x0, int y0, int x1, int y1)
{
	for (int i = 0; i <= 12; i++) {             /* 12 steps of 25 ms */
		sweet_hid_touch(4, 1, x0 + (x1 - x0) * i / 12, y0 + (y1 - y0) * i / 12);
		s8ts_wait(25);
	}
	sweet_hid_touch(4, 0, x1, y1);
}

static void
s8ts_script_thread(void *arg, wait_result_t result)
{
	(void)arg;
	(void)result;
	for (unsigned s = 0; s < s8ts_swipe_start; s++) {
		s8ts_wait(1000);
	}
	for (unsigned n = 0;; n++) {
		printf("S8 SWIPE: %u at %llu s\n", n, mach_absolute_time() / 26000000ULL);
		if (n == 0) {
			sweet_hid_key(3, 1);                 /* Home: wake the display */
			s8ts_wait(100);
			sweet_hid_key(3, 0);
			s8ts_wait(1500);
			s8ts_swipe(540, 1880, 540, 700);   /* from the bottom edge: unlock */
		} else if (n & 1) {
			s8ts_swipe(900, 1000, 150, 1000);  /* next home-screen page */
		} else {
			s8ts_swipe(150, 1000, 900, 1000);  /* back */
		}
		for (unsigned s = 0; s < s8ts_swipe_secs; s++) {
			s8ts_wait(1000);
		}
	}
}

static void
dreamlte_touch_start(void)
{
	uint8_t b[11] = {0};
	thread_t thread;
	int enabled = 1;
	(void)PE_parse_boot_argn("s8touch", &enabled, sizeof(enabled));
	(void)PE_parse_boot_argn("sweetfb_native", &s8ts_native, sizeof(s8ts_native));
	(void)PE_parse_boot_argn("sweetfb_scale", &s8ts_scaled, sizeof(s8ts_scaled));
	(void)PE_parse_boot_argn("s8tspoll", &s8ts_poll, sizeof(s8ts_poll));
	(void)PE_parse_boot_argn("s8tsdebug", &s8ts_raw, sizeof(s8ts_raw));
	/* Scripted test input does not depend on the panel answering. */
	(void)PE_parse_boot_argn("s8swipe", &s8ts_swipe_secs, sizeof(s8ts_swipe_secs));
	(void)PE_parse_boot_argn("s8swipe_start", &s8ts_swipe_start, sizeof(s8ts_swipe_start));
	if (s8ts_swipe_secs != 0 &&
	    kernel_thread_start(s8ts_script_thread, NULL, &thread) == KERN_SUCCESS) {
		printf("S8 TOUCH: scripted swipes every %u s from %u s\n", s8ts_swipe_secs, s8ts_swipe_start);
		thread_deallocate(thread);
	}
	if (!enabled) {
		printf("S8 TOUCH: disabled\n");
		return;
	}
	s8ts_i2c = ml_io_map(S8TS_HSI2C_PA, 0x1000);
	s8ts_alive = ml_io_map(S8TS_ALIVE_PA, 0x1000);
	if (!s8ts_i2c || !s8ts_alive) {
		printf("S8 TOUCH: MMIO mapping failed\n");
		return;
	}
	s8i2c_reset(s8ts_i2c);

	/* Boot status 0x20 = application firmware. A Note 8 (y661) resets
	 * with 0x42 and an S8 (y761) with 0x12; sending both costs 100 ms and
	 * an IC already in application mode ignores them. */
	bool status_ok = s8ts_cmd_read(S8TS_READ_BOOT_STATUS, b, 1);
	printf("S8 TOUCH: boot status %#x%s\n", b[0], status_ok ? "" : " (read failed)");
	if (!status_ok || b[0] != S8TS_STATUS_APP_MODE) {
		uint8_t reset = S8TS_CMD_SW_RESET_Y661;
		printf("S8 TOUCH: not in app mode, soft reset\n");
		(void)s8ts_cmd_write(reset, NULL, 0);
		s8ts_wait(50);
		reset = S8TS_CMD_SW_RESET_Y761;
		(void)s8ts_cmd_write(reset, NULL, 0);
		s8ts_wait(120);
		status_ok = s8ts_cmd_read(S8TS_READ_BOOT_STATUS, b, 1);
		printf("S8 TOUCH: boot status after reset %#x%s\n", b[0], status_ok ? "" : " (read failed)");
	}
	/* Identity: 0x52 is the S6SY761's three-byte id (0xac3761 on the S8),
	 * 0x22 the five-byte device id the y661 driver prints. */
	if (s8ts_cmd_read(S8TS_READ_ID, b, 3)) {
		printf("S8 TOUCH: id52 %02x%02x%02x\n", b[0], b[1], b[2]);
	} else {
		printf("S8 TOUCH: id52 read failed\n");
	}
	if (s8ts_cmd_read(S8TS_READ_DEVICE_ID, b, 5)) {
		printf("S8 TOUCH: id22 %02x%02x%02x%02x%02x\n", b[0], b[1], b[2], b[3], b[4]);
	} else {
		printf("S8 TOUCH: id22 read failed\n");
	}
	if (s8ts_cmd_read(S8TS_READ_TS_STATUS, b, 4)) {
		printf("S8 TOUCH: ts status %02x %02x %02x %02x\n", b[0], b[1], b[2], b[3]);
	}
	if (s8ts_cmd_read(S8TS_READ_FW_INTEGRITY, b, 1)) {
		printf("S8 TOUCH: fw integrity %#x%s\n", b[0], (b[0] & 0x80) ? " ok" : " INVALID");
	}

	/* The controller only accepts a touch function after its firmware
	 * posts the boot-complete INFO event (sec_ts_start_device order). */
	if (!s8ts_wait_boot_complete()) {
		printf("S8 TOUCH: no boot-complete event, trying anyway\n");
	}
	s8ts_exit_low_power();

	uint8_t func[2] = { S8TS_FUNC_TOUCH_PALM_WET, 0x00 };
	uint8_t sense = S8TS_CMD_SENSE_ON;
	/* The y661 ACKs SET_FUNC but can refuse SENSE_ON (0x10) with a NAK
	 * while it is already scanning - observed in the loader on 2026-10-23:
	 * setfn=0x0, sense=0x200c, and 40 coordinate events right after. Samsung
	 * logs the same failure and carries on (sec_ts_start_device). Bailing
	 * here cost the whole boot, so the writes are best-effort now and the
	 * register read-back decides whether the IC is running. */
	bool func_ok = false, sense_ok = false;
	unsigned tries = 0;
	for (tries = 0; tries < 5; tries++) {
		func_ok = s8ts_cmd_write(S8TS_CMD_SET_FUNC, func, 2);
		if (func_ok) {
			sense_ok = s8ts_cmd_write(sense, NULL, 0);
			if (sense_ok) {
				break;
			}
		}
		s8ts_wait(20);
		s8i2c_reset(s8ts_i2c);
	}
	printf("S8 TOUCH: enable writes func %s, sense %s after %u tries\n",
	    func_ok ? "ok" : "failed", sense_ok ? "ok" : "refused", tries);
	if (s8ts_cmd_read(S8TS_CMD_SET_FUNC, b, 2)) {
		printf("S8 TOUCH: touch function now %02x %02x\n", b[0], b[1]);
	}
	if (s8ts_cmd_read(S8TS_READ_TS_STATUS, b, 4)) {
		printf("S8 TOUCH: ts status after enable %02x %02x %02x %02x\n",
		    b[0], b[1], b[2], b[3]);
	}
	if (s8ts_cmd_read(S8TS_CMD_SET_POWER_MODE, b, 1)) {
		printf("S8 TOUCH: power mode now %#x\n", b[0]);
	}
	printf("S8 TOUCH: irq line %u\n",
	    a5touch_read(s8ts_alive, S8TS_GPA1_DAT) & 1u);
	if (kernel_thread_start(s8ts_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	} else {
		printf("S8 TOUCH: thread start failed\n");
	}
}
#endif /* DREAMLTE */


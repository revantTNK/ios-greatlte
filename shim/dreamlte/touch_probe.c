/* SPDX-License-Identifier: GPL-2.0-only
 * Samsung Exynos 8895 touchscreen probe, run by the loader before XNU
 * (MMU off). Covers both controllers this port meets:
 *
 * - dreamlte (S8, SM-G950F/N): Samsung S6SY761 ("y761"), mainline
 *   s6sy761.c protocol; id 0xac3761 via READ_ID 0x52.
 * - greatlte (Note 8, SM-N950F/N): Samsung "y661" (sec_ts_y661 in Samsung's
 *   4.4 tree, firmware tsp_sec/y661_great.fw). Same bus, address, IRQ,
 *   rails and event format, but its own ID registers (READ_DEVICE_ID 0x22,
 *   five bytes) and SW_RESET 0x42 instead of 0x12.
 *
 * Both sit at 0x48 on hsi2c_23 = USI09 of PERIC1 (0x108e0000), SCL/SDA
 * gpe3-1/gpe3-0 function 2, interrupt gpa1-0 active low, rails S2MPS17
 * LDO34 "tsp_io" 1.85 V and LDO35 "tsp_avdd" (S8 3.0 V, Note 8 3.3 V,
 * enabled by pmic_init just before this).
 *
 * Polled, no interrupts: every step is logged before the next MMIO access,
 * so a hang shows the access that stalled. Boot args:
 *   s8tsreset=1  power-cycle the two rails before talking to the IC
 *   s8tsprobe=N  poll events for N seconds (default 4, at most 60)
 * Touch the panel during the loader screen to see coordinate events.
 */
#include <stdint.h>
#include "touch_probe.h"
#include "pmic.h"

#define CMU_TOP			0x15a80000UL
#define CMU_PERIC1		0x10800000UL
#define TOP_USI09_MUX		(CMU_TOP + 0x10e0)
#define TOP_USI09_DIV		(CMU_TOP + 0x18e8)
#define TOP_USI09_GATE		(CMU_TOP + 0x20ec)
#define P1_USI09_USER_MUX	(CMU_PERIC1 + 0x0240)	/* PLL_CON0, bit 4 = SEL */
#define P1_USI09_PCLK		(CMU_PERIC1 + 0x20ac)
#define P1_USI09_SCLK		(CMU_PERIC1 + 0x20b0)
#define GATE_ON			((1u << 21) | (1u << 20))	/* MANUAL | CG_VALUE */
#define SYSREG_USI09		0x1082101cUL
#define USI_V1_I2C0_1		0x3u			/* stock "hsi2c0_hsi2c1" */
#define GPE3			(0x10980000UL + 0x120)	/* CON, DAT, PUD, DRV */
#define GPA1			(0x164b0000UL + 0x040)

#define HSI2C			0x108e0000UL
#define CTL			0x00
#define FIFO_CTL		0x04
#define TRAILIG_CTL		0x08
#define INT_ENABLE		0x20
#define INT_STATUS		0x24
#define FIFO_STATUS		0x30
#define TX_DATA			0x34
#define RX_DATA			0x38
#define CONF			0x40
#define AUTO_CONF		0x44
#define TIMEOUT			0x48
#define TRANS_STATUS		0x50
#define TIMING_FS1		0x60
#define TIMING_FS2		0x64
#define TIMING_FS3		0x68
#define TIMING_SLA		0x6c
#define ADDR			0x70

#define CTL_I2C_MASTER		((1u << 0) | (1u << 3))
#define CTL_RXCHON		(1u << 6)
#define CTL_TXCHON		(1u << 7)
#define CTL_SW_RST		(1u << 31)
#define CONF_AUTO_MODE		(1u << 31)
#define AUTO_READ		(1u << 16)
#define AUTO_STOP		(1u << 17)
#define AUTO_RUN		(1u << 31)
#define INT_DONE		(1u << 7)
#define INT_ERRS		(0xfu << 8)	/* abort, no ack, no dev, timeout */
#define RX_EMPTY		(1u << 24)
#define TX_FULL			(1u << 7)

#define TS_ADDR			0x48
#define TIMER_HZ		26000000UL
#define CLKIN			26000000u	/* USI09 user mux forced to OSCCLK */
#define SCL_HZ			400000u

static void (*kv)(const char *, uint64_t);
static void (*out)(const char *);

static inline uint32_t rd(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
static uintptr_t bus = HSI2C;	/* controller in use */
static unsigned dev = TS_ADDR;	/* I2C device address */
static inline uint32_t hr(unsigned o) { return rd(bus + o); }
static inline void hw(unsigned o, uint32_t v) { wr(bus + o, v); }

static uint64_t ticks(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

static void delay_ms(unsigned ms)
{
	uint64_t end = ticks() + TIMER_HZ / 1000 * ms;
	while (ticks() < end)
		;
}

static void show(const char *k, uintptr_t a)
{
	kv(k, rd(a));
}

/* i2c-exynos5.c exynos5_i2c_set_timing(), I2C_TYPE_EXYNOS8895, fast mode */
static void set_timing(void)
{
	unsigned ftl = (hr(CONF) >> 16) & 7;
	unsigned temp = CLKIN / SCL_HZ - (ftl + 3) * 2;
	unsigned div = temp / 512;
	unsigned cyc = (temp + ((ftl + 3) % (div + 1)) * 2) / (div + 1) - 2;
	unsigned l = cyc * 64 / 100, h = cyc - l;
	hw(TIMING_FS1, l << 24 | l << 16 | l << 8);
	hw(TIMING_FS2, (l / 2) << 24 | l << 8 | h);
	hw(TIMING_FS3, div << 16 | cyc);
	hw(TIMING_SLA, l / 2);
}

static void hsi2c_reset(void)
{
	hw(CTL, hr(CTL) | CTL_SW_RST);
	hw(CTL, hr(CTL) & ~CTL_SW_RST);
	set_timing();
	hw(TIMEOUT, hr(TIMEOUT) & ~(1u << 31));
	hw(CTL, CTL_I2C_MASTER);
	hw(TRAILIG_CTL, 0xf);
	hw(CONF, hr(CONF) | CONF_AUTO_MODE);
}

/* Wait for TRANS_DONE or an error; 0 on success, else the status bits. */
static uint32_t wait_done(void)
{
	uint64_t end = ticks() + TIMER_HZ / 20;
	for (;;) {
		uint32_t s = hr(INT_STATUS);
		if (s & (INT_DONE | INT_ERRS)) {
			hw(INT_STATUS, s);
			return (s & INT_ERRS) ? s : 0;
		}
		if (ticks() > end)
			return 0x80000000u | hr(TRANS_STATUS);
	}
}

/* Write wlen bytes, then (repeated start) read rlen bytes; 0 = ok. */
static uint32_t xfer(const uint8_t *w, unsigned wlen, uint8_t *r, unsigned rlen)
{
	uint32_t st;
	hw(INT_STATUS, hr(INT_STATUS));
	hw(ADDR, (dev & 0x3ff) << 10);
	hw(INT_ENABLE, INT_DONE | INT_ERRS);
	if (wlen) {
		hw(FIFO_CTL, 3);
		hw(CTL, CTL_I2C_MASTER | CTL_TXCHON);
		hw(AUTO_CONF, (rlen ? 0 : AUTO_STOP) | wlen | AUTO_RUN);
		for (unsigned i = 0; i < wlen; i++) {
			uint64_t end = ticks() + TIMER_HZ / 100;
			while ((hr(FIFO_STATUS) & TX_FULL) && ticks() < end)
				;
			hw(TX_DATA, w[i]);
		}
		if ((st = wait_done()))
			goto bad;
	}
	if (rlen) {
		hw(FIFO_CTL, 3);
		hw(CTL, CTL_I2C_MASTER | CTL_RXCHON);
		hw(AUTO_CONF, AUTO_READ | AUTO_STOP | rlen | AUTO_RUN);
		for (unsigned i = 0; i < rlen; i++) {
			uint64_t end = ticks() + TIMER_HZ / 20;
			while ((hr(FIFO_STATUS) & RX_EMPTY) && ticks() < end)
				;
			if (hr(FIFO_STATUS) & RX_EMPTY) {
				st = 0x40000000u | i;
				goto bad;
			}
			r[i] = (uint8_t)hr(RX_DATA);
		}
		if ((st = wait_done()))
			goto bad;
	}
	hw(CTL, CTL_I2C_MASTER);
	return 0;
bad:
	hsi2c_reset();
	return st;
}

static void dump(const char *what, const uint8_t *b, unsigned n, uint32_t st)
{
	out(what);
	kv(" st", st);
	if (!st) {
		uint64_t v = 0;
		for (unsigned i = 0; i < n && i < 8; i++)
			v = v << 8 | b[i];
		kv("data", v);
	}
	out("\n");
}

/* Same "key=number" scan as loader.c cmdline_u32(). */
static uint32_t arg_u32(const char *line, const char *key)
{
	if (!line)
		return 0;
	for (int i = 0; line[i]; i++) {
		if (i && line[i - 1] != ' ')
			continue;
		int k = 0;
		while (key[k] && line[i + k] == key[k])
			k++;
		if (key[k] || line[i + k] != '=')
			continue;
		uint32_t v = 0;
		for (int j = i + k + 1; line[j] >= '0' && line[j] <= '9'; j++)
			v = v * 10 + (uint32_t)(line[j] - '0');
		return v;
	}
	return 0;
}

static uint32_t reg1(uint8_t cmd, uint8_t *b, unsigned n, uint8_t *v)
{
	uint32_t st = xfer(&cmd, 1, b, n);
	*v = st ? 0 : b[0];
	return st;
}

void touch_probe(void (*kv_fn)(const char *, uint64_t), void (*out_fn)(const char *),
    const char *cmdline)
{
	uint8_t c, b[11], v = 0;
	uint32_t st, bst;

	kv = kv_fn;
	out = out_fn;
	out("TOUCH probe (sec_ts y661/y761 hsi2c_23 0x108e0000)\n");
	delay_ms(200);	/* rails just enabled by pmic_init; s6sy761.c waits 140 */
	show("top mux", TOP_USI09_MUX);
	show("div", TOP_USI09_DIV);
	show("gate", TOP_USI09_GATE);
	out("\n");
	show("p1 user", P1_USI09_USER_MUX);
	show("pclk", P1_USI09_PCLK);
	show("sclk", P1_USI09_SCLK);
	show("sysreg", SYSREG_USI09);
	out("\n");
	show("gpe3 con", GPE3);
	show("dat", GPE3 + 4);
	show("pud", GPE3 + 8);
	show("gpa1 con", GPA1);
	show("dat", GPA1 + 4);
	out("\n");

	wr(P1_USI09_PCLK, rd(P1_USI09_PCLK) | GATE_ON);
	wr(P1_USI09_SCLK, rd(P1_USI09_SCLK) | GATE_ON);
	wr(P1_USI09_USER_MUX, rd(P1_USI09_USER_MUX) & ~(1u << 4));
	wr(SYSREG_USI09, (rd(SYSREG_USI09) & ~0xfu) | USI_V1_I2C0_1);
	wr(GPE3, (rd(GPE3) & ~0xffu) | 0x22);
	wr(GPE3 + 8, rd(GPE3 + 8) & ~0xffu);
	out("clocks/pins set: ");
	show("pclk", P1_USI09_PCLK);
	show("user", P1_USI09_USER_MUX);
	show("sysreg", SYSREG_USI09);
	show("gpe3", GPE3);
	out("\n");

	/* A Note 8 (greatlte) may leave the IC in a state S-Boot created; the
	 * rails are only a few ms old here, so a restart costs little. */
	if (arg_u32(cmdline, "s8tsreset")) {
		out("TOUCH rail power cycle\n");
		kv("l34 off rc", (uint64_t)(uint32_t)pmic_write(0x5f, 0));
		kv("l35 off rc", (uint64_t)(uint32_t)pmic_write(0x60, 0));
		delay_ms(50);
		kv("l34 on rc", (uint64_t)(uint32_t)pmic_write(0x5f, 0x40 | (1850000 - 700000) / 25000));
		kv("l35 on rc", (uint64_t)(uint32_t)pmic_write(0x60, 0x40 | (3300000 - 1800000) / 25000));
		delay_ms(100);
		out("\n");
	}

	out("hsi2c regs: ");
	kv("ctl", hr(CTL));
	kv("conf", hr(CONF));
	kv("trans", hr(TRANS_STATUS));
	kv("fifo", hr(FIFO_STATUS));
	out("\n");
	hsi2c_reset();
	out("reset: ");
	kv("ctl", hr(CTL));
	kv("conf", hr(CONF));
	kv("fs2", hr(TIMING_FS2));
	kv("fs3", hr(TIMING_FS3));
	out("\n");

	/* Identity and state. Both chips implement all of these; 0x22 is the
	 * five-byte device id (y661 uses it in its probe), 0x52 the three-byte
	 * id the S8 driver has printed since boot 26 (0xac3761). */
	c = 0x55;	/* BOOT_STATUS: 0x20 = application, 0x10 = boot mode */
	bst = reg1(c, b, 1, &v);
	dump("boot st", b, 1, bst);
	c = 0x52;	/* READ_ID */
	st = xfer(&c, 1, b, 3);
	dump("id52", b, 3, st);
	c = 0x22;	/* READ_DEVICE_ID, five bytes */
	st = xfer(&c, 1, b, 5);
	dump("id22", b, 5, st);
	c = 0x23;	/* PANEL_INFO: max_x/max_y be16, nodes at [8], [9] */
	st = xfer(&c, 1, b, 11);
	dump("panel", b, 8, st);
	c = 0x21;	/* FIRMWARE_INTEGRITY: 0x80 valid */
	st = xfer(&c, 1, b, 1);
	dump("fw ok", b, 1, st);
	c = 0xaf;	/* READ_TS_STATUS: mode, ... */
	st = xfer(&c, 1, b, 4);
	dump("ts st", b, 4, st);
	c = 0x30;	/* SET/GET_TOUCHFUNCTION, two bytes */
	st = xfer(&c, 1, b, 2);
	dump("func", b, 2, st);
	kv("irq", rd(GPA1 + 4) & 1);
	out("\n");

	if (bst || v != 0x20) {
		/* y661 resets with 0x42, y761 with 0x12. Try both, then look
		 * again; an IC that is already in app mode ignores them. */
		c = 0x42;
		st = xfer(&c, 1, 0, 0);
		kv("swrst42", st);
		delay_ms(50);
		c = 0x12;
		st = xfer(&c, 1, 0, 0);
		kv("swrst12", st);
		delay_ms(120);
		c = 0x55;
		bst = reg1(c, b, 1, &v);
		dump("boot st2", b, 1, bst);
		out("\n");
	}

	/* Drain the queue until the IC reports its boot-complete INFO event
	 * (y661/y761 sec_ts_start_device does the same before enabling). */
	unsigned bootev = 0;
	for (unsigned i = 0; i < 25; i++) {
		c = 0x60;
		st = xfer(&c, 1, b, 8);
		if (!st && b[0]) {
			dump("ev", b, 8, st);
			if (((b[0] >> 2) & 0xf) == 2 && b[1] == 0) {
				bootev = i + 1;
				break;
			}
		}
		delay_ms(20);
	}
	kv("bootev", bootev);
	out("\n");

	/* y661 and y761 both default to TOUCH|PALM|WET = 0x61 (little endian). */
	uint8_t fn[3] = {0x30, 0x61, 0x00};
	kv("setfn", xfer(fn, 3, 0, 0));
	c = 0x10;	/* SENSE_ON */
	kv("sense", xfer(&c, 1, 0, 0));
	out("\n");
	kv("irq2", rd(GPA1 + 4) & 1);
	out("\n");

	/* Poll events whether or not the IRQ line says so: this tells a dead
	 * IC (no answer) from a wrong IRQ pin (events but no line). */
	unsigned secs = arg_u32(cmdline, "s8tsprobe");
	if (secs == 0)
		secs = 4;
	if (secs > 60)
		secs = 60;
	unsigned shown = 0, reads = 0, got = 0;
	uint64_t end = ticks() + (uint64_t)TIMER_HZ * secs;
	while (ticks() < end && shown < 40) {
		c = 0x60;	/* READ_ONE_EVENT */
		st = xfer(&c, 1, b, 8);
		reads++;
		if (st) {
			delay_ms(50);
			continue;
		}
		if (!b[0]) {
			delay_ms(8);	/* empty queue */
			continue;
		}
		got++;
		dump("ev", b, 8, st);
		shown++;
	}
	kv("reads", reads);
	kv("events", got);
	kv("irq3", rd(GPA1 + 4) & 1);
	out("\nTOUCH probe done\n");

	/* Keep the loader screen (and this output) for photos: s8tspause=20
	 * holds it 20 s before the jump to XNU. Not set = jump immediately. */
	unsigned pause = arg_u32(cmdline, "s8tspause");
	if (pause) {
		if (pause > 120)
			pause = 120;
		out("holding screen ");
		for (unsigned i = 0; i < pause; i++) {
			out(".");
			delay_ms(1000);
		}
		out("\n");
	}
}

/*
 * Battery: MAX77865 on hsi2c_32 = second HSI2C of USI13 (0x10970000), pins
 * gpe5-6/7 function 2 (PERIC1 bank gpe5 at +0xc0), stock USI mode
 * "uart_hsi2c1" (v1 SW_CONF 0xa). Fuel gauge 0x36, charger 0x69. The
 * kernel's SweetBattery (patch 0124) polls the same registers.
 */
#define P1_USI13_USER_MUX	(CMU_PERIC1 + 0x02c0)
#define P1_USI13_PCLK		(CMU_PERIC1 + 0x20cc)
#define P1_USI13_SCLK		(CMU_PERIC1 + 0x20d0)
#define SYSREG_USI13		0x1082102cUL
#define USI_V1_UART_I2C1	0xau
#define GPE5			(0x10980000UL + 0x0c0)

/* One 16-bit little-endian fuel-gauge register. */
static void fg_show(const char *name, uint8_t reg)
{
	uint8_t b[2];
	uint32_t st = xfer(&reg, 1, b, 2);
	kv(name, st ? 0xdead0000u | (st & 0xffff) : (uint32_t)(b[0] | b[1] << 8));
}

void battery_probe(void (*kv_fn)(const char *, uint64_t), void (*out_fn)(const char *))
{
	uint8_t r, b[2];
	kv = kv_fn;
	out = out_fn;
	out("BATTERY (MAX77865 hsi2c_32 0x10970000)\n");
	show("sysreg", SYSREG_USI13);
	show("gpe5", GPE5);
	out("\n");
	wr(P1_USI13_PCLK, rd(P1_USI13_PCLK) | GATE_ON);
	wr(P1_USI13_SCLK, rd(P1_USI13_SCLK) | GATE_ON);
	wr(P1_USI13_USER_MUX, rd(P1_USI13_USER_MUX) & ~(1u << 4));
	wr(SYSREG_USI13, (rd(SYSREG_USI13) & ~0xfu) | USI_V1_UART_I2C1);
	wr(GPE5, (rd(GPE5) & ~0xff000000u) | 0x22000000u);
	wr(GPE5 + 8, rd(GPE5 + 8) & ~0xf000u);
	bus = 0x10970000UL;
	hsi2c_reset();
	dev = 0x36;
	fg_show("soc", 0x06);
	fg_show("vcell", 0x09);
	fg_show("cur", 0x0a);
	fg_show("design", 0x18);
	out("\n");
	dev = 0x69;
	r = 0xb2;
	kv("chg int_ok", xfer(&r, 1, b, 1) ? 0xdead : b[0]);
	r = 0xb4;
	kv("dtls01", xfer(&r, 1, b, 1) ? 0xdead : b[0]);
	out("\n");
	bus = HSI2C;
	dev = TS_ADDR;
}

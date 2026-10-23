/* SPDX-License-Identifier: GPL-2.0-only
 * Galaxy S8 PMIC (S2MPS17) access over the Exynos SPEEDY bus, MMU off.
 *
 * touch_probe v25 found the touch controller unpowered under our boot: SDA
 * held low (HSI2C master state LOSE) and the gpa1-0 interrupt line at 0.
 * Its rails are S2MPS17 LDO34 "tsp_io" 1.85 V and LDO35 "tsp_avdd" 3.3 V;
 * S-Boot leaves them off and Samsung's Linux turns them on. The SPEEDY
 * transfer and the LDO values follow uniLoader (board-dreamlte.c,
 * drivers/samsung/exynos-speedy.c); the RTC layout follows Samsung's
 * rtc-s2mp.h (RTC on SPEEDY slave 2, binary counters from 0x04).
 */
#include <stdint.h>
#include "pmic.h"

#define SPEEDY			0x15b50000UL
#define SP_FIFO_CTRL		0x004
#define SP_CMD			0x008
#define SP_INT_ENABLE		0x00c
#define SP_INT_STATUS		0x010
#define SP_TX_DATA		0x034
#define SP_RX_DATA		0x038
#define SP_FIFO_RESET		(1u << 31)
#define SP_LEN(rx, tx)		((rx) | (tx) << 8)
#define SP_RANDOM		(1u << 19)
#define SP_WRITE		(1u << 20)
#define SP_SLAVE(x)		(((x) & 0xf) << 15)
#define SP_ADDR(x)		(((x) & 0xff) << 7)
#define SP_DONE			(1u << 0)

#define SLAVE_PMIC		1
#define SLAVE_RTC		2
#define L34CTRL			0x5f
#define L35CTRL			0x60
#define LDO_EN			(3u << 6)
#define L34_1V85		(LDO_EN | (1850000 - 700000) / 25000)
#define L35_3V3			(LDO_EN | (3300000 - 1800000) / 25000)
#define RTC_UPDATE		0x02
#define RTC_RUDR		0x01
#define RTC_SEC			0x04

#define TIMER_HZ		26000000UL

static void (*kv)(const char *, uint64_t);
static void (*out)(const char *);

static inline uint32_t rd(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

static uint64_t ticks(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

static void delay_us(unsigned us)
{
	uint64_t end = ticks() + TIMER_HZ / 1000000 * us;
	while (ticks() < end)
		;
}

/* One random-access byte transfer; returns the byte read, or < 0. */
static int speedy(unsigned slave, unsigned reg, int write, uint8_t val)
{
	wr(SPEEDY + SP_FIFO_CTRL, SP_FIFO_RESET);
	delay_us(10);
	wr(SPEEDY + SP_FIFO_CTRL, SP_LEN(1, 1));
	wr(SPEEDY + SP_INT_ENABLE, write ? 0x80300011u : 0x80070301u);
	wr(SPEEDY + SP_INT_STATUS, 0xffffffffu);
	wr(SPEEDY + SP_CMD, SP_RANDOM | (write ? SP_WRITE : 0) |
	   SP_SLAVE(slave) | SP_ADDR(reg));
	if (write)
		wr(SPEEDY + SP_TX_DATA, val);
	uint64_t end = ticks() + TIMER_HZ / 100;
	while (ticks() < end) {
		uint32_t s = rd(SPEEDY + SP_INT_STATUS);
		if (s & SP_DONE) {
			wr(SPEEDY + SP_INT_STATUS, 0xffffffffu);
			return write ? 0 : (int)(rd(SPEEDY + SP_RX_DATA) & 0xff);
		}
	}
	return -1;
}

static void show(const char *k, unsigned slave, unsigned reg)
{
	int v = speedy(slave, reg, 0, 0);
	kv(k, v < 0 ? 0xdead : (uint64_t)v);
}

/* Cycles of this core per 10 ms of the 26 MHz system timer. */
static void cpu_freq(void)
{
	uint64_t pmcr;
	__asm__ volatile("mrs %0, pmcr_el0" : "=r"(pmcr));
	__asm__ volatile("msr pmcr_el0, %0" :: "r"(pmcr | 1 | 4));	/* E, reset C */
	__asm__ volatile("msr pmcntenset_el0, %0" :: "r"(1UL << 31));
	__asm__ volatile("msr pmccfiltr_el0, %0" :: "r"(1UL << 27));	/* count EL2 too */
	uint64_t c0, c1, t0 = ticks();
	__asm__ volatile("isb; mrs %0, pmccntr_el0" : "=r"(c0));
	while (ticks() - t0 < TIMER_HZ / 100)
		;
	__asm__ volatile("isb; mrs %0, pmccntr_el0" : "=r"(c1));
	kv("cpu MHz", (c1 - c0) / 10000);
}

/* S2MPS17 PMIC register read for other probes (after pmic_init). */
int pmic_read(unsigned reg)
{
	return speedy(SLAVE_PMIC, reg, 0, 0);
}

int pmic_write(unsigned reg, uint8_t val)
{
	return speedy(SLAVE_PMIC, reg, 1, val);
}

uint64_t pmic_init(void (*kv_fn)(const char *, uint64_t), void (*out_fn)(const char *))
{
	kv = kv_fn;
	out = out_fn;
	out("PMIC (S2MPS17 over SPEEDY 0x15b50000)\n");
	cpu_freq();
	show("pmic id", SLAVE_PMIC, 0x00);
	show("L34", SLAVE_PMIC, L34CTRL);
	show("L35", SLAVE_PMIC, L35CTRL);
	out("\n");
	int r1 = speedy(SLAVE_PMIC, L34CTRL, 1, L34_1V85);
	int r2 = speedy(SLAVE_PMIC, L35CTRL, 1, L35_3V3);
	kv("write rc", (uint64_t)(uint32_t)(r1 | r2));
	show("L34", SLAVE_PMIC, L34CTRL);
	show("L35", SLAVE_PMIC, L35CTRL);
	out("\n");

	/* RTC: latch the counters (RUDR), then sec..year at 0x04..0x0a. */
	int u = speedy(SLAVE_RTC, RTC_UPDATE, 0, 0);
	speedy(SLAVE_RTC, RTC_UPDATE, 1, (uint8_t)((u < 0 ? 0 : u) | RTC_RUDR));
	delay_us(200);
	uint64_t raw = 0;
	out("RTC");
	show(" ctrl", SLAVE_RTC, 0x00);
	for (unsigned i = 0; i < 8; i++) {
		int v = speedy(SLAVE_RTC, RTC_SEC + i, 0, 0);
		raw |= (uint64_t)(v < 0 ? 0xff : v) << (8 * i);
	}
	kv(" sec..year", raw);
	out("\n");
	return raw;
}

/*
 * CPU clocks through the APM firmware (ACPM). On the S8, Samsung's cpufreq
 * driver never touches the PLLs or the BUCKs itself: its cal-ids are ACPM
 * vclks (DT cpufreq/domain@0 0x0b040003 = dvfs_cpucl1, the A53s; domain@1
 * 0x0b040002 = dvfs_cpucl0, Mongoose), and cal_dfs_set_rate sends
 * "FREQ_REQ id kHz" to the APM over the mailbox (acpm_dvfs.c); the firmware
 * sets the BUCK from its ASV table, then the PLL. Layout: Samsung's
 * acpm_ipc.c, acpm.c, fw_header/framework.h and common.h; addresses from
 * TWRP's live DT (acpm_ipc reg + initdata-base; acpm-ipc-channel of acpm
 * and of the CMU node clock-controller@0x15a80000, which Samsung passes to
 * cal_if_init and so to acpm_dvfs; channel 5 of the acpm_dvfs node only
 * carries the APM's MIF notifications, runs c4-c9 got no answer there).
 *
 * S-Boot leaves the APM running its boot framework without the DVFS plugin.
 * Samsung's Linux loads it at boot (TWRP dmesg:
 * "plugin(id = 2) detach done", "Loading exynos8895_acpm_dvfs.fw",
 * "plugin(id = 3) attach done"): plugins_init detaches the plugin that is
 * attached but not stay_attached, copies the built-in blob to the base of
 * the one that is stay_attached but not attached, and attaches it, over
 * channel 4. The loader does the same with the identical blob
 * (tools/dreamlte/fetch-acpm-fw.sh takes it from the RECOVERY backup; it is
 * not in git), then sets the A53s. Mongoose is left to XNU: CMU_CPUCL0 is
 * in the Mongoose power domain, which is off until XNU starts its cores.
 */
#define ACPM_MBOX		0x16440000UL	/* AP<->APM mailbox */
#define ACPM_SRAM		0x16500000UL
#define ACPM_SRAM_SIZE		0xb400U
#define ACPM_INITDATA		0x2850U
#define ACPM_CH_PLUGIN		4	/* acpm */
#define ACPM_CH_DVFS		0	/* clock-controller@0x15a80000 (cal_if_init) */
#define MB_INTGR0		0x08
#define MB_INTCR1		0x20
#define MB_INTSR1		0x28
/* struct acpm_framework (u32 fields) */
#define FW_PLUGINS		0x00
#define FW_NUM_PLUGINS		0x04
#define FW_IPC_CHANNELS		0x08
#define FW_IPC_AP_MAX		0x18
/* struct plugin, 32-bit firmware layout (44 bytes) */
#define PLUGIN_SIZE		44
#define PL_ID			0
#define PL_BASE			4	/* SRAM offset, bit 0 = Thumb */
#define PL_IS_ATTACHED		28	/* u8 */
#define PL_LEN			32
#define PL_STAY_ATTACHED	36	/* u8 */
/* struct ipc_channel: id, field, owner, type, channel_info, ap_poll */
#define IPC_CH_SIZE		72
#define CH_ID			0
#define CH_TYPE			12	/* 1 queue, 2 buffer (one slot) */
#define CH_RX_REAR		16	/* APM's RX = our TX queue */
#define CH_RX_FRONT		20
#define CH_RX_BASE		24
#define CH_TX_REAR		40	/* APM's TX = our RX queue */
#define CH_TX_FRONT		44
#define CH_TX_BASE		48
#define CH_Q_LEN		52
#define CH_Q_ELEM		56
#define TYPE_BUFFER		2
#define DP_D			(1u << 24)	/* ACPM_IPC_PROTOCOL_DP_D: detach */
#define DP_A			(1u << 25)	/* attach */
#define PROTOCOL_ID		26
#define SEQ_SHIFT		16
#define DVFS_CPUCL1		3	/* A53 */
#define FREQ_REQ		0
#define FREQ_GET		1

#ifdef ACPM_DVFS_FW
__asm__(".section .rodata\n.balign 4\n"
	"acpm_dvfs_fw: .incbin \"" ACPM_DVFS_FW "\"\n"
	"acpm_dvfs_fw_end:\n.previous\n");
extern const uint8_t acpm_dvfs_fw[], acpm_dvfs_fw_end[];
#endif

static void (*acpm_rec)(uint32_t);
static unsigned acpm_seq;

static int sram_off_ok(uint32_t off, uint32_t len)
{
	return off < ACPM_SRAM_SIZE && len <= ACPM_SRAM_SIZE - off;
}

/* Channel descriptor of AP channel id, checked to stay inside the SRAM. */
static uintptr_t acpm_channel(uint32_t id)
{
	uintptr_t fw = ACPM_SRAM + ACPM_INITDATA;
	uint32_t chans = rd(fw + FW_IPC_CHANNELS), n = rd(fw + FW_IPC_AP_MAX);
	if (n == 0 || n > 32 || !sram_off_ok(chans, n * IPC_CH_SIZE))
		return 0;
	for (uint32_t i = 0; i < n; i++) {
		uintptr_t c = ACPM_SRAM + chans + i * IPC_CH_SIZE;
		if (rd(c + CH_ID) != id)
			continue;
		uint32_t len = rd(c + CH_Q_LEN), elem = rd(c + CH_Q_ELEM);
		if (len < 1 || len > 64 || elem < 16 || elem > 64 || (elem & 3) ||
		    !sram_off_ok(rd(c + CH_RX_BASE), len * elem) ||
		    !sram_off_ok(rd(c + CH_TX_BASE), len * elem) ||
		    !sram_off_ok(rd(c + CH_RX_FRONT), 4) || !sram_off_ok(rd(c + CH_RX_REAR), 4) ||
		    !sram_off_ok(rd(c + CH_TX_FRONT), 4) || !sram_off_ok(rd(c + CH_TX_REAR), 4))
			return 0;
		return c;
	}
	return 0;
}

/*
 * One command and its answer, polled (acpm_ipc_send_data + check_response;
 * for a one-slot buffer channel Samsung takes the answer from the APM slot
 * in its interrupt thread instead). cmd[1] carries the answer. Returns 0,
 * -1 on a full queue, -2 on timeout.
 */
static int acpm_send(uintptr_t c, uint32_t cmd[4])
{
	uintptr_t s = ACPM_SRAM;
	uint32_t id = rd(c + CH_ID), bit = 1u << id;
	uint32_t len = rd(c + CH_Q_LEN), elem = rd(c + CH_Q_ELEM);
	int buffer = rd(c + CH_TYPE) == TYPE_BUFFER;
	uint32_t front = buffer ? 0 : rd(s + rd(c + CH_RX_FRONT)), next = (front + 1) % len;
	if (!buffer && (front >= len || next == rd(s + rd(c + CH_RX_REAR))))
		return -1;
	if (++acpm_seq >= 64)
		acpm_seq = 1;
	uint32_t seq = acpm_seq;
	cmd[0] |= seq << SEQ_SHIFT;
	if (buffer)
		wr(ACPM_MBOX + MB_INTCR1, bit);
	uintptr_t slot = s + rd(c + CH_RX_BASE) + front * elem;
	for (uint32_t i = 0; i < elem / 4; i++)
		wr(slot + 4 * i, i < 4 ? cmd[i] : 0);
	__asm__ volatile("dsb sy");
	if (!buffer) {
		wr(s + rd(c + CH_RX_FRONT), next);
		__asm__ volatile("dsb sy");
	}
	wr(ACPM_MBOX + MB_INTGR0, bit << 16);

	uintptr_t base = s + rd(c + CH_TX_BASE);
	uint64_t end = ticks() + TIMER_HZ / 20;		/* 50 ms */
	while (ticks() < end) {
		if (!(rd(ACPM_MBOX + MB_INTSR1) & bit))
			continue;
		if (buffer) {
			if (((rd(base) >> SEQ_SHIFT) & 0x3f) != seq) {
				wr(ACPM_MBOX + MB_INTCR1, bit);
				continue;
			}
			for (int k = 0; k < 4; k++)
				cmd[k] = rd(base + 4 * k);
			wr(ACPM_MBOX + MB_INTCR1, bit);
			return 0;
		}
		uint32_t rear = rd(s + rd(c + CH_TX_REAR)), f = rd(s + rd(c + CH_TX_FRONT));
		if (rear >= len || f >= len)
			return -3;
		for (uint32_t i = rear; i != f; i = (i + 1) % len) {
			uintptr_t r = base + i * elem;
			if (((rd(r) >> SEQ_SHIFT) & 0x3f) != seq)
				continue;
			for (int k = 0; k < 4; k++)
				cmd[k] = rd(r + 4 * k);
			/* dequeue i: move the entry at rear into its place */
			if (i != rear)
				for (uint32_t k = 0; k < elem / 4; k++)
					wr(r + 4 * k, rd(base + rear * elem + 4 * k));
			rear = (rear + 1) % len;
			wr(s + rd(c + CH_TX_REAR), rear);
			if (rear == rd(s + rd(c + CH_TX_FRONT)))
				wr(ACPM_MBOX + MB_INTCR1, bit);
			return 0;
		}
	}
	return -2;
}

/* plugins_init: detach the plugin that is attached but not to stay, load
 * the DVFS blob into the one that is to stay but is not attached, attach. */
static int acpm_load_dvfs(void)
{
#ifdef ACPM_DVFS_FW
	uintptr_t fw = ACPM_SRAM + ACPM_INITDATA, c = acpm_channel(ACPM_CH_PLUGIN);
	uint32_t pl = rd(fw + FW_PLUGINS), n = rd(fw + FW_NUM_PLUGINS);
	uint32_t blob = (uint32_t)(acpm_dvfs_fw_end - acpm_dvfs_fw);
	if (!c || n == 0 || n > 16 || !sram_off_ok(pl, n * PLUGIN_SIZE))
		return -10;
	int loaded = 0;
	for (uint32_t i = 0; i < n; i++) {
		uintptr_t p = ACPM_SRAM + pl + i * PLUGIN_SIZE;
		uint32_t att = rd(p + PL_IS_ATTACHED) & 0xff, stay = rd(p + PL_STAY_ATTACHED) & 0xff;
		uint32_t id = rd(p + PL_ID), cmd[4] = { 0, 0, 0, 0 };
		if (att == 1 && stay == 0) {
			cmd[0] = DP_D | id << PROTOCOL_ID;
		} else if (att == 0 && stay == 1) {
			uint32_t off = rd(p + PL_BASE) & ~1u;
			if (loaded || !off || !sram_off_ok(off, blob) || blob > rd(p + PL_LEN))
				return -11;
			for (uint32_t k = 0; k < blob; k += 4)
				wr(ACPM_SRAM + off + k, *(const uint32_t *)(acpm_dvfs_fw + k));
			__asm__ volatile("dsb sy");
			loaded = 1;
			cmd[0] = DP_A | id << PROTOCOL_ID;
		} else {
			continue;
		}
		int rc = acpm_send(c, cmd);
		acpm_rec((uint32_t)rc);
		acpm_rec(rd(p + PL_IS_ATTACHED) & 0xff);
		kv("plugin", id);
		kv(cmd[0] & DP_A ? "attach rc" : "detach rc", (uint32_t)rc);
	}
	delay_us(5000);
	return loaded ? 0 : -12;
#else
	return -13;
#endif
}

static int acpm_freq(uintptr_t c, unsigned id, unsigned op, uint32_t khz, uint32_t *ans)
{
	uint32_t cmd[4] = { id, khz, op, 0 };
	int rc = acpm_send(c, cmd);
	*ans = cmd[1];
	return rc;
}

/* A53 PLL_CPUCL1: F = 26 MHz * M / (P * 2^S) */
static uint32_t cl1_pll_mhz(void)
{
	uint32_t v = rd(0x16900120UL);
	uint32_t m = (v >> 16) & 0x3ff, p = (v >> 8) & 0x3f, s = v & 7;
	return p ? (uint32_t)(26ULL * m / p >> s) : 0;
}

/* Levels of ECT dvfs_cpucl1 that Samsung's Linux uses (TWRP: 455-1690). */
static const uint32_t lit_levels[] = {
	1690000, 1456000, 1248000, 1053000, 949000, 832000, 715000, 598000, 455000,
};

void acpm_cpu_clocks(uint32_t lit_khz, void (*rec)(uint32_t))
{
	acpm_rec = rec;
	out("ACPM (APM firmware DVFS)\n");
	if (!lit_khz)
		return;
	int ok = 0;
	for (unsigned i = 0; i < sizeof(lit_levels) / sizeof(lit_levels[0]); i++)
		ok |= lit_levels[i] == lit_khz;
	uintptr_t c = acpm_channel(ACPM_CH_DVFS);
	int rc = ok && c ? acpm_load_dvfs() : -14;
	kv("load rc", (uint32_t)rc);
	out("\n");
	acpm_rec(0xacc);			/* marker: results follow */
	acpm_rec((uint32_t)rc);
	acpm_rec(rd(c + 8));			/* channel owner, type, poll */
	acpm_rec(rd(c + CH_TYPE));
	acpm_rec(rd(c + 68));
	if (rc)
		return;
	uint32_t f = 0;
	rc = acpm_freq(c, DVFS_CPUCL1, FREQ_GET, 0, &f);
	acpm_rec((uint32_t)rc);
	acpm_rec(f);
	rc = acpm_freq(c, DVFS_CPUCL1, FREQ_REQ, lit_khz, &f);
	acpm_rec((uint32_t)rc);
	delay_us(1000);
	rc = acpm_freq(c, DVFS_CPUCL1, FREQ_GET, 0, &f);
	acpm_rec((uint32_t)rc);
	acpm_rec(f);
	acpm_rec(cl1_pll_mhz());
	acpm_rec((uint32_t)speedy(SLAVE_PMIC, 0x1e, 0, 0));
	/* the firmware's newest log entries (8 text bytes, value) */
	uintptr_t fw = ACPM_SRAM + ACPM_INITDATA;
	uint32_t lf = rd(ACPM_SRAM + rd(fw + 0x38)), esz = rd(fw + 0x40), elen = rd(fw + 0x44);
	acpm_rec(rd(ACPM_MBOX + MB_INTSR1));
	acpm_rec(lf);
	if (esz == 16 && elen && lf < elen && sram_off_ok(rd(fw + 0x3c), elen * esz))
		for (uint32_t n = 0, e = (lf + elen - 7) % elen; n < 3; n++, e = (e + 1) % elen)
			for (uint32_t k = 4; k < 16; k += 4)
				acpm_rec(rd(ACPM_SRAM + rd(fw + 0x3c) + e * esz + k));
	kv("lit kHz", f);
	kv("pll MHz", cl1_pll_mhz());
	cpu_freq();
	out("\n");
}

/* SPDX-License-Identifier: GPL-2.0-only
 * Galaxy S8 (SM-G950F, Exynos 8895) XNU loader.
 *
 * S-Boot hands us the BOOT ramdisk as /chosen/linux,initrd-{start,end}; it
 * holds a tools/mkpayload.py "SWEETXNU" v1 container (Mach-O segments, ADT,
 * boot-args). We copy it into the kernel-managed RAM window the ADT names
 * (the 2 GiB bank at 0x880000000, free of firmware carve-outs), build
 * boot_args and jump to XNU's physical entry with the MMU off, as
 * shim/a5xelte/xnu_boot.c does on the Galaxy A5.
 *
 * Every step is drawn on the S-Boot framebuffer and appended to TWRP's
 * ramoops console zone, so after a forced reboot into TWRP the log is in
 * /sys/fs/pstore/console-ramoops-0 (tools/dreamlte-log-pull.ps1).
 */
#include <stdint.h>
#include "../fdt.h"
#include "../font.h"
#include "ufs_probe.h"
#include "smp_probe.h"
#include "touch_probe.h"
#include "pmic.h"
#include "display_probe.h"

#define UFS_PROBE_DMA		0x8f0000000UL	/* high bank; inside XNU's RAM at 2 GiB */
#define UFS_PROBE_DMA_SIZE	0x14000UL	/* ufs_probe.c D_SIZE */

/* ---- board facts (s8-probe v2-v7, live DT, /proc/iomem) ---- */
#define FB_BASE			0xcc000000UL	/* s3cfb.bootloaderfb */
#define FB_W			1440
#define FB_H			2960
#define FB_STRIDE		(FB_W * 4)
#define DECON_TRIG		0x12860070UL	/* DECON_F HW_SW_TRIG_CONTROL */
#define DECON_TRIG_UNMASK	0x1281U		/* uniLoader dreamlte */
#define RAMOOPS_CONSOLE		0x92080000UL	/* TWRP ramoops console zone */
#define RAMOOPS_CONSOLE_SIZE	0x80000UL
#define PRZ_SIG			0x43474244U	/* "DBGC" */
#define XNU_MARKER_PHYS		0x920ff000UL	/* A5_ENTRY_MARKER_PHYS in 0124 */
#define LOW_RAM_BASE		0x80000000UL	/* initrd must be in the low bank */
#define LOW_RAM_END		0xbc800000UL
#define XNU_RAM_BASE		0x880000000UL	/* 2 GiB high bank */
#define XNU_RAM_END		0x900000000UL
#define PAGE_SIZE		4096UL
#define BOOT_LINE_LENGTH	608

/* ---- persistent log ----
 * The same text goes to two ramoops zones with separate headers: the
 * console zone (/sys/fs/pstore/console-ramoops-0) and the pmsg zone
 * (pmsg-ramoops-0). A forced reboot flips a few RAM bits; when one flips a
 * zone header, TWRP drops that zone ("found existing invalid buffer", seen on
 * the first XNU boot), the other copy usually survives. */
struct prz {
	uint32_t sig, start, size;
	uint8_t data[];
};
#define RAMOOPS_PMSG		0x92180000UL	/* after dump, console, ftrace */
static volatile struct prz *const prz = (volatile struct prz *)RAMOOPS_CONSOLE;
static volatile struct prz *const prz2 = (volatile struct prz *)RAMOOPS_PMSG;
#define PRZ_DATA_MAX	(RAMOOPS_CONSOLE_SIZE - 12)
/* The galaxios8 test phone's TWRP 3.4.0 has a smaller ramoops (dmesg: 0x8000
 * at 0x92000000; record 16 KiB, pmsg 16 KiB, no console zone), so its pmsg
 * zone is at 0x92004000. The log goes there too; the upstream TWRP's zones
 * above are kept for the G950F. */
#define RAMOOPS_PMSG_SMALL	0x92004000UL
#define PRZ3_DATA_MAX		(0x4000UL - 12)
static volatile struct prz *const prz3 = (volatile struct prz *)RAMOOPS_PMSG_SMALL;
static uint32_t log_len, log2_len, log3_len;

static void prz_put_max(volatile struct prz *z, uint32_t *len, char c, uint32_t max)
{
	if (*len >= max)
		return;
	z->data[(*len)++] = (uint8_t)c;
	z->start = *len;
	z->size = *len;
}

static void prz_put(volatile struct prz *z, uint32_t *len, char c)
{
	if (*len >= PRZ_DATA_MAX)
		return;
	z->data[(*len)++] = (uint8_t)c;
	z->start = *len;
	z->size = *len;
}

/* console zone only: used for the XNU marker padding */
static void log_ch1(char c)
{
	prz_put(prz, &log_len, c);
}

static void log_ch(char c)
{
	prz_put(prz, &log_len, c);
	prz_put(prz2, &log2_len, c);
	prz_put_max(prz3, &log3_len, c, PRZ3_DATA_MAX);
}

/* ---- screen console ---- */
static volatile uint32_t *const fb = (volatile uint32_t *)FB_BASE;
#define SCALE	3
#define CELL_W	(8 * SCALE)
#define CELL_H	(16 * SCALE + 6)
#define COLS	((FB_W - 48) / CELL_W)
#define ROWS	((FB_H - 160) / CELL_H)
static int row, col;
static uint32_t fg = 0xffffffffU;

static void fill(int x0, int y0, int w, int h, uint32_t c)
{
	for (int y = y0; y < y0 + h && y < FB_H; y++)
		for (int x = x0; x < x0 + w && x < FB_W; x++)
			fb[y * (FB_STRIDE / 4) + x] = c;
}

static void scr_ch(char c)
{
	if (c == '\n' || col >= COLS) {
		col = 0;
		row = (row + 1) % ROWS;
		fill(0, 120 + row * CELL_H, FB_W, CELL_H, 0xff000000U);
		if (c == '\n')
			return;
	}
	if (c < 0x20 || c > 0x7e)
		c = '?';
	const unsigned char *g = font8x16[c - 0x20];
	int x0 = 24 + col * CELL_W, y0 = 120 + row * CELL_H;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++)
			fill(x0 + gx * SCALE, y0 + gy * SCALE, SCALE, SCALE,
			     (g[gy] & (0x80 >> gx)) ? fg : 0xff000000U);
	col++;
}

static void out(const char *s)
{
	while (*s) {
		log_ch(*s);
		scr_ch(*s++);
	}
}

static void hex(uint64_t v)
{
	static const char digits[] = "0123456789abcdef";
	char b[19] = "0x";
	int n = 2, started = 0;
	for (int i = 60; i >= 0; i -= 4) {
		int d = (v >> i) & 0xf;
		if (d || started || i == 0) {
			b[n++] = digits[d];
			started = 1;
		}
	}
	b[n] = 0;
	out(b);
}

static void kv(const char *k, uint64_t v)
{
	out(k);
	out("=");
	hex(v);
	out(" ");
}

/* ---- payload (tools/mkpayload.py v1) ---- */
struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};
struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};
struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};
struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};
_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args size");

uint64_t dl_boot_args;	/* read by start.S */

/* MMU off: everything is Device memory, keep accesses naturally aligned. */
static void copy(uintptr_t dst, uintptr_t src, uint64_t n)
{
	if (!((dst | src) & 7)) {
		for (; n >= 8; n -= 8, dst += 8, src += 8)
			*(volatile uint64_t *)dst = *(volatile uint64_t *)src;
	}
	for (; n; n--, dst++, src++)
		*(volatile uint8_t *)dst = *(volatile uint8_t *)src;
}

static void zero(uintptr_t dst, uint64_t n)
{
	for (; n && (dst & 7); n--, dst++)
		*(volatile uint8_t *)dst = 0;
	for (; n >= 8; n -= 8, dst += 8)
		*(volatile uint64_t *)dst = 0;
	for (; n; n--, dst++)
		*(volatile uint8_t *)dst = 0;
}

static void clean(uintptr_t start, uintptr_t end)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
	uintptr_t line = 4UL << ((ctr >> 16) & 0xf);
	for (uintptr_t p = start & ~(line - 1); p < end; p += line)
		__asm__ volatile("dc civac, %0" : : "r"(p) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
}

static int magic_ok(const volatile char *m)
{
	const char *want = "SWEETXNU";
	for (int i = 0; i < 8; i++)
		if (m[i] != want[i])
			return 0;
	return 1;
}

static uint64_t fail(const char *why)
{
	fg = 0xffff4040U;
	out("FAIL: ");
	out(why);
	out("\nHold POWER+VOL DOWN, then POWER+BIXBY+VOL UP -> TWRP\n");
	return 0;
}

/* Leave an 8-byte hole at XNU_MARKER_PHYS inside the pstore text. XNU's
 * start_first_cpu stores "XNUELTE1" there (0124 A5_ENTRY_MARKER_PHYS). */
static void reserve_marker(void)
{
	uint32_t at = (uint32_t)(XNU_MARKER_PHYS - (RAMOOPS_CONSOLE + 12));
	const char *tag = "\nXNU entry marker: [";
	uint32_t tag_len = 0;
	while (tag[tag_len])
		tag_len++;
	while (log_len < at - tag_len)
		log_ch1(log_len % 128 == 127 ? '\n' : ' ');
	for (uint32_t i = 0; i < tag_len; i++)
		log_ch1(tag[i]);
	for (int i = 0; i < 8; i++)
		log_ch1('-');
	log_ch1(']');
	log_ch1('\n');
}

/* Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant). */
static int64_t days_from_civil(int64_t y, unsigned m, unsigned d)
{
	y -= m <= 2;
	int64_t era = (y >= 0 ? y : y - 399) / 400;
	unsigned yoe = (unsigned)(y - era * 400);
	unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
	unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
	return era * 146097 + (int64_t)doe - 719468;
}

/* XNU's platform expert has no clock on the S8 (iOS showed 1969). Pass the
 * PMIC RTC as "s8rtc=" = UTC seconds at system-counter zero; the kernel
 * adds the counter (patch 0124, PEGetUTCTimeOfDay). RTC bytes from 0x04:
 * msec, sec, min, hour, weekday mask, day, month, year-2000 (boot 26). */
static void rtc_bootarg(volatile struct boot_args *ba, uint64_t raw)
{
	unsigned sec = (raw >> 8) & 0x7f, min = (raw >> 16) & 0x7f;
	unsigned hour = (raw >> 24) & 0x1f, day = (raw >> 40) & 0x1f;
	unsigned mon = (raw >> 48) & 0x0f, year = 2000 + ((raw >> 56) & 0x7f);
	if (sec > 59 || min > 59 || hour > 23 || !day || !mon || mon > 12 || year < 2024)
		return;
	int64_t t = days_from_civil(year, mon, day) * 86400 + hour * 3600 + min * 60 + sec;
	uint64_t cnt;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(cnt));
	t -= (int64_t)(cnt / 26000000);
	kv("rtc unix", (uint64_t)t);
	out("\n");
	char num[24];
	int n = 0;
	do {
		num[n++] = (char)('0' + t % 10);
		t /= 10;
	} while (t && n < 20);
	int at = 0;
	while (at < BOOT_LINE_LENGTH && ba->CommandLine[at])
		at++;
	const char *key = " s8rtc=";
	if (at + 7 + n >= BOOT_LINE_LENGTH)
		return;
	for (int i = 0; key[i]; i++)
		ba->CommandLine[at++] = key[i];
	while (n)
		ba->CommandLine[at++] = num[--n];
	ba->CommandLine[at] = 0;
}

/* Words for " s8acpm=" (hex, dot-separated), appended to the boot-args. */
static char acpm_line[200];
static int acpm_len;

static void acpm_word(uint32_t v)
{
	char num[9];
	int n = 0;
	do {
		num[n++] = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	} while (v && n < 8);
	if (acpm_len + n + 1 >= (int)sizeof(acpm_line))
		return;
	if (acpm_len)
		acpm_line[acpm_len++] = '.';
	while (n)
		acpm_line[acpm_len++] = num[--n];
}

static void append_bootarg(volatile struct boot_args *ba, const char *key, const char *val, int len)
{
	int at = 0, k = 0;
	while (at < BOOT_LINE_LENGTH && ba->CommandLine[at])
		at++;
	while (key[k])
		k++;
	if (!len || at + k + len >= BOOT_LINE_LENGTH)
		return;
	for (int i = 0; i < k; i++)
		ba->CommandLine[at++] = key[i];
	for (int i = 0; i < len; i++)
		ba->CommandLine[at++] = val[i];
	ba->CommandLine[at] = 0;
}

/* Decimal value of " key=" in the boot-args, or 0. */
static uint32_t cmdline_u32(const volatile char *line, const char *key)
{
	for (int i = 0; i < BOOT_LINE_LENGTH && line[i]; i++) {
		if (i && line[i - 1] != ' ')
			continue;
		int k = 0;
		while (key[k] && i + k < BOOT_LINE_LENGTH && line[i + k] == key[k])
			k++;
		if (key[k] || i + k >= BOOT_LINE_LENGTH || line[i + k] != '=')
			continue;
		uint32_t v = 0;
		for (int j = i + k + 1; j < BOOT_LINE_LENGTH && line[j] >= '0' && line[j] <= '9'; j++)
			v = v * 10 + (uint32_t)(line[j] - '0');
		return v;
	}
	return 0;
}

#if MNGS_DIAG
/*
 * Experiment build (LOADER_CFLAGS=-DMNGS_DIAG=1): run the Mongoose
 * diagnostics and also append every value they print to the boot-args as
 * " mngs=v.v.v...". launchd logs the boot-args, and its log lands in the
 * kernel log ring on USERDATA, which survives the forced reboot back to TWRP
 * (the pmsg copy of the loader log does not). The first value is INFORM3 at
 * loader entry: Samsung's sec_reboot.c writes the reset reason there, which
 * tells whether a reset straight into recovery could be used later.
 */
static char mngs_rec[300];
static int mngs_len;

static void kv_rec(const char *k, uint64_t v)
{
	kv(k, v);
	char num[17];
	int n = 0;
	do {
		num[n++] = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	} while (v && n < 16);
	if (mngs_len + n + 1 >= (int)sizeof(mngs_rec))
		return;
	if (mngs_len)
		mngs_rec[mngs_len++] = '.';
	while (n)
		mngs_rec[mngs_len++] = num[--n];
}

/*
 * After the diagnostics the loader resets straight into recovery, the way
 * Samsung's sec_reboot.c does (INFORM2 = POWER_RESET, INFORM3 =
 * RESET_REASON_RECOVERY, PMU SWRESET); the results are then read from TWRP
 * without anyone at the phone. TWRP's kernel uses sec_reboot (kallsyms), and
 * S-Boot consumes INFORM3 (the loader always reads 0). Loop guard: if the
 * pmsg zone still ends with our reset line, the last reset did not reach
 * TWRP (whose ramoops would have taken over the zone), so boot XNU instead.
 */
#define PMU_INFORM2		0x16480808UL
#define PMU_INFORM3		0x1648080cUL
#define PMU_SWRESET		0x16480400UL
static const char reset_line[] = "MNGS: reset to recovery\n";
static int last_reset_failed;

static int ends_with_reset(volatile struct prz *z, uint32_t max)
{
	uint32_t n = z->size, k = sizeof(reset_line) - 1;
	if (z->sig != PRZ_SIG || n < k || n > max)
		return 0;
	for (uint32_t i = 0; i < k; i++)
		if (z->data[n - k + i] != (uint8_t)reset_line[i])
			return 0;
	return 1;
}

static void check_last_reset(void)
{
	last_reset_failed = ends_with_reset(prz3, PRZ3_DATA_MAX);
}

/* The reset line must end the small zone even when the log filled it. */
static void put_reset_line(void)
{
	uint32_t k = sizeof(reset_line) - 1;
	if (log3_len + k > PRZ3_DATA_MAX)
		log3_len = PRZ3_DATA_MAX - k;
	out(reset_line);
}

static void mngs_cycle(volatile struct boot_args *ba)
{
	kv_rec("INFORM3", *(volatile uint32_t *)PMU_INFORM3);
	kv_rec("last reset failed", (uint64_t)last_reset_failed);
	out("\n");
	mngs_diag(kv_rec, out);
	int at = 0;
	while (at < BOOT_LINE_LENGTH && ba->CommandLine[at])
		at++;
	const char *key = " mngs=";
	if (at + 6 + mngs_len >= BOOT_LINE_LENGTH) {
		out("MNGS: boot-args full, result not passed\n");
	} else {
		for (int i = 0; key[i]; i++)
			ba->CommandLine[at++] = key[i];
		for (int i = 0; i < mngs_len; i++)
			ba->CommandLine[at++] = mngs_rec[i];
		ba->CommandLine[at] = 0;
	}
	if (last_reset_failed) {
		out("MNGS: last reset did not reach recovery, booting XNU\n");
		return;
	}
	put_reset_line();
	clean(RAMOOPS_PMSG_SMALL, RAMOOPS_PMSG_SMALL + 0x4000);
	clean(RAMOOPS_CONSOLE, RAMOOPS_CONSOLE + RAMOOPS_CONSOLE_SIZE);
	clean(RAMOOPS_PMSG, RAMOOPS_PMSG + RAMOOPS_CONSOLE_SIZE);
	__asm__ volatile("dsb sy");
	*(volatile uint32_t *)PMU_INFORM2 = 0x12345678U;	/* SEC_POWER_RESET */
	*(volatile uint32_t *)PMU_INFORM3 = 0x12345674U;	/* REASON_RECOVERY */
	__asm__ volatile("dsb sy");
	*(volatile uint32_t *)PMU_SWRESET = 1;
	for (;;)
		__asm__ volatile("wfe");
}
#endif

uint64_t dl_main(uintptr_t dtb, uint64_t el, uint64_t sctlr)
{
	*(volatile uint32_t *)DECON_TRIG = DECON_TRIG_UNMASK;
#if MNGS_DIAG
	check_last_reset();
#endif
	prz->sig = PRZ_SIG;
	prz->start = prz->size = 0;
	prz2->sig = PRZ_SIG;
	prz2->start = prz2->size = 0;
	prz3->sig = PRZ_SIG;
	prz3->start = prz3->size = 0;
	fill(0, 0, FB_W, FB_H, 0xff000000U);
	fg = 0xffffff00U;
	out("S8LOADER BEGIN  (ios-s8 dreamlte XNU loader)\n");
	fg = 0xffffffffU;
	kv("EL", el);
	kv("SCTLR", sctlr);
	kv("DTB", dtb);
	out("\n");
#if MNGS_DIAG
	psci_early(kv_rec, out);
#endif
	if (el != 1)
		return fail("not entered at EL1");

	uint64_t rd_start, rd_end;
	if (!fdt_chosen_u64(dtb, "linux,initrd-start", &rd_start) ||
	    !fdt_chosen_u64(dtb, "linux,initrd-end", &rd_end))
		return fail("no initrd in /chosen");
	kv("initrd", rd_start);
	kv("end", rd_end);
	out("\n");
	if (rd_start < LOW_RAM_BASE || rd_end > LOW_RAM_END || rd_end <= rd_start)
		return fail("initrd outside low RAM");

	const volatile struct payload *p = (const volatile struct payload *)rd_start;
	uint64_t length = rd_end - rd_start;
	if (length < sizeof(struct payload) || !magic_ok(p->magic) || p->version != 1)
		return fail("initrd is not a SWEETXNU v1 payload");
	uint64_t nsegs = p->nsegs;
	kv("segs", nsegs);
	kv("virt", p->virt_base);
	kv("entry", p->entry_va);
	out("\n");
	kv("phys", p->phys_base);
	kv("mem", p->mem_size);
	kv("adt", p->adt_size);
	out("\n");
	if (!nsegs || nsegs > 32 ||
	    __builtin_offsetof(struct payload, segs) + nsegs * sizeof(struct payload_seg) > length ||
	    p->adt_off > length || p->adt_size > length - p->adt_off)
		return fail("bad payload header");
	if (p->phys_base < XNU_RAM_BASE || p->phys_base >= XNU_RAM_END || !p->mem_size ||
	    p->mem_size > XNU_RAM_END - p->phys_base ||
	    p->entry_va < p->virt_base || p->kernel_end < p->virt_base)
		return fail("payload RAM outside the 0x880000000 bank");
	uintptr_t mem_end = p->phys_base + p->mem_size;
	uintptr_t kernel_end = p->phys_base + (p->kernel_end - p->virt_base);
	if (kernel_end >= mem_end)
		return fail("kernel larger than RAM window");

	/* iBoot hands XNU zeroed RAM; S-Boot leaves the previous OS's data
	 * (TWRP's Linux after `adb reboot`, partly decayed after a forced
	 * reboot). XNU 6 hung right after its version line, in
	 * vm_mem_bootstrap, depending on how the phone was rebooted. */
	out("zeroing XNU RAM...\n");
	zero(p->phys_base, p->mem_size);
	out("zeroed\n");

	for (uint64_t i = 0; i < nsegs; i++) {
		const volatile struct payload_seg *s = &p->segs[i];
		if (s->vmaddr < p->virt_base || s->file_size > s->vmsize ||
		    s->file_off > length || s->file_size > length - s->file_off ||
		    s->vmsize > p->mem_size || s->vmaddr - p->virt_base > p->mem_size - s->vmsize)
			return fail("bad segment");
		uintptr_t dst = p->phys_base + (s->vmaddr - p->virt_base);
		copy(dst, rd_start + s->file_off, s->file_size);
		zero(dst + s->file_size, s->vmsize - s->file_size);
		clean(dst, dst + s->vmsize);
		out("seg ");
		hex(i);
		out(" -> ");
		hex(dst);
		out(" ");
		hex(s->vmsize);
		out("\n");
	}

	uintptr_t adt_pa = kernel_end;
	uintptr_t ba_pa = (adt_pa + p->adt_size + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1);
	if (ba_pa + PAGE_SIZE > mem_end)
		return fail("no room for ADT/boot_args");
	copy(adt_pa, rd_start + p->adt_off, p->adt_size);
	zero(ba_pa, PAGE_SIZE);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = ba_pa + PAGE_SIZE;
	ba->deviceTreeP = p->virt_base + (adt_pa - p->phys_base);
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < BOOT_LINE_LENGTH; i++)
		ba->CommandLine[i] = p->cmdline[i];
	ba->memSizeActual = p->mem_size;
	clean(adt_pa, ba_pa + PAGE_SIZE);

	uintptr_t entry_pa = p->phys_base + (p->entry_va - p->virt_base);
	if (entry_pa >= kernel_end)
		return fail("entry outside kernel");
	dl_boot_args = ba_pa;
	kv("adt_pa", adt_pa);
	kv("boot_args", ba_pa);
	out("\n");
	kv("entry_pa", entry_pa);
	out("\ncmdline: ");
	for (int i = 0; i < BOOT_LINE_LENGTH && p->cmdline[i]; i++) {
		char c[2] = { p->cmdline[i], 0 };
		out(c);
	}
	out("\n");
	ufs_probe(kv, out, UFS_PROBE_DMA);
	/* With 2 GiB for XNU (S8_DRAM_MIB) the probe's DMA area lies inside
	 * XNU's RAM, which was zeroed above; zero it again. */
	if (UFS_PROBE_DMA >= p->phys_base && UFS_PROBE_DMA + UFS_PROBE_DMA_SIZE <= mem_end) {
		zero(UFS_PROBE_DMA, UFS_PROBE_DMA_SIZE);
		clean(UFS_PROBE_DMA, UFS_PROBE_DMA + UFS_PROBE_DMA_SIZE);
	}
	rtc_bootarg(ba, pmic_init(kv, out));
	/* s8lit=<kHz>: A53 clock (S-Boot leaves 1053 MHz; levels in pmic.c). */
	acpm_cpu_clocks(cmdline_u32(p->cmdline, "s8lit"), acpm_word);
	append_bootarg(ba, " s8acpm=", acpm_line, acpm_len);
	clean(ba_pa, ba_pa + PAGE_SIZE);
	touch_probe(kv, out, (const char *)p->cmdline);
	battery_probe(kv, out);
	display_probe(kv, out);
#if MNGS_DIAG
	mngs_cycle(ba);
	clean(ba_pa, ba_pa + PAGE_SIZE);
#else
	/* mngs_probe powered Mongoose core 0x000 by hand (upstream boot 31);
	 * since boot m8 XNU starts the cores with plain PSCI CPU_ON once the GIC
	 * distributor is on, and a core left powered here would only get in the
	 * way. */
	(void)mngs_probe;
#endif
	/* smp_probe(kv, out) proved the PMU power-up (boot 19); it leaves the
	 * probed cores' PMU power on, which hid the 0 -> 0xF edge XNU needs. */
	(void)smp_probe;
	fg = 0xff40ff40U;
	out("\nJUMP TO XNU\n");
	reserve_marker();
	clean(RAMOOPS_PMSG_SMALL, RAMOOPS_PMSG_SMALL + 0x4000);
	clean(RAMOOPS_CONSOLE, RAMOOPS_CONSOLE + RAMOOPS_CONSOLE_SIZE);
	clean(RAMOOPS_PMSG, RAMOOPS_PMSG + RAMOOPS_CONSOLE_SIZE);
	return entry_pa;
}

void dl_exception(uint64_t slot)
{
	uint64_t esr, elr, far;
	__asm__ volatile("mrs %0, esr_el1" : "=r"(esr));
	__asm__ volatile("mrs %0, elr_el1" : "=r"(elr));
	__asm__ volatile("mrs %0, far_el1" : "=r"(far));
	fg = 0xffff4040U;
	out("\nLOADER EXCEPTION ");
	kv("slot", slot);
	kv("ESR", esr);
	kv("ELR", elr);
	kv("FAR", far);
	out("\n");
	for (;;)
		__asm__ volatile("wfe");
}

/* gcc may emit calls for struct copies; keep the image self-contained. */
void *memset(void *d, int c, unsigned long n)
{
	unsigned char *q = d;
	while (n--)
		*q++ = (unsigned char)c;
	return d;
}

void *memcpy(void *d, const void *s, unsigned long n)
{
	unsigned char *q = d;
	const unsigned char *r = s;
	while (n--)
		*q++ = *r++;
	return d;
}

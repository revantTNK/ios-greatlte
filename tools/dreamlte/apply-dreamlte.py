#!/usr/bin/env python3
"""Apply the Galaxy S8 (dreamlte, Exynos 8895) hardware layer to an
A5XELTE-patched xnu tree (tools-s8/prep-xnu-tree.sh output).

The A5XELTE machine config and its guards are reused unchanged. What
differs on the S8 is expressed as A5_* macros in A5XELTE.h, with the A5
values kept for a non-DREAMLTE build. Every replacement asserts its
expected match count. Usage: apply-dreamlte.py XNU_TREE
"""
import sys
from pathlib import Path

tree = Path(sys.argv[1])


def edit(rel, pairs):
    path = tree / rel
    text = path.read_text()
    for old, new, count in pairs:
        found = text.count(old)
        if found != count:
            raise SystemExit(f'{rel}: expected {count}x {old!r}, found {found}')
        text = text.replace(old, new)
    path.write_text(text)
    print(f'edited {rel}')


edit('pexpert/pexpert/arm64/A5XELTE.h', [(
    '#define A5XELTE_VTIMER_INTID         27\n',
    '#define A5XELTE_VTIMER_INTID         27\n'
    '\n'
    '/*\n'
    ' * Samsung Galaxy S8 (SM-G950F, dreamlte, Exynos 8895) build of this port.\n'
    ' * Same Samsung S-Boot handoff, GIC-400, 26 MHz timer and Cortex-A53 boot\n'
    ' * cluster as the A5; the board facts that differ are below.\n'
    ' */\n'
    '#define DREAMLTE                      1\n'
    '#if defined(DREAMLTE)\n'
    '#define A5_FB_PHYS                    0xcc000000  /* s3cfb.bootloaderfb */\n'
    '#define A5_FB_WIDTH                   1440\n'
    '#define A5_FB_HEIGHT                  2960\n'
    '#define A5_FB_STRIDE                  5760        /* bytes per row */\n'
    '#define A5_FB_2M_BLOCKS               9           /* 1440*2960*4 bytes */\n'
    '#define A5_ENTRY_MARKER_PHYS          0x920ff000  /* slot in the loader\'s pstore text */\n'
    '#define A5_BOOT_MPIDR                 0x100       /* first Cortex-A53 */\n'
    '#define A5_KEYS_DEFAULT               1           /* S8 keys: GPA0/GPA2 */\n'
    '#define A5_TOUCH_DEFAULT              0           /* A5 ZT7538 path absent */\n'
    '#define A5_KLOG_PHYS                  0x92180000  /* TWRP ramoops pmsg zone */\n'
    '#define A5_KLOG_SIZE                  0x80000\n'
    '#define A5_KLOG2_PHYS                 0x92004000  /* TWRP 3.4.0 (G950N) pmsg zone */\n'
    '#define A5_KLOG2_SIZE                 0x4000\n'
    '/* Samsung\'s S8 kernel DT: arch timer "use-physical-timer". The EL1\n'
    ' * virtual timer is not usable on the secondary cores (boot 22/24: 4\n'
    ' * CPUs up, then sleeping threads and workqueue threads never ran).\n'
    ' * Use the non-secure physical timer, PPI 14 = INTID 30. */\n'
    '#define A5_USE_PHYS_TIMER             1\n'
    '#undef A5XELTE_VTIMER_INTID\n'
    '#define A5XELTE_VTIMER_INTID         30\n'
    '#else\n'
    '#define A5_FB_PHYS                    0x67000000\n'
    '#define A5_FB_WIDTH                   1080\n'
    '#define A5_FB_HEIGHT                  1920\n'
    '#define A5_FB_STRIDE                  4320\n'
    '#define A5_FB_2M_BLOCKS               5\n'
    '#define A5_ENTRY_MARKER_PHYS          0x469ff100\n'
    '#define A5_BOOT_MPIDR                 0\n'
    '#define A5_KEYS_DEFAULT               1\n'
    '#define A5_TOUCH_DEFAULT              1\n'
    '#endif\n', 1)])

# Early assembly: entry/MMU/stage blocks are 36x21 px at x=240, rows 88..216.
stage_rows = {'0x6705d0c0': 88, '0x6707ecc0': 120, '0x670a08c0': 152,
              '0x670c24c0': 184, '0x670e40c0': 216}
pairs = [('MOV64\tx10, 0x469ff100', 'MOV64\tx10, A5_ENTRY_MARKER_PHYS', 1)]
for addr, row in stage_rows.items():
    pairs.append((f'MOV64\tx10, {addr}',
                  f'MOV64\tx10, (A5_FB_PHYS + {row} * A5_FB_STRIDE + 240 * 4)', 1))
pairs += [
    ('mov\t\tx15, #4320', 'mov\t\tx15, #A5_FB_STRIDE', 2),
    ('mov\tx15, #4320', 'mov\tx15, #A5_FB_STRIDE', 3),
    ('MOV64\tx0, 0x67000000\n\tmov\t\tx4, x0\n\tmov\t\tx5, #5\n',
     'MOV64\tx0, A5_FB_PHYS\n\tmov\t\tx4, x0\n\tmov\t\tx5, #A5_FB_2M_BLOCKS\n', 1),
    ('MOV64\tx10, 0x67000000', 'MOV64\tx10, A5_FB_PHYS', 1),
    ('mov\t\tx13, #5\nLa5_fb_attr:', 'mov\t\tx13, #A5_FB_2M_BLOCKS\nLa5_fb_attr:', 1),
    ('MOV64\tx4, 0x67000000\n\tmov\tx5, #4320',
     'MOV64\tx4, A5_FB_PHYS\n\tmov\tx5, #A5_FB_STRIDE', 1),
    ('mov\tx13, #8640', 'mov\tx13, #(2 * A5_FB_STRIDE)', 1),
    ('/* Five 2 MiB blocks map the 1080x1920 scanout buffer VA=PA.',
     '/* A5_FB_2M_BLOCKS 2 MiB blocks map the scanout buffer VA=PA.', 1),
]
edit('osfmk/arm64/start.s', pairs)

edit('osfmk/arm64/sweet_early.c', [
    ('#define A5_FB ((volatile uint32_t *)(uintptr_t)0x67000000)\n#define A5_STRIDE 1080u\n',
     '#define A5_FB ((volatile uint32_t *)(uintptr_t)A5_FB_PHYS)\n#define A5_STRIDE (A5_FB_STRIDE / 4u)\n', 1),
    ('#define A5_COLS (1080u / A5_COL_WIDTH)', '#define A5_COLS (A5_FB_WIDTH / A5_COL_WIDTH)', 1),
    ('(1920u / A5_ROW_HEIGHT)', '(A5_FB_HEIGHT / A5_ROW_HEIGHT)', 1),
    ('for (unsigned int x = 0; x < A5_STRIDE; x++) {', 'for (unsigned int x = 0; x < A5_FB_WIDTH; x++) {', 1),
])

edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('#include <pexpert/pexpert.h>\n',
     '#include <pexpert/pexpert.h>\n#include <pexpert/arm64/board_config.h>\n', 1),
    ('\tfPhys = 0x67000000ULL;\n\tfWidth = 1080;\n\tfHeight = 1920;\n\tfRowBytes = 4320;\n',
     '\tfPhys = A5_FB_PHYS;\n\tfWidth = A5_FB_WIDTH;\n\tfHeight = A5_FB_HEIGHT;\n\tfRowBytes = A5_FB_STRIDE;\n', 1),
])

edit('iokit/Kernel/arm/SweetCPU.cpp', [
    ('\tuint32_t expected_mpidr = cpu->cpu_id < 4 ? cpu->cpu_id :\n\t    0x100U + cpu->cpu_id - 4;\n',
     '#if defined(DREAMLTE)\n'
     '\t/* Exynos 8895: logical 0..3 = A53 MPIDR 0x100..0x103 (boot cluster);\n'
     '\t * logical 4..7 = Mongoose M2 MPIDR 0..3. */\n'
     '\tuint32_t expected_mpidr = cpu->cpu_id < 4 ? 0x100U + cpu->cpu_id :\n'
     '\t    cpu->cpu_id - 4;\n'
     '#else\n'
     '\tuint32_t expected_mpidr = cpu->cpu_id < 4 ? cpu->cpu_id :\n'
     '\t    0x100U + cpu->cpu_id - 4;\n'
     '#endif\n', 1),
    ('\t/* The A5 ADT describes CPU0 as the boot CPU. */\n'
     '\tif (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != 0) {\n'
     '\t\tpanic(CPU_PORT_NAME " CPU: expected boot MPIDR 0 and logical CPU 0");\n',
     '\t/* The ADT describes logical CPU 0 as the boot CPU. */\n'
     '\tif (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != A5_BOOT_MPIDR) {\n'
     '\t\tpanic(CPU_PORT_NAME " CPU: expected boot MPIDR %#x and logical CPU 0", A5_BOOT_MPIDR);\n', 1),
])

edit('pexpert/arm/pe_serial.c', [
    ('static uint32_t fbcon_cols, fbcon_rows, fbcon_col, fbcon_row;\n',
     'static uint32_t fbcon_cols, fbcon_rows, fbcon_col, fbcon_row;\n'
     '\n'
     '#if defined(DREAMLTE)\n'
     '/*\n'
     ' * Copy of the console in TWRP\'s ramoops pmsg zone, in persistent_ram\n'
     ' * format (sig "DBGC", start, size, ring data), appended to the loader\'s\n'
     ' * text there; TWRP shows it as /sys/fs/pstore/pmsg-ramoops-0 after a warm\n'
     ' * reset. Two layouts: the upstream author\'s TWRP (2 MiB ramoops, pmsg at\n'
     ' * 0x92180000) and TWRP 3.4.0 on the galaxios8 G950N (32 KiB ramoops,\n'
     ' * 16 KiB pmsg at 0x92004000); both get the text. The small zone wraps,\n'
     ' * so it keeps the last ~16 KiB, which is where a panic ends up.\n'
     ' */\n'
     'struct klog_zone {\n'
     '\tuint64_t phys, len;\n'
     '\tvolatile uint32_t *hdr;\n'
     '\tvolatile uint8_t *data;\n'
     '\tuint32_t cap, start, size;\n'
     '};\n'
     'static struct klog_zone klog_zones[] = {\n'
     '\t{ .phys = A5_KLOG_PHYS, .len = A5_KLOG_SIZE },\n'
     '\t{ .phys = A5_KLOG2_PHYS, .len = A5_KLOG2_SIZE },\n'
     '};\n'
     'static void klog_putc(uint8_t c);\n'
     '\n'
     'static void\n'
     'klog_init(void)\n'
     '{\n'
     '\tfor (unsigned i = 0; i < sizeof(klog_zones) / sizeof(klog_zones[0]); i++) {\n'
     '\t\tstruct klog_zone *z = &klog_zones[i];\n'
     '\t\tz->hdr = (volatile uint32_t *)ml_io_map(z->phys, z->len);\n'
     '\t\tif (z->hdr == NULL) {\n'
     '\t\t\tcontinue;\n'
     '\t\t}\n'
     '\t\tz->cap = (uint32_t)z->len - 12;\n'
     '\t\t/* Continue after the loader\'s text if its header is sane. */\n'
     '\t\tif (z->hdr[0] == 0x43474244u && z->hdr[1] == z->hdr[2] && z->hdr[2] < z->cap) {\n'
     '\t\t\tz->start = z->size = z->hdr[2];\n'
     '\t\t} else {\n'
     '\t\t\tz->hdr[0] = 0x43474244u;\n'
     '\t\t\tz->start = z->size = 0;\n'
     '\t\t}\n'
     '\t\tz->data = (volatile uint8_t *)(z->hdr + 3);\n'
     '\t}\n'
     '\tconst char *banner = "\\n--- XNU console ---\\n";\n'
     '\tfor (; *banner; banner++) {\n'
     '\t\tklog_putc((uint8_t)*banner);\n'
     '\t}\n'
     '\ts8_restart_init();\n'
     '}\n'
     '\n'
     'static void\n'
     'klog_putc(uint8_t c)\n'
     '{\n'
     '\tfor (unsigned i = 0; i < sizeof(klog_zones) / sizeof(klog_zones[0]); i++) {\n'
     '\t\tstruct klog_zone *z = &klog_zones[i];\n'
     '\t\tif (z->data == NULL) {\n'
     '\t\t\tcontinue;\n'
     '\t\t}\n'
     '\t\tz->data[z->start] = c;\n'
     '\t\tz->start = (z->start + 1) % z->cap;\n'
     '\t\tif (z->size < z->cap) {\n'
     '\t\t\tz->size++;\n'
     '\t\t}\n'
     '\t\tz->hdr[1] = z->start;\n'
     '\t\tz->hdr[2] = z->size;\n'
     '\t}\n'
     '}\n'
     '#endif\n', 1),
    ('fbcon_transmit_data(uint8_t c)\n{\n',
     'fbcon_transmit_data(uint8_t c)\n{\n'
     '#if defined(DREAMLTE)\n'
     '\tklog_putc(c);\n'
     '#endif\n', 1),
    ('\tfbcon_base = (volatile uint32_t *)ml_io_map_wcomb(reg[0], reg[1]);\n',
     '\tfbcon_base = (volatile uint32_t *)ml_io_map_wcomb(reg[0], reg[1]);\n'
     '#if defined(DREAMLTE)\n'
     '\tklog_init();\n'
     '#endif\n', 1),
])

# Restart, panic and power-off. Nothing set PE_halt_restart, so a panic or an
# iOS restart left the CPU spinning. Samsung's sec_reboot.c / exynos-reboot.c:
# INFORM2 = 0x12345678 (POWER_RESET), INFORM3 = reset reason, PMU SWRESET;
# power off = PS_HOLD (PMU 0x330c bit 8) low. A panic resets into TWRP when
# the test boot-arg s8autoreset is set (the pmsg zone then holds the panic),
# otherwise it restarts into iOS.
edit('pexpert/arm/pe_serial.c', [
    ('#if defined(DREAMLTE)\n/*\n * Copy of the console in TWRP',
     '#if defined(DREAMLTE)\n'
     'extern int (*PE_halt_restart)(unsigned int type);\n'
     'static volatile uint32_t *s8_pmu;\n'
     'static uint32_t s8_panic_to_recovery;\n'
     'uint32_t s8_restart_to_recovery;          /* set by s8autoreset */\n'
     '\n'
     'static int\n'
     's8_halt_restart(unsigned int type)\n'
     '{\n'
     '\t/* IOPlatformExpert.h: 0 halt, 1 restart, 4 panic restart,\n'
     '\t * 9 panic restart without callouts, 10 panic diagnostics done (sent\n'
     '\t * after the panic text, before debug.c waits for a KDP debugger over\n'
     '\t * serial, which K2b did forever); other types are notifications. */\n'
     '\tif (s8_pmu == NULL ||\n'
     '\t    (type != 0 && type != 1 && type != 4 && type != 9 && type != 10)) {\n'
     '\t\treturn 0;\n'
     '\t}\n'
     '\tif (type == 0) {\n'
     '\t\ts8_pmu[0x330c / 4] &= ~0x100u;   /* PS_HOLD low: power off */\n'
     '\t\tfor (;;) {\n'
     '\t\t}\n'
     '\t}\n'
     '\tuint32_t reason = (s8_restart_to_recovery || (type != 1 && s8_panic_to_recovery)) ?\n'
     '\t    0x12345674u : 0x12345670u;     /* REASON_RECOVERY / UNKNOWN */\n'
     '\ts8_pmu[0x808 / 4] = 0x12345678u;     /* INFORM2: SEC_POWER_RESET */\n'
     '\ts8_pmu[0x80c / 4] = reason;          /* INFORM3 */\n'
     '\t__asm__ volatile ("dsb sy" ::: "memory");\n'
     '\ts8_pmu[0x400 / 4] = 1;               /* SWRESET */\n'
     '\tfor (;;) {\n'
     '\t}\n'
     '}\n'
     '\n'
     'static void\n'
     's8_restart_init(void)\n'
     '{\n'
     '\tuint32_t secs = 0;\n'
     '\n'
     '\ts8_pmu = (volatile uint32_t *)ml_io_map(0x16480000, 0x4000);\n'
     '\ts8_panic_to_recovery = PE_parse_boot_argn("s8autoreset", &secs, sizeof(secs)) && secs != 0;\n'
     '\tPE_halt_restart = s8_halt_restart;\n'
     '}\n'
     '\n'
     '/*\n * Copy of the console in TWRP', 1),
])

# 4 GiB RAM (Note 8 high bank 0x880000000-0x97fffffff) spans four 1 GiB L1
# entries in start.s, which allocates one 4 KiB L2 table per entry for both
# the V=P and KVA mapping: 2 L1 + 8 L2 = 10 pages. The 8-page default let the
# last two pages land on topology_info and the topology cpu/cluster arrays in
# __DATA_CONST, which ml_parse_cpu_topology() then read - a panic before the
# console, with no ring and no pstore text. Same bound as ARM_LARGE_MEMORY.
edit('osfmk/arm/pmap/pmap.h', [
    ('#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 8)\n',
     '#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 34)\n', 1),
])

# Boots 3, 5, 6 and 7 hung right after the kernel version line, before
# pmap_startup's "init/release time"; boots 1, 2, 3b and 5b got past it with
# the same image. The physical aperture slide (1 GiB range, early_random) is
# the boot-to-boot variable there (gPicBase differs on every photo). Pin it
# on the S8 and mark vm_page_bootstrap's steps in the console.
edit('osfmk/arm64/arm_vm_init.c', [
    ('\tuint64_t physmap_slide = early_random() & ARM64_PHYSMAP_SLIDE_MASK & ~((uint64_t)PAGE_MASK);\n',
     '#if defined(DREAMLTE)\n'
     '\tuint64_t physmap_slide = 0;\n'
     '#else\n'
     '\tuint64_t physmap_slide = early_random() & ARM64_PHYSMAP_SLIDE_MASK & ~((uint64_t)PAGE_MASK);\n'
     '#endif\n', 1),
    # Boot 14: a 4 MiB larger kernel (sweet_ufs log ring) moved
    # topOfKernelData and hung pmap_startup again. Only XNU_MONITOR builds
    # round physmap_base to a twig (2 MiB with 4 KiB pages); do it here too.
    # The real cause of the vm_page_bootstrap hangs (boots 3-7, 14, 15):
    # arm_vm_init pre-builds L3 tables only for (2 + 10 * 256 MiB-segments)
    # MiB + the boot_args framebuffer past dynamic_memory_begin. Our loader
    # passes no Video, yet the console maps the 17 MiB S8 framebuffer there
    # first; when pmap_steal_memory then needs a table beyond the budget,
    # pmap_enter cannot allocate one yet. With 4 KiB pages one L3 table spans
    # 2 MiB (32 MiB with 16 KiB), so add room for the framebuffer and 64 MiB.
    ('\tva_l1_end += round_page(args->Video.v_height * args->Video.v_rowBytes);\n',
     '\tva_l1_end += round_page(args->Video.v_height * args->Video.v_rowBytes);\n'
     '#if defined(DREAMLTE)\n'
     '\tva_l1_end += round_page((vm_size_t)A5_FB_STRIDE * A5_FB_HEIGHT) + (64ULL << 20);\n'
     '#endif\n', 1),
    ('\tphysmap_base += physmap_slide;\n',
     '\tphysmap_base += physmap_slide;\n'
     '#if defined(DREAMLTE) && !XNU_MONITOR\n'
     '\tphysmap_base = ROUND_TWIG(physmap_base);\n'
     '#endif\n', 1),
    ('\tif (pages_used > BOOTSTRAP_TABLE_SIZE) {\n',
     '\t/* BOOTSTRAP_TABLE_SIZE is a byte count; pages_used is a page count */\n'
     '\tif (pages_used > (BOOTSTRAP_TABLE_SIZE / ARM_PGBYTES)) {\n', 1),

])

edit('osfmk/vm/vm_resident.c', [
    ('\tpmap_startup(&virtual_space_start, &virtual_space_end);\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tkprintf("A5 vm: vm_page_bootstrap -> pmap_startup\\n");\n'
     '#endif\n'
     '\tpmap_startup(&virtual_space_start, &virtual_space_end);\n', 1),
    ('\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n',
     '\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tkprintf("A5 vm: npages=%u vm_pages=%p mem_sz=%#llx\\n", npages, vm_pages, (unsigned long long)mem_sz);\n'
     '#endif\n', 1),
    ('\t\tif (!pmap_next_page(&phys_page)) {\n\t\t\tbreak;\n\t\t}\n\n\t\tif (phys_page < max_valid_low_ppnum) {\n',
     '\t\tif (!pmap_next_page(&phys_page)) {\n\t\t\tbreak;\n\t\t}\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\t\tif ((i & 0x7fff) == 0) {\n'
     '\t\t\tkprintf("A5 vm: page %u ppn %#x\\n", i, phys_page);\n'
     '\t\t}\n'
     '#endif\n'
     '\n\t\tif (phys_page < max_valid_low_ppnum) {\n', 1),
    ('\tvm_page_pages = vm_pages_count; /* used to report to user space */\n',
     '\tvm_page_pages = vm_pages_count; /* used to report to user space */\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tkprintf("A5 vm: %u pages initialized, releasing\\n", vm_pages_count);\n'
     '#endif\n', 1),
])

# ---- Galaxy S8 internal UFS: the SWEET driver with the Exynos 8895 quirks ----
# Proven by the loader probe (shim/dreamlte/ufs_probe.c, S8 boot 13): HCE
# reads 0 while running, UTRD sizes in bytes, 16-byte PRDT entries of at
# most 4 KiB, NEXUS_TYPE bit per SCSI slot, and the device stays NOT READY
# (04/02) until START STOP UNIT (power condition ACTIVE) to W-LUN 0xD0.
edit('bsd/dev/sweet_ufs.c', [
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\n#include <sys/param.h>\n',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '#include <sys/param.h>\n', 1),
    ('#define CAP_64AS        (1u << 24)              /* 64-bit DMA addressing */\n',
     '#define CAP_64AS        (1u << 24)              /* 64-bit DMA addressing */\n'
     '\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '/*\n'
     ' * Galaxy S8 (Exynos 8895) host, per the Samsung 4.4 driver and the S8\n'
     ' * loader probe (shim/dreamlte/ufs_probe.c): UTRD offsets and lengths are\n'
     ' * in bytes (UFSHCD_QUIRK_BROKEN_DWORD_UTRD), PRDT entries are 16 bytes and\n'
     ' * cover at most 4 KiB (HCI_TXPRDT_ENTRY_SIZE 12), each SCSI slot needs its\n'
     ' * HCI_UTRL_NEXUS_TYPE bit, the standard HCE register reads 0 while the host\n'
     ' * runs (UFSHCD_QUIRK_USE_OF_HCE) and UTRLCLR is inverted\n'
     ' * (UFSHCD_QUIRK_BROKEN_REQ_LIST_CLR). S-Boot leaves the device stopped\n'
     ' * (sense 02/04/02): START STOP UNIT, power condition ACTIVE, to the UFS\n'
     ' * Device well-known LUN wakes it.\n'
     ' */\n'
     '#define EXYNOS_UFS              1\n'
     '#define VS_UTRL_NEXUS_TYPE      0x40\n'
     '#define UFS_WLUN_DEVICE         0xd0\n'
     '#define UFS_ADT_NODE            "/dreamlte-ufs"\n'
     '#define UFS_DEFAULT_PART        "USERDATA"\n'
     '#define PRDT_BYTES(field)       (field)\n'
     '#else\n'
     '#define UFS_ADT_NODE            "/sweet-ufs"\n'
     '#define UFS_DEFAULT_PART        "userdata"\n'
     '#define PRDT_BYTES(field)       ((field) * 16u)\n'
     '#endif\n', 1),
    ('#define PRDT_CHUNK      (256u << 10)            /* PRDT byte count field: 18 bits */\n',
     '#if defined(EXYNOS_UFS)\n'
     '#define PRDT_CHUNK      4096u                   /* HCI_TXPRDT_ENTRY_SIZE 12 */\n'
     '#else\n'
     '#define PRDT_CHUNK      (256u << 10)            /* PRDT byte count field: 18 bits */\n'
     '#endif\n', 1),
    ('\tvm_offset_t regs;\n',
     '\tvm_offset_t regs;\n\tvm_offset_t vs_regs;                    /* Exynos vendor HCI registers */\n', 1),
    ('\tutrd->resp = (512u / 4) << 16 | (512u / 4);\n',
     '#if defined(EXYNOS_UFS)\n'
     '\tutrd->resp = 512u << 16 | 512u;\n'
     '#else\n'
     '\tutrd->resp = (512u / 4) << 16 | (512u / 4);\n'
     '#endif\n', 1),
    ('\t\tutrd->prdt = (1024u / 4) << 16 | n;\n',
     '#if defined(EXYNOS_UFS)\n'
     '\t\tutrd->prdt = 1024u << 16 | (n * (uint32_t)sizeof(ucd->prdt[0]));\n'
     '#else\n'
     '\t\tutrd->prdt = (1024u / 4) << 16 | n;\n'
     '#endif\n', 1),
    ('\t\t\t    (utrd->prdt & 0xffff) * sizeof(ucd->prdt[0]));\n',
     '\t\t\t    PRDT_BYTES(utrd->prdt & 0xffff));\n', 1),
    ('\tufs_wr(REG_UTRLDBR, 1);\n',
     '#if defined(EXYNOS_UFS)\n'
     '\t*(volatile uint32_t *)(su.vs_regs + VS_UTRL_NEXUS_TYPE) |= 1;  /* slot 0: SCSI */\n'
     '#endif\n'
     '\tufs_wr(REG_UTRLDBR, 1);\n', 1),
    ('\t\t\tufs_wr(REG_UTRLCLR, ~1u);\n',
     '#if !defined(EXYNOS_UFS)\n'
     '\t\t\tufs_wr(REG_UTRLCLR, ~1u);\n'
     '#endif\n', 1),
    ('\tif (!(hce & 1) || !(hcs & HCS_DP) || !(hcs & HCS_UTRLRDY)) {\n',
     '#if defined(EXYNOS_UFS)\n'
     '\t(void)hce;\n'
     '\tif (!(hcs & HCS_DP) || !(hcs & HCS_UTRLRDY)) {\n'
     '#else\n'
     '\tif (!(hce & 1) || !(hcs & HCS_DP) || !(hcs & HCS_UTRLRDY)) {\n'
     '#endif\n', 1),
    ('\tchar want[64] = "userdata";\n', '\tchar want[64] = UFS_DEFAULT_PART;\n', 1),
    ('\tif (SecureDTLookupEntry(NULL, "/sweet-ufs", &node) != kSuccess ||\n'
     '\t    SecureDTGetProperty(node, "reg", (void const **)&reg, &size) != kSuccess ||\n'
     '\t    size < 2 * sizeof(uintptr_t)) {\n'
     '\t\tprintf("SWEET UFS: no /sweet-ufs node in the device tree\\n");\n',
     '\tif (SecureDTLookupEntry(NULL, UFS_ADT_NODE, &node) != kSuccess ||\n'
     '\t    SecureDTGetProperty(node, "reg", (void const **)&reg, &size) != kSuccess ||\n'
     '#if defined(EXYNOS_UFS)\n'
     '\t    size < 4 * sizeof(uintptr_t)) {\n'
     '#else\n'
     '\t    size < 2 * sizeof(uintptr_t)) {\n'
     '#endif\n'
     '\t\tprintf("SWEET UFS: no " UFS_ADT_NODE " node in the device tree\\n");\n', 1),
    ('\tsu.regs = ml_io_map(reg[0], reg[1]);\n',
     '\tsu.regs = ml_io_map(reg[0], reg[1]);\n'
     '#if defined(EXYNOS_UFS)\n'
     '\tsu.vs_regs = ml_io_map(reg[2], reg[3]);\n'
     '#endif\n', 1),
    ('\terror = ufs_take_over_host();\n',
     '\terror = ufs_take_over_host();\n'
     '#if defined(EXYNOS_UFS)\n'
     '\tif (!error) {\n'
     '\t\tstatic const uint8_t ssu_active[6] = { 0x1b, 0, 0, 0, 0x10, 0 };\n'
     '\t\tsu.lun = UFS_WLUN_DEVICE;\n'
     '\t\terror = ufs_scsi(ssu_active, sizeof(ssu_active), 0, false);\n'
     '\t\tsu.lun = 0;\n'
     '\t\tprintf("SWEET UFS: START STOP UNIT (ACTIVE) to the device W-LUN: %d\\n", error);\n'
     '\t}\n'
     '#endif\n', 1),
    ('\tsweet_sample_start();\n\t/* Input drivers (HID services in iokit/Kernel/arm/hid/SweetHID.cpp). */\n'
     '\tsweet_keys_init();\n\tsweet_touch_init();\n\tsweet_usb_probe();\n',
     '\tsweet_sample_start();\n'
     '#if defined(ARM64_BOARD_CONFIG_SWEET)\n'
     '\t/* Input drivers (HID services in iokit/Kernel/arm/hid/SweetHID.cpp). */\n'
     '\tsweet_keys_init();\n\tsweet_touch_init();\n\tsweet_usb_probe();\n'
     '#endif\n', 1),
])

# The SWEET user-stack sampler (bsd/dev/sweet_sample.c; its kernel hook in
# exception.c is already built for A5XELTE): stacks of SpringBoard and
# backboardd every 2 minutes, to see where 4-CPU rendering stalls (boot 22).
edit('bsd/dev/sweet_sample.c', [
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\n/*\n * SWEET process sampler',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n/*\n * SWEET process sampler', 1),
])

# rd=ufsroot0 also on the A5XELTE machine config (the S8 build).
edit('iokit/bsddev/IOKitBSDInit.cpp', [
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\n//\n//\tSWEET: root on a GPT partition of the internal UFS (bsd/dev/sweet_ufs.c)\n',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n//\n'
     '//\tSWEET / Galaxy S8: root on a GPT partition of the internal UFS (bsd/dev/sweet_ufs.c)\n', 1),
])

# Console copy into sweet_ufs.c's ring (written to the end of the root
# partition every ufslogsecs when ufsrw=1): longer than pstore, no bit flips.
edit('osfmk/console/serial_console.c', [
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\nextern void sweet_log_append',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\nextern void sweet_log_append', 1),
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\n\tsweet_log_append(c, size);',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tsweet_log_append(c, size);', 1),
])

# Physical instead of virtual EL1 timer on the S8 (A5_USE_PHYS_TIMER).
edit('osfmk/arm64/machine_routines.c', [
    ('\t\t__builtin_arm_wsr64("CNTV_TVAL_EL0", (uint64_t)dec_value);\n',
     '#if defined(A5_USE_PHYS_TIMER)\n'
     '\t\t__builtin_arm_wsr64("CNTP_TVAL_EL0", (uint64_t)dec_value);\n'
     '#else\n'
     '\t\t__builtin_arm_wsr64("CNTV_TVAL_EL0", (uint64_t)dec_value);\n'
     '#endif\n', 1),
    ('\t\twide_val = __builtin_arm_rsr64("CNTV_TVAL_EL0");\n',
     '#if defined(A5_USE_PHYS_TIMER)\n'
     '\t\twide_val = __builtin_arm_rsr64("CNTP_TVAL_EL0");\n'
     '#else\n'
     '\t\twide_val = __builtin_arm_rsr64("CNTV_TVAL_EL0");\n'
     '#endif\n', 1),
    ('\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTV_CTL_EL0");\n',
     '#if defined(A5_USE_PHYS_TIMER)\n'
     '\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTP_CTL_EL0");\n'
     '#else\n'
     '\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTV_CTL_EL0");\n'
     '#endif\n', 1),
    ('\t__builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);\n'
     '\t/* disable the physical timer as a precaution, as its registers reset to architecturally unknown values */\n'
     '\t__builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);\n',
     '#if defined(A5_USE_PHYS_TIMER)\n'
     '\t__builtin_arm_wsr64("CNTP_CTL_EL0", cntvctl);   /* same ENABLE bit */\n'
     '\t__builtin_arm_wsr64("CNTV_CTL_EL0", CNTV_CTL_EL0_IMASKED);\n'
     '#else\n'
     '\t__builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);\n'
     '\t/* disable the physical timer as a precaution, as its registers reset to architecturally unknown values */\n'
     '\t__builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);\n'
     '#endif\n', 1),
])

edit('pexpert/arm/pe_fiq.c', [
    ('\t    a5_gic_read32(a5_gicd_base, 0x080) | (1U << 27) | (1U << 1));\n',
     '\t    a5_gic_read32(a5_gicd_base, 0x080) | (1U << A5XELTE_VTIMER_INTID) | (1U << 1));\n', 1),
    ('\ta5_gic_write32(a5_gicd_base, 0x100, (1U << 27) | (1U << 1));\n',
     '\ta5_gic_write32(a5_gicd_base, 0x100, (1U << A5XELTE_VTIMER_INTID) | (1U << 1));\n', 1),
])

# IOKit platform expert / CPU personalities: also match the S8 names.
# Present the S8 panel as the iPhone X screen (1125x2436, centered on the
# 1440x2960 panel), like SWEET does: iOS has no layout data for 1440x2960.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('#if !defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tif (!native && fWidth <= SWEET_FB_LOGICAL_W && fHeight <= SWEET_FB_LOGICAL_H) {\n',
     '#if defined(DREAMLTE)\n'
     '\tif (!native) {\n'
     '\t\tfLogicalW = SWEET_FB_LOGICAL_W;\n'
     '\t\tfLogicalH = SWEET_FB_LOGICAL_H;\n'
     '\t}\n'
     '#elif !defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tif (!native && fWidth <= SWEET_FB_LOGICAL_W && fHeight <= SWEET_FB_LOGICAL_H) {\n', 1),
])

edit('iokit/KernelConfigTables.cpp', [
    ("    \"     'IONameMatch'     = 'samsung,a5xelte-display';\"\n",
     "    \"     'IONameMatch'     = ('samsung,a5xelte-display', 'samsung,dreamlte-display');\"\n", 1),
    ("    \"     'IONameMatch'     = 'samsung,a5xelte';\"\n",
     "    \"     'IONameMatch'     = ('samsung,a5xelte', 'samsung,dreamlte');\"\n", 1),
    # K2 (cpus=8) stopped: the ADT names the Mongoose cores
    # 'samsung,mongoose-m2' (as Samsung's DT and mainline do), SweetCPU only
    # matched 'arm,cortex-a53', so logical 4-7 got no driver and startAll
    # panicked with "CPU registration timeout" after 10 s.
    ("    \"     'IONameMatch'     = 'arm,cortex-a53';\"\n",
     "    \"     'IONameMatch'     = ('arm,cortex-a53', 'samsung,mongoose-m2');\"\n", 1),
])

# A5 touch probe maps Exynos7580 I2C/GPIO blocks: a bus error on the S8.
edit('bsd/dev/a5xelte_touch.c', [
    ('#include <pexpert/pexpert.h>\n',
     '#include <pexpert/pexpert.h>\n#include <pexpert/arm64/board_config.h>\n', 1),
    ('a5xelte_touch_probe(void)\n{\n\tint enabled = 1;\n',
     'a5xelte_touch_probe(void)\n{\n\tint enabled = A5_TOUCH_DEFAULT; /* A5 touch: off on the S8 */\n', 1),
])
# No platform clock on the S8 (iOS showed 31 Dec 1969). The loader reads the
# S2MPS17 RTC and passes s8rtc = UTC seconds at system-counter zero.
edit('iokit/Kernel/IOPlatformExpert.cpp', [
    ('\tif (gIOPlatform) {\n\t\tgIOPlatform->getUTCTimeOfDay(secs, &nsecs);\n\t}\n\n\tassert(nsecs < NSEC_PER_SEC);\n',
     '\tif (gIOPlatform) {\n\t\tgIOPlatform->getUTCTimeOfDay(secs, &nsecs);\n\t}\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tuint64_t s8rtc = 0;\n'
     '\tif (*secs == 0 && PE_parse_boot_argn("s8rtc", &s8rtc, sizeof(s8rtc)) && s8rtc) {\n'
     '\t\tuint64_t ns;\n'
     '\t\tabsolutetime_to_nanoseconds(mach_absolute_time(), &ns);\n'
     '\t\t*secs = (clock_sec_t)(s8rtc + ns / NSEC_PER_SEC);\n'
     '\t\tnsecs = (clock_nsec_t)(ns % NSEC_PER_SEC);\n'
     '\t}\n'
     '#endif\n\n\tassert(nsecs < NSEC_PER_SEC);\n', 1),
    ('#include <pexpert/pexpert.h>\n#include <uuid/uuid.h>\n',
     '#include <pexpert/pexpert.h>\n#include <uuid/uuid.h>\n#include <kern/clock.h>\n'
     '#include <mach/mach_time.h>\n', 1),
])

# Present at SwapEnd. Boot 29 (sweetfb_hz=30) showed heavy artifacts: the
# vsync timer copied the latest swapped surface whenever it fired, while
# CoreAnimation (SwapWait is a no-op) could already be drawing into it.
# During the SwapEnd call the surface is stable, so copy there, at most once
# per 1/hz; the timer only flushes a swap that was skipped. One lock
# serializes the two copy paths.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('\tuint32_t      fFadeStep;      /* fade-out steps done while off */\n',
     '\tuint32_t      fFadeStep;      /* fade-out steps done while off */\n'
     '\tIOLock       *fPresentLock;   /* one panel copy at a time */\n'
     '\tuint64_t      fLastPresent;   /* mach_absolute_time of the last copy */\n'
     '\tuint64_t      fMinGap;        /* 1/hz in timebase ticks */\n', 1),
    ('\tfFlushTicks = (hz == 0 || hz >= 60) ? 1 : 60 / hz;\n',
     '\tfFlushTicks = (hz == 0 || hz >= 60) ? 1 : 60 / hz;\n'
     '\tfMinGap = 26000000ULL / (hz == 0 ? 60 : hz);     /* 26 MHz timebase */\n'
     '\tfPresentLock = IOLockAlloc();\n'
     '\tif (fPresentLock == NULL) {\n'
     '\t\treturn false;\n'
     '\t}\n', 1),
    ('\tmemcpy(fPending, rec, SWEET_FB_SWAP_REC_SIZE);\n\tfDirty = true;\n\tIOLockUnlock(fLock);\n',
     '\tmemcpy(fPending, rec, SWEET_FB_SWAP_REC_SIZE);\n\tfDirty = true;\n'
     '\tuint64_t now = mach_absolute_time();\n'
     '\tbool copyNow = !fPowerOff && now - fLastPresent >= fMinGap;\n'
     '\tif (copyNow) {\n'
     '\t\tfDirty = false;\n'
     '\t\tfLastPresent = now;\n'
     '\t}\n'
     '\tIOLockUnlock(fLock);\n'
     '\tif (copyNow) {\n'
     '\t\tpresent(rec);\n'
     '\t}\n', 1),
    ('\tuint32_t mask = get32(rec, 0x104);\n',
     '\tuint32_t mask = get32(rec, 0x104);\n\tIOLockLock(fPresentLock);\n'
     '#if defined(DREAMLTE)\n\tsweet_fb_wait_frame_done();\n#endif\n', 1),
    ('static uint32_t sweet_fb_swaps_logged;\n',
     '#if defined(DREAMLTE)\n'
     '/*\n'
     ' * Boot 31 video: torn frames (top half of one screen, bottom of the\n'
     ' * next). DECON_F fetches the panel memory at 60 Hz (boot 30 probe: 30\n'
     ' * frame-done events per 0.5 s) while we copy into it. Start each copy\n'
     ' * right after a frame-done (INTERRUPT_PENDING 0x4c bit 13, source\n'
     ' * enabled in INTERRUPT_ENABLE 0x40; the SPI is not routed), so the copy\n'
     ' * runs ahead of the next fetch.\n'
     ' */\n'
     'extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);\n'
     'static vm_offset_t sweet_fb_decon;\n'
     '\n'
     'static void\n'
     'sweet_fb_wait_frame_done(void)\n'
     '{\n'
     '\tif (sweet_fb_decon == 0) {\n'
     '\t\tsweet_fb_decon = ml_io_map(0x12860000, 0x1000);\n'
     '\t\tif (sweet_fb_decon == 0) {\n'
     '\t\t\treturn;\n'
     '\t\t}\n'
     '\t\t*(volatile uint32_t *)(sweet_fb_decon + 0x40) |= (1u << 13) | 1u;\n'
     '\t}\n'
     '\tvolatile uint32_t *pend = (volatile uint32_t *)(sweet_fb_decon + 0x4c);\n'
     '\t*pend = 1u << 13;\n'
     '\tfor (int i = 0; i < 200 && !(*pend & (1u << 13)); i++) {\n'
     '\t\tIODelay(100);\n'
     '\t}\n'
     '}\n'
     '#endif\n'
     '\n'
     'static uint32_t sweet_fb_swaps_logged;\n', 1),
    ('\t\ts->release();\n\t}\n}\n',
     '\t\ts->release();\n\t}\n\tIOLockUnlock(fPresentLock);\n}\n', 1),
])

# Battery: the A5XELTE config had no power source, so iOS showed a wrong
# battery. On the S8, SweetBattery reads the MAX77865 fuel gauge and charger
# through dreamlte_battery_read() (dreamlte_touch.c). S8 battery: 3000 mAh.
edit('iokit/Kernel/arm/SweetBattery.cpp', [
    ('#if defined(ARM64_BOARD_CONFIG_SWEET)\n#include <device/device_types.h>',
     '#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '#include <device/device_types.h>', 1),
    ('/* bsd/dev/sweet_spmi.c */\n'
     'extern "C" int sweet_spmi_init(void);\n'
     'extern "C" int sweet_spmi_read(unsigned sid, unsigned addr, uint8_t *out);\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '/* Galaxy S8: MAX77865 fuel gauge (bsd/dev/a5xelte_touch.c). */\n'
     'extern "C" int dreamlte_battery_read(unsigned *percent, unsigned *mv, int *ma,\n'
     '    int *external, int *charging, int *full);\n'
     'static inline int sweet_spmi_init(void) { return -1; }\n'
     'static inline int sweet_spmi_read(unsigned, unsigned, uint8_t *) { return -1; }\n'
     '#define SWEET_BAT_MAH 3000u\n'
     '#else\n'
     '/* bsd/dev/sweet_spmi.c */\n'
     'extern "C" int sweet_spmi_init(void);\n'
     'extern "C" int sweet_spmi_read(unsigned sid, unsigned addr, uint8_t *out);\n'
     '#define SWEET_BAT_MAH 5020u\n'
     '#endif\n', 1),
    ('5020u * percent', 'SWEET_BAT_MAH * percent', 1),
    ('setMaxCapacity(5020)', 'setMaxCapacity(SWEET_BAT_MAH)', 1),
    ('"AppleRawMaxCapacity", 5020)', '"AppleRawMaxCapacity", SWEET_BAT_MAH)', 1),
    ('"DesignCapacity", 5020)', '"DesignCapacity", SWEET_BAT_MAH)', 1),
    ('{capacity, 5020, mv', '{capacity, SWEET_BAT_MAH, mv', 1),
    ('void\nSweetBattery::poll(void)\n{\n',
     'void\nSweetBattery::poll(void)\n{\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\tunsigned pct = 0, s8mv = 0;\n'
     '\tint s8ma = 0, ext = 0, chg = 0, full = 0;\n'
     '\tif (fReal && dreamlte_battery_read(&pct, &s8mv, &s8ma, &ext, &chg, &full) == 0) {\n'
     '\t\tpublish(full ? 100 : pct, s8mv, s8ma, ext != 0, ext != 0, chg != 0, full != 0, true, true);\n'
     '\t} else {\n'
     '\t\tpublish(100, 4200, 0, true, true, false, true, false, false);\n'
     '\t}\n'
     '#else\n', 1),
    ('\t    charging, full, true, currentValid);\n}\n',
     '\t    charging, full, true, currentValid);\n#endif\n}\n', 1),
    ('\tint real = 0;\n\t(void)PE_parse_boot_argn("sweetbattery"',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tint real = 1;\n#else\n\tint real = 0;\n#endif\n'
     '\t(void)PE_parse_boot_argn("sweetbattery"', 1),
    ('\tfReal = real == 1 && sweet_spmi_init() == 0;\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tfReal = real == 1;\n#else\n'
     '\tfReal = real == 1 && sweet_spmi_init() == 0;\n#endif\n', 1),
    ('measured ? "PM6150 / estimated SOC" : "static fallback"',
     'measured ? "fuel gauge" : "static fallback"', 1),
])
edit('iokit/KernelConfigTables.cpp', [
    ('#if !defined(ARM64_BOARD_CONFIG_A5XELTE)\n    "   {"\n    "     \'IOClass\'         = SweetBattery;"',
     '#if !defined(ARM64_BOARD_CONFIG_A5XELTE) || 1  /* S8: MAX77865 */\n    "   {"\n'
     '    "     \'IOClass\'         = SweetBattery;"', 1),
])

# S8 S6SY761 driver (dreamlte_touch.c next to this script), started from
# the same IOKitBSDInit hook in place of the A5 probe.
edit('bsd/dev/a5xelte_touch.c', [
    ('void\na5xelte_touch_probe(void)\n{\n',
     (Path(__file__).parent / 'dreamlte_touch.c').read_text() +
     'void\na5xelte_touch_probe(void)\n{\n'
     '#if defined(DREAMLTE)\n\tdreamlte_touch_start();   /* the A5 path below stays off */\n#endif\n', 1),
])

# Secondary CPUs. Boots 19-21 started the A53s with a PMU power edge
# (CPUn_CONFIGURATION 0 -> 0xF around PSCI CPU_ON) and a low trampoline; the
# Mongoose cluster never came up that way. galaxios8 boot m8 (loader E2) found
# the cause: S-Boot leaves the GIC distributor disabled (GICD_CTLR = 0) and
# sets CPUn_OPTION = 0x10a, whose bit 8 (ENABLE_AUTO_WAKEUP_INT_REQ) makes the
# PMU power a core (and its cluster) up on a GIC wake request. With GICD
# enabled, plain PSCI CPU_ON starts both 0x101 and Mongoose 0x000, as in
# TWRP's Linux. The firmware keeps the CPU_ON entry in a 32-bit PMU INFORM
# register, so the low trampoline stays.
edit('iokit/Kernel/arm/SweetCPU.cpp', [
    ('#include <pexpert/pexpert.h>\n',
     '#include <pexpert/pexpert.h>\n'
     '#if defined(DREAMLTE)\n'
     'extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);\n'
     '#endif\n', 1),
    ('\tif (start_paddr != 0 || arg_paddr != 0 || cpu->phys_id == 0 ||\n',
     '\tif (start_paddr != 0 || arg_paddr != 0 || cpu->phys_id == A5_BOOT_MPIDR ||\n', 1),
    ('\t__builtin_arm_dsb(DSB_SY);\n\tint32_t rc = sweet_psci_cpu_on(cpu->phys_id, entry, getCPUNumber());\n',
     '#if defined(DREAMLTE)\n'
     '\t{\n'
     '\t\t/* ldr x1, 8; br x1; .quad entry, in the unused low bank */\n'
     '\t\tstatic vm_offset_t tramp, gicd;\n'
     '\t\tconst uint64_t tramp_pa = 0x8f000000ULL;\n'
     '\t\tif (tramp == 0) {\n'
     '\t\t\ttramp = ml_io_map(tramp_pa, 0x1000);\n'
     '\t\t\tgicd = ml_io_map(0x10201000, 0x1000);\n'
     '\t\t}\n'
     '\t\tvolatile uint32_t *t = (volatile uint32_t *)tramp;\n'
     '\t\tt[0] = 0x58000041;              /* ldr x1, #8 */\n'
     '\t\tt[1] = 0xd61f0020;              /* br x1 */\n'
     '\t\tt[2] = (uint32_t)entry;\n'
     '\t\tt[3] = (uint32_t)((uint64_t)entry >> 32);\n'
     '\t\tvolatile uint32_t *ctlr = (volatile uint32_t *)gicd;\n'
     '\t\tuint32_t was = *ctlr;\n'
     '\t\t*ctlr = was | 1;                /* GICD_CTLR: PMU auto wakeup */\n'
     '\t\t__builtin_arm_dsb(DSB_SY);\n'
     '\t\tIOLog(CPU_PORT_NAME " CPU: cpu=%u mpidr=0x%llx entry 0x%llx via 0x%llx, GICD_CTLR 0x%x\\n",\n'
     '\t\t    getCPUNumber(), (uint64_t)cpu->phys_id, (uint64_t)entry, tramp_pa, was);\n'
     '\t\tentry = (vm_offset_t)tramp_pa;\n'
     '\t}\n'
     '#endif\n'
     '\t__builtin_arm_dsb(DSB_SY);\n\tint32_t rc = sweet_psci_cpu_on(cpu->phys_id, entry, getCPUNumber());\n', 1),
])

# Smoothness, step 1. present() runs inside backboardd's SwapEnd call: it
# waits for a DECON frame-done (up to 16 ms) and then copies the frame
# (1440x2960x4 = 17 MB) into the panel memory, so CoreAnimation's render
# thread is blocked for the whole copy (async copies tore in boot 29 because
# CA reuses the surface). With eight cores, split the copy over the caller
# and three helper threads, and log what present() costs every 100 frames.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('static uint32_t sweet_fb_swaps_logged;\n',
     '#if defined(DREAMLTE)\n'
     'extern "C" kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);\n'
     'extern "C" void thread_deallocate(thread_t);\n'
     '\n'
     '#define SWEET_FB_COPY_HELPERS 3\n'
     'struct sweet_fb_copy_job {\n'
     '\tuintptr_t dst, src;\n'
     '\tuint64_t dstride, sstride, bytes;\n'
     '\tint32_t rows;\n'
     '};\n'
     'static struct sweet_fb_copy_job sweet_fb_jobs[SWEET_FB_COPY_HELPERS];\n'
     'static IOLock *sweet_fb_copy_lock;\n'
     'static uint32_t sweet_fb_copy_gen, sweet_fb_copy_left;\n'
     'static uint64_t sweet_fb_wait_ticks, sweet_fb_copy_ticks, sweet_fb_presents;\n'
     '\n'
     'static void\n'
     'sweet_fb_copy_rows(const struct sweet_fb_copy_job *j)\n'
     '{\n'
     '\tfor (int32_t y = 0; y < j->rows; y++) {\n'
     '\t\tmemcpy((void *)(j->dst + (uint64_t)y * j->dstride),\n'
     '\t\t    (const void *)(j->src + (uint64_t)y * j->sstride), (size_t)j->bytes);\n'
     '\t}\n'
     '}\n'
     '\n'
     'static void\n'
     'sweet_fb_copy_helper(void *arg, wait_result_t wr __unused)\n'
     '{\n'
     '\tuintptr_t idx = (uintptr_t)arg;\n'
     '\tuint32_t seen = 0;\n'
     '\n'
     '\tfor (;;) {\n'
     '\t\tIOLockLock(sweet_fb_copy_lock);\n'
     '\t\twhile (sweet_fb_copy_gen == seen) {\n'
     '\t\t\tIOLockSleep(sweet_fb_copy_lock, &sweet_fb_copy_gen, THREAD_UNINT);\n'
     '\t\t}\n'
     '\t\tseen = sweet_fb_copy_gen;\n'
     '\t\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '\t\tsweet_fb_copy_rows(&sweet_fb_jobs[idx]);\n'
     '\t\tIOLockLock(sweet_fb_copy_lock);\n'
     '\t\tif (--sweet_fb_copy_left == 0) {\n'
     '\t\t\tIOLockWakeup(sweet_fb_copy_lock, &sweet_fb_copy_left, false);\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '\t}\n'
     '}\n'
     '\n'
     '/* Copy rows x bytes, split over the helpers and the caller. */\n'
     'static void\n'
     'sweet_fb_copy(uintptr_t dst, uint64_t dstride, uintptr_t src, uint64_t sstride,\n'
     '    uint64_t bytes, int32_t rows)\n'
     '{\n'
     '\tif (sweet_fb_copy_lock == NULL) {\n'
     '\t\tsweet_fb_copy_lock = IOLockAlloc();\n'
     '\t\tfor (uintptr_t i = 0; sweet_fb_copy_lock != NULL && i < SWEET_FB_COPY_HELPERS; i++) {\n'
     '\t\t\tthread_t t;\n'
     '\t\t\tif (kernel_thread_start(sweet_fb_copy_helper, (void *)i, &t) == KERN_SUCCESS) {\n'
     '\t\t\t\tthread_deallocate(t);\n'
     '\t\t\t}\n'
     '\t\t}\n'
     '\t}\n'
     '\tint32_t parts = SWEET_FB_COPY_HELPERS + 1;\n'
     '\tif (sweet_fb_copy_lock == NULL || rows < 64) {\n'
     '\t\tstruct sweet_fb_copy_job all = { dst, src, dstride, sstride, bytes, rows };\n'
     '\t\tsweet_fb_copy_rows(&all);\n'
     '\t\treturn;\n'
     '\t}\n'
     '\tint32_t per = rows / parts, at = 0;\n'
     '\tIOLockLock(sweet_fb_copy_lock);\n'
     '\tfor (int32_t i = 0; i < SWEET_FB_COPY_HELPERS; i++, at += per) {\n'
     '\t\tsweet_fb_jobs[i] = (struct sweet_fb_copy_job){\n'
     '\t\t\tdst + (uint64_t)at * dstride, src + (uint64_t)at * sstride,\n'
     '\t\t\tdstride, sstride, bytes, per };\n'
     '\t}\n'
     '\tsweet_fb_copy_left = SWEET_FB_COPY_HELPERS;\n'
     '\tsweet_fb_copy_gen++;\n'
     '\tIOLockWakeup(sweet_fb_copy_lock, &sweet_fb_copy_gen, false);\n'
     '\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '\tstruct sweet_fb_copy_job mine = { dst + (uint64_t)at * dstride, src + (uint64_t)at * sstride,\n'
     '\t\tdstride, sstride, bytes, rows - at };\n'
     '\tsweet_fb_copy_rows(&mine);\n'
     '\tIOLockLock(sweet_fb_copy_lock);\n'
     '\twhile (sweet_fb_copy_left != 0) {\n'
     '\t\tIOLockSleep(sweet_fb_copy_lock, &sweet_fb_copy_left, THREAD_UNINT);\n'
     '\t}\n'
     '\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '}\n'
     '#endif\n'
     '\n'
     'static uint32_t sweet_fb_swaps_logged;\n', 1),
    ('#if defined(DREAMLTE)\n\tsweet_fb_wait_frame_done();\n#endif\n',
     '#if defined(DREAMLTE)\n'
     '\tuint64_t t_wait = mach_absolute_time();\n'
     '\tsweet_fb_wait_frame_done();\n'
     '\tuint64_t t_copy = mach_absolute_time();\n'
     '\tsweet_fb_wait_ticks += t_copy - t_wait;\n'
     '#endif\n', 1),
    ('\t\tif (src != 0 && bpe == 4) {\n'
     '\t\t\tfor (int32_t y = 0; y < h; y++) {\n'
     '\t\t\t\tmemcpy((void *)(fPixels + (uint64_t)(dy + y) * fRowBytes + (uint64_t)dx * 4),\n'
     '\t\t\t\t    (const void *)(src + s->offset + (uint64_t)(sy + y) * s->bytesPerRow + (uint64_t)sx * 4),\n'
     '\t\t\t\t    (size_t)w * 4);\n'
     '\t\t\t}\n'
     '\t\t}\n',
     '\t\tif (src != 0 && bpe == 4) {\n'
     '#if defined(DREAMLTE)\n'
     '\t\t\tsweet_fb_copy(fPixels + (uint64_t)dy * fRowBytes + (uint64_t)dx * 4, fRowBytes,\n'
     '\t\t\t    src + s->offset + (uint64_t)sy * s->bytesPerRow + (uint64_t)sx * 4,\n'
     '\t\t\t    s->bytesPerRow, (uint64_t)w * 4, h);\n'
     '#else\n'
     '\t\t\tfor (int32_t y = 0; y < h; y++) {\n'
     '\t\t\t\tmemcpy((void *)(fPixels + (uint64_t)(dy + y) * fRowBytes + (uint64_t)dx * 4),\n'
     '\t\t\t\t    (const void *)(src + s->offset + (uint64_t)(sy + y) * s->bytesPerRow + (uint64_t)sx * 4),\n'
     '\t\t\t\t    (size_t)w * 4);\n'
     '\t\t\t}\n'
     '#endif\n'
     '\t\t}\n', 1),
    ('\t\ts->release();\n\t}\n\tIOLockUnlock(fPresentLock);\n}\n',
     '\t\ts->release();\n\t}\n'
     '#if defined(DREAMLTE)\n'
     '\tsweet_fb_copy_ticks += mach_absolute_time() - t_copy;\n'
     '\tif ((++sweet_fb_presents % 100) == 0) {\n'
     '\t\tIOLog("SWEET FB: %llu presents at %llu s, last 100: wait %llu us, copy %llu us avg; %llu swaps\\n",\n'
     '\t\t    sweet_fb_presents, mach_absolute_time() / 26000000ULL, sweet_fb_wait_ticks / 2600,\n'
     '\t\t    sweet_fb_copy_ticks / 2600, sweet_fb_swap_count);\n'
     '\t\tsweet_fb_wait_ticks = sweet_fb_copy_ticks = 0;\n'
     '\t}\n'
     '#endif\n'
     '\tIOLockUnlock(fPresentLock);\n}\n', 1),
])

# Smoothness, step 2 (run p3: during swipes ~30 frames/s, each present
# blocked the render thread ~10 ms waiting for frame-done + ~3 ms copying).
# present() now only snapshots the frame into a kernel staging buffer (the
# CA surface is free again when SwapEnd returns, so no tearing from surface
# reuse); a presenter thread waits for frame-done and copies the stage to the
# panel. Both copies hold fPresentLock, so they never overlap.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('static uint32_t sweet_fb_swaps_logged;\n',
     '#if defined(DREAMLTE)\n'
     'static IOLock *sweet_fb_present_lock;\n'
     'static uintptr_t sweet_fb_stage, sweet_fb_panel;\n'
     'static uint64_t sweet_fb_stride;\n'
     'static int32_t sweet_fb_rows;\n'
     'static bool sweet_fb_stage_pending;\n'
     'static uint64_t sweet_fb_panel_ticks, sweet_fb_panel_copies;\n'
     '\n'
     'static void\n'
     'sweet_fb_presenter(void *arg __unused, wait_result_t wr __unused)\n'
     '{\n'
     '\tfor (;;) {\n'
     '\t\tIOLockLock(sweet_fb_present_lock);\n'
     '\t\twhile (!sweet_fb_stage_pending) {\n'
     '\t\t\tIOLockSleep(sweet_fb_present_lock, &sweet_fb_stage_pending, THREAD_UNINT);\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_present_lock);\n'
     '\t\tuint64_t t0 = mach_absolute_time();\n'
     '\t\tsweet_fb_wait_frame_done();\n'
     '\t\tuint64_t t1 = mach_absolute_time();\n'
     '\t\tIOLockLock(sweet_fb_present_lock);\n'
     '\t\tsweet_fb_stage_pending = false;\n'
     '\t\tsweet_fb_copy(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage, sweet_fb_stride,\n'
     '\t\t    sweet_fb_stride, sweet_fb_rows);\n'
     '\t\tIOLockUnlock(sweet_fb_present_lock);\n'
     '\t\tsweet_fb_wait_ticks += t1 - t0;\n'
     '\t\tsweet_fb_panel_ticks += mach_absolute_time() - t1;\n'
     '\t\tsweet_fb_panel_copies++;\n'
     '\t}\n'
     '}\n'
     '#endif\n'
     '\n'
     'static uint32_t sweet_fb_swaps_logged;\n', 1),
    ('#if defined(DREAMLTE)\n'
     '\tuint64_t t_wait = mach_absolute_time();\n'
     '\tsweet_fb_wait_frame_done();\n'
     '\tuint64_t t_copy = mach_absolute_time();\n'
     '\tsweet_fb_wait_ticks += t_copy - t_wait;\n'
     '#endif\n',
     '#if defined(DREAMLTE)\n'
     '\tuint64_t t_copy = mach_absolute_time();\n'
     '\tif (sweet_fb_stage == 0 && sweet_fb_present_lock == NULL) {\n'
     '\t\tsweet_fb_present_lock = fPresentLock;\n'
     '\t\tsweet_fb_panel = fPixels;\n'
     '\t\tsweet_fb_stride = fRowBytes;\n'
     '\t\tsweet_fb_rows = (int32_t)fHeight;\n'
     '\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)(fRowBytes * fHeight));\n'
     '\t\tthread_t t;\n'
     '\t\tif (stage != 0) {\n'
     '\t\t\tsweet_fb_copy(stage, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n'
     '\t\t\tif (kernel_thread_start(sweet_fb_presenter, NULL, &t) == KERN_SUCCESS) {\n'
     '\t\t\t\tthread_deallocate(t);\n'
     '\t\t\t\tsweet_fb_stage = stage;\n'
     '\t\t\t\tIOLog("SWEET FB: staged present, %llu bytes\\n", (uint64_t)fRowBytes * fHeight);\n'
     '\t\t\t}\n'
     '\t\t}\n'
     '\t}\n'
     '\t/* No stage (allocation failed): the old synchronous path. */\n'
     '\tuintptr_t panel = sweet_fb_stage != 0 ? sweet_fb_stage : fPixels;\n'
     '\tif (sweet_fb_stage == 0) {\n'
     '\t\tsweet_fb_wait_frame_done();\n'
     '\t}\n'
     '#endif\n', 1),
    ('\t\t\tsweet_fb_copy(fPixels + (uint64_t)dy * fRowBytes + (uint64_t)dx * 4, fRowBytes,\n',
     '\t\t\tsweet_fb_copy(panel + (uint64_t)dy * fRowBytes + (uint64_t)dx * 4, fRowBytes,\n', 1),
    ('\tsweet_fb_copy_ticks += mach_absolute_time() - t_copy;\n'
     '\tif ((++sweet_fb_presents % 100) == 0) {\n',
     '\tsweet_fb_copy_ticks += mach_absolute_time() - t_copy;\n'
     '\tif (sweet_fb_stage != 0) {\n'
     '\t\tsweet_fb_stage_pending = true;\n'
     '\t\tIOLockWakeup(fPresentLock, &sweet_fb_stage_pending, false);\n'
     '\t}\n'
     '\tif ((++sweet_fb_presents % 100) == 0) {\n', 1),
    ('\t\tIOLog("SWEET FB: %llu presents at %llu s, last 100: wait %llu us, copy %llu us avg; %llu swaps\\n",\n'
     '\t\t    sweet_fb_presents, mach_absolute_time() / 26000000ULL, sweet_fb_wait_ticks / 2600,\n'
     '\t\t    sweet_fb_copy_ticks / 2600, sweet_fb_swap_count);\n'
     '\t\tsweet_fb_wait_ticks = sweet_fb_copy_ticks = 0;\n',
     '\t\tuint64_t n = sweet_fb_panel_copies ? sweet_fb_panel_copies : 1;\n'
     '\t\tIOLog("SWEET FB: %llu presents at %llu s, last 100: snapshot %llu us avg (render thread); "\n'
     '\t\t    "%llu panel copies, wait %llu us, copy %llu us avg; %llu swaps\\n",\n'
     '\t\t    sweet_fb_presents, mach_absolute_time() / 26000000ULL, sweet_fb_copy_ticks / 2600,\n'
     '\t\t    sweet_fb_panel_copies, sweet_fb_wait_ticks / 26 / n, sweet_fb_panel_ticks / 26 / n,\n'
     '\t\t    sweet_fb_swap_count);\n'
     '\t\tsweet_fb_wait_ticks = sweet_fb_copy_ticks = sweet_fb_panel_ticks = 0;\n'
     '\t\tsweet_fb_panel_copies = 0;\n', 1),
])

# Run p5: in 14 minutes locationd crashed 106 times, WirelessRadioManagerd
# 45, bluetoothd and fairplayd.H2 were started ~80 times each (no GPS, radio,
# Bluetooth or FairPlay hardware), and ReportCrash processed every crash,
# all competing with the UI the user was trying to use. Boot-arg
# s8noexec=a,b,... refuses to exec those process names (launchd then retries
# rarely, without dyld, a crash or a report). Reversible: drop the boot-arg.
edit('bsd/kern/kern_exec.c', [
    ('static int exec_activate_image(struct image_params *imgp);\n',
     'static int exec_activate_image(struct image_params *imgp);\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     'static int\n'
     's8_exec_denied(const char *name)\n'
     '{\n'
     '\tstatic char list[256];\n'
     '\tstatic int state;       /* 0 unparsed, 1 no list, 2 list */\n'
     '\n'
     '\tif (state == 0) {\n'
     '\t\tstate = (PE_parse_boot_argn("s8noexec", list, sizeof(list)) && list[0]) ? 2 : 1;\n'
     '\t}\n'
     '\tif (state != 2) {\n'
     '\t\treturn 0;\n'
     '\t}\n'
     '\tsize_t n = strlen(name);\n'
     '\tfor (const char *t = list; *t;) {\n'
     '\t\tconst char *e = strchr(t, \',\');\n'
     '\t\tsize_t tl = e ? (size_t)(e - t) : strlen(t);\n'
     '\t\tif (tl == n && strncmp(t, name, n) == 0) {\n'
     '\t\t\treturn 1;\n'
     '\t\t}\n'
     '\t\tif (e == NULL) {\n'
     '\t\t\tbreak;\n'
     '\t\t}\n'
     '\t\tt = e + 1;\n'
     '\t}\n'
     '\treturn 0;\n'
     '}\n'
     '#endif\n', 1),
    ('\t\t\t/* A short line keeps the persistent console ring useful. */\n'
     '\t\t\tprintf("exec %s\\n", p->p_name);\n',
     '\t\t\t/* A short line keeps the persistent console ring useful. */\n'
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
     '\t\t\tif (s8_exec_denied(p->p_name)) {\n'
     '\t\t\t\tprintf("exec %s denied (s8noexec)\\n", p->p_name);\n'
     '\t\t\t\t/* done: asserts a reason for every failure here (run p6 panic). */\n'
     '\t\t\t\tsignature_failure_reason = os_reason_create(OS_REASON_EXEC,\n'
     '\t\t\t\t    EXEC_EXIT_REASON_WRONG_PLATFORM);\n'
     '\t\t\t\terror = EPERM;\n'
     '\t\t\t\tgoto done;\n'
     '\t\t\t}\n'
     '#endif\n'
     '\t\t\tprintf("exec %s\\n", p->p_name);\n', 1),
])

# Smoothness, step 3: fewer pixels for CoreAnimation. With sweetfb_native=0
# iOS renders the iPhone X size, 1125x2436 (36 % fewer pixels than the
# 1440x2960 panel, and the layout Apple designed); upstream showed it 1:1 in
# the middle. Boot-arg sweetfb_scale=1 makes the stage that logical size and
# lets the presenter thread scale it to 1367x2960, centered (uniform 1.215,
# 36-pixel black side bars), nearest-neighbour with precomputed row/column
# maps, on the same helper threads.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('struct sweet_fb_copy_job {\n'
     '\tuintptr_t dst, src;\n'
     '\tuint64_t dstride, sstride, bytes;\n'
     '\tint32_t rows;\n'
     '};\n',
     'struct sweet_fb_copy_job {\n'
     '\tuintptr_t dst, src;\n'
     '\tuint64_t dstride, sstride, bytes;\n'
     '\tint32_t rows;\n'
     '\tint kind;        /* 0 copy rows, 1 scale output rows y0.. */\n'
     '\tint32_t y0;\n'
     '};\n'
     '\n'
     '/* Scaled presentation (sweetfb_scale=1): stage (logical size) -> panel. */\n'
     'static bool sweet_fb_scaled;\n'
     'static uint16_t *sweet_fb_xmap, *sweet_fb_ymap;  /* panel -> stage x / y */\n'
     'static uint32_t sweet_fb_out_w, sweet_fb_out_x0;\n'
     '\n'
     'static void\n'
     'sweet_fb_scale_rows(const struct sweet_fb_copy_job *j)\n'
     '{\n'
     '\tfor (int32_t y = j->y0; y < j->y0 + j->rows; y++) {\n'
     '\t\tuint32_t *out = (uint32_t *)(j->dst + (uint64_t)y * j->dstride) + sweet_fb_out_x0;\n'
     '\t\tif (y > j->y0 && sweet_fb_ymap[y] == sweet_fb_ymap[y - 1]) {\n'
     '\t\t\tmemcpy(out, (const uint32_t *)(j->dst + (uint64_t)(y - 1) * j->dstride) + sweet_fb_out_x0,\n'
     '\t\t\t    (size_t)sweet_fb_out_w * 4);\n'
     '\t\t\tcontinue;\n'
     '\t\t}\n'
     '\t\tconst uint32_t *in = (const uint32_t *)(j->src + (uint64_t)sweet_fb_ymap[y] * j->sstride);\n'
     '\t\tfor (uint32_t x = 0; x < sweet_fb_out_w; x++) {\n'
     '\t\t\tout[x] = in[sweet_fb_xmap[x]];\n'
     '\t\t}\n'
     '\t}\n'
     '}\n', 1),
    ('static void\n'
     'sweet_fb_copy_rows(const struct sweet_fb_copy_job *j)\n'
     '{\n',
     'static void\n'
     'sweet_fb_copy_rows(const struct sweet_fb_copy_job *j)\n'
     '{\n'
     '\tif (j->kind == 1) {\n'
     '\t\tsweet_fb_scale_rows(j);\n'
     '\t\treturn;\n'
     '\t}\n', 1),
    ('/* Copy rows x bytes, split over the helpers and the caller. */\n',
     '/* Scale the stage into panel rows [0, rows), split like sweet_fb_copy. */\n'
     'static void\n'
     'sweet_fb_scale(uintptr_t dst, uint64_t dstride, uintptr_t src, uint64_t sstride, int32_t rows)\n'
     '{\n'
     '\tif (sweet_fb_copy_lock == NULL) {\n'
     '\t\tstruct sweet_fb_copy_job all = { dst, src, dstride, sstride, 0, rows, 1, 0 };\n'
     '\t\tsweet_fb_scale_rows(&all);\n'
     '\t\treturn;\n'
     '\t}\n'
     '\tint32_t parts = SWEET_FB_COPY_HELPERS + 1;\n'
     '\tint32_t per = rows / parts, at = 0;\n'
     '\tIOLockLock(sweet_fb_copy_lock);\n'
     '\tfor (int32_t i = 0; i < SWEET_FB_COPY_HELPERS; i++, at += per) {\n'
     '\t\tsweet_fb_jobs[i] = (struct sweet_fb_copy_job){\n'
     '\t\t\tdst, src, dstride, sstride, 0, per, 1, at };\n'
     '\t}\n'
     '\tsweet_fb_copy_left = SWEET_FB_COPY_HELPERS;\n'
     '\tsweet_fb_copy_gen++;\n'
     '\tIOLockWakeup(sweet_fb_copy_lock, &sweet_fb_copy_gen, false);\n'
     '\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '\tstruct sweet_fb_copy_job mine = { dst, src, dstride, sstride, 0, rows - at, 1, at };\n'
     '\tsweet_fb_copy_rows(&mine);\n'
     '\tIOLockLock(sweet_fb_copy_lock);\n'
     '\twhile (sweet_fb_copy_left != 0) {\n'
     '\t\tIOLockSleep(sweet_fb_copy_lock, &sweet_fb_copy_left, THREAD_UNINT);\n'
     '\t}\n'
     '\tIOLockUnlock(sweet_fb_copy_lock);\n'
     '}\n'
     '\n'
     '/* Copy rows x bytes, split over the helpers and the caller. */\n', 1),
    ('\t\tsweet_fb_copy(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage, sweet_fb_stride,\n'
     '\t\t    sweet_fb_stride, sweet_fb_rows);\n',
     '\t\tif (sweet_fb_scaled) {\n'
     '\t\t\tsweet_fb_scale(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage,\n'
     '\t\t\t    (uint64_t)sweet_fb_stage_w * 4, sweet_fb_rows);\n'
     '\t\t} else {\n'
     '\t\t\tsweet_fb_copy(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage, sweet_fb_stride,\n'
     '\t\t\t    sweet_fb_stride, sweet_fb_rows);\n'
     '\t\t}\n', 1),
    ('static bool sweet_fb_stage_pending;\n',
     'static bool sweet_fb_stage_pending;\n'
     'static uint32_t sweet_fb_stage_w, sweet_fb_stage_h;\n', 1),
    # stage set-up: logical size when scaling
    ('\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)(fRowBytes * fHeight));\n'
     '\t\tthread_t t;\n'
     '\t\tif (stage != 0) {\n'
     '\t\t\tsweet_fb_copy(stage, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n',
     '\t\tint scale = 0;\n'
     '\t\tPE_parse_boot_argn("sweetfb_scale", &scale, sizeof(scale));\n'
     '\t\tsweet_fb_scaled = scale != 0 && (fLogicalW != fWidth || fLogicalH != fHeight) &&\n'
     '\t\t    fLogicalW <= fWidth && fLogicalH <= fHeight;\n'
     '\t\tsweet_fb_stage_w = sweet_fb_scaled ? fLogicalW : fWidth;\n'
     '\t\tsweet_fb_stage_h = sweet_fb_scaled ? fLogicalH : fHeight;\n'
     '\t\tuint64_t stage_bytes = sweet_fb_scaled ? (uint64_t)fLogicalW * 4 * fLogicalH :\n'
     '\t\t    (uint64_t)fRowBytes * fHeight;\n'
     '\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)stage_bytes);\n'
     '\t\tif (sweet_fb_scaled && stage != 0) {\n'
     '\t\t\tsweet_fb_out_w = fLogicalW * fHeight / fLogicalH;\n'
     '\t\t\tsweet_fb_out_x0 = (fWidth - sweet_fb_out_w) / 2;\n'
     '\t\t\tsweet_fb_xmap = (uint16_t *)IOMallocData(sweet_fb_out_w * sizeof(uint16_t));\n'
     '\t\t\tsweet_fb_ymap = (uint16_t *)IOMallocData(fHeight * sizeof(uint16_t));\n'
     '\t\t\tif (sweet_fb_xmap == NULL || sweet_fb_ymap == NULL) {\n'
     '\t\t\t\tsweet_fb_scaled = false;      /* (stage too small then: drop it) */\n'
     '\t\t\t\tIOFreeData((void *)stage, (vm_size_t)stage_bytes);\n'
     '\t\t\t\tstage = 0;\n'
     '\t\t\t} else {\n'
     '\t\t\t\tfor (uint32_t x = 0; x < sweet_fb_out_w; x++) {\n'
     '\t\t\t\t\tuint32_t sx = (2 * x + 1) * fLogicalW / (2 * sweet_fb_out_w);\n'
     '\t\t\t\t\tsweet_fb_xmap[x] = (uint16_t)(sx < fLogicalW ? sx : fLogicalW - 1);\n'
     '\t\t\t\t}\n'
     '\t\t\t\tfor (uint32_t y = 0; y < fHeight; y++) {\n'
     '\t\t\t\t\tuint32_t sy = (2 * y + 1) * fLogicalH / (2 * fHeight);\n'
     '\t\t\t\t\tsweet_fb_ymap[y] = (uint16_t)(sy < fLogicalH ? sy : fLogicalH - 1);\n'
     '\t\t\t\t}\n'
     '\t\t\t\tbzero((void *)stage, (size_t)stage_bytes);\n'
     '\t\t\t\tfor (uint32_t y = 0; y < fHeight; y++) {  /* black side bars */\n'
     '\t\t\t\t\tbzero((void *)(fPixels + (uint64_t)y * fRowBytes), (size_t)fRowBytes);\n'
     '\t\t\t\t}\n'
     '\t\t\t}\n'
     '\t\t}\n'
     '\t\tthread_t t;\n'
     '\t\tif (stage != 0) {\n'
     '\t\t\tif (!sweet_fb_scaled) {\n'
     '\t\t\t\tsweet_fb_copy(stage, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n'
     '\t\t\t}\n', 1),
    ('\t\t\t\tIOLog("SWEET FB: staged present, %llu bytes\\n", (uint64_t)fRowBytes * fHeight);\n',
     '\t\t\t\tIOLog("SWEET FB: staged present, stage %ux%u, %s\\n", sweet_fb_stage_w, sweet_fb_stage_h,\n'
     '\t\t\t\t    sweet_fb_scaled ? "scaled to the panel height" : "1:1");\n', 1),
    # copy targets: stage in logical coordinates when scaling
    ('\tuintptr_t panel = sweet_fb_stage != 0 ? sweet_fb_stage : fPixels;\n',
     '\tuintptr_t panel = sweet_fb_stage != 0 ? sweet_fb_stage : fPixels;\n'
     '\tbool logical = sweet_fb_stage != 0 && sweet_fb_scaled;\n'
     '\tint32_t offX = logical ? 0 : fOffX, offY = logical ? 0 : fOffY;\n'
     '\tint32_t tgtW = logical ? (int32_t)sweet_fb_stage_w : (int32_t)fWidth;\n'
     '\tint32_t tgtH = logical ? (int32_t)sweet_fb_stage_h : (int32_t)fHeight;\n'
     '\tuint64_t tgtStride = logical ? (uint64_t)sweet_fb_stage_w * 4 : fRowBytes;\n', 1),
    ('\t\t/* Logical (presented) display coordinates -> panel coordinates. */\n'
     '\t\tdx -= fOffX;\n'
     '\t\tdy -= fOffY;\n',
     '\t\t/* Logical (presented) display coordinates -> panel coordinates. */\n'
     '#if defined(DREAMLTE)\n'
     '\t\tdx -= offX;\n'
     '\t\tdy -= offY;\n'
     '#else\n'
     '\t\tdx -= fOffX;\n'
     '\t\tdy -= fOffY;\n'
     '#endif\n', 1),
    ('\t\tif (w > (int32_t)fWidth - dx) {\n'
     '\t\t\tw = (int32_t)fWidth - dx;\n'
     '\t\t}\n'
     '\t\tif (h > (int32_t)fHeight - dy) {\n'
     '\t\t\th = (int32_t)fHeight - dy;\n'
     '\t\t}\n',
     '#if defined(DREAMLTE)\n'
     '\t\tif (w > tgtW - dx) {\n'
     '\t\t\tw = tgtW - dx;\n'
     '\t\t}\n'
     '\t\tif (h > tgtH - dy) {\n'
     '\t\t\th = tgtH - dy;\n'
     '\t\t}\n'
     '#else\n'
     '\t\tif (w > (int32_t)fWidth - dx) {\n'
     '\t\t\tw = (int32_t)fWidth - dx;\n'
     '\t\t}\n'
     '\t\tif (h > (int32_t)fHeight - dy) {\n'
     '\t\t\th = (int32_t)fHeight - dy;\n'
     '\t\t}\n'
     '#endif\n', 1),
    ('\t\t\tsweet_fb_copy(panel + (uint64_t)dy * fRowBytes + (uint64_t)dx * 4, fRowBytes,\n',
     '\t\t\tsweet_fb_copy(panel + (uint64_t)dy * tgtStride + (uint64_t)dx * 4, tgtStride,\n', 1),
])

# Smoothness, step 4 (run p7: 1125x2436 scaled, still ~33 frames/s peak).
# The presenter held fPresentLock for its 15.5 ms scale, so the next SwapEnd
# waited for it (the 2.4 ms "snapshot" figure starts after the lock), and the
# scale wrote 4-byte pixels straight into write-combined panel memory.
# Now: two stage buffers with their own small lock (the render thread writes
# one while the presenter reads the other, and never waits for it), the
# snapshot is a single-threaded copy so the helper pool belongs to the
# presenter alone, and each scaled row is built in cached memory and written
# to the panel in one copy.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    # job: a cached row buffer per job
    ('\tint kind;        /* 0 copy rows, 1 scale output rows y0.. */\n'
     '\tint32_t y0;\n'
     '};\n',
     '\tint kind;        /* 0 copy rows, 1 scale output rows y0.. */\n'
     '\tint32_t y0;\n'
     '\tuint32_t *row;   /* scale: cached row of sweet_fb_out_w pixels */\n'
     '};\n'
     'static uint32_t *sweet_fb_rowbufs[4];\n', 1),
    ('\tfor (int32_t y = j->y0; y < j->y0 + j->rows; y++) {\n'
     '\t\tuint32_t *out = (uint32_t *)(j->dst + (uint64_t)y * j->dstride) + sweet_fb_out_x0;\n'
     '\t\tif (y > j->y0 && sweet_fb_ymap[y] == sweet_fb_ymap[y - 1]) {\n'
     '\t\t\tmemcpy(out, (const uint32_t *)(j->dst + (uint64_t)(y - 1) * j->dstride) + sweet_fb_out_x0,\n'
     '\t\t\t    (size_t)sweet_fb_out_w * 4);\n'
     '\t\t\tcontinue;\n'
     '\t\t}\n'
     '\t\tconst uint32_t *in = (const uint32_t *)(j->src + (uint64_t)sweet_fb_ymap[y] * j->sstride);\n'
     '\t\tfor (uint32_t x = 0; x < sweet_fb_out_w; x++) {\n'
     '\t\t\tout[x] = in[sweet_fb_xmap[x]];\n'
     '\t\t}\n'
     '\t}\n',
     '\tint32_t built = -1;      /* stage row now in j->row */\n'
     '\tfor (int32_t y = j->y0; y < j->y0 + j->rows; y++) {\n'
     '\t\tuint32_t *out = (uint32_t *)(j->dst + (uint64_t)y * j->dstride) + sweet_fb_out_x0;\n'
     '\t\tif (sweet_fb_ymap[y] != built) {\n'
     '\t\t\tconst uint32_t *in = (const uint32_t *)(j->src + (uint64_t)sweet_fb_ymap[y] * j->sstride);\n'
     '\t\t\tfor (uint32_t x = 0; x < sweet_fb_out_w; x++) {\n'
     '\t\t\t\tj->row[x] = in[sweet_fb_xmap[x]];\n'
     '\t\t\t}\n'
     '\t\t\tbuilt = sweet_fb_ymap[y];\n'
     '\t\t}\n'
     '\t\tmemcpy(out, j->row, (size_t)sweet_fb_out_w * 4);\n'
     '\t}\n', 1),
    ('\t\tsweet_fb_jobs[i] = (struct sweet_fb_copy_job){\n'
     '\t\t\tdst, src, dstride, sstride, 0, per, 1, at };\n',
     '\t\tsweet_fb_jobs[i] = (struct sweet_fb_copy_job){\n'
     '\t\t\tdst, src, dstride, sstride, 0, per, 1, at, sweet_fb_rowbufs[i] };\n', 1),
    ('\tstruct sweet_fb_copy_job mine = { dst, src, dstride, sstride, 0, rows - at, 1, at };\n',
     '\tstruct sweet_fb_copy_job mine = { dst, src, dstride, sstride, 0, rows - at, 1, at,\n'
     '\t\tsweet_fb_rowbufs[SWEET_FB_COPY_HELPERS] };\n', 1),
    ('\t\tstruct sweet_fb_copy_job all = { dst, src, dstride, sstride, 0, rows, 1, 0 };\n',
     '\t\tstruct sweet_fb_copy_job all = { dst, src, dstride, sstride, 0, rows, 1, 0,\n'
     '\t\t\tsweet_fb_rowbufs[0] };\n', 1),
    # two stages and their lock
    ('static uint32_t sweet_fb_stage_w, sweet_fb_stage_h;\n',
     'static uint32_t sweet_fb_stage_w, sweet_fb_stage_h;\n'
     'static IOLock *sweet_fb_stage_lock;      /* only around the indices below */\n'
     'static uintptr_t sweet_fb_stages[2];\n'
     'static int sweet_fb_ready = -1, sweet_fb_busy = -1;\n', 1),
    # presenter: takes the ready stage under the stage lock only
    ('\tfor (;;) {\n'
     '\t\tIOLockLock(sweet_fb_present_lock);\n'
     '\t\twhile (!sweet_fb_stage_pending) {\n'
     '\t\t\tIOLockSleep(sweet_fb_present_lock, &sweet_fb_stage_pending, THREAD_UNINT);\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_present_lock);\n'
     '\t\tuint64_t t0 = mach_absolute_time();\n'
     '\t\tsweet_fb_wait_frame_done();\n'
     '\t\tuint64_t t1 = mach_absolute_time();\n'
     '\t\tIOLockLock(sweet_fb_present_lock);\n'
     '\t\tsweet_fb_stage_pending = false;\n',
     '\tfor (;;) {\n'
     '\t\tIOLockLock(sweet_fb_stage_lock);\n'
     '\t\twhile (sweet_fb_ready < 0) {\n'
     '\t\t\tIOLockSleep(sweet_fb_stage_lock, &sweet_fb_ready, THREAD_UNINT);\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_stage_lock);\n'
     '\t\tuint64_t t0 = mach_absolute_time();\n'
     '\t\tsweet_fb_wait_frame_done();\n'
     '\t\tuint64_t t1 = mach_absolute_time();\n'
     '\t\tIOLockLock(sweet_fb_stage_lock);\n'
     '\t\tint b = sweet_fb_ready;\n'
     '\t\tsweet_fb_ready = -1;\n'
     '\t\tsweet_fb_busy = b;\n'
     '\t\tIOLockUnlock(sweet_fb_stage_lock);\n'
     '\t\tif (b < 0) {\n'
     '\t\t\tcontinue;\n'
     '\t\t}\n'
     '\t\tsweet_fb_stage = sweet_fb_stages[b];\n', 1),
    ('\t\t\tsweet_fb_copy(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage, sweet_fb_stride,\n'
     '\t\t\t    sweet_fb_stride, sweet_fb_rows);\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_present_lock);\n',
     '\t\t\tsweet_fb_copy(sweet_fb_panel, sweet_fb_stride, sweet_fb_stage, sweet_fb_stride,\n'
     '\t\t\t    sweet_fb_stride, sweet_fb_rows);\n'
     '\t\t}\n'
     '\t\tIOLockLock(sweet_fb_stage_lock);\n'
     '\t\tsweet_fb_busy = -1;\n'
     '\t\tIOLockUnlock(sweet_fb_stage_lock);\n', 1),
    # stage set-up: two buffers, row buffers, the stage lock
    ('\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)stage_bytes);\n',
     '\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)stage_bytes);\n'
     '\t\tuintptr_t stage2 = stage ? (uintptr_t)IOMallocData((vm_size_t)stage_bytes) : 0;\n'
     '\t\tsweet_fb_stage_lock = IOLockAlloc();\n'
     '\t\tif (stage2 == 0 || sweet_fb_stage_lock == NULL) {\n'
     '\t\t\tif (stage != 0) {\n'
     '\t\t\t\tIOFreeData((void *)stage, (vm_size_t)stage_bytes);\n'
     '\t\t\t}\n'
     '\t\t\tstage = 0;\n'
     '\t\t}\n', 1),
    ('\t\t\tsweet_fb_ymap = (uint16_t *)IOMallocData(fHeight * sizeof(uint16_t));\n'
     '\t\t\tif (sweet_fb_xmap == NULL || sweet_fb_ymap == NULL) {\n',
     '\t\t\tsweet_fb_ymap = (uint16_t *)IOMallocData(fHeight * sizeof(uint16_t));\n'
     '\t\t\tbool rows_ok = true;\n'
     '\t\t\tfor (int i = 0; i <= SWEET_FB_COPY_HELPERS; i++) {\n'
     '\t\t\t\tsweet_fb_rowbufs[i] = (uint32_t *)IOMallocData(sweet_fb_out_w * 4);\n'
     '\t\t\t\trows_ok = rows_ok && sweet_fb_rowbufs[i] != NULL;\n'
     '\t\t\t}\n'
     '\t\t\tif (sweet_fb_xmap == NULL || sweet_fb_ymap == NULL || !rows_ok) {\n', 1),
    ('\t\t\t\tIOFreeData((void *)stage, (vm_size_t)stage_bytes);\n'
     '\t\t\t\tstage = 0;\n'
     '\t\t\t} else {\n',
     '\t\t\t\tIOFreeData((void *)stage, (vm_size_t)stage_bytes);\n'
     '\t\t\t\tIOFreeData((void *)stage2, (vm_size_t)stage_bytes);\n'
     '\t\t\t\tstage = 0;\n'
     '\t\t\t} else {\n', 1),
    ('\t\t\t\tbzero((void *)stage, (size_t)stage_bytes);\n',
     '\t\t\t\tbzero((void *)stage, (size_t)stage_bytes);\n'
     '\t\t\t\tbzero((void *)stage2, (size_t)stage_bytes);\n', 1),
    ('\t\t\tif (!sweet_fb_scaled) {\n'
     '\t\t\t\tsweet_fb_copy(stage, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n'
     '\t\t\t}\n',
     '\t\t\tif (!sweet_fb_scaled) {\n'
     '\t\t\t\tsweet_fb_copy(stage, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n'
     '\t\t\t\tsweet_fb_copy(stage2, fRowBytes, fPixels, fRowBytes, fRowBytes, (int32_t)fHeight);\n'
     '\t\t\t}\n'
     '\t\t\tsweet_fb_stages[0] = stage;\n'
     '\t\t\tsweet_fb_stages[1] = stage2;\n', 1),
    # present: pick the stage the presenter is not reading
    ('\tuintptr_t panel = sweet_fb_stage != 0 ? sweet_fb_stage : fPixels;\n',
     '\tint slot = -1;\n'
     '\tif (sweet_fb_stage != 0) {\n'
     '\t\tIOLockLock(sweet_fb_stage_lock);\n'
     '\t\tslot = sweet_fb_busy == 0 ? 1 : (sweet_fb_busy == 1 ? 0 : (sweet_fb_ready == 0 ? 1 : 0));\n'
     '\t\tif (sweet_fb_ready == slot) {\n'
     '\t\t\tsweet_fb_ready = -1;        /* replaced by this newer frame */\n'
     '\t\t}\n'
     '\t\tIOLockUnlock(sweet_fb_stage_lock);\n'
     '\t}\n'
     '\tuintptr_t panel = slot >= 0 ? sweet_fb_stages[slot] : fPixels;\n', 1),
    ('\t\t\tsweet_fb_copy(panel + (uint64_t)dy * tgtStride + (uint64_t)dx * 4, tgtStride,\n'
     '\t\t\t    src + s->offset + (uint64_t)sy * s->bytesPerRow + (uint64_t)sx * 4,\n'
     '\t\t\t    s->bytesPerRow, (uint64_t)w * 4, h);\n',
     '\t\t\tif (sweet_fb_stage != 0) {\n'
     '\t\t\t\t/* single-threaded: the helper pool belongs to the presenter */\n'
     '\t\t\t\tstruct sweet_fb_copy_job snap = {\n'
     '\t\t\t\t\tpanel + (uint64_t)dy * tgtStride + (uint64_t)dx * 4,\n'
     '\t\t\t\t\tsrc + s->offset + (uint64_t)sy * s->bytesPerRow + (uint64_t)sx * 4,\n'
     '\t\t\t\t\ttgtStride, s->bytesPerRow, (uint64_t)w * 4, h };\n'
     '\t\t\t\tsweet_fb_copy_rows(&snap);\n'
     '\t\t\t} else {\n'
     '\t\t\t\tsweet_fb_copy(panel + (uint64_t)dy * tgtStride + (uint64_t)dx * 4, tgtStride,\n'
     '\t\t\t\t    src + s->offset + (uint64_t)sy * s->bytesPerRow + (uint64_t)sx * 4,\n'
     '\t\t\t\t    s->bytesPerRow, (uint64_t)w * 4, h);\n'
     '\t\t\t}\n', 1),
    ('\tif (sweet_fb_stage != 0) {\n'
     '\t\tsweet_fb_stage_pending = true;\n'
     '\t\tIOLockWakeup(fPresentLock, &sweet_fb_stage_pending, false);\n'
     '\t}\n',
     '\tif (slot >= 0) {\n'
     '\t\tIOLockLock(sweet_fb_stage_lock);\n'
     '\t\tsweet_fb_ready = slot;\n'
     '\t\tIOLockWakeup(sweet_fb_stage_lock, &sweet_fb_ready, false);\n'
     '\t\tIOLockUnlock(sweet_fb_stage_lock);\n'
     '\t}\n', 1),
])

# Smoothness, step 5 (run p8: ~50 frames/s rendered, the panel ~42/s,
# limited by the presenter's 15 ms scale). The column map made every pixel a
# dependent load (map, then pixel) on in-order A53s; kernel code has no NEON.
# Step through the source row in 16.16 fixed point, four pixels at a time.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('static uint32_t sweet_fb_out_w, sweet_fb_out_x0;\n',
     'static uint32_t sweet_fb_out_w, sweet_fb_out_x0;\n'
     'static uint32_t sweet_fb_xstep;         /* 16.16 stage pixels per panel pixel */\n', 1),
    ('\t\t\tconst uint32_t *in = (const uint32_t *)(j->src + (uint64_t)sweet_fb_ymap[y] * j->sstride);\n'
     '\t\t\tfor (uint32_t x = 0; x < sweet_fb_out_w; x++) {\n'
     '\t\t\t\tj->row[x] = in[sweet_fb_xmap[x]];\n'
     '\t\t\t}\n',
     '\t\t\tconst uint32_t *in = (const uint32_t *)(j->src + (uint64_t)sweet_fb_ymap[y] * j->sstride);\n'
     '\t\t\tuint32_t *r = j->row, n = sweet_fb_out_w, step = sweet_fb_xstep;\n'
     '\t\t\tuint32_t acc = step / 2, x = 0;\n'
     '\t\t\tfor (; x + 4 <= n; x += 4) {\n'
     '\t\t\t\tuint32_t p0 = in[acc >> 16], p1 = in[(acc + step) >> 16];\n'
     '\t\t\t\tuint32_t p2 = in[(acc + 2 * step) >> 16], p3 = in[(acc + 3 * step) >> 16];\n'
     '\t\t\t\tacc += 4 * step;\n'
     '\t\t\t\tr[x] = p0;\n'
     '\t\t\t\tr[x + 1] = p1;\n'
     '\t\t\t\tr[x + 2] = p2;\n'
     '\t\t\t\tr[x + 3] = p3;\n'
     '\t\t\t}\n'
     '\t\t\tfor (; x < n; x++, acc += step) {\n'
     '\t\t\t\tr[x] = in[acc >> 16];\n'
     '\t\t\t}\n', 1),
    ('\t\t\tsweet_fb_out_x0 = (fWidth - sweet_fb_out_w) / 2;\n',
     '\t\t\tsweet_fb_out_x0 = (fWidth - sweet_fb_out_w) / 2;\n'
     '\t\t\tsweet_fb_xstep = (fLogicalW << 16) / sweet_fb_out_w;\n', 1),
])

# Clock per core: K2c ran all eight cores, but nobody knows the Mongoose
# clock (CMU_CPUCL0 was never readable with the cluster off). Each core
# counts PMCCNTR cycles over 10 ms of the 26 MHz timebase in initCPU;
# startAll logs it next to "came alive".
edit('iokit/Kernel/arm/SweetCPU.cpp', [
    ('OSDefineMetaClassAndStructors(SweetCPU, IOCPU);\n',
     'OSDefineMetaClassAndStructors(SweetCPU, IOCPU);\n'
     '\n'
     '#if defined(DREAMLTE)\n'
     'static uint32_t sweet_cpu_mhz[SWEET_SMP_MAX_CPUS];\n'
     '\n'
     'static uint32_t\n'
     'sweet_measure_mhz(void)\n'
     '{\n'
     '\tuint64_t pmcr = __builtin_arm_rsr64("PMCR_EL0");\n'
     '\t__builtin_arm_wsr64("PMCCFILTR_EL0", 0);         /* count at EL0 and EL1 */\n'
     '\t__builtin_arm_wsr64("PMCNTENSET_EL0", 1ULL << 31); /* cycle counter */\n'
     '\t__builtin_arm_wsr64("PMCR_EL0", pmcr | 1 | 4);   /* enable, reset it */\n'
     '\t__builtin_arm_isb(ISB_SY);\n'
     '\tuint64_t t0 = mach_absolute_time();\n'
     '\tuint64_t c0 = __builtin_arm_rsr64("PMCCNTR_EL0");\n'
     '\twhile (mach_absolute_time() - t0 < 260000) {      /* 10 ms at 26 MHz */\n'
     '\t}\n'
     '\tuint64_t c1 = __builtin_arm_rsr64("PMCCNTR_EL0");\n'
     '\treturn (uint32_t)((c1 - c0) / 10000);\n'
     '}\n'
     '#endif\n', 1),
    ('\t__atomic_store_n(&initialized, 1, __ATOMIC_RELEASE);\n}\n',
     '#if defined(DREAMLTE)\n'
     '\tif (getCPUNumber() < SWEET_SMP_MAX_CPUS) {\n'
     '\t\tsweet_cpu_mhz[getCPUNumber()] = sweet_measure_mhz();\n'
     '\t}\n'
     '#endif\n'
     '\t__atomic_store_n(&initialized, 1, __ATOMIC_RELEASE);\n}\n', 1),
    ('\t\tIOLog(CPU_PORT_NAME " CPU: cpu=%u mpidr=0x%x came alive; SGI1 OK\\n",\n'
     '\t\t    i, topology->cpus[i].phys_id);\n',
     '#if defined(DREAMLTE)\n'
     '\t\tIOLog(CPU_PORT_NAME " CPU: cpu=%u mpidr=0x%x came alive; SGI1 OK; %u MHz\\n",\n'
     '\t\t    i, topology->cpus[i].phys_id, sweet_cpu_mhz[i]);\n'
     '#else\n'
     '\t\tIOLog(CPU_PORT_NAME " CPU: cpu=%u mpidr=0x%x came alive; SGI1 OK\\n",\n'
     '\t\t    i, topology->cpus[i].phys_id);\n'
     '#endif\n', 1),
])

# K2b (cpus=8): with the A53 and Mongoose cores in two clusters (two
# scheduler psets) the first secondary panicked "Ticket lock ... is
# unexpectedly owned" on pset0's lock (pset0 + 0x108) as it came online; the
# two-pset path was never exercised on these boards (K1, one cluster, is
# fine). Put every core in logical cluster 0 (one pset, plain SMP
# scheduling). The physical cluster (MPIDR Aff1) still gets its slot in
# cluster_offsets for MPIDR-indexed per-CPU data.
edit('osfmk/arm64/machine_routines.c', [
    ('\t\tcpu->cluster_id = ((cluster_phys_to_logical[phys_cluster_id] == -1) ?\n'
     '\t\t    topology_info.num_clusters : cluster_phys_to_logical[phys_cluster_id]);\n',
     '#if defined(DREAMLTE)\n'
     '\t\tcpu->cluster_id = 0;\n'
     '#else\n'
     '\t\tcpu->cluster_id = ((cluster_phys_to_logical[phys_cluster_id] == -1) ?\n'
     '\t\t    topology_info.num_clusters : cluster_phys_to_logical[phys_cluster_id]);\n'
     '#endif\n', 1),
    ('\t\tcluster->num_cpus++;\n\t\tcluster->cpu_mask |= 1ULL << cpu->cpu_id;\n',
     '#if defined(DREAMLTE)\n'
     '\t\tcluster_phys_to_logical[phys_cluster_id] = 0;\n'
     '#endif\n'
     '\t\tcluster->num_cpus++;\n\t\tcluster->cpu_mask |= 1ULL << cpu->cpu_id;\n', 1),
])

# Test cycles without anyone at the phone: s8autoreset=N makes the kernel
# reset straight into TWRP N seconds after the UFS log starts, after giving
# the log thread time to flush (it writes once a second). Same registers as
# Samsung's sec_reboot.c: INFORM2 = POWER_RESET, INFORM3 = REASON_RECOVERY,
# PMU SWRESET. Off unless the boot-arg is given.
edit('bsd/dev/sweet_ufs.c', [
    ('static void\nsweet_log_start(void)\n{\n',
     'static uint32_t s8_autoreset_secs, s8_autoreset_direct;\n'
     'extern uint32_t s8_restart_to_recovery;   /* pexpert/arm/pe_serial.c */\n'
     'extern int reboot_kernel(int howto, char *message);\n'
     '\n'
     'static void\n'
     's8_autoreset_thread(__unused void *arg, __unused wait_result_t wr)\n'
     '{\n'
     '\tint chan;\n'
     '\n'
     '\t(void)tsleep(&chan, PZERO, "s8reset", (int)s8_autoreset_secs * hz);\n'
     '\tprintf("S8 AUTORESET: %u s, resetting to recovery after the log flush\\n",\n'
     '\t    s8_autoreset_secs);\n'
     '\t(void)tsleep(&chan, PZERO, "s8reset", 3 * hz);\n'
     '\t/* Clean shutdown (sync, unmount: the HFS+ journal stays empty, so\n'
     '\t * the root can be edited offline), then s8_halt_restart resets into\n'
     '\t * recovery. This thread is the fallback if that never finishes. */\n'
     '\tif (!s8_autoreset_direct) {\n'
     '\t\tthread_t fallback;\n'
     '\t\ts8_autoreset_direct = 1;\n'
     '\t\tif (kernel_thread_start(s8_autoreset_thread, NULL, &fallback) == KERN_SUCCESS) {\n'
     '\t\t\tthread_deallocate(fallback);\n'
     '\t\t}\n'
     '\t\ts8_restart_to_recovery = 1;\n'
     '\t\t(void)reboot_kernel(0, (char *)"s8autoreset");\n'
     '\t\tfor (;;) {\n'
     '\t\t\t(void)tsleep(&chan, PZERO, "s8reset", hz);\n'
     '\t\t}\n'
     '\t}\n'
     '\t(void)tsleep(&chan, PZERO, "s8reset", 30 * hz);\n'
     '\tprintf("S8 AUTORESET: clean shutdown did not finish, resetting directly\\n");\n'
     '\tvolatile uint32_t *pmu = (volatile uint32_t *)ml_io_map(0x16480000, 0x1000);\n'
     '\tpmu[0x808 / 4] = 0x12345678;       /* INFORM2: SEC_POWER_RESET */\n'
     '\tpmu[0x80c / 4] = 0x12345674;       /* INFORM3: REASON_RECOVERY */\n'
     '\t__asm__ volatile ("dsb sy" ::: "memory");\n'
     '\tpmu[0x400 / 4] = 1;                /* SWRESET */\n'
     '\tfor (;;) {\n'
     '\t\t(void)tsleep(&chan, PZERO, "s8reset", hz);\n'
     '\t}\n'
     '}\n'
     '\n'
     'static void\nsweet_log_start(void)\n{\n'
     '\tthread_t reset_thread;\n'
     '\n'
     '\tif (PE_parse_boot_argn("s8autoreset", &s8_autoreset_secs, sizeof(s8_autoreset_secs)) &&\n'
     '\t    s8_autoreset_secs != 0 &&\n'
     '\t    kernel_thread_start(s8_autoreset_thread, NULL, &reset_thread) == KERN_SUCCESS) {\n'
     '\t\tthread_deallocate(reset_thread);\n'
     '\t}\n', 1),
])

edit('bsd/dev/a5xelte_keys.c', [
    ('#include <pexpert/pexpert.h>\n',
     '#include <pexpert/pexpert.h>\n#include <pexpert/arm64/board_config.h>\n', 1),
    ('#define A5_ALIVE_PA 0x139b0000u\n',
     '#if defined(DREAMLTE)\n'
     '#define A5_ALIVE_PA 0x164b0000u            /* Exynos 8895 pinctrl ALIVE */\n'
     '#else\n'
     '#define A5_ALIVE_PA 0x139b0000u\n'
     '#endif\n', 1),
    ('static void\na5_keys_wait(void)\n',
     '#if defined(DREAMLTE)\n'
     '/*\n'
     ' * Galaxy S8 (mainline exynos8895-dreamlte.dts gpio-keys, all active low):\n'
     ' * Power GPA2-4, Volume Up GPA0-3, Volume Down GPA0-4, Bixby GPA0-6 (used\n'
     ' * as Home). Bank offsets per mainline pinctrl-exynos-arm64.c\n'
     ' * (exynos8895_pin_banks0): GPA0 0x020, GPA2 0x060; DAT at +4. Boot 22/23\n'
     ' * read 0x044 (GPA1 DAT) and saw nothing. Sample = GPA0 | GPA2 << 8.\n'
     ' */\n'
     'typedef uint16_t keys_t;\n'
     '#define KEYS_SAMPLE() ((keys_t)((a5_keys_read(0x24) & 0xff) | (a5_keys_read(0x64) & 0xff) << 8))\n'
     '#define KEYS_PINS { 12, 3, 4, 6 }\n'
     '#else\n'
     'typedef uint8_t keys_t;\n'
     '#define KEYS_SAMPLE() ((keys_t)a5_keys_read(A5_GPA2_DAT))\n'
     '#define KEYS_PINS { 7, 0, 1, 5 }\n'
     '#endif\n'
     '\n'
     'static void\na5_keys_wait(void)\n', 1),
    ('\tstatic const uint8_t pins[4] = {7, 0, 1, 5};\n'
     '\tuint8_t stable = (uint8_t)a5_keys_read(A5_GPA2_DAT);\n'
     '\tuint8_t previous = stable;\n',
     '\tstatic const uint8_t pins[4] = KEYS_PINS;\n'
     '\tkeys_t stable = KEYS_SAMPLE();\n'
     '\tkeys_t previous = stable;\n', 1),
    ('\t\tuint8_t sample = (uint8_t)a5_keys_read(A5_GPA2_DAT);\n',
     '\t\tkeys_t sample = KEYS_SAMPLE();\n', 1),
    ('\t\t\t\tuint8_t bit = 1u << pins[key];\n',
     '\t\t\t\tkeys_t bit = (keys_t)(1u << pins[key]);\n', 1),
    ('\tint enabled = 1;\n\tif (a5_keys_started) {',
     '\tint enabled = A5_KEYS_DEFAULT;\n\tif (a5_keys_started) {', 1),
])

# CPU clocks through the APM firmware (ACPM), as Samsung's cpufreq does:
# its cal-ids are ACPM vclks and cal_dfs_set_rate sends "FREQ_REQ id kHz"
# over the AP<->APM mailbox; the firmware sets the BUCK from its ASV table,
# then the PLL. Protocol and sources: shim/dreamlte/pmic.c acpm_cpu_clocks,
# which sets the A53s before XNU (CMU_CPUCL0 is in the Mongoose power domain,
# so Mongoose is set here, once its cores run). A thermal guard follows
# Samsung's trips (DT mngs-thermal: passive 83 C, hot 115 C).
S8_DVFS = r'''
/*
 * s8big= / s8lit= (kHz, an ECT level) set the cluster targets. TMU (early
 * TMU block 0x10080000, exynos-earlytmu.c / exynos_tmu.c): sensor s code in
 * CURRENT_TEMP at 0x40 + ..., trim in TRIMINFO + 4 * s, two-point 25/85 C.
 * Guard: >= 80 C one level down per second, <= 70 C one level back up per
 * 5 s, >= 95 C or an implausible reading: both clusters to the S-Boot
 * clocks (1066 / 1053 MHz) and the guard stops.
 */
#define S8_TMU_BASE		0x10080000
#define S8_ACPM_MBOX		0x16440000
#define S8_ACPM_SRAM		0x16500000
#define S8_ACPM_SRAM_SIZE	0xb400U
#define S8_ACPM_INITDATA	0x2850U
#define S8_ACPM_CH_DVFS		0       /* CMU node clock-controller@0x15a80000 */
#define S8_DVFS_BIG		2       /* dvfs_cpucl0, Mongoose */
#define S8_DVFS_LIT		3       /* dvfs_cpucl1, A53 */
#define S8_FREQ_REQ		0
#define S8_FREQ_GET		1

static volatile uint8_t *s8_mbox, *s8_sram, *s8_tmu, *s8_cmu0, *s8_cmu1;
static uint32_t s8_ch, s8_seq;

static const uint32_t s8_big_levels[] = {
	2314000, 2158000, 2002000, 1937000, 1807000, 1703000, 1469000,
	1261000, 1170000, 1066000, 962000, 858000, 741000,
};
static const uint32_t s8_lit_levels[] = {
	1690000, 1456000, 1248000, 1053000, 949000, 832000, 715000, 598000, 455000,
};
#define S8_NBIG ((int)(sizeof(s8_big_levels) / sizeof(s8_big_levels[0])))
#define S8_NLIT ((int)(sizeof(s8_lit_levels) / sizeof(s8_lit_levels[0])))
#define S8_BIG_BOOT 9                   /* 1066 MHz */
#define S8_LIT_BOOT 3                   /* 1053 MHz */

static inline uint32_t
s8_rd(volatile uint8_t *b, uint32_t off)
{
	return *(volatile uint32_t *)(b + off);
}

static inline void
s8_wr(volatile uint8_t *b, uint32_t off, uint32_t v)
{
	*(volatile uint32_t *)(b + off) = v;
}

static bool
s8_sram_ok(uint32_t off, uint32_t len)
{
	return off < S8_ACPM_SRAM_SIZE && len <= S8_ACPM_SRAM_SIZE - off;
}

/* struct ipc_channel (72 bytes): id 0, channel_info from 16 (rx_rear,
 * rx_front, rx_base at 16/20/24; tx_rear, tx_front, tx_base at 40/44/48;
 * q_len 52, q_elem_size 56). APM's RX queue is our TX queue. */
static bool
s8_acpm_find(void)
{
	uint32_t chans = s8_rd(s8_sram, S8_ACPM_INITDATA + 0x08);
	uint32_t n = s8_rd(s8_sram, S8_ACPM_INITDATA + 0x18);
	if (n == 0 || n > 32 || !s8_sram_ok(chans, n * 72)) {
		return false;
	}
	for (uint32_t i = 0; i < n; i++) {
		uint32_t c = chans + i * 72;
		if (s8_rd(s8_sram, c) != S8_ACPM_CH_DVFS) {
			continue;
		}
		uint32_t len = s8_rd(s8_sram, c + 52), elem = s8_rd(s8_sram, c + 56);
		if (len < 1 || len > 64 || elem < 16 || elem > 64 || (elem & 3) ||
		    !s8_sram_ok(s8_rd(s8_sram, c + 24), len * elem) ||
		    !s8_sram_ok(s8_rd(s8_sram, c + 48), len * elem)) {
			return false;
		}
		if (!s8_sram_ok(s8_rd(s8_sram, c + 16), 4) || !s8_sram_ok(s8_rd(s8_sram, c + 20), 4) ||
		    !s8_sram_ok(s8_rd(s8_sram, c + 40), 4) || !s8_sram_ok(s8_rd(s8_sram, c + 44), 4)) {
			return false;
		}
		s8_ch = c;
		return true;
	}
	return false;
}

/* One-slot buffer channels (type 2): Samsung writes the AP slot, raises the
 * APM interrupt and takes the answer from the APM slot in its interrupt
 * thread. Polled here. (DVFS channel 0 is a queue; kept for completeness.) */
static int
s8_acpm_send_buffer(uint32_t cmd[4])
{
	uint32_t c = s8_ch, elem = s8_rd(s8_sram, c + 56);
	if (++s8_seq >= 64) {
		s8_seq = 1;
	}
	uint32_t seq = s8_seq;
	cmd[0] |= seq << 16;
	s8_wr(s8_mbox, 0x20, 1u << S8_ACPM_CH_DVFS);               /* INTCR1 */
	uint32_t slot = s8_rd(s8_sram, c + 24);
	for (uint32_t i = 0; i < elem / 4; i++) {
		s8_wr(s8_sram, slot + 4 * i, i < 4 ? cmd[i] : 0);
	}
	__builtin_arm_dsb(DSB_SY);
	s8_wr(s8_mbox, 0x08, (1u << S8_ACPM_CH_DVFS) << 16);      /* INTGR0 */
	uint32_t r = s8_rd(s8_sram, c + 48);
	uint64_t t0 = mach_absolute_time();
	while (mach_absolute_time() - t0 < 26000000 / 20) {       /* 50 ms */
		if (!(s8_rd(s8_mbox, 0x28) & (1u << S8_ACPM_CH_DVFS))) {  /* INTSR1 */
			continue;
		}
		if (((s8_rd(s8_sram, r) >> 16) & 0x3f) != seq) {
			s8_wr(s8_mbox, 0x20, 1u << S8_ACPM_CH_DVFS);
			continue;
		}
		for (int k = 0; k < 4; k++) {
			cmd[k] = s8_rd(s8_sram, r + 4 * k);
		}
		s8_wr(s8_mbox, 0x20, 1u << S8_ACPM_CH_DVFS);
		return 0;
	}
	return -2;
}

/* acpm_ipc_send_data + check_response, polled; cmd[1] carries the answer. */
static int
s8_acpm_send(uint32_t cmd[4])
{
	uint32_t c = s8_ch;
	if (s8_rd(s8_sram, c + 12) == 2) {
		return s8_acpm_send_buffer(cmd);
	}
	uint32_t len = s8_rd(s8_sram, c + 52), elem = s8_rd(s8_sram, c + 56);
	uint32_t front = s8_rd(s8_sram, s8_rd(s8_sram, c + 20)), next = (front + 1) % len;
	if (front >= len || next == s8_rd(s8_sram, s8_rd(s8_sram, c + 16))) {
		return -1;
	}
	if (++s8_seq >= 64) {
		s8_seq = 1;
	}
	uint32_t seq = s8_seq;
	cmd[0] |= seq << 16;
	uint32_t slot = s8_rd(s8_sram, c + 24) + front * elem;
	for (uint32_t i = 0; i < elem / 4; i++) {
		s8_wr(s8_sram, slot + 4 * i, i < 4 ? cmd[i] : 0);
	}
	__builtin_arm_dsb(DSB_SY);
	s8_wr(s8_sram, s8_rd(s8_sram, c + 20), next);
	__builtin_arm_dsb(DSB_SY);
	s8_wr(s8_mbox, 0x08, (1u << S8_ACPM_CH_DVFS) << 16);      /* INTGR0 */

	uint64_t t0 = mach_absolute_time();
	while (mach_absolute_time() - t0 < 26000000 / 20) {       /* 50 ms */
		if (!(s8_rd(s8_mbox, 0x28) & (1u << S8_ACPM_CH_DVFS))) {  /* INTSR1 */
			continue;
		}
		uint32_t base = s8_rd(s8_sram, c + 48);
		uint32_t rear = s8_rd(s8_sram, s8_rd(s8_sram, c + 40));
		uint32_t f = s8_rd(s8_sram, s8_rd(s8_sram, c + 44));
		if (rear >= len || f >= len) {
			return -3;
		}
		for (uint32_t i = rear; i != f; i = (i + 1) % len) {
			uint32_t r = base + i * elem;
			if (((s8_rd(s8_sram, r) >> 16) & 0x3f) != seq) {
				continue;
			}
			for (int k = 0; k < 4; k++) {
				cmd[k] = s8_rd(s8_sram, r + 4 * k);
			}
			if (i != rear) {
				for (uint32_t k = 0; k < elem / 4; k++) {
					s8_wr(s8_sram, r + 4 * k, s8_rd(s8_sram, base + rear * elem + 4 * k));
				}
			}
			rear = (rear + 1) % len;
			s8_wr(s8_sram, s8_rd(s8_sram, c + 40), rear);
			if (rear == s8_rd(s8_sram, s8_rd(s8_sram, c + 44))) {
				s8_wr(s8_mbox, 0x20, 1u << S8_ACPM_CH_DVFS);       /* INTCR1 */
			}
			return 0;
		}
	}
	return -2;
}

static int
s8_acpm_freq(uint32_t id, uint32_t op, uint32_t khz, uint32_t *ans)
{
	uint32_t cmd[4] = { id, khz, op, 0 };
	int rc = s8_acpm_send(cmd);
	*ans = cmd[1];
	return rc;
}

static uint32_t
s8_pll_mhz(volatile uint8_t *cmu)
{
	uint32_t v = s8_rd(cmu, 0x120);
	uint32_t m = (v >> 16) & 0x3ff, p = (v >> 8) & 0x3f, s = v & 7;
	return p ? (uint32_t)((26ULL * m / p) >> s) : 0;
}

/* Hottest sensor in C (MNGS 0, 2-5; APOLLO 1), or 0 if any reads implausibly. */
static int
s8_tmu_temp(void)
{
	uint32_t two_point = (s8_rd(s8_tmu, 0) >> 23) & 1;
	int hot = 0;
	for (uint32_t s = 0; s < 6; s++) {
		uint32_t trim = s8_rd(s8_tmu, 4 * s);
		int e1 = (int)(trim & 0x1ff), e2 = (int)((trim >> 9) & 0x1ff);
		uint32_t off = s < 2 ? 0 : ((s - 2) / 3 + 1) * 4;
		uint32_t bit = 9 * (s < 2 ? s : (s - 2) % 3);
		int code = (int)((s8_rd(s8_tmu, 0x40 + off) >> bit) & 0x1ff);
		if (e1 == 0 || (two_point && e2 <= e1)) {
			return 0;
		}
		int t = two_point ? (code - e1) * (85 - 25) / (e2 - e1) + 25 : code - e1 + 25;
		if (t < 5 || t > 125) {
			return 0;
		}
		hot = t > hot ? t : hot;
	}
	return hot;
}

static int
s8_level(const uint32_t *levels, int n, uint32_t khz)
{
	for (int i = 0; i < n; i++) {
		if (levels[i] == khz) {
			return i;
		}
	}
	return -1;
}

static void
s8_dvfs_set(int big, int lit, int *cur_big, int *cur_lit)
{
	uint32_t ans;
	if (big != *cur_big) {
		int rc = s8_acpm_freq(S8_DVFS_BIG, S8_FREQ_REQ, s8_big_levels[big], &ans);
		if (rc == 0) {
			*cur_big = big;
		} else {
			IOLog("S8 DVFS: big %u kHz failed %d\n", s8_big_levels[big], rc);
		}
	}
	if (lit != *cur_lit) {
		int rc = s8_acpm_freq(S8_DVFS_LIT, S8_FREQ_REQ, s8_lit_levels[lit], &ans);
		if (rc == 0) {
			*cur_lit = lit;
		} else {
			IOLog("S8 DVFS: lit %u kHz failed %d\n", s8_lit_levels[lit], rc);
		}
	}
}

static void
s8_dvfs_thread(void *arg __unused, wait_result_t wr __unused)
{
	uint32_t big_khz = 0, lit_khz = 0, fbig = 0, flit = 0;
	PE_parse_boot_argn("s8big", &big_khz, sizeof(big_khz));
	PE_parse_boot_argn("s8lit", &lit_khz, sizeof(lit_khz));
	s8_mbox = (volatile uint8_t *)ml_io_map(S8_ACPM_MBOX, 0x1000);
	s8_sram = (volatile uint8_t *)ml_io_map(S8_ACPM_SRAM, S8_ACPM_SRAM_SIZE);
	s8_tmu = (volatile uint8_t *)ml_io_map(S8_TMU_BASE, 0x1000);
	s8_cmu0 = (volatile uint8_t *)ml_io_map(0x16800000, 0x1000);
	s8_cmu1 = (volatile uint8_t *)ml_io_map(0x16900000, 0x1000);
	if (!s8_acpm_find()) {
		IOLog("S8 DVFS: no ACPM DVFS channel, clocks unchanged\n");
		thread_terminate(current_thread());
		return;
	}
	/* FREQ_GET answers 0 (run c10), so the PLLs tell the current level. */
	fbig = s8_pll_mhz(s8_cmu0) * 1000;
	flit = s8_pll_mhz(s8_cmu1) * 1000;
	int temp = s8_tmu_temp();
	IOLog("S8 DVFS: PLL %u / %u kHz; TMU %d C (trim0 0x%x temp 0x%x 0x%x); target %u / %u\n",
	    fbig, flit, temp, s8_rd(s8_tmu, 0), s8_rd(s8_tmu, 0x40), s8_rd(s8_tmu, 0x44),
	    big_khz, lit_khz);
	int cur_big = s8_level(s8_big_levels, S8_NBIG, fbig);
	int cur_lit = s8_level(s8_lit_levels, S8_NLIT, flit);
	int want_big = s8_level(s8_big_levels, S8_NBIG, big_khz);
	int want_lit = s8_level(s8_lit_levels, S8_NLIT, lit_khz);
	if (cur_big < 0 || cur_lit < 0) {
		IOLog("S8 DVFS: PLLs not at an ECT level, clocks unchanged\n");
		thread_terminate(current_thread());
		return;
	}
	if (want_big < 0) {
		want_big = cur_big;
	}
	if (want_lit < 0) {
		want_lit = cur_lit;
	}
	if (temp == 0) {
		IOLog("S8 DVFS: TMU unreadable, back to the S-Boot clocks\n");
		s8_dvfs_set(S8_BIG_BOOT, S8_LIT_BOOT, &cur_big, &cur_lit);
		thread_terminate(current_thread());
		return;
	}
	int big = want_big, lit = want_lit;
	s8_dvfs_set(big, lit, &cur_big, &cur_lit);
	IOLog("S8 DVFS: big %u lit %u kHz; PLL %u / %u MHz\n",
	    s8_big_levels[cur_big], s8_lit_levels[cur_lit], s8_pll_mhz(s8_cmu0), s8_pll_mhz(s8_cmu1));
	for (uint32_t tick = 1, cool = 0, hot_max = temp;; tick++) {
		IOSleep(1000);
		temp = s8_tmu_temp();
		if (temp == 0 || temp >= 95) {
			IOLog("S8 DVFS: TMU %d C, back to the S-Boot clocks, guard stops\n", temp);
			s8_dvfs_set(S8_BIG_BOOT < cur_big ? cur_big : S8_BIG_BOOT,
			    S8_LIT_BOOT < cur_lit ? cur_lit : S8_LIT_BOOT, &cur_big, &cur_lit);
			break;
		}
		hot_max = (uint32_t)temp > hot_max ? (uint32_t)temp : hot_max;
		if (temp >= 80) {
			big = big + 1 < S8_NBIG ? big + 1 : big;
			lit = lit + 1 < S8_NLIT ? lit + 1 : lit;
			cool = 0;
		} else if (temp <= 70 && ++cool >= 5) {
			big = big > want_big ? big - 1 : big;
			lit = lit > want_lit ? lit - 1 : lit;
			cool = 0;
		}
		int ob = cur_big, ol = cur_lit;
		s8_dvfs_set(big, lit, &cur_big, &cur_lit);
		if (ob != cur_big || ol != cur_lit || tick % 30 == 0) {
			IOLog("S8 DVFS: %d C (max %u), big %u lit %u kHz\n", temp, hot_max,
			    s8_big_levels[cur_big], s8_lit_levels[cur_lit]);
		}
	}
	thread_terminate(current_thread());
}
'''
edit('iokit/Kernel/arm/SweetCPU.cpp', [
    ('static uint32_t sweet_cpu_mhz[SWEET_SMP_MAX_CPUS];\n',
     'static uint32_t sweet_cpu_mhz[SWEET_SMP_MAX_CPUS];\n' + S8_DVFS, 1),
    ('\tIOLog(CPU_PORT_NAME " CPU: %u/%u CPUs initialized, SGI1 verified\\n",\n'
     '\t    topology->num_cpus, topology->num_cpus);\n',
     '\tIOLog(CPU_PORT_NAME " CPU: %u/%u CPUs initialized, SGI1 verified\\n",\n'
     '\t    topology->num_cpus, topology->num_cpus);\n'
     '#if defined(DREAMLTE)\n'
     '\t{\n'
     '\t\tuint32_t khz = 0;\n'
     '\t\tthread_t t;\n'
     '\t\tif ((PE_parse_boot_argn("s8big", &khz, sizeof(khz)) && khz) ||\n'
     '\t\t    (PE_parse_boot_argn("s8lit", &khz, sizeof(khz)) && khz)) {\n'
     '\t\t\tif (kernel_thread_start(s8_dvfs_thread, NULL, &t) == KERN_SUCCESS) {\n'
     '\t\t\t\tthread_deallocate(t);\n'
     '\t\t\t}\n'
     '\t\t}\n'
     '\t}\n'
     '#endif\n', 1),
])

# DPP scaling, step 0: what does S-Boot's display path look like? With
# s8dpudump=1 the first frame-done wait logs DECON's global, data-path and
# window registers and, for the six DPU input channels (DT idma_g0..vgf1:
# reg[0] DPP 0x12851000 + n * 0x1000, reg[1] DMA 0x128B1000 + n * 0x1000,
# reg[2] common DMA 0x128B0000; dpp_drv.c probe), the IDMA and DPP enable,
# format, sizes, base and scaler.
# Offsets: Samsung's regs-decon.h / regs-dpp.h (universal8895 dpu). Off by
# default: reading a clock-gated channel could stall the bus.
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('\t\t*(volatile uint32_t *)(sweet_fb_decon + 0x40) |= (1u << 13) | 1u;\n\t}\n',
     '\t\t*(volatile uint32_t *)(sweet_fb_decon + 0x40) |= (1u << 13) | 1u;\n'
     '\t\tuint32_t dump = 0;\n'
     '\t\tif (PE_parse_boot_argn("s8dpudump", &dump, sizeof(dump)) && dump) {\n'
     '\t\t\tsweet_fb_dpu_dump();\n'
     '\t\t}\n'
     '\t}\n', 1),
    ('static void\nsweet_fb_wait_frame_done(void)\n{\n',
     '#define S8_R(b, o) (*(volatile uint32_t *)((b) + (o)))\n'
     'static void\n'
     'sweet_fb_dpu_dump(void)\n'
     '{\n'
     '\tvm_offset_t dec = ml_io_map(0x12860000, 0x2000);\n'
     '\tvm_offset_t dpp = ml_io_map(0x12850000, 0x7000);\n'
     '\tvm_offset_t dma = ml_io_map(0x128B0000, 0x7000);\n'
     '\tif (dec == 0 || dma == 0 || dpp == 0) {\n'
     '\t\treturn;\n'
     '\t}\n'
     '\tIOLog("S8 DPU: decon global 0x%x update 0x%x path0 0x%x path1 0x%x path2 0x%x\\n",\n'
     '\t    S8_R(dec, 0), S8_R(dec, 0x60), S8_R(dec, 0x214), S8_R(dec, 0x218), S8_R(dec, 0x230));\n'
     '\tfor (uint32_t w = 0; w < 6; w++) {\n'
     '\t\tvm_offset_t b = dec + 0x1000 + w * 0x30;\n'
     '\t\tIOLog("S8 DPU: win%u 0x%x 0x%x 0x%x 0x%x 0x%x 0x%x 0x%x 0x%x\\n", w,\n'
     '\t\t    S8_R(b, 0), S8_R(b, 4), S8_R(b, 8), S8_R(b, 0xc), S8_R(b, 0x10),\n'
     '\t\t    S8_R(b, 0x14), S8_R(b, 0x18), S8_R(b, 0x1c));\n'
     '\t}\n'
     '\tIOLog("S8 DPU: dma version 0x%x ch_map 0x%x glb 0x%x\\n",\n'
     '\t    S8_R(dma, 0), S8_R(dma, 4), S8_R(dma, 0x40));\n'
     '\tfor (uint32_t c = 0; c < 6; c++) {\n'
     '\t\tvm_offset_t i = dma + 0x1000 + c * 0x1000, d = dpp + 0x1000 + c * 0x1000;\n'
     '\t\tIOLog("S8 DPU: ch%u idma en 0x%x in 0x%x out 0x%x src 0x%x off 0x%x img 0x%x y 0x%x"\n'
     '\t\t    " | dpp en 0x%x in 0x%x img 0x%x scaled 0x%x h 0x%x v 0x%x\\n", c,\n'
     '\t\t    S8_R(i, 0), S8_R(i, 8), S8_R(i, 0xc), S8_R(i, 0x10), S8_R(i, 0x14),\n'
     '\t\t    S8_R(i, 0x18), S8_R(i, 0x40), S8_R(d, 0), S8_R(d, 8), S8_R(d, 0x18),\n'
     '\t\t    S8_R(d, 0x2c), S8_R(d, 0x44), S8_R(d, 0x48));\n'
     '\t}\n'
     '}\n'
     '\n'
     'static void\nsweet_fb_wait_frame_done(void)\n{\n', 1),
])

# RAM above 512 MiB: with 2 GiB (c13, and the first S8 boot) kmem_range_init
# panicked "vm_map_locate_space failing for claim kmem_ptr_range_meta". The
# pointer/data/sprayqtn claims are sized to fill the largest free kernel_map
# hole exactly and then placed one after another from the fuzzed start, so
# any VA lost to placement makes the last claim miss. Keep 1 GiB of the
# hole out of the sizing (the data range is tens of GiB) and print the
# numbers, so a repeat failure on screen says why.
edit('osfmk/vm/vm_kern.c', [
    ('\tassert((total_claims & PAGE_MASK) == 0);\n'
     '\tlargest_free_size -= total_claims;\n',
     '\tassert((total_claims & PAGE_MASK) == 0);\n'
     '#if defined(DREAMLTE)\n'
     '\tprintf("S8 KMEM: map 0x%llx-0x%llx largest free 0x%llx static claims 0x%llx (%u)\\n",\n'
     '\t    (unsigned long long)kernel_map->min_offset, (unsigned long long)kernel_map->max_offset,\n'
     '\t    (unsigned long long)largest_free_size, (unsigned long long)total_claims, kmem_claim_count);\n'
     '\tif (largest_free_size > total_claims + (2ULL << 30)) {\n'
     '\t\tlargest_free_size -= 1ULL << 30;\n'
     '\t}\n'
     '#endif\n'
     '\tlargest_free_size -= total_claims;\n', 1),
    ('\t\t\tpanic("kmem_range_init: vm_map_locate_space failing for claim %s",\n'
     '\t\t\t    sp.kc_name);\n',
     '#if defined(DREAMLTE)\n'
     '\t\t\tpanic("kmem_range_init: vm_map_locate_space failing for claim %s "\n'
     '\t\t\t    "size 0x%llx start 0x%llx (%u of %u)", sp.kc_name,\n'
     '\t\t\t    (unsigned long long)sp.kc_size, (unsigned long long)start, i, kmem_claim_count);\n'
     '#else\n'
     '\t\t\tpanic("kmem_range_init: vm_map_locate_space failing for claim %s",\n'
     '\t\t\t    sp.kc_name);\n'
     '#endif\n', 1),
])

# DPP scaling (sweetfb_dpp=1 with sweetfb_scale=1): the display hardware
# scales the 1125x2436 frame to 1367x2960 instead of the presenter (9-14 ms
# of CPU per frame). S-Boot shows its framebuffer on DECON window 5, fed by
# DMA channel G0 (DECON channel 5; loader screen: DATA_PATH_CONTROL_0 =
# WIN_EN_F(5), only IDMA 0 running). Scaling exists only on the VGF
# channels (Samsung sets SCALED_IMG_SIZE only for VGF0/1), so window 5 moves
# to VGF0 (DECON channel 1, helper.c dpu_dma_type_to_channel): DMA
# 0x128B5000, DPP 0x12855000 (DT idma_vgf0 reg[1], reg[0]). Register use
# follows Samsung's dpp_reg.c (dpp_reg_init, dpp_reg_configure_params:
# XRGB8888, sizes, ratio = src << 20 / dst, 8-tap H / 4-tap V coefficient
# table 0 for upscaling, phases 0..8 as dpp_reg_set_h/v_coef write them) and
# decon_reg.c (decon_reg_set_window_control, decon_reg_config_win_channel).
# The DPU SYSMMUs are off (loader), so the DMA reads physical addresses: the
# two stage buffers live in low DRAM XNU never uses (0xd0000000 and
# 0xd1000000, System RAM under Linux, away from the 0xcc000000 framebuffer),
# mapped write-combined. Each present points VGF0 at the stage just written,
# right after a DECON frame-done, and forces the DMA SFR update (forcing at
# a random time gave artifacts in an earlier test). If the DMA or DPP
# reports a configuration error after the switch, window 5 goes back to G0
# and the CPU path is used. Built, not tested on the phone.
S8_DPP = r'''
extern "C" vm_offset_t ml_io_map_wcomb(vm_offset_t phys_addr, vm_size_t size);
static bool sweet_fb_dpp;
static vm_offset_t s8_vgf_dma, s8_vgf_dpp, s8_dpp_decon;
static uint64_t sweet_fb_stage_phys[2] = { 0xd0000000ULL, 0xd1000000ULL };
static uint32_t s8_dpp_win_start, s8_dpp_win_end, s8_dpp_win_count, s8_dpp_path1;

/* dpp_coef.h table 0 ("Ratio <= 65536"), phases 0..8 */
static const int16_t s8_dpp_hcoef[9][8] = {
	{  0,  0,   0, 128,   0,   0,  0,  0 },
	{ -1,  2,  -6, 127,   7,  -2,  1,  0 },
	{ -1,  4, -12, 125,  16,  -5,  1,  0 },
	{ -1,  5, -15, 120,  25,  -8,  2,  0 },
	{ -1,  6, -18, 114,  35, -10,  3, -1 },
	{ -1,  6, -20, 107,  46, -13,  4, -1 },
	{ -2,  7, -21,  99,  57, -16,  5, -1 },
	{ -1,  6, -20,  89,  68, -18,  5, -1 },
	{ -1,  6, -20,  79,  79, -20,  6, -1 },
};
static const int16_t s8_dpp_vcoef[9][4] = {
	{  0, 128,   0,  0 },
	{ -4, 127,   5,  0 },
	{ -6, 124,  11, -1 },
	{ -8, 118,  19, -1 },
	{ -8, 111,  27, -2 },
	{ -8, 102,  37, -3 },
	{ -8,  92,  48, -4 },
	{ -7,  81,  59, -5 },
	{ -6,  70,  70, -6 },
};

#define S8_WIN5(off) (0x1000 + 5 * 0x30 + (off))

static void
sweet_fb_dpp_flip(int b)
{
	uint32_t pa = (uint32_t)sweet_fb_stage_phys[b];
	S8_R(s8_vgf_dma, 0x40) = pa;                     /* IN_BASE_ADDR_Y */
	S8_R(s8_vgf_dma, 0x44) = pa;                     /* IN_BASE_ADDR_C */
	__asm__ volatile ("dsb sy" ::: "memory");
	S8_R(s8_vgf_dma, 0) |= 1u << 4;                  /* SFR_UPDATE_FORCE */
}

static void
sweet_fb_dpp_restore(void)
{
	S8_R(s8_dpp_decon, 0x218) = s8_dpp_path1;
	S8_R(s8_dpp_decon, S8_WIN5(0x08)) = s8_dpp_win_start;
	S8_R(s8_dpp_decon, S8_WIN5(0x0c)) = s8_dpp_win_end;
	S8_R(s8_dpp_decon, S8_WIN5(0x1c)) = s8_dpp_win_count;
	S8_R(s8_dpp_decon, 0x60) |= (1u << 31) | (1u << 5);
}

/* Window 5 from G0 (1:1 panel copy) to VGF0 scaling sw x sh to dw x dh at x0. */
static bool
sweet_fb_dpp_start(uint32_t sw, uint32_t sh, uint32_t dw, uint32_t dh, uint32_t x0)
{
	s8_vgf_dma = ml_io_map(0x128B5000, 0x1000);
	s8_vgf_dpp = ml_io_map(0x12855000, 0x1000);
	s8_dpp_decon = ml_io_map(0x12860000, 0x2000);
	vm_offset_t g0 = ml_io_map(0x128B1000, 0x1000);
	if (s8_vgf_dma == 0 || s8_vgf_dpp == 0 || s8_dpp_decon == 0 || g0 == 0) {
		return false;
	}
	s8_dpp_path1 = S8_R(s8_dpp_decon, 0x218);
	s8_dpp_win_start = S8_R(s8_dpp_decon, S8_WIN5(0x08));
	s8_dpp_win_end = S8_R(s8_dpp_decon, S8_WIN5(0x0c));
	s8_dpp_win_count = S8_R(s8_dpp_decon, S8_WIN5(0x1c));
	IOLog("S8 DPP: before path0 0x%x path1 0x%x win5 0x%x 0x%x 0x%x 0x%x; G0 en 0x%x in 0x%x "
	    "y 0x%x; VGF0 en 0x%x dpp en 0x%x\n", S8_R(s8_dpp_decon, 0x214), s8_dpp_path1,
	    S8_R(s8_dpp_decon, S8_WIN5(0)), s8_dpp_win_start, s8_dpp_win_end, s8_dpp_win_count,
	    S8_R(g0, 0), S8_R(g0, 8), S8_R(g0, 0x40), S8_R(s8_vgf_dma, 0), S8_R(s8_vgf_dpp, 0));

	/* DMA: as G0 (bus, QoS, deadlock, gating, recovery), then format and size. */
	for (uint32_t off = 0x34; off <= 0x38; off += 4) {
		S8_R(s8_vgf_dma, off) = S8_R(g0, off);
	}
	for (uint32_t off = 0x50; off <= 0x5c; off += 4) {
		S8_R(s8_vgf_dma, off) = S8_R(g0, off);
	}
	S8_R(s8_vgf_dma, 0) |= 3u << 9;                  /* SFR, SRAM clock gate enable */
	S8_R(s8_vgf_dma, 0x0c) = 0xffu << 24;            /* OUT_CON: frame alpha */
	S8_R(s8_vgf_dma, 0x08) = (S8_R(g0, 0x08) & ~((0x1fu << 11) | (3u << 8) | (1u << 7) |
	    (1u << 6) | (1u << 4) | (1u << 3))) | (4u << 11);   /* XRGB8888 */
	S8_R(s8_vgf_dma, 0x10) = sh << 16 | sw;          /* SRC_SIZE */
	S8_R(s8_vgf_dma, 0x14) = 0;                      /* SRC_OFFSET */
	S8_R(s8_vgf_dma, 0x18) = sh << 16 | sw;          /* IMG_SIZE */
	S8_R(s8_vgf_dma, 0x40) = (uint32_t)sweet_fb_stage_phys[0];
	S8_R(s8_vgf_dma, 0x44) = (uint32_t)sweet_fb_stage_phys[0];

	/* DPP: RGB, per-frame alpha, sizes, ratios, coefficients. */
	S8_R(s8_vgf_dpp, 0) |= 7u << 8;                  /* clock gate enable */
	S8_R(s8_vgf_dpp, 0x08) &= ~((7u << 16) | (1u << 11) | (1u << 10));
	S8_R(s8_vgf_dpp, 0x18) = sh << 16 | sw;          /* IMG_SIZE */
	S8_R(s8_vgf_dpp, 0x2c) = dh << 16 | dw;          /* SCALED_IMG_SIZE */
	S8_R(s8_vgf_dpp, 0x44) = (uint32_t)(((uint64_t)sw << 20) / dw);
	S8_R(s8_vgf_dpp, 0x48) = (uint32_t)(((uint64_t)sh << 20) / dh);
	for (uint32_t i = 0; i < 9; i++) {
		for (uint32_t k = 0; k < 2; k++) {
			for (uint32_t j = 0; j < 8; j++) {
				S8_R(s8_vgf_dpp, 0x290 + i * 4 + j * 0x24 + k * 0x200) = (uint32_t)(int32_t)s8_dpp_hcoef[i][j];
			}
			for (uint32_t j = 0; j < 4; j++) {
				S8_R(s8_vgf_dpp, 0x200 + i * 4 + j * 0x24 + k * 0x200) = (uint32_t)(int32_t)s8_dpp_vcoef[i][j];
			}
		}
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	S8_R(s8_vgf_dma, 0) |= 1u << 4;                  /* SFR_UPDATE_FORCE */
	S8_R(s8_vgf_dpp, 0) |= 1u << 4;

	/* DECON: window 5 on channel 1 (VGF0), dw x dh at x0. */
	sweet_fb_wait_frame_done();
	S8_R(s8_dpp_decon, 0x218) = (s8_dpp_path1 & ~(7u << 20)) | (1u << 20);
	S8_R(s8_dpp_decon, S8_WIN5(0x08)) = x0;
	S8_R(s8_dpp_decon, S8_WIN5(0x0c)) = (dh - 1) << 16 | (x0 + dw - 1);
	S8_R(s8_dpp_decon, S8_WIN5(0x1c)) = dw * dh;
	S8_R(s8_dpp_decon, 0x60) |= (1u << 31) | (1u << 5);
	for (int i = 0; i < 4; i++) {
		sweet_fb_wait_frame_done();
	}
	uint32_t dma_err = S8_R(s8_vgf_dma, 0x870), dpp_err = S8_R(s8_vgf_dpp, 0xd08);
	IOLog("S8 DPP: after path1 0x%x update 0x%x win5 0x%x 0x%x 0x%x; VGF0 en 0x%x in 0x%x src 0x%x "
	    "y 0x%x irq 0x%x cfg_err 0x%x; dpp en 0x%x img 0x%x scaled 0x%x h 0x%x v 0x%x irq 0x%x "
	    "cfg_err 0x%x\n", S8_R(s8_dpp_decon, 0x218), S8_R(s8_dpp_decon, 0x60),
	    S8_R(s8_dpp_decon, S8_WIN5(0x08)), S8_R(s8_dpp_decon, S8_WIN5(0x0c)),
	    S8_R(s8_dpp_decon, S8_WIN5(0x1c)), S8_R(s8_vgf_dma, 0), S8_R(s8_vgf_dma, 8),
	    S8_R(s8_vgf_dma, 0x10), S8_R(s8_vgf_dma, 0x40), S8_R(s8_vgf_dma, 4), dma_err,
	    S8_R(s8_vgf_dpp, 0), S8_R(s8_vgf_dpp, 0x18), S8_R(s8_vgf_dpp, 0x2c),
	    S8_R(s8_vgf_dpp, 0x44), S8_R(s8_vgf_dpp, 0x48), S8_R(s8_vgf_dpp, 4), dpp_err);
	if (dma_err != 0 || dpp_err != 0) {
		sweet_fb_dpp_restore();
		IOLog("S8 DPP: configuration error, window 5 back on G0\n");
		return false;
	}
	return true;
}
'''
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('static uint64_t sweet_fb_panel_ticks, sweet_fb_panel_copies;\n',
     'static uint64_t sweet_fb_panel_ticks, sweet_fb_panel_copies;\n' + S8_DPP, 1),
    # presenter: in DPP mode the flip replaces the scale, and the shown stage
    # stays busy until the next one is shown
    ('\t\tsweet_fb_stage = sweet_fb_stages[b];\n'
     '\t\tif (sweet_fb_scaled) {\n',
     '\t\tsweet_fb_stage = sweet_fb_stages[b];\n'
     '\t\tif (sweet_fb_dpp) {\n'
     '\t\t\tsweet_fb_dpp_flip(b);\n'
     '\t\t\tsweet_fb_wait_ticks += t1 - t0;\n'
     '\t\t\tsweet_fb_panel_ticks += mach_absolute_time() - t1;\n'
     '\t\t\tsweet_fb_panel_copies++;\n'
     '\t\t\tcontinue;\n'
     '\t\t} else if (sweet_fb_scaled) {\n', 1),
    # stage buffers: low DRAM, write-combined, when the DPP takes over
    ('\t\tuintptr_t stage = (uintptr_t)IOMallocData((vm_size_t)stage_bytes);\n'
     '\t\tuintptr_t stage2 = stage ? (uintptr_t)IOMallocData((vm_size_t)stage_bytes) : 0;\n',
     '\t\tint dpp = 0;\n'
     '\t\tPE_parse_boot_argn("sweetfb_dpp", &dpp, sizeof(dpp));\n'
     '\t\tuintptr_t stage = 0, stage2 = 0;\n'
     '\t\tif (dpp != 0 && sweet_fb_scaled && stage_bytes <= 0x01000000) {\n'
     '\t\t\tstage = (uintptr_t)ml_io_map_wcomb(sweet_fb_stage_phys[0], (vm_size_t)stage_bytes);\n'
     '\t\t\tstage2 = stage ? (uintptr_t)ml_io_map_wcomb(sweet_fb_stage_phys[1], (vm_size_t)stage_bytes) : 0;\n'
     '\t\t\tif (stage2 != 0) {\n'
     '\t\t\t\tbzero((void *)stage, (size_t)stage_bytes);\n'
     '\t\t\t\tbzero((void *)stage2, (size_t)stage_bytes);\n'
     '\t\t\t\tuint32_t dw = fLogicalW * fHeight / fLogicalH;\n'
     '\t\t\t\tsweet_fb_dpp = sweet_fb_dpp_start(fLogicalW, fLogicalH, dw, fHeight, (fWidth - dw) / 2);\n'
     '\t\t\t}\n'
     '\t\t\tif (!sweet_fb_dpp) {\n'
     '\t\t\t\tstage = stage2 = 0;               /* (WC mappings stay; CPU path below) */\n'
     '\t\t\t}\n'
     '\t\t}\n'
     '\t\tif (stage == 0) {\n'
     '\t\t\tstage = (uintptr_t)IOMallocData((vm_size_t)stage_bytes);\n'
     '\t\t\tstage2 = stage ? (uintptr_t)IOMallocData((vm_size_t)stage_bytes) : 0;\n'
     '\t\t}\n', 1),
])

#!/usr/bin/env python3
"""Resynchronise the dreamlte_touch.c block inside
xnu/patches/0124-dreamlte-s8.patch.

CI applies the patches; tools/dreamlte/dreamlte_touch.c is the source that
apply-dreamlte.py injects into a local xnu tree. The whole driver is one
added block at the top of the a5xelte_touch.c hunk, so the block can be
rebuilt from the file and the hunk header's new-side count fixed up.

Usage: sync-patch.py            check only (exit 1 if out of sync)
       sync-patch.py --write    rewrite the patch from the .c
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
patch_path = root / 'xnu/patches/0124-dreamlte-s8.patch'
src_path = Path(__file__).resolve().parent / 'dreamlte_touch.c'
HUNK_OLD = '@@ -615,10 '
HUNK_FN = 'a5touch_start_early(vm_offset_t nfc, vm_offset_t alive)'


def split_range(spec):
    """'616,907' or '616' -> (616, 907) / (616, 1)."""
    parts = spec.split(',')
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 1


def validate_hunks(lines):
    """Every hunk header must match the hunk body (old/new line counts)."""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('@@ '):
            head = line.split('@@')[1].split()
            old = split_range(head[0])[1]
            new = split_range(head[1])[1]
            o = n = 0
            i += 1
            while i < len(lines) and not lines[i].startswith(('@@ ', 'diff --git')):
                c = lines[i][:1]
                if c == ' ':
                    o += 1
                    n += 1
                elif c == '-':
                    o += 1
                elif c == '+':
                    n += 1
                elif lines[i] == '' and i == len(lines) - 1:
                    break
                else:
                    raise SystemExit(f'line {i + 1}: bad hunk line {lines[i]!r}')
                i += 1
            if (o, n) != (old, new):
                raise SystemExit(f'line {i}: hunk says -{old},+{new}, body has -{o},+{n}')
            continue
        i += 1


def find_block(lines):
    heads = [i for i, l in enumerate(lines)
             if l.startswith(HUNK_OLD) and l.endswith(HUNK_FN)]
    if len(heads) != 1:
        raise SystemExit(f'{len(heads)} matching hunk headers')
    start = heads[0] + 1
    while not lines[start].startswith('+'):      # context before the block
        start += 1
    if lines[start] != '+#if defined(DREAMLTE)':
        raise SystemExit(f'line {start + 1}: block starts with {lines[start]!r}')
    end = start
    while lines[end].startswith('+'):
        end += 1
    return start, end                    # half-open [start, end)


patch = patch_path.read_text().split('\n')
if patch[-1] == '':
    patch.pop()
validate_hunks(patch)

start, end = find_block(patch)
have = '\n'.join(l[1:] for l in patch[start:end]) + '\n'
want = src_path.read_text()

if have == want:
    print(f'in sync: driver block {end - start} lines = {src_path.name}')
    sys.exit(0)
if '--write' not in sys.argv:
    print(f'OUT OF SYNC: patch has {end - start} lines, {src_path.name} has '
          f'{len(want.splitlines())}')
    sys.exit(1)

added = ['+' + l for l in want.splitlines()]
hunk_idx = start - 1
while not patch[hunk_idx].startswith('@@ '):     # context before the block
    hunk_idx -= 1
old_count = split_range(patch[hunk_idx].split('@@')[1].split()[0])[1]
delta = len(added) - (end - start)
header = patch[hunk_idx].split('@@')
counts = header[1].split()
new_start, new_count = split_range(counts[1])
new_count += delta
patch[hunk_idx] = (f'@@ {counts[0]} +{new_start},{new_count} @@' + header[2])
patch[start:end] = added
validate_hunks(patch)
patch_path.write_text('\n'.join(patch) + '\n')
print(f'wrote {patch_path.relative_to(root)}: driver block {len(added)} lines, '
      f'hunk old {old_count} new {new_count}')

#pragma once
#include <stdint.h>

void touch_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *),
    const char *cmdline);
void battery_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *));

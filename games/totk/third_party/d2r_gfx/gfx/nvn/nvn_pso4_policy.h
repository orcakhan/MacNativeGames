// The Metal 4 pipeline archive's (nvn_pso4.h) rules that need no Metal device, so tests/pso4_policy_probe.m runs them
// (tests/test_pso4_policy.py). Foundation only. Mac only, as the archive (nvn_pso4_fn.h PSO4_BUILT).
#pragma once
#import <Foundation/Foundation.h>
#include <math.h>

/* A file's pipelines by its name, <first key>-<count>[-title][-n] (par4_period_base; par_pub_batch_ext adds -n when the
   name is taken; a compute key may carry -tg<size>): the first all-digit part after the key, or 0. */
#define PAR4_SMALL 1024
static NSUInteger par4_name_count(NSString *name) {
    NSArray<NSString *> *parts = [name componentsSeparatedByString:@"-"];
    NSCharacterSet *notDigit = NSCharacterSet.decimalDigitCharacterSet.invertedSet;
    for (NSUInteger i = 1; i < parts.count; i++)
        if (parts[i].length && parts[i].length < 8 && [parts[i] rangeOfCharacterFromSet:notDigit].location == NSNotFound) return (NSUInteger)parts[i].integerValue;
    return 0;
}
/* The rows the memory saver keeps before the title go into periods of their own while packaging (nvn_pso4_build.h
   g_par4_compact). Their files are marked "-title" in the name (2026-11-21): they count as small at any size. Until then
   small was only PAR4_SMALL or fewer, and Breath of the Wild's 1,453 such rows made a file that never did, so every
   packaging compiled them again (about 15 s: the capturing compiler uses no cache) and a start opened that file with the
   large ones (docs/experiments/2026-11-botw-mtl4-archive). */
static BOOL par4_name_title(NSString *name) {
    NSArray<NSString *> *parts = [name componentsSeparatedByString:@"-"];
    return parts.count > 1 && [[parts subarrayWithRange:NSMakeRange(1, parts.count - 1)] containsObject:@"title"];
}
/* Small: a title file, or PAR4_SMALL pipelines or fewer (apps packaged before the mark; the last, short period). Small files
   are opened before the large ones (nvn_pso4.h par4_open_all), and packaging takes the title rows from them. */
static BOOL par4_name_small(NSString *name) {
    NSUInteger c = par4_name_count(name);
    return par4_name_title(name) || (c && c <= PAR4_SMALL);
}
static NSString *par4_period_base(NSString *first_key, NSUInteger count, BOOL title) {
    return [first_key stringByAppendingFormat:@"-%lu%@", (unsigned long)count, title ? @"-title" : @""];
}

/* Packaging's fill order (warm_fill_archive, the pipeline-archive mode with the Metal 4 archive on). Two captures sharing a
   vertex-stage function never run at once (nvn_pso4_build.h fn4_claim: Metal crashes otherwise), and the fill sorts its
   rows, so a block's rows came one vertex shader after another: in 97.5% of the windows of 8 consecutive rows (the 8 fill
   threads) two shared one, and the threads waited for each other (Breath of the Wild 1.9.0, 2026-11-21: 155.8 s, 72.7 s
   with the guard off). The block's rows are spread instead: the j-th of a group's g rows goes to the fractional position
   (j + o) / g, o the group's own offset in [0, 1) (the golden ratio's multiples, so the many groups of one or two rows
   spread over the block too instead of meeting at its middle): each group is evenly spaced. The same rows, a
   deterministic order; nothing else depends on it (fill_row takes each row on its own).
   A block is one period's worth of rows (nvn_pso4.h PAR4_PERIOD_MAX): a Metal 4 file keeps a function's code once for all
   its pipelines, so a vertex shader's rows must stay in one period. Spread over blocks of 8,192 rows they reached several
   files and the App's pipelines grew from 460 to 581 MB. Measured 2026-11-21 (BotW 1.9.0, M5 Pro, on AC, alternating):
   2,000-row blocks 58.8 / 61.6 / 70.6 s and 485 MB, 8,192-row blocks 68.9 / 85.2 / 83.8 s; sorted 155.8 s, 460 MB;
   the old archive about 74 s. Windows of 8 rows sharing a vertex shader: 97.5% sorted, 17.2% spread. */
#define PAR4_FILL_BLOCK 2000
/* What a row's capture waits on: a render, border or tile-read row's vertex shader (the first 80 bytes of its key,
   nvn_pso_skey.h pso_skey vs: its first 160 hex digits), a compute row's shader; any other row is its own group. */
static NSString *par4_row_group(NSString *row) {
    NSArray<NSString *> *c = [row componentsSeparatedByString:@"\t"];
    if (c.count < 2 || row.length < 2) return row;
    unichar t = [row characterAtIndex:0];
    if (t == 'R' || t == 'B' || t == 'T') return [@"v" stringByAppendingString:c[1].length > 160 ? [c[1] substringToIndex:160] : c[1]];
    if (t == 'C') return [@"c" stringByAppendingString:c[1]];
    return row;
}
static NSArray<NSString *> *par4_spread(NSArray<NSString *> *rows) {
    NSMutableDictionary<NSString *, NSMutableArray<NSNumber *> *> *by = [NSMutableDictionary dictionary];
    NSMutableArray<NSString *> *order = [NSMutableArray array];   // groups in first-seen order: the tie-break
    for (NSUInteger i = 0; i < rows.count; i++) {
        NSString *g = par4_row_group(rows[i]);
        NSMutableArray<NSNumber *> *m = by[g];
        if (!m) { by[g] = m = [NSMutableArray array]; [order addObject:g]; }
        [m addObject:@(i)];
    }
    typedef struct { double at; NSUInteger group, row; } par4_slot;
    par4_slot *slots = calloc(rows.count ? rows.count : 1, sizeof *slots); NSUInteger n = 0;
    if (!slots) return rows;
    for (NSUInteger gi = 0; gi < order.count; gi++) {
        NSArray<NSNumber *> *m = by[order[gi]];
        double o = fmod((double)gi * 0.6180339887498949, 1.0);
        for (NSUInteger j = 0; j < m.count; j++) slots[n++] = (par4_slot){ (j + o) / (double)m.count, gi, m[j].unsignedIntegerValue };
    }
    qsort_b(slots, n, sizeof *slots, ^int(const void *a, const void *b) {
        const par4_slot *x = a, *y = b;
        if (x->at != y->at) return x->at < y->at ? -1 : 1;
        return x->group < y->group ? -1 : x->group > y->group ? 1 : 0;
    });
    NSMutableArray<NSString *> *out = [NSMutableArray arrayWithCapacity:n];
    for (NSUInteger i = 0; i < n; i++) [out addObject:rows[slots[i].row]];
    free(slots);
    return out;
}

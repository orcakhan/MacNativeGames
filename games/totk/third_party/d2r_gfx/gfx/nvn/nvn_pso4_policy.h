// The Metal 4 pipeline archive's (nvn_pso4.h) rules that need no Metal device, so tests/pso4_policy_probe.m runs them
// (tests/test_pso4_policy.py). Foundation only. Mac only, as the archive (nvn_pso4_fn.h PSO4_BUILT).
#pragma once
#import <Foundation/Foundation.h>

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


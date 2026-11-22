#import <Foundation/Foundation.h>
// The Metal 4 pipeline archive's file-name rules (nvn_pso4_policy.h), without Metal: tests/test_pso4_policy.py.
#include "nvn_pso4_policy.h"

static int checks, failures;
static void expect(BOOL ok, const char *why) {
    ++checks;
    if (!ok) { ++failures; fprintf(stderr, "FAIL: %s\n", why); }
}

static void names(void) {
    expect(par4_name_count(@"abc-1453-title") == 1453, "the count comes before the title mark");
    expect(par4_name_count(@"abc-1453-title-2") == 1453, "a unique suffix after the mark keeps the count");
    expect(par4_name_count(@"ctg-tg64-2000") == 2000, "a compute key's -tg<size> is not the count");
    expect(par4_name_count(@"abc-2000-3") == 2000, "the first all-digit part is the count");
    expect(par4_name_count(@"abc") == 0, "no count");
    expect([par4_period_base(@"abc", 1453, YES) isEqualToString:@"abc-1453-title"], "a title period's file name");
    expect([par4_period_base(@"abc", 2000, NO) isEqualToString:@"abc-2000"], "a plain period's file name, as before");
    // the rows kept before the title are in a small file of their own whatever their count (Breath of the Wild: 1,453 >
    // PAR4_SMALL): packaging takes them from it instead of compiling them again, and a start opens it before the large ones
    expect(par4_name_small(@"abc-1453-title"), "a title file is small at any count");
    expect(par4_name_small(@"abc-1453-title-2"), "with a unique suffix too");
    expect(!par4_name_small(@"abc-2003"), "a full period is large");
    expect(par4_name_small(@"abc-775"), "a file of PAR4_SMALL or fewer stays small (apps packaged before the mark)");
    expect(!par4_name_small(@"titleabc-2000"), "the mark is a part of its own, not text inside the key");
    expect(!par4_name_small(@"abc"), "no count, no mark: not small");
}


static NSString *row_of(char kind, NSString *vs, int n) {
    // a render row's key: vs[80] first (160 hex digits), then the rest of the key
    return [NSString stringWithFormat:@"%c\t%@%08d", kind, vs, n];
}
static NSString *vs_hex(int g) { NSMutableString *s = [NSMutableString string]; while (s.length < 160) [s appendFormat:@"%04x", g]; return s; }
static NSUInteger min_gap(NSArray<NSString *> *order, NSString *group) {
    NSUInteger last = NSNotFound, gap = NSUIntegerMax;
    for (NSUInteger i = 0; i < order.count; i++) if ([par4_row_group(order[i]) isEqualToString:group]) {
        if (last != NSNotFound && i - last < gap) gap = i - last;
        last = i;
    }
    return gap;
}
static void spread(void) {
    expect([par4_row_group(row_of('R', vs_hex(7), 1)) isEqualToString:[@"v" stringByAppendingString:vs_hex(7)]], "a render row waits on its vertex shader");
    expect([par4_row_group(row_of('T', vs_hex(7), 2)) isEqualToString:par4_row_group(row_of('R', vs_hex(7), 3))], "a tile-read row on the same vertex shader as a render row");
    expect([par4_row_group(row_of('B', vs_hex(7), 2)) isEqualToString:par4_row_group(row_of('R', vs_hex(7), 3))], "a border row too");
    expect([par4_row_group(@"C\tabc") isEqualToString:@"cabc"], "a compute row on its shader");
    expect([par4_row_group(@"M\tx\ty") isEqualToString:@"M\tx\ty"], "any other row is its own group");
    // sorted as the fill sorts them: 16 vertex shaders, 8 rows each, one after another (8 fill threads)
    NSMutableArray<NSString *> *rows = [NSMutableArray array];
    for (int g = 0; g < 16; g++) for (int j = 0; j < 8; j++) [rows addObject:row_of('R', vs_hex(g), j)];
    NSArray<NSString *> *out = par4_spread(rows);
    expect(out.count == rows.count && [[NSCountedSet setWithArray:out] isEqual:[NSCountedSet setWithArray:rows]], "the same rows");
    expect([out isEqualToArray:par4_spread(rows)], "a deterministic order");
    BOOL repeat = NO;
    for (NSUInteger i = 0; i + 8 <= out.count; i++) {
        NSMutableSet *s = [NSMutableSet set];
        for (NSUInteger k = i; k < i + 8; k++) [s addObject:par4_row_group(out[k])];
        if (s.count < 8) repeat = YES;
    }
    expect(!repeat, "no 8 consecutive rows share a vertex shader when 16 of them have 8 rows each");
    // one large group among singles: evenly spaced, about n / g apart
    NSMutableArray<NSString *> *mix = [NSMutableArray array];
    for (int j = 0; j < 100; j++) [mix addObject:row_of('R', vs_hex(9999), j)];
    for (int g = 0; g < 900; g++) [mix addObject:row_of('R', vs_hex(g), 0)];
    expect(min_gap(par4_spread(mix), par4_row_group(mix[0])) >= 9, "a group of 100 in 1,000 rows is at least 9 apart");
    // one group alone keeps its order
    NSArray<NSString *> *one = @[row_of('R', vs_hex(1), 1), row_of('R', vs_hex(1), 2), row_of('R', vs_hex(1), 3)];
    expect([par4_spread(one) isEqualToArray:one], "a single group keeps its order");
    expect(par4_spread(@[]).count == 0, "no rows");
}

int main(void) {
    @autoreleasepool { names(); spread(); }
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}

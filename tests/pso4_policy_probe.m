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



int main(void) {
    @autoreleasepool { names(); }
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}

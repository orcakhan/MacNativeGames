// System-wide power sampler without root: IOReport "Energy Model" (energy per channel) and the GPU's
// IOAccelerator "Device Utilization %". One line per interval: epoch, gpu_W, cpu_W, dram_W, sum, gpu_util.
// argv[1] interval s (default 1); argv[2] present: list channel names and units on stderr once.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
typedef struct IOReportSubscription *IOReportSubscriptionRef;
extern CFDictionaryRef IOReportCopyChannelsInGroup(CFStringRef, CFStringRef, uint64_t, uint64_t, uint64_t);
extern IOReportSubscriptionRef IOReportCreateSubscription(void *, CFMutableDictionaryRef, CFMutableDictionaryRef *, uint64_t, CFTypeRef);
extern CFDictionaryRef IOReportCreateSamples(IOReportSubscriptionRef, CFMutableDictionaryRef, CFTypeRef);
extern CFDictionaryRef IOReportCreateSamplesDelta(CFDictionaryRef, CFDictionaryRef, CFTypeRef);
extern int64_t IOReportSimpleGetIntegerValue(CFDictionaryRef, int32_t);
extern CFStringRef IOReportChannelGetChannelName(CFDictionaryRef);
extern CFStringRef IOReportChannelGetUnitLabel(CFDictionaryRef);

static double gpu_util(void) {
    io_iterator_t it; double u = -1;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOAccelerator"), &it) != KERN_SUCCESS) return -1;
    io_object_t s;
    while ((s = IOIteratorNext(it))) {
        CFTypeRef ps = IORegistryEntryCreateCFProperty(s, CFSTR("PerformanceStatistics"), kCFAllocatorDefault, 0);
        if (ps) { NSNumber *n = ((__bridge NSDictionary *)ps)[@"Device Utilization %"]; if (n) u = n.doubleValue; CFRelease(ps); }
        IOObjectRelease(s);
    }
    IOObjectRelease(it); return u;
}

static double joules(NSString *unit, double v) {
    if ([unit isEqualToString:@"mJ"]) return v / 1e3;
    if ([unit isEqualToString:@"uJ"]) return v / 1e6;
    if ([unit isEqualToString:@"nJ"]) return v / 1e9;
    return 0;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        double iv = argc > 1 ? atof(argv[1]) : 1.0;
        CFDictionaryRef ch = IOReportCopyChannelsInGroup(CFSTR("Energy Model"), NULL, 0, 0, 0);
        if (!ch) { fprintf(stderr, "no Energy Model channels\n"); return 1; }
        CFMutableDictionaryRef mch = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, 0, ch), subbed = NULL;
        IOReportSubscriptionRef sub = IOReportCreateSubscription(NULL, mch, &subbed, 0, NULL);
        if (!sub) { fprintf(stderr, "no IOReport subscription\n"); return 1; }
        CFDictionaryRef prev = IOReportCreateSamples(sub, subbed, NULL);
        double tp = [NSDate date].timeIntervalSince1970;
        setvbuf(stdout, NULL, _IOLBF, 0);
        printf("epoch\tgpu_w\tcpu_w\tdram_w\tsum_w\tgpu_util\n");
        int listed = argc <= 2;
        for (;;) {
            [NSThread sleepForTimeInterval:iv];
            CFDictionaryRef cur = IOReportCreateSamples(sub, subbed, NULL);
            double tc = [NSDate date].timeIntervalSince1970, dt = tc - tp;
            CFDictionaryRef d = IOReportCreateSamplesDelta(prev, cur, NULL);
            double gpu = 0, cpu = 0, dram = 0;
            for (NSDictionary *c in ((__bridge NSDictionary *)d)[@"IOReportChannels"]) {
                CFDictionaryRef cd = (__bridge CFDictionaryRef)c;
                NSString *name = (__bridge NSString *)IOReportChannelGetChannelName(cd);
                NSString *unit = (__bridge NSString *)IOReportChannelGetUnitLabel(cd);
                double w = joules(unit, (double)IOReportSimpleGetIntegerValue(cd, 0)) / dt;
                if (!listed) fprintf(stderr, "%s [%s] %.3f W\n", name.UTF8String, unit.UTF8String, w);
                if ([name isEqualToString:@"GPU Energy"]) gpu += w;
                else if ([name isEqualToString:@"CPU Energy"]) cpu += w;
                else if ([name hasPrefix:@"DRAM"]) dram += w;
            }
            listed = 1;
            printf("%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.1f\n", tc, gpu, cpu, dram, gpu + cpu + dram, gpu_util());
            CFRelease(d); CFRelease(prev); prev = cur; tp = tc;
        }
    }
}

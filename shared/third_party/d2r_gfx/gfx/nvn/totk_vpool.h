// TOTK: NVN physical / virtual memory pools backed by Darwin VM aliasing.
#pragma once
#include <stdint.h>
#include "nvn_obj.h"

// Runtime-verified layout of NVNmappingRequest (0x28 bytes, main nvnMemoryPoolMapVirtual call).
typedef struct {
    const NVNmemoryPool *physical_pool;
    int64_t physical_offset;
    int64_t virtual_offset;
    uint64_t size;
    int32_t storage_class;
    uint32_t padding;
} totk_mapping_request;
_Static_assert(sizeof(totk_mapping_request) == 0x28, "NVNmappingRequest stride");

#define TOTK_VPOOL_PAGE 0x10000ull   // NVN virtual mapping granularity (64 KiB)

// Called by MemoryPoolInitialize for PHYSICAL or VIRTUAL pools. Returns 0 with a logged reason on failure.
int totk_vpool_init(pool_t *pool);
// Called by MemoryPoolFinalize. Returns 1 when it released the pool's host storage.
int totk_vpool_fini(pool_t *pool);
// All requests are validated before any mapping changes; returns 0 and leaves mappings intact on failure.
int totk_vpool_map(pool_t *virtual_pool, int count, const totk_mapping_request *requests);
// TOTK diagnostics: CPU address of the physical backing of a virtual-pool range (1 = mapped, *cpu set).
int totk_vpool_backing(uintptr_t va, uint64_t len, uintptr_t *cpu);
/* A copy of the virtual pools' spans and their mappings (sorted, disjoint), for judging many ranges without the lock:
   totk_vpool_view_sync refreshes it (one lock, only when the mappings changed since), totk_vpool_canon reads it. */
enum { TOTK_VPOOL_MAX_POOLS = 256, TOTK_VPOOL_MAX_MAPS = 4096 };
typedef struct { uintptr_t lo, hi; } totk_vpool_span;
typedef struct { uintptr_t va, cpu; uint64_t size; } totk_vpool_ent;
typedef struct { uint64_t gen; int npool, nmap, lost; totk_vpool_span pool[TOTK_VPOOL_MAX_POOLS]; totk_vpool_ent map[TOTK_VPOOL_MAX_MAPS]; } totk_vpool_view;
void totk_vpool_view_sync(totk_vpool_view *view);
/* The address of the storage behind [va, va + len): 1 with *canon = the physical backing when the range lies in a virtual
   pool and is mapped throughout (by one mapping, or by adjacent ones whose backing follows on), or = va when it touches no
   virtual pool (judged by the pools' spans, mapped or not); 0 otherwise (an unmapped hole, mappings whose backing does not
   follow on, a range across a pool's border, an empty or wrapping range, or a table that overflowed). */
int totk_vpool_canon(const totk_vpool_view *view, uintptr_t va, uint64_t len, uintptr_t *canon);
// Once virtual aliases have existed, address-only write tracking is insufficient.
int totk_vpool_aliases_used(void);

// TOTK: NVN physical / virtual memory pools.
// A virtual pool is a host VM range whose 64 KiB pages alias pages of physical pools via mach_vm_remap
// (copy=FALSE), so CPU and GPU writes through either view hit the same physical pages.
// Physical pools marked CPU_NO_ACCESS cannot be observed except through virtual mappings, so they get
// 16 KiB-aligned host storage (game storage may be only 4/8 KiB aligned, which Darwin cannot remap).
// CPU-visible physical pools must alias the game storage itself and therefore must be 16 KiB aligned.
#include "totk_vpool.h"
#include "nvn_mtl.h"
#include "nvn_dirty.h"
#include "../../host/hle.h"
#include <mach/mach.h>
#include "mach_vm_compat.h"
#include <pthread.h>
#include <unistd.h>

#define F_CPU_NO_ACCESS NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS
#define F_GPU_NO_ACCESS NVN_MEMORY_POOL_FLAGS_GPU_NO_ACCESS
#define F_PHYSICAL NVN_MEMORY_POOL_FLAGS_PHYSICAL
#define F_VIRTUAL NVN_MEMORY_POOL_FLAGS_VIRTUAL
#define POOL_MAGIC MAGIC('P', 'O', 'O', 'L')

static pthread_mutex_t g_map_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_aliases_used;
int totk_vpool_aliases_used(void) { return __atomic_load_n(&g_aliases_used, __ATOMIC_ACQUIRE); }

static uint64_t host_page(void) { return (uint64_t)getpagesize(); }
static uint64_t round_up(uint64_t v, uint64_t a) { return (v + a - 1) & ~(a - 1); }

/* The virtual pools (their host spans) and the mappings in them: virtual range -> CPU address of the physical backing,
   sorted by address and disjoint (a request first cuts its range out of older ones; an unmapped range has no entry).
   Diagnostics use it (a watch on a GPU address protects the pages the CPU actually touches: the game reads / writes physical
   pools through their own view), and the compute-dispatch hoist judges memory by the backing (totk_vpool_canon). g_vmap_lost:
   a table was full, so neither can be trusted any more; g_map_gen counts the changes (under g_map_mu). */
static totk_vpool_span g_vpools[TOTK_VPOOL_MAX_POOLS]; static int g_nvpools;
static totk_vpool_ent g_vmap[TOTK_VPOOL_MAX_MAPS]; static int g_nvmap, g_vmap_lost;
static uint64_t g_map_gen;
static void vmap_lose(const char *what) { if (!g_vmap_lost) LOG("【红】vpool: %s table full; ranges in virtual pools are no longer told apart by their backing", what); g_vmap_lost = 1; }
// Cuts [lo, hi) out of the mappings (0: no room to split an entry around it)
static int vmap_cut(uintptr_t lo, uintptr_t hi) {
    for (int i = 0; i < g_nvmap; i++) {
        totk_vpool_ent *e = &g_vmap[i]; uintptr_t elo = e->va, ehi = e->va + e->size;
        if (ehi <= lo || elo >= hi) continue;
        if (elo < lo && ehi > hi) {   // inside one entry: it splits around it
            if (g_nvmap >= TOTK_VPOOL_MAX_MAPS) return 0;
            memmove(&g_vmap[i + 2], &g_vmap[i + 1], (size_t)(g_nvmap - i - 1) * sizeof *e); g_nvmap++;
            g_vmap[i + 1] = (totk_vpool_ent){hi, e->cpu + (hi - elo), ehi - hi}; e->size = lo - elo; return 1;
        }
        if (elo < lo) { e->size = lo - elo; continue; }
        if (ehi > hi) { e->cpu += hi - elo; e->va = hi; e->size = ehi - hi; continue; }
        memmove(&g_vmap[i], &g_vmap[i + 1], (size_t)(g_nvmap - i - 1) * sizeof *e); g_nvmap--; i--;
    }
    return 1;
}
// [va, va + size) now shows cpu (0: unmapped)
static void vmap_note(uintptr_t va, uint64_t size, uintptr_t cpu) {
    __atomic_add_fetch(&g_map_gen, 1, __ATOMIC_RELEASE);
    if (!vmap_cut(va, va + size)) { vmap_lose("mapping"); return; }
    if (!cpu) return;
    if (g_nvmap >= TOTK_VPOOL_MAX_MAPS) { vmap_lose("mapping"); return; }
    int i = 0; while (i < g_nvmap && g_vmap[i].va < va) i++;
    memmove(&g_vmap[i + 1], &g_vmap[i], (size_t)(g_nvmap - i) * sizeof *g_vmap); g_nvmap++;
    g_vmap[i] = (totk_vpool_ent){va, cpu, size};
}
int totk_vpool_backing(uintptr_t va, uint64_t len, uintptr_t *cpu) {
    pthread_mutex_lock(&g_map_mu); int r = 0;
    for (int i = 0; i < g_nvmap; i++) { const totk_vpool_ent *e = &g_vmap[i]; if (e->cpu && va >= e->va && va + len <= e->va + e->size) { *cpu = e->cpu + (va - e->va); r = 1; break; } }
    pthread_mutex_unlock(&g_map_mu); return r;
}
void totk_vpool_view_sync(totk_vpool_view *v) {
    if (__atomic_load_n(&g_map_gen, __ATOMIC_ACQUIRE) == v->gen) return;
    pthread_mutex_lock(&g_map_mu);
    v->gen = g_map_gen; v->lost = g_vmap_lost; v->npool = g_nvpools; v->nmap = g_nvmap;
    memcpy(v->pool, g_vpools, (size_t)g_nvpools * sizeof *g_vpools); memcpy(v->map, g_vmap, (size_t)g_nvmap * sizeof *g_vmap);
    pthread_mutex_unlock(&g_map_mu);
}
int totk_vpool_canon(const totk_vpool_view *v, uintptr_t va, uint64_t len, uintptr_t *canon) {
    if (!len || va + len < va) return 0;
    uintptr_t end = va + len; const totk_vpool_span *in = NULL;
    for (int i = 0; i < v->npool; i++) if (va < v->pool[i].hi && v->pool[i].lo < end) { in = &v->pool[i]; break; }
    if (!in && !v->lost) { *canon = va; return 1; }   // no virtual pool: the address is the storage's own
    if (!in || v->lost || va < in->lo || end > in->hi) return 0;
    int lo = 0, hi = v->nmap; while (lo < hi) { int m = (lo + hi) / 2; if (v->map[m].va <= va) lo = m + 1; else hi = m; }
    if (!lo) return 0;
    const totk_vpool_ent *e = &v->map[lo - 1], *last = v->map + v->nmap;
    if (va >= e->va + e->size) return 0;   // an unmapped hole
    *canon = e->cpu + (va - e->va);
    for (; e->va + e->size < end; e++) { const totk_vpool_ent *f = e + 1;   // across the next mapping when its storage follows on
        if (f == last || f->va != e->va + e->size || f->cpu != e->cpu + e->size) return 0; }
    return 1;
}
static uint8_t *vm_fresh(uint64_t span) {
    mach_vm_address_t a = 0;
    kern_return_t kr = mach_vm_allocate(mach_task_self(), &a, span, VM_FLAGS_ANYWHERE);
    if (kr != KERN_SUCCESS) { LOG("【红】vpool: mach_vm_allocate(%#llx) failed kr=%d", span, kr); return NULL; }
    return (uint8_t *)(uintptr_t)a;
}

int totk_vpool_init(pool_t *o) {
    int phys = (o->flags & F_PHYSICAL) != 0, virt = (o->flags & F_VIRTUAL) != 0;
    o->game_mem = o->mem; o->host = NULL; o->span = 0;
    if (phys == virt) { LOG("【红】vpool: pool flags %#x must be exactly one of PHYSICAL/VIRTUAL", o->flags); return 0; }
    if (!o->size || o->size % TOTK_VPOOL_PAGE) { LOG("【红】vpool: pool size %#llx not a multiple of 64 KiB", o->size); return 0; }
    if (virt && o->mem) { LOG("【红】vpool: virtual pool given storage %p", (void *)o->mem); return 0; }
    if (phys && !o->mem) { LOG("【红】vpool: physical pool without storage"); return 0; }
    if (phys && !(o->flags & F_CPU_NO_ACCESS)) {
        if ((uintptr_t)o->mem % host_page()) { LOG("【红】vpool: CPU-visible physical pool %p not %#llx aligned; cannot alias", (void *)o->mem, host_page()); return 0; }
        return 1;   // aliases the game storage directly
    }
    o->span = round_up(o->size, host_page());
    o->host = vm_fresh(o->span);
    if (!o->host) return 0;
    o->mem = o->host;
    if (virt) {
        pthread_mutex_lock(&g_map_mu);
        if (g_nvpools < TOTK_VPOOL_MAX_POOLS) g_vpools[g_nvpools++] = (totk_vpool_span){(uintptr_t)o->host, (uintptr_t)o->host + o->span}; else vmap_lose("virtual pool");
        __atomic_add_fetch(&g_map_gen, 1, __ATOMIC_RELEASE);
        pthread_mutex_unlock(&g_map_mu);
    }
    return 1;
}

int totk_vpool_fini(pool_t *o) {
    if (!o->host) return 0;
    if (o->flags & F_VIRTUAL) {   // its span and its mappings go before the address range can be handed out again
        pthread_mutex_lock(&g_map_mu);
        uintptr_t lo = (uintptr_t)o->host, hi = lo + o->span;
        for (int i = 0; i < g_nvpools; i++) if (g_vpools[i].lo == lo) { g_vpools[i] = g_vpools[--g_nvpools]; break; }
        if (!vmap_cut(lo, hi)) vmap_lose("mapping");   // entries never cross a pool's border: nothing splits
        __atomic_add_fetch(&g_map_gen, 1, __ATOMIC_RELEASE);
        pthread_mutex_unlock(&g_map_mu);
    }
    mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)(uintptr_t)o->host, o->span);
    o->host = NULL; o->mem = o->game_mem; o->span = 0;
    return 1;
}

static int check_request(const pool_t *v, const totk_mapping_request *r, int i) {
    uint64_t end = (uint64_t)r->virtual_offset + r->size;
    if (r->virtual_offset < 0 || r->physical_offset < 0 || !r->size) { LOG("【红】vpool: request %d negative/empty range", i); return 0; }
    if ((r->virtual_offset | r->physical_offset | r->size) % TOTK_VPOOL_PAGE) { LOG("【红】vpool: request %d not 64 KiB aligned (v=%#llx p=%#llx n=%#llx)", i, r->virtual_offset, r->physical_offset, r->size); return 0; }
    if (end < r->size || end > v->size) { LOG("【红】vpool: request %d exceeds virtual pool (%#llx > %#llx)", i, end, v->size); return 0; }
    if (!r->physical_pool) return 1;   // unmap
    const pool_t *p = (const pool_t *)(const void *)r->physical_pool;
    if (p->magic != POOL_MAGIC || !(p->flags & F_PHYSICAL)) { LOG("【红】vpool: request %d source %p is not a physical pool", i, (const void *)p); return 0; }
    uint64_t pend = (uint64_t)r->physical_offset + r->size;
    if (pend < r->size || pend > p->size) { LOG("【红】vpool: request %d exceeds physical pool (%#llx > %#llx)", i, pend, p->size); return 0; }
    return 1;
}

static int apply_request(pool_t *v, const totk_mapping_request *r) {
    mach_vm_address_t dst = (mach_vm_address_t)(uintptr_t)(v->mem + r->virtual_offset);
    kern_return_t kr;
    if (!r->physical_pool) {
        kr = mach_vm_allocate(mach_task_self(), &dst, r->size, VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE);
    } else {
        const pool_t *p = (const pool_t *)(const void *)r->physical_pool;
        vm_prot_t cur, max;
        kr = mach_vm_remap(mach_task_self(), &dst, r->size, 0, VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE, mach_task_self(),
                           (mach_vm_address_t)(uintptr_t)(p->mem + r->physical_offset), FALSE, &cur, &max, VM_INHERIT_NONE);
        if (kr == KERN_SUCCESS && (cur & (VM_PROT_READ | VM_PROT_WRITE)) != (VM_PROT_READ | VM_PROT_WRITE)) { LOG("【红】vpool: alias lost RW (prot=%d)", cur); return 0; }
        if (kr == KERN_SUCCESS) vmap_note((uintptr_t)(v->mem + r->virtual_offset), r->size, (uintptr_t)(p->mem + r->physical_offset));
    }
    if (!r->physical_pool && kr == KERN_SUCCESS) vmap_note((uintptr_t)(v->mem + r->virtual_offset), r->size, 0);
    if (kr != KERN_SUCCESS || dst != (mach_vm_address_t)(uintptr_t)(v->mem + r->virtual_offset)) {
        LOG("【红】vpool: remap at %#llx size %#llx failed kr=%d", (unsigned long long)dst, r->size, kr);
        return 0;
    }
    return 1;
}

int totk_vpool_map(pool_t *v, int count, const totk_mapping_request *r) {
    if (!v || v->magic != POOL_MAGIC || !(v->flags & F_VIRTUAL) || !v->mem) { LOG("【红】vpool: MapVirtual target %p is not a virtual pool", (void *)v); return 0; }
    if (count < 0 || (count && !r)) { LOG("【红】vpool: invalid request count %d", count); return 0; }
    for (int i = 0; i < count; i++) if (!check_request(v, &r[i], i)) return 0;
    pthread_mutex_lock(&g_map_mu);
    // GPU page tables of the old zero-copy buffer and dirty-page protections refer to the replaced pages.
    __atomic_store_n(&g_aliases_used, 1, __ATOMIC_RELEASE);
    nvn_dirty_remove_range(v->mem);
    mtl_pool_del(v->mem);
    int ok = 1;
    for (int i = 0; ok && i < count; i++) ok = apply_request(v, &r[i]);
    mtl_pool_add(v->mem, v->size);
    nvn_dirty_add_range(v->mem, v->size);
    pthread_mutex_unlock(&g_map_mu);
    if (!ok) die("vpool: mapping failed after validation; virtual pool %p is inconsistent", (void *)v);
    return 1;
}

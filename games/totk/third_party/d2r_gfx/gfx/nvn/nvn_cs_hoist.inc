/* Compute dispatches moved ahead of the render pass they would split (TOTK_CS_HOIST; port of seedds/nxnative's cs_hoist_try, MIT).
   Metal cannot run a compute dispatch inside a render pass: dispatch() ends the pass, and the next draw opens another one on
   the same targets (the fixed cost of a pass, and a store and a load of every attachment). When a draw opens a pass, the
   commands after it are scanned up to the first one that may end the pass or depend on the order (anything but draws,
   dispatches, pure state and barriers without bits); each dispatch met on the way runs right away, before the pass opens,
   when it writes nothing the draws before it in that stretch read, and the replay skips it where it meets it (csh_take).
   As geo_run: the scan applies the state commands to S and R (state_op) and restores both after; a moved command counts only
   in the submission it was moved in (g_sub_serial), since the game records into the same command memory every frame.
   A draw's reads are its vertex and index buffers, uniform and read-only storage buffers and the storage of the textures it
   samples, judged on the shader variant it will draw with (csh_draw_reads); a draw that may write memory (a writable storage
   buffer, an image), reads memory not listed (descriptor pools, global memory, typed buffers, indirect records) or has a
   geometry or tessellation stage stops the scan. A dispatch's storage buffers count as written (csh_cs); it is refused for
   an indirect grid, a binding with no listed range, a uniform or storage buffer over an attachment's storage, a sampled
   colour attachment of the pass, or the pass's depth sampled after a draw of the stretch wrote depth or stencil.
   Not while another mechanism replays or rewrites these commands (stereo eyes, world freeze, pass fusion and deferral, cube
   groups, layered passes, TBDR, a geometry draw's raster), with a pending clear, or past the cursor's 8 return addresses. A
   dispatch already run ahead and not yet met by the replay (a later draw scanned again with no pass opened) stops the scan.
   Virtual-pool aliases (one physical page under several addresses): every range is judged by the address of the storage
   behind it (totk_vpool_canon, on a copy of the mappings taken once per scan); a range that cannot be (an unmapped hole of a
   virtual pool, mappings whose storage does not follow on) cannot be listed, as an unknown extent.
   TOTK_CS_HOIST=1 on (off by default for now). */
static int g_csh_probe_neg;   // probe-gpu-cs-hoist negative controls: 1 csh_take never skips (a moved dispatch runs again), 2 the scan does not run
enum { CSH_MAX = 64, CSH_RN = 1024, CSH_OPS = 4096 };
/* op: the dispatch commands run ahead and not yet met by the replay, in submission sub; moved: dispatches run ahead; scans:
   full scans; stop[]: why scans ended or did not run: 0 the first draw's reads cannot be listed, 1 a later draw's, 2 a dispatch
   refused, 3 a dispatch writes what a draw before it reads, 4 the dispatch limit, 5 another command or a barrier, 6 a bad
   cursor, 7 depth already written, 8 the pre-scan found no dispatch, 9 refused at entry, 10 the scan limit (CSH_OPS commands),
   11 the scan reached the end of the stream. Every full scan (scans) ends in exactly one of 0 to 7, 10 and 11; 8 and 9 are
   calls that did not scan. csh_stop_name gives the short names the statistics line prints. */
enum { CSH_STOPS = 12 };
static struct { const uint8_t *op[CSH_MAX]; int n; uint64_t sub, moved, scans, stop[CSH_STOPS]; } g_csh;
static const char *const csh_stop_name[CSH_STOPS] = {"first_draw", "later_draw", "dispatch_refused", "memory_conflict", "dispatch_limit", "other_op", "bad_cursor",
    "depth_written", "no_dispatch", "entry_refused", "scan_limit", "scan_end"};
static int csh_on(void) {
    static int m = -1;
    if (m < 0) { const char *e = getenv("TOTK_CS_HOIST"); m = e && atoi(e) == 1; if (m) MLOG("TOTK_CS_HOIST=1: compute dispatches between the draws of a pass run ahead of it when nothing the draws before them read changes"); }
    return m;
}
// Whether the replay's dispatch command op already ran ahead of its pass (then it is taken off the list)
static int csh_take(const uint8_t *op) {
    if (g_csh.sub != g_sub_serial) { g_csh.n = 0; return 0; }   // moves of an earlier submission the replay never met
    if (g_csh_probe_neg == 1) return 0;
    for (int i = 0; i < g_csh.n; i++) if (g_csh.op[i] == op) { g_csh.op[i] = g_csh.op[--g_csh.n]; return 1; }
    return 0;
}
typedef struct { uint64_t lo, hi; } csh_rng;
static totk_vpool_view g_csh_view;   // the virtual pools' mappings, as csh_try's scan found them
// Adds [a, a + sz) as the range of the storage behind it (the physical backing of a virtual pool's address)
static int csh_add(csh_rng *r, int *n, uint64_t a, uint64_t sz) {
    if (!a) return 1;   // not bound
    uintptr_t c;
    if (!sz || sz > UINT64_MAX - a || *n >= CSH_RN || !totk_vpool_canon(&g_csh_view, (uintptr_t)a, sz, &c)) return 0;   // an unknown extent or storage
    r[(*n)++] = (csh_rng){c, c + sz}; return 1;
}
static int csh_hit(const csh_rng *a, int na, const csh_rng *b, int nb) { for (int i = 0; i < na; i++) for (int j = 0; j < nb; j++) if (a[i].lo < b[j].hi && b[j].lo < a[i].hi) return 1; return 0; }
// The texture a handle names (a copy taken under the registry lock: the game thread grows g_treg); 0 when it names none registered
static int csh_tex(uint64_t h, tex_t *t) {
    registry_lock(); const treg_t *r = bound_tex(h); int ok = r && r->t.serial; if (ok) *t = r->t; registry_unlock();
    return ok;
}
/* Whether texture a may share storage with b (as defer_tex_alias, by the storage behind the addresses): the same texture, or
   storage that overlaps or cannot be told apart; with an unknown size, the same pool or either in a virtual pool */
static int csh_tex_alias(const tex_t *a, const tex_t *b) {
    if (!a || !b) return 0;
    if (a->serial == b->serial) return 1;
    if (!a->mem || !b->mem) return 0;
    csh_rng ra[1], rb[1]; int na = 0, nb = 0;
    if (!a->L.size || !b->L.size) {
        uintptr_t ca, cb;
        return a->pool == b->pool || !totk_vpool_canon(&g_csh_view, (uintptr_t)a->mem, 1, &ca) || ca != (uintptr_t)a->mem
            || !totk_vpool_canon(&g_csh_view, (uintptr_t)b->mem, 1, &cb) || cb != (uintptr_t)b->mem; }
    return !csh_add(ra, &na, (uint64_t)(uintptr_t)a->mem, a->L.size) || !csh_add(rb, &nb, (uint64_t)(uintptr_t)b->mem, b->L.size) || csh_hit(ra, na, rb, nb);
}
// Whether [addr, addr + size) meets the storage of an attachment of the pass (1 too when either extent is unknown)
static int csh_attachment_hit(uint64_t addr, uint64_t size) {
    if (!addr || !R.has_rt) return 0;
    csh_rng a[1]; int na = 0; if (!csh_add(a, &na, addr, size)) return 1;
    for (int k = 0; k < 9; k++) {
        const tex_t *t = k == 8 ? R.rt.depth : k < R.rt.n ? R.rt.color[k] : NULL;
        if (!t || !t->mem) continue;
        csh_rng s[1]; int ns = 0;
        if (!csh_add(s, &ns, (uint64_t)(uintptr_t)t->mem, t->L.size) || csh_hit(a, na, s, ns)) return 1;
    }
    return 0;
}
/* The memory a draw reads: vertex and index buffers, uniform and read-only storage buffers, the storage of the textures it
   samples. 0 when it cannot be listed or the draw may write memory. Each stage's shader is the variant prog_fit gives the
   draw under the state at its place (read-only, as prog_prediction_stages): a stage with no key keeps its shader, another
   takes the variant of its signature (stage_sig), and one never drawn (prog_fit would translate it) cannot be judged. */
static int csh_draw_reads(NvProg *pr, const p_draw *dw, const p_draw_idx *di, csh_rng *r, int *n) {
    if (!pr || pr->missing || pr->geo || pr->sh[2] || pr->sh[3] || pr->sh[4] || S.raster_discard) return 0;
    if ((dw && (dw->ind || dw->prim == 0x40)) || (di && di->ind)) return 0;   // indirect: the record the GPU reads; mesh: g_mtk's stages
    for (int k = 0; k < 16; k++) if (S.vbuf[k].address && !csh_add(r, n, S.vbuf[k].address, S.vbuf[k].size)) return 0;   // no address: nothing bound; a size of 0 is an unknown extent here (the pool decides, vattr_base)
    if (di && !csh_add(r, n, di->ibuf, (uint64_t)(di->count > 0 ? di->count : 0) * 4 + 16)) return 0;   // as nxnative: the widest index type, and a margin
    for (int st = 0; st < 2; st++) {
        __unsafe_unretained NvShader *sh = pr->sh[st];
        if (sh && pr->key[st]) { uint64_t sg = stage_sig(st); if (sg != pr->sig[st]) { sh = pr->alt[st][@(sg)]; if (!sh) return 0; } }
        if (!sh) continue;
        if (sh->stage < 0 || sh->stage >= 6) return 0;
        for (int i = 0; i < sh->rf.nb; i++) { const nvn_rbind *b = &sh->rf.b[i];
            switch (b->kind) {
                case NVN_RB_CBUF: case NVN_RB_UBOP: if (b->reg >= 16 || !csh_add(r, n, S.ubo[sh->stage][b->reg].addr, S.ubo[sh->stage][b->reg].size)) return 0; break;
                case NVN_RB_SBUFP: if (b->rw || b->reg >= 16 || !csh_add(r, n, S.ssbo[sh->stage][b->reg].addr, S.ssbo[sh->stage][b->reg].size)) return 0; break;
                case NVN_RB_TEX: { if (b->reg >= 128) return 0;
                    uint64_t h = S.tex[sh->stage][b->reg]; if (!(h & 0xfffff)) break;   // nothing bound: the dummy texture
                    tex_t t; if (!csh_tex(h, &t) || !csh_add(r, n, (uint64_t)(uintptr_t)t.mem, t.L.size)) return 0;
                    break; }
                case NVN_RB_SAMP: case NVN_RB_SAMPT: case NVN_RB_SUPPORT: case NVN_RB_C1: case NVN_RB_DRV0: case NVN_RB_DRV2: break;   // no guest memory (cs_rangeless)
                default: return 0;   // TEXP, SAMPP, SBUFU, GMEM, GMEML, IMG, TBUF, GEO: writes memory, or reads memory not listed here
            } } }
    return 1;
}
/* A dispatch at its place in the stream (S as it is there): the storage buffers it may write, and whether it samples the
   pass's depth (*depth = 1). 0 when it cannot run ahead: an indirect grid, a binding with no listed range, a uniform or
   storage buffer over an attachment's storage (the draws before it write their attachments), or a sampled colour
   attachment of the pass. */
static int csh_cs(NvShader *cs, const p_dispatch *dp, csh_rng *w, int *nw, int *depth) {
    if (!cs || cs->builtin || dp->indirect) return 0;
    for (int i = 0; i < cs->rf.nb; i++) { const nvn_rbind *b = &cs->rf.b[i];
        switch (b->kind) {
            case NVN_RB_SBUFP: { if (b->reg >= 16) return 0; const p_bind_buf *u = &S.ssbo[5][b->reg];
                if (csh_attachment_hit(u->addr, u->size) || !csh_add(w, nw, u->addr, u->size)) return 0; break; }
            case NVN_RB_CBUF: case NVN_RB_UBOP: if (b->reg >= 16 || csh_attachment_hit(S.ubo[5][b->reg].addr, S.ubo[5][b->reg].size)) return 0; break;
            case NVN_RB_TEX: { if (b->reg >= 128) return 0;
                uint64_t h = S.tex[5][b->reg]; if (!(h & 0xfffff)) break;
                tex_t t; if (!csh_tex(h, &t)) return 0;
                if (R.has_rt) { csh_rng s[1]; int ns = 0;
                                if (t.mem && t.L.size && !csh_add(s, &ns, (uint64_t)(uintptr_t)t.mem, t.L.size)) return 0;   // its storage cannot be told
                                for (int k = 0; k < R.rt.n && k < 8; k++) if (csh_tex_alias(&t, R.rt.color[k])) return 0;   // it would miss what the draws before it drew
                                if (csh_tex_alias(&t, R.rt.depth)) *depth = 1; }
                break; }
            case NVN_RB_SAMP: case NVN_RB_SAMPT: case NVN_RB_SUPPORT: case NVN_RB_C1: case NVN_RB_DRV0: case NVN_RB_DRV2: break;
            default: return 0;   // TEXP, SAMPP, SBUFU, GMEM, GMEML, IMG, TBUF, GEO
        } }
    return 1;
}
// Commands that end the scan before state_op is asked (it takes render conditions and SetRenderEnable as state)
static int csh_stop_op(uint32_t op, const void *a) {
    if (op == OP_BARRIER) { uint32_t bits; memcpy(&bits, a, sizeof bits); return bits != 0; }
    return op == OP_UPDATE_UB || op == OP_RENDER_COND || op == OP_RENDER_ENABLE;
}
// The program of a draw (graphics) or a dispatch (compute) met by the scan, as geo_run finds it
static NvProg *csh_prog(const prog_t *p) {
    if (!p) return nil;
    NvProg *pr = p->serial ? (__bridge NvProg *)serial_ptr(p->serial) : nil;
    if (!pr) { g_prog_prefetch = 1; pr = prog_get(p); g_prog_prefetch = 0; }   // a program met for the first time is predicted from here, before dispatch() / draw_inner ask for it with g_prog_for_draw; its stages come in the background (missing: refused)
    return pr;
}
/* Whether a dispatch comes before the first command that would stop csh_try's scan, by command codes only: most passes have
   none, and then S and R are not saved and restored for nothing. The state commands are state_op's, without the two it
   takes that stop the scan (csh_stop_op). */
static int csh_ahead(void) {
    fz_cursor c = {.p = g_exec_next, .ret_n = g_ret_n}; memcpy(c.ret, g_ret, (size_t)g_ret_n * sizeof *g_ret);
    for (int guard = 0; guard < CSH_OPS; guard++) {
        const uint8_t *q; op_hdr h; const void *a;
        if (!fz_next(&c, &q, &h, &a)) return 0;
        if (h.op == OP_DISPATCH) return 1;
        if (csh_stop_op(h.op, a)) return 0;
        switch (h.op) {
            case OP_BARRIER: case OP_DRAW: case OP_DRAW_IDX:
            case OP_SCISSOR: case OP_BIND_PROGRAM: case OP_BIND_STATE: case OP_BIND_VATTR: case OP_BIND_VSTREAM: case OP_BIND_VBUF: case OP_BIND_UBO: case OP_BIND_SSBO:
            case OP_BIND_TEX: case OP_BIND_SAMP: case OP_BIND_IMG: case OP_STENCIL: case OP_POLY_OFFSET: case OP_VIEWPORTS: case OP_DEPTH_RANGE: case OP_BLEND_COLOR:
            case OP_COPY_STRIDE: case OP_DEPTH_CLAMP: case OP_RASTER_DISCARD: case OP_PUSH_CONST:
                continue;
            default: return 0;
        }
    }
    return 0;   // the full scan stops at the same count
}
// The statistics line: the current frame, the dispatches moved, the full scans and each stop counter by name (the first moved dispatch, then every 10,000)
static void csh_log_stats(void) {
    char b[512]; int n = 0;
    for (int i = 0; i < CSH_STOPS && n < (int)sizeof b; i++) n += snprintf(b + n, sizeof b - (size_t)n, " %s=%llu", csh_stop_name[i], (unsigned long long)g_csh.stop[i]);
    MLOG("[cs-hoist] frame %llu: moved=%llu scans=%llu stops:%s", (unsigned long long)atomic_load(&g_cur_frame), (unsigned long long)g_csh.moved, (unsigned long long)g_csh.scans, b);
}
// The draw about to open a pass (pr0, dw0 / di0; no pass open): runs the dispatches that can come before the pass now
static void csh_try(NvProg *pr0, const p_draw *dw0, const p_draw_idx *di0) {
    if (g_csh_probe_neg == 2) return;
    if (g_csh.sub != g_sub_serial) { g_csh.n = 0; g_csh.sub = g_sub_serial; }   // moves of an earlier submission the replay never met
    int clear = R.clear_d || R.clear_s; for (int i = 0; i < 8; i++) clear |= R.clear_c[i];   // the pass's load action comes before anything a moved dispatch does
    if (g_eye_pass || g_frz_state || g_fz.active || g_fz_checking || g_defer_replaying || g_defer_nact || g_cg.replaying || g_lay.active || tbdr_on() || g_geo_ras.pr
        || clear || !g_exec_next || g_ret_n > 8) { g_csh.stop[9]++; return; }
    if (!csh_ahead()) { g_csh.stop[8]++; return; }
    g_csh.scans++;
    totk_vpool_view_sync(&g_csh_view);   // csh_add judges every range by the storage behind it
    static csh_rng rd[CSH_RN], wr[CSH_RN]; int nrd = 0;
    if (!csh_draw_reads(pr0, dw0, di0, rd, &nrd)) { g_csh.stop[0]++; return; }
    static typeof(S) Ssave; memcpy(&Ssave, &S, sizeof S); typeof(R) Rsave = R; int pso_dirty = g_pso_dirty, dss_dirty = g_dss_dirty, moved = 0;
    int dwrote = R.has_rt && R.rt.depth && (S.ds.dw || S.ds.st);   // a draw of the stretch writes depth or stencil (a compute view may read stencil)
    fz_cursor cur = {.p = g_exec_next, .ret_n = g_ret_n}; memcpy(cur.ret, g_ret, (size_t)g_ret_n * sizeof *g_ret);
    int why = 10;   // the stop counter this scan ends in: the scan limit unless a break below says otherwise
    for (int guard = 0; guard < CSH_OPS; guard++) {
        const uint8_t *q; op_hdr h; const void *a;
        if (!fz_next(&cur, &q, &h, &a)) { why = cur.bad ? 6 : 11; break; }   // the end of the submission or an event wait ends it too
        if (csh_stop_op(h.op, a)) { why = 5; break; }
        if (h.op == OP_BARRIER) continue;   // without bits
        if (h.op == OP_DRAW || h.op == OP_DRAW_IDX) {
            if (!csh_draw_reads(csh_prog(S.prog), h.op == OP_DRAW ? a : NULL, h.op == OP_DRAW_IDX ? a : NULL, rd, &nrd)) { why = 1; break; }
            if (R.has_rt && R.rt.depth && (S.ds.dw || S.ds.st)) dwrote = 1;
            continue; }
        if (h.op == OP_DISPATCH) {
            const p_dispatch *dp = a;
            if (!dp->indirect && (!dp->x || !dp->y || !dp->z)) continue;   // an empty grid: dispatch() runs nothing and ends no pass
            { int ran = 0; for (int i = 0; i < g_csh.n; i++) ran |= g_csh.op[i] == q;   // already run ahead by an earlier scan the replay has not passed yet
              if (ran) { why = 2; break; } }   // (no pass opened since: no targets, or a draw in between ended it)
            NvProg *cpr = csh_prog(S.cprog ? S.cprog : S.prog);   // as dispatch()
            int nwr = 0, depth = 0;
            if (!cpr || cpr->missing || !csh_cs(cpr->sh[5], dp, wr, &nwr, &depth)) { why = 2; break; }
            if (depth && dwrote) { why = 7; break; }   // it would miss depth the draws before it wrote
            if (csh_hit(wr, nwr, rd, nrd)) { why = 3; break; }   // the draws before it read what it writes
            if (g_csh.n >= CSH_MAX) { why = 4; break; }
            PD("H %llu dispatch %s moved ahead of the pass%s", (unsigned long long)(g_stat_pass + 1), cpr->sh[5]->key, depth ? " (samples the pass's depth, which no draw before it wrote)" : "");
            dispatch(dp); g_csh.op[g_csh.n++] = q; g_csh.moved++; moved++;
            if (g_csh.moved == 1 || g_csh.moved % 10000 == 0) csh_log_stats();
            continue; }
        if (state_op(h.op, a)) continue;
        why = 5; break;   // anything else may end the pass, write memory or depend on the order (targets, copies, clears, events, counters)
    }
    g_csh.stop[why]++;
    memcpy(&S, &Ssave, sizeof S); R = Rsave; args_dirty_all(); g_pso_dirty = pso_dirty || moved; g_dss_dirty = dss_dirty || moved;
    { static int once; if (moved && !once++) MLOG("[cs-hoist] compute dispatches run ahead of the pass they would split: first case pass %llu, %d dispatches", (unsigned long long)g_stat_pass + 1, moved); }
}

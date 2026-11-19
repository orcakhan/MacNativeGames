/* Compute dispatches moved ahead of the render pass they would split (TOTK_CS_HOIST; port of seedds/nxnative's cs_hoist_try, MIT).
   Metal cannot run a compute dispatch inside a render pass: dispatch() ends the pass, and the next draw opens another one on
   the same targets (the fixed cost of a pass, and a store and a load of every attachment). When a draw opens a pass, the
   commands after it are scanned up to the first one that may end the pass or depend on the order (anything but draws,
   dispatches, pure state and barriers without bits); each dispatch met on the way runs right away, before the pass opens,
   when it writes nothing the draws before it in that stretch read, and the replay skips it where it meets it (csh_take).
   As geo_run: the scan applies the state commands to S and R (state_op) and restores both after; a moved command counts only
   in the submission it was moved in (g_sub_serial), since the game records into the same command memory every frame.
   This version lists only storage and uniform buffers: a draw with any other binding, a writable storage buffer, vertex,
   index or indirect buffers, or a geometry stage, and a dispatch with any other binding or an indirect grid, stop the scan.
   Not while another mechanism replays or rewrites these commands (stereo eyes, world freeze, pass fusion and deferral, cube
   groups, layered passes, TBDR, a geometry draw's raster), with a pending clear, past the cursor's 8 return addresses, or once
   virtual-pool aliases exist (totk_vpool_aliases_used: address ranges compared here may then name the same storage). A
   dispatch already run ahead and not yet met by the replay (a later draw scanned again with no pass opened) stops the scan.
   TOTK_CS_HOIST=1 on (off by default for now). */
static int g_csh_probe_neg;   // probe-gpu-cs-hoist negative controls: 1 csh_take never skips (a moved dispatch runs again), 2 the scan does not run
enum { CSH_MAX = 64, CSH_RN = 1024, CSH_OPS = 4096 };
/* op: the dispatch commands run ahead and not yet met by the replay, in submission sub; moved: dispatches run ahead; scans:
   full scans; stop[]: why scans ended or did not run: 0 the first draw's reads cannot be listed, 1 a later draw's, 2 a dispatch
   refused, 3 a dispatch writes what a draw before it reads, 4 the dispatch limit, 5 another command or a barrier, 6 a bad
   cursor, 7 depth already written, 8 the pre-scan found no dispatch, 9 refused at entry */
static struct { const uint8_t *op[CSH_MAX]; int n; uint64_t sub, moved, scans, stop[10]; } g_csh;
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
static int csh_add(csh_rng *r, int *n, uint64_t a, uint64_t sz) {
    if (!a) return 1;   // not bound
    if (!sz || sz > UINT64_MAX - a || *n >= CSH_RN) return 0;   // an unknown extent
    r[(*n)++] = (csh_rng){a, a + sz}; return 1;
}
static int csh_hit(const csh_rng *a, int na, const csh_rng *b, int nb) { for (int i = 0; i < na; i++) for (int j = 0; j < nb; j++) if (a[i].lo < b[j].hi && b[j].lo < a[i].hi) return 1; return 0; }
// The memory a draw reads (its uniform and read-only storage buffers); 0 when it cannot be listed or the draw may write memory
static int csh_draw_reads(NvProg *pr, const p_draw *dw, const p_draw_idx *di, csh_rng *r, int *n) {
    if (!pr || pr->missing || pr->geo || pr->sh[2] || pr->sh[3] || pr->sh[4] || di || (dw && (dw->ind || dw->prim == 0x40))) return 0;
    for (int k = 0; k < 16; k++) if (S.vbuf[k].address) return 0;
    for (int st = 0; st < 2; st++) { __unsafe_unretained NvShader *sh = pr->sh[st]; if (!sh) continue;
        if (sh->stage < 0 || sh->stage >= 6) return 0;
        for (int i = 0; i < sh->rf.nb; i++) { const nvn_rbind *b = &sh->rf.b[i];
            switch (b->kind) {
                case NVN_RB_CBUF: case NVN_RB_UBOP: if (b->reg >= 16 || !csh_add(r, n, S.ubo[sh->stage][b->reg].addr, S.ubo[sh->stage][b->reg].size)) return 0; break;
                case NVN_RB_SBUFP: if (b->rw || b->reg >= 16 || !csh_add(r, n, S.ssbo[sh->stage][b->reg].addr, S.ssbo[sh->stage][b->reg].size)) return 0; break;
                default: return 0; } } }
    return 1;
}
// A dispatch at its place in the stream (S as it is there): the storage buffers it may write; 0 when it cannot run ahead
static int csh_cs(NvShader *cs, const p_dispatch *dp, csh_rng *w, int *nw) {
    if (!cs || cs->builtin || dp->indirect) return 0;
    for (int i = 0; i < cs->rf.nb; i++) { const nvn_rbind *b = &cs->rf.b[i];
        switch (b->kind) {
            case NVN_RB_SBUFP: if (b->reg >= 16 || !csh_add(w, nw, S.ssbo[5][b->reg].addr, S.ssbo[5][b->reg].size)) return 0; break;
            case NVN_RB_CBUF: case NVN_RB_UBOP: if (b->reg >= 16) return 0; break;   // reads: the draws before it write only their attachments (the check against attachment storage comes in Task 2)
            default: return 0; } }
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
    if (!pr) { g_prog_prefetch = 1; pr = prog_get(p); g_prog_prefetch = 0; }
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
// The draw about to open a pass (pr0, dw0 / di0; no pass open): runs the dispatches that can come before the pass now
static void csh_try(NvProg *pr0, const p_draw *dw0, const p_draw_idx *di0) {
    if (g_csh_probe_neg == 2) return;
    if (g_csh.sub != g_sub_serial) { g_csh.n = 0; g_csh.sub = g_sub_serial; }   // moves of an earlier submission the replay never met
    int clear = R.clear_d || R.clear_s; for (int i = 0; i < 8; i++) clear |= R.clear_c[i];   // the pass's load action comes before anything a moved dispatch does
    if (g_eye_pass || g_frz_state || g_fz.active || g_fz_checking || g_defer_replaying || g_defer_nact || g_cg.replaying || g_lay.active || tbdr_on() || g_geo_ras.pr
        || clear || !g_exec_next || g_ret_n > 8 || totk_vpool_aliases_used()) { g_csh.stop[9]++; return; }   // virtual aliases: guest address ranges no longer tell storage apart
    if (!csh_ahead()) { g_csh.stop[8]++; return; }
    g_csh.scans++;
    static csh_rng rd[CSH_RN], wr[CSH_RN]; int nrd = 0;
    if (!csh_draw_reads(pr0, dw0, di0, rd, &nrd)) { g_csh.stop[0]++; return; }
    static typeof(S) Ssave; memcpy(&Ssave, &S, sizeof S); typeof(R) Rsave = R; int pso_dirty = g_pso_dirty, dss_dirty = g_dss_dirty, moved = 0;
    fz_cursor cur = {.p = g_exec_next, .ret_n = g_ret_n}; memcpy(cur.ret, g_ret, (size_t)g_ret_n * sizeof *g_ret);
    for (int guard = 0; guard < CSH_OPS; guard++) {
        const uint8_t *q; op_hdr h; const void *a;
        if (!fz_next(&cur, &q, &h, &a)) { if (cur.bad) g_csh.stop[6]++; break; }   // the end of the submission or an event wait ends it too
        if (csh_stop_op(h.op, a)) { g_csh.stop[5]++; break; }
        if (h.op == OP_BARRIER) continue;   // without bits
        if (h.op == OP_DRAW || h.op == OP_DRAW_IDX) {
            if (!csh_draw_reads(csh_prog(S.prog), h.op == OP_DRAW ? a : NULL, h.op == OP_DRAW_IDX ? a : NULL, rd, &nrd)) { g_csh.stop[1]++; break; }
            continue; }
        if (h.op == OP_DISPATCH) {
            const p_dispatch *dp = a;
            if (!dp->indirect && (!dp->x || !dp->y || !dp->z)) continue;   // an empty grid: dispatch() runs nothing and ends no pass
            { int ran = 0; for (int i = 0; i < g_csh.n; i++) ran |= g_csh.op[i] == q;   // already run ahead by an earlier scan the replay has not passed yet
              if (ran) { g_csh.stop[2]++; break; } }   // (no pass opened since: no targets, or a draw in between ended it)
            NvProg *cpr = csh_prog(S.cprog ? S.cprog : S.prog);   // as dispatch()
            int nwr = 0;
            if (!cpr || cpr->missing || !csh_cs(cpr->sh[5], dp, wr, &nwr)) { g_csh.stop[2]++; break; }
            if (csh_hit(wr, nwr, rd, nrd)) { g_csh.stop[3]++; break; }
            if (g_csh.n >= CSH_MAX) { g_csh.stop[4]++; break; }
            dispatch(dp); g_csh.op[g_csh.n++] = q; g_csh.moved++; moved++;
            continue; }
        if (state_op(h.op, a)) continue;
        g_csh.stop[5]++; break;   // anything else may end the pass, write memory or depend on the order (targets, copies, clears, events, counters)
    }
    memcpy(&S, &Ssave, sizeof S); R = Rsave; args_dirty_all(); g_pso_dirty = pso_dirty || moved; g_dss_dirty = dss_dirty || moved;
    { static int once; if (moved && !once++) MLOG("[cs-hoist] compute dispatches run ahead of the pass they would split: first case pass %llu, %d dispatches", (unsigned long long)g_stat_pass + 1, moved); }
}

# Dispatches de compute antes do render pass — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** um dispatch de compute entre os draws de um render pass roda antes do pass quando isso não muda nada do que os draws anteriores leem, e o replay o pula depois, de modo que o pass não quebra.

**Architecture:** um arquivo novo `nvn_cs_hoist.inc`, incluído em `nvn_mtl.m` logo depois de `nvn_geometry_rt.inc`, com o exame (`csh_try`) chamado em `draw_inner` no último ponto antes de o pass abrir, e o pulo no `case OP_DISPATCH` de `mtl_exec_list`. Segue o padrão do `geo_run` (salva/restaura `S` e `R`, lista de ponteiros de comando por submissão) e as verificações do `cs_hoist_try` do nxnative, adaptadas aos helpers do fork (`fz_cursor`/`fz_next`, `state_op`, `bound_tex`).

**Tech Stack:** Objective-C/C (Metal 4), runtime de `games/totk` (BotW/TOTK; OOT pelo link `games/oot/third_party/d2r_gfx`), probes de GPU do Makefile de `games/totk`.

**Spec:** `docs/superpowers/specs/2026-11-19-compute-hoist-design.md` (aprovada em 2026-11-19).

## Global Constraints

- Switch: `TOTK_CS_HOIST` (`0` desliga, `1` liga). Padrão final: ligado, exceto em builds `GAME_OOT` (padrão desligado; `TOTK_CS_HOIST=1` liga). Até a Task 5, o padrão é desligado em todos os builds.
- Nenhuma regra por jogo ou por chave de shader.
- O exame não roda com: `g_eye_pass != 0`, `g_frz_state`, `g_fz.active`, `g_fz_checking`, `g_defer_replaying`, `g_cg.replaying`, `g_lay.active`, `tbdr_on()`, `g_geo_ras.pr`, clear pendente (`R.clear_c[0..7]`, `R.clear_d`, `R.clear_s`), `!g_exec_next`, `g_ret_n > 8`.
- O exame para em: `OP_BARRIER` com bits != 0, `OP_UPDATE_UB`, `OP_RENDER_COND`, `OP_RENDER_ENABLE`, `OP_TF_STATE`, qualquer comando que `state_op` não aceita, 4096 comandos, 64 dispatches movidos, cursor com `bad`.
- Commits pelo skill `/commit` (Conventional Commits, mensagem em inglês, no estilo do repo); um commit por task.
- Os arquivos em `docs/superpowers/` não entram no PR para o upstream (decisão de 2026-11-19).
- Shell é zsh: aspas em argumentos com `[ ] * ?`; nada de variáveis `status`, `path`; `sed -i ''`.

## Review Focus

1. **Lista de pulos válida só na submissão em que foi feita:** o jogo regrava a mesma memória de comandos todo frame; um ponteiro movido e não alcançado (draw pulado, render desligado) não pode pular o dispatch do frame seguinte. → Task 1, cenário `G`.
2. **O draw que disparou o exame não abre o pass** (scissor vazio, `cg_take`, shader faltando): o dispatch já rodou e tem que rodar uma vez só. O gancho fica depois de todos os `return` antecipados de `draw_inner`. → Task 1, cenário `H`.
3. **Dispatch cujo programa de compute ainda não foi traduzido** (shaders assíncronos): o exame recusa (não move), o replay segue o caminho atual de `dispatch()`. → Task 2, cenário `F`.
4. **Replay de olhos no VR:** com `g_eye_pass != 0` nada é movido. → Task 2, cenário `V`.
5. **Draw que pode escrever memória ou ler memória que não dá para listar** (storage gravável, imagem, `NVN_RB_TEXP`, `NVN_RB_SBUFU`, `NVN_RB_GMEM`/`GMEML`, indireto): o exame para nele. → Task 2, cenário `W`.

---

### Task 0: Script de medição (scratchpad, sem commit)

**Files:**
- Create: `$SCRATCH/measure.sh`, com `$SCRATCH` = `/private/tmp/claude-501/-Users-luisz-orca-workspaces-MacNativeGames-nxnative/dad7f38c-1611-4370-94cb-f9a315830f2d/scratchpad`

**Interfaces:**
- Produces: `measure.sh <botw|totk> <tag> [env KEY=VAL ...]` → escreve `$SCRATCH/m/<game>-<tag>/{windows.txt,passdump.txt,summary.txt,shot.png,log}`.

- [ ] **Step 1: Escrever o script** com o protocolo da linha de base, sem mudar nada dele: abre o executável do app (`~/Applications/Breath of the Wild.app/Contents/MacOS/BotW` ou `/Applications/Tears of the Kingdom.app/Contents/MacOS/TOTK`) com `TOTK_DEBUG_LOG=1 TOTK_INPUT_FILE=<cmds>` e as variáveis extras; espera duas linhas `计时 至帧`; envia `key 38 200` três vezes, com 4 s e 3 s entre elas (título → lista → carregar); espera o GPU p50 de uma janela passar de 3 ms; espera 150 s; grava 60 s de linhas `计时 至帧` em `windows.txt`; envia `passdump 3` e grava as linhas `[pass]` em `passdump.txt`; envia `wshot`; envia `close` e espera o processo sair. `summary.txt` traz frame p50 médio, mínimo e máximo, GPU p50 médio, mínimo e máximo, envio p50 médio, ciclos por frame da última linha `翻译细项`, passes por frame e passes fechados na linha de `rp_end()` de `dispatch()`, agrupados em mesmos alvos/outros alvos (o awk da linha de base). A linha de `rp_end()` em `dispatch()` é achada por grep no `nvn_mtl.m` do commit gravado no app (`MNGSourceCommit`).
- [ ] **Step 2: Conferir** rodando `measure.sh botw base2`. Esperado: frame p50 entre 10,9 e 11,7 ms, GPU p50 entre 8,0 e 8,2 ms, 14 quebras por frame em mesmos alvos. Se ficar fora, parar e relatar antes de seguir (a linha de base não é reproduzível).

### Task 1: Esqueleto do exame, pulo no replay e probe do caso simples

**Files:**
- Create: `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_cs_hoist.inc`
- Modify: `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_mtl.m` (include depois de `#include "nvn_geometry_rt.inc"`, ~linha 18795; chamada em `draw_inner`; `case OP_DISPATCH` em `mtl_exec_list`, ~linha 21158; probe perto de `mtl_probe_layer_merge`, ~linha 24892)
- Modify: `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_mtl.h` (declaração do probe)
- Modify: `games/totk/runtime/loader.c:658`, `games/totk/runtime/gpu_path_probe.m` (nome e descrição do probe), `games/totk/Makefile:187,216` (`probe-gpu-cs-hoist` nas duas listas)

**Interfaces:**
- Produces (em `nvn_cs_hoist.inc`):
  - `static int csh_on(void)` — lê `TOTK_CS_HOIST` uma vez; nesta task o padrão é 0; registra um `MLOG` quando ligado.
  - `static void csh_try(NvProg *pr0, const p_draw *dw0, const p_draw_idx *di0)` — o exame; roda dispatches movidos com `dispatch()`.
  - `static int csh_take(const uint8_t *op)` — 1 se `op` foi movido nesta submissão (e o tira da lista).
  - `static struct { const uint8_t *op[64]; int n; uint64_t sub, moved, scans, stop[10]; } g_csh;` — `sub` = `g_sub_serial` da lista; `stop[]` por motivo (índices fixados na Task 3).
  - `int mtl_probe_cs_hoist(void)` (em `nvn_mtl.m`, ao lado dos outros probes; usa `lp_rec`, `lp_rt`, `lp_draw`, `lp_sc`, `lp_prog`, `lp_end`).

- [ ] **Step 1: Confirmar que os probes rodam nesta máquina**

Run: `make -C games/totk probe-gpu-layer-merge PROBE_ROOT=/Users/luisz/MacNativeGames-work/totk/totk/`
Esperado: termina com JSON e sem `MDIE`. Se falhar por algo do ambiente, parar e relatar.

- [ ] **Step 2: Escrever o probe com o cenário A (que falha)**

`mtl_probe_cs_hoist` liga `TOTK_CS_HOIST=1` com `setenv` antes do primeiro uso. Monta um programa gráfico (vertex + fragment de cor fixa, como no layer probe) e um de compute (como no dispatch-chain probe: `NVN_RB_SBUFP` reg 0, `rw = 1`, kernel `s0[i] += 1`), um alvo 2D 8x8 RGBA8 e uma memória `s0` de 16 KiB em `mtl_pool_add`. Lista A: `prog(gráfico) · rt · sc · draw · bind ssbo s0 no estágio 5 · prog(compute) · dispatch 1x1x1 · prog(gráfico) · draw · end`.
Asserções do cenário A: `g_stat_pass` sobe 1; `g_csh.moved` sobe 1; `s0[0] == 1` lido de volta depois de `rp_end()` e da espera da submissão; os pixels do alvo com a cor dos dois draws.
Controles negativos (`TOTK_PROBE_NEGATIVE`): `=1` faz `csh_take` sempre devolver 0 (o dispatch roda duas vezes: `s0[0] == 2`, o probe tem que morrer); `=2` desliga o exame (2 passes, o probe tem que morrer).
Cenário G (Review Focus 1): deixar em `g_csh` o ponteiro do comando de dispatch da lista A com `sub = g_sub_serial - 1` (um movimento de uma submissão anterior que o replay nunca alcançou), abrir uma submissão nova (`mtl_sub_begin`) com o exame desligado só para essa lista (`static int g_csh_probe_neg;` no `.inc`, no padrão do `g_lay_probe_neg`: o probe também usa ele para os negativos 1 e 2), rodar a lista A e checar que `s0[0]` sobe exatamente 1 (o ponteiro antigo não pulou o dispatch novo).
Cenário H (Review Focus 2): primeiro draw com scissor de área zero (`lp_sc(w, 0, 0, 0, 0)`), depois `sc` normal, dispatch, draw: `s0[0]` sobe exatamente 1.

- [ ] **Step 3: Rodar e ver falhar**

Run: `make -C games/totk probe-gpu-cs-hoist PROBE_ROOT=/Users/luisz/MacNativeGames-work/totk/totk/`
Esperado: FAIL no cenário A, com 2 passes e `moved` 0.

- [ ] **Step 4: Implementar `csh_on`, `csh_take`, o pulo e `csh_try` no caso simples**

- Gancho em `draw_inner`: logo antes de `if (!g_enc) { g_fd_dw = dw; g_fd_di = di; }` (depois do cube group e de todos os `return` antecipados): `if (!g_enc && csh_on()) csh_try(pr, dw, di);`.
- `mtl_exec_list`: `case OP_DISPATCH: if (!csh_take(p)) dispatch(a); break;`. `csh_take` esvazia a lista quando `g_csh.sub != g_sub_serial`.
- Forward declaration de `static void dispatch(const p_dispatch *dp);` antes do include.
- `csh_try`: aplica as recusas de entrada das Global Constraints; faz o pré-exame só por código de comando (há `OP_DISPATCH` antes do primeiro comando que pararia o exame? lista de estado como `csh_dispatch_ahead` do nxnative, com `OP_UPDATE_UB`, `OP_RENDER_COND` e `OP_RENDER_ENABLE` como parada); só então salva `S` (cópia estática, como `geo_run`), `R`, `g_pso_dirty`, `g_dss_dirty`; cursor `fz_cursor cur = {.p = g_exec_next}` com `g_ret` copiado para `cur.ret`; para cada comando: estado via `state_op`, draw acumula leituras, dispatch decide e roda `dispatch()`, guardando o ponteiro; no fim restaura `S`, `R`, `args_dirty_all()`, `g_pso_dirty |= moved`, `g_dss_dirty |= moved`.
- Nesta task, as leituras dos draws e as escritas dos dispatches usam só storage (`NVN_RB_SBUFP`) e uniform (`NVN_RB_CBUF`/`NVN_RB_UBOP`) por `sh->stage`; qualquer outro tipo de binding para o exame (as regras completas vêm na Task 2).

- [ ] **Step 5: Rodar e ver passar, inclusive os controles negativos**

Run: o comando do Step 3, depois o mesmo com `TOTK_PROBE_NEGATIVE=1` e com `TOTK_PROBE_NEGATIVE=2`.
Esperado: PASS; os dois negativos terminam em `MDIE`.

- [ ] **Step 6: Commit** (`/commit`), por exemplo `perf: compute dispatches between the draws of a pass can run ahead of it (TOTK_CS_HOIST=1, off by default)`.

### Task 2: Regras completas de dependência

**Files:**
- Modify: `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_cs_hoist.inc`, `nvn_mtl.m` (cenários novos no probe)

**Interfaces:**
- Consumes: `csh_try`, `g_csh`, `mtl_probe_cs_hoist` (Task 1).
- Produces: `static int csh_draw_reads(NvProg *pr, const p_draw *dw, const p_draw_idx *di, csh_rng *r, int *n)` e `static int csh_cs(NvShader *cs, const p_dispatch *dp, csh_rng *w, int *nw, int *depth)`, com `typedef struct { uint64_t lo, hi; } csh_rng;` (até 1024 faixas), como no nxnative.

- [ ] **Step 1: Escrever os cenários (que falham)** no `mtl_probe_cs_hoist`, cada um com a contagem de passes e de `moved`:
  - `B`: o vertex shader do draw tem `NVN_RB_CBUF` reg 0 apontando para `s0`; o dispatch escreve `s0` → não move, 2 passes.
  - `C`: alvo com depth, estado de depth com `dw = 1`, o compute amostra a textura de depth (`NVN_RB_TEX` com o handle registrado do depth) → não move, 2 passes. Variante `C2`: o mesmo com `dw = 0` → move, 1 pass.
  - `D`: `OP_BARRIER` com bits `0x12` entre o draw e o dispatch → não move, 2 passes; com bits 0 → move.
  - `E`: `OP_UPDATE_UB` entre o draw e o dispatch → não move.
  - `F` (Review Focus 3): o programa de compute marcado `missing` → não move, e o dispatch roda uma vez.
  - `V` (Review Focus 4): `g_eye_pass = 1` durante a lista → não move (devolver a 0 depois).
  - `W` (Review Focus 5): o fragment shader do draw tem `NVN_RB_SBUFP` com `rw = 1` → não move; com `NVN_RB_TEXP` → não move.
  - `X`: o compute amostra a textura de cor do pass (`NVN_RB_TEX` com o handle do alvo) → não move.
  - `Y`: dispatch indireto (`p_dispatch.indirect != 0`) → não move.
- [ ] **Step 2: Rodar e ver falhar** (comando da Task 1, Step 3). Esperado: falha no primeiro cenário cuja regra ainda não existe.
- [ ] **Step 3: Implementar `csh_draw_reads` e `csh_cs`** como as funções do nxnative com o mesmo nome (`/Volumes/DevProjects/others/nxnative/dm/gfx/nvn/nvn_mtl.m`, ~15610-15666), traduzidas: `S.ubo[sh->stage]`, `S.ssbo[sh->stage]`, `S.tex[sh->stage][reg]` com `bound_tex()` → `treg_t.t` (`mem`, `L.size`); sobreposição de armazenamento por `[mem, mem + L.size)` contra `R.rt.color[k]` e `R.rt.depth`; `S.vbuf[k]` (`address`, `size`) e o index buffer (`p_draw_idx.ibuf`); `ind != 0` em draw → para. Parada para tipos sem leitura listável: `NVN_RB_TEXP`, `NVN_RB_SBUFU`, `NVN_RB_GMEM`, `NVN_RB_GMEML`, `NVN_RB_IMG`, `NVN_RB_TBUF`, `NVN_RB_SBUFP` com `rw` em draw, `NVN_RB_GEO`, `pr->geo`, `pr->sh[2..4]`, `S.raster_discard`. "Depth escrito" quando `R.rt.depth && (S.ds.dw || S.ds.st)`. Programa de compute com `missing` → para.
- [ ] **Step 4: Rodar e ver passar** (todos os cenários da Task 1 e da Task 2, mais os dois negativos).
- [ ] **Step 5: Commit** (`/commit`).

### Task 3: Estatística e dump de passes

**Files:**
- Modify: `nvn_cs_hoist.inc`

**Interfaces:**
- Produces: índices de `g_csh.stop[]`: 0 primeiro draw, 1 draw seguinte, 2 dispatch recusado, 3 conflito de memória, 4 limite de dispatches, 5 outro comando ou barreira, 6 cursor inválido, 7 depth já escrito, 8 pré-exame sem dispatch, 9 recusa de entrada.

- [ ] **Step 1:** Linha `PD("H %llu dispatch %s moved ahead of the pass%s", ...)` para cada dispatch movido (como no nxnative).
- [ ] **Step 2:** `MLOG` no primeiro dispatch movido e depois a cada 10.000, com o frame atual (`g_cur_frame`), `moved`, `scans` e os dez `stop[]` com nome.
- [ ] **Step 3:** Rodar o probe da Task 2 (tem que passar sem mudança) e conferir a linha `MLOG` no JSON/log do probe.
- [ ] **Step 4: Commit** (`/commit`).

### Task 4: Validação nos jogos (imagem e quebras)

**Files:** nenhum no repo; resultados em `$SCRATCH/m/`.

- [ ] **Step 1:** Atualizar os apps com o runtime da branch: `/opt/homebrew/opt/python@3.14/bin/python3.14 update_runtime.py "$HOME/Applications/Breath of the Wild.app"` e o mesmo para `/Applications/Tears of the Kingdom.app`. Esperado: `done in N s ... has the runtime of this repository` nos dois.
- [ ] **Step 2:** `measure.sh botw off TOTK_CS_HOIST=0` e `measure.sh botw on TOTK_CS_HOIST=1`. Esperado em `on`: as quebras em mesmos alvos caem de 14 para perto de 0 (o que sobrar tem motivo na linha `MLOG` da Task 3); `off` igual à linha de base.
- [ ] **Step 3:** O mesmo no TOTK. Esperado: 7 quebras em `off`; em `on`, a do G-buffer some ou aparece com motivo (provavelmente `stop[7]`).
- [ ] **Step 4: Imagem:** em cada jogo, com `TOTK_CS_HOIST=0` e `=1`, `texdump <path com %d>` pelo arquivo de comandos no mesmo frame da cena parada; comparar os alvos 3D com RMSE ≤ 0,7% (tolerância do nxnative); a sobreposição 2D e as animações por relógio podem diferir. Se passar disso, parar e investigar antes da Task 5.
- [ ] **Step 5:** Se o dump mostrar quebras restantes com `SET_RT` dos mesmos alvos entre o draw e o dispatch, registrar quantas por frame para decidir a extensão deixada em aberto na spec (não implementar aqui).

### Task 5: Desempenho, padrão ligado e documentação

**Files:**
- Modify: `nvn_cs_hoist.inc` (`csh_on`: padrão 1, exceto `#ifdef GAME_OOT` → 0)
- Modify: `docs/performance-followups.md` ou o documento de desempenho que já descreve as otimizações de pass deste runtime (o construtor escolhe o que já cobre `TOTK_LAYER_MERGE`/`TOTK_CUBE_MERGE`; `git grep -l TOTK_LAYER_MERGE docs`), com a regra, o switch e as medições.

- [ ] **Step 1:** ABBA no BotW: `off`, `on`, `on`, `off` com `measure.sh` e 2 min de pausa entre as rodadas. Idem no TOTK.
- [ ] **Step 2: Aplicar o critério da spec:** fps sobe fora da faixa da linha de base → ligado; fps igual e GPU p50 menor → ligado, e a Task 6 vira obrigatória; fps cai → manter desligado, relatar e parar o plano aqui. Os ciclos por frame do envio (`翻译细项`) vão no relatório, antes e depois.
- [ ] **Step 3:** Ligar o padrão (exceto OOT) e documentar.
- [ ] **Step 4:** Rodar de novo o probe da Task 2 sem `setenv` forçado (confirma o padrão) e um `measure.sh botw default` sem variável (confirma `moved > 0`).
- [ ] **Step 5: Commit** (`/commit`).

### Task 6: A/B no iPad (obrigatória se o fps no Mac não subiu)

- [ ] **Step 1:** Seguir a receita de A/B do iPad na memória do projeto (`ipad-a16-perf-ab`): devicectl, `TOTK_DEBUG_LOG=1`, ABBA com pausas, mesma condição de carga, medir só depois de ~2 min, cap padrão; comparar GPU p50, ciclos do envio e o patamar de clock com `TOTK_CS_HOIST=0` e `=1`.
- [ ] **Step 2:** Relatar. Se piorar no iPad, voltar o padrão para desligado no iOS (`TARGET_OS_IPHONE`) num commit próprio.

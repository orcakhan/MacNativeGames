# Dispatches de compute antes do render pass (porte do `cs_hoist_try` do nxnative)

Data: 2026-11-19. Branch: `orcakhan/nxnative` (base `main` 778ab5f9).

## Intenção

No gfx de BotW/TOTK (`games/totk/third_party/d2r_gfx/gfx/nvn/nvn_mtl.m`), todo dispatch de compute que aparece
entre os draws de um render pass fecha o pass (`dispatch()` chama `rp_end()`), e o draw seguinte abre outro pass
nos mesmos alvos. Cada quebra custa o custo fixo de um pass (~35-50 µs no Apple GPU) e a gravação + releitura de
todos os anexos. O nxnative resolveu isso no BotW 1.9.0 (`cs_hoist_try`, `docs/reference/rendering.md`, seção
"Compute dispatches between the draws of a pass run ahead of it"): quando um draw abre um pass, os comandos à
frente são examinados, e cada dispatch que pode rodar antes do pass sem mudar nada do que os draws anteriores a ele
leem roda já, antes do pass abrir; o replay pula esse dispatch quando chega nele, e o pass fica aberto.

Por quê: mais fps com fps destravado; com fps travado, menos GPU e menos banda (energia), o que importa no iPad,
onde o clock cai para um patamar definido pela carga total.

## Linha de base (Mac M5 Pro, em janela, fps destravado, `main` 778ab5f9, 2026-11-19)

| | BotW 1.9.0 | TOTK 1.4.3 |
|---|---|---|
| Cena | save Great Plateau 18/11 23:38, câmera parada | save "Beneath Hyrule Castle" 19/11 13:49, câmera parada |
| Saída | 2560x1440, suavização MetalFX | 3022x1700 (interno 1920x1080) |
| Frame p50 (60 s depois de 2,5 min) | 11,30 ms (88,5 fps), 10,9-11,7 | 8,85 ms (113,1 fps), 8,76-8,96 |
| GPU p50 | 8,12 ms, 8,03-8,19 | 7,46 ms, 7,40-7,51 |
| Passes por frame | 137-138 | 92-96 |
| Passes fechados por dispatch | 14 por frame, todos reabertos nos mesmos alvos (5 no 2560x1440 com 4 cores + depth, 9 no 1280x720) | 7 por frame; só 1 reaberto nos mesmos alvos (G-buffer 2560x1440: 41 draws, dispatch, 110 draws) |

Logs: `botw-baseline.log` e `totk-baseline.log` no scratchpad da sessão (copiar para `analysis/` se forem
referência de PR). Medição: `TOTK_DEBUG_LOG=1`, linhas `计时 至帧` (janelas de 300 frames) e
`TOTK_INPUT_FILE` com `passdump 3`; a linha `Z ... pass_end ... at=nvn_mtl.m:<linha de rp_end em dispatch()>` conta
as quebras.

## Metas

- BotW: as quebras por dispatch reabertas nos mesmos alvos caem de 14 para perto de 0 por frame; o que sobrar tem
  motivo contado (linha de estatística).
- TOTK: a quebra do G-buffer some se a regra permitir; nenhuma regressão.
- Imagem idêntica: dump de texturas de um frame fixo com o porte ligado e desligado bate (dentro do ruído de
  animação por tempo de parede, como no nxnative).
- Ligado por padrão para BotW (1.6.0 e 1.9.0) e TOTK, desligável com `TOTK_CS_HOIST=0` (decisão do usuário,
  2026-11-19). **Desligado por padrão no Ocarina of Time** (`games/oot/third_party/d2r_gfx` é um link para esta
  mesma pasta; build com `GAME_OOT`): ele passa por caminhos que BotW/TOTK não usam (modo de barreiras do Mac
  `g_oot_bar_mode`, draws de mesh, dispatches indiretos, replay de VR) e ganha validação própria depois; até lá,
  `TOTK_CS_HOIST=1` liga para testes (decisão do usuário, 2026-11-19).

## Critério de sucesso (decisão do usuário, 2026-11-19)

Medido no protocolo da linha de base (BotW e TOTK, fps destravado):

- **fps destravado sobe** (frame p50 menor, fora da faixa de variação da linha de base): fica ligado.
- **fps igual, GPU p50 menor:** fica ligado (com fps travado vira economia de GPU/energia), e o A/B no iPad passa a
  ser etapa obrigatória para confirmar, não opcional.
- **fps cai:** desligado por padrão; investigar o custo do exame.
- Custo de CPU do exame (anti-meta abaixo): ciclos por frame do thread de envio (linha `翻译细项`, "每帧提交 周期"),
  antes e depois, nas mesmas cenas (decisão do construtor).

## Não-metas

- Forçar o caso em que a regra recusa (ex.: dispatch que amostra depth depois de draws que gravaram depth). Esses
  ficam quebrando o pass, e a estatística diz quantos são.
- VR (replay por olho, `g_eye_pass`): o porte fica desligado durante o replay de olhos.
- Mexer no mecanismo de geometry shader (`nvn_geometry_rt.inc`), no cube merge, no pass em camadas ou no TBDR.

## Anti-metas (falhou mesmo que "funcione")

- Qualquer mudança visível de imagem, partícula faltando, fora de lugar ou com um frame de atraso.
- Regra específica de jogo ou de shader (o nxnative evitou de propósito: as verificações são gerais).
- Custo de CPU no thread de envio maior que o ganho (o nxnative mediu 2,5% do thread de envio só para salvar e
  restaurar estado em todo pass; por isso o pré-exame barato antes do exame completo é obrigatório).

## Restrições do nosso fork

O fork divergiu do nxnative. O porte tem que usar o que já existe aqui e respeitar o que só existe aqui:

- Cursor de comandos: `fz_cursor` / `fz_next` (equivalente ao `op_cursor` / `op_next`), estado a partir de
  `g_exec_next` e `g_ret_n`/`g_ret`.
- Aplicação de estado no exame: `state_op` (atenção: aqui ele inclui `OP_RENDER_COND` e `OP_RENDER_ENABLE`, que
  o exame deve tratar como parada, não como estado).
- Padrão de "rodar antes e pular depois" já usado pelos draws com geometry shader (`geo_run` / `geo_draw`):
  cópia de `S` e `R`, `args_dirty_all()`, `g_pso_dirty`/`g_dss_dirty`, lista de ponteiros de comando válida só
  na submissão em que foi feita (`g_sub_serial`, como `g_geo_run_sub`).
- Faixas de memória lidas/escritas por estágio: `geo_access` / `geo_access_stage` são o análogo do
  `csh_draw_reads` / `csh_cs` do nxnative.
- Updates de uniform inline não fecham o pass aqui (renomeação, `upd_shadow`). O exame para em `OP_UPDATE_UB`.
- Outros mecanismos no ponto em que o draw abre o pass (`draw_inner`, perto de `if (!g_enc) { g_fd_dw = dw; ... }`):
  congelamento de mundo (`g_frz_state`, `g_fz`), deferral/fusão TBDR (`defer_try`, `fuse_try`, `hoist_try` de
  passes só de clear), cube merge (`cg_take` / `cg_flush`), pass em camadas (`g_lay`), commits no meio da submissão
  (`TOTK_CHUNK_DRAWS`), estágio de encode em pipeline (`rs_sync`). O porte não roda quando um desses está
  replayando ou em modo especial; onde a interação for incerta, recusa.

## Abordagens consideradas

1. **Porte da regra do nxnative adaptado aos helpers do fork, no padrão do `geo_run` (escolhida).** Verificações
   gerais de dependência de memória, sem regra por jogo; reaproveita cursor, `state_op` e o padrão de pular comando
   que já são testados aqui.
2. Regra específica do BotW (por chave do shader de partícula). Descartada: frágil e contra a anti-meta.
3. Rodar o dispatch depois do pass. Descartada: os draws depois do dispatch leem o que ele escreve.

## Comportamento (o que o construtor implementa)

Quando um draw vai abrir um pass (`!g_enc`, nenhum dos mecanismos especiais acima ativo, `TOTK_CS_HOIST` ligado,
fora do replay de olhos):

1. Pré-exame barato só por código de comando (como `csh_dispatch_ahead`): existe um `OP_DISPATCH` antes do primeiro
   comando que pararia o exame? Se não, nada a fazer (sem salvar estado).
2. Recusa se o pass tem clear pendente (`R.clear_c`, `R.clear_d`, `R.clear_s`).
3. Exame completo a partir de `g_exec_next`, com `S`/`R` salvos e restaurados no fim:
   - draws: acumula as faixas que leem (vertex, index, indireto, uniform, texturas por slot fixo com o
     armazenamento delas). Para se o draw pode escrever memória (storage buffer gravável, imagem, transform
     feedback), se as leituras não podem ser listadas (bindless/dinâmico, indireto indexado desconhecido,
     multi-draw), ou se é draw de geometry shader. Marca "depth escrito" se o draw grava depth ou stencil num
     pass com depth.
   - dispatch: recusa se indireto, bindless/dinâmico, imagem/storage desconhecido, uniform ou storage que cruza o
     armazenamento de um anexo, amostra um anexo de cor do pass, ou amostra o depth do pass depois de "depth
     escrito". Recusa se o que ele escreve cruza o que os draws anteriores no trecho leem. Senão, roda agora
     (`dispatch()` com o estado daquele ponto), registra o ponteiro do comando e continua.
   - para em: barreira do jogo com bits, `OP_UPDATE_UB`, `OP_RENDER_COND`, `OP_RENDER_ENABLE`, `OP_TF_STATE`,
     qualquer comando que não seja estado puro (`SET_RT`, cópias, clears, eventos, contadores...), limite de
     comandos / de dispatches movidos, cursor inválido.
4. No replay, `case OP_DISPATCH`: se o ponteiro está na lista da submissão atual, pula (e tira da lista).
5. Estatística periódica no log (dispatches movidos; motivos de parada por tipo) e linha `H` no dump de passes.

## Verificação

- Teste de GPU no binário, no padrão dos `probe-gpu-*` do Makefile (`mtl_probe_ub_rename`): um dispatch
  independente entre draws é movido uma vez e o pass não quebra; um que escreve o que um draw anterior lê não é
  movido; um que amostra depth depois de draw que grava depth não é movido; barreira não é atravessada;
  controles negativos (`TOTK_PROBE_NEGATIVE`) que têm que falhar.
- Jogo: dump de passes nas mesmas cenas, contando quebras por dispatch antes/depois; dump de texturas de um frame
  com `TOTK_CS_HOIST=0` e `=1`.
- Desempenho: mesmas cenas e protocolo da linha de base (em janela, fps destravado, 2,5 min de aquecimento,
  60 s de janelas), BotW e TOTK, ABBA. Depois, A/B no iPad com a receita da memória.

## Já respondido pelo código (verificação do construtor)

- Commits no meio da submissão (`TOTK_CHUNK_DRAWS`) só acontecem em `rp_begin_ex` sem pass aberto: não separam um
  dispatch movido do seu pass.
- Tolerância de imagem: o nxnative comparou dumps de textura a 0,7% de RMSE; aqui há o comando `texdump`.
- Dependências de memória: `geo_access` existe e pode ser estendido.

## Deixado para o construtor

- Nomes de funções/variáveis, onde exatamente encaixar no `draw_inner`, tamanhos de buffers de faixas.
- Se vale atravessar `SET_RT` de mesmos alvos (continuação de pass, `TOTK_RT_CONTINUE`) no exame: só se o dump
  depois da primeira versão mostrar quebras restantes com esse padrão.
- Divisão em commits pequenos (regra do usuário: commits frequentes, revisáveis isoladamente).

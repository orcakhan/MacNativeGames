# Experimento: dispatches de compute antes do render pass (porte do `cs_hoist_try` do nxnative)

Branch `orcakhan/nxnative`, 19 a 21/11/2026. **Estado: guardado, não enviado à main.** O ganho medido foi pequeno
demais para o custo de manter o código; falta uma medição (cena com partículas) para decidir de vez.

## O que é

No replay NVN→Metal do BotW/TOTK, todo dispatch de compute entre os draws de um render pass fecha o pass, e o draw
seguinte abre outro nos mesmos alvos. O porte (`nvn_cs_hoist.inc`) examina os comandos à frente quando um draw abre o pass
e roda antes cada dispatch que não muda nada que os draws anteriores leem; o replay pula o dispatch depois. O nxnative
mediu 101→111 fps num M2 Max (BotW 1.9.0, cena com partículas).

## Estado do código (HEAD da branch)

- Ligado por padrão só no BotW (`GAME_BOTW`, 1.6.0 e 1.9.0); desligado no TOTK e no OOT. `TOTK_CS_HOIST=0` desliga,
  outro valor liga; `flag cs_hoist <0|1>` no `TOTK_INPUT_FILE` alterna com o jogo aberto.
- Teste de GPU: `make -C games/totk probe-gpu-cs-hoist PROBE_ROOT=<work>/totk/totk/` (946 verificações, com controles
  negativos). Também passam `probe-gpu-ubo-snapshot`, `probe-gpu-ub-rename`, `probe-gpu-dispatch-chain`.
- Estatística no log: linha `[cs-hoist] frame N: moved=… stops: …`; no dump de passes, linhas `H` por dispatch movido.
- ~800 linhas: ~260 de lógica, ~390 de teste, ~100 na tabela de memória virtual (`totk_vpool.c`, comparação pelo
  armazenamento físico por trás dos aliases).
- Revisão final (modelo mais forte) + rodada de correções + re-revisão: sem pendência crítica ou importante.
  Ver `final-review.md` e `final-review-fixes-rereview.md`.

## Medições

Todas antes da última correção (a regra que recusa dispatches sobre cópias de uniforms, commit abfee4e0), que pode ter
reduzido os dispatches movidos. **Não foram repetidas depois dela.**

**Mac M5 Pro, BotW 1.9.0, em janela, fps destravado, 3022x1700, Link parado (Great Plateau), off/on/on/off:**

| Rodada | Frame p50 | GPU p50 | Passes quebrados por dispatch |
|---|---|---|---|
| off 1 | 7,95 ms | 5,33 ms | 15/frame |
| on 1 | 7,92 ms | 5,26 ms | 11/frame |
| on 2 | 7,93 ms | 5,25 ms | 11/frame |
| off 2 | 7,99 ms | 5,33 ms | 16/frame |

GPU −0,075 ms (−1,4%); frame igual (a cena é limitada pela CPU: 7,9 ms de frame contra 5,3 de GPU); custo de CPU do
envio dentro do ruído. ~6-7 dispatches movidos por frame.

**iPad A16, BotW 1.9.0, 30 fps travado, 1600x900 → 1920x1080 MetalFX, autoload, off/on/on/off:**
GPU p50 29,90 / 29,85 / 29,79 / 30,17 ms (−0,22 ms, −0,7%, faixas se sobrepõem); frame 33,4 ms em todas; sem custo de
envio mensurável. ~39% dos exames movem um dispatch.

**Imagem:** numa sessão só, alternando `flag cs_hoist`, a diferença entre ligado e desligado (RMSE 1,43-1,45%) não passa
do ruído de tempo com a mesma configuração (1,66-1,74%); frames consecutivos 0,12-0,16%. Capturas de sessões separadas
não servem (10-19% entre duas rodadas iguais: câmera e nuvens mudam a cada abertura).

## Por que o ganho é pequeno

- As quebras caras ficam: o dispatch no meio do G-buffer em resolução cheia (4 cores + depth) lê o depth que os draws
  antes dele gravaram, e por isso não pode ser movido (parada `depth_written`: 1/3 dos exames no Mac, 60% no iPad). O porte
  só tira as quebras baratas, em alvos de meia resolução.
- A cena medida tinha poucas partículas; o ganho do nxnative vinha de partículas.
- No Mac a cena é limitada pela CPU, então aliviar a GPU não sobe o fps.

## Para retomar

1. Atualizar o app do Mac com a branch (`update_runtime.py "<app>"`) e rodar `scripts/flagab.sh <tag>` num save com
   muitas partículas (fogo, chuva, fogueira; partículas que duram, não explosões), com o Link parado. Isso alterna o porte
   na mesma sessão (off on on off off on on off, 30 s cada).
2. Critério combinado: GPU −3% ou mais, ou fps maior numa cena limitada pela GPU → vale abrir o PR (antes, rodar o
   BotW 1.6.0 uma vez, que nunca rodou com o porte). Perto de 1% de novo → não enviar.
3. TOTK: nunca medido; para ligar lá, precisa de dump de passes, par de imagens com `flag cs_hoist` e ABBA.
4. iPad: gerar a .ipa com `--device-gpu applegpu_g15p` (sem isso, a primeira abertura monta ~17.900 pipelines, ~12 min).

## Arquivos

- `design.md`: spec aprovada (intenção, metas, anti-metas, critério de sucesso).
- `plan.md`: plano de implementação por tarefas.
- `ledger.md`: registro de execução com cada decisão (R1-R19), números brutos e pendências menores.
- `final-review.md`, `final-review-fixes-report.md`, `final-review-fixes-rereview.md`: revisão final e correções.
- `scripts/`: `measure.sh` (uma abertura medida, usada no ABBA), `flagab.sh` (A/B na mesma sessão), `imgab.sh` +
  `rmse.py` (comparação de imagem), `ipad.sh` (A/B no iPad via devicectl; `IPAD_UDID` no ambiente). Recriados a partir da
  sessão; os logs brutos se perderam com a limpeza do diretório temporário, os números estão neste README e no ledger.

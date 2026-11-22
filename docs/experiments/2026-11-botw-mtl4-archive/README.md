# Arquivo de pipelines Metal 4 no BotW 1.9.0 do Mac: fase 0

Data: 2026-11-21. Mac: M5 Pro, macOS 27.2, SDK 27.2, SSD interno, na tomada. Jogo: Breath of the Wild 1.9.0.
Branch `orcakhan/botw-mtl4-archive`, a partir do `main` `4894d5dc`.

## Resumo

O BotW 1.9.0 do Mac passa a usar o arquivo de pipelines do Metal 4 que o Ocarina of Time já usa (`nvn_pso4*.h`). O
arquivo antigo (`MTLBinaryArchive`, 8 pipelines por arquivo) fica só para o que o Metal 4 não aceita. Sem pipelines
flexíveis: esses foram descartados na fase anterior (branch `orcakhan/pipelines`).

**Nenhum critério de parada disparou.**

| | Arquivo antigo | Metal 4 | Diferença |
|---|---|---|---|
| Pipelines no app (bytes) | 814,1 MB | 460,2 MB | **−43,5%** |
| Pipelines no app (arquivos) | 2.384 | 11 | −2.373 |
| Chaves achadas no Metal 4 por um 2º processo | — | 18.249 de 18.250 | 99,99% |
| Memória residente máxima no jogo | 4.522 MB | 4.108 MB | **−414 MB (−9%)** |
| Aberturas de arquivo de pipeline num lançamento | 2.538 (4,1 s somados) | 11 (0,58 s) | −2.527 |
| Tempo até o título | 10,20 s | 9,88 s | dentro do ruído |
| Quadros de 100 ms ou mais | 1 | 1 | igual |
| GPU p50 | 5,50 ms | 5,45 ms | igual |
| **Gerar o arquivo (empacotar), cache frio** | **74,5 s** | **155,3 s** | **+81 s (2,1×)** |
| **Gerar o arquivo, cache quente** | **27,0 s** | **147,8 s** | **+121 s (5,5×)** |

**Recomendação:** aceitar a migração do BotW 1.9.0.
- O ganho certo veio maior que a estimativa: −43,5% em bytes, contra 340–520 MB estimados. Além disso, 2.384 arquivos
  viraram 11.
- O jogo usa 414 MB a menos de memória e quase não abre arquivos durante o jogo.
- Não há ganho de tempo neste Mac, como esperado.

O custo é o tempo de empacotar: cada build ou update do BotW passa a levar uns 80–120 s a mais nesse passo. Há também
um defeito herdado do OOT que vale consertar à parte (ver "Achados").

## O que mudou no runtime (só Mac)

- `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_pso4_fn.h`: `PSO4_BUILT` com
  `(defined(GAME_OOT) || defined(GAME_BOTW190)) && !TARGET_OS_IPHONE`.
  - **Só Mac.** iOS e visionOS ficam de fora porque `TARGET_OS_IPHONE` vale 1 nos dois.
  - TOTK e BotW 1.6.0 continuam no arquivo antigo.
- `games/totk/runtime/frontend.m` (arquivo só do Mac): ao fechar a janela, o BotW 1.9.0 chama
  `mtl_pipeline_archive_quit`, como o OOT. Isso grava o período ainda capturando e imprime a linha de sessão. O TOTK não
  chama, para não ganhar a espera de `pso_user_queue` a cada fechamento.
- Testes:
  - `tests/test_botw_pso4_gate.py` pré-processa o gate para cada jogo e plataforma e confere o fechamento da janela.
  - `tests/test_ipad_pipelines_old_archive.py` garante que o build do iPad continua no arquivo antigo.
  - Os dois foram conferidos por mutação.
- `tools/gfx_matrix.py`: as 14 configurações compilam, sem avisos novos. Os testes do OOT que tocam o arquivo Metal 4
  passam.

## Como foi medido

Ferramenta: `games/totk/tests/mtl4_archive/` (`archive.py`, `run.py`), testada em `tests/test_mtl4_archive_tool.py`.

- **Bundle id próprio em toda execução.** O cache do Metal é separado por bundle id. Todas as execuções usaram binários
  com `org.macnativegames.mtl4test-NNNN`. O cache `org.macnativegames.totk-native` dos jogos instalados não recebeu
  nenhuma escrita (conferido com `find -newer` antes e depois).
- **Dois apps de teste**, clones APFS do app instalado, atualizados com `update_runtime.py` a partir do mesmo binário do
  branch:
  - A com `TOTK_PSO_MTL4=0`;
  - B com o Metal 4.
  - O app instalado não foi tocado.
- **Geração:** o modo `pipeline-archive` como o empacotamento roda, com o binário por um link na pasta `build` do app.
  - Dois braços do mesmo binário, 3 repetições alternando quem vai primeiro, frio (bundle id novo) e quente.
  - Depois de cada geração do Metal 4, um **segundo processo** procura cada chave de novo (`TOTK_PAR_RECHECK=1`). A
    cobertura é o que ele achou.
  - O tamanho é contado passando a pasta por `build_app.mac_pipeline_files`, a mesma função do empacotamento.
- **Jogo:**
  - o binário direto, com o ambiente do launcher, em cópias de perfil, cache e configurações;
  - save 2 carregado automaticamente;
  - o mesmo roteiro nos dois apps: 30 s parado, gira a câmera 6 s, anda 15 s, gira 6 s, anda 15 s;
  - fecha pelo comando `close` 120 s depois do carregamento;
  - um lançamento de preparo por app, depois ABABAB;
  - "fora do ruído" = diferença maior que 2 desvios-padrão combinados e de pelo menos 5%.

## Cobertura (item 1)

- **Metal 4:** das 18.250 chaves que o braço antigo grava (render e compute), 18.249 foram para o Metal 4. O segundo
  processo achou todas as 18.249 sem compilar nenhuma, nas 3 repetições, na atualização e na morte do serviço.
  - Critério: ≥ 90%. Resultado: 99,99%.
- **Resto no arquivo antigo:** 1 pipeline de render, 75.872 bytes. As duas bibliotecas dele não estão na `shader-libs`
  do app: ele usa uma biblioteca feita em tempo de execução, numa função criada fora do `lib_fn`.
- **As 183 chaves de bibliotecas feitas em tempo de execução** (variantes, contadas na fase anterior): só essa 1 ficou no
  caminho antigo. As outras passaram pelo `lib_fn`, foram gravadas no Metal 4 e o segundo processo achou todas.
  - No jogo, a linha de sessão do app B: 18.249 tiradas do arquivo, 0 compiladas, 1 pelo caminho antigo.

## Tamanho (item 2)

Medido como o app leva (`mac_pipeline_files`):

| | Arquivos | Bytes | vs antigo |
|---|---|---|---|
| Antigo | 2.384 `.metalarchive` | 814.114.752 | — |
| Metal 4 do zero | 10 `.mtl4a` + 1 `.metalarchive` | 460.174.272 | −43,5% |
| Metal 4 atualizando sobre a pasta antiga | 10 + 1 | 460.574.384 | −43,4% |
| Metal 4 com morte do serviço | 11 + 1 | 460.150.256 | −43,5% |

- **Apps de teste:** o bundle `Pipelines-botw190.bundle` dos apps confere, com 800.620 KB (A) contra 446.040 KB (B).
- **Atualização:** quase igual ao zero. O arquivo antigo que sobra é maior (535 KB contra 76 KB), porque o arquivo
  original de 8 pipelines vai inteiro, mas a diferença é pequena.
- **Critério 1:** ≥ 25% no pior dos dois. Resultado: −43,4%.

## Tempo de gerar (item 3)

| Mediana de 3 | Frio | Quente |
|---|---|---|
| Antigo | 74,5 s (73,1 / 74,5 / 78,8) | 27,0 s (27,5 / 27,0 / 26,7) |
| Metal 4 | 155,3 s (155,5 / 155,3 / 154,3) | 147,8 s (147,8 / 148,2 / 146,3) |
| Metal 4 atualizando | 154,8 s | — |

- **Conferência:** o braço antigo bate com a linha de base da fase anterior (70,9 s frio, 21–24 s quente).
- **Custo do passo do título:** dos ~150 s do Metal 4, ~15 s são o passo que põe as linhas de antes do título num
  arquivo pequeno (ver "Achados").
- **Cache quente:** o cache do Metal quase não ajuda o compilador que captura (148 s quente contra 155 s frio).
- **Causa não verificada.** Hipóteses:
  - o compilador ligado ao serializador (`CaptureBinaries`) compila sem usar o cache;
  - a espera entre capturas que usam a mesma função de vértice (`fn4_claim`; nenhuma desistiu de esperar,
    `gave_up` 0).
- **Para quem empacota:** um build ou update do BotW leva +81 s frio e +121 s quente nesse passo. O OOT já paga isso.

## Morte do serviço de compilação

- **Teste:** `TOTK_PSO4_TEST_DEATH=150`, com a 150ª captura simulando a morte do serviço.
- **Período perdido:** o período em curso, com 156 pipelines, não foi escrito e foi recapturado num período novo
  (`par4_recapture`).
- **Resultado:** o segundo processo achou todas as chaves, sem falta.

## iPad (modo do aparelho)

- **Por que não muda:** o build do iPad não lê o arquivo do app do Mac. `device_pipelines.make` roda o modo
  `pipeline-archive` sem `TOTK_PIPELINE_ARCHIVE_HOST`, e o runtime liga então `TOTK_SHADER_DEVICE_LIBS=1`, que desliga o
  Metal 4 (`par4_on`).
- **Execução:** com a seed do aparelho do BotW 1.9.0 (`~/Applications/Breath of the Wild-shader-seed`, mesmo `chain`), o
  binário do branch:
  - não criou `pipelines-mtl4/`;
  - gerou as mesmas 18.221 chaves com o Metal 4 ligado e com `TOTK_PSO_MTL4=0`.
- **Falhas que já existiam:** as duas execuções terminam com 29 pipelines que falham com as bibliotecas do aparelho na GPU
  do Mac, nos dois braços igualmente.
- **Teste automático:** `tests/test_ipad_pipelines_old_archive.py`.
- **Critério 3:** não disparou.

## Jogo no M5 Pro (item 4)

| Lançamento | Título | Espera do título | Memória máx. | Quadros ≥ 100 ms | Aberturas (soma) | GPU p50 |
|---|---|---|---|---|---|---|
| A 0 | 10,14 s | 2,6 s | 4.522 MB | 1 | 2.538 (4,18 s) | 5,40 |
| B 1 | 9,84 s | 2,1 s | 4.091 MB | 1 | 11 (0,60 s) | 5,42 |
| A 2 | 10,20 s | 2,6 s | 4.531 MB | 1 | 2.533 (4,07 s) | 5,47 |
| B 3 | 10,17 s | 2,1 s | 4.128 MB | 2 | 11 (0,57 s) | 5,46 |
| A 4 | 10,20 s | 2,6 s | 4.515 MB | 1 | 2.538 (4,13 s) | 5,59 |
| B 5 | 9,88 s | 2,1 s | 4.108 MB | 1 | 11 (0,58 s) | 5,45 |

- **Memória:** −414 MB, fora do ruído. Bate com a causa conhecida: ao abrir um arquivo, o formato antigo copia as
  descrições para a memória.
- **Tempo até o título e quadros longos:** dentro do ruído.
  - Os quadros longos medidos são o primeiro envio de ~200 texturas.
  - A criação de pipelines nesses quadros fica em 0,5 ms ou menos.
- **Espera do título:** 2,6 → 2,1 s nas 3 de cada. A regra de ruído dá "fora", mas com variação zero ela não decide nada.
  Fica como indício.
- **Aberturas:** no antigo, os 4,1 s somados correm em segundo plano e não aparecem no tempo até o título neste SSD. Em
  disco lento ou USB, era isso que pesava no OOT. Aqui não foi medido.
- **Preparação:** foi o primeiro lançamento de cada app com um bundle id novo.
  - A teve 2 quadros de 424 e 1.186 ms, com 370 e 283 ms criando pipelines e bibliotecas.
  - B teve 1 quadro de 104 ms.
  - É uma medição só por app, não uma conclusão.

## Critérios de parada

| Critério | Limite | Resultado | Disparou? |
|---|---|---|---|
| Bundle encolhe menos de 25% (pior entre zero e atualização) e o jogo não melhora | < 25% e sem melhora | −43,4% | não |
| Chaves achadas no Metal 4 | < 90% | 99,99% | não |
| O iPad deixa de receber o que precisa | qualquer mudança | sem mudança | não |

## Achados

1. **O arquivo do título do BotW nunca conta como "pequeno".** Defeito que já existia no caminho do OOT; não foi
   consertado aqui.
   - O empacotamento põe as linhas carregadas antes do título num arquivo próprio (`g_par4_compact`). No BotW são 1.453
     pipelines, acima de `PAR4_SMALL` (1.024).
   - **Consequência 1:** todo empacotamento recompila essas 1.453 (~15 s), porque `par4_in_small_file` não as reconhece.
   - **Consequência 2:** no jogo, `par4_open_all` abre esse arquivo junto com os grandes, e não antes deles, como foi
     pensado.
   - **Consertos possíveis:** subir o limite, ou marcar o arquivo do título pelo nome em vez da contagem. Mexe também no
     OOT, então fica para você decidir.
2. **Gerar pelo Metal 4 custa 2× frio e 5,5× quente.** A causa não foi verificada (ver item 3). Se o tempo de
   empacotamento importar, vale um teste à parte: comparar compile com e sem captura e com o `fn4_claim` desligado.
3. **Ferramenta de medição:** o ambiente de jogo precisa das variáveis `TOTK_GPU_*` que o launcher sempre define. Sem
   elas, todo lançamento aborta em `h_nvnQueueSubmitCommands` logo depois de carregar o save. Isso vale para qualquer A/B
   futuro feito por script.

## O que não foi medido

- Macs mais lentos (M1, M2) e app em disco externo, onde o OOT ganhou em tempo.
- A migração do lado do jogador: as chaves dos arquivos antigos da própria máquina, recompiladas na primeira abertura.
  Nesta máquina, a pasta local tinha uma entrada de 4 KB.
- A morte real do serviço de compilação no M1/M2 (#2107). Só a simulada.
- Mais de 3 lançamentos por braço e trajetos longos.

## Porte para o TOTK (só descrito)

- **Muda:**
  - o gate para o TOTK (as versões a decidir: `TOTK_GAME_V143` e a base);
  - a chamada de fechamento no `frontend.m`, fora do `#ifdef GAME_BOTW190`.
- **Conferir:**
  - as variantes do TOTK (border, tile read, HDR, saídas retipadas, MetalFX) e se cada uma passa pelo `lib_fn`;
  - as 2.895 chaves de bibliotecas feitas em tempo de execução;
  - os pipelines de mesh, que ficam no caminho antigo por design;
  - o arquivo do título, que no TOTK deve ser ainda maior que `PAR4_SMALL`.
- **Medir:** as mesmas medições, com a mesma ferramenta (`run.py`), trocando `rewritten/botw190`. O TOTK tem 1,8 GB e
  4.191 arquivos, e a geração deve passar de 5 minutos.

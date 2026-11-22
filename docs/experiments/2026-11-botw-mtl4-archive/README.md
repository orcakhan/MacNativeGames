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
| Chaves tiradas do Metal 4 no jogo (4 de 4 lançamentos, 0 compiladas) | — | 18.249 de 18.250 | 99,99% |
| Memória residente máxima no jogo | 4.522 MB | 4.108 MB | **−414 MB (−9%)** |
| Aberturas de arquivo de pipeline num lançamento | 2.538 (4,1 s somados) | 11 (0,58 s) | −2.527 |
| Tempo até o título | 10,20 s | 9,88 s | dentro do ruído |
| Quadros de 100 ms ou mais | 1 | 1 | igual |
| GPU p50 | 5,50 ms | 5,45 ms | igual |
| Gerar o arquivo, cache frio, **antes dos consertos** | 74,5 s | 155,3 s | +81 s (2,1×) |
| Rebuild sobre a pasta anterior, cache quente, **antes dos consertos** | 4,1 s | 17,1 s | +13 s |
| **Gerar o arquivo do zero, cache frio, com os consertos** (alternando, 3 de cada) | 74,0 / 81,0 / 76,5 s | **74,2 / 74,0 / 71,2 s** | **igual** (mediana −2,5 s, dentro da variação) |
| **Rebuild sobre a pasta anterior, frio / quente, com os consertos** | 22,4 / 4,1 s | **5,9 / 2,6 s** | **mais rápido** |
| **Pipelines no app gerando do zero, com os consertos** | 816,9 MB, 2.375 arquivos | **458,9 MB, 11 arquivos** | **−43,8%** |

**Os dois consertos (2026-11-21, seção "Consertos"):**
- **A:** o arquivo do título passa a ser reconhecido pelo nome. Com isso, o rebuild deixou de recompilar as 1.453 linhas
  do título.
- **B:** as linhas de cada período são intercaladas por função de vértice, e cada bloco fecha o seu período. Com isso, as
  capturas deixaram de esperar umas pelas outras, sem repetir código entre arquivos. Só no BotW 1.9.0: o empacotamento
  do OOT não foi medido com ele.

**Recomendação:** aceitar a migração do BotW 1.9.0 com os dois consertos.
- O ganho certo: −43,8% em bytes num empacotamento do zero (458,9 MB), e 2.375 arquivos viraram 11.
- O jogo usa 414 MB a menos de memória e quase não abre arquivos durante o jogo.
- Não há ganho de tempo de jogo neste Mac, como esperado.
- Com os consertos, empacotar do zero leva o mesmo que o arquivo antigo, e um rebuild leva menos.
- **O A/B de jogo foi medido com o app B empacotado antes dos consertos** (460 MB, ordem ordenada). Os consertos não
  mudam quais chaves o jogo encontra, mas mudam como os pipelines se dividem entre os arquivos, e com isso os bytes lidos
  ao abrir cada arquivo. Um pacote feito do zero com os consertos (458,9 MB, outra divisão) nunca foi lançado. Ver "O que
  não foi medido".

## O que mudou no runtime (só Mac)

- `games/totk/third_party/d2r_gfx/gfx/nvn/nvn_pso4_fn.h`: `PSO4_BUILT` com
  `(defined(GAME_OOT) || defined(GAME_BOTW190)) && !TARGET_OS_IPHONE`.
  - **Só Mac.** iOS e visionOS ficam de fora porque `TARGET_OS_IPHONE` vale 1 nos dois.
  - TOTK e BotW 1.6.0 continuam no arquivo antigo.
- `games/totk/runtime/frontend.m` (arquivo só do Mac): ao fechar a janela, o BotW 1.9.0 chama
  `mtl_pipeline_archive_quit`, como o OOT. Isso imprime a linha de sessão, como os 4 lançamentos do app B mostram. Também
  grava o período ainda capturando, mas isso foi **conferido só no código**, igual ao OOT: nenhum lançamento medido tinha
  período em captura ao fechar (todos com `写进 0 个文件`). O TOTK não chama, para não ganhar a espera de `pso_user_queue`
  a cada fechamento.
- Testes:
  - `tests/test_botw_pso4_gate.py` pré-processa o gate para cada jogo e plataforma e confere o fechamento da janela.
  - `tests/test_ipad_pipelines_old_archive.py` garante que o build do iPad continua no arquivo antigo.
  - Os dois foram conferidos por mutação.
- `tools/gfx_matrix.py`: as 14 configurações compilam, e ele não reportou avisos novos em relação ao HEAD. Os testes do
  OOT que tocam o arquivo Metal 4 passam.

## Como foi medido

Ferramenta: `games/totk/tests/mtl4_archive/` (`archive.py`, `run.py`), testada em `tests/test_mtl4_archive_tool.py`.

- **Bundle id próprio em toda execução.** O cache do Metal é separado por bundle id. Todas as execuções usaram binários
  com `org.macnativegames.mtl4test-NNNN`. O cache `org.macnativegames.totk-native` dos jogos instalados não recebeu
  nenhuma escrita (conferido com `find -newer` antes e depois).
- **O que foi escrito fora das cópias.** Perfil, saves e configurações reais não foram tocados: só cópias. Mas os
  lançamentos usam a pasta real do BotW para duas coisas, como a receita de A/B anterior:
  - a prova da RomFS (`TOTK_ROMFS_PROOF_DIR`): `BotW/.romfs-verified-v1` e `.aoc1-verified-v1` foram reescritos;
  - o game slot (`TOTK_GAME_SLOT_DIR`): `game-slot/history.log` e `holder`. O `holder` aponta para o último lançamento,
    já encerrado, o que o slot trata como livre.
  - O `update_runtime.py` registrou os apps de teste no macOS, com o mesmo bundle id do BotW instalado. Desfeito:
    `lsregister -u` nos dois e `-f` no app instalado, que voltou a ser o único registrado.
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

- **Metal 4:** das 18.250 chaves que o braço antigo grava (render e compute), 18.249 foram para o Metal 4.
  - **No jogo (a prova independente):** os 4 lançamentos do app B (preparo e 3 medidos) imprimem
    `取 18249 条，编 0 条`. As 18.249 vieram do arquivo e nenhuma foi compilada.
  - **No segundo processo de empacotamento:** ele achou as 18.249 nas 3 repetições, na atualização e na morte do serviço.
    Mas ele também recompila de propósito as 1.453 linhas do título (o passo do arquivo pequeno, ver "Achados"), então,
    para esses ~8% das chaves, ele só acha o que ele mesmo escreveu. A ferramenta desconta esse passo e marca quando uma
    chave é contada duas vezes (na morte: 18.405 achadas para 18.250 chaves).
  - Critério: ≥ 90%. Resultado: 99,99%.
- **Resto no arquivo antigo:** 1 pipeline de render, 75.872 bytes. As duas bibliotecas dele não estão na `shader-libs`
  do app: ele usa uma biblioteca feita em tempo de execução, numa função criada fora do `lib_fn`.
- **As 183 chaves de bibliotecas feitas em tempo de execução** (variantes, contadas na fase anterior): só essa 1 ficou no
  caminho antigo. Que as outras foram para o Metal 4 e são achadas é **inferido**: nenhuma chave saiu do Metal 4 além
  dessa, e o jogo compila 0. Elas não foram conferidas uma a uma.

## Tamanho (item 2)

Medido como o app leva (`mac_pipeline_files`):

| | Arquivos | Bytes | vs antigo |
|---|---|---|---|
| Antigo | 2.384 `.metalarchive` | 814.114.752 | — |
| Metal 4 do zero | 10 `.mtl4a` + 1 `.metalarchive` | 460.174.272 | −43,5% |
| Metal 4 atualizando sobre a pasta antiga | 10 + 1 | 460.574.384 | −43,4% |
| Metal 4 com morte do serviço | 11 + 1 | 460.150.256 | −43,5% |

- **Apps de teste:** o bundle `Pipelines-botw190.bundle` dos apps tem 800.620 KB (A) contra 446.040 KB (B), em
  `du`. O B confere em arquivos (11). O A tem 2.377 `.metalarchive` contra 2.384 contados pela ferramenta, uma diferença
  de 7 arquivos cuja causa não verifiquei. Os bytes ficam a menos de 1%.
- **Linha de base:** o design citava o app instalado (782 MB, 2.478 arquivos, 17.897 chaves). Aqui são 18.250 chaves
  porque o `update_runtime.py` aplicou a lista de shaders compartilhada mais nova, que acrescenta 367 pipelines. Os dois
  braços usam a mesma lista.
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

### Por que gerar pelo Metal 4 é mais lento (investigado 2026-11-21)

Medido numa amostra fixa de 2.000 linhas `R` do `pso_manifest.tsv`, com a CPU do processo e dos `MTLCompilerService`
amostrada a cada 0,5 s. As variantes vieram de um binário de diagnóstico com duas chaves de ambiente, que **não estão no
branch**: `TOTK_PSO4_DIAG_NOCLAIM` (sem `fn4_claim`) e `TOTK_PSO4_DIAG_PLAIN` (compilador Metal 4 sem serializador, nada
capturado).

| Variante | Frio | Quente | CPU do serviço (frio / quente) |
|---|---|---|---|
| Arquivo antigo | 9,5 s | 5,2 s | 456% / 183% |
| Metal 4, como está | 15,8 s | 15,1 s | 257% / 280% |
| Metal 4 sem `fn4_claim` | 10,3 s | 9,8 s | 498% / 518% |
| Metal 4 sem captura | 9,5 s | **0,6 s** | 321% / 0% |

1. **Compilar com captura não usa o cache do Metal.** Sem captura, o compilador Metal 4 acha tudo no cache (0,6 s, CPU
   do serviço zero). Com o serializador em `CaptureBinaries`, cada pipeline é compilado de novo, com cache quente ou frio.
   É comportamento do Metal, não do nosso código. Hipótese, não verificada: o serializador precisa do código que ele
   mesmo gera, então não aproveita o que está no cache.
2. **`fn4_claim` custa ~1/3 do tempo.**
   - O que é: duas capturas que usam a mesma função de vértice nunca rodam juntas, e a thread que não consegue a vez fica
     parada esperando.
   - Quanto custa: sem isso, o frio cai de 15,8 para 10,3 s, e o serviço usa o dobro de núcleos.
   - Por que existe: o Metal trava quando duas capturas leem a mesma função ao mesmo tempo (nxnative #815). Tirar não é
     um conserto.
3. **Sem captura e com cache frio, o compilador Metal 4 custa o mesmo que o antigo (9,5 s).** O compilador em si não é
   mais lento.

**O caso que mais acontece, rebuild ou update sobre a pasta anterior** (`TOTK_PAR_RECHECK=1`, o que o `build_app.py`
faz quando o binário muda): as chaves que já estão no `.mtl4a` são achadas, não compiladas.

| Rebuild sobre a pasta anterior | Cache do Metal frio | Quente |
|---|---|---|
| Arquivo antigo | 22,4 s | 4,1 s |
| Metal 4 | 19,3 s | 17,1 s |

Dos 17,1 s do Metal 4 quente, ~14,5 s são o passo do título, que recompila as 1.453 linhas a cada empacotamento por causa
do `PAR4_SMALL` (ver "Achados") e, por capturar, nunca usa o cache. Sem esse defeito, o rebuild Metal 4 ficaria perto do
antigo. Isso é estimado, não medido.

**Para quem empacota, antes dos consertos** (ver "Consertos" abaixo):
- primeiro build, ou primeira atualização a partir do arquivo antigo: +81 s (155 contra 74,5 s);
- rebuilds seguintes: +13 s com cache quente (17 contra 4 s), quase todos do passo do título.
- O OOT já paga isso.

### Consertos (2026-11-21, usuário: "Fazer os dois")

Os dois só mexem no empacotamento do Mac com o Metal 4. O preparo antes do título no primeiro início, o arquivo antigo, o
modo do aparelho (iPad) e o iOS ficam como estavam. O código é compartilhado com o OOT no Mac, cujo empacotamento não foi
medido de novo.

**Teto, medido antes:** uma geração fria da lista inteira com o `fn4_claim` desligado (binário de diagnóstico) levou
**72,7 s**, contra 155,8 s com ele ligado. Na lista ordenada, a espera custava mais da metade do tempo.

**A. O arquivo do título é marcado pelo nome** (`fix(pso4): title periods are marked by name`).
- O que mudou:
  - Os períodos do passo do título geram `<primeira chave>-<n>-title.mtl4a`.
  - "Pequeno" passa a ser: arquivo de título, ou até 1.024 pipelines como antes (`nvn_pso4_policy.h par4_name_small`).
  - Um período recapturado depois da morte do serviço herda a marca.
- Testes:
  - `tests/pso4_policy_probe.m` testa as regras de nome sem Metal;
  - `tests/test_pso4_policy.py` confere que o código usa essas regras.
- Medido:
  - Rebuild sobre a pasta Metal 4 anterior: **6,7 s frio / 2,8 s quente**, contra 19,3 / 17,1 s. O arquivo antigo leva
    22,4 / 4,1 s.
  - O passo do título compila **0** em vez de 1.453 (0,2 s).
  - No cenário de morte, as linhas recapturadas caem em dois arquivos `-title`.
  - Atualizar um app empacotado antes da A recompila as 1.453 uma vez (4,6 s) e apaga o arquivo antigo do título.

**B. Cada período tem as linhas intercaladas por função de vértice**
(`perf(pso4): packaging spreads each period's rows by vertex function`).
- O que mudou:
  - A lista continua ordenada, para os shaders de um bloco carregarem uma vez.
  - Os blocos têm no máximo o tamanho de um período (2.000 linhas).
  - Dentro do bloco, as linhas de cada função de vértice ficam espaçadas por igual, a partir de um deslocamento próprio
    (razão áurea), em `nvn_pso4_policy.h par4_spread`.
  - No fim de cada bloco o período é escrito (`nvn_pso4.h par4_cut_block`), se tiver pelo menos meio período. Assim um
    rebuild, com poucas linhas novas, não gera arquivos pequenos.
  - Só no BotW 1.9.0: o OOT continua com os blocos ordenados até ser medido (revisão de 2026-11-21).
- Disputa, **simulada** com as listas do app (`spread_sim.py`, não medida no Metal): janelas de 8 linhas com função de
  vértice repetida caem de 97,5% para 17,2%.
- **Por que blocos de um período, e por que fechar o período no fim:** um arquivo `.mtl4a` guarda o código de uma
  função uma vez só.
  - Com blocos de 8.192, as linhas de uma função se espalhavam por vários arquivos, e os pipelines no app subiam de 460
    para **581 MB**.
  - Com blocos de 2.000 sem fechar o período: 485 MB. Um bloco novo captura ~1.680 das suas 2.000 linhas, porque as do
    título já estão no arquivo dele. Então os períodos fechavam no meio dos blocos, e quase todo grupo daquele bloco caía
    em dois arquivos (achado da revisão).
  - Fechando no fim do bloco: **458,9 MB**.

**Final (o que ficou: blocos de 2.000 que fecham o período), na tomada, antigo e novo alternando, geração fria do zero:**

| | 1 | 2 | 3 | Mediana | Tamanho | Memória da ferramenta |
|---|---|---|---|---|---|---|
| Arquivo antigo | 74,0 s | 81,0 s | 76,5 s | 76,5 s | 816,9 MB | ~725 MB |
| **Metal 4 com os consertos** | 74,2 s | 74,0 s | 71,2 s | **74,0 s** | **458,9 MB** | ~730 MB |

- **Mesma rodada de geração** (binário final, 1 repetição): antigo 68,7 s frio; Metal 4 70,7 s frio e 55,9 s quente.
  - Atualizar a partir do arquivo antigo: 72,1 s, contra 155 s antes. Tamanho 459,3 MB.
  - Cenário de morte do serviço: 71,3 s, 461,9 MB. As linhas recapturadas caem em arquivos `-title`.
  - Rebuild sobre a pasta anterior: 5,9 s frio / 2,6 s quente.
  - Cobertura: 99,99%, com 0 chaves faltando, nos três cenários.
  - Arquivos: 1.821 a 2.000 pipelines cada, mais o do título (1.453) e o último (984).
- **Antes de fechar o período, para comparar** (blocos de 2.000, mesmo binário, alternando com 8.192):

| Geração fria, na tomada | 1 | 2 | 3 | Mediana | Tamanho |
|---|---|---|---|---|---|
| Blocos de 2.000, sem fechar o período | 58,8 s | 61,6 s | 70,6 s | 61,6 s | 485 MB |
| Blocos de 8.192 | 68,9 s | 85,2 s | 83,8 s | 83,8 s | 581 MB |
| Ordenado, sem o conserto | | | | 155,8 s | 460 MB |

- **Variação:** nas duas séries, os tempos variam uns ±10 s entre rodadas e sobem ao longo da sequência, provavelmente
  pelo aquecimento da máquina. Dizer "igual ao antigo" é o que os dados sustentam, não "mais rápido".
- **iPad:** o modo do aparelho, rodado com o binário de 8.192 (a trava é a mesma), gera as mesmas 18.221 chaves e nenhum
  `pipelines-mtl4/`.

## Morte do serviço de compilação

- **Teste:** `TOTK_PSO4_TEST_DEATH=150`, com a 150ª captura simulando a morte do serviço.
- **Período perdido:** o período em curso, com 156 pipelines, não foi escrito e foi recapturado num período novo
  (`par4_recapture`).
- **Resultado:** o segundo processo achou todas as chaves, sem falta.
- **Limite:** a 150ª captura caiu dentro do passo do título. A recaptura nesse passo foi exercitada, e as linhas do título
  ficaram divididas entre um arquivo de 156 e outro de 1.297. A recaptura durante o passo principal não foi exercitada.

## iPad (modo do aparelho)

- **Por que não muda:** o build do iPad não lê o arquivo do app do Mac. `device_pipelines.make` roda o modo
  `pipeline-archive` sem `TOTK_PIPELINE_ARCHIVE_HOST`, e o runtime liga então `TOTK_SHADER_DEVICE_LIBS=1`, que desliga o
  Metal 4 (`par4_on`).
- **Execução:** com a seed do aparelho do BotW 1.9.0 (`~/Applications/Breath of the Wild-shader-seed`, mesmo `chain`), o
  binário do branch:
  - não criou `pipelines-mtl4/`;
  - gerou as mesmas 18.221 chaves com o Metal 4 ligado e com `TOTK_PSO_MTL4=0`.
- **29 falhas:** as duas execuções terminam com 29 pipelines que falham com as bibliotecas do aparelho na GPU do Mac, nos
  dois braços igualmente. Não comparei com o `main`.
- **Quanto essa execução prova:** pouco além do código. No modo do aparelho, o Metal 4 fica desligado nos dois braços por
  construção, então "ligado = desligado" é quase garantido; o que ela mostra é que nenhum `pipelines-mtl4/` aparece. E ela
  rodou o binário pela pasta `build` do app do Mac, não pelo caminho que o `device_pipelines.make` usa.
- **A garantia principal:** a leitura do código e o teste automático `tests/test_ipad_pipelines_old_archive.py`, conferido
  por mutação.
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
| Bundle encolhe menos de 25% (pior entre zero e atualização) e o jogo não melhora | < 25% e sem melhora | −43,4%; com os consertos, −43,8% (zero e atualização) | não |
| Chaves achadas no Metal 4 | < 90% | 99,99% | não |
| O iPad deixa de receber o que precisa | qualquer mudança | sem mudança | não |

## Achados

1. **O arquivo do título do BotW nunca contava como "pequeno". Consertado: conserto A.** Era um limite do código
   compartilhado que veio com o OOT; não verifiquei se o OOT também passa dele.
   - O empacotamento põe as linhas carregadas antes do título num arquivo próprio (`g_par4_compact`). No BotW são 1.453
     pipelines, acima de `PAR4_SMALL` (1.024).
   - **Consequência 1:** todo empacotamento recompila essas 1.453 (~15 s), porque `par4_in_small_file` não as reconhece.
   - **Consequência 2:** no jogo, `par4_open_all` abre esse arquivo junto com os grandes, e não antes deles, como foi
     pensado.
2. **Gerar pelo Metal 4 custava 2× frio e 5,5× quente.**
   - **Causas medidas:** a captura não usa o cache do Metal, e o `fn4_claim` fazia as threads esperarem.
   - **A espera foi consertada (conserto B):** a geração fria fica no nível do arquivo antigo (mediana 74,0 contra 76,5 s).
   - **Continua:** a captura ainda não usa o cache. Gerar do zero com cache quente também leva ~60 s, contra 26 s do
     antigo. Mas o rebuild, o caso comum, acha as chaves no arquivo e não compila.
3. **Ferramenta de medição:** o ambiente de jogo precisa das variáveis `TOTK_GPU_*` que o launcher sempre define. Sem
   elas, todo lançamento aborta em `h_nvnQueueSubmitCommands` logo depois de carregar o save. Isso vale para qualquer A/B
   futuro feito por script.

## O que não foi medido

- **Um lançamento do jogo com o app reconstruído com os consertos.** O app B foi atualizado com A e B (o arquivo do
  título virou `-title`, ~455 MB de `.mtl4a`). O lançamento falhou antes do jogo, em "native display link initialization", porque a
  tela tinha se desligado (23:08). Falta conferir:
  - a linha de abertura em segundo plano listando o arquivo do título entre os pequenos;
  - a linha de sessão com `取 18249，编 0`.
  - Esse app foi reconstruído sobre a pasta ordenada de antes da B: só o arquivo do título é novo. Por isso, ele não
    valida a nova divisão dos arquivos. Para validar, falta lançar um app empacotado do zero com os consertos.
- O empacotamento do OOT com os consertos.
- Macs mais lentos (M1, M2) e app em disco externo, onde o OOT ganhou em tempo.
- A migração do lado do jogador: as chaves dos arquivos antigos da própria máquina, recompiladas na primeira abertura.
  Nesta máquina, a pasta local tinha uma entrada de 4 KB.
- A morte real do serviço de compilação no M1/M2 (#2107). Só a simulada, e só dentro do passo do título.
- **Compilar durante o jogo.** Nenhum lançamento do B compilou pipeline (`编 0`), porque o arquivo estava completo. Um
  pipeline que falte no arquivo é compilado pelo compilador que captura, e a geração mostra esse compilador cerca de 2×
  mais lento por pipeline. "Quadros longos iguais" vale só para um arquivo completo.
- **Gravar o último período ao fechar a janela** com captura em curso: conferido só no código. Nenhum fechamento medido
  tinha o que gravar.
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
- **Antes de reusar a ferramenta:** o `run.py` tem `rewritten/botw190` e a pasta `BotW` fixos. A cobertura por chave e a
  classificação do resto foram feitas por dois scripts do scratch que não estão no branch. Os dois precisam entrar no
  `run.py`.
- **Medir:** as mesmas medições, com a mesma ferramenta. O TOTK tem 1,8 GB e
  4.191 arquivos, e a geração deve passar de 5 minutos.

# Campanhas experimentais

Os scripts utilizados nas coletas foram mantidos sem alterações de lógica. A reorganização corrigiu apenas os caminhos padrão de saída que dependiam da posição dos arquivos.

## Caracterização (60 ensaios)

- `characterization/initial/`: `executar_campanha.py`, `plano_36_ensaios.csv` e `protocolo.md` (Runs 153–188).
- `characterization/complementary/`: `executar_campanha.py` controla a campanha, `coletar_ensaios.py` realiza as coletas e `plano_24_ensaios.csv` define as Runs 197–220. `compilar_binarios.py` e `concluir_compilacao.py` auxiliam a compilar/conferir as duas variantes do Nó A. A pasta `binarios/` conserva as imagens históricas e `registro_binarios.json`.
- Arquivos das execuções: `../data/zips/`.

Conferência do primeiro plano sem acessar os dispositivos:

```bash
python3 experiments/characterization/initial/executar_campanha.py --dry-run
```

As etapas inicial e complementar possuem hashes de binários distintos, registrados nos metadados das execuções. Os resultados principais estão resumidos no [README do projeto](../README.md).

## Progressão até Bus-Off (40 ensaios)

- `busoff/executar_campanha_integral_phase20.py`: coordena a campanha.
- `busoff/executar_campanha_CAN_phase20.py`: executa e registra cada ensaio.
- `busoff/plano_campanha_phase20_40_runs.csv`: plano das execuções 304–343.
- `busoff/main_phase20.c` e `busoff/injector.pio`: código do Pico nessa campanha.
- `busoff/node_a_busoff_trace.c`: variante instrumentada do firmware do Nó A identificada nos logs de inicialização dos ensaios 304–343.
- Registros definitivos: `../data/busoff_estudo_2026/zips/` (Runs 304–343). Os ZIPs contêm os arquivos brutos.

Conferência sem iniciar a bancada:

```bash
python3 experiments/busoff/executar_campanha_integral_phase20.py --dry-run
```

Os ensaios 300 e 303 foram preliminares. Apenas 304–343 integram a amostra principal.

## Dados e reprodução

O repositório contém um ZIP por ensaio definitivo: 60 em `../data/zips/` e 40 em `../data/busoff_estudo_2026/zips/`. Cada ZIP reúne os registros brutos e os metadados daquela execução. Para evitar duplicação, foram removidas as cópias descompactadas, os pacotes consolidados redundantes e os registros exploratórios. Os ZIPs dos pilotos 300 e 303 permanecem em `../data/busoff_estudo_2026/zips/` porque o controlador verifica esses dois pilotos antes de autorizar a campanha física.

Antes de uma nova aquisição física, confira as portas seriais, a compilação dos firmwares, a configuração da bancada e as condições elétricas. Os comandos de verificação acima não acionam o injetor.

## Invocacao direta segura

O executor PHASE20 individual conserva o SHA-256 exigido pelo controlador historico. O caminho padrao herdado para o plano nao corresponde a este diretorio; informe sempre o plano explicitamente:

```bash
python3 experiments/busoff/executar_campanha_CAN_phase20.py \
  --plan experiments/busoff/plano_campanha_phase20_40_runs.csv --dry-run

python3 experiments/characterization/complementary/coletar_ensaios.py --dry-run
```

Para conferir o controle da campanha complementar sem acessar hardware:

```bash
python3 experiments/characterization/complementary/executar_campanha.py \
  --plan experiments/characterization/complementary/plano_24_ensaios.csv \
  --reference-bin experiments/characterization/complementary/binarios/node_a_referencia.bin \
  --adaptive-bin experiments/characterization/complementary/binarios/node_a_adaptativo.bin
```

Os comandos acima apenas validam planos e nao abrem portas seriais. Para a campanha complementar, a execucao fisica direta exige agora `--execute`, e o controlador encaminha essa autorizacao explicitamente quando invocado com `--execute`. A alteracao afeta apenas o controle de invocacao, nao a logica de geracao de pulsos ou o conteudo das coletas historicas.

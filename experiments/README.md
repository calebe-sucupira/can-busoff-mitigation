# Campanhas experimentais

Os scripts utilizados nas coletas foram mantidos sem alterações de lógica. A reorganização corrigiu apenas os caminhos padrão de saída que dependiam da posição dos arquivos.

## Caracterização (60 ensaios)

- `characterization/initial/`: plano e executor dos ensaios 153–188.
- `characterization/complementary/`: plano, executor e binários associados aos ensaios 197–220.
- Arquivos das execuções: `../data/zips/`.
- Métricas consolidadas: `../analysis/avaliacao_campanha_60_runs/`.

Conferência do primeiro plano sem acessar os dispositivos:

```bash
python3 experiments/characterization/initial/executar_campanha_CAN.py --dry-run
```

As etapas inicial e complementar possuem hashes de binários distintos. A documentação de proveniência está em `../analysis/auditoria_proveniencia_CAN_60/`.

## Progressão até Bus-Off (40 ensaios)

- `busoff/executar_campanha_integral_phase20.py`: coordena a campanha.
- `busoff/executar_campanha_CAN_phase20.py`: executa e registra cada ensaio.
- `busoff/plano_campanha_phase20_40_runs.csv`: plano das execuções 304–343.
- `busoff/main_phase20.c` e `busoff/injector.pio`: código do Pico nessa campanha.
- Registros: `../data/busoff_estudo_2026/raw/` e `../data/busoff_estudo_2026/zips/`.

Conferência sem iniciar a bancada:

```bash
python3 experiments/busoff/executar_campanha_integral_phase20.py --dry-run
```

Os ensaios 300 e 303 foram preliminares. Apenas 304–343 integram a amostra principal.

## Dados e reprodução

Os ZIPs da raiz foram movidos para `../data/archives/`. Os registros dos pilotos foram organizados em `../data/pilots/`. Nenhum dado bruto da amostra principal foi retirado.

Antes de uma nova aquisição física, confira as portas seriais, a compilação dos firmwares, a configuração da bancada e as condições elétricas. Os comandos de verificação acima não acionam o injetor.

# Consolidação da campanha CAN — 60 ensaios

## Escopo e validação

Foram auditados os 36 ensaios originais (Runs 153–188) e as quatro repetições adicionais por condição (Runs 197–220), totalizando **60 ensaios, dez por perfil e política**. Todos os ZIPs têm CRC válido e QC aprovado, com 40 s de injeção por ensaio, sem prazos perdidos do injetor. Modo de inicialização do Nó A e confirmação da automação foram verificados. Os perfis e as sementes correspondem dentro de cada bloco; não há sincronização elétrica entre pulso e quadro.

A RUN 187 possui um registro inicial corrompido. O QC contabiliza 5.251 TX_SUCCESS na run completa, mas há 5.250 registros TX_SUCCESS válidos nos logs e CSV depois de descartar essa única linha inválida. Esse tratamento não modifica o ZIP; as métricas delimitadas à injeção coincidem com a análise original dos 36 ensaios.

## Resultado por condição (dez ensaios por condição)

| Perfil | Política | Pico de TEC, média ± DP | ERROR A/40 s, média | TX A/40 s, média | Alertas/1.000 TX OK | Tempo total Error Passive | Gaps totais |
|---|---|---:|---:|---:|---:|---:|---:|
| BAIXO | REFERENCIA | 37,00 ± 11,06 | 101,30 | 3999,90 | 25,33 | 0,000 | 0 |
| BAIXO | ADAPTATIVO | 32,90 ± 3,38 | 96,40 | 4000,20 | 24,10 | 0,000 | 0 |
| MEDIO_V2 | REFERENCIA | 77,90 ± 20,64 | 241,90 | 4000,60 | 60,47 | 0,009 | 0 |
| MEDIO_V2 | ADAPTATIVO | 79,60 ± 13,78 | 230,00 | 3999,20 | 57,51 | 0,000 | 10 |
| ALTO | REFERENCIA | 127,20 ± 16,69 | 407,90 | 4000,70 | 101,96 | 1,634 | 0 |
| ALTO | ADAPTATIVO | 133,40 ± 10,90 | 400,80 | 3756,10 | 106,71 | 9,284 | 2493 |

O pico de TEC é o máximo da variável `tec_peak` nas amostras de monitoramento dentro da janela de injeção. As contagens `ERROR`, `TX_SUCCESS` e `RECEIVED` utilizam a janela host `NOISE_START`–`NOISE_END`. O tempo em Error Passive e os gaps referem-se à execução completa, como nos relatórios anteriores.

**`ERROR/1.000 TX_SUCCESS` não é taxa de erro de quadro ou de bits.** O controlador realiza retransmissões que não são contabilizadas nesse denominador.

## Resultado do último bloco (Runs 215–220)

| Run | Perfil | Política | Pico TEC | Entradas Passive | Tempo Passive (s) | Gap | ERROR A/40s | TX OK A/40s |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 215 | ALTO | ADAPTATIVO | 135 | 5 | 0,879 | 161 | 373 | 3840 |
| 216 | MEDIO_V2 | ADAPTATIVO | 52 | 0 | 0,000 | 0 | 202 | 4000 |
| 217 | BAIXO | ADAPTATIVO | 37 | 0 | 0,000 | 0 | 101 | 4000 |
| 218 | BAIXO | REFERENCIA | 36 | 0 | 0,000 | 0 | 123 | 4000 |
| 219 | MEDIO_V2 | REFERENCIA | 68 | 0 | 0,000 | 0 | 214 | 4001 |
| 220 | ALTO | REFERENCIA | 139 | 5 | 0,331 | 0 | 417 | 4001 |

## Interpretação

- **BAIXO:** o TEC não alcançou o limiar de contenção (96) em nenhum ensaio; não há atuação observada da política (gap zero).
- **MÉDIO_V2:** apenas uma execução adaptativa apresentou substituições, totalizando dez; o perfil oferece baixa exposição ao mecanismo.
- **ALTO:** a política foi ativada em 10/10 execuções e substituiu 2.493 atualizações da aplicação, não quadros perdidos no barramento. As transmissões bem-sucedidas médias durante a injeção passaram de 4.000,7 na referência para 3.756,1 com a política (aproximadamente 6,1% menos).
- **ALTO e TEC:** os picos médios foram 127,2 (referência) e 133,4 (adaptativo). Não há evidência de redução sistemática do pico de TEC.
- **ALTO e Error Passive:** tempo acumulado 1,634 s na referência contra 9,284 s no modo adaptativo. A redução de transmissões bem-sucedidas pode reduzir oportunidades de decremento do TEC, mas isso é uma explicação mecanística plausível, não uma prova causal isolada.
- **Bus-Off:** zero ocorrências nos 60 ensaios. Não é possível demonstrar prevenção ou adiamento desse estado sem um controle que efetivamente entre em Bus-Off sob condições seguras e verificadas.

## Proveniência e cautela para inferência

Os 36 ensaios iniciais e os 24 adicionais apresentam **hashes SHA-256 diferentes dos binários** em cada política. Cada uma das duas fases manteve um par de hashes estável, e todos os modos foram verificados na inicialização. Somente esses registros não comprovam equivalência binária ou funcional entre as duas fases; antes de testes inferenciais pooled, convém comparar os fontes/artefatos da compilação. As tabelas conjuntas são descritivas, e disponibilizamos também `resumo_por_fase_experimental.csv` para transparência.

Mesmo compartilhando a semente por bloco, os pulsos não estão sincronizados aos quadros CAN: os pares de bloco são comparações organizadas, não pares físicos de perturbações idênticas. Há dez repetições por condição, não milhares de unidades estatísticas independentes representadas por cada evento `ERROR`.

## Próximos passos

1. Preservar os 60 ZIPs como conjunto de dados da campanha ampliada.
2. Comparar a proveniência dos firmwares entre as duas fases (binários, fontes, flags, opções de compilação).
3. Retomar a viabilidade de uma condição que produza Bus-Off no modo de referência sem intensificar curtos no circuito desprovido de instrumentação elétrica adequada.
4. Preparar a seção de Resultados e Discussão distinguindo atuação da política, desempenho e limites do experimento.

## Reprodutibilidade

Na raiz do repositório, guardar este arquivo como `analysis/avaliar_campanha_60_runs_TCC2.py` e executar:

`python3 analysis/avaliar_campanha_60_runs_TCC2.py`

As entradas esperadas ficam em `data/zips/`. As saídas vão para `analysis/avaliacao_campanha_60_runs/` sem modificar os dados brutos.

# Avaliação quantitativa da política reativa — campanha oficial (Runs 153–188)

## Escopo, qualidade e cuidado com as métricas

Análise descritiva dos **36 arquivos brutos ZIP**: três perfis, duas políticas e seis blocos por condição. Cada ensaio tem 40 s de injeção (além de baseline e recuperação). Os ZIPs passaram na validação QC e na verificação de integridade. As contagens de `ERROR`, `TX_SUCCESS` e `RECEIVED` foram extraídas dos logs com carimbo de tempo de captura do computador e delimitadas pelo período `NOISE_START`–`NOISE_END` do Pico. Os picos de TEC foram obtidos dos registros de monitoramento (`tec_peak`).

**Importante:** `ERROR` é um alerta/evento disponibilizado pelo firmware/controlador. `ERROR` dividido por `TX_SUCCESS` é um **indicador descritivo de alertas por mil transmissões bem-sucedidas**, **não** probabilidade de falha por tentativa, taxa de erro de bits nem perda de quadros. O número de tentativas internas e retransmissões não foi contabilizado por esse denominador. Contagens por modo agregam seis ensaios e não devem ser tratadas como milhares de observações independentes.

## Comparação por perfil

| Perfil | Política | Pico TEC (média ± DP) | ERROR A /40 s (média) | TX OK A /40 s (média) | ERROR A/1000 TX OK | Error Passive (s, soma) | Gap (soma da RUN) |
|---|---|---:|---:|---:|---:|---:|---:|
| BAIXO | REFERENCIA | 38.17 ± 14.65 | 97.83 | 3999.67 | 24.46 | 0.000 | 0 |
| BAIXO | ADAPTATIVO | 33.50 ± 2.43 | 93.33 | 4000.33 | 23.33 | 0.000 | 0 |
| MEDIO_V2 | REFERENCIA | 81.00 ± 25.74 | 244.83 | 4000.33 | 61.20 | 0.009 | 0 |
| MEDIO_V2 | ADAPTATIVO | 87.17 ± 9.64 | 241.50 | 3998.17 | 60.40 | 0.000 | 10 |
| ALTO | REFERENCIA | 133.17 ± 7.94 | 409.33 | 4000.67 | 102.32 | 0.969 | 0 |
| ALTO | ADAPTATIVO | 132.67 ± 13.87 | 390.50 | 3737.83 | 104.47 | 6.925 | 1625 |

## Diferenças agregadas (reativo em relação à referência)

| Perfil | Eventos ERROR A | TX OK A | Alertas por 1000 TX OK | Picos TEC (média) |
|---|---:|---:|---:|---:|
| BAIXO | -4.60% | 0.02% | -4.62% | -4.67 |
| MEDIO_V2 | -1.36% | -0.05% | -1.31% | 6.17 |
| ALTO | -4.60% | -6.57% | 2.11% | -0.50 |

## Comparações dentro dos seis blocos (mesma semente, sem sincronização elétrica)

Os blocos usam a mesma semente por perfil, mas os pulsos **não** são sincronizados aos quadros CAN; comparação descritiva não equivale a pareamento físico de cada perturbação.

| Perfil | Δ TEC pico (adap−ref) por bloco | Δ alertas/1000 TX OK por bloco |
|---|---|---|
| BAIXO | -29, -12, +12, +4, +3, -6 | -8.25, -8.26, +2.49, -1.50, +1.49, +7.25 |
| MEDIO_V2 | +11, +13, +15, +26, -27, -1 | +6.00, +3.50, -11.49, +18.76, -7.84, -13.74 |
| ALTO | -11, +17, +4, -30, +19, -2 | +0.35, -3.51, -1.37, -4.25, +9.08, +13.34 |

## Interpretação e limitações

1. **BAIXO:** em todos os ensaios o TEC permaneceu abaixo de 96, e `gap=0`; não houve contenção de submissões. Diferenças entre políticas neste perfil não medem atuação efetiva do controle.
2. **MÉDIO_V2:** houve atuação limitada: apenas um dos seis ensaios reativos apresentou atualizações substituídas (`gap` total 10). Por isso, o perfil oferece pouca exposição à política para avaliar sua eficácia.
3. **ALTO:** os seis ensaios reativos apresentaram atualização substituída, com queda clara do total de TX bem-sucedidas. A contagem de alertas `ERROR` caiu menos que as transmissões, aumentando ligeiramente o indicador por mil TX bem-sucedidas. Essa normalização **não demonstra** risco causal maior por mensagem.
4. **TEC e Error Passive:** o pico médio de TEC no ALTO permaneceu semelhante entre os modos. O tempo acumulado em `Error Passive` foi maior com contenção, consistente com o mecanismo observado em janelas sem erros: menos transmissões bem-sucedidas também significam menos oportunidades de redução do TEC. Isso é uma **explicação plausível**, não prova causal isolada.
5. **Bus-Off:** não ocorreu em nenhuma das 36 RUNs. Não se pode afirmar prevenção, adiamento ou redução da frequência de Bus-Off; o modo sem política também não entrou nesse estado.
6. **Amostragem e eventos:** alertas e amostras são observáveis pelo firmware, não uma instrumentação elétrica independente. O intervalo de captura tem pequena incerteza nos eventos próximos às transições de fase. A RUN 187 tem uma linha inicial corrompida antes dos dados válidos; o script a ignora sem alterar os arquivos brutos.
7. **Inferência estatística:** n=6 por condição, ordem não aleatorizada individualmente e perfis sem sincronização pulso/quadro. Evitar tratar alertas individuais como replicações. As diferenças reportadas são descritivas, e a ausência de diferença sistemática no pico TEC não prova equivalência.
8. **Gap:** `gap_total_run` contabiliza atualizações substituídas pela aplicação, não perdas de quadros no barramento. Não é usado como numerador de erro CAN.

## Próximo passo sugerido

Construir a seção de Resultados e Discussão com essas tabelas e com as análises temporais já reproduzidas. Para investigar Bus-Off real, seria preciso uma condição de referência que atinja esse estado com segurança elétrica verificável; não intensificar o curto no hardware sem instrumentação adequada. A medição de duração de tarefas do RTOS, se ainda constar entre os objetivos finais, exige uma verificação específica da instrumentação atual.

## Reprodutibilidade

Rodar a partir da raiz do projeto: `python3 analysis/avaliar_eficacia_36_runs_TCC2.py`. Entradas: `data/zips/run_153_injection.zip` até `run_188_injection.zip`. Saídas em `analysis/avaliacao_eficacia_36_runs/`. O código usa somente a biblioteca padrão.

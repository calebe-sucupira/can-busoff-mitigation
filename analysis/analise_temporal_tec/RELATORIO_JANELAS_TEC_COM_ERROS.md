# Janelas com erros e TEC elevado — ensaios ALTO

Base: 12 ensaios oficiais ALTO e Runs 191–196. Janelas de 80–120 ms, selecionadas por TEC inicial >= 96 e incremento do contador `errors`.

| Modo | Janelas | TEC sobe | TEC cai | Correspondencia com 8×Δerrors−Δtx_ok |
|---|---:|---:|---:|---:|
| REFERENCIA | 81 | 47 | 34 | 81/81 |
| ADAPTATIVO | 76 | 76 | 0 | 75/76 |

## Janelas com exatamente um incremento de `errors`

| Modo | Janelas | Mediana Δtx_ok | Mediana ΔTEC |
|---|---:|---:|---:|
| REFERENCIA | 34 | 10 | -2 |
| ADAPTATIVO | 42 | 5 | 3 |

## Interpretacao e limites

- As janelas sao **correlacionadas**, nao repeticoes independentes. A comparacao entre modos nao isola o efeito causal do algoritmo.
- `errors` e um contador de eventos fornecido pelo firmware, nao uma medicao direta da quantidade de bits CAN corrompidos.
- A relacao `ΔTEC ≈ 8×Δerrors − Δtx_ok` resume um padrao **observado neste subconjunto**, nao deve ser tratada como lei geral do CAN.
- Os valores de TEC foram amostrados; eventos intermediarios podem nao aparecer no log. Verificar `STATE_CHANGE` para Bus-Off.
- Nao usar essas correlacoes para validar eletricamente um perfil de injecao mais intenso.
- Os ensaios nao demonstram mitigacao de Bus-Off: o estado nao ocorreu no conjunto analisado.

CSV detalhado: `janelas_tec_alto_com_erros.csv`.

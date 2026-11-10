# Auditoria temporal do TEC — TCC II

**Escopo:** 12 ensaios oficiais ALTO (155, 156, 160, 163, 165, 170, 173, 174, 178, 181, 183 e 188) e seis exploratórios ALTO (191–196). Todos os 18 ZIPs apresentam `qc.json` válido. Não foi identificado evento `BUS_OFF` nesse conjunto.

## Hipótese investigada

Quando há uma sequência de erros, o TEC sobe. Quando os erros cessam temporariamente, transmissões CAN bem-sucedidas reduzem o contador, limitando seu acúmulo. A política reativa reduz também as oportunidades de transmissão bem-sucedida e pode tornar a recuperação do TEC mais lenta.

## Método e resultados

Foram encontrados 9696 intervalos entre amostras consecutivas (`SAMPLE`) nos 18 ensaios. Selecionamos 3602 intervalos com 80–120 ms, TEC inicial positivo, nenhum incremento do contador cumulativo de erros CAN (`errors`) e `tx_ok` não decrescente.

Em **3602/3602** intervalos, observou-se exatamente `TEC_final = max(0, TEC_inicial - Δtx_ok)`; o piso em zero é necessário porque o TEC não assume valor negativo. Essas janelas são intervalos de tempo correlacionados, **não** repetições experimentais independentes.

Em contraste, entre 2829 janelas de 80–120 ms com incremento de `errors`, houve crescimento do TEC em 2464 e queda em 338. Esse contador de eventos não deve ser convertido diretamente em incremento de TEC: os efeitos variam com o tipo de erro e o estado do controlador.

### Taxa observada de recuperação em janelas sem novos erros

| Faixa inicial do TEC | Modo | Janelas | TX bem-sucedidas por janela (mediana) | Redução do TEC por janela (mediana) |
|---|---|---:|---:|---:|
| TEC de 1 a 95 | REFERENCIA | 1385 | 10 | 10 |
| TEC de 1 a 95 | ADAPTATIVO | 1325 | 10 | 10 |
| TEC de 96 a 127 | REFERENCIA | 85 | 10 | 10 |
| TEC de 96 a 127 | ADAPTATIVO | 178 | 5 | 5 |
| TEC de 128 a 255 | REFERENCIA | 5 | 10 | 10 |
| TEC de 128 a 255 | ADAPTATIVO | 60 | 3 | 3 |

Nas janelas sem novo erro e com TEC ainda positivo, os resultados são compatíveis com 100 Hz (referência), aproximadamente 50 Hz (reativo em alerta) e 25 Hz (reativo em condição mais severa). O número de janelas em `TEC≥128` do modo referência é reduzido e não deve ser utilizado para inferência estatística isolada.

### Exemplos auditáveis

- **Run 191 (referência):** entre 13,690 e 13,789 s, o TEC caiu de 137 para 127, com dez transmissões concluídas e nenhum incremento do contador de erros (91 em ambas as amostras).
- **Run 193 (reativo):** entre 15,780 e 15,881 s, TEC de 132 para 129; três transmissões concluídas; contador de erros inalterado em 91.
- **Run 160 (reativo):** entre 15,051 e 15,552 s, TEC de 141 para 129; doze transmissões concluídas e contador de erros inalterado em 92.

## Interpretação e limites

Os dados **sustentam fortemente** a recuperação do TEC durante intervalos sem novos erros, por transmissões bem-sucedidas. No modo reativo, a redução de frequência também reduz a velocidade dessa recuperação. Esse mecanismo oferece uma explicação plausível para a permanência em `Error Passive` por mais tempo em alguns ensaios com a política. Não demonstra que a política cause Bus-Off, nem que reduzir a frequência em geral seja prejudicial.

O contador `tec_peak` reúne os máximos observados pelo monitor com período nominal de 1 ms, e pode superar `tec` nas amostras impressas. A coincidência exata é uma característica **observada** nos registros, não uma comprovação completa das regras internas do controlador; eventos dentro dos 100 ms podem não estar visíveis. O firmware armazena `SAMPLE` e `TX_SUCCESS` separadamente, e os timestamps seriais não são uma referência elétrica ao nível do bit.

**Conclusão prática:** a ausência de Bus-Off parece envolver uma alternância entre aumentos por erro e quedas em períodos de transmissões bem-sucedidas; não há evidência de acúmulo sustentado até 256 nos ensaios avaliados. Esse diagnóstico, sozinho, não autoriza intensificar curtos elétricos. Para um novo perfil seria necessário validar previamente os limites do circuito; sem osciloscópio, uma avaliação emulada do algoritmo seria alternativa auxiliar, mas não comprovaria mitigação de Bus-Off físico.

## Arquivos de reprodução

`analise_temporal_crescimento_recuperacao_tec_TCC2.py` — script; `resumo_por_run_alto_18.csv`, `intervalos_amostras_tec.csv`, `resumo_recuperacao_por_faixa.csv` — dados derivados; PNGs dos Runs 191 e 193. Todos os arquivos de entrada são ZIPs originais preservados.

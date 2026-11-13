# TCC2 — Protocolo pré-especificado da campanha oficial CAN (proposta v1)

**Data de preparação:** 15/10/2026. **Estado:** aguardando pré-validação dos Runs 151–152 e congelamento dos binários. **Não iniciar os Runs 153–188 antes dessa etapa.**

## 1. Pergunta de pesquisa

Em um barramento CAN clássico de 125 kbit/s sujeito a três **densidades programadas** de perturbação elétrica, uma política de throttling adaptativo governada pelo TEC reduz indicadores de degradação associados ao risco de Bus-Off, e a que custo de entrega/atualização da aplicação, em comparação à política de referência?

**Distinções obrigatórias:** maior TEC não significa mais erros cumulativos; `ERROR` não equivale a quadro CAN definitivamente perdido; `gap` representa atualizações de aplicação não submetidas intencionalmente, não perda do barramento; evitar afirmar prevenção de Bus-Off sem observar/descrever eventos adequadamente.

## 2. Montagem e firmware congelados

- Nó A: ESP32, transmissor periódico, `node-a-throttling-v1.3`, ESP-IDF 6.0.2, CAN 125 kbit/s, produção de atualização de aplicação nominal 100 Hz, CAN retransmitido automaticamente; mesmo código entre grupos **exceto** `ENABLE_THROTTLING` (0 referência / 1 adaptativo).
- No modo adaptativo, controle definido a partir de TEC: 0–95 → 100 Hz, 96–127 → 50 Hz, ≥128 → 25 Hz. Registrar no boot `throttling=0/1`; outras alterações no firmware exigem nova validação e novo congelamento.
- Nó B: mesmo firmware receptor em ambas as políticas; ACK como antes.
- Pico: **firmware parametrizável v1.5 já validado nos pilotos**. Mantém `injector.pio` e largura **nominal** de pulso de 8 µs. Nenhuma modificação de PCB, conexões ou sincronismo externo.
- Fases de cada ensaio: **5 s de baseline + 40 s de injeção + 5 s de recuperação**, além do tempo de abertura/fechamento de captura; não confundir duração do ZIP com janela experimental.
- Frequências configuradas por intervalos pseudoaleatórios uniformes: `BAIXO 40000..60000 µs` (~20/s), `MEDIO_V2 17500..22500 µs` (~50/s), `ALTO 9375..14375 µs` (~84/s). A intensidade elétrica individual nominal é a mesma; muda a frequência de pulsos.
- **Limitação:** a largura/amplitude real do pulso não foi validada por osciloscópio nos registros. Não apresentar `pulses` como contagem física aferida: o campo contabiliza comandos PIO.
- Um mesmo `seed_hex` gera o mesmo planejamento determinístico de intervalos dentro de cada perfil, **mas não sincroniza pulsos e quadros CAN entre execuções**, de modo que comparações por semente não equivalem a experimentos fisicamente pareados.
- Congelar e guardar SHA-256 dos binários gravados de Nó A referência, Nó A adaptativo, Nó B e Pico; o executor registra hash do `node_a.bin` local quando disponível, mas **isso não comprova sozinho o conteúdo do dispositivo**.

## 3. Desenho experimental

- Fatores: três densidades de perturbação × duas políticas (referência e adaptativa).
- Repetições: **6 sementes novas por combinação**, definidas e salvas antecipadamente → **36 ensaios oficiais**.
- Sementes na ordem de blocos 1–6: `0xEA125C50`, `0x361424B1`, `0x32CCD896`, `0x70B50ECB`, `0x7B21822C`, `0x02AE6661`. Obtidas determinística e independentemente dos resultados usando `random.Random(20261015).getrandbits(32)`, excluindo `0`, as antigas sementes `0x454A9485`, `0xCA2D51FF`, `0x6D2B79F5` e valores repetidos.
- Cada bloco usa a mesma semente nos seis testes (três perfis sob cada política), com ordens de perfil predefinidas. Nos blocos ímpares, referência vem antes; nos pares, adaptativo vem antes. As ordens de perfil variam entre blocos.
- As políticas são executadas em **grupos homogêneos de três runs** para evitar dezenas de gravações no Nó A. São cerca de **seis trocas de política ao longo de 36 runs**, e não uma troca em cada ensaio. Esse agrupamento reduz trabalho e limita, mas não elimina, efeitos de deriva temporal. Não reordenar com base no TEC observado.
- Executar **todos** os ensaios previstos, inclusive os que não ativarem throttling ou não apresentarem erro. Não encerrar antecipadamente por melhora ou piora aparente; se a coleta for interrompida externamente, registrar quais runs ficaram pendentes e o motivo.
- O tamanho amostral é viável para análise descritiva com intervalos de incerteza; 6 por condição/nível não garante poder estatístico para detectar efeitos pequenos nem incidência de Bus-Off rara.

## 4. Pré-validação obrigatória: Runs 151 e 152 (NÃO oficiais)

| Run | Política | Perfil | Semente | Duração | Papel |
|---|---|---|---|---|---|
| 151 | ADAPTATIVO (`throttling=1`) | ALTO | `0xCA2D51FF` | 40 s | Verificar confirmação do modo, integridade dos três logs, eventual `gap` e entradas nos modos ALERT/CRITICAL |
| 152 | REFERÊNCIA (`throttling=0`) | ALTO | `0xCA2D51FF` | 40 s | Verificar a transição de firmware, identificação no boot e compatibilidade com v1.5 |

Os pilotos são excluídos da estimativa oficial. Se não houver ativação do throttling no Run 151, **não reprovar apenas por isso**: verificar configuração, log e se TEC cruzou o limiar. Avaliar se o mecanismo efetivamente exercitou algum limiar antes de autorizar toda a campanha; como variação de fase pode produzir TEC baixo, um piloto adicional justificado pode ser necessário e deve receber **ID novo**.

Depois da validação, o Run 153 começa com referência; o Run 152 já deixa a bancada nesse modo.

## 5. Variáveis e desfechos pré-definidos

**Primário — ALTO:** máximo do TEC do Nó A observado durante os 40 s de injeção, comparando 6 referências × 6 adaptativos (um valor por ensaio). Extrair `SAMPLE.tec_peak` associado à janela de ruído e apresentar também `SAMPLE.tec` instantâneo; conferir a ambiguidade das amostras que cruzam `NOISE_START`/`NOISE_END` e realizar análise de sensibilidade excluindo amostras limítrofes.

**Secundários (todos os perfis):**

1. TEC instantâneo mediano, pico e evolução temporal; fração estimada do tempo acima de 96 e 128, usando amostragem e declarando a resolução temporal da estimativa.
2. Número de entradas reais em Error Passive e tempo total em Passive por transições `STATE_CHANGE` consistentes; não contar `WARNING->WARNING` como nova transição; distinguir Error Warning reportado pelo controlador de limiar TEC do algoritmo.
3. Eventos `ERROR` nos Nós A e B **por 40 s de ruído** e eventos/s; não chamar de perdas de quadros.
4. Eventos Bus-Off e recuperação, se ocorrerem. Um evento Bus-Off **não invalida** a execução se sua captura for íntegra.
5. `TX_SUCCESS` no Nó A e `RECEIVED` no Nó B durante a janela, taxas de entrega e latência quando disponíveis, respeitando bordas de captura e retransmissões.
6. `gap` e redução efetiva de submissões/atualizações no adaptativo; quantificar custo da mitigação. `gap` não entra no cálculo de perda de quadro CAN.
7. Quantos ensaios adaptativos apresentaram amostras nos modos ALERTA/CRÍTICO; ausência de ativação em um ensaio é resultado, não erro de protocolo.

Comparar métricas por perfil e política, mas manter a análise de ALTO como prioridade declarada antes de observar os resultados. Reportar todos os valores por run e **intervalos de confiança/compatibilidade**, preferindo diferenças absolutas e proporções; com n=6, qualquer inferência será sensível à variabilidade. A semelhança de semente pode orientar apresentação por bloco, sem supor mesma fase física.

## 6. Regras de validade e auditoria

- **Antes de enviar `s` ao Pico**, o executor abre as três seriais, verifica a versão do Pico e `CONFIG_OK`, e lê o boot do Nó A para confirmar `throttling=0/1` e 125 kbit/s.
- Depois do teste, verifica `TEST_START`, `NOISE_START`, `NOISE_END`, `TEST_END`, parâmetros/seed/pulsos calculados, `missed_deadlines=0`, duração (tolerância de 10 ms), presença de `SAMPLE` nos dois nós e preserva o ZIP em `data/zips/` e os dados em `data/raw/`.
- **Limitações do QC automático:** `qc.valid=true` prova consistência básica de execução, **não** que TEC tenha sido alto nem que a largura elétrica real seja 8 µs; a classificação final exige auditoria offline de janelas, `ERROR`, estados CAN e métricas.
- Se ocorrer pouco TX_SUCCESS/RECEIVED, o executor anota *warning*, não descarta o ensaio automaticamente: pode ser efeito real do throttling ou de erro grave. Ausência total de dados/telemetria por falha serial, modo incorreto, parâmetros divergentes ou fase incompleta é falha de execução.
- **Não excluir por:** TEC elevado/baixo, Bus-Off, Error Passive, retransmissões, `gap` alto, ausência de intervenção, ou entrega degradada. Repetição de tentativa invalida recebe **novo número de run** (não reutilizar o anterior) e conserva ZIP/log original. Usar um `plano_repeticoes.csv` separado com mesmo perfil, semente e política da célula prevista.
- Identificar quais mudanças operacionais foram necessárias (firmware do Nó A, reinício de bancada etc.). Manter, se possível, pausas iguais entre ensaios e condições físicas estáveis. O executor usa 3 s entre runs por padrão; elevar `--between` de modo consistente se necessário.

## 7. Limitações e interpretação científica

Não existe sincronismo físico Pico→CAN. Ensaio com mesma semente não garante colisões equivalentes em referência e adaptativo. A interpretação causal será restrita à randomização/balanceamento da campanha e à variabilidade observada, não à equivalência exata de pulsos que atingiram quadros. A parte de *Bus-Off* é formulada como **mitigação de indicadores associados ao risco** caso a referência não tenha Bus-Off observado. Não alegar prevenção demonstrada de um evento que não ocorreu.

**Critério para avançar:** os dois pilotos 151/152 devem confirmar o modo correto, integridade da captura e funcionamento do executor atualizado antes de começar os 36 ensaios oficiais. Nenhum dado da campanha oficial foi coletado na preparação deste documento.

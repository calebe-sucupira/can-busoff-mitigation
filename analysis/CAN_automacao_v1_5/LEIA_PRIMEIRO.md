# Automação dos ensaios CAN — Pico parametrizável v1.5

**Status:** protótipo para validação na bancada. Código C verificado sintaticamente com *stubs* do Pico SDK, mas **ainda não compilado com o Pico SDK real nem testado fisicamente nesta versão**. O executor Python passou em teste simulado ponta a ponta; é obrigatório validar o Run 145 antes de executar o lote restante.

## Para que serve

Um único firmware do Pico recebe por USB, **antes** de cada execução: ID do ensaio, perfil, intervalo mínimo, intervalo máximo, semente e duração da injeção. O programa no Linux lê o CSV do protocolo e executa, em sequência, os Runs 145–150. Ele captura três portas em paralelo, salva formatos compatíveis com `capture_v13.py`, verifica parâmetros e encerramento e gera um ZIP individual por run.

- **Não regravar o Pico entre runs.** Basta gravar esta versão uma vez.
- **O `injector.pio` é byte a byte idêntico ao v1.4.** GP2, GP4 e o circuito não mudam.
- **Não altera o firmware dos nós A e B.** Para os pilotos 145–150, o Nó A deve estar em `throttling=0`.
- **Não é a campanha oficial do TCC.** É um piloto de duração.

## Conteúdo

- `main.c`: firmware do Pico com parâmetros configuráveis por USB, preservando o agendamento absoluto do v1.4.
- `injector.pio`: PIO original com pulso nominal de 8 µs.
- `executar_lote.py`: aquisição e execução automatizada no Linux.
- `plano_runs_145_150.csv`: parâmetros e ordem **prescritos** dos seis pilotos, com pulsos ideais previstos.
- `requirements.txt`: dependência Python para a serial.

## 1. Gravar o firmware (uma única vez)

No projeto Pico SDK que você já compila, substitua `main.c` pelo `main.c` deste pacote. O `injector.pio` pode permanecer, pois está igual; mantenha seu `CMakeLists.txt` atual e as opções USB que você já usa.

No diretório do projeto, por exemplo:

```bash
cmake -S . -B build
cmake --build build -j4
```

Grave o `.uf2` produzido da mesma forma que você já utiliza. O nome e o caminho do `.uf2` dependem do seu `CMakeLists.txt`.

**Não regrave o firmware antigo entre os testes.** A versão v1.5 receberá os parâmetros diretamente do programa Python.

## 2. Preparar o Python (somente uma vez)

Abra o terminal na pasta extraída do pacote:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Verifique as portas Linux. Os valores habituais da sua bancada eram:

- `/dev/ttyUSB0` = Nó A;
- `/dev/ttyACM0` = Nó B;
- `/dev/ttyACM1` = Pico.

Os nomes podem mudar após reconectar os dispositivos. Confira com `ls -l /dev/serial/by-id/` ou com o comando que você já usa para identificar as portas. É possível substituir os caminhos nas opções `--node-a`, `--node-b`, `--pico`.

**Não execute `capture_v13.py` ao mesmo tempo que `executar_lote.py`**, porque os dois disputariam as mesmas portas.

## 3. Conferir o plano sem iniciar a bancada

```bash
python executar_lote.py --dry-run
```

O programa exibe as seis configurações e compara a contagem teórica de pulsos com o CSV, sem abrir portas seriais.

## 4. Primeiro ensaio: apenas Run 145

Com o Pico já gravado com `main.c` v1.5 e o Nó A em `throttling=0`:

```bash
python executar_lote.py --from-run 145 --to-run 145
```

Ele espera pela prontidão do Pico, verifica a confirmação da configuração e captura a execução inteira até `TEST_END`. Verifique o arquivo `data_automatizada/raw/run_145_injection/qc.json` e envie o ZIP `data_automatizada/zips/run_145_injection.zip` para auditoria.

**Se o 145 falhar**, não reaproveite esse mesmo ID. Preserve os dados e ajuste o planejamento para uma repetição com um ID novo.

## 5. Rodada restante em um só comando

**Somente depois de aprovar o primeiro ensaio em hardware:**

```bash
python executar_lote.py --from-run 146 --to-run 150
```

Isso executa os outros cinco com durações de 40, 60, 60, 40 e 20 segundos, ajustando a semente e a duração automaticamente sem regravar o Pico.

Para rodar todos os seis de uma vez, caso nenhum tenha sido executado ainda:

```bash
python executar_lote.py --from-run 145 --to-run 150
```

O programa **não sobrescreve** os runs existentes.

## 6. Fluxo por execução

1. Abre as três portas e registra os dados.
2. Solicita `STATUS` e exige `firmware=pico-param-v1.5` e `state=IDLE`.
3. Envia `CFG,<run>,<perfil>,<min>,<max>,<seed>,<duracao_s>`.
4. Aguarda `CONFIG_OK` e compara os parâmetros retornados ao CSV.
5. Envia `s` e aguarda `TEST_START`, `NOISE_START`, `NOISE_END` e `TEST_END`.
6. Verifica duração, contagem programada de pulsos, `missed_deadlines=0`, completude da aquisição e `throttling=0` no boot do Nó A.
7. Registra `qc.json` e cria um ZIP com todos os dados. Se houver erro, salva o que foi possível e **interrompe o lote**, sem ocultar a falha.

Pastas resultantes:

```text
data_automatizada/
  raw/
    run_145_injection/
      node_a.log, node_a.csv
      node_b.log, node_b.csv
      pico.log, pico.csv
      control_events.jsonl
      metadata.json
      qc.json
  zips/
    run_145_injection.zip
    run_146_injection.zip
    ...
```

Os logs e CSVs preservam o formato utilizado na captura `v13` (o ZIP inclui `qc.json`, um arquivo adicional de validação). O programa não realiza a análise científica de TEC, que continua sendo uma etapa posterior.

## 7. Protocolo serial do Pico

- `?` = solicitação de `STATUS`.
- `CFG,145,ALTO,9375,14375,454A9485,20\n` = configura um teste com parâmetros explícitos (somente no estado IDLE).
- `s` = inicia o teste com a configuração atual (mantém compatibilidade com o comando de início do `capture_v13.py`).
- `x` = aborta o teste e coloca GP2 em alta impedância.

A largura nominal do pulso permanece em 8 µs, definida no `injector.pio`. `pulse_count` representa **comandos enviados ao PIO**, não medições elétricas; a verificação com osciloscópio permanece pendente.

## Limitações importantes

- **Não houve compilação real com Pico SDK nem validação em hardware desta versão parametrizável.** Compilar/gravar e executar **um** piloto primeiro.
- Cada ensaio reabre as portas para obter os logs de boot e verificar `throttling=0`; os caminhos seriais precisam estar corretos.
- Não há realimentação automática para alterar o nível de perturbação conforme o TEC: as configurações vêm do **plano pré-registrado**, para não enviesar os resultados.
- O script interrompe o lote em erro de configuração, tempo, captura ou contagem; *não* reexecuta automaticamente tentativas inválidas com o mesmo ID.
- Uma semente igual reproduz a sequência de intervalos gerados, **não** a fase dos pulsos em relação aos quadros CAN.
- A automação não executa medições elétricas e não substitui a validação instrumental.

# TCC II — Telemetria complementar para progressão do TEC (proposta)

**Estado:** variante de código preparada e revisada apenas por comparação textual e teste de lógica isolada. **Não compilada com ESP-IDF, não gravada no ESP32 e não validada em bancada.** Não utilizar para nova injeção sem revisão e controle do circuito.

## Achado específico no firmware entregue

O Nó A consulta o status TWAI a cada **1 ms** (`MONITOR_PERIOD_MS`) e emite `SAMPLE` a cada **100 ms** (`HEARTBEAT_MS`), salvo mudança de estado ou de classe `NORMAL/ALERT/CRITICAL`. Acima de TEC=128 o modo continua `CRITICAL`; por isso a progressão 128→256 pode ficar subamostrada nos registros. O callback `STATE_CHANGE` continua sendo a evidência primária de Bus-Off.

## Alteração proposta (somente na cópia separada)

- Mantém id CAN, bitrate 125 kbit/s, política 100/50/25 Hz, callbacks TWAI, fila, janela de 1 ms, retry nativo, Pico e circuito **inalterados**.
- Adiciona uma emissão `SAMPLE` quando a consulta de 1 ms detectar **pela primeira vez** algum dos marcos 160, 192, 224 ou 240 (até quatro amostras adicionais por inicialização do Nó A); a amostra registra o **TEC realmente observado naquele instante**, sem inventar igualdade ao marco.
- Não reativa um marco caso o TEC diminua e volte a crescer, para evitar inundação serial. **Os marcos são rearmados somente após reinicialização do Nó A**; confirmar o boot em cada execução.
- Altera `FW_BUILD_TAG` para `node-a-throttling-v1.3-busoff-trace`, permitindo diferenciar resultados da campanha oficial de 60 ensaios.
- Preserva a estrutura CSV: linhas extras continuam sendo `SAMPLE`, e o analisador de Bus-Off já criado consegue lê-las sem mudar o parser.

**Limites:** o TWAI pode variar várias unidades dentro de 1 ms; um Bus-Off rápido pode acontecer sem que o monitor observe 160/192/224/240. A marcação extra não prova valores intermediários nem segurança elétrica. Quatro emissões extras não garantem integridade da UART sob uma tempestade de erros; conferir o campo `lost` e os logs.

## Reprodutibilidade

Usar essa variante, após revisão/compilação, **nos dois modos**; única diferença na compilação entre eles deve ser `ENABLE_THROTTLING=0/1`. Preservar binários, fontes, configuração ESP-IDF e SHA256 completos. Não misturar observações dessa variante com a campanha principal. Executar testes baseline/sem injeção antes de qualquer teste elétrico. Os 60 ensaios históricos permanecem intactos.

## Portão elétrico ainda pendente

O circuito conhecido chaveia o transistor entre CAN_H e CAN_L **sem resistor limitador em série no coletor/emissor**. O datasheet do SN65HVD230 contém características de corrente de saída e proteção térmica, mas isso não certifica o pulso real, a corrente no 2N2222, nem permite aumentar o regime de curtos sem avaliação elétrica. O comando `x` é parada lógica por USB, não uma proteção de hardware independente. Sem instrumento adequado e avaliação do circuito, **não iniciar novos perfis intensificados**.

## Próxima aplicação futura

Após validar a segurança do estágio de injeção, realizar piloto em referência, verificar evolução e entrada real `->BUS_OFF`; congelar regime e comparar com adaptativo em repetições predefinidas. O protocolo prospectivo já existente em `protocolo_busoff_TCC2_piloto_e_comparacao_2026-10-19.md` governa os ensaios; esta variante não os autoriza.

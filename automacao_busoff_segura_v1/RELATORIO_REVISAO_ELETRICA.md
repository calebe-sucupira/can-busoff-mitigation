# Revisão preliminar do injetor de perturbações — TCC II

**Escopo:** projeto existente, sem alterar PCBs, ligações, Node A/B ou os níveis BAIXO/MEDIO_V2/ALTO.

## Circuito informado pelo autor

- RP2040 Raspberry Pi Pico: GPIO GP2 -> resistor 1 kΩ -> base do transistor 2N2222.
- Resistor 10 kΩ entre base e emissor.
- Coletor em CAN_H, emissor em CAN_L.
- Dois transceptores SN65HVD230 na bancada CAN de 125 kbit/s.

O transistor estabelece uma ligação temporária comandada entre as linhas diferenciais. O método implementado **não reproduz automaticamente o acoplamento capacitivo de EMI** planejado no TCC I.

## Achados no firmware real

1. `firmware/pico-injector/injector.pio` usa `pull block`, `set pindirs, 1 [7]` e `set pindirs, 0`. O controlador configura o PIO para 1 MHz, programando pulsos nominais de 8 µs.
2. Existe o comando `x`/`X`, que chama `abort_test` e emite `TEST_ABORTED`. A afirmação anterior de que STOP não existia estava incorreta.
3. O término normal chama `injector_set_high_z()` **com a máquina PIO habilitada**. A documentação do Pico SDK recomenda configurar direção de pinos com a máquina de estados desabilitada; por isso há uma correção candidata isolada. Essa observação não comprova que o circuito tenha falhado nos ensaios anteriores.
4. `CFG` aceita durações de 5 a 180 s, intervalo mínimo de 1000 µs e os nomes de perfil previstos no firmware. **Aceitar um comando na sintaxe não equivale a validação elétrica.** O executor existente é mais restritivo e só libera os três perfis oficiais.
5. A monitoração Node A já emite `STATE_CHANGE` com `ACTIVE/WARNING/PASSIVE -> BUS_OFF` e amostras `SAMPLE` com estado. A automação segura detecta ambos.

## Limitações da revisão eletrônica

A TI declara proteção contra falhas e desligamento térmico do SN65HVD230, mas isso não certifica a segurança de curtos repetidos entre CAN_H e CAN_L em uma placa específica. Sem aferição de forma de onda, corrente real, tensão de acionamento do transistor e aquecimento interno, **não há base para estabelecer uma frequência ALTO_EXT segura**. O limite do transistor depende da versão física efetivamente instalada e das condições de comutação; não foi inferido a partir de números nominais.

Fontes: [TI SN65HVD230 datasheet Rev. O](https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf); [Raspberry Pi Pico SDK — hardware PIO](https://www.raspberrypi.com/documentation/pico-sdk/hardware.html).

## Decisão para a próxima etapa

Validar a confirmação STOP do Pico **sem iniciar pulsos**, usando `validar_stop_pico_idle.py`. Depois, verificar o comportamento do sistema de parada com parâmetros já utilizados, quando houver um procedimento seguro e controlado para isso. Não executar ALTO_EXT antes de validar as limitações elétricas e o mecanismo de parada.

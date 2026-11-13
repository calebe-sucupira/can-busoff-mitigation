# Throttling reativo em redes CAN

Projeto de Trabalho de Conclusão de Curso em Engenharia de Computação. Foram desenvolvidos firmwares, placas de circuito impresso e ferramentas de aquisição para avaliar o controle reativo de submissões CAN sob perturbações elétricas.

## O experimento

A bancada reúne dois nós ESP32-WROOM-32 com transceptores SN65HVD230, conectados a um barramento CAN clássico de **125 kbit/s**, e um injetor independente com Raspberry Pi Pico (RP2040) e transistor 2N2222. O Nó A produz e transmite as atualizações; o Nó B registra os quadros recebidos.

No Nó A, uma política de *throttling* usa o contador de erros de transmissão (TEC) para alterar a frequência nominal de novas submissões:

| Faixa de TEC | Modo | Taxa nominal |
| --- | --- | ---: |
| 0–95 | Normal | 100 Hz |
| 96–127 | Alerta | 50 Hz |
| 128 ou mais | Crítico | 25 Hz |

A produção da aplicação continua em **100 Hz**. Uma fila de uma posição mantém somente a atualização mais recente (*latest-only*). A política não modifica a retransmissão automática do controlador. A mesma base de firmware é utilizada na condição de referência (`ENABLE_THROTTLING=0`) e na condição reativa (`ENABLE_THROTTLING=1`), por meio de configurações distintas de compilação.

## Resultados

Foram realizados **100 ensaios** em dois conjuntos:

- **60 ensaios de caracterização:** três densidades de perturbação e duas condições de operação, com dez repetições por grupo. Nenhum atingiu Bus-Off. No perfil de maior densidade, a política reduziu o número de atualizações efetivamente entregues.
- **40 ensaios de progressão até Bus-Off:** 20 por condição. Todos alcançaram Bus-Off. O tempo médio foi de **10,39 s** na referência e **12,08 s** na condição reativa. A comparação estatística não foi significativa (Mann–Whitney bilateral, `p ≈ 0,285`).

No segundo anterior ao Bus-Off, a média de transmissões concluídas foi de **97,2** na referência e **28,7** na condição reativa, redução aproximada de **70,5%**. A contenção do tráfego foi observada, mas **não foi demonstrado que a política evita ou retarda de forma consistente o Bus-Off**. A menor frequência de atualizações recebidas é um custo da estratégia.

## Estrutura do repositório

| Pasta | Conteúdo |
| --- | --- |
| `firmware/node-a/` | Firmware transmissor e política reativa |
| `firmware/node-b/` | Firmware receptor |
| `firmware/pico-injector/` | Firmware parametrizável do injetor (caracterização) |
| `hardware/` | Projetos KiCad das duas placas e bibliotecas |
| `experiments/characterization/` | Executores e planos dos 60 ensaios |
| `experiments/busoff/` | Código e plano dos 40 ensaios de progressão |
| `analysis/` | Scripts, tabelas e verificações dos dados |
| `data/` | Registros originais, ensaios preliminares e pacotes compactados |
| `docs/` | Documentação de fabricação |

O código do injetor para a campanha de progressão até Bus-Off está em `experiments/busoff/main_phase20.c` e `experiments/busoff/injector.pio`; é distinto do firmware parametrizável da caracterização.

Os 60 ensaios compreendem as execuções **153–188** e **197–220**. Os 40 ensaios de progressão compreendem **304–343**. Os ensaios **300 e 303** são preliminares e não integram a amostra de 40. Registros brutos, arquivos de execução e hashes de binários foram conservados para conferência dos resultados.

Veja [experiments/README.md](experiments/README.md) para localizar os programas e planos.

## Tecnologias

ESP-IDF 6.0.2, FreeRTOS, Raspberry Pi Pico SDK, PIO, C, Python 3 (pyserial) e KiCad.

A compilação e a execução exigem as ferramentas e configurações de cada placa. Não se deve executar campanhas físicas sem conferir previamente as conexões, o circuito de injeção e os mecanismos de interrupção.

## Limitações e segurança

O circuito injetor comuta temporariamente CAN_H e CAN_L. Foi desenvolvido **exclusivamente para uma bancada isolada**; não se destina à injeção de falhas em veículos ou equipamentos em operação. A parada controlada por software não substitui a possibilidade de desenergização física.

Os resultados se referem à configuração experimental descrita; não estabelecem parâmetros ótimos para outras redes CAN.

# Investigacao offline do saldo de TEC e risco de Bus-Off

Base: registros SAMPLE do No A, nos 12 ensaios ALTO oficiais e 6 exploratorios (191–196).
Janelas regulares: 80 a 120 ms. Nao foram executados testes fisicos.

## Observacao direta

- Maior sequencia de janelas regulares com novo evento ERROR e TEC inicial >=96: **3**.
- Maior sequencia com novo evento ERROR em qualquer faixa de TEC: **7**.
- Essas contagens dependem da discretizacao em cerca de 100 ms; pulsos/erros podem ocorrer concentrados dentro de uma janela.

## Simulacao ilustrativa (nao e modelo fisico validado)

Em cada janela de 100 ms, a evolucao aproximada e `TEC_prox = max(0, TEC_atual + 8*eventos_ERROR - TX_sucesso)`.
Para a referencia admite-se 10 sucessos/janela; para a politica, 10 se TEC<96, 5 se 96<=TEC<128, e 2/3 alternados quando TEC>=128.
Os eventos ERROR sao impostos artificialmente e nao dependem da quantidade de transmissoes. Isso NAO descreve fielmente o controlador real.

| TEC inicial | Eventos ERROR/100 ms | Modo | Tempo ate >=256 |
|---:|---:|---|---:|
| 96 | 0 | REFERENCIA | nao em 60 s |
| 96 | 0 | REATIVO | nao em 60 s |
| 96 | 1 | REFERENCIA | nao em 60 s |
| 96 | 1 | REATIVO | 3.5 |
| 96 | 2 | REFERENCIA | 2.7 |
| 96 | 2 | REATIVO | 1.3 |
| 128 | 0 | REFERENCIA | nao em 60 s |
| 128 | 0 | REATIVO | nao em 60 s |
| 128 | 1 | REFERENCIA | nao em 60 s |
| 128 | 1 | REATIVO | 2.4 |
| 128 | 2 | REFERENCIA | 2.2 |
| 128 | 2 | REATIVO | 1.0 |

## Cautelas metodologicas

- `ERROR` e um evento de software; nao e necessariamente um erro fisico CAN independente nem uma medida universal de TEC +8.
- A politica modifica as tentativas de transmissao e, portanto, tambem altera a oportunidade de gerar novos eventos. Nao e valido manter os mesmos erros como forca externa para prever o resultado real.
- As janelas de um mesmo ensaio sao correlacionadas; o perfil do injetor nao e sincronizado com o inicio dos quadros.
- O resultado nao valida eletricamente o injetor, nem estabelece frequencia ou intensidade segura de curtos.
- A observacao de uma eventual entrada em Bus-Off exigiria o evento STATE_CHANGE no equipamento; um valor calculado de TEC >=256 nao a comprova.

## Implicacao

Os registros sustentam que o saldo entre erros e transmissões bem-sucedidas determina a tendencia observada do TEC. A simulacao sugere por que a frequencia de transmissao pode alterar a recuperacao, mas nao permite prever que um novo perfil fisico produziria Bus-Off.

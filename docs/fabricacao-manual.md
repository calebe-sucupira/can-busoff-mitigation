# Placas para fabricação manual

As duas placas usam trilhas somente em **F.Cu**, sem vias. A montagem e o
espelhamento da transferência devem seguir o método escolhido para colocar os
componentes na face oposta ao cobre. O nome F.Cu, por si só, não define o lado
físico da montagem.

## Dimensões adotadas

| Elemento | Ilha de cobre | Furo |
| --- | --- | --- |
| ESP32, Pico, módulos CAN, conectores e jumpers | 2,1 × 2,1 mm | 1,0 mm |
| Resistores e capacitores | 2,2 × 2,2 mm | 0,8 mm |
| Transistor Q1 | 2,1 × 2,1 mm | 0,8 mm |
| Pontos de teste existentes | 2,5 × 2,5 mm | 1,2 mm |

Todas as trilhas atuais têm **1,0 mm** de largura. As regras de projeto usam
**0,4 mm de isolamento mínimo** e **0,5 mm de largura mínima**, com largura
padrão de roteamento de 1,0 mm. São escolhas para facilitar o processo manual;
a qualidade da transferência, corrosão e furação ainda precisa ser conferida.

## Footprints e conexões

- Os footprints adaptados estão na biblioteca local
  `hardware/libraries/manual_tht.pretty`, registrada nos dois projetos.
- Os esquemáticos apontam para essa biblioteca, de modo que atualizar a PCB a
  partir do esquemático preserva a seleção dos footprints adaptados.
- O Pico usa o footprint THT, com 40 furos, sem ilhas SMD duplicadas. As posições
  dos 40 furos são as mesmas da versão anterior. Os sete pinos GND utilizados
  no esquemático estão interligados pela própria placa, respeitando a área de
  exclusão de cobre do footprint comum Pico/Pico W.
- Q1 usa o footprint TO-92 com pinos em linha e passo de **2,54 mm**. A ordem
  elétrica foi preservada: **1 = emissor, 2 = base, 3 = coletor**. Será necessário
  acomodar os terminais nesse espaçamento; confira a pinagem do transistor real.
- As posições dos furos dos demais componentes foram preservadas.
- Os circuitos dos módulos CAN não foram modificados. Confira a pinagem e os
  componentes já presentes nos módulos quando chegarem.

## Conferência antes da fabricação

1. Imprima em escala **100% / 1:1**, sem ajustar à página. Confira com uma régua
   uma distância conhecida; dez intervalos de 2,54 mm devem medir 25,4 mm.
2. Teste os dois alinhamentos de pinos do ESP32 e do Pico, além dos módulos CAN,
   conectores e soquetes reais. Testar apenas o ESP32 valida somente seu encaixe.
3. Confira a posição do pino 1 e do USB pelo lado em que os componentes serão
   montados. Valide a orientação final após considerar a transferência do papel.
4. Use os diâmetros de furo como referência e confira o encaixe dos terminais
   antes de furar a placa inteira.

## Verificação desta revisão

As duas PCBs passaram no DRC do KiCad 10.0.5, com isolamento de 0,4 mm:
**zero violações, zero conexões pendentes e zero divergências com o esquemático**.

O ERC da injetora passou sem apontamentos. O ERC da placa do experimento mantém
os três apontamentos de alimentação já existentes (GND e entradas 3V3 dos
módulos CAN); esta revisão não alterou a modelagem elétrica dos símbolos.
As conexões dos esquemáticos foram comparadas com a versão anterior.

Essas verificações cobrem os arquivos de projeto. O encaixe nas peças reais e
o funcionamento elétrico ainda dependem da montagem e dos testes em bancada.

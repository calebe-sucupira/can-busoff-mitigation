# Auditoria de proveniencia dos aplicativos do No A

## Cobertura

- Runs examinados: **60/60**; validacao dos hashes em metadados: **OK**.
- Os hashes representam SHA-256 do aplicativo registrado em cada ZIP.
- A origem exata dos executaveis so e comprovada se arquivos .bin encontrados forem identicos aos hashes.

## Grupos

| Campanha | Politica | Runs | SHA-256 | Arquivos .bin coincidentes |
|---|---|---:|---|---:|
| ORIGINAL | REFERENCIA | 18 | `4e65131036fcd9db999a5fe67f4874f7d2c319b4d5d3caa89ad65e871c6a14e5` | 1 |
| ORIGINAL | ADAPTATIVO | 18 | `4e4fae386a6c46addd32ef862b35a4d769ba570479ff8528d418f6c5e23cb707` | 0 |
| COMPLEMENTAR | REFERENCIA | 12 | `559b0773e025a2639186503acd75b3ccc30ea7caebbe966ae457a0d65ce0dd6e` | 2 |
| COMPLEMENTAR | ADAPTATIVO | 12 | `e65d74af829c0307988542a2483300d2f8435a9674dafce1c9b1495da56cf3db` | 2 |

## Interpretacao metodologica

- Binarios iguais byte a byte entre campanhas para cada politica: **FALSE**.
- Hashes distintos **nao** comprovam mudanca funcional e **nao** comprovam equivalencia.
- Manifestos podem apontar para hashes, mas a correspondencia dos arquivos reais exige conferir .bin.
- Fontes encontradas agora sao instantaneos atuais; vinculacao a compilacoes historicas depende de evidencia.
- A comparabilidade funcional completa entre campanhas permanece **NAO COMPROVADA** ate auditoria de fontes e compilacao historica.

## Arquivos binarios correspondentes encontrados

- ORIGINAL / REFERENCIA: `/home/calebe/Documentos/tcc/can-busoff-mitigation/firmware/node-a/build/node_a.bin`
- ORIGINAL / ADAPTATIVO: **NAO LOCALIZADO**
- COMPLEMENTAR / REFERENCIA: `/home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/node_a_referencia.bin`, `/home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/workspaces/referencia/build/node_a.bin`
- COMPLEMENTAR / ADAPTATIVO: `/home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/node_a_adaptativo.bin`, `/home/calebe/Documentos/tcc/can-busoff-mitigation/automacao_complementar_CAN_TCC2_v2/binarios_node_a_complementar/workspaces/adaptativo/build/node_a.bin`

## Pistas adicionais

- Manifestos com hashes relacionados: 3 registros.
- Pares atuais de fontes C encontrados: 3.
- Consulte `manifestos_e_hashes.csv` e `instantaneos_fontes.csv`.
- Nenhum firmware foi compilado, gravado, modificado ou executado.

# Campanha CAN: como integrar ao seu projeto existente

Coloque **somente** estes três arquivos na pasta do seu executor atual:

```text
~/Documentos/tcc/can-busoff-mitigation/analysis/CAN_automacao_v1_5/
  executar_campanha_CAN.py
  plano_prevalidacao_CAN_runs_151_152.csv
  plano_oficial_CAN_runs_153_188.csv
```

**Não substitua `executar_lote.py`**, nem `capture.py`, nem o `main.c` da Pico v1.5. **Não altere as ligações físicas.**

Abra o terminal na raiz do projeto:

```bash
cd ~/Documentos/tcc/can-busoff-mitigation
```

Confira os planos **sem abrir dispositivos**:

```bash
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py --plan analysis/CAN_automacao_v1_5/plano_prevalidacao_CAN_runs_151_152.csv --dry-run
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py --dry-run
```

## Antes de qualquer run oficial: 2 testes-piloto

**Run 151:** carregue a versão do Nó A com `ENABLE_THROTTLING=1` (adaptativo). O executor verificará a linha `throttling=1` no boot antes de enviar o comando de início:

```bash
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py \
  --plan analysis/CAN_automacao_v1_5/plano_prevalidacao_CAN_runs_151_152.csv \
  --from-run 151 --to-run 151
```

**Run 152:** carregue a versão de referência do Nó A com `ENABLE_THROTTLING=0`:

```bash
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py \
  --plan analysis/CAN_automacao_v1_5/plano_prevalidacao_CAN_runs_151_152.csv \
  --from-run 152 --to-run 152
```

**Pare e envie os dois ZIPs para auditoria antes de começar os oficiais.** O Run 151/152 continua sendo piloto, independentemente do TEC observado.

## Campanha oficial — NÃO iniciar antes de liberar os pilotos

O arquivo oficial possui Runs 153–188 e seis blocos. Cada grupo de três runs usa **a mesma política**, e o executor bloqueia automaticamente um pedido de executar grupos que misturem referência e adaptativo. Isso é intencional: ele **não regrava automaticamente** o firmware do Nó A.

Quando autorizados, os primeiros grupos são:

```bash
# Com Nó A em REFERÊNCIA, executar primeiro grupo de 3
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py --from-run 153 --to-run 155

# Trocar Nó A para ADAPTATIVO e executar o próximo grupo
python3 analysis/CAN_automacao_v1_5/executar_campanha_CAN.py --from-run 156 --to-run 158
```

Seguir exatamente o plano CSV; não alterar a ordem após verificar resultados. São **seis trocas de política durante os 36 runs**, em vez de 36 novas gravações no Pico. **O firmware Pico v1.5 já serve para todos os ensaios.**

## Destino dos arquivos

Nenhuma pasta `automatizada` será criada:

```text
data/raw/run_151_injection/  (logs, CSVs, metadata.json, qc.json etc.)
data/zips/run_151_injection.zip
```

O script detecta o diretório raiz pelo local onde foi instalado (dois níveis acima de `analysis/CAN_automacao_v1_5`). Ele não sobrescreve um Run existente.

## Importante

- `qc.valid=true` não é análise científica final: só indica que a captura passou pelos testes básicos automáticos.
- `node_a_binary_sha256` pode aparecer como `null` se não encontrar `firmware/node-a/build/node_a.bin`; revise o artefato realmente gravado.
- Se o modo não corresponder ao plano, o script interrompe **antes do comando `s`**; conserva os arquivos para auditoria.
- Um Run interrompido ou inválido **não deve ter seu ID reutilizado**.
- Feche qualquer outro programa que esteja acessando as portas seriais (inclusive `capture.py`).
- Todos os parâmetros técnicos, as métricas e limitações estão no arquivo `protocolo_campanha_oficial_CAN_v1_2026-10-15.md`.

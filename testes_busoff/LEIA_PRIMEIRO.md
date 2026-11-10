# Preparação de parada por Bus-Off (offline)

Este pacote **não é um novo perfil de injeção** e **não está autorizado para ensaios que intensifiquem curtos**. Ele contém exclusivamente uma correção de fluxo de controle no computador e testes sintéticos.

Conteúdo:

- `correcao_host_busoff.patch`: alteração proposta somente para `executar_campanha_CAN_seguro.py`;
- `automacao_busoff_segura_v1/executar_campanha_CAN_seguro.py`: cópia completa do mesmo executor com a correção;
- `testar_parada_busoff_offline.py`: 7 testes com portas simuladas;
- `RELATORIO_REVISAO_BUSOFF.md`: achados, verificações e limites.

**Primeiro, apenas os testes offline:**

```bash
python3 testar_parada_busoff_offline.py
```

**Para verificar se a correção se aplica ao código que você tem, sem alterá-lo:**

```bash
cd ~/Documentos/tcc/can-busoff-mitigation
patch -p1 --dry-run < /caminho/onde/descompactou/correcao_host_busoff.patch
```

Não há alteração de `firmware/node-a`, `firmware/pico-injector` ou do PIO. O arquivo de orquestração também permanece inalterado. **Qualquer resultado desses testes é exclusivamente uma validação lógica no computador.**

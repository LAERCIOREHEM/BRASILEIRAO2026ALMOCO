# Orchestrator BR Almoço 1.1.4 — correção de dispatch e backoff AF

A versão 1.1.4 mantém o workflow robusto único `Atualizar Brasileirao (ESPN)` e corrige três pontos:

1. `workflow_dispatch` aceita qualquer resposta HTTP 2xx do GitHub. Em especial, HTTP 200 com `workflow_run_id` deixa de ser classificado como `degraded`.
2. A mesma divergência AF (`resultados:reconhecidos`) não gera Actions sucessivas: após um dispatch `forcar_af=true`, a mesma assinatura entra em backoff por 120 minutos. Se a divergência mudar porque entrou novo resultado, ela volta a ser elegível.
3. `/health` e `/status` passam a informar `passesEventIdsToMainWorkflow`, sem referência ao workflow de núcleo rápido removido.

Mantidos: FINAL por summary/event_id, fallback scoreboard BRT+UTC, polling de 60 s, debounce 0 s, retry de convergência, circuit breaker de runs e coleta completa no workflow principal.

Excluídos do escopo: AO VIVO, públicos, melhores momentos, elencos e fair play.

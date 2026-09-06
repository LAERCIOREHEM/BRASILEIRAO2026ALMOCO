# Orchestrator BR Almoço 1.1.3 — workflow robusto único

A versão 1.1.3 remove o workflow `Atualizar núcleo rápido do Brasileirão`.

Quando a ESPN confirma FINAL por `event_id`, o Worker dispara diretamente `Atualizar Brasileirao (ESPN)` com `coleta_completa=true`, `forcar_af=false` e o(s) `event_id(s)` para reconciliação direta via summary ESPN.

Mantidos: summary por event_id, fallback scoreboard BRT+UTC, polling de 60 s, debounce 0 s, retry de convergência e circuit breakers.

Excluídos: AO VIVO, públicos, melhores momentos, elencos e fair play.

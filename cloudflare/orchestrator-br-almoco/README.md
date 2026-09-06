# Orchestrator BR Almoço 1.1.2 — FAST CORE + FINAL por event_id

Orquestrador independente do repositório `LAERCIOREHEM/BRASILEIRAO2026ALMOCO`.
O site continua no GitHub Pages; Cloudflare é usado somente para o Worker/DO de decisão.

## Fora do escopo

O motor NÃO observa nem dispara:

- AO VIVO;
- públicos;
- melhores momentos;
- elencos;
- fair play.

## Recursos exclusivos

- Worker: `brasileirao-almoco-orchestrator`;
- Durable Object: `BrAlmocoOrchestratorStateV1`;
- binding: `ORCHESTRATOR_STATE`;
- PAT GitHub: `BR_ALMOCO_ORCHESTRATOR_GITHUB_TOKEN`;
- API token Cloudflare: `BR_ALMOCO_CF_API_TOKEN`;
- Account ID: `BR_ALMOCO_CF_ACCOUNT_ID`.

Nenhum token/secret do Fórmula do Gol é reutilizado.

## Arquitetura 1.1.2

`Cloudflare Cron (1 min) -> Worker -> Durable Object -> decisão -> workflow_dispatch somente se necessário`

### FINAL: caminho rápido

1. Worker consulta `summary?event=<event_id>` da ESPN a cada 60 s na janela de encerramento.
2. O summary individual é fonte primária; scoreboard BRT+UTC é apenas fallback.
3. Assim que o summary confirma `post/completed`, não existe mais debounce artificial: o FAST CORE é elegível no mesmo tick.
4. O Worker envia o(s) `event_id` confirmado(s) ao workflow `Atualizar núcleo rápido do Brasileirão`.
5. O FAST CORE instala `curl-cffi` (Chrome impersonation) para não depender de `urllib`, que recebe HTTP 403 da ESPN em runners GitHub.
6. O FAST CORE usa coleta incremental rápida e força o `summary` exatamente para os `event_id` recebidos. Em execução manual, também verifica proativamente jogos recentes ainda não finalizados.
7. Publica imediatamente `tabela.json`, `jogos.json`, `resultados.json`, calendário e, quando possível, `apuracao.json` + `ranking-apostas.json`.
8. Depois enfileira `Atualizar Brasileirao (ESPN)` com `coleta_completa=true` para estatísticas/AF/derivados.

Assim, resultado/tabela/apostas/bolão não ficam esperando uma varredura completa antes da primeira publicação.

### Por que a 1.1.1 podia preservar um snapshot velho

O `fetch_json()` já tinha transporte `curl-cffi`, mas o FAST CORE não instalava o pacote. Em runner GitHub a ESPN respondeu `403` ao fallback `urllib`; o coletor corretamente preservou o snapshot anterior, porém o workflow terminou verde sem resultado novo. A 1.1.2 corrige o transporte do FAST CORE.

Além disso, o `summary` antes só era usado pelo coletor quando havia divergência entre standings e resultados. Se os dois endpoints agregados estivessem igualmente atrasados, o fallback não era acionado. A 1.1.2 faz a reconciliação proativa por `event_id` antes dessa auditoria.

### Recovery

- FINAL normal: sondagem a cada 60 s;
- dispatch no mesmo tick após FINAL confirmado;
- retry FAST: 3 min se o resultado ainda não convergiu;
- guard externo do FAST também usa 3 min, não os 15 min genéricos;
- recovery: até +12 h, a cada 5 min;
- circuit breaker de blocos continua ativo;
- workflows pesados do orquestrador sempre recebem `coleta_completa=true`.

## Ações automáticas permitidas

1. `Atualizar núcleo rápido do Brasileirão` — FINAL ainda não incorporado.
2. `Atualizar Brasileirao (ESPN)` — manutenção/reconciliação completa.
3. `Atualizar Brasileirao (ESPN)` com `forcar_af=true` — AF defasado.
4. `Apurar Apostas Brasileirão` — resultados e apuração divergentes.
5. `Sincronizar blocos de apostas` — fronteira/crítica válida.
6. `Buscar transmissões ...` com `modo=tv` — cobertura/urgência.

## SHADOW / ACTIVE

- `shadow`: calcula e registra candidatos sem disparar GitHub;
- `active`: habilita `workflow_dispatch`.

Após subir a 1.1.2, execute `Deploy Orchestrator BR Almoço` em `active`.

O Summary do workflow de deploy imprime e preserva as URLs completas de `/health` e `/status`.

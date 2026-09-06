# Orchestrator BR Almoço 1.1.0 — FAST CORE

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

## Arquitetura 1.1.0

`Cloudflare Cron (1 min) -> Worker -> Durable Object -> decisão -> workflow_dispatch somente se necessário`

### FINAL: caminho rápido

O FINAL não chama mais de imediato o workflow pesado. A sequência é:

1. Worker consulta `summary?event=<event_id>` da ESPN a cada 60 s na janela de encerramento;
2. fallback usa scoreboard em ambas as datas possíveis, BRT e UTC;
3. após 45 s de debounce, chama `Atualizar núcleo rápido do Brasileirão`;
4. o workflow rápido força `ESPN_COLETA_COMPLETA=true`;
5. publica imediatamente `tabela.json`, `jogos.json`, `resultados.json`, calendário e, quando possível, `apuracao.json` + `ranking-apostas.json`;
6. depois enfileira `Atualizar Brasileirao (ESPN)` com `coleta_completa=true` para estatísticas/AF/derivados.

As telas críticas consultam primeiro o `main` bruto do GitHub e usam GitHub Pages apenas como fallback. Assim resultado/tabela/apostas/bolão não precisam aguardar o deploy completo do site.

### Recovery

- FINAL normal: sondagem a cada 60 s;
- recovery: até +12 h, a cada 5 min;
- recovery de FINAL não bloqueia mais indefinidamente as rotinas lentas;
- checkpoint de bloco vencido passa a ser condição explícita de recuperação;
- workflows pesados do orquestrador sempre recebem `coleta_completa=true`.

## Ações automáticas permitidas

1. `Atualizar núcleo rápido do Brasileirão` — FINAL ainda não incorporado.
2. `Atualizar Brasileirao (ESPN)` — manutenção/reconciliação completa.
3. `Atualizar Brasileirao (ESPN)` com `forcar_af=true` — AF defasado.
4. `Apurar Apostas Brasileirão` — resultados e apuração divergentes.
5. `Sincronizar blocos de apostas` — fronteira, crítica ou checkpoint vencido.
6. `Buscar transmissões ...` com `modo=tv` — cobertura/urgência.

## SHADOW / ACTIVE

- `shadow`: calcula e registra candidatos sem disparar GitHub;
- `active`: habilita `workflow_dispatch`.

Após subir esta versão, redeploy do Worker em `active` é necessário para o código 1.1.0 entrar em produção.

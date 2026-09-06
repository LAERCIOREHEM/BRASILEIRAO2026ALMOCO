# Orchestrator BR Almoço 1.0.1

Este pacote cria um orquestrador **independente** para o repositório `LAERCIOREHEM/BRASILEIRAO2026ALMOCO`.

## Escopo excluído por decisão de produto

O motor NÃO observa nem dispara rotinas de:

- AO VIVO;
- públicos;
- melhores momentos;
- elencos;
- fair play.

Esses módulos não fazem parte da matriz de ações.

## Recursos separados do Fórmula do Gol

O pacote cria nomes próprios:

- Worker: `brasileirao-almoco-orchestrator`;
- Durable Object: `BrAlmocoOrchestratorStateV1`;
- binding: `ORCHESTRATOR_STATE`;
- PAT GitHub esperado: `BR_ALMOCO_ORCHESTRATOR_GITHUB_TOKEN`;
- API token Cloudflare esperado: `BR_ALMOCO_CF_API_TOKEN`;
- Account ID armazenado separadamente: `BR_ALMOCO_CF_ACCOUNT_ID`.

Nenhum nome de secret/token do Fórmula do Gol aparece no workflow.

## Arquitetura

`Cloudflare Cron (1 min) -> Worker -> Durable Object -> decisão determinística -> workflow_dispatch somente se necessário`

O site continua no GitHub Pages. `workers.dev` é usado apenas pelo orquestrador.

## Decisões automáticas permitidas

1. `Atualizar Brasileirao (ESPN)`
   - FINAL ESPN ainda não incorporado;
   - reconciliação de calendário/TBA;
   - auditoria crítica;
   - snapshot realmente envelhecido, com limites menores perto de jogos.
2. `Apurar Apostas Brasileirão`
   - somente quando resultados e jogos apurados divergem.
3. `Atualizar Brasileirao (ESPN) / forcar_af=true`
   - somente quando AF está atrás dos resultados.
4. `Sincronizar blocos de apostas`
   - fronteira real de abertura/fechamento;
   - inconsistência crítica;
   - safety net contextual (não a cada 6 h).
5. `Buscar transmissões ... / modo=tv`
   - orientado por jogos sem grade e urgência;
   - nunca `modo=aovivo`.

## TV

Não existe mais “rodar uma vez por dia” se a cobertura já estiver completa.
O Worker compara diretamente o calendário futuro com `dados-br/transmissoes-tv.json`:

- faltando em <72 h: retenta após 3 h;
- faltando em <14 d: retenta após 24 h;
- faltando em <35 d: retenta após 48 h;
- cobertura completa: nenhuma Action de TV por simples troca de data.

## FINAL

O Worker começa a sondar ESPN apenas perto do horário provável de encerramento.
Ele não acompanha gol, placar, cartão ou evento AO VIVO.

Quando detecta FINAL ainda ausente de `resultados.json`:

- espera debounce de 90 s para agrupar finais próximos;
- revalida `resultados.json` imediatamente antes do dispatch;
- verifica writer ativo no GitHub;
- aplica cooldown;
- dispara uma única atualização quando necessário.

## SHADOW / ACTIVE

- `shadow`: calcula e registra candidatos, mas não dispara GitHub.
- `active`: habilita `workflow_dispatch`.

Primeiro deploy obrigatório: `shadow`.

## O cron-job.org

Não pause antes de validar o Worker em SHADOW.
Depois da validação:

1. pause o cron-job.org que chama `orquestrador-inteligente.yml`;
2. imediatamente faça novo deploy deste Worker em `active`;
3. mantenha o cron externo apenas pausado por alguns dias como contingência;
4. o workflow antigo pode permanecer no GitHub para execução manual/dry-run.


## Convergência de FINAL — 1.0.1

- ESPN FINAL: anti-cache em query, headers e `cf.cacheTtl=0`.
- Recovery path até +24h; após +300 min, polling a cada 15 min.
- `pendingFinals` só é resolvido quando `resultados.json` contém o `event_id`.
- Sem convergência, novo dispatch é permitido após 15 min, respeitando writer gate.
- AO VIVO do navegador desativado; Resultados usa somente o snapshot consolidado.

# Orchestrator BR Almoço 1.1.6 — correção do fetch ESPN na Cloudflare

A versão 1.1.6 mantém um único workflow esportivo robusto: `Atualizar Brasileirao (ESPN)`.

## Correção principal

1. **Scoreboard ESPN como fonte primária**, usando a mesma estratégia browser-like comprovada no orquestrador do Fórmula do Gol: `Mozilla/5.0`, `Cache-Control: no-cache`, cache Cloudflare desativado e timeout de 8 s.
2. Consulta as partições de data **BRT e UTC** para evitar perda de jogos noturnos.
3. **Summary por `event_id` vira fallback/segunda opinião**, não mais a única fonte primária.
4. **Safety trigger temporal em T+110 min**: se o jogo ainda não consta em `resultados.json`, o Worker chama o `Atualizar Brasileirao (ESPN)` robusto mesmo que scoreboard e summary do Cloudflare falhem.
5. O safety trigger respeita **retry mínimo de 5 min**, writer gate, circuit breaker e revalidação de `resultados.json`, evitando tempestade de Actions.
6. `/status` expõe diagnóstico do último probe (`scoreboardHits`, `summaryHits`, `unresolved`, warnings), facilitando auditoria futura.

## Fluxo

```text
Cloudflare Cron 1 min
  ↓
T+88: scoreboard ESPN (browser-like)
  ↓
se não resolver → summary por event_id
  ↓
FINAL detectado → Atualizar Brasileirao imediatamente

OU, independentemente das fontes Cloudflare:

T+110 e ainda ausente de resultados.json
  ↓
safety trigger
  ↓
Atualizar Brasileirao (coleta_completa=true + event_ids)
  ↓
coletor robusto GitHub/curl_cffi decide o estado real
```

Excluídos do escopo: AO VIVO, públicos, melhores momentos, elencos e fair play.


## Correção 1.1.6

A 1.1.5 combinava `cache: "no-store"` com `cf.cacheTtl = 0`.
O runtime Cloudflare rejeitava a subrequest antes de acessar a ESPN.

A 1.1.6 mantém `cache: "no-store"`, headers `no-cache` e a query
`orch=<minuto>` para cache-busting, removendo somente `cf.cacheTtl`.

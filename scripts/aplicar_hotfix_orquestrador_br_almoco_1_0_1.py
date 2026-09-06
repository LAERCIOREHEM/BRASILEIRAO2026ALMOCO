#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# REVISÃO R1: não modifica arquivos em .github/workflows; workflows são atualizados manualmente pelo usuário.
"""HOTFIX Orchestrator BR Almoço 1.0.1.

Aplica sobre o HEAD ATUAL do repositório, sem substituir o site por uma cópia
antiga. Falha fechado se a estrutura esperada tiver mudado.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "cloudflare/orchestrator-br-almoco/src/index.js"
TESTS = ROOT / "cloudflare/orchestrator-br-almoco/test/orchestrator.test.mjs"
PACKAGE = ROOT / "cloudflare/orchestrator-br-almoco/package.json"
WRANGLER = ROOT / "cloudflare/orchestrator-br-almoco/wrangler.toml"
INDEX = ROOT / "index.html"
README = ROOT / "cloudflare/orchestrator-br-almoco/README.md"

MARKER = "FINAL_CONVERGENCE_1_0_1"


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"ERRO: arquivo esperado não existe: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ERRO: {label}: esperado 1 match literal, encontrado {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, repl: str, label: str, flags=0) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"ERRO: {label}: esperado 1 match regex, encontrado {count}")
    return out


def patch_worker() -> None:
    s = read(WORKER)
    if 'export const VERSION = "1.0.1";' in s and MARKER in s:
        return

    s = s.replace("Orchestrator 1.0.0", "Orchestrator 1.0.1", 1)
    s = replace_once(s, 'export const VERSION = "1.0.0";', 'export const VERSION = "1.0.1";', "VERSION")

    s = replace_once(
        s,
        "  fastProbeEndMinutes: 300,\n  fastProbeIntervalSeconds: 90,\n  finalDebounceSeconds: 90,\n  mainCooldownMinutes: 8,",
        "  fastProbeEndMinutes: 300,\n  fastProbeIntervalSeconds: 90,\n  finalRecoveryEndMinutes: 1440,\n  finalRecoveryIntervalMinutes: 15,\n  finalDebounceSeconds: 90,\n  finalRetryMinutes: 15,\n  mainCooldownMinutes: 8,",
        "DEFAULTS FINAL",
    )
    s = replace_once(
        s,
        '    fastProbeIntervalSeconds: n(env, "FAST_PROBE_INTERVAL_SECONDS", DEFAULTS.fastProbeIntervalSeconds),\n    finalDebounceSeconds: n(env, "FINAL_DEBOUNCE_SECONDS", DEFAULTS.finalDebounceSeconds),\n    mainCooldownMinutes: n(env, "MAIN_COOLDOWN_MINUTES", DEFAULTS.mainCooldownMinutes),',
        '    fastProbeIntervalSeconds: n(env, "FAST_PROBE_INTERVAL_SECONDS", DEFAULTS.fastProbeIntervalSeconds),\n    finalRecoveryEndMinutes: n(env, "FINAL_RECOVERY_END_MINUTES", DEFAULTS.finalRecoveryEndMinutes),\n    finalRecoveryIntervalMinutes: n(env, "FINAL_RECOVERY_INTERVAL_MINUTES", DEFAULTS.finalRecoveryIntervalMinutes),\n    finalDebounceSeconds: n(env, "FINAL_DEBOUNCE_SECONDS", DEFAULTS.finalDebounceSeconds),\n    finalRetryMinutes: n(env, "FINAL_RETRY_MINUTES", DEFAULTS.finalRetryMinutes),\n    mainCooldownMinutes: n(env, "MAIN_COOLDOWN_MINUTES", DEFAULTS.mainCooldownMinutes),',
        "runtimeConfig FINAL",
    )

    block = '''export function relevantFinalProbeGames(snapshot, nowMs, cfg = DEFAULTS) {
  const results = resultIdSet(snapshot);
  return (snapshot?.games || []).filter((g) => {
    if (g.concluded || g.tba || !Number.isFinite(g.kickoffMs) || results.has(g.id)) return false;
    const elapsedMin = (nowMs - g.kickoffMs) / 60_000;
    return elapsedMin >= cfg.fastProbeStartMinutes && elapsedMin <= cfg.finalRecoveryEndMinutes;
  });
}

export function finalProbeIntervalMs(games, nowMs, cfg = DEFAULTS) {
  const xs = Array.isArray(games) ? games : [];
  const normalWindow = xs.some((g) => {
    if (!Number.isFinite(g?.kickoffMs)) return false;
    const elapsedMin = (nowMs - g.kickoffMs) / 60_000;
    return elapsedMin <= cfg.fastProbeEndMinutes;
  });
  return normalWindow
    ? cfg.fastProbeIntervalSeconds * 1000
    : cfg.finalRecoveryIntervalMinutes * 60_000;
}

export function collectRepositoryFinals(snapshot, pendingFinals, nowMs) {
  const results = resultIdSet(snapshot);
  const next = { ...(pendingFinals || {}) };
  for (const id of Object.keys(next)) {
    if (results.has(id)) delete next[id];
  }
  for (const game of snapshot?.games || []) {
    if (!game?.id || !game.concluded || results.has(game.id) || next[game.id]) continue;
    next[game.id] = iso(nowMs);
  }
  return next;
}
'''
    s = replace_regex_once(
        s,
        r'export function relevantFinalProbeGames\(snapshot, nowMs, cfg = DEFAULTS\) \{.*?\n\}\s*(?=export function collectNewFinals\()',
        block.rstrip()+"\n",
        "relevant/recovery functions",
        flags=re.S,
    )

    probe = '''export async function probeEspn(games, nowMs = Date.now()) {
  const days = [...new Set(games.map((g) => dateKeyBrt(g.kickoffMs)))];
  const wanted = new Set(games.map((g) => g.id));
  const states = {};
  const errors = [];
  await Promise.all(days.map(async (day) => {
    // FINAL_CONVERGENCE_1_0_1: sinal de FINAL sempre foge de cache intermediário.
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?dates=${day}&limit=100&_=${Math.trunc(nowMs)}`;
    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: {
          "user-agent": "Brasileirao-Almoco-Orchestrator/1.0.1",
          "accept": "application/json",
          "cache-control": "no-cache",
          "pragma": "no-cache",
        },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      for (const event of data.events || []) {
        const id = String(event?.id || "");
        if (!wanted.has(id)) continue;
        const type = event?.status?.type || {};
        let state = String(type.state || "").toLowerCase();
        if (type.completed === true) state = "post";
        states[id] = { state: ["pre", "in", "post"].includes(state) ? state : "" };
      }
    } catch (error) {
      errors.push(`ESPN ${day}: ${error?.message || error}`);
    }
  }));
  return { states, errors };
}
'''
    s = replace_regex_once(
        s,
        r'async function probeEspn\(games\) \{.*?\n\}\s*(?=async function listRuns\()',
        probe.rstrip()+"\n",
        "probeEspn no-cache",
        flags=re.S,
    )
    s = s.replace('"user-agent": "Brasileirao-Almoco-Orchestrator/1.0",', '"user-agent": "Brasileirao-Almoco-Orchestrator/1.0.1",')

    fast = '''    // FAST PATH: apenas detectar FINAL. Não há AO VIVO, gols, placar ou eventos no escopo.
    // FINAL já conhecido no calendário mas ainda ausente em resultados também entra
    // na fila de convergência, sem depender de uma nova resposta da ESPN.
    state.pendingFinals = collectRepositoryFinals(state.snapshot, state.pendingFinals, nowMs);

    // Janela normal: +88..+300 min. Recovery: até +24h, a cada 15 min.
    const probeGames = relevantFinalProbeGames(state.snapshot, nowMs, cfg);
    state.relevantSportsGames = probeGames.length;
    const lastFast = parseDate(state.lastFastProbeAt);
    const probeIntervalMs = finalProbeIntervalMs(probeGames, nowMs, cfg);
    if (probeGames.length && (!Number.isFinite(lastFast) || nowMs - lastFast >= probeIntervalMs)) {
      const cacheAge = ageHours(state.snapshot?.fetchedAtMs, nowMs);
      if (cacheAge <= cfg.staleCacheMaxHoursForFinal) {
        const probed = await probeEspn(probeGames, nowMs);
        state.lastFastProbeAt = iso(nowMs);
        if (probed.errors.length) state.errors.push(...probed.errors);
        state.pendingFinals = collectNewFinals(state.snapshot, probed.states, state.pendingFinals, nowMs);
      } else {
        state.errors.push(`cache do repositório velho demais para FINAL (${cacheAge.toFixed(1)}h)`);
      }
    }
'''
    s = replace_regex_once(
        s,
        r'    // FAST PATH: apenas detectar FINAL\. Não há AO VIVO, gols, placar ou eventos no escopo\.\n.*?\n    let selected = chooseFinalCandidate',
        fast.rstrip()+"\n    let selected = chooseFinalCandidate",
        "FAST PATH",
        flags=re.S,
    )

    cooldown = '''    const isFinalConvergence = selected.action === ACTIONS.MAIN && Array.isArray(selected.eventIds) && selected.eventIds.length > 0;
    const lastMain = isFinalConvergence ? lastActionMs(state, ACTIONS.MAIN) : null;
    const finalCooldownOk = !isFinalConvergence || !Number.isFinite(lastMain) || nowMs - lastMain >= cfg.finalRetryMinutes * 60_000;
    if (!finalCooldownOk || (!isFinalConvergence && !isCooldownElapsed(state, selected.action, nowMs, cfg))) {
      state.result = "none";
      state.resultReason = isFinalConvergence
        ? `FINAL ainda não convergiu; retry liberado após ${cfg.finalRetryMinutes} min`
        : `cooldown ativo para ${selected.action}`;
      await this.writeState(state);
      return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
    }'''
    s = replace_regex_once(
        s,
        r'    if \(!isCooldownElapsed\(state, selected\.action, nowMs, cfg\)\) \{.*?\n    \}',
        cooldown,
        "cooldown FINAL",
        flags=re.S,
    )

    s = replace_regex_once(
        s,
        r'\n      if \(selected\.action === ACTIONS\.MAIN && Array\.isArray\(selected\.eventIds\)\) \{\n        for \(const id of selected\.eventIds\) delete state\.pendingFinals\[id\];\n      \}',
        '\n      // 1.0.1: dispatch não significa publicação. pendingFinals permanece até\n      // resultados.json realmente conter o event_id; então a revalidação o remove.',
        "não apagar pendingFinals no dispatch",
        flags=re.S,
    )
    write(WORKER, s)


def patch_index() -> None:
    s = read(INDEX)
    if 'const ESPN_LIVE_DISABLED = true;' not in s:
        s = replace_regex_once(
            s,
            r'// AO VIVO — ESPN \(bra\.1\), direto do navegador, a cada 30 segundos\.\n// Mesma técnica do módulo da Copa \(aovivo\.js\): a API da ESPN aceita CORS,\n// então o placar em tempo real NÃO depende do GitHub Actions\.\n// Fora da janela de jogo o motor dorme \(zero requisições\)\.',
            '// AO VIVO do Brasileirão foi DESCONTINUADO neste site.\n// Compatibilidade legada permanece abaixo, mas nenhum polling ESPN é armado.\n// Resultados refletem exclusivamente resultados.json consolidado.',
            "comentário AO VIVO",
        )
        s = replace_once(
            s,
            "const ESPN_SCOREBOARD_BR = 'https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard';",
            "const ESPN_LIVE_DISABLED = true;\nconst ESPN_SCOREBOARD_BR = 'https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard';",
            "flag AO VIVO disabled",
        )
        s = replace_once(
            s,
            'async function espnLiveTick() {\n  _espnTimer = null;',
            'async function espnLiveTick() {\n  _espnTimer = null;\n  if (ESPN_LIVE_DISABLED) return;',
            "espnLiveTick no-op",
        )
        s = replace_once(
            s,
            'function espnLiveArmar() {\n  if (_espnTimer) return;',
            'function espnLiveArmar() {\n  if (ESPN_LIVE_DISABLED) return;\n  if (_espnTimer) return;',
            "espnLiveArmar no-op",
        )

    replacement = '''function resultadosComFinaisRecentesESPN(listaBase) {
  // Assinatura mantida por compatibilidade. Resultado provisório de AO VIVO
  // foi removido: a página usa somente o snapshot consolidado.
  const lista = Array.isArray(listaBase) ? listaBase.slice() : [];
  return lista.sort((a,b) => String(b.data_iso || '').localeCompare(String(a.data_iso || '')));
}'''
    s = replace_regex_once(
        s,
        r'function resultadosComFinaisRecentesESPN\(listaBase\) \{.*?\n\}',
        replacement,
        "resultados sem FINAL provisório",
        flags=re.S,
    )
    s = re.sub(
        r'<span class="resultado-data">\$\{dataFmt\}\$\{r\._provisorioESPN \? \' · <strong style="color:var\(--accent\)">ESPN · resultado recém-finalizado</strong>\' : \'\'\}</span>',
        '<span class="resultado-data">${dataFmt}</span>',
        s,
        count=1,
    )
    if "ESPN · resultado recém-finalizado" in s:
        raise SystemExit("ERRO: rótulo provisório ainda existe em index.html")
    write(INDEX, s)


def patch_package_wrangler() -> None:
    data = json.loads(read(PACKAGE))
    data["version"] = "1.0.1"
    write(PACKAGE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    w = read(WRANGLER)
    if 'FINAL_RECOVERY_END_MINUTES = "1440"' not in w:
        w = replace_once(
            w,
            'FAST_PROBE_INTERVAL_SECONDS = "90"\nFINAL_DEBOUNCE_SECONDS = "90"\nMAIN_COOLDOWN_MINUTES = "8"',
            'FAST_PROBE_INTERVAL_SECONDS = "90"\nFINAL_RECOVERY_END_MINUTES = "1440"\nFINAL_RECOVERY_INTERVAL_MINUTES = "15"\nFINAL_DEBOUNCE_SECONDS = "90"\nFINAL_RETRY_MINUTES = "15"\nMAIN_COOLDOWN_MINUTES = "8"',
            "wrangler FINAL vars",
        )
    write(WRANGLER, w)



def patch_tests() -> None:
    s = read(TESTS)
    if 'probe ESPN de FINAL força no-cache em todas as camadas' in s:
        return

    s = replace_once(s, 'import assert from "node:assert/strict";', 'import assert from "node:assert/strict";\nimport { readFileSync } from "node:fs";\nimport { fileURLToPath } from "node:url";\nimport { dirname, resolve } from "node:path";', "test imports fs")
    s = replace_once(s, '  collectNewFinals,\n  computeNextSlowAt,', '  collectNewFinals,\n  collectRepositoryFinals,\n  computeNextSlowAt,\n  finalProbeIntervalMs,', "test imports final funcs")
    s = replace_once(s, '  parseDate,\n  relevantFinalProbeGames,', '  parseDate,\n  probeEspn,\n  relevantFinalProbeGames,', "test import probe")

    anchor = '''test("fast path começa apenas perto do horário provável de FINAL", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T16:00";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.deepEqual(relevantFinalProbeGames(snap, NOW, DEFAULTS).map((g) => g.id), ["g1"]);
});'''
    extra = '''

test("recovery path mantém jogo elegível até 24h após kickoff", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T10:00";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.deepEqual(relevantFinalProbeGames(snap, NOW, DEFAULTS).map((g) => g.id), ["g1"]);
  const muitoAntigo = parseDate("2026-09-04T11:00:01-03:00");
  assert.equal(relevantFinalProbeGames(snap, muitoAntigo, DEFAULTS).length, 0);
});

test("recovery path reduz polling ESPN para 15 minutos depois de +300 min", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T15:30";
  let snap = buildRepositorySnapshot(f, NOW);
  assert.equal(finalProbeIntervalMs(relevantFinalProbeGames(snap, NOW, DEFAULTS), NOW, DEFAULTS), 90_000);
  f.calendar.jogos[0].data_iso = "2026-09-03T10:00";
  snap = buildRepositorySnapshot(f, NOW);
  assert.equal(finalProbeIntervalMs(relevantFinalProbeGames(snap, NOW, DEFAULTS), NOW, DEFAULTS), 15 * 60_000);
});

test("FINAL consolidado no calendário mas ausente em resultados vira pendência", () => {
  const f = baseFiles();
  f.calendar.jogos[0].estado = "post";
  f.calendar.jogos[0].concluido = true;
  const snap = buildRepositorySnapshot(f, NOW);
  assert.ok(collectRepositoryFinals(snap, {}, NOW).g1);
});

test("probe ESPN de FINAL força no-cache em todas as camadas", async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (input, init = {}) => {
    seen.push({ url: String(input), init });
    return new Response(JSON.stringify({ events: [{ id: "g1", status: { type: { state: "post", completed: true } } }] }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const out = await probeEspn([{ id: "g1", kickoffMs: parseDate("2026-09-03T16:00") }], NOW);
    assert.equal(out.states.g1.state, "post");
    assert.match(seen[0].url, /&_=[0-9]+$/);
    assert.equal(seen[0].init.cache, "no-store");
    assert.equal(seen[0].init.headers["cache-control"], "no-cache");
    assert.equal(seen[0].init.cf.cacheTtl, 0);
    assert.equal(seen[0].init.cf.cacheEverything, false);
  } finally { globalThis.fetch = originalFetch; }
});'''
    s = replace_once(s, anchor, anchor + extra, "novos testes recovery/no-cache")

    anchor2 = '''test("ações automáticas possíveis são somente as cinco aprovadas", () => {
  assert.deepEqual(Object.values(ACTIONS).sort(), [
    "apurar_apostas",
    "atualizar_brasileirao",
    "atualizar_brasileirao_forcar_af",
    "none",
    "sincronizar_blocos_apostas",
    "transmissoes_tv",
  ].sort());
});'''
    extra2 = '''

test("browser não arma polling AO VIVO nem injeta resultado provisório", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const html = readFileSync(resolve(here, "../../../index.html"), "utf8");
  assert.match(html, /const ESPN_LIVE_DISABLED = true;/);
  assert.match(html, /function espnLiveArmar\\(\\) \\{\\s*if \\(ESPN_LIVE_DISABLED\\) return;/);
  assert.doesNotMatch(html, /ESPN · resultado recém-finalizado/);
  const fn = html.match(/function resultadosComFinaisRecentesESPN\\(listaBase\\) \\{[\\s\\S]*?\\n\\}/)?.[0] || "";
  assert.doesNotMatch(fn, /state\\.espnLive/);
});'''
    s = replace_once(s, anchor2, anchor2 + extra2, "teste browser sem live")

    needle = '''    assert.equal(dispatches.length, 1);
    assert.match(dispatches[0].url, /atualizar-brasileirao\\.yml\\/dispatches$/);
    assert.deepEqual(dispatches[0].body, { ref: "main", inputs: {} });'''
    repl = needle + '''
    const persisted = storageMap.get("state");
    assert.ok(persisted.pendingFinals.g1); // dispatch != publicação'''
    s = replace_once(s, needle, repl, "teste pending persiste")
    write(TESTS, s)


def patch_readme() -> None:
    if not README.exists():
        return
    s = read(README)
    s = s.replace("1.0.0", "1.0.1")
    if "Convergência de FINAL — 1.0.1" not in s:
        s += '''

## Convergência de FINAL — 1.0.1

- ESPN FINAL: anti-cache em query, headers e `cf.cacheTtl=0`.
- Recovery path até +24h; após +300 min, polling a cada 15 min.
- `pendingFinals` só é resolvido quando `resultados.json` contém o `event_id`.
- Sem convergência, novo dispatch é permitido após 15 min, respeitando writer gate.
- AO VIVO do navegador desativado; Resultados usa somente o snapshot consolidado.
'''
    write(README, s)


def validate() -> None:
    s = read(WORKER)
    for needle in [
        'export const VERSION = "1.0.1";',
        MARKER,
        'finalRecoveryEndMinutes: 1440',
        'finalRetryMinutes: 15',
        'cf: { cacheTtl: 0, cacheEverything: false }',
        'state.pendingFinals = collectRepositoryFinals',
        'dispatch não significa publicação',
    ]:
        if needle not in s:
            raise SystemExit(f"ERRO: validação Worker: ausente {needle}")
    h = read(INDEX)
    assert 'const ESPN_LIVE_DISABLED = true;' in h
    assert 'ESPN · resultado recém-finalizado' not in h
    fn = h.split('function resultadosComFinaisRecentesESPN(listaBase) {', 1)[1].split('\n}', 1)[0]
    assert 'state.espnLive' not in fn
    w = read(WRANGLER)
    assert 'FINAL_RECOVERY_END_MINUTES = "1440"' in w
    assert 'FINAL_RETRY_MINUTES = "15"' in w
    print("Validação estrutural do HOTFIX 1.0.1: OK")


def main() -> None:
    patch_worker()
    patch_index()
    patch_package_wrangler()
    patch_tests()
    patch_readme()
    validate()
    print("HOTFIX Orchestrator BR Almoço 1.0.1 aplicado com sucesso.")

if __name__ == "__main__":
    main()

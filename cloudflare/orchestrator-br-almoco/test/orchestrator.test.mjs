import test from "node:test";
import assert from "node:assert/strict";
import {
  ACTIONS,
  BrAlmocoOrchestratorStateV1,
  DEFAULTS,
  WRITER_WORKFLOW_NAMES,
  WORKFLOW_BY_ACTION,
  buildRepositorySnapshot,
  chooseSlowCandidate,
  chooseFinalCandidate,
  collectNewFinals,
  computeNextSlowAt,
  dateKeyBrt,
  findActiveWriter,
  normalizeMode,
  parseDate,
  relevantFinalProbeGames,
} from "../src/index.js";

const NOW = parseDate("2026-09-03T17:30:00-03:00");

function baseFiles() {
  return {
    calendar: {
      gerado_em: "2026-09-03T17:00:00-03:00",
      jogos: [
        { event_id: "g1", rodada: 26, mandante: "A", visitante: "B", data_iso: "2026-09-05T16:00", estado: "pre", concluido: false, adiado: false, data_definir: false },
        { event_id: "g2", rodada: 26, mandante: "C", visitante: "D", data_iso: "2026-09-06T16:00", estado: "pre", concluido: false, adiado: false, data_definir: false },
      ],
    },
    results: { atualizado_em: "2026-09-03T17:00:00-03:00", resultados: [{ event_id: "r20", rodada: 20 }] },
    apuracao: { schema_version: 4, rodadas: [{ rodada: 20, jogos_apurados: 1 }] },
    ranking: { schema_version: 4 },
    apostasConfig: { rodadaInicialApostas: 20 },
    afAudit: { status: "ok", integridade: { partidas_2026_concluidas: 1 } },
    afBolao: { status: "ok" },
    tv: { atualizado_em: "2026-09-03T17:00:00-03:00", jogos: { g1: { canais: ["Premiere"] }, g2: { canais: ["Globo"] } } },
    tvAudit: { atualizado_em: "2026-09-03T17:00:00-03:00" },
    blocksAudit: { status: "ok", gerado_em: "2026-09-03T17:00:00-03:00", proximo_evento_em: "2026-09-04T21:00:00-03:00", criticos: [], avisos: [] },
    generalAudit: { status: "ok", gerado_em: "2026-09-03T17:00:00-03:00", criticos: [] },
  };
}

function state() { return { lastDispatchAt: {} }; }

test("datas locais do repositório são interpretadas como BRT", () => {
  assert.equal(new Date(parseDate("2026-09-05T16:00")).toISOString(), "2026-09-05T19:00:00.000Z");
});

test("dateKeyBrt mantém o dia esportivo de Brasília", () => {
  assert.equal(dateKeyBrt(parseDate("2026-09-05T23:30:00-03:00")), "20260905");
});

test("modo desconhecido sempre cai em shadow", () => {
  assert.equal(normalizeMode("ACTIVE"), "active");
  assert.equal(normalizeMode("qualquer"), "shadow");
});

test("snapshot íntegro reconhece cobertura completa de TV", () => {
  const snap = buildRepositorySnapshot(baseFiles(), NOW);
  assert.equal(snap.tv.games35d, 2);
  assert.equal(snap.tv.covered35d, 2);
  assert.equal(snap.tv.missing14d, 0);
  assert.equal(snap.tv.critical72h, 0);
});

test("cobertura completa não dispara TV só porque virou outro dia", () => {
  const snap = buildRepositorySnapshot(baseFiles(), NOW);
  assert.equal(chooseSlowCandidate(snap, state(), NOW, DEFAULTS), null);
});

test("TV crítica dispara somente se a última busca já respeitou backoff", () => {
  const f = baseFiles();
  f.tv.atualizado_em = "2026-09-03T12:00:00-03:00";
  f.tv.jogos.g1.canais = [];
  const snap = buildRepositorySnapshot(f, NOW);
  const dec = chooseSlowCandidate(snap, state(), NOW, DEFAULTS);
  assert.equal(dec.action, ACTIONS.TV);
  assert.match(dec.reason, /72h/);
});

test("fronteira de bloco tem precedência no slow path", () => {
  const f = baseFiles();
  f.blocksAudit.proximo_evento_em = "2026-09-03T17:33:00-03:00";
  const snap = buildRepositorySnapshot(f, NOW);
  const dec = chooseSlowCandidate(snap, state(), NOW, DEFAULTS);
  assert.equal(dec.action, ACTIONS.BLOCKS);
});

test("auditoria crítica de blocos dispara imediatamente", () => {
  const f = baseFiles();
  f.blocksAudit.status = "critical";
  f.blocksAudit.criticos = ["x"];
  const snap = buildRepositorySnapshot(f, NOW);
  assert.equal(chooseSlowCandidate(snap, state(), NOW, DEFAULTS).action, ACTIONS.BLOCKS);
});

test("apuração só dispara quando realmente diverge dos resultados", () => {
  const f = baseFiles();
  f.apuracao.rodadas[0].jogos_apurados = 0;
  const snap = buildRepositorySnapshot(f, NOW);
  const dec = chooseSlowCandidate(snap, state(), NOW, DEFAULTS);
  assert.equal(dec.action, ACTIONS.APURAR);
  assert.match(dec.reason, /R20/);
});

test("AF só dispara quando reconhece menos resultados", () => {
  const f = baseFiles();
  f.afAudit.integridade.partidas_2026_concluidas = 0;
  const snap = buildRepositorySnapshot(f, NOW);
  assert.equal(chooseSlowCandidate(snap, state(), NOW, DEFAULTS).action, ACTIONS.MAIN_AF);
});

test("manutenção usa idade real dos artefatos, não troca de data civil", () => {
  const f = baseFiles();
  f.calendar.gerado_em = "2026-09-02T16:00:00-03:00";
  f.results.atualizado_em = "2026-09-02T16:00:00-03:00";
  f.generalAudit.gerado_em = "2026-09-02T16:00:00-03:00";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.equal(chooseSlowCandidate(snap, state(), NOW, DEFAULTS).action, ACTIONS.MAIN);
});

test("jogo TBA reduz o intervalo de reconciliação estrutural", () => {
  const f = baseFiles();
  f.calendar.jogos.push({ event_id: "late", rodada: 21, mandante: "E", visitante: "F", data_iso: null, estado: "pre", concluido: false, adiado: true, data_definir: true });
  f.calendar.gerado_em = "2026-09-03T04:00:00-03:00";
  f.results.atualizado_em = "2026-09-03T04:00:00-03:00";
  f.generalAudit.gerado_em = "2026-09-03T04:00:00-03:00";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.equal(snap.pendingCalendar, 1);
  assert.equal(chooseSlowCandidate(snap, state(), NOW, DEFAULTS).action, ACTIONS.MAIN);
});

test("jogo recente não é tratado como AO VIVO pelo orquestrador", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T16:30";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.equal(relevantFinalProbeGames(snap, NOW, DEFAULTS).length, 0);
});

test("fast path começa apenas perto do horário provável de FINAL", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T16:00";
  const snap = buildRepositorySnapshot(f, NOW);
  assert.deepEqual(relevantFinalProbeGames(snap, NOW, DEFAULTS).map((g) => g.id), ["g1"]);
});

test("FINAL ESPN entra em debounce e não vira pipeline por gol", () => {
  const f = baseFiles();
  f.calendar.jogos[0].data_iso = "2026-09-03T16:00";
  const snap = buildRepositorySnapshot(f, NOW);
  const pending = collectNewFinals(snap, { g1: { state: "post" } }, {}, NOW);
  assert.ok(pending.g1);
  assert.equal(chooseFinalCandidate(snap, pending, NOW + 30_000, DEFAULTS), null);
  assert.equal(chooseFinalCandidate(snap, pending, NOW + 100_000, DEFAULTS).action, ACTIONS.MAIN);
});

test("FINAL já presente em resultados é deduplicado na memória", () => {
  const f = baseFiles();
  f.results.resultados.push({ event_id: "g1", rodada: 26 });
  f.apuracao.rodadas.push({ rodada: 26, jogos_apurados: 1 });
  f.afAudit.integridade.partidas_2026_concluidas = 2;
  const snap = buildRepositorySnapshot(f, NOW);
  const pending = collectNewFinals(snap, { g1: { state: "post" } }, { g1: "2026-09-03T20:00:00Z" }, NOW);
  assert.equal(pending.g1, undefined);
});

test("writer ativo bloqueável é reconhecido", () => {
  assert.ok(findActiveWriter([{ name: "Atualizar Brasileirao (ESPN)", status: "in_progress" }]));
  assert.equal(findActiveWriter([{ name: "Deploy site", status: "in_progress" }]), null);
});

test("matriz de ações não possui ação de AO VIVO nem módulos descontinuados", () => {
  const actions = Object.values(ACTIONS).join(" ").toLowerCase();
  for (const forbidden of ["aovivo", "ao_vivo", "publico", "melhores", "elenco", "fair"]) {
    assert.equal(actions.includes(forbidden), false);
  }
  // O nome histórico do workflow de TV contém “ao vivo”, mas o novo motor
  // só consegue despachá-lo pela ação transmissoes_tv, cujo input é modo=tv.
  assert.ok(WRITER_WORKFLOW_NAMES.has("Buscar transmissões ao vivo do Brasileirão"));
  assert.deepEqual(WORKFLOW_BY_ACTION[ACTIONS.TV].inputs, { modo: "tv" });
  assert.equal(Object.values(WORKFLOW_BY_ACTION).some((spec) => spec.inputs?.modo === "aovivo"), false);
});

test("próximo slow check é antecipado pela fronteira de bloco", () => {
  const f = baseFiles();
  f.blocksAudit.proximo_evento_em = "2026-09-03T17:40:00-03:00";
  const snap = buildRepositorySnapshot(f, NOW);
  const next = computeNextSlowAt(snap, NOW, DEFAULTS);
  assert.equal(new Date(next).toISOString(), new Date(parseDate("2026-09-03T17:35:00-03:00")).toISOString());
});

test("ações automáticas possíveis são somente as cinco aprovadas", () => {
  assert.deepEqual(Object.values(ACTIONS).sort(), [
    "apurar_apostas",
    "atualizar_brasileirao",
    "atualizar_brasileirao_forcar_af",
    "none",
    "sincronizar_blocos_apostas",
    "transmissoes_tv",
  ].sort());
});


test("integração: ACTIVE agrupa FINAL e despacha somente Atualizar Brasileirão", async () => {
  const files = baseFiles();
  files.calendar.jogos[0].data_iso = "2026-09-03T16:00";
  files.calendar.gerado_em = "2026-09-03T17:35:00-03:00";
  files.results.atualizado_em = "2026-09-03T17:35:00-03:00";
  files.generalAudit.gerado_em = "2026-09-03T17:35:00-03:00";
  files.blocksAudit.gerado_em = "2026-09-03T17:35:00-03:00";
  files.tv.atualizado_em = "2026-09-03T17:35:00-03:00";

  const repoFiles = {
    "dados-br/calendario-completo.json": files.calendar,
    "resultados.json": files.results,
    "dados-br/apuracao.json": files.apuracao,
    "dados-br/ranking-apostas.json": files.ranking,
    "dados-br/apostas-config.json": files.apostasConfig,
    "dados-br/auditoria-probabilidades.json": files.afAudit,
    "dados-br/probabilidades-bolao.json": files.afBolao,
    "dados-br/transmissoes-tv.json": files.tv,
    "dados-br/auditoria-transmissoes-tv.json": files.tvAudit,
    "dados-br/auditoria-blocos-apostas.json": files.blocksAudit,
    "dados-br/auditoria-geral.json": files.generalAudit,
  };

  const storageMap = new Map();
  const ctx = {
    storage: {
      async get(key) { return storageMap.get(key); },
      async put(key, value) { storageMap.set(key, structuredClone(value)); },
    },
  };
  const env = {
    ORCHESTRATOR_MODE: "active",
    GITHUB_REPOSITORY: "LAERCIOREHEM/BRASILEIRAO2026ALMOCO",
    GITHUB_BRANCH: "main",
    GITHUB_TOKEN: "token-exclusivo-teste",
  };

  const dispatches = [];
  const originalFetch = globalThis.fetch;
  const originalNow = Date.now;
  let clock = parseDate("2026-09-03T17:40:00-03:00");
  Date.now = () => clock;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url);
    if (url.hostname === "api.github.com" && url.pathname.includes("/contents/")) {
      const path = decodeURIComponent(url.pathname.split("/contents/")[1]);
      const payload = repoFiles[path];
      assert.ok(payload, `arquivo mock ausente: ${path}`);
      const content = Buffer.from(JSON.stringify(payload), "utf8").toString("base64");
      return new Response(JSON.stringify({ type: "file", content }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.hostname === "site.api.espn.com") {
      return new Response(JSON.stringify({ events: [{ id: "g1", status: { type: { state: "post", completed: true } } }] }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.hostname === "api.github.com" && url.pathname.endsWith("/actions/runs")) {
      return new Response(JSON.stringify({ workflow_runs: [] }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.hostname === "api.github.com" && url.pathname.includes("/actions/workflows/") && url.pathname.endsWith("/dispatches")) {
      dispatches.push({ url: url.pathname, body: JSON.parse(init.body) });
      return new Response(null, { status: 204 });
    }
    throw new Error(`fetch mock não previsto: ${url}`);
  };

  try {
    const durable = new BrAlmocoOrchestratorStateV1(ctx, env);
    const first = await durable.tick();
    const firstBody = await first.json();
    assert.equal(firstBody.action, ACTIONS.NONE); // debounce ainda não venceu
    assert.equal(dispatches.length, 0);

    clock += 100_000;
    const second = await durable.tick();
    const secondBody = await second.json();
    assert.equal(secondBody.action, ACTIONS.MAIN);
    assert.equal(secondBody.result, "dispatched");
    assert.equal(dispatches.length, 1);
    assert.match(dispatches[0].url, /atualizar-brasileirao\.yml\/dispatches$/);
    assert.deepEqual(dispatches[0].body, { ref: "main", inputs: {} });
  } finally {
    globalThis.fetch = originalFetch;
    Date.now = originalNow;
  }
});

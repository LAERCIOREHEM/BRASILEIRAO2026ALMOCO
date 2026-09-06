/*
 * Brasileirão 2026 Almoço — Orchestrator 1.1.0
 *
 * Escopo deliberadamente EXCLUÍDO:
 * - AO VIVO / placar em browser
 * - públicos
 * - melhores momentos
 * - elencos
 * - fair play
 *
 * O Worker é um cérebro determinístico. Ele não escreve no repositório.
 * Só dispara workflows existentes quando o estado objetivo exige trabalho.
 */

export const VERSION = "1.1.1";
export const ENGINE = "br-almoco-cloudflare-orchestrator";
export const TIMEZONE = "America/Sao_Paulo";

export const ACTIONS = Object.freeze({
  NONE: "none",
  FAST: "atualizar_nucleo_brasileirao",
  MAIN: "atualizar_brasileirao",
  MAIN_AF: "atualizar_brasileirao_forcar_af",
  APURAR: "apurar_apostas",
  BLOCKS: "sincronizar_blocos_apostas",
  TV: "transmissoes_tv",
});

export const WORKFLOW_BY_ACTION = Object.freeze({
  [ACTIONS.FAST]: { file: "atualizar-nucleo-brasileirao.yml", inputs: {} },
  [ACTIONS.MAIN]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "true", forcar_af: "false" } },
  [ACTIONS.MAIN_AF]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "true", forcar_af: "true" } },
  [ACTIONS.APURAR]: { file: "apurar-brasileirao.yml", inputs: {} },
  [ACTIONS.BLOCKS]: { file: "sincronizar-blocos-apostas.yml", inputs: {} },
  [ACTIONS.TV]: { file: "buscar-transmissoes-aovivo-brasileirao.yml", inputs: { modo: "tv" } },
});

export const WORKFLOW_NAME_BY_ACTION = Object.freeze({
  [ACTIONS.FAST]: "Atualizar núcleo rápido do Brasileirão",
  [ACTIONS.MAIN]: "Atualizar Brasileirao (ESPN)",
  [ACTIONS.MAIN_AF]: "Atualizar Brasileirao (ESPN)",
  [ACTIONS.APURAR]: "Apurar Apostas Brasileirão",
  [ACTIONS.BLOCKS]: "Sincronizar blocos de apostas",
  [ACTIONS.TV]: "Buscar transmissões ao vivo do Brasileirão",
});

// ÚNICOS workflows considerados escritores pelo novo orquestrador.
// AO VIVO, públicos, melhores momentos, elencos e fair play não aparecem aqui.
export const WRITER_WORKFLOW_NAMES = new Set([
  "Atualizar núcleo rápido do Brasileirão",
  "Atualizar Brasileirao (ESPN)",
  "Apurar Apostas Brasileirão",
  "Auditar modelos AF-Previsão",
  "Buscar transmissões ao vivo do Brasileirão",
  "Sincronizar blocos de apostas",
]);

const REPO_FILES = Object.freeze({
  calendar: "dados-br/calendario-completo.json",
  results: "resultados.json",
  apuracao: "dados-br/apuracao.json",
  ranking: "dados-br/ranking-apostas.json",
  apostasConfig: "dados-br/apostas-config.json",
  afAudit: "dados-br/auditoria-probabilidades.json",
  afBolao: "dados-br/probabilidades-bolao.json",
  tv: "dados-br/transmissoes-tv.json",
  tvAudit: "dados-br/auditoria-transmissoes-tv.json",
  blocksAudit: "dados-br/auditoria-blocos-apostas.json",
  generalAudit: "dados-br/auditoria-geral.json",
});

export const DEFAULTS = Object.freeze({
  slowIntervalMinutes: 30,
  slowRetryErrorMinutes: 5,
  fastProbeStartMinutes: 88,
  fastProbeEndMinutes: 300,
  fastProbeIntervalSeconds: 60,
  finalRecoveryEndMinutes: 720,
  finalRecoveryIntervalMinutes: 5,
  finalDebounceSeconds: 45,
  finalRetryMinutes: 5,
  fastCooldownMinutes: 3,
  mainCooldownMinutes: 8,
  apuracaoCooldownMinutes: 10,
  blocksCooldownMinutes: 10,
  afCooldownMinutes: 20,
  tvCriticalRetryHours: 3,
  tv14dRetryHours: 24,
  tv35dRetryHours: 48,
  tvFullCoverageRecheckHours: 72,
  maintenanceMaxHours: 24,
  maintenancePendingCalendarHours: 12,
  maintenanceNearGameHours: 12,
  maintenanceNearGameWindowHours: 36,
  maintenanceVeryNearHours: 6,
  maintenanceVeryNearWindowHours: 8,
  staleCacheMaxHoursForFinal: 6,
  blockBoundaryBeforeMinutes: 5,
  blockBoundaryAfterMinutes: 20,
  blockSafetyNearDays: 7,
  blockSafetyNearHours: 72,
  blockSafetyFarHours: 168,
  blockPastDueRetryHours: 1,
  blocksFailureBackoffHours: 6,
  duplicateRunGuardMinutes: 15,
  githubRunsLimit: 50,
  recentDecisionsLimit: 20,
});

function n(env, key, fallback) {
  const value = Number(env?.[key]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

export function runtimeConfig(env = {}) {
  return {
    slowIntervalMinutes: n(env, "SLOW_INTERVAL_MINUTES", DEFAULTS.slowIntervalMinutes),
    slowRetryErrorMinutes: n(env, "SLOW_RETRY_ERROR_MINUTES", DEFAULTS.slowRetryErrorMinutes),
    fastProbeStartMinutes: n(env, "FAST_PROBE_START_MINUTES", DEFAULTS.fastProbeStartMinutes),
    fastProbeEndMinutes: n(env, "FAST_PROBE_END_MINUTES", DEFAULTS.fastProbeEndMinutes),
    fastProbeIntervalSeconds: n(env, "FAST_PROBE_INTERVAL_SECONDS", DEFAULTS.fastProbeIntervalSeconds),
    finalRecoveryEndMinutes: n(env, "FINAL_RECOVERY_END_MINUTES", DEFAULTS.finalRecoveryEndMinutes),
    finalRecoveryIntervalMinutes: n(env, "FINAL_RECOVERY_INTERVAL_MINUTES", DEFAULTS.finalRecoveryIntervalMinutes),
    finalDebounceSeconds: n(env, "FINAL_DEBOUNCE_SECONDS", DEFAULTS.finalDebounceSeconds),
    finalRetryMinutes: n(env, "FINAL_RETRY_MINUTES", DEFAULTS.finalRetryMinutes),
    fastCooldownMinutes: n(env, "FAST_COOLDOWN_MINUTES", DEFAULTS.fastCooldownMinutes),
    mainCooldownMinutes: n(env, "MAIN_COOLDOWN_MINUTES", DEFAULTS.mainCooldownMinutes),
    apuracaoCooldownMinutes: n(env, "APURACAO_COOLDOWN_MINUTES", DEFAULTS.apuracaoCooldownMinutes),
    blocksCooldownMinutes: n(env, "BLOCKS_COOLDOWN_MINUTES", DEFAULTS.blocksCooldownMinutes),
    afCooldownMinutes: n(env, "AF_COOLDOWN_MINUTES", DEFAULTS.afCooldownMinutes),
    tvCriticalRetryHours: n(env, "TV_CRITICAL_RETRY_HOURS", DEFAULTS.tvCriticalRetryHours),
    tv14dRetryHours: n(env, "TV_14D_RETRY_HOURS", DEFAULTS.tv14dRetryHours),
    tv35dRetryHours: n(env, "TV_35D_RETRY_HOURS", DEFAULTS.tv35dRetryHours),
    tvFullCoverageRecheckHours: n(env, "TV_FULL_COVERAGE_RECHECK_HOURS", DEFAULTS.tvFullCoverageRecheckHours),
    maintenanceMaxHours: n(env, "MAINTENANCE_MAX_HOURS", DEFAULTS.maintenanceMaxHours),
    maintenancePendingCalendarHours: n(env, "MAINTENANCE_PENDING_CALENDAR_HOURS", DEFAULTS.maintenancePendingCalendarHours),
    maintenanceNearGameHours: n(env, "MAINTENANCE_NEAR_GAME_HOURS", DEFAULTS.maintenanceNearGameHours),
    maintenanceNearGameWindowHours: n(env, "MAINTENANCE_NEAR_GAME_WINDOW_HOURS", DEFAULTS.maintenanceNearGameWindowHours),
    maintenanceVeryNearHours: n(env, "MAINTENANCE_VERY_NEAR_HOURS", DEFAULTS.maintenanceVeryNearHours),
    maintenanceVeryNearWindowHours: n(env, "MAINTENANCE_VERY_NEAR_WINDOW_HOURS", DEFAULTS.maintenanceVeryNearWindowHours),
    staleCacheMaxHoursForFinal: n(env, "STALE_CACHE_MAX_HOURS_FOR_FINAL", DEFAULTS.staleCacheMaxHoursForFinal),
    blockBoundaryBeforeMinutes: n(env, "BLOCK_BOUNDARY_BEFORE_MINUTES", DEFAULTS.blockBoundaryBeforeMinutes),
    blockBoundaryAfterMinutes: n(env, "BLOCK_BOUNDARY_AFTER_MINUTES", DEFAULTS.blockBoundaryAfterMinutes),
    blockSafetyNearDays: n(env, "BLOCK_SAFETY_NEAR_DAYS", DEFAULTS.blockSafetyNearDays),
    blockSafetyNearHours: n(env, "BLOCK_SAFETY_NEAR_HOURS", DEFAULTS.blockSafetyNearHours),
    blockSafetyFarHours: n(env, "BLOCK_SAFETY_FAR_HOURS", DEFAULTS.blockSafetyFarHours),
    blockPastDueRetryHours: n(env, "BLOCK_PAST_DUE_RETRY_HOURS", DEFAULTS.blockPastDueRetryHours),
    blocksFailureBackoffHours: n(env, "BLOCKS_FAILURE_BACKOFF_HOURS", DEFAULTS.blocksFailureBackoffHours),
    duplicateRunGuardMinutes: n(env, "DUPLICATE_RUN_GUARD_MINUTES", DEFAULTS.duplicateRunGuardMinutes),
    githubRunsLimit: n(env, "GITHUB_RUNS_LIMIT", DEFAULTS.githubRunsLimit),
    recentDecisionsLimit: n(env, "RECENT_DECISIONS_LIMIT", DEFAULTS.recentDecisionsLimit),
  };
}

export function normalizeMode(value) {
  return String(value || "shadow").toLowerCase() === "active" ? "active" : "shadow";
}

export function parseDate(value) {
  if (!value) return null;
  const text = String(value).trim();
  if (!text) return null;
  let normalized = text;
  // JSONs do Brasileirão usam data local sem offset; Brasília em 2026 = UTC-3.
  if (!/[zZ]$|[+-]\d\d:\d\d$/.test(normalized)) {
    normalized = normalized.length === 16 ? `${normalized}:00-03:00` : `${normalized}-03:00`;
  }
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
}

export function iso(ms) {
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null;
}

export function ageHours(timestampMs, nowMs) {
  if (!Number.isFinite(timestampMs)) return Number.POSITIVE_INFINITY;
  return Math.max(0, nowMs - timestampMs) / 3_600_000;
}

export function dateKeyBrt(ms) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(ms));
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${map.year}${map.month}${map.day}`;
}

function uniqueStrings(values) {
  return [...new Set((values || []).map((v) => String(v || "").trim()).filter(Boolean))];
}

function safeInt(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function maxFinite(values) {
  const xs = values.filter(Number.isFinite);
  return xs.length ? Math.max(...xs) : null;
}

function minFinite(values) {
  const xs = values.filter(Number.isFinite);
  return xs.length ? Math.min(...xs) : null;
}

function formatGame(game) {
  return `${game.home || "?"} x ${game.away || "?"}`;
}

function resultIdSet(snapshot) {
  return new Set(snapshot?.resultIds || []);
}

export function buildRepositorySnapshot(files, nowMs) {
  const calendar = files.calendar || {};
  const results = files.results || {};
  const apuracao = files.apuracao || {};
  const ranking = files.ranking || {};
  const apostasConfig = files.apostasConfig || {};
  const afAudit = files.afAudit || {};
  const afBolao = files.afBolao || {};
  const tv = files.tv || {};
  const tvAudit = files.tvAudit || {};
  const blocksAudit = files.blocksAudit || {};
  const generalAudit = files.generalAudit || {};

  const games = [];
  for (const row of calendar.jogos || []) {
    if (!row || typeof row !== "object") continue;
    const id = String(row.event_id || "").trim();
    const kickoffMs = parseDate(row.data_iso);
    if (!id) continue;
    games.push({
      id,
      kickoffMs,
      round: safeInt(row.rodada),
      home: String(row.mandante || "").trim(),
      away: String(row.visitante || "").trim(),
      concluded: row.concluido === true || String(row.estado || "").toLowerCase() === "post",
      postponed: row.adiado === true,
      tba: row.data_definir === true || !Number.isFinite(kickoffMs),
    });
  }
  games.sort((a, b) => (a.kickoffMs ?? Number.MAX_SAFE_INTEGER) - (b.kickoffMs ?? Number.MAX_SAFE_INTEGER));

  const resultRows = Array.isArray(results.resultados) ? results.resultados : [];
  const resultIds = uniqueStrings(resultRows.map((r) => r?.event_id || r?.id));
  const initialRound = safeInt(apostasConfig.rodadaInicialApostas, 20);

  const finalByRound = new Map();
  for (const row of resultRows) {
    const round = safeInt(row?.rodada);
    if (round >= initialRound) finalByRound.set(round, (finalByRound.get(round) || 0) + 1);
  }
  const apByRound = new Map();
  for (const row of apuracao.rodadas || []) {
    const round = safeInt(row?.rodada);
    if (round >= initialRound) apByRound.set(round, safeInt(row?.jogos_apurados));
  }
  const apuracaoDivergences = [];
  const apuracaoSchemasOk = apuracao.schema_version === 4 && ranking.schema_version === 4;
  if (!apuracaoSchemasOk) {
    apuracaoDivergences.push("artefato de apuração/ranking ausente ou schema != 4");
  } else {
    for (const [round, expected] of [...finalByRound.entries()].sort((a, b) => a[0] - b[0])) {
      const actual = apByRound.get(round) || 0;
      if (actual !== expected) apuracaoDivergences.push(`R${round}: apurados=${actual}, resultados=${expected}`);
    }
  }

  const afCount = safeInt(afAudit?.integridade?.partidas_2026_concluidas, -1);
  const afOk = afAudit.status === "ok" && afBolao.status === "ok" && afCount === resultRows.length;

  const future = games.filter((g) => !g.concluded && Number.isFinite(g.kickoffMs) && g.kickoffMs >= nowMs);
  const nextGame = future[0] || null;
  const pendingCalendar = games.filter((g) => !g.concluded && (g.tba || g.postponed)).length;

  const tvMap = tv.jogos && typeof tv.jogos === "object" ? tv.jogos : {};
  const horizon35 = nowMs + 35 * 86_400_000;
  const horizon14 = nowMs + 14 * 86_400_000;
  const horizon72 = nowMs + 72 * 3_600_000;
  const future35 = future.filter((g) => g.kickoffMs <= horizon35);
  const tvMissing35 = [];
  const tvMissing14 = [];
  const tvCritical72 = [];
  for (const g of future35) {
    const channels = tvMap?.[g.id]?.canais;
    const covered = Array.isArray(channels) && channels.some((c) => String(c || "").trim());
    if (covered) continue;
    tvMissing35.push(g.id);
    if (g.kickoffMs <= horizon14) tvMissing14.push(g.id);
    if (g.kickoffMs <= horizon72) tvCritical72.push(g.id);
  }

  const coreTimes = [
    parseDate(calendar.gerado_em),
    parseDate(results.atualizado_em),
    parseDate(generalAudit.gerado_em || generalAudit.atualizado_em),
  ];
  const oldestCoreAgeHours = Math.max(...coreTimes.map((t) => ageHours(t, nowMs)));

  return {
    fetchedAt: iso(nowMs),
    fetchedAtMs: nowMs,
    games,
    resultIds,
    resultCount: resultRows.length,
    nextGameAt: iso(nextGame?.kickoffMs),
    nextGameAtMs: nextGame?.kickoffMs ?? null,
    nextGameLabel: nextGame ? formatGame(nextGame) : "",
    pendingCalendar,
    core: {
      calendarAt: calendar.gerado_em || null,
      resultsAt: results.atualizado_em || null,
      generalAuditAt: generalAudit.gerado_em || generalAudit.atualizado_em || null,
      oldestAgeHours: oldestCoreAgeHours,
      generalStatus: String(generalAudit.status || "unknown"),
      generalCriticals: Array.isArray(generalAudit.criticos) ? generalAudit.criticos.length : 0,
    },
    blocks: {
      status: String(blocksAudit.status || "missing"),
      generatedAt: blocksAudit.gerado_em || null,
      generatedAtMs: parseDate(blocksAudit.gerado_em),
      nextEventAt: blocksAudit.proximo_evento_em || null,
      nextEventAtMs: parseDate(blocksAudit.proximo_evento_em),
      criticals: Array.isArray(blocksAudit.criticos) ? blocksAudit.criticos.length : 0,
      warnings: Array.isArray(blocksAudit.avisos) ? blocksAudit.avisos.length : 0,
    },
    apuracao: {
      ok: apuracaoDivergences.length === 0,
      divergences: apuracaoDivergences,
    },
    af: {
      ok: afOk,
      results: resultRows.length,
      recognized: afCount,
      statusAudit: String(afAudit.status || "missing"),
      statusBolao: String(afBolao.status || "missing"),
    },
    tv: {
      updatedAt: tv.atualizado_em || tvAudit.atualizado_em || null,
      updatedAtMs: parseDate(tv.atualizado_em || tvAudit.atualizado_em),
      games35d: future35.length,
      covered35d: future35.length - tvMissing35.length,
      missing35d: tvMissing35.length,
      missing14d: tvMissing14.length,
      critical72h: tvCritical72.length,
      missingIds35d: tvMissing35,
    },
  };
}

function cooldownMs(action, cfg) {
  if (action === ACTIONS.FAST) return cfg.fastCooldownMinutes * 60_000;
  if (action === ACTIONS.MAIN) return cfg.mainCooldownMinutes * 60_000;
  if (action === ACTIONS.MAIN_AF) return cfg.afCooldownMinutes * 60_000;
  if (action === ACTIONS.APURAR) return cfg.apuracaoCooldownMinutes * 60_000;
  if (action === ACTIONS.BLOCKS) return cfg.blocksCooldownMinutes * 60_000;
  return 0;
}

function lastActionMs(state, action) {
  // FAST/MAIN/MAIN_AF compartilham família apenas para observar a última escrita
  // esportiva. O FINAL usa retry próprio e pode convergir rapidamente.
  if (action === ACTIONS.FAST || action === ACTIONS.MAIN || action === ACTIONS.MAIN_AF) {
    return maxFinite([
      parseDate(state?.lastDispatchAt?.[ACTIONS.FAST]),
      parseDate(state?.lastDispatchAt?.[ACTIONS.MAIN]),
      parseDate(state?.lastDispatchAt?.[ACTIONS.MAIN_AF]),
    ]);
  }
  return parseDate(state?.lastDispatchAt?.[action]);
}

export function isCooldownElapsed(state, action, nowMs, cfg) {
  const last = lastActionMs(state, action);
  const wait = cooldownMs(action, cfg);
  return !Number.isFinite(last) || nowMs - last >= wait;
}

function candidate(action, reason, details = {}) {
  return { action, reason, ...details };
}

export function chooseSlowCandidate(snapshot, state, nowMs, cfg = DEFAULTS) {
  if (!snapshot) return null;

  // 1) Fronteira de bloco é um evento temporal exato e tem precedência no slow path.
  const blockEvent = snapshot.blocks?.nextEventAtMs;
  if (snapshot.blocks?.status === "critical" || (snapshot.blocks?.criticals || 0) > 0) {
    if (isCooldownElapsed(state, ACTIONS.BLOCKS, nowMs, cfg)) {
      return candidate(ACTIONS.BLOCKS, "Auditoria dos blocos está crítica; sincronizar janelas antes de aceitar nova operação de apostas.");
    }
  }
  if (Number.isFinite(blockEvent)) {
    const deltaMin = (blockEvent - nowMs) / 60_000;
    if (deltaMin <= cfg.blockBoundaryBeforeMinutes && deltaMin >= -cfg.blockBoundaryAfterMinutes) {
      if (isCooldownElapsed(state, ACTIONS.BLOCKS, nowMs, cfg)) {
        return candidate(ACTIONS.BLOCKS, `Fronteira automática de bloco chegou (${deltaMin.toFixed(0)} min); sincronizar abertura/fechamento e e-mail aplicável.`, { checkpoint: snapshot.blocks.nextEventAt });
      }
    }
  }

  // 2) Recuperações leves só quando artefatos realmente divergem.
  if (!snapshot.apuracao?.ok && isCooldownElapsed(state, ACTIONS.APURAR, nowMs, cfg)) {
    return candidate(ACTIONS.APURAR, `Apuração está atrás dos resultados: ${(snapshot.apuracao.divergences || []).slice(0, 4).join("; ")}`);
  }
  if (!snapshot.af?.ok && isCooldownElapsed(state, ACTIONS.MAIN_AF, nowMs, cfg)) {
    return candidate(ACTIONS.MAIN_AF, `AF-Previsão está defasado: resultados=${snapshot.af.results}, AF reconhece=${snapshot.af.recognized}.`);
  }

  // 3) Atualização principal por estado real dos artefatos, nunca apenas porque virou o dia.
  const coreAge = Number(snapshot.core?.oldestAgeHours);
  const nextGameMs = snapshot.nextGameAtMs;
  const untilGameHours = Number.isFinite(nextGameMs) ? (nextGameMs - nowMs) / 3_600_000 : Number.POSITIVE_INFINITY;
  let maintenanceLimit = cfg.maintenanceMaxHours;
  let maintenanceReason = `Snapshot principal envelheceu (${coreAge.toFixed(1)}h > ${maintenanceLimit}h).`;

  if ((snapshot.pendingCalendar || 0) > 0) {
    maintenanceLimit = Math.min(maintenanceLimit, cfg.maintenancePendingCalendarHours);
    maintenanceReason = `Há ${snapshot.pendingCalendar} jogo(s) adiado(s)/TBA pendente(s); reconciliar ESPN/CBF após ${maintenanceLimit}h sem atualização.`;
  }
  if (untilGameHours >= 0 && untilGameHours <= cfg.maintenanceNearGameWindowHours) {
    maintenanceLimit = Math.min(maintenanceLimit, cfg.maintenanceNearGameHours);
    maintenanceReason = `Próximo jogo em ${untilGameHours.toFixed(1)}h e snapshot principal tem ${coreAge.toFixed(1)}h; reconciliar calendário/resultados.`;
  }
  if (untilGameHours >= 0 && untilGameHours <= cfg.maintenanceVeryNearWindowHours) {
    maintenanceLimit = Math.min(maintenanceLimit, cfg.maintenanceVeryNearHours);
    maintenanceReason = `Próximo jogo está muito próximo (${untilGameHours.toFixed(1)}h) e o snapshot tem ${coreAge.toFixed(1)}h.`;
  }
  if ((snapshot.core?.generalCriticals || 0) > 0 || snapshot.core?.generalStatus === "critical") {
    maintenanceLimit = 0;
    maintenanceReason = "Auditoria geral detectou inconsistência crítica; regenerar snapshot principal.";
  }
  if (coreAge > maintenanceLimit && isCooldownElapsed(state, ACTIONS.MAIN, nowMs, cfg)) {
    return candidate(ACTIONS.MAIN, maintenanceReason);
  }

  // 4) TV orientada por cobertura, não por cron diário.
  const lastTvMs = maxFinite([
    parseDate(state?.lastDispatchAt?.[ACTIONS.TV]),
    snapshot.tv?.updatedAtMs,
  ]);
  const sinceTvHours = ageHours(lastTvMs, nowMs);
  if ((snapshot.tv?.critical72h || 0) > 0 && sinceTvHours >= cfg.tvCriticalRetryHours) {
    return candidate(ACTIONS.TV, `${snapshot.tv.critical72h} jogo(s) nas próximas 72h continuam sem transmissão; nova busca elegível após ${cfg.tvCriticalRetryHours}h.`, { mode: "tv" });
  }
  if ((snapshot.tv?.missing14d || 0) > 0 && sinceTvHours >= cfg.tv14dRetryHours) {
    return candidate(ACTIONS.TV, `${snapshot.tv.missing14d} jogo(s) nos próximos 14 dias sem grade; nova busca após ${cfg.tv14dRetryHours}h.`, { mode: "tv" });
  }
  if ((snapshot.tv?.missing35d || 0) > 0 && sinceTvHours >= cfg.tv35dRetryHours) {
    return candidate(ACTIONS.TV, `${snapshot.tv.missing35d} jogo(s) na janela de 35 dias sem grade; nova busca após ${cfg.tv35dRetryHours}h.`, { mode: "tv" });
  }

  // 5) Auditoria de bloco não roda de 6 em 6 horas. Só existe safety net contextual.
  const blockGenerated = snapshot.blocks?.generatedAtMs;
  const blockAge = ageHours(blockGenerated, nowMs);
  if (Number.isFinite(blockEvent) && blockEvent > nowMs) {
    const days = (blockEvent - nowMs) / 86_400_000;
    const maxAge = days <= cfg.blockSafetyNearDays ? cfg.blockSafetyNearHours : cfg.blockSafetyFarHours;
    if (blockAge > maxAge && isCooldownElapsed(state, ACTIONS.BLOCKS, nowMs, cfg)) {
      return candidate(ACTIONS.BLOCKS, `Auditoria de blocos tem ${blockAge.toFixed(1)}h e o próximo evento está em ${days.toFixed(1)} dia(s); atualizar somente como safety net.`);
    }
  }
  // 1.1.1: checkpoint vencido, sozinho, NÃO dispara workflow.
  // Um checkpoint passado pode ser apenas auditoria velha. Repetir a RPC quando ela
  // está falhando cria tempestade de Actions. A recuperação ocorre por fronteira
  // futura/estado crítico e pelo circuit breaker baseado no histórico real do GitHub.

  return null;
}

export function computeNextSlowAt(snapshot, nowMs, cfg = DEFAULTS) {
  let next = nowMs + cfg.slowIntervalMinutes * 60_000;
  const event = snapshot?.blocks?.nextEventAtMs;
  if (Number.isFinite(event) && event > nowMs) {
    const before = event - cfg.blockBoundaryBeforeMinutes * 60_000;
    if (before > nowMs) next = Math.min(next, before);
    else next = Math.min(next, event);
  }
  return Math.max(nowMs + 60_000, next);
}

export function relevantFinalProbeGames(snapshot, nowMs, cfg = DEFAULTS) {
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
export function collectNewFinals(snapshot, espnStates, pendingFinals, nowMs) {
  const results = resultIdSet(snapshot);
  const next = { ...(pendingFinals || {}) };
  for (const id of Object.keys(next)) {
    if (results.has(id)) delete next[id];
  }
  for (const [id, row] of Object.entries(espnStates || {})) {
    if (results.has(id)) continue;
    if (String(row?.state || "") === "post" && !next[id]) next[id] = iso(nowMs);
  }
  return next;
}

export function chooseFinalCandidate(snapshot, pendingFinals, nowMs, cfg = DEFAULTS) {
  const ready = [];
  const byId = new Map((snapshot?.games || []).map((g) => [g.id, g]));
  for (const [id, firstSeen] of Object.entries(pendingFinals || {})) {
    const seenMs = parseDate(firstSeen);
    if (!Number.isFinite(seenMs)) continue;
    if (nowMs - seenMs < cfg.finalDebounceSeconds * 1000) continue;
    ready.push(byId.get(id) || { id, home: "?", away: "?" });
  }
  if (!ready.length) return null;
  const labels = ready.slice(0, 6).map(formatGame).join(", ");
  return candidate(ACTIONS.FAST, `ESPN marcou FINAL ainda não incorporado: ${labels}.`, { eventIds: ready.map((g) => g.id) });
}

function defaultState() {
  return {
    schemaVersion: 1,
    engine: ENGINE,
    version: VERSION,
    lastTickAt: null,
    lastSlowAt: null,
    nextSlowAt: null,
    lastFastProbeAt: null,
    lastDispatchAt: {},
    snapshot: null,
    pendingFinals: {},
    candidate: null,
    result: "none",
    resultReason: "ainda não executado",
    errors: [],
    recentDecisions: [],
  };
}

function trimRecent(items, limit) {
  return (items || []).slice(-Math.max(5, limit));
}

function recordDecision(state, nowMs, entry, cfg) {
  state.recentDecisions = trimRecent([...(state.recentDecisions || []), { at: iso(nowMs), ...entry }], cfg.recentDecisionsLimit);
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function githubHeaders(env) {
  const token = String(env.GITHUB_TOKEN || "").trim();
  return {
    "accept": "application/vnd.github+json",
    "authorization": `Bearer ${token}`,
    "x-github-api-version": "2026-03-10",
    "user-agent": "Brasileirao-Almoco-Orchestrator/1.1.1",
  };
}

function repoBase(env) {
  const repo = String(env.GITHUB_REPOSITORY || "LAERCIOREHEM/BRASILEIRAO2026ALMOCO").trim();
  if (!/^[^/]+\/[^/]+$/.test(repo)) throw new Error(`GITHUB_REPOSITORY inválido: ${repo}`);
  return `https://api.github.com/repos/${repo}`;
}

function decodeBase64Utf8(value) {
  const cleaned = String(value || "").replace(/\s+/g, "");
  const binary = atob(cleaned);
  const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

async function githubJson(env, url, options = {}) {
  if (!String(env.GITHUB_TOKEN || "").trim()) throw new Error("GITHUB_TOKEN exclusivo do BR Almoço não configurado no Worker");
  const response = await fetch(url, {
    ...options,
    headers: { ...githubHeaders(env), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const body = (await response.text()).slice(0, 500);
    throw new Error(`GitHub HTTP ${response.status}: ${body}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function readRepoJson(env, path) {
  const branch = encodeURIComponent(String(env.GITHUB_BRANCH || "main"));
  const safePath = path.split("/").map(encodeURIComponent).join("/");
  const payload = await githubJson(env, `${repoBase(env)}/contents/${safePath}?ref=${branch}`);
  if (!payload || payload.type !== "file" || !payload.content) throw new Error(`Conteúdo GitHub inválido para ${path}`);
  try {
    return JSON.parse(decodeBase64Utf8(payload.content));
  } catch (error) {
    throw new Error(`${path}: JSON inválido: ${error?.message || error}`);
  }
}

async function loadRepositoryFiles(env) {
  const entries = Object.entries(REPO_FILES);
  const results = await Promise.allSettled(entries.map(async ([key, path]) => [key, await readRepoJson(env, path)]));
  const files = {};
  const errors = [];
  results.forEach((result, index) => {
    const [key, path] = entries[index];
    if (result.status === "fulfilled") files[result.value[0]] = result.value[1];
    else errors.push(`${path}: ${result.reason?.message || result.reason}`);
  });
  const critical = ["calendar", "results", "apuracao", "ranking", "apostasConfig", "afAudit", "afBolao", "tv", "blocksAudit", "generalAudit"];
  const missingCritical = critical.filter((key) => !files[key]);
  if (missingCritical.length) {
    throw new Error(`Fontes críticas indisponíveis: ${missingCritical.join(", ")} :: ${errors.join(" | ")}`);
  }
  return { files, errors };
}

export function dateKeyUtc(ms) {
  if (!Number.isFinite(ms)) return "";
  return new Date(ms).toISOString().slice(0, 10).replaceAll("-", "");
}

export function espnStateFromPayload(data) {
  const candidates = [
    data?.header?.competitions?.[0]?.status?.type,
    data?.competitions?.[0]?.status?.type,
    data?.status?.type,
  ].filter(Boolean);
  for (const type of candidates) {
    let state = String(type?.state || "").toLowerCase();
    if (type?.completed === true) state = "post";
    if (["pre", "in", "post"].includes(state)) return state;
  }
  return "";
}

function espnNoCacheOptions() {
  return {
    cache: "no-store",
    headers: {
      "user-agent": "Brasileirao-Almoco-Orchestrator/1.1.1",
      "accept": "application/json",
      "cache-control": "no-cache",
      "pragma": "no-cache",
    },
    cf: { cacheTtl: 0, cacheEverything: false },
  };
}

export async function probeEspn(games, nowMs = Date.now()) {
  const wantedGames = (games || []).filter((g) => g?.id);
  const wanted = new Set(wantedGames.map((g) => String(g.id)));
  const states = {};
  const errors = [];
  const diagnostics = [];

  // Fonte primária: summary por event_id. Não depende de qual dia a ESPN
  // indexou um jogo que cruza meia-noite UTC/BRT.
  await Promise.all(wantedGames.map(async (game) => {
    const id = String(game.id);
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary?event=${encodeURIComponent(id)}&_=${Math.trunc(nowMs)}`;
    try {
      const response = await fetch(url, espnNoCacheOptions());
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const state = espnStateFromPayload(data);
      if (state) states[id] = { state, source: "summary" };
    } catch (error) {
      diagnostics.push(`ESPN summary ${id}: ${error?.message || error}`);
    }
  }));

  // Fallback: scoreboard em AMBAS as partições possíveis (dia BRT e dia UTC).
  // Serve para indisponibilidade pontual do summary, não como fonte primária.
  const unresolved = wantedGames.filter((g) => !states[String(g.id)]?.state);
  const days = [...new Set(unresolved.flatMap((g) => [dateKeyBrt(g.kickoffMs), dateKeyUtc(g.kickoffMs)]).filter(Boolean))];
  if (days.length) {
    await Promise.all(days.map(async (day) => {
      const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?dates=${day}&limit=100&_=${Math.trunc(nowMs)}`;
      try {
        const response = await fetch(url, espnNoCacheOptions());
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        for (const event of data.events || []) {
          const id = String(event?.id || "");
          if (!wanted.has(id) || states[id]?.state) continue;
          const type = event?.status?.type || {};
          let state = String(type.state || "").toLowerCase();
          if (type.completed === true) state = "post";
          if (["pre", "in", "post"].includes(state)) states[id] = { state, source: `scoreboard:${day}` };
        }
      } catch (error) {
        diagnostics.push(`ESPN scoreboard ${day}: ${error?.message || error}`);
      }
    }));
  }
  // Falhas de uma fonte que foram resolvidas pelo fallback não degradam o Worker.
  const stillUnresolved = wantedGames.filter((g) => !states[String(g.id)]?.state);
  if (stillUnresolved.length && diagnostics.length) {
    errors.push(`ESPN sem estado para ${stillUnresolved.map((g) => g.id).join(", ")}: ${diagnostics.join(" | ")}`);
  }
  return { states, errors };
}
async function listRuns(env, limit) {
  const branch = encodeURIComponent(String(env.GITHUB_BRANCH || "main"));
  const perPage = Math.max(10, Math.min(100, Math.trunc(limit || 50)));
  const payload = await githubJson(env, `${repoBase(env)}/actions/runs?branch=${branch}&per_page=${perPage}`);
  return Array.isArray(payload?.workflow_runs) ? payload.workflow_runs : [];
}

export function findActiveWriter(runs) {
  return (runs || []).find((run) => WRITER_WORKFLOW_NAMES.has(String(run?.name || "")) && ["queued", "in_progress", "waiting", "pending", "requested"].includes(String(run?.status || ""))) || null;
}

export function recentActionRunGuard(runs, action, nowMs, cfg = DEFAULTS) {
  const workflowName = WORKFLOW_NAME_BY_ACTION[action];
  if (!workflowName) return null;
  const matches = (runs || [])
    .filter((run) => String(run?.name || "") === workflowName)
    .map((run) => ({ ...run, _ms: parseDate(run?.created_at || run?.run_started_at || run?.updated_at) }))
    .filter((run) => Number.isFinite(run._ms))
    .sort((a, b) => b._ms - a._ms);
  const latest = matches[0];
  if (!latest) return null;
  const ageMin = (nowMs - latest._ms) / 60_000;

  // Defesa externa ao Durable Object: mesmo que o estado local seja perdido,
  // o histórico do GitHub impede re-dispatch imediato da mesma ação.
  if (ageMin >= 0 && ageMin < cfg.duplicateRunGuardMinutes) {
    return {
      blocked: true,
      reason: `circuit breaker: ${workflowName} já teve run há ${ageMin.toFixed(1)} min (${latest.status || "?"}/${latest.conclusion || "?"})`,
      run: latest,
    };
  }

  // Blocos têm proteção adicional: falha de RPC não pode virar loop automático.
  if (action === ACTIONS.BLOCKS && String(latest.conclusion || "") === "failure") {
    const ageHours = ageMin / 60;
    if (ageHours >= 0 && ageHours < cfg.blocksFailureBackoffHours) {
      return {
        blocked: true,
        reason: `circuit breaker: última sincronização de blocos falhou há ${ageHours.toFixed(2)}h; nova tentativa automática bloqueada por ${cfg.blocksFailureBackoffHours}h`,
        run: latest,
      };
    }
  }
  return null;
}

async function dispatchWorkflow(env, action) {
  const spec = WORKFLOW_BY_ACTION[action];
  if (!spec) throw new Error(`Ação sem workflow: ${action}`);
  const branch = String(env.GITHUB_BRANCH || "main");
  const url = `${repoBase(env)}/actions/workflows/${encodeURIComponent(spec.file)}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: { ...githubHeaders(env), "content-type": "application/json" },
    body: JSON.stringify({ ref: branch, inputs: spec.inputs }),
  });
  if (response.status !== 204) {
    const body = (await response.text()).slice(0, 500);
    throw new Error(`workflow_dispatch ${spec.file}: HTTP ${response.status}: ${body}`);
  }
  return spec.file;
}

async function refreshResultIds(env) {
  const results = await readRepoJson(env, REPO_FILES.results);
  return new Set(uniqueStrings((results.resultados || []).map((r) => r?.event_id || r?.id)));
}

export class BrAlmocoOrchestratorStateV1 {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
  }

  async readState() {
    return (await this.ctx.storage.get("state")) || defaultState();
  }

  async writeState(state) {
    await this.ctx.storage.put("state", state);
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return this.health();
    if (url.pathname === "/status") return this.status();
    if (url.pathname === "/tick" && request.method === "POST") return this.tick();
    return jsonResponse({ ok: false, error: "not_found" }, 404);
  }

  async health() {
    const state = await this.readState();
    return jsonResponse({
      ok: true,
      service: "brasileirao-almoco-orchestrator",
      engine: ENGINE,
      version: VERSION,
      mode: normalizeMode(this.env.ORCHESTRATOR_MODE),
      cron: "* * * * *",
      workersDevOnly: true,
      siteHostingUntouched: true,
      liveIgnored: true,
      excludedDomains: ["ao_vivo", "publicos", "melhores_momentos", "elencos", "fair_play"],
      githubTokenConfigured: Boolean(String(this.env.GITHUB_TOKEN || "").trim()),
      lastTickAt: state.lastTickAt,
    });
  }

  async status() {
    const state = await this.readState();
    const snap = state.snapshot;
    return jsonResponse({
      ok: (state.errors || []).length === 0,
      engine: ENGINE,
      version: VERSION,
      mode: normalizeMode(this.env.ORCHESTRATOR_MODE),
      lastTickAt: state.lastTickAt,
      lastSlowAt: state.lastSlowAt,
      nextSlowAt: state.nextSlowAt,
      lastFastProbeAt: state.lastFastProbeAt,
      relevantSportsGames: state.relevantSportsGames || 0,
      slowEvaluated: state.slowEvaluated === true,
      candidate: state.candidate,
      result: state.result,
      resultReason: state.resultReason,
      errors: state.errors || [],
      hints: snap ? {
        nextGameAt: snap.nextGameAt,
        nextGame: snap.nextGameLabel,
        pendingCalendar: snap.pendingCalendar,
        coreOldestAgeHours: Number.isFinite(snap.core?.oldestAgeHours) ? Number(snap.core.oldestAgeHours.toFixed(2)) : null,
        blocks: {
          status: snap.blocks?.status,
          nextEventAt: snap.blocks?.nextEventAt,
          warnings: snap.blocks?.warnings,
        },
        apuracao: snap.apuracao,
        af: snap.af,
        transmissoesTv: {
          games35d: snap.tv?.games35d,
          covered35d: snap.tv?.covered35d,
          missing35d: snap.tv?.missing35d,
          missing14d: snap.tv?.missing14d,
          critical72h: snap.tv?.critical72h,
          updatedAt: snap.tv?.updatedAt,
        },
        pendingFinals: state.pendingFinals || {},
      } : null,
      recentDecisions: state.recentDecisions || [],
    });
  }

  async tick() {
    const nowMs = Date.now();
    const cfg = runtimeConfig(this.env);
    const mode = normalizeMode(this.env.ORCHESTRATOR_MODE);
    const state = await this.readState();
    state.lastTickAt = iso(nowMs);
    state.slowEvaluated = false;
    state.errors = [];
    state.candidate = null;
    state.result = "none";
    state.resultReason = "nenhuma ação útil";

    // SLOW PATH: lê o repositório só quando venceu o relógio lento.
    const nextSlowMs = parseDate(state.nextSlowAt);
    if (!state.snapshot || !Number.isFinite(nextSlowMs) || nowMs >= nextSlowMs) {
      try {
        const loaded = await loadRepositoryFiles(this.env);
        state.snapshot = buildRepositorySnapshot(loaded.files, nowMs);
        state.lastSlowAt = iso(nowMs);
        state.slowEvaluated = true;
        if (loaded.errors.length) state.errors.push(...loaded.errors);
        state.nextSlowAt = iso(computeNextSlowAt(state.snapshot, nowMs, cfg));
      } catch (error) {
        state.errors.push(error?.message || String(error));
        state.nextSlowAt = iso(nowMs + cfg.slowRetryErrorMinutes * 60_000);
        state.result = "degraded";
        state.resultReason = "slow path falhou; fail-closed, nenhum workflow foi disparado";
        recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: state.errors[0], result: "degraded" }, cfg);
        await this.writeState(state);
        return jsonResponse({ ok: false, ...state }, 200);
      }
    }

    // FAST PATH: apenas detectar FINAL. Não há AO VIVO, gols, placar ou eventos no escopo.
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
    let selected = chooseFinalCandidate(state.snapshot, state.pendingFinals, nowMs, cfg);
    const hasPendingFinalDebounce = Object.keys(state.pendingFinals || {}).length > 0;
    // 1.1.0: recovery de FINAL NÃO bloqueia mais o slow path. Só preservamos a
    // prioridade por poucos segundos enquanto um FINAL confirmado está no debounce.
    if (!selected && !hasPendingFinalDebounce) {
      selected = chooseSlowCandidate(state.snapshot, state, nowMs, cfg);
    }
    if (!selected && hasPendingFinalDebounce) {
      state.resultReason = "FINAL confirmado em debounce curto; demais rotinas voltam a ser elegíveis imediatamente depois";
    } else if (!selected && probeGames.length > 0) {
      state.resultReason = "monitorando encerramento por event_id; nenhuma outra ação útil";
    }
    state.candidate = selected;

    if (!selected) {
      await this.writeState(state);
      return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
    }

    // FINAL: revalida resultados imediatamente antes do dispatch para evitar duplicata por cache.
    if (selected.action === ACTIONS.FAST && Array.isArray(selected.eventIds) && selected.eventIds.length) {
      try {
        const freshIds = await refreshResultIds(this.env);
        const missing = selected.eventIds.filter((id) => !freshIds.has(id));
        for (const id of selected.eventIds.filter((id) => freshIds.has(id))) delete state.pendingFinals[id];
        if (!missing.length) {
          state.candidate = null;
          state.result = "none";
          state.resultReason = "FINAL já foi incorporado antes do dispatch; ação cancelada";
          recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: state.resultReason, result: "deduplicated" }, cfg);
          await this.writeState(state);
          return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
        }
        selected.eventIds = missing;
      } catch (error) {
        state.errors.push(`revalidação FINAL: ${error?.message || error}`);
        state.result = "degraded";
        state.resultReason = "não foi possível revalidar FINAL; fail-closed";
        recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: state.resultReason, result: "degraded" }, cfg);
        await this.writeState(state);
        return jsonResponse({ ok: false, action: ACTIONS.NONE, reason: state.resultReason });
      }
    }

    const isFinalConvergence = selected.action === ACTIONS.FAST && Array.isArray(selected.eventIds) && selected.eventIds.length > 0;
    const lastMain = isFinalConvergence ? parseDate(state?.lastDispatchAt?.[ACTIONS.FAST]) : null;
    const finalCooldownOk = !isFinalConvergence || !Number.isFinite(lastMain) || nowMs - lastMain >= cfg.finalRetryMinutes * 60_000;
    if (!finalCooldownOk || (!isFinalConvergence && !isCooldownElapsed(state, selected.action, nowMs, cfg))) {
      state.result = "none";
      state.resultReason = isFinalConvergence
        ? `FINAL ainda não convergiu; retry liberado após ${cfg.finalRetryMinutes} min`
        : `cooldown ativo para ${selected.action}`;
      await this.writeState(state);
      return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
    }

    if (mode === "shadow") {
      state.result = "shadow";
      state.resultReason = selected.reason;
      recordDecision(state, nowMs, { action: selected.action, reason: selected.reason, result: "shadow", checkpoint: selected.checkpoint || null }, cfg);
      await this.writeState(state);
      return jsonResponse({ ok: true, action: selected.action, result: "shadow", reason: selected.reason });
    }

    // ACTIVE: só agora consulta Actions, evitando GitHub API a cada minuto.
    try {
      const runs = await listRuns(this.env, cfg.githubRunsLimit);
      const writer = findActiveWriter(runs);
      if (writer) {
        state.result = "none";
        state.resultReason = `writer já ativo: ${writer.name} (${writer.status})`;
        recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: state.resultReason, result: "writer_busy" }, cfg);
        await this.writeState(state);
        return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
      }

      const guard = recentActionRunGuard(runs, selected.action, nowMs, cfg);
      if (guard?.blocked) {
        state.result = "none";
        state.resultReason = guard.reason;
        recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: guard.reason, result: "circuit_breaker" }, cfg);
        // Não martela o GitHub a cada minuto quando a condição de origem persiste.
        state.nextSlowAt = iso(nowMs + Math.max(5, cfg.slowIntervalMinutes) * 60_000);
        await this.writeState(state);
        return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
      }

      const workflow = await dispatchWorkflow(this.env, selected.action);
      state.lastDispatchAt = { ...(state.lastDispatchAt || {}), [selected.action]: iso(nowMs) };
      state.result = "dispatched";
      state.resultReason = selected.reason;
      recordDecision(state, nowMs, { action: selected.action, reason: selected.reason, result: "dispatched", workflow, checkpoint: selected.checkpoint || null }, cfg);

      // 1.1.0: dispatch não significa publicação. pendingFinals permanece até
      // resultados.json realmente conter o event_id; então a revalidação o remove.
      // Após qualquer writer, refresca o repositório cedo para observar o novo estado.
      state.nextSlowAt = iso(nowMs + 2 * 60_000);
      await this.writeState(state);
      return jsonResponse({ ok: true, action: selected.action, result: "dispatched", workflow, reason: selected.reason });
    } catch (error) {
      state.errors.push(error?.message || String(error));
      state.result = "degraded";
      state.resultReason = "dispatch/preflight GitHub falhou; nenhum estado foi assumido como publicado";
      recordDecision(state, nowMs, { action: selected.action, reason: state.errors.at(-1), result: "degraded" }, cfg);
      await this.writeState(state);
      return jsonResponse({ ok: false, action: selected.action, result: "degraded", error: state.errors.at(-1) });
    }
  }
}

async function singleton(env) {
  const id = env.ORCHESTRATOR_STATE.idFromName("brasileirao-almoco-v1");
  return env.ORCHESTRATOR_STATE.get(id);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!["/health", "/status"].includes(url.pathname)) {
      return jsonResponse({ ok: false, error: "not_found", endpoints: ["/health", "/status"] }, 404);
    }
    const stub = await singleton(env);
    return stub.fetch(new Request(`https://orchestrator.internal${url.pathname}`, { method: "GET" }));
  },

  async scheduled(_event, env, ctx) {
    const stub = await singleton(env);
    ctx.waitUntil(stub.fetch(new Request("https://orchestrator.internal/tick", { method: "POST" })));
  },
};

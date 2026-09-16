/*
 * Brasileirão 2026 Almoço — Orchestrator 2.0.0 · Agenda/Event Driven
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

export const VERSION = "2.0.0";
export const ENGINE = "br-almoco-cloudflare-orchestrator";
export const TIMEZONE = "America/Sao_Paulo";

export const ACTIONS = Object.freeze({
  NONE: "none",
  FINAL: "atualizar_brasileirao_final",
  MAIN: "atualizar_brasileirao",
  MAIN_AF: "atualizar_brasileirao_forcar_af",
  APURAR: "apurar_apostas",
  BLOCKS: "sincronizar_blocos_apostas",
  TV: "transmissoes_tv",
});

export const WORKFLOW_BY_ACTION = Object.freeze({
  [ACTIONS.FINAL]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "false" } },
  [ACTIONS.MAIN]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "false" } },
  [ACTIONS.MAIN_AF]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "true" } },
  [ACTIONS.APURAR]: { file: "apurar-brasileirao.yml", inputs: {} },
  [ACTIONS.BLOCKS]: { file: "sincronizar-blocos-apostas.yml", inputs: {} },
  [ACTIONS.TV]: { file: "buscar-transmissoes-aovivo-brasileirao.yml", inputs: { modo: "tv" } },
});

export const WORKFLOW_NAME_BY_ACTION = Object.freeze({
  [ACTIONS.FINAL]: "Atualizar Brasileirao (ESPN)",
  [ACTIONS.MAIN]: "Atualizar Brasileirao (ESPN)",
  [ACTIONS.MAIN_AF]: "Atualizar Brasileirao (ESPN)",
  [ACTIONS.APURAR]: "Apurar Apostas Brasileirão",
  [ACTIONS.BLOCKS]: "Sincronizar blocos de apostas",
  [ACTIONS.TV]: "Buscar transmissões ao vivo do Brasileirão",
});

// ÚNICOS workflows considerados escritores pelo novo orquestrador.
// AO VIVO, públicos, melhores momentos, elencos e fair play não aparecem aqui.
export const WRITER_WORKFLOW_NAMES = new Set([
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
  sourceStatus: "dados-br/status-atualizacao.json",
});

export const DEFAULTS = Object.freeze({
  // O cron Cloudflare continua a cada minuto, mas o repositório/GitHub só são
  // consultados quando existe uma janela esportiva ou operacional real.
  slowIntervalMinutes: 360,
  slowRetryErrorMinutes: 15,
  sleepRepoRefreshHours: 12,
  preGameWakeHours: 6,
  preGameScoutIntervalMinutes: 30,
  nearGameWindowMinutes: 60,
  nearGameScoutIntervalMinutes: 5,
  agendaScoutFarIntervalHours: 12,
  agendaScoutHorizonDays: 14,
  agendaScoutMaxGames: 20,
  pendingCalendarScoutHours: 6,
  sourceRecoveryProbeMinutes: 60,
  sourceRecoveryNearMinutes: 5,
  scheduleChangeToleranceMinutes: 5,
  mainSignalBackoffMinutes: 360,
  criticalSignalBackoffMinutes: 360,
  fastProbeStartMinutes: 88,
  fastProbeEndMinutes: 300,
  fastProbeIntervalSeconds: 60,
  finalRecoveryEndMinutes: 720,
  finalRecoveryIntervalMinutes: 5,
  finalDebounceSeconds: 0,
  finalRetryMinutes: 3,
  finalSafetyStartMinutes: 110,
  finalSafetyRetryMinutes: 5,
  fastCooldownMinutes: 3,
  mainCooldownMinutes: 30,
  apuracaoCooldownMinutes: 10,
  blocksCooldownMinutes: 10,
  afCooldownMinutes: 20,
  afSameDivergenceBackoffMinutes: 120,
  tvCriticalRetryHours: 3,
  tv14dRetryHours: 24,
  tv35dRetryHours: 48,
  tvFullCoverageRecheckHours: 72,
  staleCacheMaxHoursForFinal: 168,
  blockBoundaryBeforeMinutes: 5,
  blockBoundaryAfterMinutes: 20,
  blockSafetyNearDays: 7,
  blockSafetyNearHours: 72,
  blockSafetyFarHours: 168,
  blockPastDueRetryHours: 1,
  blocksFailureBackoffHours: 6,
  duplicateRunGuardMinutes: 15,
  githubRunsLimit: 50,
  recentDecisionsLimit: 30,
});

function n(env, key, fallback) {
  const value = Number(env?.[key]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

export function runtimeConfig(env = {}) {
  return {
    slowIntervalMinutes: n(env, "SLOW_INTERVAL_MINUTES", DEFAULTS.slowIntervalMinutes),
    slowRetryErrorMinutes: n(env, "SLOW_RETRY_ERROR_MINUTES", DEFAULTS.slowRetryErrorMinutes),
    sleepRepoRefreshHours: n(env, "SLEEP_REPO_REFRESH_HOURS", DEFAULTS.sleepRepoRefreshHours),
    preGameWakeHours: n(env, "PRE_GAME_WAKE_HOURS", DEFAULTS.preGameWakeHours),
    preGameScoutIntervalMinutes: n(env, "PRE_GAME_SCOUT_INTERVAL_MINUTES", DEFAULTS.preGameScoutIntervalMinutes),
    nearGameWindowMinutes: n(env, "NEAR_GAME_WINDOW_MINUTES", DEFAULTS.nearGameWindowMinutes),
    nearGameScoutIntervalMinutes: n(env, "NEAR_GAME_SCOUT_INTERVAL_MINUTES", DEFAULTS.nearGameScoutIntervalMinutes),
    agendaScoutFarIntervalHours: n(env, "AGENDA_SCOUT_FAR_INTERVAL_HOURS", DEFAULTS.agendaScoutFarIntervalHours),
    agendaScoutHorizonDays: n(env, "AGENDA_SCOUT_HORIZON_DAYS", DEFAULTS.agendaScoutHorizonDays),
    agendaScoutMaxGames: n(env, "AGENDA_SCOUT_MAX_GAMES", DEFAULTS.agendaScoutMaxGames),
    pendingCalendarScoutHours: n(env, "PENDING_CALENDAR_SCOUT_HOURS", DEFAULTS.pendingCalendarScoutHours),
    sourceRecoveryProbeMinutes: n(env, "SOURCE_RECOVERY_PROBE_MINUTES", DEFAULTS.sourceRecoveryProbeMinutes),
    sourceRecoveryNearMinutes: n(env, "SOURCE_RECOVERY_NEAR_MINUTES", DEFAULTS.sourceRecoveryNearMinutes),
    scheduleChangeToleranceMinutes: n(env, "SCHEDULE_CHANGE_TOLERANCE_MINUTES", DEFAULTS.scheduleChangeToleranceMinutes),
    mainSignalBackoffMinutes: n(env, "MAIN_SIGNAL_BACKOFF_MINUTES", DEFAULTS.mainSignalBackoffMinutes),
    criticalSignalBackoffMinutes: n(env, "CRITICAL_SIGNAL_BACKOFF_MINUTES", DEFAULTS.criticalSignalBackoffMinutes),
    fastProbeStartMinutes: n(env, "FAST_PROBE_START_MINUTES", DEFAULTS.fastProbeStartMinutes),
    fastProbeEndMinutes: n(env, "FAST_PROBE_END_MINUTES", DEFAULTS.fastProbeEndMinutes),
    fastProbeIntervalSeconds: n(env, "FAST_PROBE_INTERVAL_SECONDS", DEFAULTS.fastProbeIntervalSeconds),
    finalRecoveryEndMinutes: n(env, "FINAL_RECOVERY_END_MINUTES", DEFAULTS.finalRecoveryEndMinutes),
    finalRecoveryIntervalMinutes: n(env, "FINAL_RECOVERY_INTERVAL_MINUTES", DEFAULTS.finalRecoveryIntervalMinutes),
    finalDebounceSeconds: n(env, "FINAL_DEBOUNCE_SECONDS", DEFAULTS.finalDebounceSeconds),
    finalRetryMinutes: n(env, "FINAL_RETRY_MINUTES", DEFAULTS.finalRetryMinutes),
    finalSafetyStartMinutes: n(env, "FINAL_SAFETY_START_MINUTES", DEFAULTS.finalSafetyStartMinutes),
    finalSafetyRetryMinutes: n(env, "FINAL_SAFETY_RETRY_MINUTES", DEFAULTS.finalSafetyRetryMinutes),
    fastCooldownMinutes: n(env, "FAST_COOLDOWN_MINUTES", DEFAULTS.fastCooldownMinutes),
    mainCooldownMinutes: n(env, "MAIN_COOLDOWN_MINUTES", DEFAULTS.mainCooldownMinutes),
    apuracaoCooldownMinutes: n(env, "APURACAO_COOLDOWN_MINUTES", DEFAULTS.apuracaoCooldownMinutes),
    blocksCooldownMinutes: n(env, "BLOCKS_COOLDOWN_MINUTES", DEFAULTS.blocksCooldownMinutes),
    afCooldownMinutes: n(env, "AF_COOLDOWN_MINUTES", DEFAULTS.afCooldownMinutes),
    afSameDivergenceBackoffMinutes: n(env, "AF_SAME_DIVERGENCE_BACKOFF_MINUTES", DEFAULTS.afSameDivergenceBackoffMinutes),
    tvCriticalRetryHours: n(env, "TV_CRITICAL_RETRY_HOURS", DEFAULTS.tvCriticalRetryHours),
    tv14dRetryHours: n(env, "TV_14D_RETRY_HOURS", DEFAULTS.tv14dRetryHours),
    tv35dRetryHours: n(env, "TV_35D_RETRY_HOURS", DEFAULTS.tv35dRetryHours),
    tvFullCoverageRecheckHours: n(env, "TV_FULL_COVERAGE_RECHECK_HOURS", DEFAULTS.tvFullCoverageRecheckHours),
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

function stableHash(text) {
  let hash = 0x811c9dc5;
  for (const ch of String(text || "")) {
    hash ^= ch.codePointAt(0);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function gameScheduleKey(game) {
  return [
    game?.id || "",
    Number.isFinite(game?.kickoffMs) ? iso(game.kickoffMs) : "TBA",
    game?.postponed === true ? "P" : "-",
    game?.tba === true ? "T" : "-",
    game?.concluded === true ? "F" : "-",
  ].join("|");
}

export function agendaSignature(games) {
  const rows = (games || [])
    .filter((g) => g?.id && g?.concluded !== true)
    .map(gameScheduleKey)
    .sort();
  return stableHash(rows.join("\n"));
}

function sourceIsHealthy(source) {
  if (!source) return true;
  if (source.synchronized === true) return true;
  const status = String(source.status || "").toLowerCase();
  return ["ok", "sucesso", "success", "sincronizado"].includes(status);
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
  const sourceStatus = files.sourceStatus || {};

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
  const pendingScheduleGames = games.filter((g) => {
    if (g.concluded) return false;
    if (g.tba || g.postponed) return true;
    return Number.isFinite(g.kickoffMs) && g.kickoffMs < nowMs - 30 * 60_000;
  });
  const pendingCalendar = pendingScheduleGames.length;

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
    pendingScheduleGames,
    agendaSignature: agendaSignature(games),
    source: {
      status: String(sourceStatus.status || "unknown"),
      synchronized: sourceStatus.sincronizado === true,
      healthy: sourceIsHealthy({ status: sourceStatus.status, synchronized: sourceStatus.sincronizado === true }),
      fingerprint: String(sourceStatus.fingerprint || ""),
      lastAttempt: sourceStatus.ultima_tentativa || null,
      lastAttemptMs: parseDate(sourceStatus.ultima_tentativa),
      lastSuccess: sourceStatus.ultimo_sucesso || sourceStatus.ultimo_snapshot_valido || null,
      lastSuccessMs: parseDate(sourceStatus.ultimo_sucesso || sourceStatus.ultimo_snapshot_valido),
      message: String(sourceStatus.mensagem_admin || ""),
    },
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
  if (action === ACTIONS.FINAL) return cfg.fastCooldownMinutes * 60_000;
  if (action === ACTIONS.MAIN) return cfg.mainCooldownMinutes * 60_000;
  if (action === ACTIONS.MAIN_AF) return cfg.afCooldownMinutes * 60_000;
  if (action === ACTIONS.APURAR) return cfg.apuracaoCooldownMinutes * 60_000;
  if (action === ACTIONS.BLOCKS) return cfg.blocksCooldownMinutes * 60_000;
  return 0;
}

function lastActionMs(state, action) {
  // FINAL/MAIN/MAIN_AF compartilham família apenas para observar a última escrita
  // esportiva. O FINAL usa retry próprio e pode convergir rapidamente.
  if (action === ACTIONS.FINAL || action === ACTIONS.MAIN || action === ACTIONS.MAIN_AF) {
    return maxFinite([
      parseDate(state?.lastDispatchAt?.[ACTIONS.FINAL]),
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
  if (!snapshot.af?.ok) {
    const signature = `${safeInt(snapshot.af.results)}:${safeInt(snapshot.af.recognized)}`;
    const lastAttemptMs = parseDate(state?.afLastAttempt?.at);
    const sameSignature = String(state?.afLastAttempt?.signature || "") === signature;
    const backoffMs = cfg.afSameDivergenceBackoffMinutes * 60_000;
    const sameDivergenceBackoff = sameSignature && Number.isFinite(lastAttemptMs) && nowMs - lastAttemptMs < backoffMs;
    if (!sameDivergenceBackoff && isCooldownElapsed(state, ACTIONS.MAIN_AF, nowMs, cfg)) {
      return candidate(
        ACTIONS.MAIN_AF,
        `AF-Previsão está defasado: resultados=${snapshot.af.results}, AF reconhece=${snapshot.af.recognized}.`,
        { afSignature: signature },
      );
    }
  }

  // 3) MAIN NÃO é mais disparado por idade do snapshot. O Worker 2.0 é
  // orientado por EVENTO: FINAL, mudança objetiva de agenda, recuperação da
  // fonte ou inconsistência crítica. Um snapshot velho, sozinho, nunca justifica
  // gastar um GitHub Action.
  if ((snapshot.core?.generalCriticals || 0) > 0 || snapshot.core?.generalStatus === "critical") {
    if (snapshot.source?.healthy !== false && isCooldownElapsed(state, ACTIONS.MAIN, nowMs, cfg)) {
      const signature = `critical:${snapshot.agendaSignature}:${snapshot.core?.generalCriticals || 0}:${snapshot.resultCount}`;
      return candidate(
        ACTIONS.MAIN,
        "Auditoria geral detectou inconsistência crítica com fonte disponível; regenerar snapshot principal uma vez por sinal.",
        { mainSignalSignature: signature, signalBackoffMinutes: cfg.criticalSignalBackoffMinutes },
      );
    }
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

export function orchestratorPhase(snapshot, nowMs, cfg = DEFAULTS) {
  const nextGameMs = snapshot?.nextGameAtMs;
  const deltaMin = Number.isFinite(nextGameMs) ? (nextGameMs - nowMs) / 60_000 : Number.POSITIVE_INFINITY;
  const finalGames = relevantFinalProbeGames(snapshot, nowMs, cfg);
  if (finalGames.length) return "final_watch";
  if (Number.isFinite(deltaMin) && deltaMin <= 0 && deltaMin >= -cfg.fastProbeStartMinutes) return "game_window";
  if (Number.isFinite(deltaMin) && deltaMin > 0 && deltaMin <= cfg.nearGameWindowMinutes) return "near_game";
  if (Number.isFinite(deltaMin) && deltaMin > 0 && deltaMin <= cfg.preGameWakeHours * 60) return "pre_game";
  if (snapshot?.source?.healthy === false) return "source_degraded";
  if ((snapshot?.pendingCalendar || 0) > 0) return "calendar_watch";
  return "sleep";
}

export function computeWakePlan(snapshot, nowMs, cfg = DEFAULTS) {
  const phase = orchestratorPhase(snapshot, nowMs, cfg);
  const nextGameMs = snapshot?.nextGameAtMs;
  const candidates = [];

  const add = (ms, reason) => {
    if (Number.isFinite(ms) && ms > nowMs) candidates.push({ atMs: ms, reason });
  };

  if (phase === "final_watch") {
    add(nowMs + cfg.fastProbeIntervalSeconds * 1000, "sondar FINAL");
  } else if (phase === "game_window" || phase === "near_game") {
    add(nowMs + cfg.nearGameScoutIntervalMinutes * 60_000, "janela de jogo/agenda próxima");
  } else if (phase === "pre_game") {
    add(nowMs + cfg.preGameScoutIntervalMinutes * 60_000, "pré-jogo: confirmar agenda sem GitHub Action");
  } else if (phase === "source_degraded") {
    add(nowMs + cfg.sourceRecoveryProbeMinutes * 60_000, "fonte preservada: testar recuperação de forma barata");
  } else if (phase === "calendar_watch") {
    add(nowMs + cfg.pendingCalendarScoutHours * 3_600_000, "jogos adiados/TBA: revisar agenda externamente");
  } else {
    add(nowMs + cfg.sleepRepoRefreshHours * 3_600_000, "SLEEP: revisão de segurança do estado");
  }

  if (snapshot?.source?.healthy === false) {
    const untilMin = Number.isFinite(nextGameMs) ? (nextGameMs - nowMs) / 60_000 : Number.POSITIVE_INFINITY;
    const recoveryMin = untilMin <= cfg.preGameWakeHours * 60 ? cfg.sourceRecoveryNearMinutes : cfg.sourceRecoveryProbeMinutes;
    add(nowMs + recoveryMin * 60_000, "probe barato de recuperação da fonte");
  }

  if (Number.isFinite(nextGameMs)) {
    add(nextGameMs - cfg.preGameWakeHours * 3_600_000, `acordar T-${cfg.preGameWakeHours}h para ${snapshot.nextGameLabel || "próximo jogo"}`);
    add(nextGameMs - cfg.nearGameWindowMinutes * 60_000, `entrar em janela próxima de ${snapshot.nextGameLabel || "próximo jogo"}`);
    add(nextGameMs + cfg.fastProbeStartMinutes * 60_000, `iniciar vigilância de FINAL de ${snapshot.nextGameLabel || "próximo jogo"}`);
  }

  const blockEvent = snapshot?.blocks?.nextEventAtMs;
  if (Number.isFinite(blockEvent)) {
    add(blockEvent - cfg.blockBoundaryBeforeMinutes * 60_000, "fronteira de bloco de apostas");
  }

  candidates.sort((a, b) => a.atMs - b.atMs);
  const first = candidates[0] || { atMs: nowMs + cfg.sleepRepoRefreshHours * 3_600_000, reason: "SLEEP" };
  return { phase, nextWakeAtMs: Math.max(nowMs + 60_000, first.atMs), nextWakeReason: first.reason };
}

export function computeNextSlowAt(snapshot, nowMs, cfg = DEFAULTS) {
  const phase = orchestratorPhase(snapshot, nowMs, cfg);
  let next = nowMs + cfg.sleepRepoRefreshHours * 3_600_000;
  if (phase === "final_watch") next = nowMs + cfg.finalRecoveryIntervalMinutes * 60_000;
  else if (phase === "near_game" || phase === "game_window") next = nowMs + 15 * 60_000;
  else if (phase === "pre_game") next = nowMs + cfg.preGameScoutIntervalMinutes * 60_000;
  else if (phase === "source_degraded") next = nowMs + cfg.sourceRecoveryProbeMinutes * 60_000;
  else if (phase === "calendar_watch") next = nowMs + cfg.pendingCalendarScoutHours * 3_600_000;

  const nextGameMs = snapshot?.nextGameAtMs;
  if (Number.isFinite(nextGameMs)) {
    const wakePre = nextGameMs - cfg.preGameWakeHours * 3_600_000;
    if (wakePre > nowMs) next = Math.min(next, wakePre);
    const wakeNear = nextGameMs - cfg.nearGameWindowMinutes * 60_000;
    if (wakeNear > nowMs) next = Math.min(next, wakeNear);
  }
  const blockEvent = snapshot?.blocks?.nextEventAtMs;
  if (Number.isFinite(blockEvent) && blockEvent > nowMs) {
    const before = blockEvent - cfg.blockBoundaryBeforeMinutes * 60_000;
    if (before > nowMs) next = Math.min(next, before);
    else next = Math.min(next, blockEvent);
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
  return candidate(ACTIONS.FINAL, `ESPN marcou FINAL ainda não incorporado: ${labels}.`, { eventIds: ready.map((g) => g.id) });
}

export function chooseSafetyFinalCandidate(snapshot, state, nowMs, cfg = DEFAULTS) {
  const results = resultIdSet(snapshot);
  const lastByEvent = state?.finalSafetyLastAttempt || {};
  const eligible = [];
  for (const game of snapshot?.games || []) {
    if (!game?.id || game.concluded || game.tba || !Number.isFinite(game.kickoffMs) || results.has(game.id)) continue;
    const elapsedMin = (nowMs - game.kickoffMs) / 60_000;
    if (elapsedMin < cfg.finalSafetyStartMinutes || elapsedMin > cfg.finalRecoveryEndMinutes) continue;
    const lastMs = parseDate(lastByEvent[game.id]);
    if (Number.isFinite(lastMs) && nowMs - lastMs < cfg.finalSafetyRetryMinutes * 60_000) continue;
    eligible.push(game);
  }
  if (!eligible.length) return null;
  const labels = eligible.slice(0, 6).map(formatGame).join(", ");
  return candidate(
    ACTIONS.FINAL,
    `Safety trigger: ${labels} já passou de T+${cfg.finalSafetyStartMinutes}min e ainda não consta em resultados; chamar Atualizar Brasileirão robusto mesmo sem confirmação do probe Cloudflare.`,
    { eventIds: eligible.map((g) => g.id), safetyTrigger: true },
  );
}

function defaultState() {
  return {
    schemaVersion: 2,
    engine: ENGINE,
    version: VERSION,
    lastTickAt: null,
    lastSlowAt: null,
    nextSlowAt: null,
    phase: "boot",
    nextWakeAt: null,
    nextWakeReason: "carregar estado inicial",
    lastFastProbeAt: null,
    lastFastProbeDiagnostics: null,
    fastProbeWarnings: [],
    lastAgendaScoutAt: null,
    lastAgendaScoutDiagnostics: null,
    lastDispatchAt: {},
    mainSignalLast: null,
    snapshot: null,
    pendingFinals: {},
    candidate: null,
    result: "none",
    resultReason: "ainda não executado",
    errors: [],
    recentDecisions: [],
    afLastAttempt: null,
    finalSafetyLastAttempt: {},
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
    "user-agent": "Brasileirao-Almoco-Orchestrator/2.0.0",
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
  const critical = ["calendar", "results", "apuracao", "ranking", "apostasConfig", "afAudit", "afBolao", "tv", "blocksAudit", "generalAudit", "sourceStatus"];
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

const ESPN_TIMEOUT_MS = 8000;

async function fetchWithTimeout(url, options = {}, timeoutMs = ESPN_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function espnNoCacheOptions() {
  // 1.1.6: não combinar RequestInit.cache="no-store" com cf.cacheTtl=0.
  // O runtime Cloudflare rejeita essa combinação antes da requisição.
  // A query ?orch=<minuto> já faz cache-busting e "no-store" evita cache da subrequest.
  return {
    cache: "no-store",
    headers: {
      "accept": "application/json,text/plain,*/*",
      "cache-control": "no-cache",
      "pragma": "no-cache",
      "user-agent": "Mozilla/5.0 (compatible; BrasileiroAlmoco-Orchestrator/2.0.0)",
    },
  };
}

export async function probeEspn(games, nowMs = Date.now()) {
  const wantedGames = (games || []).filter((g) => g?.id);
  const wanted = new Set(wantedGames.map((g) => String(g.id)));
  const states = {};
  const errors = [];
  const notes = [];

  // 1.1.6: SCOREBOARD é a fonte primária, espelhando o mecanismo comprovado
  // do Fórmula do Gol. Consultamos tanto o dia BRT quanto UTC para jogos noturnos.
  const days = [...new Set(wantedGames.flatMap((g) => [dateKeyBrt(g.kickoffMs), dateKeyUtc(g.kickoffMs)]).filter(Boolean))];
  const scoreboardHits = new Set();
  await Promise.all(days.map(async (day) => {
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?dates=${day}&limit=100&orch=${Math.floor(nowMs / 60_000)}`;
    try {
      const response = await fetchWithTimeout(url, espnNoCacheOptions());
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      for (const event of data?.events || []) {
        const id = String(event?.id || "");
        if (!wanted.has(id)) continue;
        scoreboardHits.add(id);
        const type = event?.status?.type || {};
        let state = String(type?.state || "").toLowerCase();
        if (type?.completed === true) state = "post";
        if (["pre", "in", "post"].includes(state)) {
          states[id] = { state, source: `scoreboard:${day}` };
        }
      }
    } catch (error) {
      notes.push(`scoreboard ${day}: ${error?.name || "Error"}: ${error?.message || error}`);
    }
  }));

  // Fallback/segunda opinião: summary individual somente para eventos que o
  // scoreboard não resolveu. Falha aqui também não impede o safety trigger temporal.
  const unresolvedAfterScoreboard = wantedGames.filter((g) => !states[String(g.id)]?.state);
  const summaryHits = new Set();
  await Promise.all(unresolvedAfterScoreboard.map(async (game) => {
    const id = String(game.id);
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary?event=${encodeURIComponent(id)}&orch=${Math.floor(nowMs / 60_000)}`;
    try {
      const response = await fetchWithTimeout(url, espnNoCacheOptions());
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const state = espnStateFromPayload(data);
      if (state) {
        states[id] = { state, source: "summary" };
        summaryHits.add(id);
      }
    } catch (error) {
      notes.push(`summary ${id}: ${error?.name || "Error"}: ${error?.message || error}`);
    }
  }));

  const unresolved = wantedGames.filter((g) => !states[String(g.id)]?.state).map((g) => String(g.id));
  if (unresolved.length) {
    errors.push(`ESPN sem estado para ${unresolved.join(", ")}${notes.length ? `: ${notes.join(" | ")}` : ""}`);
  }

  return {
    states,
    errors,
    diagnostics: {
      strategy: "scoreboard_primary_browser_ua+summary_fallback+safety_clock",
      wanted: [...wanted],
      scoreboardDays: days,
      scoreboardHits: [...scoreboardHits],
      summaryFallbackRequested: unresolvedAfterScoreboard.map((g) => String(g.id)),
      summaryHits: [...summaryHits],
      unresolved,
      notes,
    },
  };
}


export function espnKickoffFromPayload(data) {
  const comp = data?.header?.competitions?.[0] || data?.competitions?.[0] || null;
  const candidates = [comp?.date, comp?.startDate, data?.date, data?.header?.date].filter(Boolean);
  for (const value of candidates) {
    const ms = Date.parse(String(value));
    if (Number.isFinite(ms)) return ms;
  }
  return null;
}

export function agendaScoutGames(snapshot, nowMs, cfg = DEFAULTS) {
  const phase = orchestratorPhase(snapshot, nowMs, cfg);
  const all = snapshot?.games || [];
  const chosen = [];
  const seen = new Set();
  const add = (game) => {
    if (!game?.id || game.concluded || seen.has(game.id)) return;
    seen.add(game.id);
    chosen.push(game);
  };

  // Em janela esportiva, olhar somente o que pode mudar agora.
  if (["pre_game", "near_game", "game_window", "final_watch"].includes(phase)) {
    const nextMs = snapshot?.nextGameAtMs;
    for (const game of all) {
      if (!Number.isFinite(game.kickoffMs)) continue;
      if (Number.isFinite(nextMs) && Math.abs(game.kickoffMs - nextMs) <= 6 * 3_600_000) add(game);
    }
  } else {
    // Fora de jogo: auditoria barata de agenda, nunca GitHub Action por idade.
    for (const game of snapshot?.pendingScheduleGames || []) add(game);
    const horizon = nowMs + cfg.agendaScoutHorizonDays * 86_400_000;
    for (const game of all) {
      if (chosen.length >= cfg.agendaScoutMaxGames) break;
      if (!Number.isFinite(game.kickoffMs) || game.kickoffMs < nowMs || game.kickoffMs > horizon) continue;
      add(game);
    }
  }
  return chosen.slice(0, Math.max(1, cfg.agendaScoutMaxGames));
}

export function agendaScoutIntervalMs(snapshot, nowMs, cfg = DEFAULTS) {
  const phase = orchestratorPhase(snapshot, nowMs, cfg);
  const nextGameMs = snapshot?.nextGameAtMs;
  const untilMin = Number.isFinite(nextGameMs) ? (nextGameMs - nowMs) / 60_000 : Number.POSITIVE_INFINITY;
  if (snapshot?.source?.healthy === false) {
    return (untilMin <= cfg.preGameWakeHours * 60 ? cfg.sourceRecoveryNearMinutes : cfg.sourceRecoveryProbeMinutes) * 60_000;
  }
  if (phase === "near_game" || phase === "game_window" || phase === "final_watch") {
    return cfg.nearGameScoutIntervalMinutes * 60_000;
  }
  if (phase === "pre_game") return cfg.preGameScoutIntervalMinutes * 60_000;
  if (phase === "calendar_watch") return cfg.pendingCalendarScoutHours * 3_600_000;
  return cfg.agendaScoutFarIntervalHours * 3_600_000;
}

export async function probeAgenda(snapshot, nowMs = Date.now(), cfg = DEFAULTS) {
  const games = agendaScoutGames(snapshot, nowMs, cfg);
  const changes = [];
  const finals = [];
  const notes = [];
  let reachable = false;

  await Promise.all(games.map(async (game) => {
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary?event=${encodeURIComponent(game.id)}&agenda=${Math.floor(nowMs / 300_000)}`;
    try {
      const response = await fetchWithTimeout(url, espnNoCacheOptions());
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      reachable = true;
      const data = await response.json();
      const remoteState = espnStateFromPayload(data);
      const remoteKickoffMs = espnKickoffFromPayload(data);
      if (remoteState === "post" && !resultIdSet(snapshot).has(game.id)) finals.push(game.id);
      if (Number.isFinite(remoteKickoffMs)) {
        const diffMin = Number.isFinite(game.kickoffMs)
          ? Math.abs(remoteKickoffMs - game.kickoffMs) / 60_000
          : Number.POSITIVE_INFINITY;
        const remoteFuture = remoteKickoffMs > nowMs - 6 * 3_600_000;
        if (diffMin > cfg.scheduleChangeToleranceMinutes || ((game.tba || game.postponed) && remoteFuture)) {
          changes.push({
            id: game.id,
            game: formatGame(game),
            localKickoff: iso(game.kickoffMs),
            remoteKickoff: iso(remoteKickoffMs),
            diffMinutes: Number.isFinite(diffMin) ? Math.round(diffMin) : null,
            localPostponed: game.postponed === true,
            localTba: game.tba === true,
          });
        }
      }
    } catch (error) {
      notes.push(`summary ${game.id}: ${error?.name || "Error"}: ${error?.message || error}`);
    }
  }));

  // Sem jogos conhecidos para sondar, ou em fonte degradada, um scoreboard diário
  // serve apenas como teste barato de reachability. Não dispara MAIN por si só
  // quando a fonte já está saudável.
  if (!games.length || snapshot?.source?.healthy === false) {
    const day = dateKeyBrt(nowMs);
    const url = `https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?dates=${day}&limit=100&agenda=${Math.floor(nowMs / 300_000)}`;
    try {
      const response = await fetchWithTimeout(url, espnNoCacheOptions());
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      reachable = true;
      await response.json();
    } catch (error) {
      notes.push(`scoreboard ${day}: ${error?.name || "Error"}: ${error?.message || error}`);
    }
  }

  const signature = stableHash(JSON.stringify(changes.map((c) => [c.id, c.localKickoff, c.remoteKickoff]).sort()));
  return {
    reachable,
    changes,
    finals: uniqueStrings(finals),
    signature,
    diagnostics: {
      at: iso(nowMs),
      phase: orchestratorPhase(snapshot, nowMs, cfg),
      probedIds: games.map((g) => g.id),
      reachable,
      changes,
      finals: uniqueStrings(finals),
      notes,
    },
  };
}

export function mainSignalBlocked(state, selected, nowMs, cfg = DEFAULTS) {
  if (selected?.action !== ACTIONS.MAIN || !selected?.mainSignalSignature) return null;
  const last = state?.mainSignalLast;
  if (!last || String(last.signature || "") !== String(selected.mainSignalSignature)) return null;
  const atMs = parseDate(last.at);
  const backoffMin = Number(selected.signalBackoffMinutes || cfg.mainSignalBackoffMinutes);
  if (!Number.isFinite(atMs) || nowMs - atMs >= backoffMin * 60_000) return null;
  return {
    blocked: true,
    reason: `mesmo sinal MAIN já despachado há ${((nowMs - atMs) / 60_000).toFixed(1)} min; backoff=${backoffMin}min`,
  };
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
  // FINAL é exceção deliberada: se o run terminou verde mas a ESPN não
  // convergiu, a recuperação não pode ficar presa no guard genérico de 15 min.
  const guardMinutes = action === ACTIONS.FINAL
    ? Math.min(cfg.duplicateRunGuardMinutes, cfg.finalRetryMinutes)
    : cfg.duplicateRunGuardMinutes;
  if (ageMin >= 0 && ageMin < guardMinutes) {
    return {
      blocked: true,
      reason: `circuit breaker: ${workflowName} já teve run há ${ageMin.toFixed(1)} min (${latest.status || "?"}/${latest.conclusion || "?"}); guard=${guardMinutes}min`,
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

async function dispatchWorkflow(env, action, context = {}) {
  const spec = WORKFLOW_BY_ACTION[action];
  if (!spec) throw new Error(`Ação sem workflow: ${action}`);
  const branch = String(env.GITHUB_BRANCH || "main");
  const url = `${repoBase(env)}/actions/workflows/${encodeURIComponent(spec.file)}/dispatches`;
  const inputs = { ...(spec.inputs || {}) };
  if (action === ACTIONS.FINAL) {
    const eventIds = uniqueStrings(context?.eventIds || []);
    if (eventIds.length) inputs.event_ids = eventIds.join(",");
  }
  const response = await fetch(url, {
    method: "POST",
    headers: { ...githubHeaders(env), "content-type": "application/json" },
    body: JSON.stringify({ ref: branch, inputs }),
  });
  const bodyText = await response.text();
  if (!response.ok) {
    throw new Error(`workflow_dispatch ${spec.file}: HTTP ${response.status}: ${bodyText.slice(0, 500)}`);
  }

  let payload = null;
  if (bodyText.trim()) {
    try { payload = JSON.parse(bodyText); } catch { payload = null; }
  }
  return {
    file: spec.file,
    httpStatus: response.status,
    workflowRunId: payload?.workflow_run_id ?? null,
    runUrl: payload?.html_url ?? payload?.run_url ?? null,
  };
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
      fastPath: {
        scoreboardPrimary: true,
        browserLikeScoreboard: true,
        cloudflareFetchCachePolicy: "request_no_store_without_cf_cacheTtl",
        summaryFallbackByEventId: true,
        passesEventIdsToMainWorkflow: true,
        mainWorkflowIncremental: true,
        probeIntervalSeconds: runtimeConfig(this.env).fastProbeIntervalSeconds,
        finalDebounceSeconds: runtimeConfig(this.env).finalDebounceSeconds,
        finalRetryMinutes: runtimeConfig(this.env).finalRetryMinutes,
        safetyTriggerMinutes: runtimeConfig(this.env).finalSafetyStartMinutes,
        safetyRetryMinutes: runtimeConfig(this.env).finalSafetyRetryMinutes,
      },
      orchestration: {
        strategy: "agenda_event_driven_v2",
        githubHeavyWorkOnlyOnEvidence: true,
        ageOnlyMainDispatchDisabled: true,
        agendaScoutWithoutGithubAction: true,
        sourceRecoveryProbeWithoutGithubAction: true,
        preGameWakeHours: runtimeConfig(this.env).preGameWakeHours,
      },
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
      phase: state.phase || "unknown",
      nextWakeAt: state.nextWakeAt || null,
      nextWakeReason: state.nextWakeReason || null,
      lastFastProbeAt: state.lastFastProbeAt,
      lastAgendaScoutAt: state.lastAgendaScoutAt || null,
      relevantSportsGames: state.relevantSportsGames || 0,
      slowEvaluated: state.slowEvaluated === true,
      candidate: state.candidate,
      result: state.result,
      resultReason: state.resultReason,
      errors: state.errors || [],
      fastPath: {
        scoreboardPrimary: true,
        browserLikeScoreboard: true,
        cloudflareFetchCachePolicy: "request_no_store_without_cf_cacheTtl",
        summaryFallbackByEventId: true,
        passesEventIdsToMainWorkflow: true,
        mainWorkflowIncremental: true,
        probeIntervalSeconds: runtimeConfig(this.env).fastProbeIntervalSeconds,
        finalDebounceSeconds: runtimeConfig(this.env).finalDebounceSeconds,
        finalRetryMinutes: runtimeConfig(this.env).finalRetryMinutes,
        safetyTriggerMinutes: runtimeConfig(this.env).finalSafetyStartMinutes,
        safetyRetryMinutes: runtimeConfig(this.env).finalSafetyRetryMinutes,
      },
      hints: snap ? {
        nextGameAt: snap.nextGameAt,
        nextGame: snap.nextGameLabel,
        pendingCalendar: snap.pendingCalendar,
        agendaSignature: snap.agendaSignature,
        source: snap.source,
        coreOldestAgeHours: Number.isFinite(snap.core?.oldestAgeHours) ? Number(snap.core.oldestAgeHours.toFixed(2)) : null,
        agendaScout: {
          lastAt: state.lastAgendaScoutAt || null,
          diagnostics: state.lastAgendaScoutDiagnostics || null,
          mainSignalLast: state.mainSignalLast || null,
        },
        blocks: {
          status: snap.blocks?.status,
          nextEventAt: snap.blocks?.nextEventAt,
          warnings: snap.blocks?.warnings,
        },
        apuracao: snap.apuracao,
        af: snap.af,
        afControl: {
          lastAttempt: state.afLastAttempt || null,
          sameDivergenceBackoffMinutes: runtimeConfig(this.env).afSameDivergenceBackoffMinutes,
        },
        transmissoesTv: {
          games35d: snap.tv?.games35d,
          covered35d: snap.tv?.covered35d,
          missing35d: snap.tv?.missing35d,
          missing14d: snap.tv?.missing14d,
          critical72h: snap.tv?.critical72h,
          updatedAt: snap.tv?.updatedAt,
        },
        pendingFinals: state.pendingFinals || {},
        finalSafetyLastAttempt: state.finalSafetyLastAttempt || {},
        lastFastProbeDiagnostics: state.lastFastProbeDiagnostics || null,
        fastProbeWarnings: state.fastProbeWarnings || [],
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
    state.fastProbeWarnings = [];
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

    // Agenda/Event Driven 2.0: mesmo com cron de 1 minuto, este plano deixa o
    // Worker em SLEEP até existir uma razão esportiva/operacional concreta.
    const wakePlan = computeWakePlan(state.snapshot, nowMs, cfg);
    state.phase = wakePlan.phase;
    state.nextWakeAt = iso(wakePlan.nextWakeAtMs);
    state.nextWakeReason = wakePlan.nextWakeReason;

    let agendaSelected = null;
    const lastAgendaScout = parseDate(state.lastAgendaScoutAt);
    const scoutInterval = agendaScoutIntervalMs(state.snapshot, nowMs, cfg);
    const scoutDue = state.phase !== "final_watch"
      && (!Number.isFinite(lastAgendaScout) || nowMs - lastAgendaScout >= scoutInterval);

    if (scoutDue) {
      const scout = await probeAgenda(state.snapshot, nowMs, cfg);
      state.lastAgendaScoutAt = iso(nowMs);
      state.lastAgendaScoutDiagnostics = scout.diagnostics;
      if (scout.finals.length) {
        const syntheticStates = Object.fromEntries(scout.finals.map((id) => [id, { state: "post", source: "agenda_scout" }]));
        state.pendingFinals = collectNewFinals(state.snapshot, syntheticStates, state.pendingFinals, nowMs);
      }
      if (scout.changes.length) {
        const labels = scout.changes.slice(0, 4).map((c) => `${c.game}: ${c.localKickoff || "TBA"} -> ${c.remoteKickoff}`).join("; ");
        agendaSelected = candidate(
          ACTIONS.MAIN,
          `Mudança objetiva de agenda detectada pela ESPN sem rodar GitHub: ${labels}.`,
          {
            mainSignalSignature: `agenda:${state.snapshot.agendaSignature}:${scout.signature}`,
            signalBackoffMinutes: state.phase === "near_game" || state.phase === "pre_game" ? 30 : cfg.mainSignalBackoffMinutes,
          },
        );
      } else if (state.snapshot?.source?.healthy === false && scout.reachable) {
        agendaSelected = candidate(
          ACTIONS.MAIN,
          "A última coleta foi preservada, mas a ESPN voltou a responder ao probe barato do Cloudflare; executar uma única recuperação incremental.",
          {
            mainSignalSignature: `source-recovery:${state.snapshot.source.fingerprint || state.snapshot.source.status}:${state.snapshot.resultCount}`,
            signalBackoffMinutes: cfg.mainSignalBackoffMinutes,
          },
        );
      }
    }

    // FAST PATH: apenas detectar FINAL. Não há AO VIVO, gols, placar ou eventos no escopo.
    // FINAL já conhecido no calendário mas ainda ausente em resultados também entra
    // na fila de convergência, sem depender de uma nova resposta da ESPN.
    state.pendingFinals = collectRepositoryFinals(state.snapshot, state.pendingFinals, nowMs);

    // Janela normal: +88..+300 min. Recovery: até +12h, a cada 5 min.
    const probeGames = relevantFinalProbeGames(state.snapshot, nowMs, cfg);
    state.relevantSportsGames = probeGames.length;
    const lastFast = parseDate(state.lastFastProbeAt);
    const probeIntervalMs = finalProbeIntervalMs(probeGames, nowMs, cfg);
    if (probeGames.length && (!Number.isFinite(lastFast) || nowMs - lastFast >= probeIntervalMs)) {
      const cacheAge = ageHours(state.snapshot?.fetchedAtMs, nowMs);
      if (cacheAge <= cfg.staleCacheMaxHoursForFinal) {
        const probed = await probeEspn(probeGames, nowMs);
        state.lastFastProbeAt = iso(nowMs);
        state.lastFastProbeDiagnostics = probed.diagnostics || null;
        state.fastProbeWarnings = probed.errors || [];
        state.pendingFinals = collectNewFinals(state.snapshot, probed.states, state.pendingFinals, nowMs);
      } else {
        state.errors.push(`cache do repositório velho demais para FINAL (${cacheAge.toFixed(1)}h)`);
      }
    }
    let selected = chooseFinalCandidate(state.snapshot, state.pendingFinals, nowMs, cfg);
    if (!selected) selected = chooseSafetyFinalCandidate(state.snapshot, state, nowMs, cfg);
    const hasPendingFinalDebounce = Object.keys(state.pendingFinals || {}).length > 0;
    // 1.1.0: recovery de FINAL NÃO bloqueia mais o slow path. Só preservamos a
    // prioridade por poucos segundos enquanto um FINAL confirmado está no debounce.
    if (!selected && !hasPendingFinalDebounce && agendaSelected) {
      selected = agendaSelected;
    }
    if (!selected && !hasPendingFinalDebounce) {
      selected = chooseSlowCandidate(state.snapshot, state, nowMs, cfg);
    }
    if (!selected && hasPendingFinalDebounce) {
      state.resultReason = "FINAL confirmado em debounce curto; demais rotinas voltam a ser elegíveis imediatamente depois";
    } else if (!selected && probeGames.length > 0) {
      state.resultReason = `monitorando encerramento; scoreboard primário + summary fallback; safety trigger em T+${cfg.finalSafetyStartMinutes}min`;
    } else if (!selected) {
      state.resultReason = `${String(state.phase || "sleep").toUpperCase()}: nenhuma mudança capaz de justificar GitHub Action; próximo wake: ${state.nextWakeAt || "n/a"} (${state.nextWakeReason || "sem motivo"})`;
    }
    state.candidate = selected;

    if (!selected) {
      await this.writeState(state);
      return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
    }

    // FINAL: revalida resultados imediatamente antes do dispatch para evitar duplicata por cache.
    if (selected.action === ACTIONS.FINAL && Array.isArray(selected.eventIds) && selected.eventIds.length) {
      try {
        const freshIds = await refreshResultIds(this.env);
        const alreadyPresent = selected.eventIds.filter((id) => freshIds.has(id));
        const missing = selected.eventIds.filter((id) => !freshIds.has(id));
        for (const id of alreadyPresent) delete state.pendingFinals[id];
        if (alreadyPresent.length && state.snapshot) {
          state.snapshot.resultIds = uniqueStrings([...(state.snapshot.resultIds || []), ...alreadyPresent]);
          state.snapshot.resultCount = Math.max(safeInt(state.snapshot.resultCount), state.snapshot.resultIds.length);
        }
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

    const signalGuard = mainSignalBlocked(state, selected, nowMs, cfg);
    if (signalGuard?.blocked) {
      state.result = "none";
      state.resultReason = signalGuard.reason;
      recordDecision(state, nowMs, { action: ACTIONS.NONE, reason: signalGuard.reason, result: "signal_backoff" }, cfg);
      await this.writeState(state);
      return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
    }

    const isFinalConvergence = selected.action === ACTIONS.FINAL && Array.isArray(selected.eventIds) && selected.eventIds.length > 0;
    const lastMain = isFinalConvergence ? parseDate(state?.lastDispatchAt?.[ACTIONS.FINAL]) : null;
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
        state.nextSlowAt = iso(computeNextSlowAt(state.snapshot, nowMs, cfg));
        await this.writeState(state);
        return jsonResponse({ ok: true, action: ACTIONS.NONE, reason: state.resultReason });
      }

      const workflow = await dispatchWorkflow(this.env, selected.action, selected);
      state.lastDispatchAt = { ...(state.lastDispatchAt || {}), [selected.action]: iso(nowMs) };
      if (selected.action === ACTIONS.MAIN && selected.mainSignalSignature) {
        state.mainSignalLast = {
          signature: String(selected.mainSignalSignature),
          at: iso(nowMs),
          reason: selected.reason,
          retryAfter: iso(nowMs + Number(selected.signalBackoffMinutes || cfg.mainSignalBackoffMinutes) * 60_000),
        };
      }
      if (selected.action === ACTIONS.FINAL && selected.safetyTrigger === true) {
        const map = { ...(state.finalSafetyLastAttempt || {}) };
        for (const id of uniqueStrings(selected.eventIds || [])) map[id] = iso(nowMs);
        state.finalSafetyLastAttempt = map;
      }
      if (selected.action === ACTIONS.MAIN_AF) {
        state.afLastAttempt = {
          signature: String(selected.afSignature || `${safeInt(state.snapshot?.af?.results)}:${safeInt(state.snapshot?.af?.recognized)}`),
          at: iso(nowMs),
          retryAfter: iso(nowMs + cfg.afSameDivergenceBackoffMinutes * 60_000),
        };
      }
      state.result = "dispatched";
      state.resultReason = selected.reason;
      recordDecision(state, nowMs, { action: selected.action, reason: selected.reason, result: "dispatched", workflow, checkpoint: selected.checkpoint || null }, cfg);

      // 1.1.0: dispatch não significa publicação. pendingFinals permanece até
      // resultados.json realmente conter o event_id; então a revalidação o remove.
      // Após qualquer writer, refresca o repositório cedo para observar o novo estado.
      state.nextSlowAt = iso(nowMs + (selected.action === ACTIONS.FINAL ? 2 : 5) * 60_000);
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

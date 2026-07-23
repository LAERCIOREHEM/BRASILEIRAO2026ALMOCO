(function () {
  "use strict";

  const FILES = {
    leaders: "dados-br/lideres-jogadores.json",
    competition: "dados-br/estatisticas-competicao.json",
    details: "dados-br/jogos-detalhes.json",
    ranking: "dados-br/ranking-desempenho.json",
    rankingHistory: "dados-br/historico-ranking-desempenho.json",
    table: "tabela.json",
    results: "resultados.json",
    audit: "dados-br/auditoria-estatisticas.json",
    probabilities: "dados-br/probabilidades-brasileirao.json",
    probabilitiesAudit: "dados-br/auditoria-probabilidades.json",
    probabilitiesHistory: "dados-br/historico-probabilidades.json",
    probabilityModelsAudit: "dados-br/auditoria-modelos-af-previsao.json",
    probabilityEvaluation: "dados-br/avaliacao-af-previsao.json",
    pointsThresholds: "dados-br/probabilidades-por-pontuacao.json",
  };

  const state = {
    leaders: null,
    competition: null,
    details: null,
    ranking: null,
    rankingHistory: null,
    table: null,
    results: null,
    audit: null,
    probabilities: null,
    probabilitiesAudit: null,
    probabilitiesHistory: null,
    probabilityModelsAudit: null,
    probabilityEvaluation: null,
    pointsThresholds: null,
    probabilitySort: "classificacao",
    probabilityHistoryClub: "",
    probabilityHistoryMetric: "campeao_pct",
    tab: "probabilidades",
    expanded: { artilheiros: false, assistencias: false, publico: false },
    expandedClubGoals: {},
    clubFilter: "",
    gamesLimit: 10,
  };

  const $ = (id) => document.getElementById(id);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    }[c]));
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function eventText(value) {
    if (value && typeof value === "object") {
      return String(value.displayValue ?? value.displayClock ?? value.text ?? value.name ?? value.value ?? "").trim();
    }
    const text = String(value ?? "").trim();
    if (!text) return "";
    const display = text.match(/displayValue['"\s:]+([^,}\]]+)/i);
    return display ? display[1].replace(/^['"\s]+|['"\s]+$/g, "") : text;
  }

  function eventMinute(event) {
    return eventText(event?.minuto ?? event?.clock ?? event?.displayClock ?? event?.time);
  }

  function eventTeam(event) {
    const raw = event?.time;
    let text = "";
    if (raw && typeof raw === "object") {
      text = String(raw.displayName ?? raw.shortDisplayName ?? raw.fullName ?? raw.name ?? raw.abbreviation ?? "").trim();
    } else {
      text = String(raw ?? "").trim();
    }
    if (!text || /^[{[]/.test(text) || /displayValue|['"]value['"]\s*:/i.test(text)) return "";
    return text;
  }

  function minuteKey(value) {
    const nums = eventText(value).match(/\d+/g) || [];
    return nums.length ? `${Number(nums[0])}+${Number(nums[1] || 0)}` : normalize(value);
  }

  function uniqueEvents(list, kind) {
    const best = new Map();
    for (const original of (Array.isArray(list) ? list : [])) {
      if (!original || typeof original !== "object") continue;
      const item = {
        ...original,
        minuto: eventMinute(original),
        jogador: String(original.jogador || "").trim(),
        time: eventTeam(original),
      };
      const identity = normalize(item.jogador) || normalize(item.descricao || "");
      const key = [kind, normalize(item.tipo || ""), minuteKey(item.minuto), identity].join("|");
      const quality = (item.jogador ? 20 : 0) + (item.time ? 10 : 0) + (item.descricao ? 2 : 0);
      const previous = best.get(key);
      if (!previous || quality > previous.quality) best.set(key, { item, quality });
    }
    return Array.from(best.values(), (entry) => entry.item);
  }

  function clubSlug(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  }

  function clubHref(name) {
    return `clubes.html#${encodeURIComponent(clubSlug(name))}`;
  }

  function number(value, digits = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("pt-BR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function integer(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString("pt-BR") : "—";
  }

  function dateTimeBR(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString("pt-BR", {
      timeZone: "America/Sao_Paulo",
      dateStyle: "short",
      timeStyle: "short",
    });
  }

  function dateBR(value) {
    if (!value) return "Data não informada";
    const s = String(value);
    const d = new Date(s.length <= 16 ? `${s}:00-03:00` : s);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleDateString("pt-BR", {
      timeZone: "America/Sao_Paulo",
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  }

  async function fetchJson(path, fallback) {
    try {
      const response = await fetch(`${path}${path.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.warn(`Falha ao carregar ${path}:`, error);
      return fallback;
    }
  }

  function tableRows() {
    return Array.isArray(state.table?.tabela) ? state.table.tabela : [];
  }

  function resultsRows() {
    return Array.isArray(state.results?.resultados) ? state.results.resultados : [];
  }

  function teamMap() {
    const map = new Map();
    const add = (team) => {
      if (!team || typeof team !== "object") return;
      const name = String(team.time || team.nome || "").trim();
      if (!name) return;
      const key = normalize(name);
      const previous = map.get(key) || {};
      map.set(key, {
        ...previous,
        ...team,
        time: String(team.time || previous.time || team.nome || previous.nome || name),
        nome: String(team.nome || previous.nome || team.time || previous.time || name),
        escudo: String(team.escudo || previous.escudo || ""),
        sigla: String(team.sigla || previous.sigla || ""),
      });
    };

    tableRows().forEach(add);
    resultsRows().forEach((game) => [game?.mandante, game?.visitante].forEach(add));
    (Array.isArray(state.competition?.gols_por_clube) ? state.competition.gols_por_clube : []).forEach(add);
    (Array.isArray(state.ranking?.ranking) ? state.ranking.ranking : []).forEach(add);
    if (leadersValid()) {
      [...state.leaders.artilharia, ...state.leaders.assistencias].forEach((player) => add({
        time: player?.time,
        nome: player?.time,
        escudo: player?.escudo,
        sigla: player?.sigla,
      }));
    }
    return map;
  }

  function teamInfo(name) {
    return teamMap().get(normalize(name)) || { time: name || "", nome: name || "", escudo: "", sigla: "" };
  }

  function teamName(obj) {
    return String(obj?.time || obj?.nome || obj || "");
  }

  function initials(name) {
    return String(name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?";
  }

  function shield(obj, cls = "stats-shield") {
    const name = teamName(obj);
    const info = teamInfo(name);
    const src = String((obj && typeof obj === "object" ? obj.escudo : "") || info?.escudo || "");
    const fallback = "img/escudo-neutro.svg";
    return `<img class="${escapeAttr(cls)}${src ? "" : " is-neutral-shield"}" src="${escapeAttr(src || fallback)}" alt="" loading="lazy" onerror="this.onerror=null; this.src='${fallback}'; this.classList.add('is-neutral-shield')">`;
  }

  function leadersValid() {
    return state.leaders?.status === "valido" && Array.isArray(state.leaders?.artilharia) && Array.isArray(state.leaders?.assistencias);
  }

  function detailMap() {
    return state.details?.jogos && typeof state.details.jogos === "object" ? state.details.jogos : {};
  }

  function gameDetail(game) {
    const id = String(game?.event_id || game?.id || "");
    if (id && detailMap()[id]) return detailMap()[id];
    return Object.values(detailMap()).find((item) => item && String(item.event_id || "") === id) || null;
  }

  function gameById(eventId) {
    return resultsRows().find((game) => String(game.event_id || game.id || "") === String(eventId || "")) || null;
  }

  function sortedResults() {
    return resultsRows().slice().sort((a, b) => String(b.data_iso || "").localeCompare(String(a.data_iso || "")));
  }

  function emptyState(message, extra = "") {
    return `<div class="stats-empty"><strong>${escapeHtml(message)}</strong>${extra ? `<span>${escapeHtml(extra)}</span>` : ""}</div>`;
  }

  function summaryCard(icon, label, primary, secondary, team) {
    const logo = team ? shield(team, "summary-shield") : `<span class="summary-icon">${icon}</span>`;
    return `<article class="stats-summary-card">
      <div class="stats-summary-label">${logo}<span>${escapeHtml(label)}</span></div>
      <div class="stats-summary-primary">${escapeHtml(primary || "Aguardando dados")}</div>
      <div class="stats-summary-secondary">${escapeHtml(secondary || "")}</div>
    </article>`;
  }

  function renderSummary() {
    const scorer = leadersValid() ? state.leaders.artilharia[0] : null;
    const assistant = leadersValid() ? state.leaders.assistencias[0] : null;
    const attacks = Array.isArray(state.competition?.gols_por_clube) && state.competition.gols_por_clube.length
      ? state.competition.gols_por_clube
      : tableRows().slice().sort((a, b) => Number(b.gp || 0) - Number(a.gp || 0));
    const attack = attacks[0] || null;
    const rank = Array.isArray(state.ranking?.ranking) ? state.ranking.ranking[0] : null;

    $("cards-resumo").innerHTML = [
      summaryCard("⚽", "Artilheiro", scorer?.nome, scorer ? `${scorer.time} · ${integer(scorer.gols)} gols` : "Ranking oficial ainda não atualizado", scorer),
      summaryCard("🎯", "Garçom", assistant?.nome, assistant ? `${assistant.time} · ${integer(assistant.assistencias)} assist.` : "Ranking oficial ainda não atualizado", assistant),
      summaryCard("🥅", "Melhor ataque", attack?.time, attack ? `${integer(attack.gols_pro ?? attack.gp)} gols` : "Aguardando consolidado", attack),
      summaryCard("⚡", "Ranking", rank?.time, rank ? `Índice ${number(rank.indice_final ?? rank.score, 1)}` : "Aguardando ranking", rank),
    ].join("");
  }

  function playerRows(type) {
    if (!leadersValid()) return [];
    return type === "artilheiros" ? state.leaders.artilharia : state.leaders.assistencias;
  }

  function renderPlayers(type) {
    const target = type === "artilheiros" ? $("lista-artilharia") : $("lista-assistencias");
    const list = playerRows(type);
    const field = type === "artilheiros" ? "gols" : "assistencias";
    const unit = type === "artilheiros" ? "gols" : "assist.";
    if (!list.length) {
      target.innerHTML = emptyState("Ranking oficial ainda não disponível.", "Execute o workflow Atualizar Brasileirao (ESPN) e aguarde a coleta validada.");
      return;
    }
    const expanded = state.expanded[type];
    const shown = expanded ? list : list.slice(0, 5);
    target.innerHTML = `<div class="stats-player-list">${shown.map((player, index) => {
      const games = Number(player.jogos);
      const value = Number(player[field] || 0);
      const average = Number.isFinite(games) && games > 0 ? `${number(value / games, 2)} por jogo` : "Jogos não informados";
      return `<article class="stats-player-row">
        <div class="stats-rank">${integer(player.posicao || index + 1)}</div>
        <div class="stats-player-main">
          <div class="stats-player-name">${escapeHtml(player.nome)}</div>
          <div class="stats-player-club">${shield(player, "stats-mini-shield")}<span>${escapeHtml(player.time)}</span></div>
          <div class="stats-player-meta">${Number.isFinite(games) ? `${integer(games)} jogos · ` : ""}${escapeHtml(average)}</div>
        </div>
        <div class="stats-player-value"><strong>${integer(value)}</strong><span>${unit}</span></div>
      </article>`;
    }).join("")}</div>${list.length > 5 ? `<button class="stats-expand-btn" type="button" data-expand-list="${type}">${expanded ? "Mostrar somente os 5 primeiros ↑" : `Ver todos (${list.length}) ↓`}</button>` : ""}`;
  }

  function clubOptions() {
    return tableRows().slice().sort((a, b) => String(a.time || "").localeCompare(String(b.time || ""), "pt-BR"));
  }

  function filteredGames() {
    const filter = normalize(state.clubFilter);
    return sortedResults().filter((game) => {
      if (!filter) return true;
      return normalize(game?.mandante?.nome) === filter || normalize(game?.visitante?.nome) === filter;
    });
  }

  function renderGameFilter() {
    const clubs = clubOptions();
    const selected = state.clubFilter;
    const info = selected ? teamInfo(selected) : null;
    const games = filteredGames();
    $("filtro-jogos").innerHTML = `<div class="stats-game-filter">
      <div class="stats-filter-control">
        <label for="stats-club-filter">Clube</label>
        <select id="stats-club-filter">
          <option value="">Todos os clubes</option>
          ${clubs.map((club) => `<option value="${escapeAttr(club.time)}" ${normalize(club.time) === normalize(selected) ? "selected" : ""}>${escapeHtml(club.time)}</option>`).join("")}
        </select>
      </div>
      <div class="stats-filter-current">
        ${selected ? shield(info, "stats-filter-shield") : `<span class="stats-filter-all">BR</span>`}
        <div><strong>${escapeHtml(selected || "Todos os clubes")}</strong><span>${integer(games.length)} partida(s) encontrada(s)</span></div>
        ${selected ? `<button type="button" data-clear-game-filter>Limpar</button>` : ""}
      </div>
    </div>`;
    const select = $("stats-club-filter");
    select?.addEventListener("change", () => {
      state.clubFilter = select.value || "";
      state.gamesLimit = 10;
      renderGameFilter();
      renderGames();
    });
    $("filtro-jogos").querySelector("[data-clear-game-filter]")?.addEventListener("click", () => {
      state.clubFilter = "";
      state.gamesLimit = 10;
      renderGameFilter();
      renderGames();
    });
  }

  function matchScore(game) {
    return `${integer(game.placar_mandante)} × ${integer(game.placar_visitante)}`;
  }

  function eventLine(goal) {
    const assists = Array.isArray(goal?.assistencias) && goal.assistencias.length
      ? ` · assistência: ${goal.assistencias.join(", ")}`
      : "";
    return `<li><span>⚽ ${escapeHtml(goal?.minuto || "")}</span><strong>${escapeHtml(goal?.jogador || "Gol")}</strong><small>${escapeHtml(goal?.time || "")}${escapeHtml(assists)}</small></li>`;
  }

  function cardLine(card) {
    const icon = card?.tipo === "vermelho" ? "🟥" : "🟨";
    return `<li><span>${icon} ${escapeHtml(card?.minuto || "")}</span><strong>${escapeHtml(card?.jogador || "Cartão")}</strong><small>${escapeHtml(card?.time || "")}</small></li>`;
  }

  function statisticRows(detail) {
    const stats = Array.isArray(detail?.stats) ? detail.stats : (Array.isArray(detail?.estatisticas) ? detail.estatisticas : []);
    if (!stats.length) return emptyState("Estatísticas avançadas não disponibilizadas para esta partida.");
    return `<div class="stats-match-stat-list">${stats.map((stat) => `<div class="stats-match-stat-row">
      <strong>${escapeHtml(stat.home ?? stat.mandante ?? "—")}</strong>
      <span>${escapeHtml(stat.nome || stat.label || "Estatística")}</span>
      <strong>${escapeHtml(stat.away ?? stat.visitante ?? "—")}</strong>
    </div>`).join("")}</div>`;
  }

  function gameCard(game) {
    const detail = gameDetail(game) || {};
    const home = game.mandante || teamInfo(detail.mandante);
    const away = game.visitante || teamInfo(detail.visitante);
    const crowd = Number(detail.publico);
    const goals = uniqueEvents(detail.gols, "goal");
    const cards = uniqueEvents(detail.cartoes, "card");
    return `<details class="stats-game-card" data-game-id="${escapeAttr(game.event_id || game.id || "")}">
      <summary>
        <span class="stats-game-round">R${escapeHtml(game.rodada || detail.rodada || "—")}</span>
        <div class="stats-game-summary-main">
          <div class="stats-game-date">${escapeHtml(dateBR(game.data_iso || detail.data_iso))}</div>
          <div class="stats-game-teams">
            <span>${shield(home, "stats-game-shield")} ${escapeHtml(teamName(home))}</span>
            <b>${escapeHtml(matchScore(game))}</b>
            <span>${escapeHtml(teamName(away))} ${shield(away, "stats-game-shield")}</span>
          </div>
          <div class="stats-game-quick">${detail.estadio ? `📍 ${escapeHtml(detail.estadio)}` : ""}${Number.isFinite(crowd) && crowd > 0 ? ` · 👥 ${integer(crowd)}` : ""}</div>
        </div>
        <span class="stats-game-chevron">⌄</span>
      </summary>
      <div class="stats-game-body">
        <div class="stats-game-info-grid">
          <div><span>Estádio</span><strong>${escapeHtml(detail.estadio || game.estadio || "Não informado")}</strong></div>
          <div><span>Público</span><strong>${Number.isFinite(crowd) && crowd > 0 ? integer(crowd) : "Não informado"}</strong></div>
          <div><span>Árbitro</span><strong>${escapeHtml(detail.arbitro || "Não informado")}</strong></div>
        </div>
        ${(goals.length || cards.length) ? `<div class="stats-match-events">
          ${goals.length ? `<section><h4>Gols</h4><ul>${goals.map(eventLine).join("")}</ul></section>` : ""}
          ${cards.length ? `<section><h4>Cartões</h4><ul>${cards.map(cardLine).join("")}</ul></section>` : ""}
        </div>` : ""}
        ${statisticRows(detail)}
        <div class="stats-source-note">Fonte: ESPN; público complementado por fonte documental quando ausente. Nenhum campo é estimado.</div>
      </div>
    </details>`;
  }

  function renderGames() {
    const target = $("lista-jogos-estatisticas");
    const games = filteredGames();
    if (!games.length) {
      target.innerHTML = emptyState("Nenhuma partida encontrada para o filtro selecionado.");
      return;
    }
    const shown = games.slice(0, state.gamesLimit);
    target.innerHTML = `<div class="stats-games-list">${shown.map(gameCard).join("")}</div>${games.length > shown.length ? `<button type="button" class="stats-expand-btn" data-more-games>Mostrar mais ${Math.min(10, games.length - shown.length)} jogos ↓</button>` : ""}`;
    target.querySelector("[data-more-games]")?.addEventListener("click", () => {
      state.gamesLimit += 10;
      renderGames();
    });
  }

  function renderClubGoals() {
    const target = $("lista-gols-clube");
    const list = Array.isArray(state.competition?.gols_por_clube) ? state.competition.gols_por_clube : [];
    if (!list.length) {
      target.innerHTML = emptyState("Consolidado de gols por clube ainda não disponível.", "Aguarde a atualização automática dos dados.");
      return;
    }
    target.innerHTML = `<div class="stats-club-goals-list">${list.map((club, index) => {
      const markers = Array.isArray(club.marcadores) ? club.marcadores : [];
      const key = clubSlug(club.time);
      const expanded = Boolean(state.expandedClubGoals[key]);
      const shown = expanded ? markers : markers.slice(0, 5);
      const unknown = Number(club.gols_nao_individualizados || 0);
      return `<details class="stats-club-goals-card">
        <summary>
          <span class="stats-rank">${integer(club.posicao || index + 1)}</span>
          <a class="stats-club-shield-link" href="${escapeAttr(clubHref(club.time))}" title="Abrir página de ${escapeAttr(club.time)}" aria-label="Abrir página de ${escapeAttr(club.time)}" onclick="event.stopPropagation()">${shield(club, "stats-club-shield")}</a>
          <div class="stats-club-goals-main"><a href="${escapeAttr(clubHref(club.time))}" onclick="event.stopPropagation()"><strong>${escapeHtml(club.time)}</strong></a><span>${integer(club.jogos)} jogos · média ${number(club.media_gols, 2)}</span></div>
          <div class="stats-club-goals-value"><strong>${integer(club.gols_pro)}</strong><span>gols</span></div>
          <span class="stats-game-chevron">⌄</span>
        </summary>
        <div class="stats-club-markers">
          <h4>Marcadores do clube</h4>
          ${markers.length ? `<div class="stats-marker-list">${shown.map((player) => `<div><span>${escapeHtml(player.nome)}</span><strong>${integer(player.gols)}</strong></div>`).join("")}${unknown > 0 ? `<div class="stats-marker-other"><span>Gols contra ou ainda sem autoria individualizada</span><strong>${integer(unknown)}</strong></div>` : ""}</div>${markers.length > 5 ? `<button class="stats-expand-btn stats-marker-expand" type="button" data-expand-club-goals="${escapeAttr(key)}">${expanded ? "Mostrar somente os 5 primeiros ↑" : `Ver todos (${markers.length}) ↓`}</button>` : ""}` : emptyState("Nenhum marcador individualizado na base consolidada.")}
          <div class="stats-club-balance"><span>Gols sofridos: <b>${integer(club.gols_contra)}</b></span><span>Saldo: <b>${integer(club.saldo)}</b></span></div>
        </div>
      </details>`;
    }).join("")}</div>`;
    target.querySelectorAll("[data-expand-club-goals]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const key = button.dataset.expandClubGoals || "";
        state.expandedClubGoals[key] = !state.expandedClubGoals[key];
        renderClubGoals();
        const card = target.querySelector(`[data-expand-club-goals="${key}"]`)?.closest("details");
        if (card) card.open = true;
      });
    });
  }

  function performanceCard(record) {
    if (!record) return "";
    const home = record.mandante || "?";
    const away = record.visitante || "?";
    const score = `${integer(record.placar_mandante)} × ${integer(record.placar_visitante)}`;
    return `<button class="stats-record-card" type="button" data-open-game="${escapeAttr(record.event_id || "")}">
      <span>${escapeHtml(record.categoria || "Destaque")}</span>
      <strong>${escapeHtml(home)} ${escapeHtml(score)} ${escapeHtml(away)}</strong>
      <small>Rodada ${escapeHtml(record.rodada || "—")} · ${escapeHtml(dateBR(record.data_iso))}</small>
    </button>`;
  }

  function sequenceRows() {
    const data = state.competition?.sequencias || {};
    const definitions = [
      ["vitorias", "Vitórias"],
      ["invencibilidade", "Invencibilidade"],
      ["derrotas", "Derrotas"],
      ["sem_vencer", "Sem vencer"],
    ];
    const rows = definitions.flatMap(([key, label]) => {
      const item = data[key] || {};
      return [
        { label: `Maior sequência de ${label.toLowerCase()}`, data: item.maior },
        { label: `Sequência atual de ${label.toLowerCase()}`, data: item.atual },
      ];
    });
    if (!rows.some((row) => row.data)) return emptyState("Sequências ainda não consolidadas.");
    return `<div class="stats-sequence-list">${rows.map((row) => `<div class="stats-sequence-row"><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.data?.time || "—")}</strong><b>${integer(row.data?.quantidade)}</b></div>`).join("")}</div>`;
  }

  function attendanceGameRow(game, index) {
    return `<button type="button" class="stats-attendance-row" data-open-game="${escapeAttr(game.event_id || "")}">
      <span>${integer(index + 1)}</span>
      <div><strong>${escapeHtml(game.mandante)} × ${escapeHtml(game.visitante)}</strong><small>R${escapeHtml(game.rodada || "—")} · ${escapeHtml(dateBR(game.data_iso))}</small></div>
      <b>${integer(game.publico)}</b>
    </button>`;
  }

  function renderChampionship() {
    const target = $("campeonato-conteudo");
    const performance = state.competition?.performance_por_partida || {};
    const attendance = state.competition?.publico || {};
    const ranking = Array.isArray(attendance.ranking) ? attendance.ranking : [];
    const attendanceShown = state.expanded.publico ? ranking : ranking.slice(0, 5);
    const performanceHtml = [
      performance.mais_gols_mandante,
      performance.mais_gols_visitante,
      performance.maior_margem_vitoria,
      performance.jogo_com_mais_gols,
    ].filter(Boolean).map(performanceCard).join("");

    target.innerHTML = `<div class="stats-champ-grid">
      <section class="panel"><div class="panel-inner"><div class="section-head"><div><div class="kicker">📈 Recordes</div><h2>Performance por partida</h2></div></div>${performanceHtml ? `<div class="stats-record-grid">${performanceHtml}</div>` : emptyState("Performance por partida ainda não consolidada.")}</div></section>
      <section class="panel"><div class="panel-inner"><div class="section-head"><div><div class="kicker">🔁 Momento</div><h2>Sequências</h2></div></div>${sequenceRows()}</div></section>
    </div>
    <section class="panel stats-attendance-panel"><div class="panel-inner">
      <div class="section-head"><div><div class="kicker">👥 Torcida</div><h2>Público</h2></div><span class="badge">Jogos com dado oficial</span></div>
      <div class="stats-attendance-summary">
        <div><span>Maior público</span><strong>${integer(attendance.maior_publico?.publico)}</strong></div>
        <div><span>Menor público</span><strong>${integer(attendance.menor_publico?.publico)}</strong></div>
        <div><span>Média</span><strong>${integer(attendance.media_publico)}</strong></div>
        <div><span>Total</span><strong>${integer(attendance.total_publico)}</strong></div>
        <div><span>Jogos informados</span><strong>${integer(attendance.jogos_com_publico)}</strong></div>
      </div>
      ${attendanceShown.length ? `<div class="stats-attendance-list">${attendanceShown.map(attendanceGameRow).join("")}</div>${ranking.length > 5 ? `<button class="stats-expand-btn" type="button" data-expand-attendance>${state.expanded.publico ? "Mostrar somente os 5 maiores ↑" : `Ver todos os públicos (${ranking.length}) ↓`}</button>` : ""}` : emptyState("As fontes consultadas ainda não disponibilizaram público para os jogos processados.")}
      <p class="stats-source-note">${escapeHtml(attendance.observacao || "Média calculada somente sobre partidas com público informado.")}</p>
    </div></section>`;
  }

  function metricBar(label, value) {
    const n = Math.max(0, Math.min(100, Number(value) || 0));
    return `<div class="stats-performance-metric"><span>${escapeHtml(label)}</span><div><i style="width:${n.toFixed(1)}%"></i></div><strong>${number(n, 1)}</strong></div>`;
  }

  function renderRanking() {
    const target = $("ranking-desempenho");
    const ranking = Array.isArray(state.ranking?.ranking) ? state.ranking.ranking : [];
    if (!ranking.length) {
      target.innerHTML = emptyState("Ranking de desempenho ainda não disponível.");
      return;
    }
    target.innerHTML = `<div class="stats-performance-list">${ranking.map((club, index) => `<article class="stats-performance-card">
      <div class="stats-performance-head">
        <span class="stats-rank">${integer(club.pos || club.pos_ranking || index + 1)}</span>
        <a class="stats-performance-club-link" href="${escapeAttr(clubHref(club.time))}" title="Abrir página de ${escapeAttr(club.time)}" aria-label="Abrir página de ${escapeAttr(club.time)}">${shield(club, "stats-performance-shield")}</a>
        <div><a class="stats-performance-name-link" href="${escapeAttr(clubHref(club.time))}"><strong>${escapeHtml(club.time)}</strong></a><span>${integer(club.pontos)} pts · ${integer(club.pos_tabela)}º na tabela · SG ${integer(club.sg)}</span></div>
        <b>${number(club.indice_final ?? club.score, 1)}<small>índice</small></b>
      </div>
      <div class="stats-performance-bars">
        ${metricBar("Ataque", club.ataque)}
        ${metricBar("Defesa", club.defesa)}
        ${metricBar("Domínio", club.dominio)}
        ${metricBar("Eficiência", club.eficiencia)}
        ${metricBar("Disciplina", club.disciplina)}
      </div>
      <p>${escapeHtml(club.justificativa || "Índice calculado pelo site.")}</p>
      ${rankingPerformanceHistoryDetails(club.time)}
    </article>`).join("")}</div>`;
  }

  function probabilityDisplayText(detail, value, digits = 1) {
    const explicit = String(detail?.exibicao || "").trim();
    if (explicit) return explicit;
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    if (n >= 0 && n < 0.1) return "<0,1%";
    if (n > 99.9 && n < 100) return ">99,9%";
    return `${number(n, digits)}%`;
  }

  function probabilityFieldValue(club, field) {
    const p = club?.probabilidades_pct || {};
    if (Number.isFinite(Number(p[field]))) return Number(p[field]);
    if (field === "libertadores") return Number(p.libertadores_base);
    if (field === "sul_americana") return Number(p.sul_americana_base);
    return Number(p[field]);
  }

  function probabilityFieldDetail(club, field) {
    const details = club?.probabilidades_detalhes || {};
    return details[field] || (field === "libertadores" ? details.libertadores_base : field === "sul_americana" ? details.sul_americana_base : null);
  }

  function probabilityClubRows() {
    return Array.isArray(state.probabilities?.clubes) ? state.probabilities.clubes : [];
  }

  function probabilityClubByName(name) {
    const key = normalize(name);
    return probabilityClubRows().find((club) => normalize(club?.clube) === key) || null;
  }

  function probabilityMetric(label, value, tone = "neutral", detail = null, help = "") {
    const raw = Number(value);
    const n = Number.isFinite(raw) ? Math.max(0, Math.min(100, raw)) : 0;
    const display = probabilityDisplayText(detail, raw);
    const impossible = detail?.impossivel_estruturalmente === true || detail?.possivel_estruturalmente === false;
    const residual = !impossible && (detail?.zero_observado || (Number.isFinite(raw) && raw < 0.1));
    const title = impossible
      ? String(detail?.motivo_impossibilidade || "Via estruturalmente indisponível para o clube.")
      : residual
        ? "Evento não é tratado como impossível: ficou abaixo da resolução visual de 0,1%."
        : help;
    return `<div class="probability-metric probability-tone-${escapeAttr(tone)}"${title ? ` title="${escapeAttr(title)}"` : ""}>
      <span>${escapeHtml(label)}${residual ? '<em class="probability-residual-mark" aria-label="Probabilidade residual">ⓘ</em>' : ""}</span>
      <strong>${escapeHtml(display)}</strong>
      <div aria-hidden="true"><i style="width:${n.toFixed(4)}%"></i></div>
    </div>`;
  }

  function probabilityHighlight(icon, label, item, tone, field) {
    const club = item?.clube || "Aguardando dados";
    const row = probabilityClubByName(club);
    const pct = Number.isFinite(Number(item?.probabilidade_pct)) ? Number(item.probabilidade_pct) : probabilityFieldValue(row, field);
    const detail = probabilityFieldDetail(row, field);
    const info = teamInfo(club);
    return `<a class="probability-highlight probability-tone-${escapeAttr(tone)}" href="${escapeAttr(clubHref(club))}" aria-label="Abrir página de ${escapeAttr(club)}">
      <div class="probability-highlight-label"><span>${escapeHtml(icon)}</span>${escapeHtml(label)}</div>
      <div class="probability-highlight-main">${shield(info, "probability-highlight-shield")}<strong>${escapeHtml(club)}</strong></div>
      <b>${escapeHtml(probabilityDisplayText(detail, pct))}</b>
    </a>`;
  }

  function projectedPosition(club) {
    const explicit = Number(club?.posicao_projetada);
    if (Number.isFinite(explicit)) return Math.max(1, Math.min(20, Math.round(explicit)));
    const mean = Number(club?.posicao_projetada_media);
    return Number.isFinite(mean) ? Math.max(1, Math.min(20, Math.round(mean))) : null;
  }

  function projectedPoints(club) {
    const points = club?.pontos_projetados || {};
    const value = Number(points.media ?? points.media_estimada);
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function probabilityPositionRange(club) {
    const explicit = club?.faixa_posicao_80 || {};
    const best = Number(explicit.melhor);
    const worst = Number(explicit.pior);
    if (Number.isFinite(best) && Number.isFinite(worst)) {
      return { best: Math.min(best, worst), worst: Math.max(best, worst) };
    }
    const values = Array.isArray(club?.distribuicao_posicoes_pct) ? club.distribuicao_posicoes_pct : [];
    if (!values.length) return null;
    let cumulative = 0;
    let lower = null;
    let upper = null;
    values.forEach((value, index) => {
      cumulative += Math.max(0, Number(value) || 0);
      if (lower === null && cumulative >= 10) lower = index + 1;
      if (upper === null && cumulative >= 90) upper = index + 1;
    });
    return { best: lower || 1, worst: upper || 20 };
  }

  function probabilityProjectionMetric(label, value, tone = "position", help = "") {
    return `<div class="probability-metric probability-projection-metric probability-tone-${escapeAttr(tone)}"${help ? ` title="${escapeAttr(help)}"` : ""}>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value || "—")}</strong>
      <small>${escapeHtml(help)}</small>
    </div>`;
  }

  function probabilityTrendNote(club) {
    const trend = club?.tendencia_recente;
    if (!trend) return "";
    const games = Number(trend.jogos_considerados);
    const adjustment = Number(trend.ajuste_forca_pct);
    const label = String(trend.classificacao || "estável");
    const adjustmentText = Number.isFinite(adjustment) ? `${adjustment >= 0 ? "+" : ""}${number(adjustment, 1)}%` : "—";
    return `<p class="probability-trend-note"><span>Tendência recente</span><strong>${escapeHtml(label)}</strong><small>${Number.isFinite(games) ? `${integer(games)} jogos` : "janela recente"} · ajuste limitado ${escapeHtml(adjustmentText)}</small></p>`;
  }

  function probabilityHistoryClubRow(snapshot, clubName) {
    const row = (Array.isArray(snapshot?.clubes) ? snapshot.clubes : []).find((item) => normalize(item?.clube) === normalize(clubName));
    if (!row) return null;
    const positionRaw = Number(row.posicao_projetada ?? row.posicao_media_estimada);
    const pointsRaw = Number(row.pontos_projetados ?? row.pontos_media_estimada ?? row.pontos_medios);
    return {
      snapshot,
      row,
      position: Number.isFinite(positionRaw) ? Math.round(positionRaw) : null,
      points: Number.isFinite(pointsRaw) ? Math.round(pointsRaw) : null,
    };
  }

  function performanceHistoryClubRows(clubName) {
    const snapshots = Array.isArray(state.rankingHistory?.snapshots) ? state.rankingHistory.snapshots : [];
    return snapshots
      .filter((snapshot) => snapshot?.destaque_interface || snapshot?.id === "atual")
      .map((snapshot) => {
        const item = (Array.isArray(snapshot?.ranking) ? snapshot.ranking : [])
          .find((row) => normalize(row?.time) === normalize(clubName));
        return item ? { snapshot, item } : null;
      })
      .filter(Boolean);
  }

  function performanceHistoryMovement(currentPosition, previousPosition) {
    if (previousPosition === null || previousPosition === undefined) {
      return '<span class="club-evolution-move is-same">• início</span>';
    }
    const current = Number(currentPosition);
    const previous = Number(previousPosition);
    if (!Number.isFinite(current) || !Number.isFinite(previous) || current === previous) {
      return '<span class="club-evolution-move is-same">• manteve</span>';
    }
    const delta = Math.abs(previous - current);
    return current < previous
      ? `<span class="club-evolution-move is-up">▲ ${integer(delta)}</span>`
      : `<span class="club-evolution-move is-down">▼ ${integer(delta)}</span>`;
  }

  function performanceHistoryClubHtml(clubName) {
    const rows = performanceHistoryClubRows(clubName);
    if (!rows.length) return "";
    const cards = rows.map(({ snapshot, item }, index) => {
      const previous = index > 0 ? rows[index - 1].item : null;
      const games = Number(item?.jogos);
      const label = snapshot?.id === "atual"
        ? `Atual${Number.isFinite(games) ? ` · ${integer(games)} jogos` : ""}`
        : snapshot?.nome || "Marco";
      return `<article class="club-evolution-card${snapshot?.id === "atual" ? " is-current" : ""}">
        <span>${escapeHtml(label)}</span>
        <strong>${integer(item?.pos)}º <i>·</i> ${number(item?.indice_final, 1)}</strong>
        <small>posição · AF-Score ${performanceHistoryMovement(item?.pos, previous?.pos)}</small>
      </article>`;
    }).join("");
    return `<section class="club-performance-history" aria-label="Evolução do Ranking de Desempenho de ${escapeAttr(clubName)}">
      <div class="club-evolution-head"><div><span>AF-Score</span><strong>Evolução do Ranking de Desempenho</strong></div><small>comparação após a mesma quantidade de jogos</small></div>
      <div class="club-evolution-strip">${cards}</div>
      <p>Os marcos fechados comparam os 20 clubes após exatamente 5, 10, 15 e, futuramente, mais jogos. Assim, partidas atrasadas não criam vantagem artificial.</p>
    </section>`;
  }

  function rankingPerformanceHistoryDetails(clubName) {
    const history = performanceHistoryClubHtml(clubName);
    if (!history) return "";
    return `<details class="ranking-history-details">
      <summary><span class="ranking-history-label is-closed">Ver evolução do ranking</span><span class="ranking-history-label is-open">Recolher evolução do ranking</span><i aria-hidden="true"></i></summary>
      <div class="ranking-history-content">${history}</div>
    </details>`;
  }

  function probabilityHistoryClubStateKey(snapshot, row) {
    const publishedKey = String(row?.hash_estado_clube || "").trim();
    if (publishedKey) return publishedKey;
    const games = Number(row?.jogos_atuais);
    const points = Number(row?.pontos_atuais);
    const position = Number(row?.posicao_atual);
    const clubRound = Number(row?.rodada_referencia_clube);
    if ([games, points, position].some(Number.isFinite)) {
      return [
        Number.isFinite(games) ? games : "—",
        Number.isFinite(points) ? points : "—",
        Number.isFinite(position) ? position : "—",
        Number.isFinite(clubRound) ? clubRound : "—",
      ].join("|");
    }
    return String(snapshot?.hash_estado_esportivo || snapshot?.hash_entrada || snapshot?.hash_snapshot || snapshot?.gerado_em || "");
  }

  function probabilityClubHistoryRows(clubName, limit = 12) {
    const snapshots = Array.isArray(state.probabilitiesHistory?.snapshots) ? state.probabilitiesHistory.snapshots : [];
    const rows = [];
    snapshots.forEach((snapshot) => {
      const entry = probabilityHistoryClubRow(snapshot, clubName);
      if (!entry) return;
      const key = probabilityHistoryClubStateKey(snapshot, entry.row);
      if (rows.length && rows[rows.length - 1].stateKey === key) return;
      rows.push({ ...entry, stateKey: key });
    });
    return rows.slice(-Math.max(1, Number(limit) || 12));
  }

  function probabilityHistoryReference(snapshot, row) {
    const clubRound = Number(row?.rodada_referencia_clube);
    if (Number.isFinite(clubRound) && clubRound > 0) return `R${integer(clubRound)}`;
    const globalRound = Number(snapshot?.rodada_referencia);
    if (Number.isFinite(globalRound) && globalRound > 0) return `R${integer(globalRound)}`;
    return dateBR(snapshot?.gerado_em);
  }

  function probabilityClubHistoryDetails(club) {
    const historyRows = probabilityClubHistoryRows(club?.clube, 10);
    const performanceHistory = performanceHistoryClubHtml(club?.clube);
    if (!historyRows.length && !performanceHistory) return "";
    const body = historyRows.map(({ snapshot, row, position, points }) => {
      const reference = probabilityHistoryReference(snapshot, row);
      const title = probabilityDisplayText(null, Number(row?.campeao_pct));
      const lib = probabilityDisplayText(null, probabilityHistoryValue(row, "libertadores_pct"));
      const sula = probabilityDisplayText(null, probabilityHistoryValue(row, "sul_americana_pct"));
      const relegation = probabilityDisplayText(null, Number(row?.rebaixamento_pct));
      return `<tr><th scope="row"><span>${escapeHtml(reference)}</span><small>${escapeHtml(dateBR(snapshot?.gerado_em))}</small></th><td>${position ? `${integer(position)}º` : "—"}</td><td>${points ?? "—"}</td><td>${escapeHtml(title)}</td><td>${escapeHtml(lib)}</td><td>${escapeHtml(sula)}</td><td>${escapeHtml(relegation)}</td></tr>`;
    }).join("");
    const forecastHistory = historyRows.length ? `<section class="club-forecast-history">
      <div class="club-evolution-head"><div><span>AF-Previsão</span><strong>Evolução da previsão</strong></div><small>${integer(historyRows.length)} ${historyRows.length === 1 ? "estado salvo" : "estados salvos"}</small></div>
      <div class="probability-history-scroll"><table><thead><tr><th>Referência</th><th>Pos.</th><th>Pts</th><th>Título</th><th>Libertadores</th><th>Sul-Americana</th><th>Queda</th></tr></thead><tbody>${body}</tbody></table></div>
      <p>A evolução do clube ganha uma nova linha somente quando ele conclui outra partida. Jogos atrasados preservam a rodada real, como R4 após R19. Reexecuções sem jogo novo não criam estados artificiais.</p>
    </section>` : "";
    return `<details class="probability-history-details">
      <summary>Evolução do clube <span>AF-Score + AF-Previsão</span></summary>
      <div class="club-evolution-content">${performanceHistory}${forecastHistory}</div>
    </details>`;
  }

  function probabilityPositionDistribution(club) {
    const values = Array.isArray(club?.distribuicao_posicoes_pct) ? club.distribuicao_posicoes_pct : [];
    if (!values.length) return emptyState("Distribuição de posições ainda não disponível.");
    const max = Math.max(...values.map((value) => Number(value) || 0), 0.0001);
    return `<div class="probability-position-grid">${values.map((value, index) => {
      const n = Math.max(0, Number(value) || 0);
      const relative = n <= 0 ? 0 : Math.max(1.5, (n / max) * 100);
      const position = index + 1;
      const zone = position === 1 ? "title" : position <= 5 ? "libertadores" : position <= 11 ? "sulamericana" : position >= 17 ? "relegation" : "neutral";
      const display = probabilityDisplayText(null, n);
      return `<div class="probability-position-cell probability-position-zone-${zone}" title="${position}º lugar: ${escapeAttr(display)}">
        <span>${position}º</span>
        <div aria-hidden="true"><i style="width:${relative.toFixed(2)}%"></i></div>
        <strong>${escapeHtml(display)}</strong>
      </div>`;
    }).join("")}</div>`;
  }

  function probabilitySortRows(rows) {
    const sort = state.probabilitySort;
    const sorted = rows.slice();
    const probabilityKey = {
      campeao: "campeao",
      libertadores: "libertadores",
      sulamericana: "sul_americana",
      rebaixamento: "rebaixamento",
    }[sort];
    sorted.sort((a, b) => {
      if (sort === "classificacao") return (Number(a?.posicao_atual) || 99) - (Number(b?.posicao_atual) || 99);
      if (sort === "posicao") return (projectedPosition(a) || 99) - (projectedPosition(b) || 99);
      if (sort === "pontos") return (projectedPoints(b) || 0) - (projectedPoints(a) || 0);
      return probabilityFieldValue(b, probabilityKey) - probabilityFieldValue(a, probabilityKey);
    });
    return sorted;
  }

  const PROBABILITY_ROUTE_LABELS = {
    via_brasileirao: "Via Brasileirão",
    via_copa_do_brasil: "Via Copa do Brasil",
    via_titulo_libertadores: "Via título da Libertadores",
    via_titulo_sul_americana: "Via título da Sul-Americana",
    via_repasse: "Via repasse",
    campeao: "Campeão da Copa do Brasil",
    vice: "Vice da Copa do Brasil",
    vice_herda_vaga_direta: "Vice herdando vaga direta",
  };

  function probabilityRouteRow(key, detail, tone) {
    const n = Math.max(0, Math.min(100, Number(detail?.percentual_estimado) || 0));
    return `<div class="probability-route-row probability-route-${escapeAttr(tone)}">
      <span>${escapeHtml(PROBABILITY_ROUTE_LABELS[key] || key)}</span>
      <div aria-hidden="true"><i style="width:${n.toFixed(4)}%"></i></div>
      <strong>${escapeHtml(probabilityDisplayText(detail, n))}</strong>
    </div>`;
  }

  function probabilityQualificationRoutes(club) {
    const decomposition = club?.decomposicao_chances;
    if (!decomposition?.libertadores || !decomposition?.sul_americana) return "";
    const lib = decomposition.libertadores;
    const sula = decomposition.sul_americana;
    const libRoutes = lib.vias || {};
    const sulaRoutes = sula.vias || {};
    const cupSubroutes = lib.subvias_copa_do_brasil || {};
    const cupRows = Object.entries(cupSubroutes).map(([key, detail]) => probabilityRouteRow(key, detail, "cup")).join("");
    return `<details class="probability-route-details">
      <summary>Como se formam as chances continentais? <span>vias exclusivas e auditáveis</span></summary>
      <div class="probability-route-columns">
        <section>
          <div class="probability-route-head"><span>Libertadores consolidada</span><strong>${escapeHtml(probabilityDisplayText(lib.total, probabilityFieldValue(club, "libertadores")))}</strong></div>
          <div class="probability-route-list">${Object.entries(libRoutes).map(([key, detail]) => probabilityRouteRow(key, detail, "libertadores")).join("")}</div>
          ${cupRows ? `<details class="probability-cup-subroutes"><summary>Detalhar a via Copa do Brasil</summary><div>${cupRows}</div></details>` : ""}
        </section>
        <section>
          <div class="probability-route-head"><span>Sul-Americana consolidada</span><strong>${escapeHtml(probabilityDisplayText(sula.total, probabilityFieldValue(club, "sul_americana")))}</strong></div>
          <div class="probability-route-list">${Object.entries(sulaRoutes).map(([key, detail]) => probabilityRouteRow(key, detail, "sulamericana")).join("")}</div>
          <p>As seis vagas são destinadas aos melhores clubes ainda não classificados à Libertadores em cada universo simulado.</p>
        </section>
      </div>
      <p class="probability-route-note">Cada simulação atribui apenas uma via de Libertadores ao clube. Por isso, os caminhos somam exatamente a chance consolidada e não duplicam cenários.</p>
    </details>`;
  }

  function probabilityClubCard(club, order) {
    const points = club?.pontos_projetados || {};
    const info = teamInfo(club?.clube);
    const titleValue = probabilityFieldValue(club, "campeao");
    const libValue = probabilityFieldValue(club, "libertadores");
    const sulaValue = probabilityFieldValue(club, "sul_americana");
    const relegationValue = probabilityFieldValue(club, "rebaixamento");
    const position = projectedPosition(club);
    const projected = projectedPoints(club);
    const range = probabilityPositionRange(club);
    const rangeText = range ? `${integer(range.best)}º–${integer(range.worst)}º` : "—";
    return `<article class="probability-club-card">
      <div class="probability-club-head">
        <span class="probability-order">${integer(order)}</span>
        <a class="probability-club-link" href="${escapeAttr(clubHref(club?.clube))}" aria-label="Abrir página de ${escapeAttr(club?.clube)}">${shield(info, "probability-club-shield")}</a>
        <div class="probability-club-title">
          <a href="${escapeAttr(clubHref(club?.clube))}"><strong>${escapeHtml(club?.clube)}</strong></a>
          <span>${integer(club?.posicao_atual)}º na tabela · ${integer(club?.pontos_atuais)} pts · ${integer(club?.jogos_atuais)} jogos</span>
        </div>
        <div class="probability-points">
          <strong>${projected ?? "—"}</strong><span>pontos projetados</span>
          <small>faixa central de 80%: ${integer(points.percentil_10)}–${integer(points.percentil_90)}</small>
        </div>
      </div>
      <div class="probability-metric-grid">
        ${probabilityMetric("Campeão", titleValue, "title", probabilityFieldDetail(club, "campeao"))}
        ${probabilityProjectionMetric("Posição projetada", position ? `${integer(position)}º` : "—", "position", "Média das posições simuladas, exibida como inteiro.")}
        ${probabilityProjectionMetric("Faixa provável", rangeText, "range", "Faixa central de 80% das posições simuladas.")}
        ${probabilityMetric("Libertadores", libValue, "libertadores", probabilityFieldDetail(club, "libertadores"), "Chance consolidada por Brasileirão, copas, títulos continentais e repasses.")}
        ${probabilityMetric("Sul-Americana", sulaValue, "sulamericana", probabilityFieldDetail(club, "sul_americana"), "Chance consolidada após a alocação de todas as vagas de Libertadores.")}
        ${probabilityMetric("Rebaixamento", relegationValue, "relegation", probabilityFieldDetail(club, "rebaixamento"))}
      </div>
      ${probabilityTrendNote(club)}
      ${probabilityQualificationRoutes(club)}
      <details class="probability-position-details">
        <summary>Distribuição das 20 posições <span>projeção: ${position ? `${integer(position)}º` : "—"} · mediana: ${integer(club?.posicao_projetada_mediana)}º</span></summary>
        ${probabilityPositionDistribution(club)}
      </details>
      ${probabilityClubHistoryDetails(club)}
    </article>`;
  }


  function renderProbabilityStatus() {
    const target = $("probabilidades-status");
    if (!target) return;
    const data = state.probabilities;
    if (!data || data.status !== "ok") {
      target.innerHTML = emptyState("Probabilidades ainda não disponíveis.", "Execute o workflow Atualizar Brasileirao (ESPN) após subir os arquivos do AF-Previsão.");
      return;
    }
    const base = data.base_corrente || {};
    const sim = data.simulacao || {};
    const integrated = data.integracao_continental || {};
    const competitions = Array.isArray(integrated.competicoes) ? integrated.competicoes.length : 0;
    target.innerHTML = `<div class="probability-status-grid">
      <div><span>Modelo</span><strong>${escapeHtml(data.versao_modelo || "AF-Previsão")}</strong></div>
      <div><span>Atualização</span><strong>${escapeHtml(dateTimeBR(data.gerado_em))}</strong></div>
      <div><span>Campeonato</span><strong>${integer(base.partidas_concluidas)} concluídas · ${integer(base.partidas_restantes)} restantes</strong></div>
      <div><span>Universos integrados</span><strong>2.000.000 simulações${competitions ? ` · ${integer(competitions)} copas` : ""}</strong></div>
    </div>`;
  }

  function renderProbabilityHighlights() {
    const target = $("probabilidades-destaques");
    if (!target) return;
    const highlights = state.probabilities?.destaques;
    if (!highlights) {
      target.innerHTML = "";
      return;
    }
    target.innerHTML = `<div class="probability-highlight-grid">
      ${probabilityHighlight("🏆", "Maior chance de título", highlights.maior_chance_titulo, "title", "campeao")}
      ${probabilityHighlight("🌎", "Maior chance de Libertadores", highlights.maior_chance_libertadores, "libertadores", "libertadores")}
      ${probabilityHighlight("🟦", "Maior chance de Sul-Americana", highlights.maior_chance_sul_americana, "sulamericana", "sul_americana")}
      ${probabilityHighlight("🔻", "Maior risco de rebaixamento", highlights.maior_risco_rebaixamento, "relegation", "rebaixamento")}
    </div>`;
  }


  function pointsThresholdCell(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `<strong>${integer(n)}</strong><small>pts</small>` : `<span aria-label="nível não atingido">—</span>`;
  }

  function pointsThresholdRows(rows) {
    return rows.map((row) => `<tr>
      <th scope="row">${escapeHtml(row.rotulo || `${number(row.probabilidade_pct, 1)}%`)}</th>
      <td>${pointsThresholdCell(row.titulo)}</td>
      <td>${pointsThresholdCell(row.libertadores)}</td>
      <td>${pointsThresholdCell(row.sul_americana_ou_melhor)}</td>
      <td>${pointsThresholdCell(row.permanencia)}</td>
    </tr>`).join("");
  }

  function renderPointsThresholds() {
    const target = $("probabilidades-por-pontuacao");
    if (!target) return;
    const data = state.pointsThresholds;
    const rows = Array.isArray(data?.niveis) ? data.niveis : [];
    if (!data || data.status !== "ok" || !rows.length) {
      target.innerHTML = `<div class="probability-points-empty">Aguardando a próxima atualização íntegra do AF-Previsão.</div>`;
      return;
    }
    const mainLevels = new Set([50, 70, 80, 90, 95, 99, 99.9]);
    const mainRows = rows.filter((row) => mainLevels.has(Number(row.probabilidade_pct)));
    const extraRows = rows.filter((row) => !mainLevels.has(Number(row.probabilidade_pct)));
    const tableHead = `<thead><tr>
      <th scope="col">Chance</th>
      <th scope="col"><span>🏆</span> Título</th>
      <th scope="col"><span>🌎</span> Libertadores</th>
      <th scope="col"><span>🟦</span> Sul-Americana+</th>
      <th scope="col"><span>🛡️</span> Permanência</th>
    </tr></thead>`;
    target.innerHTML = `<div class="probability-points-scroll" tabindex="0" aria-label="Tabela de pontos necessários por objetivo">
      <table class="probability-points-table">${tableHead}<tbody>${pointsThresholdRows(mainRows)}</tbody></table>
    </div>
    ${extraRows.length ? `<details class="probability-points-more"><summary>Ver níveis detalhados <span>60%, 97%, 99,5% e 100% simulados</span></summary><div class="probability-points-scroll" tabindex="0"><table class="probability-points-table probability-points-table-extra">${tableHead}<tbody>${pointsThresholdRows(extraRows)}</tbody></table></div></details>` : ""}
    <div class="probability-points-notes">
      <p><strong>Sul-Americana+:</strong> significa alcançar ao menos uma vaga continental, seja na Sul-Americana ou na Libertadores.</p>
      <p><strong>100% nos cenários:</strong> ocorreu em todos os universos simulados daquela faixa; não representa impossibilidade matemática do cenário contrário.</p>
      <p>Atualizado em ${escapeHtml(dateTimeBR(data.gerado_em))} · ${integer(data.simulacoes)} simulações.</p>
    </div>`;
  }

  function renderProbabilityControls() {
    // Card "Ordenar tabela por / Compare os 20 clubes" removido a pedido:
    // poluía o layout. A tabela de probabilidades usa ordenação fixa por
    // classificação atual. Mantida a função vazia para não quebrar chamadas.
    const target = $("probabilidades-controles");
    if (target) target.innerHTML = "";
  }

  function probabilityComparisonRow(club) {
    const info = teamInfo(club?.clube);
    const position = projectedPosition(club);
    const range = probabilityPositionRange(club);
    const rangeText = range ? `${integer(range.best)}º–${integer(range.worst)}º` : "—";
    return `<tr>
      <td class="probability-table-position"><span>${integer(club?.posicao_atual)}</span></td>
      <th scope="row" class="probability-table-club"><a href="${escapeAttr(clubHref(club?.clube))}">${shield(info, "probability-table-shield")}<strong>${escapeHtml(club?.clube)}</strong></a></th>
      <td class="probability-table-number"><strong>${integer(club?.pontos_atuais)}</strong></td>
      <td class="probability-table-number">${integer(club?.jogos_atuais)}</td>
      <td class="probability-table-percent probability-cell-title">${escapeHtml(probabilityDisplayText(probabilityFieldDetail(club, "campeao"), probabilityFieldValue(club, "campeao")))}</td>
      <td class="probability-table-percent probability-cell-lib">${escapeHtml(probabilityDisplayText(probabilityFieldDetail(club, "libertadores"), probabilityFieldValue(club, "libertadores")))}</td>
      <td class="probability-table-percent probability-cell-sula">${escapeHtml(probabilityDisplayText(probabilityFieldDetail(club, "sul_americana"), probabilityFieldValue(club, "sul_americana")))}</td>
      <td class="probability-table-percent probability-cell-drop">${escapeHtml(probabilityDisplayText(probabilityFieldDetail(club, "rebaixamento"), probabilityFieldValue(club, "rebaixamento")))}</td>
      <td class="probability-table-projection"><strong>${position ? `${integer(position)}º` : "—"}</strong></td>
      <td class="probability-table-range">${escapeHtml(rangeText)}</td>
    </tr>`;
  }

  function renderProbabilityRanking() {
    const target = $("probabilidades-ranking");
    if (!target) return;
    const rows = probabilitySortRows(probabilityClubRows());
    if (!rows.length) {
      target.innerHTML = "";
      return;
    }
    target.innerHTML = `<section class="probability-ranking-section probability-comparison-section">
      <div class="probability-section-head"><div><div class="kicker">20 clubes</div><h3>Tabela geral de probabilidades</h3></div><span>compare chances e projeções em uma única leitura</span></div>
      <p class="probability-table-hint">↔ No celular, arraste a tabela para ver todas as probabilidades e projeções.</p>
      <div class="probability-table-shell">
        <table class="probability-comparison-table">
          <thead><tr><th>Pos.</th><th>Time</th><th>Pts</th><th>J</th><th>Campeão</th><th>Libertadores</th><th>Sul-Americana</th><th>Rebaixamento</th><th>Proj.</th><th>Faixa</th></tr></thead>
          <tbody>${rows.map(probabilityComparisonRow).join("")}</tbody>
        </table>
      </div>
    </section>`;
  }

  function renderProbabilityDetails() {
    const target = $("probabilidades-detalhes");
    if (!target) return;
    const rows = probabilitySortRows(probabilityClubRows());
    target.innerHTML = rows.length ? `<div class="probability-club-list">${rows.map((club, index) => probabilityClubCard(club, index + 1)).join("")}</div>` : "";
  }

  const PROBABILITY_HISTORY_METRICS = {
    campeao_pct: { label: "Título", detail: "campeao" },
    libertadores_pct: { label: "Libertadores", detail: "libertadores" },
    sul_americana_pct: { label: "Sul-Americana", detail: "sul_americana" },
    rebaixamento_pct: { label: "Rebaixamento", detail: "rebaixamento" },
  };

  function probabilityHistoryValue(row, metric) {
    const value = Number(row?.[metric]);
    if (Number.isFinite(value)) return value;
    if (metric === "libertadores_pct") return Number(row?.libertadores_base_pct);
    if (metric === "sul_americana_pct") return Number(row?.sul_americana_base_pct);
    return value;
  }

  function renderProbabilityEvolution() {
    const target = $("probabilidades-evolucao");
    if (!target) return;
    const snapshots = Array.isArray(state.probabilitiesHistory?.snapshots) ? state.probabilitiesHistory.snapshots : [];
    if (!snapshots.length) {
      target.innerHTML = `<section class="probability-evolution-section"><div class="probability-section-head"><div><div class="kicker">Histórico versionado</div><h3>Evolução das probabilidades</h3></div><span>0 snapshots</span></div><div class="probability-evolution-empty"><strong>O histórico ainda não começou.</strong><p>Quando o primeiro estado íntegro for publicado, esta área passará a guardar a evolução sem criar registros artificiais a cada execução.</p></div></section>`;
      return;
    }
    const latest = snapshots[snapshots.length - 1];
    const latestClubs = Array.isArray(latest?.clubes) ? latest.clubes : [];
    const clubNames = latestClubs.map((row) => row?.clube).filter(Boolean).sort((a, b) => a.localeCompare(b, "pt-BR"));
    if (!state.probabilityHistoryClub || !clubNames.includes(state.probabilityHistoryClub)) {
      const leader = latestClubs.slice().sort((a, b) => probabilityHistoryValue(b, "campeao_pct") - probabilityHistoryValue(a, "campeao_pct"))[0];
      state.probabilityHistoryClub = leader?.clube || clubNames[0] || "";
    }
    if (!PROBABILITY_HISTORY_METRICS[state.probabilityHistoryMetric]) state.probabilityHistoryMetric = "campeao_pct";
    const metric = PROBABILITY_HISTORY_METRICS[state.probabilityHistoryMetric];
    const historyRows = probabilityClubHistoryRows(state.probabilityHistoryClub, 12)
      .map(({ snapshot, row }) => ({
        snapshot,
        club: row,
        value: probabilityHistoryValue(row, state.probabilityHistoryMetric),
      }))
      .filter((row) => Number.isFinite(row.value));
    const max = Math.max(...historyRows.map((row) => row.value), 0.0001);
    const rowsHtml = historyRows.map(({ snapshot, club, value }) => {
      const detailKey = metric.detail;
      const display = String(club?.exibicao?.[detailKey] || "").trim() || probabilityDisplayText(null, value);
      const relative = value <= 0 ? 0 : Math.max(2, (value / max) * 100);
      return `<div class="probability-evolution-row"><time>${escapeHtml(dateTimeBR(snapshot?.gerado_em))}</time><div><i style="width:${relative.toFixed(2)}%"></i></div><strong>${escapeHtml(display)}</strong></div>`;
    }).join("");
    target.innerHTML = `<section class="probability-evolution-section">
      <div class="probability-section-head"><div><div class="kicker">Histórico versionado</div><h3>Evolução das probabilidades</h3></div><span>${integer(historyRows.length)} ${historyRows.length === 1 ? "estado do clube" : "estados do clube"}</span></div>
      <div class="probability-evolution-controls">
        <label><span>Clube</span><select data-probability-history-club>${clubNames.map((name) => `<option value="${escapeAttr(name)}"${name === state.probabilityHistoryClub ? " selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select></label>
        <label><span>Evento</span><select data-probability-history-metric>${Object.entries(PROBABILITY_HISTORY_METRICS).map(([key, item]) => `<option value="${key}"${key === state.probabilityHistoryMetric ? " selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select></label>
      </div>
      <div class="probability-evolution-caption"><strong>${escapeHtml(state.probabilityHistoryClub)}</strong><span>${escapeHtml(metric.label)} · uma referência por partida concluída do clube</span></div>
      ${historyRows.length ? `<div class="probability-evolution-list">${rowsHtml}</div>` : `<div class="probability-evolution-empty"><strong>Sem série suficiente para esta combinação.</strong></div>`}
    </section>`;
  }

  function renderProbabilityAudit() {
    const target = $("probabilidades-auditoria-metodo");
    if (!target) return;
    const data = state.probabilities || {};
    const audit = state.probabilitiesAudit || {};
    const models = state.probabilityModelsAudit || {};
    const winner = models?.selecao_modelo?.vencedor || {};
    const metrics = winner?.ranking?.[0]?.metricas || winner?.metricas || models?.selecao_modelo?.ranking?.[0]?.metricas || {};
    const sim = audit?.simulacao || data?.simulacao || {};
    const base = models?.base || {};
    const integrated = data?.integracao_continental || {};
    const margin = Number(sim?.convergencia?.margem_95_maxima_pontos_percentuais ?? sim?.margem_95_maxima_pontos_percentuais ?? data?.simulacao?.margem_95_maxima_pontos_percentuais);
    const threshold = Number(integrated?.limiar_exibicao_percentual ?? 0.1);
    const competitions = Array.isArray(integrated?.competicoes) ? integrated.competicoes.length : 0;
    const trend = data?.metodologia_resumida?.tendencia_recente || audit?.tendencia_recente?.configuracao || {};
    const trendWindow = Number(trend?.janela_jogos);
    const trendWeight = Number(trend?.peso_no_modelo);
    const trendLimit = Number(trend?.limite_ajuste_taxa_partida_pct);
    target.innerHTML = `<article><span>Base histórica</span><strong>${integer(base.partidas || 1140)} partidas</strong><small>${Array.isArray(base.temporadas) ? base.temporadas.join(" · ") : "2023 · 2024 · 2025"}</small></article>
      <article><span>Validação temporal</span><strong>${integer(metrics.partidas || 760)} previsões</strong><small>integralmente fora da amostra</small></article>
      <article><span>Log Loss</span><strong>${number(metrics.log_loss, 4)}</strong><small>menor é melhor</small></article>
      <article><span>Brier multiclasse</span><strong>${number(metrics.brier_multiclasse, 4)}</strong><small>menor é melhor</small></article>
      <article><span>Monte Carlo</span><strong>${integer(sim.quantidade || data?.simulacao?.quantidade)}</strong><small>semente ${integer(sim.semente || data?.simulacao?.semente)}</small></article>
      <article><span>Margem numérica</span><strong>${Number.isFinite(margin) ? `±${number(margin, 3)} p.p.` : "—"}</strong><small>pior caso aproximado, 95%</small></article>
      <article><span>Forma recente</span><strong>${Number.isFinite(trendWindow) ? `${integer(trendWindow)} jogos` : "Aguardando"}</strong><small>${Number.isFinite(trendWeight) ? `${number(trendWeight * 100, 0)}% de peso` : "peso controlado"}${Number.isFinite(trendLimit) ? ` · limite ±${number(trendLimit, 0)}%` : ""}</small></article>
      <article><span>Resolução visual</span><strong>&lt;${number(threshold, 1)}%</strong><small>zero observado não vira impossibilidade</small></article>
      <article><span>Histórico público</span><strong>${integer(state.probabilitiesHistory?.total_snapshots ?? state.probabilityEvaluation?.cobertura?.snapshots)}</strong><small>${state.probabilityEvaluation?.integridade_historico?.encadeado ? "cadeia SHA-256 íntegra" : "encadeamento após a próxima atualização"}</small></article>`;
  }

  function renderProbabilityEvaluation() {
    const target = $("probabilidades-avaliacao-final");
    if (!target) return;
    const data = state.probabilityEvaluation || {};
    const ready = data.publicar_na_interface === true && data.avaliacao_final?.agregado;
    target.hidden = !ready;
    if (!ready) {
      target.innerHTML = "";
      return;
    }
    const aggregate = data.avaliacao_final.agregado || {};
    const position = aggregate.posicao || {};
    const points = aggregate.pontos || {};
    const events = aggregate.eventos || {};
    const snapshots = Number(aggregate.snapshots_avaliados || data.cobertura?.snapshots);
    const eventCards = [
      ["Título", events.campeao],
      ["Libertadores", events.libertadores],
      ["Sul-Americana", events.sul_americana],
      ["Rebaixamento", events.rebaixamento],
    ].map(([label, metric]) => `<article><span>${escapeHtml(label)}</span><strong>${number(metric?.brier, 4)}</strong><small>Brier · Log Loss ${number(metric?.log_loss, 4)}</small></article>`).join("");
    target.innerHTML = `<section class="probability-final-evaluation" aria-labelledby="titulo-avaliacao-af">
      <div class="probability-section-head"><div><div class="kicker">Avaliação pós-campeonato</div><h3 id="titulo-avaliacao-af">Avaliação do AF-Previsão 2026</h3></div><span>${integer(snapshots)} ${snapshots === 1 ? "snapshot" : "snapshots"}</span></div>
      <p>As previsões registradas durante a temporada foram comparadas com a classificação e as vagas efetivamente observadas. A avaliação só é publicada depois da conclusão do Brasileirão e das competições que alteram as vagas continentais.</p>
      <div class="probability-final-evaluation-summary">
        <article><span>Erro médio de posição</span><strong>${number(position.mae_posicoes, 2)}</strong><small>posições por clube e snapshot</small></article>
        <article><span>Erro médio de pontos</span><strong>${number(points.mae_pontos, 2)}</strong><small>pontos por clube e snapshot</small></article>
        <article><span>RPS das posições</span><strong>${number(position.rps_posicao, 4)}</strong><small>menor é melhor</small></article>
      </div>
      <details class="probability-final-evaluation-details"><summary>Ver métricas probabilísticas <span>Brier e Log Loss</span></summary><div class="probability-final-evaluation-events">${eventCards}</div><p>O Brier Score mede a distância entre a probabilidade publicada e o desfecho observado. O Log Loss pune previsões excessivamente confiantes que terminam erradas. Em ambos, valores menores indicam melhor desempenho.</p></details>
    </section>`;
  }

  function renderProbabilities() {
    renderProbabilityStatus();
    renderProbabilityHighlights();
    renderPointsThresholds();
    renderProbabilityControls();
    renderProbabilityRanking();
    renderProbabilityDetails();
    renderProbabilityAudit();
    renderProbabilityEvaluation();
  }

  function activateTab(tab, updateHash = true) {
    state.tab = tab;
    qsa("[data-tab]").forEach((button) => {
      const active = button.dataset.tab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    qsa("[data-view]").forEach((view) => {
      const active = view.dataset.view === tab;
      view.classList.toggle("active", active);
      view.hidden = !active;
    });
    if (updateHash) history.replaceState(null, "", `#${tab}`);
    if (tab === "jogos") {
      renderGameFilter();
      renderGames();
    } else if (tab === "campeonato") {
      renderChampionship();
    } else if (tab === "probabilidades") {
      renderProbabilities();
    } else if (tab === "desempenho") {
      renderRanking();
    }
  }

  function openGame(eventId) {
    const game = gameById(eventId);
    if (!game) return;
    state.clubFilter = "";
    state.gamesLimit = Math.max(10, sortedResults().findIndex((row) => String(row.event_id || row.id || "") === String(eventId)) + 1);
    activateTab("jogos");
    requestAnimationFrame(() => {
      const safeId = String(eventId).replace(/[^a-zA-Z0-9_-]/g, "");
      const element = document.querySelector(`[data-game-id="${safeId}"]`);
      if (element) {
        element.open = true;
        element.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }

  function bindEvents() {
    qsa("[data-tab]").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    document.addEventListener("change", (event) => {
      const clubSelect = event.target.closest("[data-probability-history-club]");
      if (clubSelect) {
        state.probabilityHistoryClub = clubSelect.value;
        renderProbabilityEvolution();
        return;
      }
      const metricSelect = event.target.closest("[data-probability-history-metric]");
      if (metricSelect) {
        state.probabilityHistoryMetric = metricSelect.value;
        renderProbabilityEvolution();
      }
    });
    document.addEventListener("click", (event) => {
      const expand = event.target.closest("[data-expand-list]");
      if (expand) {
        const type = expand.dataset.expandList;
        state.expanded[type] = !state.expanded[type];
        renderPlayers(type);
        return;
      }
      const attendance = event.target.closest("[data-expand-attendance]");
      if (attendance) {
        state.expanded.publico = !state.expanded.publico;
        renderChampionship();
        return;
      }
      const probabilityMethod = event.target.closest("[data-probability-method]");
      if (probabilityMethod) {
        event.preventDefault();
        history.replaceState(null, "", "#metodologia-probabilidades");
        $("metodologia-probabilidades")?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      const probabilityTop = event.target.closest("[data-probability-top]");
      if (probabilityTop) {
        event.preventDefault();
        history.replaceState(null, "", "#probabilidades");
        $("topo-probabilidades")?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      const game = event.target.closest("[data-open-game]");
      if (game) openGame(game.dataset.openGame);
    });
  }

  function renderAll() {
    renderSummary();
    renderPlayers("artilheiros");
    renderPlayers("assistencias");
    renderClubGoals();
    renderRanking();
    renderProbabilities();
    renderChampionship();
    renderGameFilter();
    renderGames();
    activateTab(state.tab, false);
  }

  async function load() {
    bindEvents();
    const hashTab = location.hash.replace(/^#/, "");
    const openProbabilityMethod = hashTab === "metodologia-probabilidades";
    const abrirMetodologia = hashTab === "metodologia-ranking";
    if (openProbabilityMethod) state.tab = "probabilidades";
    else if (abrirMetodologia) state.tab = "desempenho";
    else if (["artilheiros", "jogos", "assistencias", "gols-clube", "campeonato", "probabilidades", "desempenho"].includes(hashTab)) state.tab = hashTab;

    const [leaders, competition, details, ranking, rankingHistory, table, results, audit, probabilities, probabilitiesAudit, probabilitiesHistory, probabilityModelsAudit, probabilityEvaluation, pointsThresholds] = await Promise.all([
      fetchJson(FILES.leaders, { status: "aguardando_workflow", artilharia: [], assistencias: [] }),
      fetchJson(FILES.competition, { resumo: {}, performance_por_partida: {}, sequencias: {}, publico: {}, gols_por_clube: [], jogos: [] }),
      fetchJson(FILES.details, { jogos: {} }),
      fetchJson(FILES.ranking, { ranking: [] }),
      fetchJson(FILES.rankingHistory, { total_snapshots: 0, snapshots: [] }),
      fetchJson(FILES.table, { tabela: [] }),
      fetchJson(FILES.results, { resultados: [] }),
      fetchJson(FILES.audit, { status: "aguardando_workflow" }),
      fetchJson(FILES.probabilities, { status: "aguardando_workflow", clubes: [], partidas_restantes: [] }),
      fetchJson(FILES.probabilitiesAudit, { status: "aguardando_workflow" }),
      fetchJson(FILES.probabilitiesHistory, { total_snapshots: 0, snapshots: [] }),
      fetchJson(FILES.probabilityModelsAudit, { status: "aguardando_workflow" }),
      fetchJson(FILES.probabilityEvaluation, { status: "aguardando_primeira_execucao", publicar_na_interface: false }),
      fetchJson(FILES.pointsThresholds, { status: "aguardando_workflow", niveis: [] }),
    ]);

    state.leaders = leaders;
    state.competition = competition;
    state.details = details;
    state.ranking = ranking;
    state.rankingHistory = rankingHistory;
    state.table = table;
    state.results = results;
    state.audit = audit;
    state.probabilities = probabilities;
    state.probabilitiesAudit = probabilitiesAudit;
    state.probabilitiesHistory = probabilitiesHistory;
    state.probabilityModelsAudit = probabilityModelsAudit;
    state.probabilityEvaluation = probabilityEvaluation;
    state.pointsThresholds = pointsThresholds;
    renderAll();
    if (openProbabilityMethod) {
      requestAnimationFrame(() => $("metodologia-probabilidades")?.scrollIntoView({ behavior: "auto", block: "start" }));
    }
    if (abrirMetodologia) requestAnimationFrame(() => document.getElementById("metodologia-ranking")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  document.addEventListener("DOMContentLoaded", load);
})();

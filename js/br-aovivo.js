(function () {
  "use strict";

  const SCOREBOARD_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard";
  const SUMMARY_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary";
  const REFRESH_MS = 30000;
  const TZ = "America/Sao_Paulo";

  const $ = (sel) => document.querySelector(sel);
  const app = $("#live-app");
  const switcher = $("#live-switcher");
  const badge = $("#live-update-badge");
  const alertBox = $("#live-alert");

  const CLUBES = {
    "athletico pr": "Athletico-PR", "athletico paranaense": "Athletico-PR", "atletico paranaense": "Athletico-PR",
    "atletico mg": "Atlético-MG", "atletico mineiro": "Atlético-MG", "clube atletico mineiro": "Atlético-MG",
    "bahia": "Bahia", "ec bahia": "Bahia", "esporte clube bahia": "Bahia",
    "botafogo": "Botafogo", "botafogo rj": "Botafogo", "botafogo de futebol e regatas": "Botafogo",
    "bragantino": "Bragantino", "rb bragantino": "Bragantino", "red bull bragantino": "Bragantino",
    "chapecoense": "Chapecoense", "associacao chapecoense de futebol": "Chapecoense",
    "corinthians": "Corinthians", "sc corinthians paulista": "Corinthians", "corinthians paulista": "Corinthians",
    "coritiba": "Coritiba", "coritiba fc": "Coritiba",
    "cruzeiro": "Cruzeiro", "cruzeiro ec": "Cruzeiro",
    "flamengo": "Flamengo", "cr flamengo": "Flamengo",
    "fluminense": "Fluminense", "fluminense fc": "Fluminense",
    "gremio": "Grêmio", "gremio fbpa": "Grêmio",
    "internacional": "Internacional", "sc internacional": "Internacional",
    "mirassol": "Mirassol", "mirassol fc": "Mirassol",
    "palmeiras": "Palmeiras", "se palmeiras": "Palmeiras",
    "remo": "Remo", "clube do remo": "Remo",
    "santos": "Santos", "santos fc": "Santos",
    "sao paulo": "São Paulo", "sao paulo fc": "São Paulo",
    "vasco": "Vasco da Gama", "vasco da gama": "Vasco da Gama", "cr vasco da gama": "Vasco da Gama",
    "vitoria": "Vitória", "ec vitoria": "Vitória"
  };

  const SIGLAS = {
    "Athletico-PR": "CAP", "Atlético-MG": "CAM", "Bahia": "BAH", "Botafogo": "BOT",
    "Bragantino": "RBB", "Chapecoense": "CHA", "Corinthians": "COR", "Coritiba": "CFC",
    "Cruzeiro": "CRU", "Flamengo": "FLA", "Fluminense": "FLU", "Grêmio": "GRE",
    "Internacional": "INT", "Mirassol": "MIR", "Palmeiras": "PAL", "Remo": "REM",
    "Santos": "SAN", "São Paulo": "SAO", "Vasco da Gama": "VAS", "Vitória": "VIT"
  };

  const PROVIDERS = {
    premiere: {
      label: "Premiere",
      aliases: ["premiere"],
      links: [
        { label: "Premiere", url: "https://globoplay.globo.com/categorias/premiere/" },
        { label: "Claro tv+", url: "https://www.clarotvmais.com.br/ao-vivo" },
        { label: "Prime Video", url: "https://www.primevideo.com" }
      ]
    },
    sportv: {
      label: "SporTV",
      aliases: ["sportv", "sport tv"],
      links: [
        { label: "Globoplay", url: "https://globoplay.globo.com/" },
        { label: "Claro tv+", url: "https://www.clarotvmais.com.br/ao-vivo" }
      ]
    },
    disney: {
      label: "Disney+ / ESPN",
      aliases: ["disney+", "disney plus", "espn"],
      links: [
        { label: "Disney+", url: "https://www.disneyplus.com/pt-br" }
      ]
    },
    prime: {
      label: "Prime Video",
      aliases: ["prime video", "amazon prime", "amazon prime video"],
      links: [
        { label: "Prime Video", url: "https://www.primevideo.com" }
      ]
    },
    globo: {
      label: "Globo",
      aliases: ["globo", "tv globo"],
      links: [
        { label: "Globoplay", url: "https://globoplay.globo.com/" }
      ]
    },
    record: {
      label: "Record",
      aliases: ["record", "record tv", "recordtv"],
      links: [
        { label: "Record", url: "https://record.r7.com/" }
      ]
    },
    getv: {
      label: "GE TV",
      aliases: ["ge tv", "getv"],
      links: [
        { label: "Canal GE TV", url: "https://www.youtube.com/@getv" }
      ]
    },
    cazetv: {
      label: "CazéTV",
      aliases: ["cazetv", "caze tv"],
      links: [
        { label: "Canal CazéTV", url: "https://www.youtube.com/@CazeTV" }
      ]
    }
  };

  const OFFICIAL_HOSTS = new Set([
    "globoplay.globo.com", "www.globoplay.globo.com",
    "clarotvmais.com.br", "www.clarotvmais.com.br",
    "claro.com.br", "www.claro.com.br",
    "primevideo.com", "www.primevideo.com",
    "disneyplus.com", "www.disneyplus.com",
    "record.r7.com", "www.record.r7.com", "r7.com", "www.r7.com",
    "youtube.com", "www.youtube.com"
  ]);

  const FINAL_CACHE_KEY = "br2026_finais_reais_v2";

  function cachedFinalTimes() {
    try {
      const parsed = JSON.parse(localStorage.getItem(FINAL_CACHE_KEY) || "{}");
      const now = Date.now();
      const out = {};
      for (const [key, value] of Object.entries(parsed || {})) {
        const ts = Number(value || 0);
        if (ts > 0 && now - ts <= 12 * 3600000) out[key] = ts;
      }
      return out;
    } catch (_) {
      return {};
    }
  }

  function saveFinalTimes() {
    try { localStorage.setItem(FINAL_CACHE_KEY, JSON.stringify(state.finalizadosEm || {})); } catch (_) {}
  }

  const state = {
    agenda: [],
    eventosLocais: [],
    calendario: [],
    diretos: [],
    transmissoes: {},
    transmissoesTv: {},
    selecionado: "",
    resumoPorId: {},
    ultimaAtualizacao: null,
    ultimaFalha: "",
    timer: null,
    tickTimer: null,
    carregando: false,
    primeiraCarga: true,
    finalizadosEm: cachedFinalTimes(),
    probabilidadesJogos: null
  };

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function norm(v) {
    return String(v || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
  }

  function canon(v) {
    const n = norm(v);
    if (!n) return "";
    if (CLUBES[n]) return CLUBES[n];
    for (const [k, nome] of Object.entries(CLUBES)) {
      if (n.includes(k) || k.includes(n)) return nome;
    }
    return String(v || "").trim();
  }

  function parseDate(v) {
    if (!v) return null;
    const s = String(v);
    const d = new Date(s.length <= 16 ? s + ":00-03:00" : s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function dateKey(d) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit"
    }).formatToParts(d);
    const obj = {};
    parts.forEach((p) => { if (p.type !== "literal") obj[p.type] = p.value; });
    return [obj.year, obj.month, obj.day].join("-");
  }

  function compactDate(d) {
    return dateKey(d).replace(/-/g, "");
  }

  function formatDateTime(d) {
    if (!d) return "Horário a definir";
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: TZ, weekday: "long", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(d).replace(/\s+às\s+/, ", ");
  }

  function formatShort(d) {
    if (!d) return "A definir";
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(d);
  }

  function formatClockTime(d) {
    return d ? new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(d) : "";
  }

  function teamKey(a, b) {
    return canon(a) + "|" + canon(b);
  }

  function localTeam(raw) {
    const t = raw || {};
    const nome = canon(t.nome || t.displayName || t.name || t.shortDisplayName || t.abbreviation);
    return {
      id: String(t.id || ""),
      nome: nome || String(t.displayName || t.name || "Time"),
      sigla: t.sigla || t.abbreviation || SIGLAS[nome] || "",
      escudo: t.escudo || (Array.isArray(t.logos) && t.logos[0] && t.logos[0].href) || t.logo || ""
    };
  }

  function localGamesFromJson(data) {
    return (data && Array.isArray(data.jogos) ? data.jogos : []).map((j) => ({
      id: String(j.event_id || ""),
      rodada: Number(j.rodada || 0),
      date: parseDate(j.data_iso),
      dataIso: j.data_iso || "",
      state: String(j.estado || "pre"),
      completed: String(j.estado || "") === "post",
      detail: j.status || "",
      clock: "",
      venue: j.estadio || "",
      transmissao: j.transmissao || "",
      adiado: j.adiado === true,
      dataDefinir: j.data_definir === true,
      finalizadoEm: parseDate(j.finalizado_em),
      home: { ...localTeam(j.mandante), score: j.placar_mandante },
      away: { ...localTeam(j.visitante), score: j.placar_visitante },
      raw: null,
      source: "local"
    }));
  }

  function getCompetition(ev) {
    return (ev && Array.isArray(ev.competitions) && ev.competitions[0]) || {};
  }

  function statusFromEvent(ev, comp) {
    return (comp && comp.status) || (ev && ev.status) || {};
  }

  function venueFromCompetition(comp) {
    const v = (comp && comp.venue) || {};
    const addr = v.address || {};
    const cidade = [addr.city, addr.state].filter(Boolean).join(", ");
    return [v.fullName || v.displayName || v.name || "", cidade].filter(Boolean).join(" · ");
  }

  function roundFromEvent(ev, comp) {
    const nodes = [ev, comp, ev && ev.week, comp && comp.week, comp && comp.round];
    for (const node of nodes) {
      if (!node || typeof node !== "object") continue;
      for (const k of ["number", "week", "round", "value"]) {
        const n = Number(node[k]);
        if (n >= 1 && n <= 38) return n;
      }
      for (const k of ["displayName", "name", "description", "text"]) {
        const m = String(node[k] || "").match(/(?:rodada|round|week|matchday)?\s*([1-3]?\d)\b/i);
        if (m && Number(m[1]) >= 1 && Number(m[1]) <= 38) return Number(m[1]);
      }
    }
    return 0;
  }

  function broadcastNames(ev, comp) {
    const out = [];
    const add = (value) => {
      if (Array.isArray(value)) return value.forEach(add);
      const name = String(value || "").trim();
      if (!name || out.some((x) => norm(x) === norm(name))) return;
      out.push(name);
    };
    const walk = (node) => {
      if (!node) return;
      if (Array.isArray(node)) return node.forEach(walk);
      if (typeof node !== "object") return;
      if (Array.isArray(node.names)) node.names.forEach(add);
      for (const key of ["name", "shortName", "displayName", "network", "callLetters"]) add(node[key]);
      if (node.media) walk(node.media);
    };
    [
      comp && comp.broadcasts,
      comp && comp.geoBroadcasts,
      ev && ev.broadcasts,
      ev && ev.geoBroadcasts
    ].forEach(walk);
    return out;
  }

  function normalizeEvent(ev) {
    const comp = getCompetition(ev);
    const competitors = comp.competitors || [];
    const h = competitors.find((c) => c.homeAway === "home") || competitors[0];
    const a = competitors.find((c) => c.homeAway === "away") || competitors[1];
    if (!h || !a) return null;
    const status = statusFromEvent(ev, comp);
    const type = status.type || {};
    const home = localTeam(h.team || {});
    const away = localTeam(a.team || {});
    home.score = h.score == null || h.score === "" ? null : Number(h.score);
    away.score = a.score == null || a.score === "" ? null : Number(a.score);
    const date = parseDate(ev.date || comp.date);
    const completed = type.completed === true;
    const detail = type.shortDetail || type.detail || status.displayClock || (status.type && status.type.detail) || "";
    const interrupted = /postpon|adiad|suspend|cancel/i.test([type.name, type.description, type.detail, type.shortDetail].join(" "));
    let safeState = String(type.state || (completed ? "post" : "pre")).toLowerCase();
    // A ESPN eventualmente devolve state=post/completed=false para evento futuro.
    // Um jogo futuro não pode entrar como encerrado; preservamos a data e tratamos
    // o evento como pré-jogo (ou como adiado, quando o texto assim indicar).
    if (safeState === "post" && !completed && date && date.getTime() > Date.now() + 15 * 60000) {
      safeState = "pre";
    }
    return {
      id: String(ev.id || comp.id || ""),
      rodada: roundFromEvent(ev, comp),
      date,
      dataIso: date ? date.toISOString() : "",
      state: safeState,
      completed,
      detail,
      clock: status.displayClock || "",
      period: Number(status.period || comp.period || 0),
      venue: venueFromCompetition(comp),
      transmissao: broadcastNames(ev, comp).join(" / "),
      adiado: interrupted,
      dataDefinir: false,
      finalizadoEm: parseDate(ev.finalizado_em || ev.finalizedAt || ev.completedAt),
      home,
      away,
      raw: ev,
      competition: comp,
      source: "espn"
    };
  }

  function findLocal(game) {
    if (!game) return null;
    if (game.id) {
      const byId = state.agenda.find((x) => x.id && x.id === game.id);
      if (byId) return byId;
    }
    const key = teamKey(game.home.nome, game.away.nome);
    return state.agenda.find((x) => teamKey(x.home.nome, x.away.nome) === key) || null;
  }

  function findCalendar(game) {
    if (!game || !game.home || !game.away) return null;
    if (game.id) {
      const byId = state.calendario.find((x) => String(x && x.event_id || '') === String(game.id));
      if (byId) return byId;
    }
    const key = teamKey(game.home.nome, game.away.nome);
    return state.calendario.find((x) => teamKey(x && x.mandante, x && x.visitante) === key) || null;
  }

  function calendarAsLocal(game) {
    const item = findCalendar(game);
    if (!item) return null;
    return {
      id: String(item.event_id || ''),
      rodada: Number(item.rodada || 0),
      date: item.data_definir === true ? null : parseDate(item.data_iso),
      dataIso: item.data_definir === true ? '' : String(item.data_iso || ''),
      state: String(item.estado || 'pre'),
      completed: item.concluido === true,
      detail: item.status || '',
      clock: '',
      venue: item.estadio || '',
      transmissao: '',
      adiado: item.adiado === true,
      dataDefinir: item.data_definir === true,
      finalizadoEm: null,
      home: localTeam({ nome: item.mandante }),
      away: localTeam({ nome: item.visitante }),
      raw: null,
      source: 'calendar'
    };
  }

  function mergeLocal(game) {
    const loc = findLocal(game) || calendarAsLocal(game);
    if (!loc) return game;
    return {
      ...loc,
      ...game,
      rodada: loc.rodada || game.rodada,
      date: game.date || loc.date,
      dataIso: game.dataIso || loc.dataIso,
      venue: game.venue || loc.venue,
      transmissao: loc.transmissao || game.transmissao,
      // HOTFIX_REAGENDADOS_20260902: snapshot historicamente adiado não
      // contamina um evento ESPN atual que já voltou a ter kickoff ativo.
      adiado: game.adiado === true || (!game.date && loc.adiado === true),
      finalizadoEm: game.finalizadoEm || loc.finalizadoEm || null,
      home: { ...loc.home, ...game.home, nome: loc.home.nome || game.home.nome, escudo: loc.home.escudo || game.home.escudo },
      away: { ...loc.away, ...game.away, nome: loc.away.nome || game.away.nome, escudo: loc.away.escudo || game.away.escudo }
    };
  }

  async function fetchJson(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function safeYouTubeUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.href);
      const host = url.hostname.toLowerCase();
      if (host !== "youtube.com" && host !== "www.youtube.com" && host !== "youtu.be") return "";
      if (host === "youtu.be") return /^[A-Za-z0-9_-]{11}$/.test(url.pathname.replace(/^\//, "")) ? url.href : "";
      const id = url.searchParams.get("v");
      return /^[A-Za-z0-9_-]{11}$/.test(id || "") ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  // ===== Modal de embed YouTube (player incorporado) =====
  // Toca a transmissão dentro do próprio site. Fallback: se o canal bloquear
  // a incorporação, o rodapé oferece link direto "Abrir no YouTube ↗".
  function extrairVideoIdYoutube(valor) {
    const direto = String(valor || "").trim();
    if (/^[A-Za-z0-9_-]{11}$/.test(direto)) return direto;
    try {
      const u = new URL(direto, window.location.href);
      const host = u.hostname.toLowerCase().replace(/^www\./, "");
      let id = "";
      if (host === "youtu.be") id = u.pathname.split("/").filter(Boolean)[0] || "";
      else if (host.endsWith("youtube.com")) {
        id = u.searchParams.get("v") || "";
        if (!id && /^\/(?:embed|shorts|live)\//.test(u.pathname)) id = u.pathname.split("/")[2] || "";
      }
      return /^[A-Za-z0-9_-]{11}$/.test(id) ? id : "";
    } catch (_) {
      return "";
    }
  }

  let mmModalOverflowAnterior = "";
  let mmModalResizeHandler = null;

  function ajustarModalTransmissaoDesktop() {
    const modal = document.getElementById("mm-modal-player");
    if (!modal || !window.matchMedia("(min-width: 641px)").matches) return;
    const card = modal.querySelector(".mm-modal-card");
    const header = modal.querySelector(".mm-modal-header");
    const footer = modal.querySelector(".mm-modal-footer");
    if (!card || !header || !footer) return;
    const margemModal = 36;
    card.style.width = Math.min(960, Math.max(0, window.innerWidth - margemModal)) + "px";
    for (let tentativa = 0; tentativa < 3; tentativa += 1) {
      const alturaFixa = header.getBoundingClientRect().height + footer.getBoundingClientRect().height + 2;
      const alturaDisponivelVideo = Math.max(0, window.innerHeight - margemModal - alturaFixa);
      const larguraPelaAltura = (alturaDisponivelVideo * 16 / 9) + 2;
      card.style.width = Math.floor(Math.min(960, window.innerWidth - margemModal, larguraPelaAltura)) + "px";
    }
  }

  function fecharModalTransmissao() {
    const modal = document.getElementById("mm-modal-player");
    if (!modal) return;
    const iframe = modal.querySelector("iframe");
    if (iframe) iframe.src = "about:blank";
    modal.remove();
    if (mmModalResizeHandler) window.removeEventListener("resize", mmModalResizeHandler);
    mmModalResizeHandler = null;
    document.body.style.overflow = mmModalOverflowAnterior;
    document.removeEventListener("keydown", teclaModalTransmissao);
  }

  function teclaModalTransmissao(evento) {
    if (evento.key === "Escape") fecharModalTransmissao();
  }

  function abrirModalTransmissao(videoIdOuUrl, titulo, urlOriginal, fonte) {
    const id = extrairVideoIdYoutube(videoIdOuUrl || urlOriginal);
    if (!id) {
      if (urlOriginal) window.open(urlOriginal, "_blank", "noopener,noreferrer");
      return;
    }
    fecharModalTransmissao();
    const urlYoutube = urlOriginal || "https://www.youtube.com/watch?v=" + encodeURIComponent(id);
    const modal = document.createElement("div");
    modal.id = "mm-modal-player";
    modal.className = "mm-modal-backdrop";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", titulo || "Transmissão ao vivo");
    modal.innerHTML =
      '<section class="mm-modal-card">' +
        '<header class="mm-modal-header">' +
          '<strong>' + esc(titulo || "Transmissão ao vivo") + '</strong>' +
          '<button type="button" class="mm-modal-close" aria-label="Fechar vídeo">×</button>' +
        '</header>' +
        '<div class="mm-modal-frame">' +
          '<iframe src="https://www.youtube-nocookie.com/embed/' + encodeURIComponent(id) + '?autoplay=1&rel=0&playsinline=1" ' +
            'title="' + esc(titulo || "Transmissão ao vivo") + '" loading="eager" ' +
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" ' +
            'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>' +
        '</div>' +
        '<footer class="mm-modal-footer">' +
          '<span>' + esc(fonte || "Transmissão publicada no YouTube") + '. Caso o canal bloqueie a incorporação, use o link oficial.</span>' +
          '<a href="' + esc(urlYoutube) + '" target="_blank" rel="noopener noreferrer">Abrir no YouTube ↗</a>' +
        '</footer>' +
      '</section>';
    modal.addEventListener("click", function (evento) {
      if (evento.target === modal || evento.target.classList.contains("mm-modal-close")) {
        fecharModalTransmissao();
      }
    });
    document.body.appendChild(modal);
    mmModalOverflowAnterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ajustarModalTransmissaoDesktop();
    mmModalResizeHandler = ajustarModalTransmissaoDesktop;
    window.addEventListener("resize", mmModalResizeHandler);
    document.addEventListener("keydown", teclaModalTransmissao);
    modal.querySelector(".mm-modal-close")?.focus();
  }
  // Exposta no window para ser chamada via onclick dos botões de transmissão.
  window.__brAovivoAbrirTransmissao = function (btn) {
    if (!btn) return;
    abrirModalTransmissao(
      btn.getAttribute("data-video-id") || "",
      btn.getAttribute("data-titulo") || "",
      btn.getAttribute("data-url") || "",
      btn.getAttribute("data-fonte") || ""
    );
  };

  function safeOfficialUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.href);
      if (url.protocol !== "https:" || !OFFICIAL_HOSTS.has(url.hostname.toLowerCase())) return "";
      return url.href;
    } catch (_) {
      return "";
    }
  }

  const TRANSMISSION_CACHE_YT = "br2026_transmissoes_youtube_v1";
  const TRANSMISSION_CACHE_TV = "br2026_transmissoes_tv_v1";

  function cachedTransmissionMap(key) {
    try {
      const raw = localStorage.getItem(key);
      const parsed = raw ? JSON.parse(raw) : null;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function saveTransmissionMap(key, value) {
    try {
      if (value && typeof value === "object" && Object.keys(value).length) {
        localStorage.setItem(key, JSON.stringify(value));
      }
    } catch (_) {}
  }

  async function loadTransmissions() {
    const previousYoutube = state.transmissoes && Object.keys(state.transmissoes).length
      ? state.transmissoes
      : cachedTransmissionMap(TRANSMISSION_CACHE_YT);
    const previousTv = state.transmissoesTv && Object.keys(state.transmissoesTv).length
      ? state.transmissoesTv
      : cachedTransmissionMap(TRANSMISSION_CACHE_TV);

    const [youtubeResult, manualResult, tvResult] = await Promise.allSettled([
      fetchJson("dados-br/transmissoes-aovivo.json?t=" + Date.now()),
      fetchJson("dados-br/transmissoes-aovivo-manual.json?t=" + Date.now()),
      fetchJson("dados-br/transmissoes-tv.json?t=" + Date.now())
    ]);

    const automatic = youtubeResult.status === "fulfilled" && youtubeResult.value && youtubeResult.value.jogos && typeof youtubeResult.value.jogos === "object"
      ? youtubeResult.value.jogos
      : {};
    const manual = manualResult.status === "fulfilled" && manualResult.value && manualResult.value.jogos && typeof manualResult.value.jogos === "object"
      ? manualResult.value.jogos
      : {};
    const tv = tvResult.status === "fulfilled" && tvResult.value && tvResult.value.jogos && typeof tvResult.value.jogos === "object"
      ? tvResult.value.jogos
      : {};

    // Nunca apaga um link válido por causa de uma falha transitória, 404 durante
    // deploy ou resposta vazia em um único ciclo. O manual prevalece sobre o robô.
    const mergedYoutube = Object.assign({}, previousYoutube, automatic, manual);
    state.transmissoes = Object.keys(mergedYoutube).length ? mergedYoutube : previousYoutube;
    state.transmissoesTv = Object.keys(tv).length ? Object.assign({}, previousTv, tv) : previousTv;
    saveTransmissionMap(TRANSMISSION_CACHE_YT, state.transmissoes);
    saveTransmissionMap(TRANSMISSION_CACHE_TV, state.transmissoesTv);
  }

  function transmissionEntryForGame(game, source) {
    if (!game || !source) return null;
    const direct = game.id && source[String(game.id)];
    if (direct) return direct;
    if (game.id) {
      const byEventId = Object.values(source).find((item) => item && String(item.event_id || "") === String(game.id));
      if (byEventId) return byEventId;
    }
    const wanted = teamKey(game.home && game.home.nome, game.away && game.away.nome);
    const gameDate = game.date ? dateKey(game.date) : "";
    for (const item of Object.values(source)) {
      if (!item || typeof item !== "object") continue;
      if (teamKey(item.mandante, item.visitante) !== wanted) continue;
      const itemDate = parseDate(item.data_iso);
      if (!gameDate || !itemDate || dateKey(itemDate) === gameDate) return item;
    }
    return null;
  }

  function transmissionForGame(game) {
    return transmissionEntryForGame(game, state.transmissoes);
  }

  function providerForChannel(channel) {
    const wanted = norm(channel);
    if (!wanted) return null;
    for (const [key, provider] of Object.entries(PROVIDERS)) {
      if (provider.aliases.some((alias) => wanted.includes(norm(alias)) || norm(alias).includes(wanted))) {
        return { key, ...provider };
      }
    }
    return null;
  }

  function channelsFromText(value) {
    const text = String(value || "").trim();
    if (!text) return [];
    const found = [];
    for (const provider of Object.values(PROVIDERS)) {
      if (provider.aliases.some((alias) => norm(text).includes(norm(alias)))) found.push(provider.label);
    }
    if (found.length) return Array.from(new Set(found));
    return Array.from(new Set(text.split(/\s*(?:\/|,|;|\be\b)\s*/i).map((x) => x.trim()).filter(Boolean)));
  }

  function closedTransmissionForGame(game) {
    const manual = transmissionEntryForGame(game, state.transmissoesTv);
    if (manual) return manual;
    const canais = channelsFromText(game && game.transmissao);
    return canais.length ? { canais, origem: "ESPN" } : null;
  }

  function transmissionLabel(game) {
    const yt = transmissionForGame(game);
    const principal = yt && yt.principal;
    if (principal && safeYouTubeUrl(principal.url)) return principal.nome || (principal.fonte === "cazetv" ? "CazéTV" : "GE TV");
    const closed = closedTransmissionForGame(game);
    const canais = closed && Array.isArray(closed.canais) ? closed.canais.filter(Boolean) : [];
    return canais.join(" / ");
  }

  function renderClosedTransmission(game) {
    const entry = closedTransmissionForGame(game);
    if (!entry) return "";
    const canais = Array.isArray(entry.canais) ? entry.canais.filter(Boolean) : [];
    if (!canais.length) return "";

    const links = [];
    const seen = new Set();
    const addLink = (label, value) => {
      const url = safeOfficialUrl(value);
      const key = norm(label) + "|" + url;
      if (!url || seen.has(key) || links.length >= 3) return;
      seen.add(key);
      links.push({ label: String(label || "Acessar"), url });
    };

    for (const item of (Array.isArray(entry.links) ? entry.links : [])) addLink(item.label, item.url);
    for (const canal of canais) {
      const provider = providerForChannel(canal);
      for (const item of ((provider && provider.links) || [])) addLink(item.label, item.url);
    }

    const buttons = links.length
      ? '<div class="live-provider-actions">' + links.map((item) => '<a class="live-provider-button" href="' + esc(item.url) + '" target="_blank" rel="noopener noreferrer">' + esc(item.label) + '</a>').join("") + '</div>'
      : '<div class="live-provider-no-link">Consulte o aplicativo ou a operadora da sua assinatura.</div>';

    return '<aside class="live-provider-card" aria-label="Onde assistir"><div class="live-provider-heading"><span class="live-provider-icon">📺</span><div><span class="live-provider-kicker">Onde assistir</span><strong>' + esc(canais.join(" / ")) + '</strong></div></div>' +
      '<p>Acesso sujeito à assinatura do serviço escolhido.</p>' + buttons + '</aside>';
  }

  function renderTransmission(game) {
    const entry = transmissionForGame(game);
    const principal = entry && entry.principal;
    const url = principal && safeYouTubeUrl(principal.url);
    let youtube = "";
    if (url) {
      const sourceName = principal.nome || (principal.fonte === "cazetv" ? "CazéTV" : "GE TV");
      const liveNow = String(principal.status || "").toLowerCase() === "live" || game.state === "in";
      const kickoff = game.date instanceof Date ? game.date.getTime() : NaN;
      const preLive = !liveNow && isFinite(kickoff) && Date.now() >= kickoff - 60 * 60000;
      const liveStyle = liveNow || preLive;
      const finished = game.state === "post";
      const label = finished
        ? "▶ Rever na " + sourceName
        : (liveNow ? "AO VIVO na " + sourceName : (preLive ? "AO VIVO em breve na " + sourceName : "▶ Assistir na " + sourceName));
      const note = finished
        ? "Transmissão oficial encerrada no YouTube"
        : (liveNow ? "Transmissão oficial ao vivo no YouTube" : (preLive ? "A bola rola em breve — transmissão oficial no YouTube" : "Transmissão oficial programada no YouTube"));
      const homeName = (game.home && game.home.nome) || "";
      const awayName = (game.away && game.away.nome) || "";
      const tituloModal = (finished ? "Reprise: " : "Transmissão: ") + homeName + " x " + awayName;
      const fonteModal = "Transmissão oficial " + sourceName;
      const btnAttrs =
        ' data-url="' + esc(url) + '"' +
        ' data-video-id="' + esc(principal.video_id || "") + '"' +
        ' data-titulo="' + esc(tituloModal) + '"' +
        ' data-fonte="' + esc(fonteModal) + '"';
      // Botão abre o vídeo dentro do próprio site (modal com iframe embed).
      // Se o canal bloquear a incorporação, o rodapé do modal oferece link
      // direto para o YouTube — abertura direta no YouTube.
      youtube = '<div class="live-stream-area"><button type="button" class="live-stream-button ' + (liveStyle ? "is-live" : "") + '" onclick="window.__brAovivoAbrirTransmissao(this)"' + btnAttrs + '>' + esc(label) + '</button><div class="live-stream-note">' + esc(note) + '</div></div>';
    }
    return youtube + renderClosedTransmission(game);
  }

  async function loadProbabilityDataset() {
    // Fonte canônica da Execução 1: contém V/E/D e taxas de gols por partida.
    const primary = await fetchJson("dados-br/probabilidades-jogos.json?t=" + Date.now()).catch(() => null);
    if (primary && primary.status === "ok" && Array.isArray(primary.jogos)) return primary;

    // Fallback operacional: evita perder a informação durante uma publicação
    // parcial, usando o arquivo geral do AF-Previsão no mesmo formato básico.
    const fallback = await fetchJson("dados-br/probabilidades-brasileirao.json?t=" + Date.now()).catch(() => null);
    if (fallback && Array.isArray(fallback.partidas_restantes)) {
      return { status: "ok", jogos: fallback.partidas_restantes };
    }
    return null;
  }

  async function loadLocal() {
    const [jogos, eventos, calendario, probabilidades] = await Promise.all([
      fetchJson("jogos.json?t=" + Date.now()),
      fetchJson("espn_eventos.json?t=" + Date.now()).catch(() => ({ eventos: [] })),
      fetchJson("dados-br/calendario-completo.json?t=" + Date.now()).catch(() => ({ jogos: [] })),
      loadProbabilityDataset()
    ]);
    state.agenda = localGamesFromJson(jogos).filter((g) => !g.dataDefinir && g.date);
    state.eventosLocais = (eventos.eventos || []).slice();
    state.calendario = (calendario.jogos || []).slice();
    state.probabilidadesJogos = probabilidades;
    for (const item of state.eventosLocais) {
      const key = String(item && item.event_id || "");
      const finalizado = parseDate(item && item.finalizado_em);
      if (key && finalizado) state.finalizadosEm[key] = finalizado.getTime();
    }
    saveFinalTimes();
  }

  function finalizadoLocalParaJogo(game) {
    if (!game) return 0;
    const direct = state.eventosLocais.find((item) => String(item && item.event_id || "") === String(game.id || ""));
    if (direct) {
      const parsed = parseDate(direct.finalizado_em);
      if (parsed) return parsed.getTime();
    }
    return game.finalizadoEm instanceof Date ? game.finalizadoEm.getTime() : 0;
  }

  function estimarFinalizadoEm(game, now) {
    const inicio = game && game.date instanceof Date ? game.date.getTime() : NaN;
    if (!Number.isFinite(inicio)) return now;
    const raw = String((game && (game.detail || game.clock)) || "");
    const m = raw.match(/(\d{1,3})\s*['’]?\s*(?:\+\s*(\d+))?/);
    const duracaoMin = m
      ? Math.max(90, Number(m[1] || 90)) + Number(m[2] || 0) + 18
      : 115;
    // Tempo jogado + intervalo + pequena margem operacional. É estável entre
    // reloads e impede que um deploy dê nova sobrevida a uma partida antiga.
    return Math.min(now, inicio + duracaoMin * 60000);
  }

  async function loadScoreboard() {
    const now = new Date();
    const ini = compactDate(new Date(now.getTime() - 24 * 3600 * 1000));
    const fim = compactDate(new Date(now.getTime() + 2 * 24 * 3600 * 1000));
    const url = SCOREBOARD_API + "?dates=" + ini + "-" + fim + "&limit=80&_=" + Date.now();
    const data = await fetchJson(url);
    const normalized = (data.events || []).map(normalizeEvent).filter(Boolean).map(mergeLocal);
    const seen = new Set();
    for (const game of normalized) {
      const key = String(game.id || teamKey(game.home && game.home.nome, game.away && game.away.nome));
      if (!key) continue;
      seen.add(key);
      if (gameReallyFinished(game)) {
        const stable = finalizadoLocalParaJogo(game);
        if (stable > 0) state.finalizadosEm[key] = stable;
        else if (!state.finalizadosEm[key]) state.finalizadosEm[key] = estimarFinalizadoEm(game, Date.now());
      } else {
        delete state.finalizadosEm[key];
      }
    }
    for (const key of Object.keys(state.finalizadosEm)) {
      if (Date.now() - state.finalizadosEm[key] > 12 * 3600000) delete state.finalizadosEm[key];
    }
    saveFinalTimes();
    state.diretos = normalized;
  }

  function sameFixture(a, b) {
    if (!a || !b || !a.home || !a.away || !b.home || !b.away) return false;
    if (a.id && b.id && String(a.id) === String(b.id)) return true;
    if (teamKey(a.home.nome, a.away.nome) !== teamKey(b.home.nome, b.away.nome)) return false;

    // A ESPN e a agenda local podem usar IDs diferentes para o mesmo jogo,
    // especialmente em partidas adiadas/remarcadas. Nesses casos, a combinação
    // clubes + data/rodada é a identidade mais confiável.
    if (a.date instanceof Date && b.date instanceof Date) {
      const diff = Math.abs(a.date.getTime() - b.date.getTime());
      if (dateKey(a.date) === dateKey(b.date) || diff <= 12 * 3600000) return true;
    }
    if (a.rodada && b.rodada && Number(a.rodada) === Number(b.rodada)) return true;
    return false;
  }

  function mergeGameRecords(a, b) {
    const espn = a && a.source === "espn" ? a : (b && b.source === "espn" ? b : null);
    const primary = espn || b || a;
    const secondary = primary === a ? b : a;
    if (!secondary) return primary;

    return {
      ...secondary,
      ...primary,
      id: primary.id || secondary.id,
      rodada: primary.rodada || secondary.rodada,
      date: primary.date || secondary.date,
      dataIso: primary.dataIso || secondary.dataIso,
      detail: primary.detail || secondary.detail,
      clock: primary.clock || secondary.clock,
      venue: primary.venue || secondary.venue,
      transmissao: primary.transmissao || secondary.transmissao,
      finalizadoEm: primary.finalizadoEm || secondary.finalizadoEm || null,
      home: { ...secondary.home, ...primary.home, escudo: primary.home.escudo || secondary.home.escudo },
      away: { ...secondary.away, ...primary.away, escudo: primary.away.escudo || secondary.away.escudo }
    };
  }

  function allGames() {
    const merged = [];
    const upsert = (game) => {
      if (!game || !game.home || !game.away) return;
      const index = merged.findIndex((item) => sameFixture(item, game));
      if (index < 0) merged.push(game);
      else merged[index] = mergeGameRecords(merged[index], game);
    };

    state.agenda.forEach(upsert);
    state.diretos.forEach((g) => upsert(mergeLocal(g)));
    return merged;
  }

  function isPostponed(g) {
    return Boolean(g && g.adiado) && (!g.date || /adiad|postpon|suspend|cancel|data a definir/i.test(g.detail || ""));
  }

  function gameReallyFinished(g, reference) {
    if (!g || isPostponed(g)) return false;
    const now = Number(reference || Date.now());
    const kickoff = g.date instanceof Date ? g.date.getTime() : NaN;
    if (!Number.isFinite(kickoff) || kickoff > now - 90 * 60000) return false;
    const hs = Number(g.home && g.home.score), as = Number(g.away && g.away.score);
    if (!Number.isFinite(hs) || !Number.isFinite(as)) return false;
    return g.completed === true || g.state === "post";
  }

  function priorityGames(games) {
    const now = Date.now();
    const live = games.filter((g) => g.state === "in").sort((a, b) => (a.date || 0) - (b.date || 0));
    if (live.length) return live;

    // Mantém jogos encerrados em destaque por quinze minutos contados da
    // primeira resposta em que a ESPN os marcou como post/finalizados.
    const recent = games.filter((g) => {
      if (!gameReallyFinished(g, now)) return false;
      const key = String(g.id || teamKey(g.home && g.home.nome, g.away && g.away.nome));
      const endedAt = Number(state.finalizadosEm[key] || 0);
      return endedAt > 0 && now - endedAt <= 15 * 60000;
    }).sort((a, b) => {
      const ka = String(a.id || teamKey(a.home && a.home.nome, a.away && a.away.nome));
      const kb = String(b.id || teamKey(b.home && b.home.nome, b.away && b.away.nome));
      return Number(state.finalizadosEm[kb] || 0) - Number(state.finalizadosEm[ka] || 0);
    });
    const future = games.filter((g) => g.state !== "post" && !isPostponed(g) && g.date && g.date.getTime() >= now - 30 * 60000)
      .sort((a, b) => a.date - b.date);

    if (recent.length) {
      const latestKey = String(recent[0].id || teamKey(recent[0].home.nome, recent[0].away.nome));
      const latest = Number(state.finalizadosEm[latestKey] || 0);
      return recent.filter((g) => {
        const key = String(g.id || teamKey(g.home.nome, g.away.nome));
        return Math.abs(Number(state.finalizadosEm[key] || 0) - latest) <= 2 * 60000;
      }).slice(0, 8);
    }
    if (future.length) {
      const first = future[0].date.getTime();
      return future.filter((g) => Math.abs(g.date.getTime() - first) <= 2 * 60000).slice(0, 8);
    }
    return [];
  }

  function chooseGame(games) {
    const priorities = priorityGames(games);
    // A seleção principal deve vir SOMENTE dos jogos prioritários: ao vivo,
    // encerrados há no máximo 15 minutos ou próximos jogos. O fallback antigo
    // usava todos os jogos — inclusive encerrados — e fazia uma partida finalizada
    // reaparecer indefinidamente depois que a janela pós-jogo expirava.
    const eligible = priorities;
    let selected = eligible.find((g) => g.id && g.id === state.selecionado);
    if (!selected) selected = eligible[0] || null;
    if (selected && selected.id) state.selecionado = selected.id;
    else state.selecionado = null;
    return { selected, priorities };
  }

  function clubHref(name) {
    const canonical = canon(name) || String(name || "").trim();
    const clubSlug = norm(canonical).replace(/\s+/g, "-");
    return "clubes.html#" + encodeURIComponent(clubSlug);
  }

  function teamLink(team, inner) {
    return '<a class="live-team-link" href="' + esc(clubHref(team.nome)) + '" aria-label="Abrir página de ' + esc(team.nome) + '">' + inner + '</a>';
  }

  function teamLogo(team) {
    const fallback = "img/escudo-neutro.svg";
    const src = String(team && team.escudo || "");
    return '<img class="' + (src ? '' : 'is-neutral-shield') + '" src="' + esc(src || fallback) + '" alt="" loading="eager" onerror="this.onerror=null; this.src=\'img/escudo-neutro.svg\'; this.classList.add(\'is-neutral-shield\')">';
  }

  function clockMinute(g) {
    const raw = String((g && (g.clock || g.detail)) || "").trim();
    const match = raw.match(/^(\d{1,3})(?::\d{2})?(?:\+\d+)?(?:['’])?$/);
    return match ? Number(match[1]) : NaN;
  }

  // Detecta intervalo APENAS quando a ESPN confirma isso pelo shortDetail
  // ("HT"/"Halftime"/"Intervalo"), que é o campo canônico. STATUS_HALFTIME no
  // type.name só é aceito quando o shortDetail é vazio/genérico — assim um
  // STATUS_HALFTIME residual da ESPN não sobrescreve um minuto de jogo válido.
  function isHalftime(statusType, shortDetail) {
    const sd = String(shortDetail || "").trim();
    if (/^HT$/i.test(sd)) return true;
    if (/^half\s*time$/i.test(sd)) return true;
    if (/^intervalo$/i.test(sd)) return true;
    const name = String((statusType && statusType.name) || "").toUpperCase();
    if (name === "STATUS_HALFTIME") {
      // Aceita STATUS_HALFTIME só se o shortDetail não indica jogo rolando.
      // Se o shortDetail tem um minuto ("30'", "45+2'"), o jogo está andando.
      if (!sd) return true;
      if (/^\d+/.test(sd)) return false;
      return true;
    }
    return false;
  }

  // Detecta fim de jogo com precisão. type.completed é o sinal canônico da ESPN.
  function isFinished(g, statusType, shortDetail) {
    if (gameReallyFinished(g)) return true;
    // Nenhum rótulo textual da ESPN pode transformar evento futuro ou adiado
    // em jogo encerrado. A data mínima e o placar são validados acima.
    if (!g || isPostponed(g) || !(g.date instanceof Date) || g.date.getTime() > Date.now() - 90 * 60000) return false;
    const name = String((statusType && statusType.name) || "").toUpperCase();
    if (name === "STATUS_FULL_TIME" || name === "STATUS_FINAL" || (name === "STATUS_END_OF_PERIOD" && g.state === "post")) return true;
    const sd = String(shortDetail || "").trim();
    if (/^FT$/i.test(sd)) return true;
    if (/^full\s*time$/i.test(sd)) return true;
    return false;
  }

  function gameState(g) {
    const statusType = g && g.raw && g.raw.status && g.raw.status.type;
    const shortDetail = statusType && statusType.shortDetail;
    const text = [g && g.detail, statusType && statusType.name, statusType && statusType.description, statusType && statusType.detail, shortDetail].join(" ");
    if (/postpon|adiad/i.test(text)) return { key: "postponed", label: "Adiado" };
    if (/suspend/i.test(text)) return { key: "postponed", label: "Suspenso" };
    if (/cancel/i.test(text)) return { key: "postponed", label: "Cancelado" };
    // Fim de jogo tem prioridade sobre qualquer outra classificação.
    if (isFinished(g, statusType, shortDetail)) return { key: "post", label: "Encerrado" };
    if (g.state === "in") {
      if (isHalftime(statusType, shortDetail)) return { key: "live", label: "Intervalo" };
      return { key: "live", label: "Ao vivo" };
    }
    return { key: "pre", label: "Próximo jogo" };
  }

  // Igual ao Copa2026: confia no shortDetail da ESPN, que já entrega "30'",
  // "45+2'", "HT", "FT" prontos. g.detail = displayClock || shortDetail (ver
  // normalizeEvent), então já é a fonte certa para exibir.
  function statusText(g) {
    const s = gameState(g);
    if (s.key === "live") {
      if (s.label === "Intervalo") return "Intervalo";
      return g.detail || g.clock || "Ao vivo";
    }
    if (s.key === "post") return "Fim de jogo";
    if (s.key === "postponed") return s.label;
    return g.date ? formatDateTime(g.date) : "Horário a definir";
  }

  function probabilityRowForGame(game) {
    const data = state.probabilidadesJogos;
    const rows = data && Array.isArray(data.jogos) ? data.jogos : [];
    if (!game || !rows.length) return null;

    const id = String(game.id || "");
    let row = id ? rows.find((item) => String(item && item.event_id || "") === id) : null;
    if (!row) {
      const key = teamKey(game.home && game.home.nome, game.away && game.away.nome);
      const day = game.date instanceof Date ? dateKey(game.date) : "";
      row = rows.find((item) => {
        if (!item || teamKey(item.mandante, item.visitante) !== key) return false;
        const itemDate = parseDate(item.data_iso);
        const itemDay = itemDate ? dateKey(itemDate) : "";
        return !day || !itemDay || day === itemDay;
      }) || null;
    }
    return row;
  }

  function probabilityForGame(game) {
    const row = probabilityRowForGame(game);
    if (!row) return null;
    const display = row.exibicao || {};
    const values = row.probabilidades_exibicao_pct || row.probabilidades_pct || {};
    const text = (field) => {
      const ready = String(display[field] || "").trim();
      if (ready) return ready;
      const n = Number(values[field]);
      return Number.isFinite(n)
        ? n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%"
        : "";
    };
    const home = text("mandante");
    const draw = text("empate");
    const away = text("visitante");
    return home && draw && away ? { home, draw, away } : null;
  }

  function renderPregameProbability(game, mode) {
    const p = probabilityForGame(game);
    if (!p) return "";
    const home = String(game.home && game.home.nome || "Mandante");
    const away = String(game.away && game.away.nome || "Visitante");
    if (mode === "mobile") {
      return '<div class="live-prob-mobile" aria-label="Probabilidades pré-jogo: ' + esc(home) + ' ' + esc(p.home) + ', empate ' + esc(p.draw) + ', ' + esc(away) + ' ' + esc(p.away) + '">' +
        '<span><small>' + esc(home) + '</small><strong>' + esc(p.home) + '</strong></span>' +
        '<span class="draw"><small>Empate</small><strong>' + esc(p.draw) + '</strong></span>' +
        '<span><small>' + esc(away) + '</small><strong>' + esc(p.away) + '</strong></span></div>';
    }
    return {
      home: '<span class="live-prob-badge" title="Chance pré-jogo de vitória do ' + esc(home) + '"><small>Vitória</small><strong>' + esc(p.home) + '</strong></span>',
      draw: '<span class="live-prob-badge draw" title="Chance pré-jogo de empate"><small>Empate</small><strong>' + esc(p.draw) + '</strong></span>',
      away: '<span class="live-prob-badge" title="Chance pré-jogo de vitória do ' + esc(away) + '"><small>Vitória</small><strong>' + esc(p.away) + '</strong></span>'
    };
  }

  // ===== Probabilidade dinâmica (Poisson condicional) =====
  // Recalcula P(vitória mandante / empate / vitória visitante) DURANTE o jogo,
  // a partir de: placar atual, minutos restantes, taxas de gol pré-jogo do
  // modelo AF-Previsão, e expulsões. É estatística pura (não é odd/aposta).
  //
  // Fundamento: gols em futebol seguem Poisson. Os gols do RESTANTE do jogo
  // são independentes do que já aconteceu e têm média = taxa_por_minuto ×
  // minutos_restantes. Somando o placar atual às simulações do restante,
  // obtém-se a probabilidade de cada desfecho. Um placar de 4×0 aos 85' dá
  // ~100% para quem vence, exatamente como esperado.

  function contarVermelhos(g, summary) {
    try {
      const rows = eventRows(g, summary).filter(r => r.type && r.type.key === "red");
      let vh = 0, va = 0;
      const homeNome = norm((g.home && g.home.nome) || "");
      const awayNome = norm((g.away && g.away.nome) || "");
      for (const r of rows) {
        const t = norm(r.team || "");
        if (t && t === homeNome) vh++;
        else if (t && t === awayNome) va++;
      }
      if (g.home) g.home.vermelhos = vh;
      if (g.away) g.away.vermelhos = va;
    } catch (e) {
      if (g.home) g.home.vermelhos = g.home.vermelhos || 0;
      if (g.away) g.away.vermelhos = g.away.vermelhos || 0;
    }
  }

  function poissonPMF(k, lambda) {
    if (lambda <= 0) return k === 0 ? 1 : 0;
    // P(X=k) = e^-λ * λ^k / k!
    let p = Math.exp(-lambda);
    for (let i = 1; i <= k; i++) p *= lambda / i;
    return p;
  }

  function minutoAtual(g) {
    // Minuto decorrido; robusto a "45+2", intervalo e 2º tempo.
    const raw = String((g && (g.clock || g.detail)) || "").trim();
    const m = raw.match(/^(\d{1,3})(?:\+(\d+))?/);
    let base = m ? Number(m[1]) : NaN;
    const acr = m && m[2] ? Number(m[2]) : 0;
    if (!isFinite(base)) {
      // Sem relógio: usa o período (1=1ºT, 2=2ºT) como aproximação grosseira.
      if (g.period >= 2) return 60;
      if (g.period === 1) return 25;
      return 0;
    }
    // Enquanto o jogo está em curso NUNCA zeramos o tempo restante — mesmo
    // aos 90+7 o árbitro pode dar mais acréscimo. Limitamos em 89.5 para
    // preservar sempre >= 0.5 min de janela probabilística. Só quando a
    // partida vira "post" o placar decide de forma determinística.
    return Math.min(base + acr, 89.5);
  }

  function taxasAoVivo(g) {
    const row = probabilityRowForGame(g);
    const ge = row && row.gols_esperados;
    const home = Number(ge && ge.mandante);
    const away = Number(ge && ge.visitante);
    return home > 0 && away > 0 ? { home, away } : null;
  }

  // Distribuição de probabilidade do nº de gols restantes de um time (0..8),
  // com massa da cauda agregada no último índice.
  function distribuicaoGolsRestantes(lambda, maxGols) {
    const dist = [];
    let acumulado = 0;
    for (let k = 0; k < maxGols; k++) {
      const p = poissonPMF(k, lambda);
      dist.push(p);
      acumulado += p;
    }
    dist.push(Math.max(0, 1 - acumulado)); // cauda: >= maxGols
    return dist;
  }

  function probabilidadeDinamica(g) {
    const s = gameState(g);
    // Enquanto NÃO for pós-jogo, tratamos como partida em andamento e
    // aplicamos piso probabilístico. Se a partida for "post", o placar
    // atual decide.
    const emJogo = s.key === "live";
    if (s.key !== "live" && s.key !== "post") return null;
    const taxas = taxasAoVivo(g);
    if (!taxas) return null;

    const golsHome = Number(g.home && g.home.score);
    const golsAway = Number(g.away && g.away.score);
    if (!isFinite(golsHome) || !isFinite(golsAway)) return null;

    // Se o árbitro já apitou o fim, mostra o desfecho determinístico.
    if (!emJogo) {
      if (golsHome > golsAway) return { home: 100, empate: 0, away: 0, minuto: 90, restanteMin: 0 };
      if (golsHome < golsAway) return { home: 0, empate: 0, away: 100, minuto: 90, restanteMin: 0 };
      return { home: 0, empate: 100, away: 0, minuto: 90, restanteMin: 0 };
    }

    const DURACAO = 90;
    const minuto = minutoAtual(g);
    // Enquanto in-game, o restante nunca é zero (minutoAtual já limita em 89.5).
    // Mantém no mínimo 0.5 min de janela probabilística até o apito.
    const restanteMin = Math.max(0.5, DURACAO - minuto);
    const fracao = restanteMin / DURACAO;

    // Ajuste por expulsão: um time com um jogador a menos perde força
    // ofensiva e concede mais. Fatores conservadores da literatura.
    let fatorHome = 1, fatorAway = 1;
    const vermelhosHome = Number(g.home && g.home.vermelhos) || 0;
    const vermelhosAway = Number(g.away && g.away.vermelhos) || 0;
    if (vermelhosHome > 0) { fatorHome *= Math.pow(0.75, vermelhosHome); fatorAway *= Math.pow(1.15, vermelhosHome); }
    if (vermelhosAway > 0) { fatorAway *= Math.pow(0.75, vermelhosAway); fatorHome *= Math.pow(1.15, vermelhosAway); }

    // Taxa esperada de gols no tempo restante.
    const lambdaHome = taxas.home * fracao * fatorHome;
    const lambdaAway = taxas.away * fracao * fatorAway;

    const MAXG = 8;
    const distH = distribuicaoGolsRestantes(lambdaHome, MAXG);
    const distA = distribuicaoGolsRestantes(lambdaAway, MAXG);

    let pHome = 0, pEmpate = 0, pAway = 0;
    for (let gh = 0; gh <= MAXG; gh++) {
      for (let ga = 0; ga <= MAXG; ga++) {
        const prob = distH[gh] * distA[ga];
        const finalH = golsHome + gh;
        const finalA = golsAway + ga;
        if (finalH > finalA) pHome += prob;
        else if (finalH < finalA) pAway += prob;
        else pEmpate += prob;
      }
    }
    const total = pHome + pEmpate + pAway || 1;
    let home = (pHome / total) * 100;
    let empate = (pEmpate / total) * 100;
    let away = (pAway / total) * 100;

    // Piso "estatisticamente possível" enquanto o jogo não terminou.
    // Em futebol nada é impossível até o apito final: sempre há uma cauda
    // probabilística por menor que seja. 0,01% = 1 em 10 mil.
    const PISO = 0.01;
    const antes = [home, empate, away];
    const pisos = antes.map(v => Math.max(v, PISO));
    // Renormaliza mantendo soma = 100 e preservando as razões entre os
    // valores que ficaram acima do piso. Se todos precisaram do piso
    // (impossível na prática), distribui igualmente.
    const somaPisada = pisos.reduce((s, v) => s + v, 0);
    if (somaPisada > 0) {
      const escala = 100 / somaPisada;
      home = pisos[0] * escala;
      empate = pisos[1] * escala;
      away = pisos[2] * escala;
    }

    return { home, empate, away, minuto, restanteMin };
  }

  function percentuaisEmDecimos(values) {
    const raw = values.map((value) => Math.max(0, Number(value) || 0));
    const total = raw.reduce((sum, value) => sum + value, 0) || 1;
    const exact = raw.map((value) => value * 1000 / total);
    const tenths = exact.map((value) => Math.floor(value));
    let missing = 1000 - tenths.reduce((sum, value) => sum + value, 0);
    const order = exact.map((value, index) => ({ index, fraction: value - tenths[index] }))
      .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
    for (let i = 0; i < missing; i++) tenths[order[i % order.length].index] += 1;
    return tenths.map((value) => value / 10);
  }

  function renderProbabilidadeDinamica(g) {
    const pd = probabilidadeDinamica(g);
    if (!pd) return "";
    // Formatação inteligente: nas caudas (>=99 ou <=1) mostra 2 casas para
    // não perder informação (99,86% em vez de "100%"; 0,08% em vez de "0%").
    // No meio, 1 casa já basta e fica visualmente limpo.
    const fmt = (v) => {
      const casas = (v >= 99 || v <= 1) ? 2 : 1;
      return v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) + "%";
    };
    const homeNome = esc((g.home && g.home.nome) || "Mandante");
    const awayNome = esc((g.away && g.away.nome) || "Visitante");
    return '<div class="live-winprob" aria-label="Probabilidade dinâmica do resultado da partida">' +
      '<div class="live-winprob-title">Chance de resultado</div>' +
      '<div class="live-winprob-bar">' +
        '<span class="live-winprob-seg home" style="width:' + pd.home.toFixed(3) + '%"></span>' +
        '<span class="live-winprob-seg draw" style="width:' + pd.empate.toFixed(3) + '%"></span>' +
        '<span class="live-winprob-seg away" style="width:' + pd.away.toFixed(3) + '%"></span>' +
      '</div>' +
      '<div class="live-winprob-legend">' +
        '<span><strong>' + fmt(pd.home) + '</strong> ' + homeNome + '</span>' +
        '<span><strong>' + fmt(pd.empate) + '</strong> Empate</span>' +
        '<span><strong>' + fmt(pd.away) + '</strong> ' + awayNome + '</span>' +
      '</div>' +
      '<div class="live-winprob-note">Estimativa estatística do nosso modelo · não é aposta</div>' +
    '</div>';
  }

  function simpleMessage(g) {
    const s = gameState(g);
    if (s.key === "live") return "Bola rolando pelo Brasileirão!";
    if (s.key === "post") return "Fim de jogo no Brasileirão.";
    if (s.key === "postponed") return "A partida aguarda nova definição oficial.";
    if (!g.date) return "Data e horário ainda serão confirmados.";
    const diff = g.date.getTime() - Date.now();
    if (diff <= 20 * 60000 && diff > 0) return "Tá quase na hora. Prepare a torcida!";
    const today = dateKey(g.date) === dateKey(new Date());
    return today ? "Hoje tem Brasileirão!" : "Próximo compromisso do Brasileirão.";
  }

  function countdownText(g) {
    if (!g || !g.date || g.state === "in" || g.state === "post") return "";
    let diff = g.date.getTime() - Date.now();
    if (diff <= 0) return "Aguardando início oficial";
    const days = Math.floor(diff / 86400000); diff %= 86400000;
    const hours = Math.floor(diff / 3600000); diff %= 3600000;
    const mins = Math.floor(diff / 60000);
    const secs = Math.floor((diff % 60000) / 1000);
    if (days > 0) return "Começa em " + days + "d " + hours + "h " + mins + "min";
    if (hours > 0) return "Começa em " + hours + "h " + mins + "min";
    return "Começa em " + mins + "min " + String(secs).padStart(2, "0") + "s";
  }

  function teamIdMap(g) {
    const map = {};
    if (g.home.id) map[String(g.home.id)] = g.home;
    if (g.away.id) map[String(g.away.id)] = g.away;
    return map;
  }

  function eventType(obj) {
    const text = norm([
      obj && obj.type && (obj.type.text || obj.type.name || obj.type.description),
      obj && obj.text, obj && obj.description
    ].filter(Boolean).join(" "));
    if (obj && obj.scoringPlay === true || /\bgoal\b|\bgol\b/.test(text)) return { key: "goal", label: "Gol", icon: "⚽" };
    if (obj && obj.redCard === true || /red card|cartao vermelho|expuls/.test(text)) return { key: "red", label: "Cartão vermelho", icon: "🟥" };
    if (obj && obj.yellowCard === true || /yellow card|cartao amarelo/.test(text)) return { key: "yellow", label: "Cartão amarelo", icon: "🟨" };
    return null;
  }

  function eventMinute(obj) {
    return String((obj && obj.clock && obj.clock.displayValue) || (obj && obj.displayClock) || "").trim();
  }

  function compactPlayerName(raw) {
    let s = String(raw || "").trim().replace(/\s+/g, " ");
    if (!s) return "";
    // Remove sufixos geracionais e partículas que não ajudam no nome esportivo.
    const parts = s.split(" ").filter(Boolean);
    const suffixes = new Set(["junior", "júnior", "neto", "filho", "sobrinho", "ii", "iii", "iv"]);
    while (parts.length > 1 && suffixes.has(norm(parts[parts.length - 1]))) parts.pop();
    if (parts.length <= 2) return parts.join(" ");
    // Para nomes extensos, mantém o primeiro nome e o último sobrenome útil.
    const particles = new Set(["da", "de", "do", "das", "dos", "e"]);
    const genericSurnames = new Set(["silva", "santos", "souza", "sousa", "oliveira", "pereira", "costa", "lima", "alves", "rocha", "nascimento", "ferreira", "gomes", "ribeiro", "martins", "carvalho"]);
    let last = parts.length - 1;
    while (last > 1 && (particles.has(norm(parts[last])) || genericSurnames.has(norm(parts[last])))) last--;
    while (last > 1 && particles.has(norm(parts[last]))) last--;
    return parts[0] + " " + parts[last];
  }

  function rosterNameMap(summary) {
    const out = {};
    const add = (athlete) => {
      if (!athlete) return;
      const id = athlete.id != null ? String(athlete.id) : "";
      const short = athlete.shortName || athlete.displayName || athlete.fullName || athlete.name || "";
      if (id && short) out[id] = compactPlayerName(short);
    };
    for (const roster of ((summary && summary.rosters) || [])) {
      for (const entry of (roster.roster || roster.athletes || [])) add(entry.athlete || entry);
    }
    for (const team of (((summary || {}).boxscore || {}).players || [])) {
      for (const statGroup of (team.statistics || [])) {
        for (const athlete of (statGroup.athletes || [])) add(athlete.athlete || athlete);
      }
    }
    return out;
  }

  function eventAthlete(obj, summary) {
    const roster = rosterNameMap(summary);
    const involved = obj && obj.athletesInvolved;
    const athlete = Array.isArray(involved) && involved[0] ? involved[0] : (obj && obj.athlete) || null;
    if (!athlete) return "";
    const id = athlete.id != null ? String(athlete.id) : "";
    const raw = (id && roster[id]) || athlete.shortName || athlete.displayName || athlete.fullName || athlete.name || "";
    return compactPlayerName(raw);
  }

  function eventRows(g, summary) {
    const candidates = [];
    const comp = g.competition || getCompetition(g.raw || {});
    for (const d of (comp.details || [])) candidates.push(d);
    for (const d of ((summary && summary.scoringPlays) || [])) candidates.push(d);
    for (const p of ((summary && summary.plays) || [])) candidates.push(p);
    const teamMap = teamIdMap(g);
    const out = [];
    const seen = new Set();
    for (const item of candidates) {
      const type = eventType(item);
      if (!type) continue;
      const min = eventMinute(item);
      const athlete = eventAthlete(item, summary);
      const teamId = String((item.team && item.team.id) || item.teamId || "");
      const team = teamMap[teamId];
      const fallbackText = String(item.text || item.description || type.label);
      const text = athlete ? type.label + " — " + athlete : fallbackText;
      const identity = athlete ? norm(athlete) : norm(fallbackText);
      const key = [type.key, min, identity, teamId].join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ type, min, athlete, text, teamId, team: team ? team.nome : "", sort: Number((min.match(/\d+/) || [999])[0]) });
    }
    out.sort((a, b) => a.sort - b.sort || a.text.localeCompare(b.text, "pt-BR"));
    return out;
  }


  function firstArray() {
    let fallback = [];
    for (const value of arguments) {
      if (!Array.isArray(value)) continue;
      if (!fallback.length) fallback = value;
      if (value.length) return value;
    }
    return fallback;
  }

  function personName(value) {
    const person = value && (value.athlete || value.player || value.person || value);
    const ready = person && (person.shortName || person.displayName || person.fullName || person.name);
    const composed = person && [person.firstName, person.lastName].filter(Boolean).join(" ");
    return String(ready || composed || "").trim();
  }

  function teamReference(value) {
    return value && (value.team || value.competitor || value.club || value.franchise || value) || {};
  }

  function teamMatches(reference, team) {
    const ref = teamReference(reference);
    const refId = String(ref.id || ref.teamId || reference && reference.teamId || "");
    const teamId = String(team && team.id || "");
    if (refId && teamId && refId === teamId) return true;
    const refName = canon(ref.displayName || ref.shortDisplayName || ref.name || ref.location || ref.abbreviation || "");
    return Boolean(refName && team && norm(refName) === norm(team.nome));
  }

  function lineupGroupType(group) {
    const label = norm([group && group.name, group && group.displayName, group && group.label, group && group.type].filter(Boolean).join(" "));
    if (/starter|starting|titular|lineup/.test(label)) return "starter";
    if (/substitute|bench|reserve|reserva|suplente/.test(label)) return "reserve";
    return "";
  }

  function entryStarter(entry, hint) {
    for (const value of [entry && entry.starter, entry && entry.isStarter, entry && entry.starting, entry && entry.started]) {
      if (value === true) return true;
      if (value === false) return false;
    }
    const status = norm([
      entry && entry.status && (entry.status.name || entry.status.type || entry.status.description),
      entry && entry.role && (entry.role.name || entry.role.type || entry.role.description),
      entry && entry.type && (entry.type.name || entry.type.text || entry.type.description)
    ].filter(Boolean).join(" "));
    if (/starter|starting|titular/.test(status)) return true;
    if (/substitute|bench|reserve|reserva|suplente/.test(status)) return false;
    return hint === "starter" ? true : hint === "reserve" ? false : null;
  }

  function lineupEntry(entry, hint, index) {
    const athlete = entry && (entry.athlete || entry.player || entry.person || entry);
    const name = personName(athlete);
    if (!name) return null;
    const id = String(athlete.id || entry && entry.id || "");
    const jersey = String(entry && (entry.jersey || entry.jerseyNumber || entry.uniformNumber) || athlete.jersey || athlete.jerseyNumber || "").trim();
    const position = entry && entry.position || athlete.position || {};
    const positionText = String(position.abbreviation || position.shortName || position.displayName || position.name || entry && entry.positionAbbreviation || "").trim();
    const starter = entryStarter(entry, hint);
    const captain = Boolean(entry && (entry.captain === true || entry.isCaptain === true) || athlete.captain === true);
    const order = Number(entry && (entry.order || entry.sortOrder || entry.lineupOrder || entry.formationPlace));
    return {
      id,
      name,
      shortName: compactPlayerName(name),
      jersey,
      position: positionText,
      starter,
      captain,
      order: Number.isFinite(order) ? order : index + 1000
    };
  }

  function dedupePlayers(players) {
    const byKey = new Map();
    for (const player of players) {
      const key = player.id ? "id:" + player.id : "name:" + norm(player.name);
      const current = byKey.get(key);
      if (!current || (current.starter !== true && player.starter === true)) byKey.set(key, player);
    }
    return Array.from(byKey.values());
  }

  function sortPlayers(players) {
    const positionOrder = { G: 0, GK: 0, D: 1, DF: 1, M: 2, MF: 2, F: 3, FW: 3, A: 3 };
    return players.slice().sort((a, b) => {
      const poA = positionOrder[String(a.position || "").toUpperCase()] ?? 9;
      const poB = positionOrder[String(b.position || "").toUpperCase()] ?? 9;
      return a.order - b.order || poA - poB || (Number(a.jersey) || 999) - (Number(b.jersey) || 999) || a.name.localeCompare(b.name, "pt-BR");
    });
  }

  function rosterEntries(container) {
    const direct = firstArray(container && container.roster, container && container.athletes, container && container.players, container && container.entries);
    if (direct.length) return direct.map((entry, index) => lineupEntry(entry, "", index)).filter(Boolean);
    const output = [];
    for (const group of firstArray(container && container.statistics, container && container.groups, container && container.sections)) {
      const hint = lineupGroupType(group);
      const rows = firstArray(group && group.athletes, group && group.players, group && group.roster, group && group.entries);
      rows.forEach((entry, index) => {
        const parsed = lineupEntry(entry, hint, output.length + index);
        if (parsed) output.push(parsed);
      });
    }
    return output;
  }

  function formationText(container) {
    const value = container && (container.formation || container.formationName || container.tacticalFormation || container.scheme);
    if (!value) return "";
    return String(typeof value === "object" ? value.displayName || value.name || value.text || value.abbreviation || "" : value).trim();
  }

  function coachNameFrom(value) {
    const candidates = firstArray(value && value.coaches, value && value.coach ? [value.coach] : [], value && value.headCoach ? [value.headCoach] : []);
    for (const candidate of candidates) {
      const name = personName(candidate);
      if (name) return name;
    }
    return "";
  }

  function coachForTeam(summary, team, roster) {
    const direct = coachNameFrom(roster);
    if (direct) return direct;
    const pools = [
      summary && summary.coaches,
      summary && summary.gameInfo && summary.gameInfo.coaches,
      summary && summary.boxscore && summary.boxscore.teams,
      summary && summary.header && summary.header.competitions && summary.header.competitions[0] && summary.header.competitions[0].competitors
    ];
    for (const pool of pools) {
      for (const item of (Array.isArray(pool) ? pool : [])) {
        if (!teamMatches(item, team)) continue;
        const name = coachNameFrom(item);
        if (name) return name;
      }
    }
    return "";
  }

  function lineupContainers(summary) {
    const out = [];
    const addAll = (rows, source) => {
      for (const row of (Array.isArray(rows) ? rows : [])) if (row && typeof row === "object") out.push({ ...row, _lineupSource: source });
    };
    addAll(summary && summary.rosters, "rosters");
    addAll(summary && summary.lineups, "lineups");
    addAll(summary && summary.boxscore && summary.boxscore.players, "boxscore");
    return out;
  }

  function stripSubstitutionReason(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .replace(/\s*\((?:injury|injured|tactical|concussion|illness|medical|les[aã]o|lesionado|contus[aã]o|op[cç][aã]o t[eé]cnica|problema f[ií]sico)\)\s*$/i, "")
      .replace(/\s+(?:because of|due to)\s+(?:an?\s+)?(?:injury|concussion|illness)\s*$/i, "")
      .replace(/\s+(?:injury|injured|tactical|concussion|illness|medical|les[aã]o|lesionado|contus[aã]o|op[cç][aã]o t[eé]cnica|problema f[ií]sico)\s*$/i, "")
      .trim();
  }

  function cleanSubstitutionText(value) {
    const cleaned = String(value || "").replace(/\s+/g, " ").replace(/^Substitution[,.:]?\s*/i, "").replace(/^Substitui[cç][aã]o[,.:]?\s*/i, "").trim();
    return stripSubstitutionReason(cleaned);
  }

  function substitutionNames(item) {
    const raw = String(item && (item.text || item.shortText || item.description) || "").trim();
    let match = raw.match(/(?:Substitution[,.:]?\s*[^.]*\.\s*)?(.+?)\s+replaces\s+(.+?)(?:\.|$)/i);
    if (!match) match = raw.match(/(?:Substitui[cç][aã]o[,.:]?\s*[^.]*\.\s*)?(.+?)\s+entra\s+(?:no\s+lugar\s+de|por)\s+(.+?)(?:\.|$)/i);
    if (match) return { entered: compactPlayerName(stripSubstitutionReason(match[1])), left: compactPlayerName(stripSubstitutionReason(match[2])), raw };
    const involved = firstArray(item && item.athletesInvolved, item && item.participants, item && item.athletes);
    const names = involved.map(personName).filter(Boolean).map(compactPlayerName);
    if (names.length >= 2) return { entered: names[0], left: names[1], raw };
    return { entered: names[0] || "", left: "", raw };
  }

  function substitutionRows(g, summary) {
    const out = { home: [], away: [] };
    const seen = new Set();
    const candidates = [];
    for (const item of firstArray(summary && summary.plays)) candidates.push(item);
    for (const item of firstArray(summary && summary.commentary)) candidates.push(item);
    const homeId = String(g && g.home && g.home.id || "");
    const awayId = String(g && g.away && g.away.id || "");
    for (const item of candidates) {
      const text = String(item && (item.text || item.shortText || item.description) || "");
      const typeText = norm([item && item.type && (item.type.text || item.type.name || item.type.description), text].filter(Boolean).join(" "));
      if (!/substitution|substituicao|substituição|replaces|entra no lugar/.test(typeText)) continue;
      const teamId = String(item && item.team && item.team.id || item && item.teamId || "");
      let side = teamId && teamId === homeId ? "home" : teamId && teamId === awayId ? "away" : "";
      if (!side) {
        const normalizedText = norm(text);
        if (normalizedText.includes(norm(g.home.nome))) side = "home";
        else if (normalizedText.includes(norm(g.away.nome))) side = "away";
      }
      if (!side) continue;
      const names = substitutionNames(item);
      const minute = eventMinute(item);
      const label = names.entered && names.left
        ? "Entrou " + names.entered + " · saiu " + names.left
        : names.entered
          ? "Entrou " + names.entered
          : cleanSubstitutionText(text);
      if (!label) continue;
      const key = [side, minute, norm(label)].join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      out[side].push({ minute, label, sort: Number((minute.match(/\d+/) || [999])[0]) });
    }
    out.home.sort((a, b) => a.sort - b.sort || a.label.localeCompare(b.label, "pt-BR"));
    out.away.sort((a, b) => a.sort - b.sort || a.label.localeCompare(b.label, "pt-BR"));
    return out;
  }

  function lineupsForGame(g, summary) {
    const containers = lineupContainers(summary);
    const changes = substitutionRows(g, summary || {});
    const side = (team, key) => {
      const container = containers.find((item) => teamMatches(item, team)) || null;
      const parsed = dedupePlayers(rosterEntries(container || {}));
      const hasStarterMetadata = parsed.some((player) => player.starter !== null);
      const starters = sortPlayers(parsed.filter((player) => player.starter === true));
      const reserves = sortPlayers(parsed.filter((player) => player.starter === false));
      const related = hasStarterMetadata ? [] : sortPlayers(parsed);
      return {
        team,
        formation: formationText(container),
        coach: coachForTeam(summary || {}, team, container || {}),
        starters,
        reserves,
        related,
        changes: changes[key]
      };
    };
    const home = side(g.home, "home");
    const away = side(g.away, "away");
    const totalPlayers = home.starters.length + home.reserves.length + home.related.length + away.starters.length + away.reserves.length + away.related.length;
    const startersReady = home.starters.length >= 10 && away.starters.length >= 10;
    return { home, away, totalPlayers, startersReady, partial: totalPlayers > 0 && !startersReady };
  }

  function renderLineupPlayer(player) {
    const meta = [player.position, player.captain ? "capitão" : ""].filter(Boolean).join(" · ");
    return '<div class="live-lineup-player">' +
      '<span class="live-lineup-number">' + esc(player.jersey || "—") + '</span>' +
      '<span class="live-lineup-player-name">' + esc(player.shortName || player.name) + (meta ? '<small>' + esc(meta) + '</small>' : '') + '</span>' +
    '</div>';
  }

  function renderLineupChanges(rows) {
    if (!rows.length) return "";
    return '<div class="live-lineup-changes"><h4>Substituições</h4>' + rows.map((row) =>
      '<div class="live-lineup-change"><span>' + esc(row.minute || "—") + '</span><strong>' + esc(row.label) + '</strong></div>'
    ).join("") + '</div>';
  }

  function renderLineupTeam(data) {
    const team = data.team || {};
    const starters = data.starters.length ? data.starters : data.related;
    const startersTitle = data.starters.length ? "Titulares" : data.related.length ? "Jogadores relacionados" : "Titulares";
    const lineupBody = starters.length
      ? '<div class="live-lineup-list"><h4>' + startersTitle + '<span>' + starters.length + '</span></h4>' + starters.map(renderLineupPlayer).join("") + '</div>'
      : '<div class="live-lineup-team-empty">Aguardando a ESPN divulgar os titulares.</div>';
    const reserves = data.reserves.length
      ? '<details class="live-lineup-reserves"><summary>Reservas <span>' + data.reserves.length + '</span></summary><div class="live-lineup-reserve-list">' + data.reserves.map(renderLineupPlayer).join("") + '</div></details>'
      : "";
    return '<article class="live-lineup-team-card">' +
      '<header class="live-lineup-team-head">' +
        (team.escudo ? '<img src="' + esc(team.escudo) + '" alt="Escudo do ' + esc(team.nome) + '">' : '') +
        '<div><h3>' + esc(team.nome) + '</h3>' +
          (data.formation ? '<span>Formação ' + esc(data.formation) + '</span>' : '<span>Formação não informada</span>') +
        '</div>' +
      '</header>' +
      '<div class="live-lineup-coach"><span>Técnico</span><strong>' + esc(data.coach || "Não informado pela ESPN") + '</strong></div>' +
      lineupBody + reserves + renderLineupChanges(data.changes) +
    '</article>';
  }

  function renderLineups(g, summary) {
    const data = lineupsForGame(g, summary || {});
    let note = "Aguardando divulgação pela ESPN.";
    let stateClass = "waiting";
    if (data.startersReady) {
      note = "Escalações confirmadas pela ESPN.";
      stateClass = "confirmed";
    } else if (data.partial) {
      note = "Informações parciais: o card será completado automaticamente.";
      stateClass = "partial";
    } else if (data.home.changes.length || data.away.changes.length) {
      note = "Substituições disponíveis; escalações iniciais ainda não foram informadas.";
      stateClass = "partial";
    }
    return '<section class="panel live-subpanel live-lineups-panel"><div class="panel-inner">' +
      '<div class="live-section-head"><h2>👥 Escalações</h2><span class="live-section-note">ESPN summary · atualização 30s</span></div>' +
      '<div class="live-lineups-status ' + stateClass + '"><span aria-hidden="true"></span>' + esc(note) + '</div>' +
      '<div class="live-lineups-grid">' + renderLineupTeam(data.home) + renderLineupTeam(data.away) + '</div>' +
      '<p class="live-lineups-footnote">Exibimos apenas informações presentes no resumo da ESPN; dados ausentes não são estimados.</p>' +
    '</div></section>';
  }

  const LIVE_METRIC_RULES = [
    { keys:["expected goals","expectedgoals","xg"], label:"xG", order:1 },
    { keys:["possession pct","possession percent","possession percentage","possessionpct","possession","posse"], label:"Posse", order:2, percent:true },
    { keys:["total shots","totalshots","shots total","shots","shot attempts","finalizacoes","finalizações"], label:"Finalizações", order:3 },
    { keys:["shots on goal","shots on target","shotsongoal","shotsontarget","chutes no gol"], label:"Chutes no gol", order:4 },
    { keys:["shots off target","shotsofftarget"], label:"Chutes para fora", order:5 },
    { keys:["blocked shots","blockedshots"], label:"Chutes bloqueados", order:6 },
    { keys:["shot pct","shot percent","shot percentage","shotpct","shooting percentage","aproveitamento dos chutes"], label:"Aproveitamento dos chutes", order:7, percent01:true, derived:"shotPct" },
    { keys:["big chances created","bigchancescreated"], label:"Grandes chances", order:8 },
    { keys:["big chances missed","bigchancesmissed"], label:"Chances perdidas", order:9 },
    { keys:["corner kicks","cornerkicks","won corners","woncorners","corners"], label:"Escanteios", order:10 },
    { keys:["fouls committed","foulscommitted","fouls"], label:"Faltas", order:11 },
    { keys:["yellow cards","yellowcards"], label:"Amarelos", order:12 },
    { keys:["red cards","redcards"], label:"Vermelhos", order:13 },
    { keys:["offsides","offside"], label:"Impedimentos", order:14 },
    { keys:["saves","goalkeeper saves"], label:"Defesas", order:15 },
    { keys:["accurate passes","accuratepasses","completed passes","passes completed"], label:"Passes certos", order:16 },
    { keys:["pass pct","pass percent","pass percentage","pass accuracy","passpct","passaccuracy"], label:"Precisão de passe", order:17, percent01:true },
    { keys:["total passes","totalpasses","passes"], label:"Passes", order:18 },
    { keys:["duels won","duelswon"], label:"Duelos vencidos", order:19 },
    { keys:["tackles won","tackleswon","tackles"], label:"Desarmes", order:20 },
    { keys:["interceptions"], label:"Interceptações", order:21 },
    { keys:["crosses","total crosses","totalcrosses"], label:"Cruzamentos", order:22 }
  ];

  function metricKey(s) {
    return norm(String(s || "").replace(/([a-z])([A-Z])/g, "$1 $2")).replace(/\s+/g, " ").trim();
  }
  function ruleForMetric(name) {
    const key = metricKey(name), compact = key.replace(/\s+/g, "");
    for (const r of LIVE_METRIC_RULES) {
      const label = norm(r.label), lc = label.replace(/\s+/g, "");
      if (key === label || compact === lc) return r;
      if (r.keys.some(k => key === norm(k) || compact === norm(k).replace(/\s+/g, ""))) return r;
    }
    for (const r of LIVE_METRIC_RULES) {
      if (r.label === "Finalizações") continue;
      if (r.keys.some(k => key.includes(norm(k)) || compact.includes(norm(k).replace(/\s+/g, "")))) return r;
    }
    return null;
  }
  function rawStatValue(s) {
    return s && s.displayValue != null ? String(s.displayValue) : String(s && s.value != null ? s.value : "");
  }
  function numericStat(v) {
    const m = String(v == null ? "" : v).replace(",", ".").replace("%", "").match(/-?\d+(?:\.\d+)?/);
    return m ? Number(m[0]) : NaN;
  }
  function formatStatValue(rule, raw) {
    if (raw == null || raw === "") return "";
    const s = String(raw).trim();
    const n = numericStat(s);
    if ((rule.percent || rule.percent01) && !/%/.test(s) && Number.isFinite(n)) {
      const value = rule.percent01 && n >= 0 && n <= 1 ? n * 100 : n;
      return (Math.round(value * 10) / 10).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%";
    }
    return s;
  }

  function collectStats(g, summary) {
    const byTeam = {};
    const add = (team, stats) => {
      if (!team) return;
      const id = String(team.id || "");
      const name = canon(team.displayName || team.name || team.shortDisplayName || team.abbreviation);
      const key = id || name;
      if (!key) return;
      const current = byTeam[key] || {};
      for (const stat of (stats || [])) {
        const rule = ruleForMetric(stat.displayName || stat.shortDisplayName || stat.name || stat.label || stat.abbreviation || "");
        if (!rule) continue;
        const value = formatStatValue(rule, rawStatValue(stat));
        if (value !== "") current[rule.label] = value;
      }
      byTeam[key] = current;
    };

    const comp = g.competition || getCompetition(g.raw || {});
    for (const c of (comp.competitors || [])) add(c.team || {}, c.statistics || []);
    for (const t of (((summary || {}).boxscore || {}).teams || [])) add(t.team || {}, t.statistics || t.stats || []);

    const side = (which) => {
      const team = g[which];
      return byTeam[String(team.id || "")] || byTeam[canon(team.nome)] || {};
    };
    const home = side("home"), away = side("away");

    // Se a ESPN não trouxer aproveitamento, calcula chutes no gol ÷ finalizações.
    const deriveShotPct = (obj) => {
      if (obj["Aproveitamento dos chutes"] != null) return;
      const shots = numericStat(obj["Finalizações"]), on = numericStat(obj["Chutes no gol"]);
      if (Number.isFinite(shots) && shots > 0 && Number.isFinite(on)) obj["Aproveitamento dos chutes"] = (Math.round((on / shots) * 1000) / 10).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "%";
    };
    deriveShotPct(home); deriveShotPct(away);

    const rows = [];
    for (const rule of LIVE_METRIC_RULES) {
      const hv = home[rule.label] != null ? home[rule.label] : "";
      const av = away[rule.label] != null ? away[rule.label] : "";
      // Só exibe quando a fonte trouxe a métrica para os dois lados.
      if (hv === "" || av === "") continue;
      const hn = numericStat(hv), an = numericStat(av);
      let pct = 50;
      if (Number.isFinite(hn) && Number.isFinite(an) && hn + an > 0) pct = Math.max(4, Math.min(96, hn / (hn + an) * 100));
      rows.push({ label: rule.label, home: hv, away: av, pct, order: rule.order });
    }
    return rows.sort((a,b) => a.order - b.order);
  }

  function goalsBySide(g, summary) {
    const rows = eventRows(g, summary).filter(r => r.type.key === "goal");
    const home = [], away = [];
    const homeId = String(g.home.id || ""), awayId = String(g.away.id || "");
    for (const row of rows) {
      const item = { min: row.min, athlete: row.athlete || compactPlayerName(row.text.replace(/^Gol\s*[—-]?\s*/i, "")) || "Gol" };
      if (row.teamId && row.teamId === homeId) home.push(item);
      else if (row.teamId && row.teamId === awayId) away.push(item);
      else if (row.team === g.home.nome) home.push(item);
      else if (row.team === g.away.nome) away.push(item);
    }
    return { home, away };
  }

  function renderGoalsUnderTeams(g, summary) {
    const goals = goalsBySide(g, summary);
    const side = (items) => items.length ? '<div class="live-team-goals">' + items.map(x => '<div><span>' + esc(x.min || "") + '</span> ' + esc(x.athlete) + '</div>').join("") + '</div>' : '';
    return { home: side(goals.home), away: side(goals.away) };
  }

  async function loadSummary(g) {
    if (!g || !g.id || g.source !== "espn") return null;
    try {
      const data = await fetchJson(SUMMARY_API + "?event=" + encodeURIComponent(g.id) + "&_=" + Date.now());
      state.resumoPorId[g.id] = data;
      return data;
    } catch (e) {
      return state.resumoPorId[g.id] || null;
    }
  }

  function renderSwitcher(games, selected) {
    if (!games || games.length <= 1) {
      switcher.hidden = true;
      switcher.innerHTML = "";
      return;
    }
    switcher.hidden = false;
    switcher.innerHTML = games.map((g) => {
      const active = selected && g.id === selected.id;
      const live = g.state === "in";
      return '<button type="button" class="live-game-tab ' + (active ? "active" : "") + '" data-game-id="' + esc(g.id) + '">' +
        (live ? '<span class="dot-live"></span>' : "") +
        (g.home.escudo ? '<img src="' + esc(g.home.escudo) + '" alt="">' : "") +
        esc(g.home.sigla || SIGLAS[g.home.nome] || g.home.nome.slice(0, 3)) + " " +
        (g.state === "pre" ? "×" : esc(g.home.score == null ? "-" : g.home.score) + "×" + esc(g.away.score == null ? "-" : g.away.score)) + " " +
        esc(g.away.sigla || SIGLAS[g.away.nome] || g.away.nome.slice(0, 3)) +
        (g.away.escudo ? '<img src="' + esc(g.away.escudo) + '" alt="">' : "") + "</button>";
    }).join("");
    switcher.querySelectorAll("[data-game-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.selecionado = btn.getAttribute("data-game-id") || "";
        await renderPage();
        setTimeout(() => btn.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" }), 30);
      });
    });
  }

  function renderStats(g, summary) {
    const rows = collectStats(g, summary);
    if (!rows.length) return '<div class="live-empty">As estatísticas serão exibidas quando estiverem disponíveis para esta partida.</div>';
    const names = '<div class="live-stats-head"><div>' + esc(g.home.nome) + '</div><div>comparativo</div><div>' + esc(g.away.nome) + '</div></div>';
    return '<div class="live-stats live-stats-complete">' + names + rows.map((r) => '<div class="live-stat-row">' +
      '<div class="live-stat-value"><strong>' + esc(r.home) + '</strong><div class="live-stat-mini"><span style="width:' + r.pct.toFixed(1) + '%"></span></div></div>' +
      '<div class="live-stat-label">' + esc(r.label) + (r.label === "Aproveitamento dos chutes" ? ' <small title="Chutes no gol ÷ finalizações">ⓘ</small>' : '') + '</div>' +
      '<div class="live-stat-value right"><strong>' + esc(r.away) + '</strong><div class="live-stat-mini"><span style="width:' + (100-r.pct).toFixed(1) + '%"></span></div></div>' +
      '</div>').join("") + '<div class="live-stats-note">Mostramos somente métricas disponibilizadas pela ESPN. O site não inventa dados ausentes.</div></div>';
  }

  function renderNextList(all, selected) {
    const now = Date.now();
    const next = all.filter((g) => g.date && g.date.getTime() > now && !isPostponed(g) && !gameReallyFinished(g, now) && (!selected || !sameFixture(g, selected)))
      .sort((a, b) => a.date - b.date).slice(0, 6);
    if (!next.length) return "";
    return '<section class="panel live-subpanel"><div class="panel-inner"><div class="live-section-head"><h2>Próximos jogos</h2></div>' +
      '<div class="live-next-list">' + next.map((g) => {
        const canal = transmissionLabel(g);
        return '<div class="live-next-item"><div><div class="live-next-teams">' + esc(g.home.nome) + ' × ' + esc(g.away.nome) + '</div>' +
          (canal ? '<span class="live-next-channel">📺 ' + esc(canal) + '</span>' : '') + '</div><div class="live-next-meta">Rodada ' + esc(g.rodada || "—") + '<br>' + esc(formatShort(g.date)) + '</div></div>';
      }).join("") + '</div></div></section>';
  }

  function renderMain(g, summary, all) {
    if (!g) {
      app.innerHTML = '<div class="panel"><div class="panel-inner"><div class="live-empty">Nenhuma partida futura foi encontrada na agenda publicada. O robô continuará tentando atualizar os dados.</div></div></div>';
      return;
    }
    const s = gameState(g);
    const scoreVisible = s.key === "live" || s.key === "post";
    const score = scoreVisible
      ? '<div class="live-score">' + esc(g.home.score == null ? 0 : g.home.score) + ' × ' + esc(g.away.score == null ? 0 : g.away.score) + '</div>'
      : '<div class="live-vs">×</div>';
    const roundText = g.rodada ? "Rodada " + g.rodada : "Brasileirão";
    const delayed = g.adiado ? " · jogo adiado" : "";
    const countdown = countdownText(g);
    const venue = g.venue ? '<span>🏟️ <strong>' + esc(g.venue) + '</strong></span>' : "";
    const transmission = "";
    const goalLines = renderGoalsUnderTeams(g, summary);
    // A previsão pré-jogo permanece visível até a bola rolar. Durante a partida,
    // o mesmo conjunto de taxas alimenta a atualização Poisson condicional.
    const probabilityDesktop = s.key === "pre" ? renderPregameProbability(g, "desktop") : "";
    const probabilityMobile = s.key === "pre" ? renderPregameProbability(g, "mobile") : "";
    const probabilityHome = probabilityDesktop && probabilityDesktop.home ? probabilityDesktop.home : "";
    const probabilityDraw = probabilityDesktop && probabilityDesktop.draw ? probabilityDesktop.draw : "";
    const probabilityAway = probabilityDesktop && probabilityDesktop.away ? probabilityDesktop.away : "";
    contarVermelhos(g, summary);

    app.innerHTML = '<section class="live-main-card"><div class="live-card-inner">' +
      '<div class="live-round-row"><span class="live-round-badge">' + esc(roundText + delayed) + '</span>' +
      '<span class="live-state-badge ' + esc(s.key) + '">' + esc(s.label) + '</span></div>' +
      (probabilityDesktop ? '<div class="live-prob-kicker">Probabilidades pré-jogo · AF-Previsão</div>' : '') +
      '<div class="live-score-grid">' + teamLink(g.home, '<div class="live-team">' + probabilityHome + teamLogo(g.home) + '<div class="live-team-name">' + esc(g.home.nome) + '</div>' + goalLines.home + '<div class="live-team-abbr">' + esc(g.home.sigla || SIGLAS[g.home.nome] || "") + '</div></div>') +
      '<div class="live-score-center">' + probabilityDraw + score + '<div class="live-clock">' + esc(statusText(g)) + '</div>' +
      (s.key === "pre" ? '<div class="live-kickoff">Horário de Brasília</div>' : "") +
      (countdown ? '<div class="live-countdown" data-countdown-game="' + esc(g.id) + '">' + esc(countdown) + '</div>' : "") + '</div>' +
      teamLink(g.away, '<div class="live-team">' + probabilityAway + teamLogo(g.away) + '<div class="live-team-name">' + esc(g.away.nome) + '</div>' + goalLines.away + '<div class="live-team-abbr">' + esc(g.away.sigla || SIGLAS[g.away.nome] || "") + '</div></div>') + '</div>' +
      probabilityMobile +
      renderProbabilidadeDinamica(g) +
      '<div class="live-meta">' + venue + transmission + '</div>' +
      renderTransmission(g) +
      '<div class="live-message">' + esc(simpleMessage(g)) + '</div></div></section>' +
      '<section class="panel live-subpanel live-stats-panel"><div class="panel-inner"><div class="live-section-head"><h2>📊 Estatísticas</h2><span class="live-section-note">ESPN summary</span></div>' + renderStats(g, summary) + '</div></section>' +
      renderLineups(g, summary) +
      renderNextList(all, g);
  }

  async function renderPage() {
    const all = allGames();
    const { selected, priorities } = chooseGame(all);
    const switchGames = priorities.length ? priorities : (selected ? [selected] : []);
    renderSwitcher(switchGames, selected);
    const summary = await loadSummary(selected);
    renderMain(selected, summary, all);
    updateCountdowns();
    if (badge) {
      badge.classList.toggle("is-live", Boolean(selected && selected.state === "in"));
      badge.classList.remove("is-error");
      badge.textContent = state.ultimaAtualizacao ? "Atualizado " + formatClockTime(state.ultimaAtualizacao) + " · 30s" : "Atualizando a cada 30s";
    }
  }

  function updateCountdowns() {
    const all = allGames();
    document.querySelectorAll("[data-countdown-game]").forEach((el) => {
      const id = el.getAttribute("data-countdown-game");
      const g = all.find((x) => x.id === id);
      if (g) el.textContent = countdownText(g);
    });
  }

  function showAlert(msg) {
    if (!msg) {
      alertBox.classList.remove("show");
      alertBox.textContent = "";
      return;
    }
    alertBox.textContent = msg;
    alertBox.classList.add("show");
  }

  async function refresh() {
    if (state.carregando || document.hidden) return;
    state.carregando = true;
    try {
      if (state.primeiraCarga) await loadLocal();
      await Promise.all([loadScoreboard(), loadTransmissions()]);
      state.ultimaAtualizacao = new Date();
      state.ultimaFalha = "";
      state.primeiraCarga = false;
      showAlert("");
      await renderPage();
    } catch (e) {
      console.warn("Ao vivo indisponível:", e);
      state.ultimaFalha = e && e.message ? e.message : String(e);
      if (badge) {
        badge.classList.add("is-error");
        badge.classList.remove("is-live");
        badge.textContent = "Fonte temporariamente indisponível";
      }
      showAlert("A ESPN não respondeu nesta tentativa. A última informação válida permanece na tela e uma nova tentativa ocorrerá automaticamente.");
      if (state.primeiraCarga) {
        try {
          await Promise.all([loadLocal(), loadTransmissions()]);
          state.primeiraCarga = false;
          await renderPage();
        } catch (_) {
          app.innerHTML = '<div class="panel"><div class="panel-inner"><div class="live-empty">Não foi possível carregar a agenda agora. Tente novamente em alguns instantes.</div></div></div>';
        }
      }
    } finally {
      state.carregando = false;
      clearTimeout(state.timer);
      state.timer = setTimeout(refresh, REFRESH_MS);
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      clearTimeout(state.timer);
      refresh();
    }
  });

  state.tickTimer = setInterval(updateCountdowns, 1000);
  refresh();
})();

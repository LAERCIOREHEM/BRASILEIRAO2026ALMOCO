/* ========================================================================== 
   br-apostas.js — Apostas logadas do Brasileirão 2026
   Execução 1 UX: navegação clara, rodada atual automática e administração orientada por etapas.
   ========================================================================== */
(function (global, document) {
  "use strict";

  const CFG = global.BR_CFG || {};
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const STORAGE_KEY = "brApostasSessaoV2";

  const state = {
    supabase: null,
    usuario: null,
    token: "",
    jogosJson: null,
    resultadosJson: null,
    espnEventosJson: null,
    configLocal: null,
    configSupabase: [],
    jogos: [],
    resultados: [],
    rodadas: [],
    rodada: Number(CFG.rodadaInicialApostas || 20),
    aba: "apostas",
    meusPalpites: [],
    publicos: [],
    apuracao: { rodadas: [], ranking_geral: [] },
    rankingApostas: { ranking_geral: [] },
    _autoRefreshTimer: null,
    auditoria: [],
    auditoriaEventos: [],
    participantes: [],
    progresso: [],
    ligas: [],
    ligaAtual: null,
    ligasAdmin: [],
    ligaMembros: [],
    adminLigaSelecionada: null,
    rodadaAutomatica: Number(CFG.rodadaInicialApostas || 20),
    rodadaEscolhidaManualmente: false,
    rodadaAutomaticaResolvida: false,
    toastTimer: null
  };


  function abaInicialPorUrl() {
    try {
      const params = new URLSearchParams(global.location.search || "");
      const aba = (params.get("aba") || global.location.hash.replace("#", "") || "").toLowerCase();
      return ["apostas", "meus", "ranking", "publico", "auditoria", "admin"].includes(aba) ? aba : "";
    } catch (err) {
      return "";
    }
  }

  function status(msg, tipo = "warn") {
    const el = $("#status");
    if (!el) return;
    el.textContent = msg;
    el.className = `status ${tipo}`;
  }

  function toast(msg, tipo = "ok") {
    const region = $("#toast-region");
    if (!region || !msg) return;
    clearTimeout(state.toastTimer);
    const item = document.createElement("div");
    item.className = `toast ${tipo}`;
    item.setAttribute("role", tipo === "err" ? "alert" : "status");
    item.innerHTML = `<span class="toast-icon" aria-hidden="true">${tipo === "err" ? "⚠️" : tipo === "warn" ? "ℹ️" : "✅"}</span><span>${escapeHtml(msg)}</span>`;
    region.replaceChildren(item);
    requestAnimationFrame(() => item.classList.add("show"));
    state.toastTimer = setTimeout(() => {
      item.classList.remove("show");
      setTimeout(() => { if (item.isConnected) item.remove(); }, 220);
    }, 4200);
  }

  function confirmarAcao(mensagem) {
    return global.confirm(mensagem);
  }

  function cacheBust(url) {
    const sep = String(url).includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}`;
  }

  async function fetchJson(url, fallback) {
    try {
      const res = await fetch(cacheBust(url), { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return await res.json();
    } catch (err) {
      console.warn("Falha ao buscar", url, err);
      return fallback;
    }
  }

  function parseData(iso) {
    if (!iso) return null;
    const d = new Date(String(iso).length <= 16 ? iso : String(iso).replace("Z", "+00:00"));
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function fmtData(isoOrDate) {
    const d = isoOrDate instanceof Date ? isoOrDate : parseData(isoOrDate);
    if (!d) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(d).replace(".", "");
  }

  function fmtDataLonga(isoOrDate) {
    const d = isoOrDate instanceof Date ? isoOrDate : parseData(isoOrDate);
    if (!d) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(d);
  }

  function startOfDay(d) {
    const x = new Date(d.getTime());
    x.setHours(0, 0, 0, 0);
    return x;
  }

  function setWeekdayAround(reference, targetWeekday, preferFuture) {
    const d = startOfDay(reference);
    const current = d.getDay();
    let delta = targetWeekday - current;
    if (preferFuture && delta < 0) delta += 7;
    if (!preferFuture && delta > 0) delta -= 7;
    d.setDate(d.getDate() + delta);
    return d;
  }

  function normalizarTexto(s) {
    return String(s || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch] || ch));
  }

  function tipoLabel(tipo) {
    return ({ exato: "cravou", saldo: "saldo", resultado: "resultado", erro: "errou", descartado: "fora do prazo" }[tipo] || tipo || "—");
  }

  function pontosClasse(pontos) {
    const n = Number(pontos || 0);
    if (n >= 5) return "score-max";
    if (n >= 3) return "score-mid";
    if (n >= 2) return "score-low";
    return "score-zero";
  }

  function timeNome(time) { return (time && time.nome) || String(time || ""); }
  function timeSigla(time) { return (time && time.sigla) || normalizarTexto(timeNome(time)).slice(0, 3).toUpperCase(); }
  function timeEscudo(time) { return (time && time.escudo) || ""; }
  function jogoId(j) { return String(j.event_id || j.id || j.jogo_chave || `${timeNome(j.mandante)}-${timeNome(j.visitante)}-${j.data_iso || ""}`); }
  function jogoChave(j) { return `${normalizarTexto(timeNome(j.mandante))}-${normalizarTexto(timeNome(j.visitante))}-${String(j.data_iso || "").slice(0, 10)}`; }


  function prefixoEventoBrasileirao(eventId) {
    const s = String(eventId || "");
    return s.length >= 6 ? s.slice(0, 6) : s;
  }

  function sanearJogosPorRodada(lista) {
    const grupos = new Map();
    for (const j of (lista || [])) {
      const r = Number(j && j.rodada || 0);
      if (!r) continue;
      if (!grupos.has(r)) grupos.set(r, []);
      grupos.get(r).push(j);
    }
    const saida = [];
    for (const [rodada, jogos] of Array.from(grupos.entries()).sort((a, b) => a[0] - b[0])) {
      let arr = jogos.slice().sort((a, b) => String(a.data_iso || "").localeCompare(String(b.data_iso || "")));
      if (arr.length > 10) {
        const cont = {};
        arr.forEach(j => { const p = prefixoEventoBrasileirao(j.event_id || j.id); if (p) cont[p] = (cont[p] || 0) + 1; });
        const dominante = Object.entries(cont).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
        const filtrada = arr.filter(j => prefixoEventoBrasileirao(j.event_id || j.id) === dominante);
        if (filtrada.length >= 10) arr = filtrada;
      }
      if (arr.length > 10) {
        const usados = new Set();
        const semDuplicar = [];
        for (const j of arr) {
          const m = timeNome(j.mandante);
          const v = timeNome(j.visitante);
          const cm = normalizarTexto(m);
          const cv = normalizarTexto(v);
          if (!cm || !cv || usados.has(cm) || usados.has(cv)) continue;
          usados.add(cm); usados.add(cv); semDuplicar.push(j);
          if (semDuplicar.length === 10) break;
        }
        if (semDuplicar.length === 10) arr = semDuplicar;
      }
      if (jogos.length > 10 && arr.length > 10) console.warn(`Rodada ${rodada} veio com ${jogos.length} jogos; exibindo os 10 primeiros saneados.`);
      saida.push(...arr.slice(0, 10));
    }
    return saida.sort((x, y) => String(x.data_iso || "").localeCompare(String(y.data_iso || "")));
  }

  function todosJogos() {
    const a = (state.jogosJson && state.jogosJson.jogos) || [];
    const b = (state.resultadosJson && state.resultadosJson.resultados) || [];
    const c = ((state.espnEventosJson && state.espnEventosJson.eventos) || []).map(e => ({
      event_id: e.event_id,
      rodada: e.rodada,
      data_iso: e.data_iso,
      mandante: { nome: e.mandante, escudo: (state.clubesPorNome && state.clubesPorNome[e.mandante] && state.clubesPorNome[e.mandante].escudo) || "", sigla: (state.clubesPorNome && state.clubesPorNome[e.mandante] && state.clubesPorNome[e.mandante].sigla) || "" },
      visitante: { nome: e.visitante, escudo: (state.clubesPorNome && state.clubesPorNome[e.visitante] && state.clubesPorNome[e.visitante].escudo) || "", sigla: (state.clubesPorNome && state.clubesPorNome[e.visitante] && state.clubesPorNome[e.visitante].sigla) || "" },
      estadio: e.estadio || "",
      transmissao: e.transmissao || "",
      estado: e.estado || "pre",
      placar_mandante: e.placar_mandante,
      placar_visitante: e.placar_visitante
    }));
    const map = new Map();
    [...a, ...b, ...c].forEach(j => {
      if (!j) return;
      const id = jogoId(j);
      if (!map.has(id)) map.set(id, j);
    });
    return sanearJogosPorRodada(Array.from(map.values()).sort((x, y) => String(x.data_iso || "").localeCompare(String(y.data_iso || ""))));
  }

  function jogosDaRodada(rodada) {
    return state.jogos.filter(j => Number(j.rodada) === Number(rodada));
  }

  function configDaRodada(rodada) {
    const supa = state.configSupabase.find(c => Number(c.rodada) === Number(rodada));
    if (supa) return supa;
    const local = ((state.configLocal && state.configLocal.rodadas) || []).find(c => Number(c.rodada) === Number(rodada));
    if (local) return local;
    return null;
  }

  function janelaPadrao(rodada) {
    const jogos = jogosDaRodada(rodada);
    const datas = jogos.map(j => parseData(j.data_iso)).filter(Boolean).sort((a, b) => a - b);
    const primeira = datas[0] || new Date();
    const js = CFG.janelaPadrao || {};
    let sabado;
    if ([0, 1, 2, 3].includes(primeira.getDay())) sabado = setWeekdayAround(primeira, js.fechaDiaSemana ?? 6, false);
    else sabado = setWeekdayAround(primeira, js.fechaDiaSemana ?? 6, true);
    sabado.setHours(js.fechaHora ?? 10, js.fechaMinuto ?? 0, 0, 0);
    const abre = setWeekdayAround(sabado, js.abreDiaSemana ?? 4, false);
    abre.setHours(js.abreHora ?? 0, 0, 0, 0);
    return { rodada, abre_em: abre.toISOString(), fecha_em: sabado.toISOString(), status: "programada", origem: "padrao" };
  }

  function configEfetiva(rodada) {
    const cfg = configDaRodada(rodada) || janelaPadrao(rodada);
    return {
      rodada: Number(rodada),
      abre_em: cfg.abre_em,
      fecha_em: cfg.fecha_em,
      publica_em: cfg.publica_em || null,
      status: cfg.status || "programada",
      observacao: cfg.observacao || ""
    };
  }

  function rodadaAberta(rodada) {
    const cfg = configEfetiva(rodada);
    const agora = new Date();
    const abre = parseData(cfg.abre_em);
    const fecha = parseData(cfg.fecha_em);
    const status = String(cfg.status || "programada").toLowerCase();
    if (Number(rodada) < Number(CFG.rodadaInicialApostas || 20)) return false;
    if (["fechada", "apurada", "publicada", "bloqueada", "encerrada"].includes(status)) return false;
    if (status === "aberta") return true; // abertura manual pelo admin ignora o horário
    if (!abre || !fecha) return false;
    return agora >= abre && agora < fecha;
  }

  function rodadaPublica(rodada) {
    const cfg = configEfetiva(rodada);
    const status = String(cfg.status || "").toLowerCase();
    if (["publicada", "apurada"].includes(status)) return true;
    const pub = parseData(cfg.publica_em);
    return Boolean(pub && new Date() >= pub);
  }

  function statusJanela(rodada) {
    const cfg = configEfetiva(rodada);
    const abre = parseData(cfg.abre_em);
    const fecha = parseData(cfg.fecha_em);
    const agora = new Date();
    const status = String(cfg.status || "programada").toLowerCase();
    if (rodadaPublica(rodada)) return { classe: "done", texto: "Palpites publicados", detalhe: `Rodada ${rodada} publicada` };
    if (status === "aberta") return { classe: "open", texto: "Apostas abertas", detalhe: fecha ? `Aberta pelo admin · até ${fmtDataLonga(fecha)}` : "Aberta pelo admin" };
    if (["fechada", "apurada", "bloqueada", "encerrada"].includes(status)) return { classe: "lock", texto: "Rodada fechada", detalhe: `Fechada em ${fmtDataLonga(fecha)}` };
    if (abre && agora < abre) return { classe: "warn", texto: "Aguardando abertura", detalhe: `Abre em ${fmtDataLonga(abre)}` };
    if (fecha && agora >= fecha) return { classe: "lock", texto: "Janela encerrada", detalhe: `Fechou em ${fmtDataLonga(fecha)}` };
    return { classe: "open", texto: "Apostas abertas", detalhe: `Até ${fmtDataLonga(fecha)}` };
  }

  function sessionPayload() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); }
    catch (_) { return null; }
  }

  function notifySessionChanged(authenticated) {
    try {
      document.dispatchEvent(new CustomEvent("br:session-changed", {
        detail: { authenticated: Boolean(authenticated), usuario: authenticated ? state.usuario : null }
      }));
    } catch (_) {}
  }

  function saveSession(usuario, token) {
    state.usuario = usuario;
    state.token = token;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ usuario, token, salvo_em: new Date().toISOString() }));
    notifySessionChanged(true);
  }

  function clearSession() {
    state.usuario = null;
    state.token = "";
    localStorage.removeItem(STORAGE_KEY);
    notifySessionChanged(false);
  }

  async function validarSessaoAtual() {
    if (!state.usuario || !state.usuario.id || !state.token || !state.supabase) return false;
    try {
      const rows = await rpcRows("br_validar_sessao", {
        p_participante_id: state.usuario.id,
        p_token: state.token,
        p_exige_admin: false
      });
      const ok = rows[0] === true || Boolean(rows[0] && rows[0].br_validar_sessao === true);
      if (!ok) clearSession();
      return ok;
    } catch (err) {
      console.warn("Não foi possível validar a sessão salva.", err);
      clearSession();
      return false;
    }
  }

  function retornoSeguroAposLogin() {
    try {
      const params = new URLSearchParams(global.location.search || "");
      const raw = params.get("retorno") || sessionStorage.getItem("brLoginRetorno") || "";
      if (!raw) return "";
      const url = new URL(raw, global.location.href);
      if (url.origin !== global.location.origin) return "";
      const path = String(url.pathname || "/").replace(/\/+$/, "") || "/";
      const file = path.split("/").filter(Boolean).pop() || "";
      const view = String(url.searchParams.get("view") || "").toLowerCase();
      const adminLegado = view === "participantes" && url.searchParams.get("admin") === "1";
      const rotaPrivadaLimpa = path === "/bolao" || path === "/aniversariantes";
      const permitido = rotaPrivadaLimpa || file === "regras.html" || ((file === "" || file === "index.html") && (["rank", "aniversariantes"].includes(view) || adminLegado));
      if (!permitido) return "";
      sessionStorage.removeItem("brLoginRetorno");
      return url.pathname + url.search + url.hash;
    } catch (_) {
      return "";
    }
  }

  function rpcRows(name, args) {
    if (!state.supabase) return Promise.reject(new Error("Supabase não inicializado."));
    return state.supabase.rpc(name, args || {}).then(({ data, error }) => {
      if (error) throw error;
      if (!data) return [];
      return Array.isArray(data) ? data : [data];
    });
  }

  function initSupabase() {
    const supa = CFG.supabase || {};
    if (!global.supabase || !supa.url || !supa.key) return null;
    return global.supabase.createClient(supa.url, supa.key, {
      auth: { persistSession: false, autoRefreshToken: false }
    });
  }

  // ── Auto-refresh do ranking e apuração (a cada 5 min quando rodada ativa) ──
  async function recarregarApuracao() {
    try {
      const [apuracao, rankingApostas] = await Promise.all([
        fetchJson("dados-br/apuracao.json?_=" + Date.now(), { rodadas: [], ranking_geral: [] }),
        fetchJson("dados-br/ranking-apostas.json?_=" + Date.now(), { ranking_geral: [] })
      ]);
      state.apuracao = apuracao || { rodadas: [], ranking_geral: [] };
      state.rankingApostas = rankingApostas || { ranking_geral: [] };
      if (["ranking", "publico"].includes(state.aba)) renderConteudo();
    } catch (_) { /* silencioso — nao interrompe a experiencia */ }
  }

  function rodadaAtiva() {
    return state.rodadas.some(r => rodadaAberta(r) || rodadaPublica(r));
  }

  function iniciarAutoRefresh() {
    pararAutoRefresh();
    if (!rodadaAtiva()) return;
    state._autoRefreshTimer = setInterval(recarregarApuracao, 5 * 60 * 1000);
  }

  function pararAutoRefresh() {
    if (state._autoRefreshTimer) {
      clearInterval(state._autoRefreshTimer);
      state._autoRefreshTimer = null;
    }
  }

  async function carregarBase() {
    const arq = CFG.arquivos || {};
    const [jogosJson, resultadosJson, espnEventosJson, configLocal, apuracao, rankingApostas, clubesJson] = await Promise.all([
      fetchJson(arq.jogos || "jogos.json", { jogos: [] }),
      fetchJson(arq.resultados || "resultados.json", { resultados: [] }),
      fetchJson(arq.eventos || "espn_eventos.json", { eventos: [] }),
      fetchJson(arq.configRodadas || "dados-br/apostas-config.json", { rodadas: [] }),
      fetchJson("dados-br/apuracao.json", { rodadas: [], ranking_geral: [] }),
      fetchJson("dados-br/ranking-apostas.json", { ranking_geral: [] }),
      fetchJson("dados-br/clubes.json", { clubes: [] })
    ]);
    state.jogosJson = jogosJson;
    state.resultadosJson = resultadosJson;
    state.espnEventosJson = espnEventosJson;
    state.configLocal = configLocal;
    state.apuracao = apuracao || { rodadas: [], ranking_geral: [] };
    state.rankingApostas = rankingApostas || { ranking_geral: [] };
    // Mapa nome -> {escudo, sigla} para enriquecer eventos ESPN (R21+ chegam so com string)
    const clubeLista = (clubesJson && clubesJson.clubes) || [];
    state.clubesPorNome = {};
    clubeLista.forEach(c => { if (c && c.nome) state.clubesPorNome[c.nome] = c; });
    state.jogos = todosJogos();
    const set = new Set();
    for (let r = Number(CFG.rodadaInicialApostas || 20); r <= 38; r += 1) set.add(r);
    state.jogos.forEach(j => { if (Number(j.rodada) >= Number(CFG.rodadaInicialApostas || 20)) set.add(Number(j.rodada)); });
    state.rodadas = Array.from(set).sort((a, b) => a - b);
    if (!state.rodadas.includes(state.rodada)) state.rodada = state.rodadas[0] || Number(CFG.rodadaInicialApostas || 20);
  }

  async function carregarConfigsSupabase() {
    if (!state.supabase) return;
    try {
      state.configSupabase = await rpcRows("br_listar_config_rodadas", { p_temporada: CFG.temporada || 2026 });
    } catch (err) {
      console.warn("Config Supabase indisponível", err);
      state.configSupabase = [];
    }
  }

  async function carregarMeusPalpites() {
    if (!state.usuario) return;
    try {
      state.meusPalpites = await rpcRows("br_listar_meus_palpites", {
        p_participante_id: state.usuario.id,
        p_token: state.token,
        p_rodada: state.rodada,
        p_temporada: CFG.temporada || 2026
      });
    } catch (err) {
      console.warn("Meus palpites indisponíveis", err);
      state.meusPalpites = [];
    }
  }

  async function carregarLigas() {
    if (!state.usuario) return;
    try {
      const rows = await rpcRows("br_listar_minhas_ligas", {
        p_participante_id: state.usuario.id,
        p_token: state.token
      });
      state.ligas = Array.isArray(rows) ? rows : [];
    } catch (err) {
      console.warn("Ligas indisponíveis; usando Liga Geral virtual", err);
      state.ligas = [{ liga_id: "geral", nome: "Liga Geral", slug: "liga-geral", descricao: "Ranking geral", ativa: true, papel: "participante" }];
    }
    if (!state.ligas.length) {
      state.ligas = [{ liga_id: "geral", nome: "Liga Geral", slug: "liga-geral", descricao: "Ranking geral", ativa: true, papel: "participante" }];
    }
    const existe = state.ligas.some(l => String(l.liga_id) === String(state.ligaAtual));
    if (!state.ligaAtual || !existe) {
      const preferida = ligaPreferida(state.ligas);
      state.ligaAtual = preferida ? preferida.liga_id : null;
    }
  }

  function ligaAtualObj() {
    return state.ligas.find(l => String(l.liga_id) === String(state.ligaAtual)) || state.ligas[0] || null;
  }

  function nomeLigaAtual() {
    const l = ligaAtualObj();
    return l ? l.nome : "Liga Geral";
  }

  function ligaRelatorioObj() {
    return (state.ligasAdmin || []).find(l => String(l.liga_id) === String(state.adminLigaSelecionada)) || ligaAtualObj();
  }

  function nomeLigaRelatorio() {
    const l = ligaRelatorioObj();
    return l ? l.nome : nomeLigaAtual();
  }

  function slugLigaRelatorio() {
    const l = ligaRelatorioObj();
    return l ? (l.slug || l.liga_id || ligaSlugAtual()) : ligaSlugAtual();
  }

  function isAdminGlobal() {
    return Boolean(state.usuario && state.usuario.admin);
  }

  function isAdminLiga() {
    return Boolean((state.ligas || []).some(l => String(l.papel || "") === "admin_liga"));
  }

  function canAdminAny() {
    return isAdminGlobal() || isAdminLiga();
  }

  function canEditLiga(ligaId) {
    if (isAdminGlobal()) return true;
    return Boolean((state.ligasAdmin || state.ligas || []).some(l => String(l.liga_id) === String(ligaId) && String(l.papel || "") === "admin_liga"));
  }

  function adminPerfilTexto() {
    if (isAdminGlobal()) return "administrador global";
    if (isAdminLiga()) return "administrador de liga";
    return "participante";
  }

  function ligaSlugAtual() {
    const l = ligaAtualObj();
    return l ? (l.slug || l.liga_id || "liga-geral") : "liga-geral";
  }

  function isLigaAlmoco(liga) {
    const slug = normalizarTexto(liga?.slug || liga?.nome || "");
    return slug === "almoco-de-sexta" || slug === "almoco-sexta" || slug === "almoco";
  }

  function isLigaGeral(liga) {
    const slug = normalizarTexto(liga?.slug || liga?.nome || "");
    return slug === "liga-geral" || slug === "geral";
  }

  function ligaPreferida(ligas) {
    const lista = Array.isArray(ligas) ? ligas : [];
    return lista.find(isLigaAlmoco) || lista.find(l => !isLigaGeral(l)) || lista[0] || null;
  }

  function rankingPorLigaPayload(payload, ligaId) {
    if (!payloadPontuacaoConfiavel(payload)) return null;
    const porLiga = (payload && (payload.rankings_por_liga || payload.ranking_por_liga)) || {};
    const liga = state.ligas.find(l => String(l.liga_id) === String(ligaId)) || ligaAtualObj();
    const chaves = [
      liga?.liga_id,
      liga?.slug,
      normalizarTexto(liga?.nome || ""),
      "liga-geral"
    ].filter(Boolean).map(String);
    for (const k of chaves) {
      if (Array.isArray(porLiga[k])) return porLiga[k];
    }
    return null;
  }

  function payloadPontuacaoConfiavel(payload) {
    return Boolean(payload && payload.validacao_resultados && payload.validacao_resultados.somente_finalizados === true);
  }

  function resultadoFinalLocal(eventId) {
    const id = String(eventId || "");
    if (!id) return null;
    const lista = (state.resultadosJson && state.resultadosJson.resultados) || [];
    return lista.find(r => String(r.event_id || r.id || "") === id) || null;
  }

  function resultadoFinalizado(resultado, eventId) {
    const r = resultado || {};
    const temPlacar = r.placar_mandante !== null && r.placar_mandante !== undefined
      && r.placar_visitante !== null && r.placar_visitante !== undefined;
    if (!temPlacar) return false;
    const local = resultadoFinalLocal(eventId || r.event_id || r.id);
    if (!local) return false;
    return Number(local.placar_mandante) === Number(r.placar_mandante)
      && Number(local.placar_visitante) === Number(r.placar_visitante);
  }

  function apuracaoRodadaConfiavel(ap) {
    if (!ap || !payloadPontuacaoConfiavel(state.apuracao)) return false;
    const jogos = Array.isArray(ap.jogos) ? ap.jogos : [];
    const finais = jogos.filter(j => resultadoFinalizado(j.resultado || {}, j.event_id));
    const ids = new Set(finais.map(j => String((j.resultado || {}).event_id || j.event_id || "")).filter(Boolean));
    return finais.length === jogos.length && Number(ap.jogos_apurados || 0) === ids.size;
  }

  function rankingGeralConfiavel() {
    const candidatos = [state.rankingApostas, state.apuracao];
    for (const payload of candidatos) {
      if (!payloadPontuacaoConfiavel(payload)) continue;
      const porLiga = rankingPorLigaPayload(payload, state.ligaAtual);
      if (Array.isArray(porLiga)) return porLiga;
      if (Array.isArray(payload.ranking_geral)) return payload.ranking_geral;
    }
    return [];
  }

  function rankingRodadaPorLiga(ap, ligaId) {
    if (!ap || !apuracaoRodadaConfiavel(ap)) return [];
    const porLiga = (ap.rankings_por_liga || ap.ranking_por_liga || {});
    const liga = state.ligas.find(l => String(l.liga_id) === String(ligaId)) || ligaAtualObj();
    const chaves = [liga?.liga_id, liga?.slug, normalizarTexto(liga?.nome || ""), "liga-geral"].filter(Boolean).map(String);
    for (const k of chaves) {
      if (Array.isArray(porLiga[k])) return porLiga[k];
    }
    return Array.isArray(ap.ranking) ? ap.ranking : [];
  }

  function vencedoresRodadaPorLiga(ap, ligaId) {
    if (!ap || !apuracaoRodadaConfiavel(ap)) return [];
    const porLiga = (ap.vencedores_por_liga || {});
    const liga = state.ligas.find(l => String(l.liga_id) === String(ligaId)) || ligaAtualObj();
    const chaves = [liga?.liga_id, liga?.slug, normalizarTexto(liga?.nome || ""), "liga-geral"].filter(Boolean).map(String);
    for (const k of chaves) {
      if (Array.isArray(porLiga[k])) return porLiga[k];
    }
    return Array.isArray(ap.vencedores) ? ap.vencedores : [];
  }

  function renderLigaBox() {
    const box = $("#liga-box");
    if (!box || !state.usuario) return;
    const ligas = state.ligas || [];
    if (!ligas.length) { box.innerHTML = ""; return; }
    const atual = ligaAtualObj();
    const adminCta = canAdminAny() ? `<div class="liga-admin-cta">
        <button class="btn" type="button" id="abrir-admin-ligas">➕ Criar/gerenciar ligas</button>
        <small>Use esta área para criar ligas de outros grupos, colocar participantes e definir admin da liga.</small>
      </div>` : "";
    const avisoGeral = atual && isLigaGeral(atual) ? `<p class="muted-note"><strong>Liga Geral</strong> é a visão consolidada de todos. A liga padrão do grupo é <strong>Almoço de Sexta</strong>; outras ligas podem ser criadas no Admin.</p>` : "";
    box.innerHTML = `<section class="panel liga-panel"><div class="panel-inner liga-box-inner">
      <div>
        <div class="kicker">Liga ativa</div>
        <h2>${escapeHtml(nomeLigaAtual())}</h2>
        <p>O palpite é único por rodada. A liga selecionada filtra ranking, palpites públicos, progresso e auditoria.</p>
        ${avisoGeral}
      </div>
      <div class="liga-select-actions">
        <label>Selecionar liga
          <select id="liga-select">${ligas.map(l => {
            const sufixo = isLigaAlmoco(l) ? " · padrão" : (l.papel === "admin_liga" || l.pode_gerir ? " · admin" : "");
            return `<option value="${escapeAttr(l.liga_id)}" ${String(l.liga_id) === String(state.ligaAtual) ? "selected" : ""}>${escapeHtml(l.nome)}${sufixo}</option>`;
          }).join("")}</select>
        </label>
        ${adminCta}
      </div>
    </div></section>`;
    $("#liga-select")?.addEventListener("change", async ev => {
      state.ligaAtual = ev.target.value;
      status(`Liga ativa: ${nomeLigaAtual()}.`, "ok");
      renderLigaBox();
      renderConteudo();
    });
    $("#abrir-admin-ligas")?.addEventListener("click", async () => {
      state.aba = "admin";
      await refresh();
      document.getElementById("conteudo")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function carregarPublicos() {
    try {
      if (state.usuario && state.ligaAtual) {
        state.publicos = await rpcRows("br_listar_palpites_publicos_liga", {
          p_participante_id: state.usuario.id,
          p_token: state.token,
          p_liga_id: state.ligaAtual,
          p_rodada: state.rodada,
          p_temporada: CFG.temporada || 2026
        });
      } else {
        state.publicos = await rpcRows("br_listar_palpites_publicos", {
          p_rodada: state.rodada,
          p_temporada: CFG.temporada || 2026
        });
      }
    } catch (err) {
      console.warn("Palpites públicos por liga indisponíveis", err);
      state.publicos = [];
    }
  }

  function htmlTeam(time, cls) {
    const esc = timeEscudo(time);
    return `<div class="team ${cls || ""}">${esc ? `<img src="${esc}" alt="">` : ""}<div><div class="team-name">${timeNome(time)}</div><div class="team-sigla">${timeSigla(time)}</div></div></div>`;
  }

  function palpiteSalvoPara(id) {
    return state.meusPalpites.find(p => String(p.event_id) === String(id));
  }

  function jogoTemResultadoFinal(jogo) {
    const id = jogoId(jogo);
    if (!id) return false;
    return Boolean(resultadoFinalLocal(id));
  }

  function rodadaConcluida(rodada) {
    const jogos = jogosDaRodada(rodada);
    return jogos.length > 0 && jogos.every(jogoTemResultadoFinal);
  }

  function intervaloRodada(rodada) {
    const datas = jogosDaRodada(rodada)
      .map(j => parseData(j.data_iso))
      .filter(Boolean)
      .sort((a, b) => a - b);
    return {
      inicio: datas[0] || null,
      fim: datas[datas.length - 1] || null
    };
  }

  function rodadaTemJogoEmAndamento(rodada) {
    const ids = new Set(jogosDaRodada(rodada).map(j => String(jogoId(j))).filter(Boolean));
    const eventos = (state.espnEventosJson && state.espnEventosJson.eventos) || [];
    return eventos.some(e => ids.has(String(e.event_id || e.id || "")) && String(e.estado || e.state || "").toLowerCase() === "in");
  }

  function determinarRodadaAtual() {
    const rodadas = (state.rodadas || []).slice().sort((a, b) => a - b);
    if (!rodadas.length) return Number(CFG.rodadaInicialApostas || 20);
    const abertas = rodadas.filter(r => !rodadaConcluida(r) && rodadaAberta(r));
    if (abertas.length) return abertas[0];
    const emAndamento = rodadas.find(r => rodadaTemJogoEmAndamento(r));
    if (emAndamento) return emAndamento;
    const agora = new Date();
    const futuras = rodadas
      .filter(r => !rodadaConcluida(r))
      .map(r => ({ rodada: r, ...intervaloRodada(r) }))
      .filter(x => x.inicio && x.inicio >= agora)
      .sort((a, b) => a.inicio - b.inicio);
    if (futuras.length) return futuras[0].rodada;
    const incompletaComJogos = rodadas.find(r => jogosDaRodada(r).length > 0 && !rodadaConcluida(r));
    if (incompletaComJogos) return incompletaComJogos;
    const comJogos = rodadas.filter(r => jogosDaRodada(r).length > 0);
    return comJogos[comJogos.length - 1] || rodadas[0];
  }

  function resolverRodadaAutomatica(force = false) {
    const atual = determinarRodadaAtual();
    state.rodadaAutomatica = atual;
    if (force || !state.rodadaAutomaticaResolvida || !state.rodadaEscolhidaManualmente) {
      state.rodada = atual;
    }
    state.rodadaAutomaticaResolvida = true;
  }

  function renderResumo() {
    const jogos = jogosDaRodada(state.rodada);
    const st = statusJanela(state.rodada);
    const salvos = state.meusPalpites.length;
    const pct = jogos.length ? Math.round((salvos / jogos.length) * 100) : 0;
    $("#numero-rodada").textContent = state.rodada;
    $("#total-jogos").textContent = jogos.length;
    $("#texto-janela").textContent = st.texto;
    const badge = $("#badge-janela");
    badge.textContent = st.detalhe;
    badge.className = `badge ${st.classe}`;
    $("#meu-percentual").textContent = `${pct}%`;
    $("#meu-total-salvo").textContent = salvos;
  }

  function renderRodadas() {
    const tabs = $("#rodadas");
    const contexto = $("#rodada-contexto");
    const voltar = $("#voltar-rodada-atual");
    const titulo = $("#controle-titulo");
    const descricao = $("#controle-descricao");
    if (!tabs) return;
    const manual = Number(state.rodada) !== Number(state.rodadaAutomatica);
    tabs.innerHTML = state.rodadas.map(r => {
      const active = Number(r) === Number(state.rodada);
      const current = Number(r) === Number(state.rodadaAutomatica);
      return `<button type="button" class="${active ? "active" : ""} ${current ? "current" : ""}" data-rodada="${r}" role="tab" aria-selected="${active}" aria-label="Rodada ${r}${current ? ", rodada atual" : ""}">R${r}${current ? `<span class="current-dot" aria-hidden="true"></span>` : ""}</button>`;
    }).join("");
    tabs.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => trocarRodada(Number(btn.dataset.rodada), true)));
    if (contexto) contexto.innerHTML = manual
      ? `Consultando <strong>Rodada ${state.rodada}</strong> · atual automática: <strong>R${state.rodadaAutomatica}</strong>`
      : `Rodada atual identificada automaticamente: <strong>R${state.rodadaAutomatica}</strong>`;
    if (voltar) voltar.hidden = !manual;
    if (titulo) titulo.textContent = manual ? `Consultando rodada ${state.rodada}` : `Rodada atual: ${state.rodadaAutomatica}`;
    if (descricao) descricao.textContent = manual
      ? "Você está consultando outra rodada. Use o botão ao lado para voltar ao contexto atual."
      : "A rodada em andamento é escolhida automaticamente pelos jogos e resultados disponíveis.";
  }

  function renderUsuario() {
    const chip = $("#usuario-chip");
    if (!state.usuario) { chip.hidden = true; return; }
    chip.hidden = false;
    chip.innerHTML = `${canAdminAny() ? "🛠️ " : "👤 "}${escapeHtml(state.usuario.nome)}<br><small>${escapeHtml(nomeLigaAtual())} · ${escapeHtml(adminPerfilTexto())}</small><br><button class="btn ghost" type="button" id="sair">sair</button>`;
    $("#sair")?.addEventListener("click", () => { clearSession(); renderLogin(); status("Sessão encerrada.", "warn"); });
    $$(".admin-only").forEach(el => { el.hidden = !canAdminAny(); });
  }

  function renderLogin() {
    const autenticado = Boolean(state.usuario);
    $("#login-area").hidden = autenticado;
    $("#app-area").hidden = !autenticado;
    // Oculta o card de título quando logado — não agrega após o login
    const titleSection = document.querySelector(".br-page-title");
    if (titleSection) titleSection.hidden = autenticado;
    renderUsuario();
  }

  function renderApostas() {
    const root = $("#conteudo");
    const jogos = jogosDaRodada(state.rodada);
    const aberta = rodadaAberta(state.rodada);
    const st = statusJanela(state.rodada);
    if (!jogos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>Rodada ${state.rodada} ainda sem jogos no JSON.</strong><p>Quando o workflow ESPN trouxer a tabela da rodada, os confrontos aparecem aqui. O admin já pode configurar a janela.</p></div></section>`;
      return;
    }
    const aviso = aberta ?
      `<div class="status ok">Janela aberta. Você pode salvar ou alterar seus palpites até o fechamento.</div>` :
      `<div class="status warn">${st.texto}. ${st.detalhe}. Os campos ficam bloqueados fora da janela.</div>`;
    root.innerHTML = `${aviso}<form id="form-palpites" class="matches">${jogos.map(j => {
      const id = jogoId(j);
      const salvo = palpiteSalvoPara(id);
      return `<article class="match-card" data-event-id="${id}">
        <div class="match-top"><span>Rodada ${j.rodada} · ${fmtData(j.data_iso)}</span><span class="badge ${aberta ? "open" : "lock"}">${aberta ? "aberto" : "travado"}</span></div>
        <div class="match-body">
          ${htmlTeam(j.mandante, "home")}
          <div class="score-inputs">
            <input name="pm-${id}" type="number" inputmode="numeric" min="0" max="30" value="${salvo?.placar_mandante ?? ""}" ${aberta ? "" : "disabled"} aria-label="Placar ${timeNome(j.mandante)}">
            <span>x</span>
            <input name="pv-${id}" type="number" inputmode="numeric" min="0" max="30" value="${salvo?.placar_visitante ?? ""}" ${aberta ? "" : "disabled"} aria-label="Placar ${timeNome(j.visitante)}">
          </div>
          ${htmlTeam(j.visitante, "away")}
        </div>
        <div class="match-extra">
          <span class="badge info">${j.estadio || "estádio a confirmar"}</span>
          ${salvo ? `<span class="badge open saved-pill">salvo ${fmtDataLonga(salvo.atualizado_em || salvo.criado_em)}</span>` : `<span class="badge">não salvo</span>`}
        </div>
      </article>`;
    }).join("")}
    <div class="actions"><button class="btn" type="submit" ${aberta ? "" : "disabled"}>💾 Salvar palpites da rodada</button><button class="btn secondary" type="button" id="limpar-campos" ${aberta ? "" : "disabled"}>limpar campos</button></div>
    </form>`;
    $("#form-palpites")?.addEventListener("submit", salvarPalpites);
    $("#limpar-campos")?.addEventListener("click", () => {
      if (!confirmarAcao("Limpar os placares preenchidos nesta tela? Nenhum dado já salvo será apagado.")) return;
      $$("#form-palpites input").forEach(i => { i.value = ""; });
      status("Campos da tela limpos. Nenhum palpite salvo foi apagado.", "ok");
      toast("Campos limpos. Os palpites já salvos foram preservados.", "ok");
    });
  }

  function coletarPalpitesFormulario() {
    const jogos = jogosDaRodada(state.rodada);
    const payload = [];
    for (const j of jogos) {
      const id = jogoId(j);
      const pmEl = $(`[name="pm-${CSS.escape(id)}"]`);
      const pvEl = $(`[name="pv-${CSS.escape(id)}"]`);
      const pm = pmEl?.value === "" ? null : Number(pmEl?.value);
      const pv = pvEl?.value === "" ? null : Number(pvEl?.value);
      if (pm === null && pv === null) continue;
      if (!Number.isInteger(pm) || !Number.isInteger(pv) || pm < 0 || pv < 0 || pm > 30 || pv > 30) {
        throw new Error(`Placar inválido em ${timeNome(j.mandante)} x ${timeNome(j.visitante)}.`);
      }
      payload.push({
        event_id: id,
        jogo_chave: jogoChave(j),
        mandante: timeNome(j.mandante),
        visitante: timeNome(j.visitante),
        placar_mandante: pm,
        placar_visitante: pv,
        kickoff: j.data_iso || null,
        fecha_em: configEfetiva(state.rodada).fecha_em
      });
    }
    return payload;
  }

  async function salvarPalpites(ev) {
    ev.preventDefault();
    try {
      if (!rodadaAberta(state.rodada)) throw new Error("Rodada fora da janela de apostas.");
      const payload = coletarPalpitesFormulario();
      if (!payload.length) throw new Error("Preencha ao menos um placar antes de salvar.");
      status("Salvando palpites com hash de comprovante...", "warn");
      const rows = await rpcRows("br_salvar_palpites", {
        p_participante_id: state.usuario.id,
        p_token: state.token,
        p_temporada: CFG.temporada || 2026,
        p_rodada: state.rodada,
        p_palpites: payload
      });
      const comprovante = rows[0] || {};
      await carregarMeusPalpites();
      renderResumo();
      renderApostas();
      const root = $("#conteudo");
      root.insertAdjacentHTML("afterbegin", `<div class="comprovante"><strong>🧾 Comprovante gerado</strong><p>Rodada ${state.rodada} · ${payload.length} palpites enviados.</p><p class="hash">${comprovante.hash_fechamento || comprovante.hash || "hash indisponível"}</p></div>`);
      status(`✅ PALPITES GRAVADOS COM SUCESSO! Comprovante da rodada ${state.rodada} gerado.`, "ok");
      toast(`Palpites da rodada ${state.rodada} salvos com sucesso.`, "ok");
    } catch (err) {
      console.error(err);
      status(err.message || "Falha ao salvar palpites.", "err");
      toast(err.message || "Falha ao salvar palpites.", "err");
    }
  }

  function renderMeus() {
    const root = $("#conteudo");
    if (!state.meusPalpites.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty">Você ainda não tem palpites salvos na rodada ${state.rodada}.</div></section>`;
      return;
    }
    const hash = state.meusPalpites.find(p => p.hash_fechamento)?.hash_fechamento || "—";
    root.innerHTML = `<section class="panel"><div class="panel-inner">
      <div class="kicker">Meus palpites</div><h2>Rodada ${state.rodada}</h2>
      <p>Você pode consultar seus próprios palpites a qualquer momento. Os palpites dos outros só aparecem após a publicação da rodada.</p>
      <div class="comprovante"><strong>Hash atual da rodada</strong><p class="hash">${hash}</p></div>
      <div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Jogo</th><th>Meu palpite</th><th>Atualizado</th></tr></thead><tbody>
      ${state.meusPalpites.map(p => `<tr><td>${p.mandante} x ${p.visitante}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td>${fmtDataLonga(p.atualizado_em || p.criado_em)}</td></tr>`).join("")}
      </tbody></table></div>
    </div></section>`;
  }

  function apuracaoRodada(rodada) {
    const lista = (state.apuracao && state.apuracao.rodadas) || [];
    return lista.find(r => Number(r.rodada) === Number(rodada)) || null;
  }

  function mapaPontosRodada(rodada) {
    const ap = apuracaoRodada(rodada);
    const mapa = new Map();
    if (!ap || !apuracaoRodadaConfiavel(ap) || !Array.isArray(ap.jogos)) return mapa;
    ap.jogos.forEach(j => {
      if (!resultadoFinalizado(j.resultado || {}, j.event_id)) return;
      (j.palpites || []).forEach(p => {
        const eventId = j.resultado?.event_id || j.event_id || "";
        if (p.participante_id) mapa.set(`id:${p.participante_id}::${eventId}`, p);
        mapa.set(`nome:${normalizarTexto(p.membro || "")}::${eventId}`, p);
      });
    });
    return mapa;
  }

  function renderRanking() {
    const root = $("#conteudo");
    const ap = apuracaoRodada(state.rodada);
    if (!ap || ap.sigilosa) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty">
        <strong>Ranking da rodada ainda não publicado.</strong>
        <p>A apuração só aparece aqui depois que a rodada tiver resultados e for publicada. Enquanto isso, os palpites seguem sigilosos.</p>
        ${canAdminAny() ? `<p class="muted-note">Admin: rode o workflow <strong>Apurar Apostas Brasileirão</strong> após os jogos e publique a rodada.</p>` : ""}
      </div></section>`;
      return;
    }
    const confiavel = apuracaoRodadaConfiavel(ap);
    const ranking = confiavel ? rankingRodadaPorLiga(ap, state.ligaAtual) : [];
    const vencedoresLiga = confiavel ? vencedoresRodadaPorLiga(ap, state.ligaAtual) : [];
    const jogosApurados = confiavel ? Number(ap.jogos_apurados || 0) : 0;
    const avisoValidacao = confiavel ? ""
      : `<div class="status warn">Pontuação ocultada: apuração não confirmou todos os jogos encerrados.</div>`;

    // Palpites por participante para o botão recolhível
    // Usa publicos se disponível, senão marca como indisponível
    const publicos = Array.isArray(state.publicos) ? state.publicos : [];
    const pontosMap = mapaPontosRodada(state.rodada);

    // Mapa de resultados reais: event_id → {pm, pv}
    const resultadoReal = new Map();
    const apRef = apuracaoRodada(state.rodada);
    if (apRef && Array.isArray(apRef.jogos)) {
      apRef.jogos.forEach(function(j) {
        var res = j.resultado || {};
        var eid = String(res.event_id || j.event_id || '');
        if (eid && res.placar_mandante != null && res.placar_visitante != null) {
          resultadoReal.set(eid, { pm: res.placar_mandante, pv: res.placar_visitante });
        }
      });
    }

    function palpitesDoParticipante(membro, participanteId) {
      var minha = publicos.filter(function(p) {
        return (participanteId && p.participante_id && String(p.participante_id) === String(participanteId))
          || (!participanteId && normalizarTexto(p.membro || '') === normalizarTexto(membro || ''));
      });
      if (!minha.length) return '<p class="muted-note" style="margin:8px 0">Palpites não disponíveis ou rodada ainda sigilosa.</p>';
      return '<div class="palpite-expand-grid">' + minha.map(function(p) {
        var kId = 'id:' + (p.participante_id || '') + '::' + (p.event_id || '');
        var kNome = 'nome:' + normalizarTexto(p.membro || '') + '::' + (p.event_id || '');
        var det = (p.participante_id && pontosMap.get(kId)) || pontosMap.get(kNome) || {};
        var pontosCls = det.pontos != null ? pontosClasse(det.pontos) : '';
        var pontosStr = det.pontos != null ? String(det.pontos) + ' pts' : '— pts';
        var tipoStr = det.tipo ? tipoLabel(det.tipo) : null;
        var rr = resultadoReal.get(String(p.event_id || ''));
        var temReal = rr != null;

        // Layout:
        // ┌──────────────────────────────────────┐
        // │ Santos x Chapecoense                 │
        // │ 2 x 2  [cravou · 5 pts]              │  ← resultado real + veredito
        // │ Palpite: 2 x 0                       │  ← palpite do apostador
        // └──────────────────────────────────────┘

        var jogoHtml = '<div class="pex-jogo">'
          + escapeHtml(p.mandante) + ' <em>×</em> ' + escapeHtml(p.visitante)
          + '</div>';

        var veredito = tipoStr ? ('<span class="pex-veredito ' + pontosCls + '">' + escapeHtml(tipoStr) + ' · ' + pontosStr + '</span>') : '';

        var realHtml = temReal
          ? '<div class="pex-resultado-real ' + pontosCls + '">'
              + '<span class="pex-score">' + rr.pm + ' × ' + rr.pv + '</span>'
              + veredito
            + '</div>'
          : '<div class="pex-resultado-real pex-aguardando">'
              + '<span class="pex-score pex-nd">—</span>'
            + '</div>';

        var palHtml = '<div class="pex-palpite-row">'
          + '<span class="pex-pal-label">Palpite:</span>'
          + '<span class="pex-pal-score">' + p.placar_mandante + ' × ' + p.placar_visitante + '</span>'
          + '</div>';

        return '<div class="palpite-card ' + pontosCls + '">'
          + jogoHtml
          + realHtml
          + palHtml
          + '</div>';
      }).join('') + '</div>';
    }

    const posIcons = ["", "🥇", "🥈", "🥉"];

    const linhasRanking = ranking.map((r, idx) => {
      const uid = `rk-${idx}-${normalizarTexto(r.membro)}`;
      const icon = posIcons[r.pos] || "";
      const isVencedor = vencedoresLiga.includes(r.membro);
      return `<article class="rk-card${isVencedor ? " rk-vencedor" : ""}" id="${uid}">
        <div class="rk-main">
          <div class="rk-pos">${icon || r.pos}</div>
          <div class="rk-info">
            <div class="rk-nome">${escapeHtml(r.membro)}${isVencedor ? " 🏆" : ""}</div>
            <div class="rk-badges">
              <span class="rk-badge">✅ ${r.cravadas} cravada${r.cravadas !== 1 ? "s" : ""}</span>
              <span class="rk-badge">📊 ${r.resultados} resultado${r.resultados !== 1 ? "s" : ""}</span>
              <span class="rk-badge">💧 saldo ${r.saldos >= 0 ? "+" : ""}${r.saldos}</span>
              <span class="rk-badge rk-badge-err">❌ ${r.erros} erro${r.erros !== 1 ? "s" : ""}</span>
            </div>
          </div>
          <div class="rk-pts"><strong>${r.pontos}</strong><small>pts</small></div>
        </div>
        <details class="rk-palpites">
          <summary><span>Ver palpites</span><i aria-hidden="true"></i></summary>
          <div class="rk-palpites-body">${palpitesDoParticipante(r.membro, r.participante_id)}</div>
        </details>
      </article>`;
    });

    root.innerHTML = `<section class="ranking-rodada-section">
      <div class="rk-header">
        <div>
          <div class="kicker">Ranking da rodada</div>
          <h2>Rodada ${state.rodada} · ${escapeHtml(nomeLigaAtual())}</h2>
          ${vencedoresLiga.length
            ? `<p class="rk-winner-line">🏆 Vencedor da liga: <strong>${vencedoresLiga.map(escapeHtml).join(", ")}</strong></p>`
            : `<p class="rk-winner-line muted">Aguardando jogos apurados.</p>`}
        </div>
        <div class="rk-header-kpis">
          <span><strong>${ap.participantes || 0}</strong><small>participantes</small></span>
          <span><strong>${jogosApurados}</strong><small>jogos apurados</small></span>
        </div>
      </div>
      ${avisoValidacao}
      ${ranking.length
        ? `<div class="export-row"><button class="btn secondary" type="button" id="export-ranking">⬇️ Exportar CSV</button></div>
           <div class="rk-list">${linhasRanking.join("")}</div>`
        : `<div class="panel"><div class="panel-inner empty">Nenhum jogo apurado nesta rodada.</div></div>`}
    </section>`;
    $("#export-ranking")?.addEventListener("click", exportarRankingCsv);
  }

  function renderRankingGeral(_geral) {
    // Card de ranking acumulado removido a pedido — exibe apenas ranking da rodada.
    return "";
  }

  async function renderPublico() {
    await carregarPublicos();
    const root = $("#conteudo");
    const ap = apuracaoRodada(state.rodada);
    const pontosMap = mapaPontosRodada(state.rodada);
    if (!rodadaPublica(state.rodada) && !state.publicos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>Palpites ainda sigilosos.</strong><p>A rodada ${state.rodada} só abre para todos após o fechamento/publicação feita pelo administrador.</p></div></section>`;
      return;
    }
    if (!state.publicos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty">Nenhum palpite público encontrado para a rodada ${state.rodada}.</div></section>`;
      return;
    }
    const apConfiavel = ap && !ap.sigilosa && apuracaoRodadaConfiavel(ap);
    const jogosApurados = apConfiavel ? Number(ap.jogos_apurados || 0) : 0;
    root.innerHTML = `<section class="panel"><div class="panel-inner">
      <div class="kicker">Palpites públicos</div><h2>Rodada ${state.rodada} · ${escapeHtml(nomeLigaAtual())}</h2>
      <p>Lista aberta após publicação da rodada. Quando a apuração já estiver disponível, a tabela mostra pontos e tipo de acerto jogo a jogo.</p>
      ${jogosApurados > 0 ? `<div class="status ok">Apuração publicada · ${jogosApurados} jogos encerrados e apurados.</div>` : `<div class="status warn">Palpites publicados; a pontuação aparecerá somente após o encerramento dos jogos.</div>`}
      <div class="export-row"><button class="btn secondary" type="button" id="export-publicos">⬇️ Exportar palpites CSV</button></div>
      <div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Participante</th><th>Jogo</th><th>Palpite</th><th>Pontos</th><th>Tipo</th><th>Hash</th></tr></thead><tbody>
        ${state.publicos.map(p => {
          const det = (p.participante_id && pontosMap.get(`id:${p.participante_id}::${p.event_id || ""}`))
            || pontosMap.get(`nome:${normalizarTexto(p.membro || "")}::${p.event_id || ""}`)
            || {};
          return `<tr><td>${escapeHtml(p.membro)}</td><td>${escapeHtml(p.mandante)} x ${escapeHtml(p.visitante)}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td class="num ${pontosClasse(det.pontos)}">${det.pontos ?? "—"}</td><td>${escapeHtml(tipoLabel(det.tipo))}</td><td class="hash">${escapeHtml(p.hash_fechamento || "—")}</td></tr>`;
        }).join("")}
      </tbody></table></div>
    </div></section>`;
    $("#export-publicos")?.addEventListener("click", exportarPublicosCsv);
  }

  async function carregarAdmin() {
    if (!canAdminAny()) return;
    try {
      const total = jogosDaRodada(state.rodada).length;
      const [participantes, ligas] = await Promise.all([
        rpcRows("br_admin_listar_participantes", { p_admin_id: state.usuario.id, p_token: state.token }),
        rpcRows("br_admin_listar_ligas", { p_admin_id: state.usuario.id, p_token: state.token })
      ]);
      state.participantes = participantes;
      state.ligasAdmin = ligas;
      if (!state.adminLigaSelecionada && ligas.length) state.adminLigaSelecionada = ligas[0].liga_id;
      const [progresso, ligaMembros] = await Promise.all([
        rpcRows("br_admin_progresso_rodada_liga", {
          p_admin_id: state.usuario.id,
          p_token: state.token,
          p_temporada: CFG.temporada || 2026,
          p_rodada: state.rodada,
          p_total_jogos: total,
          p_liga_id: state.adminLigaSelecionada || null
        }),
        rpcRows("br_admin_listar_liga_participantes", { p_admin_id: state.usuario.id, p_token: state.token, p_liga_id: null })
      ]);
      state.progresso = progresso;
      state.ligaMembros = ligaMembros;
    } catch (err) {
      console.warn("Admin por liga indisponível; tentando fallback geral", err);
      try {
        const total = jogosDaRodada(state.rodada).length;
        state.progresso = await rpcRows("br_admin_progresso_rodada", { p_admin_id: state.usuario.id, p_token: state.token, p_temporada: CFG.temporada || 2026, p_rodada: state.rodada, p_total_jogos: total });
      } catch (_) { state.progresso = []; }
      state.participantes = state.participantes || [];
      state.ligasAdmin = state.ligasAdmin || [];
      state.ligaMembros = state.ligaMembros || [];
    }
  }

  function pinAleatorio() {
    return String(Math.floor(100000 + Math.random() * 900000));
  }

  async function carregarAuditoria() {
    if (!canAdminAny()) return;
    try {
      const [rel, eventos] = await Promise.all([
        rpcRows("br_admin_relatorio_auditoria_liga", {
          p_admin_id: state.usuario.id,
          p_token: state.token,
          p_temporada: CFG.temporada || 2026,
          p_rodada: state.rodada,
          p_total_jogos: jogosDaRodada(state.rodada).length,
          p_liga_id: state.adminLigaSelecionada || state.ligaAtual || null
        }),
        rpcRows("br_admin_auditoria_eventos_liga", {
          p_admin_id: state.usuario.id,
          p_token: state.token,
          p_temporada: CFG.temporada || 2026,
          p_rodada: state.rodada,
          p_liga_id: state.adminLigaSelecionada || state.ligaAtual || null
        })
      ]);
      state.auditoria = rel;
      state.auditoriaEventos = eventos;
    } catch (err) {
      console.warn("Auditoria por liga indisponível; usando fallback geral", err);
      try {
        const [rel, eventos] = await Promise.all([
          rpcRows("br_admin_relatorio_auditoria", { p_admin_id: state.usuario.id, p_token: state.token, p_temporada: CFG.temporada || 2026, p_rodada: state.rodada, p_total_jogos: jogosDaRodada(state.rodada).length }),
          rpcRows("br_admin_auditoria_eventos", { p_admin_id: state.usuario.id, p_token: state.token, p_temporada: CFG.temporada || 2026, p_rodada: state.rodada })
        ]);
        state.auditoria = rel;
        state.auditoriaEventos = eventos;
      } catch (_) {
        state.auditoria = [];
        state.auditoriaEventos = [];
      }
    }
  }

  async function renderAuditoria() {
    const root = $("#conteudo");
    if (!canAdminAny()) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty">Área restrita ao administrador.</div></section>`;
      return;
    }
    await carregarAuditoria();
    root.innerHTML = `<div class="admin-child-back"><button class="btn ghost" type="button" id="voltar-admin">← Voltar ao Admin</button></div><section class="panel"><div class="panel-inner">
      <div class="kicker">Relatório de auditoria por liga</div><h2>Rodada ${state.rodada} · ${escapeHtml(nomeLigaRelatorio())}</h2>
      <p>Conferência administrativa filtrada pela liga selecionada: preenchimento, hashes, primeira/última gravação e quantidade de alterações. Os placares continuam preservados pelas regras de publicação.</p>
      <div class="export-row"><button class="btn secondary" type="button" id="export-auditoria">⬇️ Exportar auditoria CSV</button></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Participante</th><th>Login</th><th>Preenchido</th><th>%</th><th>Hash</th><th>Primeiro envio</th><th>Última alteração</th><th>Alterações</th></tr></thead><tbody>
        ${state.auditoria.map(r => `<tr><td>${escapeHtml(r.nome)}</td><td>${escapeHtml(r.login)}</td><td>${r.total_palpites}/${r.total_jogos}</td><td>${Number(r.percentual || 0).toFixed(0)}%</td><td class="hash">${escapeHtml(r.hash_fechamento || "—")}</td><td>${fmtDataLonga(r.primeiro_envio)}</td><td>${fmtDataLonga(r.ultimo_envio)}</td><td>${r.alteracoes || 0}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="audit-actions"><button class="btn secondary" type="button" id="copiar-auditoria">copiar resumo</button></div>
    </div></section>
    <section class="panel"><div class="panel-inner"><div class="kicker">Eventos de auditoria</div><h2>Últimas alterações</h2>
      ${state.auditoriaEventos.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Quando</th><th>Participante</th><th>Jogo</th><th>Ação</th><th>Hash</th></tr></thead><tbody>${state.auditoriaEventos.map(e => `<tr><td>${fmtDataLonga(e.criado_em)}</td><td>${escapeHtml(e.membro)}</td><td>${escapeHtml(e.event_id)}</td><td>${escapeHtml(e.acao)}</td><td class="hash">${escapeHtml(e.hash_fechamento || "—")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">Ainda não há eventos de auditoria para esta rodada.</div>`}
    </div></section>`;
    $("#voltar-admin")?.addEventListener("click", async () => { state.aba = "admin"; await refresh(); });
    $("#copiar-auditoria")?.addEventListener("click", copiarResumoAuditoria);
    $("#export-auditoria")?.addEventListener("click", exportarAuditoriaCsv);
  }

  function csvEscape(valor) {
    const s = String(valor ?? "");
    return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function baixarCsv(nomeArquivo, linhas) {
    const csv = linhas.map(row => row.map(csvEscape).join(";")).join("\n") + "\n";
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nomeArquivo;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    status(`✅ CSV GERADO COM SUCESSO! Arquivo ${nomeArquivo} baixado.`, "ok");
    toast(`Arquivo ${nomeArquivo} gerado com sucesso.`, "ok");
  }
  function exportarRankingCsv() {
    const ap = apuracaoRodada(state.rodada);
    const rankingRodada = ap ? rankingRodadaPorLiga(ap, state.ligaAtual) : [];
    const geral = rankingGeralConfiavel();
    const linhas = [["tipo", "liga", "rodada", "pos", "participante", "pontos", "cravadas", "saldo", "resultado", "erros", "vitorias_rodada"]];
    rankingRodada.forEach(r => linhas.push(["rodada", nomeLigaAtual(), state.rodada, r.pos, r.membro, r.pontos, r.cravadas, r.saldos, r.resultados, r.erros, ""]));
    geral.forEach(r => linhas.push(["acumulado", nomeLigaAtual(), "", r.pos, r.membro, r.pontos, r.cravadas, r.saldos, r.resultados, r.erros || 0, r.vitorias_rodada || 0]));
    baixarCsv(`ranking-${ligaSlugAtual()}-rodada-${state.rodada}.csv`, linhas);
  }

  function exportarPublicosCsv() {
    const pontosMap = mapaPontosRodada(state.rodada);
    const linhas = [["liga", "rodada", "participante", "jogo", "palpite", "pontos", "tipo", "hash", "atualizado_em"]];
    state.publicos.forEach(p => {
      const det = pontosMap.get(`${p.membro || ""}::${p.event_id || ""}`) || {};
      linhas.push([nomeLigaAtual(), state.rodada, p.membro, `${p.mandante} x ${p.visitante}`, `${p.placar_mandante} x ${p.placar_visitante}`, det.pontos ?? "", tipoLabel(det.tipo), p.hash_fechamento || "", p.atualizado_em || ""]);
    });
    baixarCsv(`palpites-publicos-${ligaSlugAtual()}-rodada-${state.rodada}.csv`, linhas);
  }

  function exportarAuditoriaCsv() {
    const linhas = [["liga", "rodada", "participante", "login", "preenchido", "total_jogos", "percentual", "hash", "primeiro_envio", "ultimo_envio", "alteracoes"]];
    state.auditoria.forEach(r => linhas.push([nomeLigaRelatorio(), state.rodada, r.nome, r.login, r.total_palpites, r.total_jogos, r.percentual, r.hash_fechamento || "", r.primeiro_envio || "", r.ultimo_envio || "", r.alteracoes || 0]));
    baixarCsv(`auditoria-${slugLigaRelatorio()}-rodada-${state.rodada}.csv`, linhas);
  }

  function exportarProgressoCsv() {
    const linhas = [["liga", "rodada", "participante", "login", "status", "preenchido", "total_jogos", "percentual"]];
    state.progresso.forEach(p => linhas.push([nomeLigaRelatorio(), state.rodada, p.nome, p.login, p.ativo ? "ativo" : "inativo", p.total_palpites, p.total_jogos, p.percentual]));
    baixarCsv(`progresso-${slugLigaRelatorio()}-rodada-${state.rodada}.csv`, linhas);
  }

  async function copiarResumoAuditoria() {
    const linhas = state.auditoria.map(r => `${r.nome}: ${r.total_palpites}/${r.total_jogos} (${Number(r.percentual || 0).toFixed(0)}%) · hash ${r.hash_fechamento || "—"}`);
    const texto = `Auditoria Rodada ${state.rodada}\n` + linhas.join("\n");
    try { await navigator.clipboard.writeText(texto); status("Resumo de auditoria copiado.", "ok"); toast("Resumo de auditoria copiado.", "ok"); }
    catch (_) { status("Não consegui copiar automaticamente; selecione a tabela manualmente.", "warn"); }
  }

  function ligasDoParticipante(participanteId) {
    return (state.ligaMembros || [])
      .filter(m => String(m.participante_id) === String(participanteId) && m.membro_ativo)
      .map(m => m.nome_liga)
      .filter(Boolean);
  }

  function membrosDaLiga(ligaId) {
    return (state.ligaMembros || []).filter(m => String(m.liga_id) === String(ligaId));
  }

  function ligaAdminSelecionadaObj() {
    return (state.ligasAdmin || []).find(l => String(l.liga_id) === String(state.adminLigaSelecionada)) || (state.ligasAdmin || [])[0] || null;
  }

  function renderLigasAdminHtml() {
    const ligas = state.ligasAdmin || [];
    const membros = membrosDaLiga(state.adminLigaSelecionada);
    const selecionada = ligaAdminSelecionadaObj();
    const globalAdmin = isAdminGlobal();
    const participantesOptions = (state.participantes || [])
      .filter(p => p.ativo)
      .map(p => `<option value="${escapeAttr(p.participante_id)}">${escapeHtml(p.nome)} · ${escapeHtml(p.login)}</option>`).join("");
    const formLiga = globalAdmin ? `<form id="admin-liga-form" class="admin-form league-form">
          <input type="hidden" id="admin-liga-id">
          <div class="league-form-head"><strong>Criar nova liga</strong><span>Ex.: amigos da F1, família, pessoal da Caixa, pelada etc.</span></div>
          <div class="two"><label>Nome da liga <input id="admin-liga-nome" placeholder="Ex.: Amigos da F1" required></label><label>Slug <input id="admin-liga-slug" placeholder="amigos-f1"></label></div>
          <label>Descrição <input id="admin-liga-desc" placeholder="Descrição curta da liga"></label>
          <div class="switch-row"><label><input type="checkbox" id="admin-liga-ativa" checked> liga ativa</label></div>
          <div class="actions"><button class="btn" type="submit">➕ criar/salvar liga</button><button class="btn ghost" type="button" id="limpar-liga">nova/limpar</button></div>
          <p class="muted-note">Após salvar, escolha a liga abaixo e adicione os participantes. O ranking será separado por liga.</p>
        </form>` : `<div class="empty"><strong>Admin de liga</strong><p>Você gerencia apenas as ligas em que recebeu papel de administrador. Criação de novas ligas, alteração de janela e criação de usuários ficam restritas ao admin global.</p></div>`;
    const papelOptions = globalAdmin
      ? `<option value="participante">participante</option><option value="admin_liga">admin da liga</option><option value="observador">observador</option>`
      : `<option value="participante">participante</option><option value="observador">observador</option>`;
    return `<article class="panel" style="grid-column:1/-1"><div class="panel-inner">
      <div class="kicker">Ligas</div><h2>Criar e gerenciar ligas</h2>
      <p><strong>Almoço de Sexta</strong> é a liga padrão do grupo. Use esta área para criar outras ligas, adicionar participantes e definir quem é admin de cada uma.</p>
      <div class="league-admin-grid">
        ${formLiga}
        <div class="league-list">
          <div class="table-wrap"><table class="data-table"><thead><tr><th>Liga</th><th>Status</th><th>Participantes</th><th>Permissão</th><th>Ação</th></tr></thead><tbody>
            ${ligas.map(l => `<tr><td><strong>${escapeHtml(l.nome)}</strong><br><small>${escapeHtml(l.slug || "")}</small></td><td>${l.ativa ? "ativa" : "inativa"}</td><td>${l.participantes_ativos || 0}/${l.total_participantes || 0}</td><td>${l.pode_gerir || globalAdmin ? "gerencia" : "visualiza"}</td><td>${globalAdmin ? `<button class="btn secondary" type="button" data-edit-liga="${escapeAttr(l.liga_id)}">editar</button>` : "—"}</td></tr>`).join("") || `<tr><td colspan="5">Nenhuma liga cadastrada.</td></tr>`}
          </tbody></table></div>
        </div>
      </div>
      <div class="league-members-box">
        <div class="form-line wide">
          <label>Liga para administrar
            <select id="admin-liga-selecionada">${ligas.map(l => `<option value="${escapeAttr(l.liga_id)}" ${String(l.liga_id) === String(state.adminLigaSelecionada) ? "selected" : ""}>${escapeHtml(l.nome)}</option>`).join("")}</select>
          </label>
          <form id="admin-add-membro" class="inline-add-member">
            <label>Adicionar participante
              <select id="admin-add-participante">${participantesOptions}</select>
            </label>
            <label>Papel
              <select id="admin-add-papel">${papelOptions}</select>
            </label>
            <button class="btn secondary" type="submit">adicionar à liga</button>
          </form>
        </div>
        <h3>${selecionada ? `Participantes da liga ${escapeHtml(selecionada.nome)}` : "Participantes da liga"}</h3>
        <div class="table-wrap"><table class="data-table"><thead><tr><th>Participante</th><th>Login</th><th>Papel</th><th>Status</th><th>Ação</th></tr></thead><tbody>
          ${membros.length ? membros.map(m => `<tr><td>${escapeHtml(m.nome)}</td><td>${escapeHtml(m.login)}</td><td>${escapeHtml(m.papel)}</td><td>${m.membro_ativo ? "na liga" : "removido"}${m.participante_ativo ? "" : " · usuário inativo"}</td><td>${m.membro_ativo ? `<button class="btn danger" type="button" data-remover-liga="${escapeAttr(m.liga_id)}" data-remover-part="${escapeAttr(m.participante_id)}">remover da liga</button>` : `<button class="btn secondary" type="button" data-reativar-liga="${escapeAttr(m.liga_id)}" data-reativar-part="${escapeAttr(m.participante_id)}">reativar na liga</button>`}</td></tr>`).join("") : `<tr><td colspan="5">Nenhum participante nesta liga.</td></tr>`}
        </tbody></table></div>
      </div>
    </div></article>`;
  }

  function adminEtapasHtml(cfg) {
    const statusAtual = String(cfg.status || "programada").toLowerCase();
    const publicada = rodadaPublica(state.rodada);
    const apurada = statusAtual === "apurada";
    const aberta = rodadaAberta(state.rodada);
    const fechada = ["fechada", "publicada", "apurada", "bloqueada", "encerrada"].includes(statusAtual);
    const etapas = [
      ["Programação criada", Boolean(cfg.abre_em || cfg.fecha_em)],
      ["Apostas abertas", aberta || fechada || publicada || apurada],
      ["Palpites fechados", fechada || publicada || apurada],
      ["Palpites públicos", publicada || apurada],
      ["Apuração concluída", apurada]
    ];
    const primeiraPendente = etapas.findIndex(e => !e[1]);
    return `<ol class="admin-steps">${etapas.map((e, i) => `<li class="${e[1] ? "done" : i === primeiraPendente ? "current" : "pending"}"><span aria-hidden="true">${e[1] ? "✓" : i === primeiraPendente ? "●" : "○"}</span><strong>${e[0]}</strong></li>`).join("")}</ol>`;
  }

  function adminAcaoContextualHtml(cfg) {
    const statusAtual = String(cfg.status || "programada").toLowerCase();
    const aberta = rodadaAberta(state.rodada);
    if (statusAtual === "apurada") return `<div class="admin-next-action done"><strong>✅ Rodada concluída</strong><span>Palpites publicados e apuração marcada como concluída.</span></div>`;
    if (rodadaPublica(state.rodada)) return `<div class="admin-next-action"><strong>🧮 Apuração em andamento</strong><span>O ranking é atualizado pelo workflow conforme os jogos terminam. Não é necessário marcar manualmente.</span></div>`;
    if (aberta || statusAtual === "aberta") return `<div class="admin-next-action"><strong>Próxima ação recomendada</strong><span>Encerre as apostas somente quando quiser bloquear novos envios.</span><button class="btn danger" type="button" id="fechar-rodada">🔒 Encerrar apostas agora</button></div>`;
    if (["fechada", "bloqueada", "encerrada"].includes(statusAtual)) return `<div class="admin-next-action"><strong>Próxima ação recomendada</strong><span>As apostas estão encerradas. Libere os palpites públicos quando o sigilo puder terminar.</span><button class="btn secondary" type="button" id="publicar-rodada">📣 Liberar palpites públicos</button></div>`;
    return `<div class="admin-next-action"><strong>Próxima ação recomendada</strong><span>Salve a programação ou libere as apostas imediatamente.</span><button class="btn secondary" type="button" id="abrir-rodada">🔓 Abrir apostas agora</button></div>`;
  }

  async function renderAdmin() {
    await carregarAdmin();
    const cfg = configEfetiva(state.rodada);
    const root = $("#conteudo");
    if (!canAdminAny()) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty">Área restrita ao administrador.</div></section>`;
      return;
    }
    const globalAdmin = isAdminGlobal();
    const painelAdministracaoAnual = globalAdmin ? `<article class="panel admin-section" id="admin-anual"><div class="panel-inner">
        <div class="kicker">Administração integrada</div><h2>Ranking anual e aniversários</h2>
        <p>As ferramentas históricas continuam em uma área separada e protegida.</p>
        <div class="actions"><a class="btn secondary" href="./?brasileirao=1&view=participantes&admin=1">⚙️ Abrir administração anual</a></div>
      </div></article>` : "";
    const painelParticipantes = globalAdmin ? `<article class="panel admin-section" id="admin-participantes"><div class="panel-inner">
        <div class="kicker">Participantes</div><h2>Criar ou alterar acesso</h2>
        <form id="admin-participante" class="admin-form">
          <input type="hidden" id="admin-participante-id">
          <input type="hidden" id="admin-nome-atual">
          <label>Usuário/login <input id="admin-login" required placeholder="ex.: laercio" autocomplete="off"></label>
          <div class="actions"><button class="btn" type="submit">Salvar participante</button><button class="btn ghost" type="button" id="limpar-admin">Limpar formulário</button></div>
          <div class="switch-row"><label><input type="checkbox" id="admin-e-admin"> administrador global</label><label><input type="checkbox" id="admin-ativo" checked> ativo</label></div>
          <p class="muted-note">Ao salvar, o sistema gera um PIN novo e oferece o envio por WhatsApp. Para preservar o histórico, inative o acesso ou remova o participante da liga.</p>
        </form>
      </div></article>` : `<article class="panel admin-section" id="admin-participantes"><div class="panel-inner empty"><strong>Perfil: admin de liga</strong><p>Você acompanha os participantes das suas ligas. A criação de usuários e a janela global ficam com o administrador global.</p></div></article>`;
    const painelRodada = globalAdmin ? `<article class="panel admin-section admin-window-panel" id="admin-janela"><div class="panel-inner">
        <div class="kicker">1. Janela e publicação</div><div class="admin-window-title"><div><h2>Rodada ${state.rodada}</h2><p>Configure os horários e siga apenas a próxima ação indicada pelo sistema.</p></div><span class="badge ${statusJanela(state.rodada).classe}">${escapeHtml(statusJanela(state.rodada).texto)}</span></div>
        ${adminEtapasHtml(cfg)}
        <form id="admin-rodada" class="admin-form admin-window-form">
          <div class="two"><label>Abre em <input id="cfg-abre" type="datetime-local" value="${toDatetimeLocal(cfg.abre_em)}"></label><label>Fecha em <input id="cfg-fecha" type="datetime-local" value="${toDatetimeLocal(cfg.fecha_em)}"></label></div>
          <div class="two"><label>Publica em <input id="cfg-publica" type="datetime-local" value="${toDatetimeLocal(cfg.publica_em)}"></label><label>Observação <input id="cfg-obs" value="${escapeAttr(cfg.observacao || "")}" placeholder="Informação opcional para a administração"></label></div>
          <div class="actions admin-save-row"><button class="btn" type="submit">💾 Salvar programação</button><span class="muted-note">Salva datas e observação sem executar uma mudança de etapa inesperada.</span></div>
          ${adminAcaoContextualHtml(cfg)}
          <details class="admin-advanced"><summary>Opções avançadas de emergência</summary><div class="admin-advanced-body"><p class="muted-note">Use apenas para corrigir um estado excepcional. O fluxo normal deve seguir a ação recomendada acima.</p><label>Status manual <select id="cfg-status"><option value="programada">programada</option><option value="aberta">aberta</option><option value="fechada">fechada</option><option value="publicada">publicada</option><option value="apurada">apurada</option><option value="bloqueada">bloqueada</option></select></label><button class="btn secondary" type="button" id="aplicar-status-manual">Aplicar status manual</button></div></details>
          <div id="admin-inline-feedback" class="admin-inline-feedback" aria-live="polite">Última configuração carregada: ${escapeHtml(statusJanela(state.rodada).detalhe)}.</div>
        </form>
      </div></article>` : `<article class="panel admin-section admin-window-panel" id="admin-janela"><div class="panel-inner"><div class="kicker">1. Janela e publicação</div><h2>Rodada ${state.rodada}</h2><p class="muted-note">A janela é global e somente o administrador global pode alterá-la.</p><p><span class="badge ${statusJanela(state.rodada).classe}">${escapeHtml(statusJanela(state.rodada).detalhe)}</span></p></div></article>`;
    const painelProgresso = `<article class="panel admin-section" id="admin-preenchimento"><div class="panel-inner">
        <div class="kicker">2. Preenchimento</div><h2>Progresso sem revelar placares</h2>
        <p>O percentual considera a liga selecionada. Antes da publicação, o administrador acompanha apenas a quantidade preenchida.</p>
        <div class="export-row"><button class="btn secondary" type="button" id="export-progresso">⬇️ Exportar progresso CSV</button></div>
        <div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Participante</th><th>Login</th><th>Status</th><th>Ligas</th><th>Preenchido</th><th>%</th><th>Ações</th></tr></thead><tbody>
          ${state.progresso.map(p => `<tr><td>${escapeHtml(p.nome)}</td><td>${escapeHtml(p.login)}</td><td>${p.ativo ? "ativo" : "inativo"}${p.admin ? " · admin" : ""}</td><td>${ligasDoParticipante(p.participante_id).map(escapeHtml).join(", ") || "—"}</td><td>${p.total_palpites}/${p.total_jogos}</td><td><div class="progress-wrap"><div class="progress-bar" style="width:${Math.max(0, Math.min(100, Number(p.percentual || 0)))}%"></div></div></td><td class="action-cell">${globalAdmin ? `<button class="btn secondary" type="button" data-edit="${escapeAttr(p.participante_id)}">editar</button>${p.ativo ? `<button class="btn danger" type="button" data-inativar="${escapeAttr(p.participante_id)}">inativar</button>` : `<button class="btn secondary" type="button" data-reativar="${escapeAttr(p.participante_id)}">reativar</button>`}` : `<span class="muted-note">gerencie pela liga</span>`}</td></tr>`).join("")}
        </tbody></table></div>
      </div></article>`;
    const painelAuditoria = `<article class="panel admin-section" id="admin-auditoria"><div class="panel-inner"><div class="kicker">4. Auditoria</div><h2>Conferir registros da rodada</h2><p>Visualize hashes, horários e alterações sem expor palpites antes da publicação.</p><div class="actions"><button class="btn secondary" type="button" id="abrir-auditoria-admin">🧾 Abrir auditoria detalhada</button></div></div></article>`;
    const painelLigas = `<div class="admin-section admin-ligas-last" id="admin-ligas"><div class="admin-section-label"><span>5. Ligas</span><small>Área de uso menos frequente, mantida por último.</small></div>${renderLigasAdminHtml()}</div>`;
    root.innerHTML = `<section class="admin-workspace">
      <nav class="admin-section-nav" aria-label="Seções administrativas"><a href="#admin-janela">1. Janela</a><a href="#admin-preenchimento">2. Preenchimento</a><a href="#admin-participantes">3. Participantes</a><a href="#admin-auditoria">4. Auditoria</a><a href="#admin-ligas">5. Ligas</a></nav>
      <section class="admin-grid">
        ${painelRodada}
        ${painelProgresso}
        ${painelParticipantes}
        ${painelAdministracaoAnual}
        ${painelAuditoria}
        ${painelLigas}
      </section>
    </section>`;
    if (globalAdmin) {
      $("#cfg-status").value = cfg.status || "programada";
      $("#limpar-admin")?.addEventListener("click", () => { limparFormParticipante(); status("Formulário de participante limpo.", "ok"); toast("Formulário limpo.", "ok"); });
      $("#admin-participante")?.addEventListener("submit", salvarParticipanteAdmin);
      $("#admin-rodada")?.addEventListener("submit", salvarRodadaAdmin);
      $("#abrir-rodada")?.addEventListener("click", async () => { if (!confirmarAcao(`Abrir as apostas da rodada ${state.rodada} agora?`)) return; await abrirRodadaAgora(); });
      $("#publicar-rodada")?.addEventListener("click", async () => { if (!confirmarAcao(`Liberar os palpites públicos da rodada ${state.rodada}?`)) return; await alterarStatusRodada("publicada"); });
      $("#fechar-rodada")?.addEventListener("click", async () => { if (!confirmarAcao(`Encerrar as apostas da rodada ${state.rodada} agora? Depois disso, ninguém poderá alterar palpites.`)) return; await alterarStatusRodada("fechada"); });
      $("#aplicar-status-manual")?.addEventListener("click", async () => { const novo = $("#cfg-status").value; if (!confirmarAcao(`Aplicar manualmente o status “${novo}” à rodada ${state.rodada}?`)) return; await alterarStatusRodada(novo); });
      $$('[data-edit]').forEach(btn => btn.addEventListener("click", () => preencherParticipante(btn.dataset.edit)));
      $$('[data-inativar]').forEach(btn => btn.addEventListener("click", () => alterarAtivoParticipante(btn.dataset.inativar, false)));
      $$('[data-reativar]').forEach(btn => btn.addEventListener("click", () => alterarAtivoParticipante(btn.dataset.reativar, true)));
      $("#admin-liga-form")?.addEventListener("submit", salvarLigaAdmin);
      $("#limpar-liga")?.addEventListener("click", () => { limparFormLiga(); $("#admin-liga-nome")?.focus(); status("Formulário de liga limpo.", "ok"); toast("Formulário de liga limpo.", "ok"); });
      $$('[data-edit-liga]').forEach(btn => btn.addEventListener("click", () => preencherLiga(btn.dataset.editLiga)));
    }
    $("#abrir-auditoria-admin")?.addEventListener("click", async () => { state.aba = "auditoria"; await refresh(); });
    $("#export-progresso")?.addEventListener("click", exportarProgressoCsv);
    $("#admin-liga-selecionada")?.addEventListener("change", async ev => { state.adminLigaSelecionada = ev.target.value; await renderAdmin(); });
    $("#admin-add-membro")?.addEventListener("submit", adicionarParticipanteLiga);
    $$('[data-remover-liga]').forEach(btn => btn.addEventListener("click", () => removerParticipanteLiga(btn.dataset.removerLiga, btn.dataset.removerPart, false)));
    $$('[data-reativar-liga]').forEach(btn => btn.addEventListener("click", () => removerParticipanteLiga(btn.dataset.reativarLiga, btn.dataset.reativarPart, true)));
  }

  function limparFormLiga() {
    $("#admin-liga-id").value = "";
    $("#admin-liga-nome").value = "";
    $("#admin-liga-slug").value = "";
    $("#admin-liga-desc").value = "";
    $("#admin-liga-ativa").checked = true;
  }

  function preencherLiga(id) {
    const l = (state.ligasAdmin || []).find(x => String(x.liga_id) === String(id));
    if (!l) return;
    state.adminLigaSelecionada = l.liga_id;
    $("#admin-liga-id").value = l.liga_id;
    $("#admin-liga-nome").value = l.nome || "";
    $("#admin-liga-slug").value = l.slug || "";
    $("#admin-liga-desc").value = l.descricao || "";
    $("#admin-liga-ativa").checked = Boolean(l.ativa);
    $("#admin-liga-nome").scrollIntoView({ behavior: "smooth", block: "center" });
    status(`✏️ Editando a liga ${l.nome || ""}. Ajuste os campos e clique em salvar.`, "warn");
  }

  async function salvarLigaAdmin(ev) {
    ev.preventDefault();
    try {
      status("Salvando liga...", "warn");
      const rows = await rpcRows("br_admin_salvar_liga", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_liga_id: $("#admin-liga-id").value || null,
        p_nome: $("#admin-liga-nome").value.trim(),
        p_slug: $("#admin-liga-slug").value.trim() || null,
        p_descricao: $("#admin-liga-desc").value.trim() || null,
        p_ativa: $("#admin-liga-ativa").checked
      });
      const liga = rows[0];
      if (liga?.liga_id) {
        state.adminLigaSelecionada = liga.liga_id;
        state.ligaAtual = liga.liga_id;
      }
      await carregarLigas();
      renderLigaBox();
      status("✅ LIGA GRAVADA COM SUCESSO! Agora adicione os participantes abaixo.", "ok");
      toast("Liga salva com sucesso.", "ok");
      await renderAdmin();
    } catch (err) { status(err.message || "Falha ao salvar liga.", "err"); toast(err.message || "Falha ao salvar liga.", "err"); }
  }

  async function adicionarParticipanteLiga(ev) {
    ev.preventDefault();
    try {
      const ligaId = $("#admin-liga-selecionada").value;
      const participanteId = $("#admin-add-participante").value;
      if (!ligaId || !participanteId) throw new Error("Selecione liga e participante.");
      await rpcRows("br_admin_vincular_participante_liga", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_liga_id: ligaId,
        p_participante_id: participanteId,
        p_papel: $("#admin-add-papel").value || "participante",
        p_ativo: true
      });
      status("✅ PARTICIPANTE ADICIONADO À LIGA COM SUCESSO!", "ok");
      toast("Participante adicionado à liga.", "ok");
      await renderAdmin();
    } catch (err) { status(err.message || "Falha ao adicionar participante à liga.", "err"); toast(err.message || "Falha ao adicionar participante à liga.", "err"); }
  }

  async function removerParticipanteLiga(ligaId, participanteId, reativar) {
    try {
      const msg = reativar ? "Reativar participante nesta liga?" : "Remover participante desta liga? O histórico antigo será preservado.";
      if (!confirm(msg)) return;
      await rpcRows("br_admin_vincular_participante_liga", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_liga_id: ligaId,
        p_participante_id: participanteId,
        p_papel: "participante",
        p_ativo: Boolean(reativar)
      });
      status(reativar ? "✅ REATIVADO NA LIGA COM SUCESSO!" : "✅ REMOVIDO DA LIGA COM SUCESSO! Histórico preservado.", "ok");
      toast(reativar ? "Participante reativado na liga." : "Participante removido da liga. Histórico preservado.", "ok");
      await renderAdmin();
    } catch (err) { status(err.message || "Falha ao alterar participante na liga.", "err"); toast(err.message || "Falha ao alterar participante na liga.", "err"); }
  }

  async function alterarAtivoParticipante(participanteId, ativo) {
    try {
      const pergunta = ativo ? "Reativar este participante?" : "Inativar este participante? Ele não conseguirá mais entrar, mas o histórico será preservado.";
      if (!confirm(pergunta)) return;
      await rpcRows("br_admin_alterar_status_participante", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_participante_id: participanteId,
        p_ativo: Boolean(ativo)
      });
      status(ativo ? "✅ PARTICIPANTE REATIVADO COM SUCESSO!" : "✅ PARTICIPANTE INATIVADO COM SUCESSO! Histórico preservado.", "ok");
      toast(ativo ? "Participante reativado." : "Participante inativado. Histórico preservado.", "ok");
      await renderAdmin();
    } catch (err) { status(err.message || "Falha ao alterar status do participante.", "err"); toast(err.message || "Falha ao alterar status do participante.", "err"); }
  }

  function toDatetimeLocal(iso) {
    const d = parseData(iso);
    if (!d) return "";
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function escapeAttr(s) { return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); }

  function limparFormParticipante() {
    $("#admin-participante-id").value = "";
    $("#admin-nome-atual").value = "";
    $("#admin-login").value = "";
    $("#admin-e-admin").checked = false;
    $("#admin-ativo").checked = true;
  }

  function preencherParticipante(id) {
    const p = state.participantes.find(x => String(x.participante_id || x.id) === String(id));
    if (!p) return;
    $("#admin-participante-id").value = p.participante_id || p.id;
    $("#admin-nome-atual").value = p.nome || "";
    $("#admin-login").value = p.login || "";
    $("#admin-e-admin").checked = Boolean(p.admin);
    $("#admin-ativo").checked = Boolean(p.ativo);
    $("#admin-login").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#admin-login").focus();
    status(`✏️ Editando ${p.nome || p.login}. Ao salvar, um PIN novo será gerado.`, "warn");
  }

  function nomeAPartirDoLogin(login) {
    return String(login || "")
      .replace(/[._-]+/g, " ")
      .trim()
      .split(/\s+/)
      .map(parte => parte ? parte.charAt(0).toUpperCase() + parte.slice(1) : parte)
      .join(" ");
  }

  function mensagemWhatsappAcesso(nome, login, pin) {
    return [
      "🏆 Bolão Brasileirão 2026 — Almoço de Sexta",
      "",
      `Fala, ${nome}! Seu acesso está pronto:`,
      `👤 Usuário: ${login}`,
      `🔑 PIN: ${pin}`,
      "",
      "Acesse o site: https://brasileirao2026almoco.com.br/apostas.html e faça suas apostas! ⚽🍀"
    ].join("\n");
  }

  function abrirWhatsappComMensagem(texto) {
    const url = "https://wa.me/?text=" + encodeURIComponent(texto);
    const win = global.open(url, "_blank", "noopener");
    if (!win) global.location.href = url;
  }

  function mensagemErroParticipante(err) {
    const msg = String(err?.message || err || "");
    if (/duplicate|unique|br_participantes_login|login/i.test(msg) && /existe|duplicate|unique|duplic/i.test(msg)) {
      return "Já existe participante com esse usuário/login. Atualize a lista e salve de novo para renovar o PIN dele.";
    }
    if (/ambiguous|ambígua|42702/i.test(msg)) {
      return "O banco ainda está com a função antiga. Rode o script supabase/brasileirao_apostas_exec16_hotfix_participantes.sql no SQL Editor do Supabase e tente de novo.";
    }
    if (/pin/i.test(msg)) {
      return "Não foi possível gerar/salvar o PIN. Tente novamente.";
    }
    if (/Acesso admin inválido|Sessão inválida|JWT|token/i.test(msg)) {
      return "Sessão de administrador inválida ou expirada. Saia e entre novamente antes de salvar.";
    }
    return msg || "Falha ao salvar participante.";
  }

  async function salvarParticipanteAdmin(ev) {
    ev.preventDefault();
    try {
      const login = String($("#admin-login").value || "").trim().toLowerCase();
      if (!login) throw new Error("Informe o usuário/login antes de salvar.");

      const idInformado = $("#admin-participante-id").value || null;
      const existente = (state.participantes || []).find(p =>
        idInformado
          ? String(p.participante_id || p.id) === String(idInformado)
          : String(p.login || "").trim().toLowerCase() === login
      ) || null;
      const participanteId = idInformado || (existente ? (existente.participante_id || existente.id) : null);
      const atualizado = Boolean(participanteId);
      const veioDoEditar = Boolean(idInformado);

      const nome = String($("#admin-nome-atual").value || "").trim()
        || (existente && existente.nome)
        || nomeAPartirDoLogin(login);
      const pin = pinAleatorio();

      // Via botão "editar" as caixas refletem o participante e mandam a palavra final.
      // Digitando só o login de alguém que já existe, preserva admin/ativo atuais
      // para não rebaixar nem inativar ninguém sem querer.
      const adminFlag = veioDoEditar ? $("#admin-e-admin").checked : (existente ? Boolean(existente.admin) : $("#admin-e-admin").checked);
      const ativoFlag = veioDoEditar ? $("#admin-ativo").checked : (existente ? true : $("#admin-ativo").checked);

      status(atualizado ? "Alterando participante e gerando novo PIN..." : "Criando participante e gerando PIN...", "warn");
      await rpcRows("br_admin_salvar_participante", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_participante_id: participanteId,
        p_nome: nome,
        p_login: login,
        p_pin: pin,
        p_admin: adminFlag,
        p_ativo: ativoFlag
      });

      limparFormParticipante();
      await renderAdmin();
      status(`✅ PARTICIPANTE ${atualizado ? "ALTERADO" : "CRIADO"} COM SUCESSO! Usuário: ${login} · PIN: ${pin}. Envie apenas para a pessoa.`, "ok");
      toast(`Participante ${atualizado ? "alterado" : "criado"} com sucesso.`, "ok");

      const enviarWhats = confirm(
        `PARTICIPANTE ${atualizado ? "ALTERADO" : "CRIADO"}!\n` +
        `Usuário: ${login}\nPIN: ${pin}\n\n` +
        "Deseja mandar msg pra ele pelo WhatsApp?"
      );
      if (enviarWhats) abrirWhatsappComMensagem(mensagemWhatsappAcesso(nome, login, pin));
    } catch (err) { const msg = mensagemErroParticipante(err); status(msg, "err"); toast(msg, "err"); }
  }

  async function salvarRodadaAdmin(ev) {
    ev.preventDefault();
    await salvarConfigRodada($("#cfg-status").value);
  }

  async function alterarStatusRodada(statusNovo) {
    $("#cfg-status").value = statusNovo;
    await salvarConfigRodada(statusNovo);
  }

  async function abrirRodadaAgora() {
    const abreEl = $("#cfg-abre");
    if (abreEl) {
      const abre = abreEl.value ? new Date(abreEl.value) : null;
      if (!abre || abre > new Date()) abreEl.value = toDatetimeLocal(new Date().toISOString());
    }
    $("#cfg-status").value = "aberta";
    await salvarConfigRodada("aberta");
  }

  function mensagemStatusRodada(statusNovo) {
    const r = state.rodada;
    const mapa = {
      aberta: `🔓 RODADA ${r} ABERTA COM SUCESSO! Apostas liberadas para os participantes agora.`,
      publicada: `📣 RODADA ${r} PUBLICADA COM SUCESSO! Ranking e palpites liberados para todos.`,
      apurada: `🧮 RODADA ${r} MARCADA COMO APURADA COM SUCESSO!`,
      fechada: `🔒 RODADA ${r} FECHADA COM SUCESSO! Ninguém mais envia palpites.`,
      bloqueada: `🔒 RODADA ${r} BLOQUEADA COM SUCESSO!`,
      programada: `✅ JANELA GRAVADA COM SUCESSO! Rodada ${r} programada.`,
      futura: `✅ JANELA GRAVADA COM SUCESSO! Rodada ${r} marcada como futura.`
    };
    return mapa[String(statusNovo || "").toLowerCase()] || `✅ JANELA DA RODADA ${r} GRAVADA COM SUCESSO!`;
  }

  async function salvarConfigRodada(statusNovo) {
    try {
      status("Salvando janela da rodada...", "warn");
      await rpcRows("br_admin_definir_rodada", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_temporada: CFG.temporada || 2026,
        p_rodada: state.rodada,
        p_abre_em: $("#cfg-abre").value ? new Date($("#cfg-abre").value).toISOString() : null,
        p_fecha_em: $("#cfg-fecha").value ? new Date($("#cfg-fecha").value).toISOString() : null,
        p_publica_em: $("#cfg-publica").value ? new Date($("#cfg-publica").value).toISOString() : null,
        p_status: statusNovo,
        p_observacao: $("#cfg-obs").value || null
      });
      await carregarConfigsSupabase();
      const mensagem = mensagemStatusRodada(statusNovo);
      status(mensagem, "ok");
      toast(mensagem.replace(/^[^A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9]+/i, ""), "ok");
      await refresh();
    } catch (err) {
      const msg = String(err?.message || err || "");
      if (/ambiguous|ambígua|42702/i.test(msg)) {
        status("O banco ainda está com a função antiga da janela. Rode supabase/brasileirao_apostas_exec17_janela_rodada.sql no SQL Editor do Supabase e tente de novo.", "err");
        toast("Não foi possível salvar a janela. Atualize a função do banco.", "err");
      } else {
        status(msg || "Falha ao salvar janela.", "err");
        toast(msg || "Falha ao salvar janela.", "err");
      }
    }
  }

  function renderConteudo() {
    renderResumo();
    renderRodadas();
    $$("[data-aba]").forEach(btn => {
      const ativo = btn.dataset.aba === state.aba || (btn.dataset.aba === "admin" && state.aba === "auditoria");
      btn.classList.toggle("active", ativo);
      btn.setAttribute("aria-selected", String(ativo));
    });
    if (state.aba === "meus") return renderMeus();
    if (state.aba === "ranking") { carregarPublicos().then(() => renderRanking()); return; }
    if (state.aba === "publico") return renderPublico();
    if (state.aba === "auditoria") return renderAuditoria();
    if (state.aba === "admin") return renderAdmin();
    return renderApostas();
  }

  async function refresh() {
    await carregarConfigsSupabase();
    resolverRodadaAutomatica(false);
    if (state.usuario) {
      await carregarLigas();
      await carregarMeusPalpites();
    }
    renderLogin();
    renderConteudo();
    renderLigaBox();
  }

  async function trocarRodada(rodada, manual = true) {
    state.rodada = Number(rodada);
    state.rodadaEscolhidaManualmente = Boolean(manual && Number(state.rodada) !== Number(state.rodadaAutomatica));
    await refresh();
  }

  async function voltarRodadaAtual() {
    state.rodadaEscolhidaManualmente = false;
    resolverRodadaAutomatica(true);
    await refresh();
    toast(`Você voltou para a rodada atual: R${state.rodadaAutomatica}.`, "ok");
  }

  async function onLogin(ev) {
    ev.preventDefault();
    try {
      const login = $("#login-usuario").value.trim();
      const pin = $("#login-pin").value.trim();
      if (!login || !pin) throw new Error("Informe usuário e PIN.");
      status("Validando usuário/PIN...", "warn");
      const rows = await rpcRows("br_login_participante", { p_login: login, p_pin: pin });
      const u = rows[0];
      if (!u || !u.token) throw new Error("Login não retornou sessão válida.");
      saveSession({ id: u.id || u.participante_id, nome: u.nome, login: u.login, admin: Boolean(u.admin) }, u.token);
      status(`Bem-vindo, ${u.nome}.`, "ok");
      const retorno = retornoSeguroAposLogin();
      if (retorno) {
        global.location.replace(retorno);
        return;
      }
      await carregarLigas();
      state.aba = "apostas";
      state.rodadaEscolhidaManualmente = false;
      await refresh();
    } catch (err) {
      console.error(err);
      clearSession();
      status(err.message || "Usuário ou PIN inválido.", "err");
      renderLogin();
    }
  }

  function bindBaseEvents() {
    $("#form-login")?.addEventListener("submit", onLogin);
    $("#voltar-rodada-atual")?.addEventListener("click", voltarRodadaAtual);
    $$("[data-aba]").forEach(btn => btn.addEventListener("click", async () => {
      state.aba = btn.dataset.aba;
      await refresh();
    }));
  }

  async function init() {
    const abaUrl = abaInicialPorUrl();
    if (abaUrl) state.aba = abaUrl;
    state.supabase = initSupabase();
    bindBaseEvents();
    await carregarBase();
    const sess = sessionPayload();
    if (sess && sess.usuario && sess.token) {
      state.usuario = sess.usuario;
      state.token = sess.token;
    }
    if (!state.supabase) {
      clearSession();
      status("Supabase não inicializado. Confira js/br-config.js.", "err");
    } else if (state.usuario) {
      status("Validando sessão salva...", "warn");
      await validarSessaoAtual();
    }
    if (state.usuario && !abaUrl) {
      await carregarLigas();
      state.aba = "apostas";
      state.rodadaEscolhidaManualmente = false;
    }
    if (!state.usuario && state.supabase) {
      status("Entre com usuário e PIN para acessar a área restrita.", "warn");
    }
    await refresh();
    iniciarAutoRefresh();
  }

  document.addEventListener("DOMContentLoaded", init);
})(window, document);

/* ========================================================================== 
   br-apostas.js — Apostas logadas do Brasileirão 2026
   Execuções 1–5: UX, blocos automáticos independentes, apostas progressivas, apuração e rankings.
   ========================================================================== */
(function (global, document) {
  "use strict";

  const CFG = global.BR_CFG || {};
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const STORAGE_KEY = "brApostasSessaoV2";
  const BLOCOS_3_RODADAS = [
    { inicio: 21, fim: 23, nome: "Bloco 21–23" },
    { inicio: 24, fim: 26, nome: "Bloco 24–26" },
    { inicio: 27, fim: 29, nome: "Bloco 27–29" },
    { inicio: 30, fim: 32, nome: "Bloco 30–32" },
    { inicio: 33, fim: 35, nome: "Bloco 33–35" },
    { inicio: 36, fim: 38, nome: "Bloco 36–38" }
  ];

  const state = {
    supabase: null,
    usuario: null,
    token: "",
    jogosJson: null,
    resultadosJson: null,
    espnEventosJson: null,
    calendarioCompletoJson: null,
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
    blocosApostas: [],
    blocosInfraDisponivel: false,
    blocoAdminSelecionado: null,
    comprovanteBloco: null,
    progressoBloco: null,
    exec3InfraDisponivel: false,
    filtroRodadaBloco: "todos",
    publicoFiltro: "bloco",
    draftDirty: false,
    draftRestaurado: false,
    salvandoPalpites: false,
    rankingExportAtual: null,
    toastTimer: null,
    abaInicialExplicita: false,
    contextoInicialExplicito: false,
    abaEscolhidaManualmente: false,
    destinoCronologicoResolvido: false
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

  function contextoInicialPorUrl() {
    try {
      const params = new URLSearchParams(global.location.search || "");
      const raw = String(params.get("bloco") || params.get("rodada") || "").trim();
      if (!raw) return null;
      if (raw === "20" || raw.toUpperCase() === "R20") return 20;
      const match = raw.match(/^(?:R)?(21|24|27|30|33|36)(?:[-–](23|26|29|32|35|38))?$/i);
      if (!match) return null;
      const inicio = Number(match[1]);
      const esperadoFim = inicio + 2;
      if (match[2] && Number(match[2]) !== esperadoFim) return null;
      return inicio;
    } catch (err) {
      return null;
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

  const BR_RAW_MAIN = "https://raw.githubusercontent.com/LAERCIOREHEM/BRASILEIRAO2026ALMOCO/main/";
  const BR_CRITICAL_JSON = new Set([
    "jogos.json",
    "resultados.json",
    "espn_eventos.json",
    "dados-br/calendario-completo.json",
    "dados-br/apuracao.json",
    "dados-br/ranking-apostas.json"
  ]);

  function cacheBust(url) {
    const sep = String(url).includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function caminhoRelativo(url) {
    return String(url || "").split("?")[0].replace(/^\/+/, "");
  }

  async function fetchJson(url, fallback) {
    const path = caminhoRelativo(url);
    const candidatos = BR_CRITICAL_JSON.has(path)
      ? [`${BR_RAW_MAIN}${path}`, url]
      : [url];
    let ultimoErro = null;
    for (const candidato of candidatos) {
      try {
        const res = await fetch(cacheBust(candidato), { cache: "no-store", headers: { "Cache-Control": "no-cache", "Pragma": "no-cache" } });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return await res.json();
      } catch (err) { ultimoErro = err; }
    }
    console.warn("Falha ao buscar", url, ultimoErro);
    return fallback;
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
  function chaveConfrontoTimes(j) {
    const mandante = normalizarTexto(timeNome(j && j.mandante));
    const visitante = normalizarTexto(timeNome(j && j.visitante));
    return mandante && visitante ? `${mandante}|${visitante}` : "";
  }
  function chaveConfrontoRodada(j) {
    const rodada = Number(j && j.rodada || 0);
    const times = chaveConfrontoTimes(j);
    return rodada && times ? `${rodada}|${times}` : "";
  }
  function idSinteticoJogo(j) {
    const rodada = Number(j && j.rodada || 0);
    const mandante = normalizarTexto(timeNome(j && j.mandante));
    const visitante = normalizarTexto(timeNome(j && j.visitante));
    return `fg-${Number(CFG.temporada || 2026)}-r${rodada}-${mandante}-${visitante}`;
  }
  function jogoChave(j) { return `${normalizarTexto(timeNome(j.mandante))}-${normalizarTexto(timeNome(j.visitante))}-${String(j.data_iso || "").slice(0, 10)}`; }
  function jogoUidCanonico(j) {
    const rodada = Number(j && j.rodada || 0);
    const mandante = String(timeNome(j && j.mandante) || "").trim().toLocaleLowerCase("pt-BR");
    const visitante = String(timeNome(j && j.visitante) || "").trim().toLocaleLowerCase("pt-BR");
    return `${Number(CFG.temporada || 2026)}|${rodada}|${mandante}|${visitante}`;
  }

  function jogoComHorarioInconsistente(j) {
    if (!j) return false;
    const data = parseData(j.data_iso);
    if (!data) return false;
    const estado = String(j.estado || j.state || "").trim().toLowerCase();
    const statusFonte = String(j.status || "").trim().toLowerCase();
    const concluido = j.concluido === true || j.completed === true;
    const relogioZerado = ["", "0", "0'", "0:00", "0’"].includes(statusFonte);
    return estado === "post" && !concluido && relogioZerado && data.getTime() > Date.now() + 15 * 60 * 1000;
  }

  function jogoTemHorarioConfiavel(j) {
    if (!j || j.data_definir === true) return false;
    if (!parseData(j.data_iso)) return false;
    return !jogoComHorarioInconsistente(j);
  }

  function normalizarHorarioJogo(j) {
    if (!j || !jogoComHorarioInconsistente(j)) return j;
    // A ESPN às vezes devolve um evento FUTURO como state=post, completed=false,
    // relógio 0' e um horário artificial. Esse horário não pode comandar a
    // abertura/fechamento do bolão nem aparecer como programação confirmada.
    return {
      ...j,
      data_iso: null,
      data_definir: true,
      estado: "pre",
      status: "Data a definir",
      finalizado_em: null,
      horario_descartado_inconsistente: true
    };
  }

  function compararJogosPorData(a, b) {
    const da = jogoTemHorarioConfiavel(a) ? parseData(a.data_iso) : null;
    const db = jogoTemHorarioConfiavel(b) ? parseData(b.data_iso) : null;
    if (da && db && da.getTime() !== db.getTime()) return da - db;
    if (da && !db) return -1;
    if (!da && db) return 1;
    const ra = Number(a && a.rodada || 0);
    const rb = Number(b && b.rodada || 0);
    if (ra !== rb) return ra - rb;
    return `${timeNome(a && a.mandante)}-${timeNome(a && a.visitante)}`.localeCompare(`${timeNome(b && b.mandante)}-${timeNome(b && b.visitante)}`, "pt-BR");
  }

  function fmtDataJogo(j) {
    return jogoTemHorarioConfiavel(j) ? fmtData(j.data_iso) : "data a definir";
  }


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
      let arr = jogos.slice().sort(compararJogosPorData);
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
    return saida.sort(compararJogosPorData);
  }

  function timeCalendario(nome) {
    const clube = (state.clubesPorNome && state.clubesPorNome[nome]) || {};
    return { nome: String(nome || ""), escudo: clube.escudo || "", sigla: clube.sigla || "" };
  }

  function todosJogos() {
    const a = (state.jogosJson && state.jogosJson.jogos) || [];
    const b = (state.resultadosJson && state.resultadosJson.resultados) || [];
    const c = ((state.espnEventosJson && state.espnEventosJson.eventos) || []).map(e => ({
      event_id: e.event_id,
      rodada: e.rodada,
      data_iso: e.data_iso,
      mandante: timeCalendario(e.mandante),
      visitante: timeCalendario(e.visitante),
      estadio: e.estadio || "",
      transmissao: e.transmissao || "",
      estado: e.estado || "pre",
      concluido: e.concluido === true,
      data_definir: e.data_definir === true,
      placar_mandante: e.placar_mandante,
      placar_visitante: e.placar_visitante
    }));
    const calendario = ((state.calendarioCompletoJson && state.calendarioCompletoJson.jogos) || []).map(item => {
      const base = {
        ...item,
        mandante: timeCalendario(item.mandante),
        visitante: timeCalendario(item.visitante),
        estado: item.estado || "pre",
        data_definir: item.data_definir === true || !item.data_iso
      };
      return { ...base, event_id: String(item.event_id || idSinteticoJogo(base)) };
    });
    const calendarioPorTimes = new Map(calendario.map(j => [chaveConfrontoTimes(j), j]).filter(([chave]) => Boolean(chave)));
    const aplicarRodadaCanonica = item => {
      const canonico = calendarioPorTimes.get(chaveConfrontoTimes(item));
      const rodadaFonte = Number(item && item.rodada || 0);
      if (!canonico || Number(canonico.rodada) === rodadaFonte) return item;
      return { ...item, rodada: Number(canonico.rodada), rodada_corrigida_calendario_de: rodadaFonte || null };
    };

    const map = new Map();
    [...a, ...b, ...c].forEach(item => {
      const j = normalizarHorarioJogo(aplicarRodadaCanonica(item));
      if (!j) return;
      const id = jogoId(j);
      if (!map.has(id)) map.set(id, j);
    });

    // calendario-completo.json é a malha canônica de 380 partidas. Ele completa
    // confrontos sem data/event_id que a ESPN ainda não publicou, sem duplicar
    // os jogos mais ricos já presentes em jogos/resultados/eventos.
    const confrontosExistentes = new Set(Array.from(map.values()).map(chaveConfrontoRodada).filter(Boolean));
    calendario.forEach(item => {
      const j = normalizarHorarioJogo(item);
      if (!j) return;
      const chave = chaveConfrontoRodada(j);
      if (chave && confrontosExistentes.has(chave)) return;
      map.set(jogoId(j), j);
      if (chave) confrontosExistentes.add(chave);
    });

    return sanearJogosPorRodada(Array.from(map.values()).sort(compararJogosPorData));
  }

  function jogosDaRodada(rodada) {
    return state.jogos.filter(j => Number(j.rodada) === Number(rodada));
  }

  function blocoEstaticoDaRodada(rodada) {
    const r = Number(rodada);
    const base = BLOCOS_3_RODADAS.find(b => r >= b.inicio && r <= b.fim);
    return base ? { rodada_inicio: base.inicio, rodada_fim: base.fim, nome: base.nome, bloco_id: null } : null;
  }

  function contextoEhBloco() {
    return Number(state.rodada) >= 21;
  }

  function jogosDoBloco(bloco) {
    if (!bloco) return [];
    return state.jogos.filter(j => Number(j.rodada) >= Number(bloco.rodada_inicio) && Number(j.rodada) <= Number(bloco.rodada_fim));
  }

  function jogosDoContexto() {
    const bloco = blocoDaRodada(state.rodada);
    return bloco ? jogosDoBloco(bloco) : jogosDaRodada(state.rodada);
  }

  function contextoLabel(rodada = state.rodada) {
    const bloco = blocoDaRodada(rodada);
    return bloco ? `Bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}` : `Rodada ${Number(rodada)}`;
  }

  function contextoAdminAtual() {
    const rodada = Number(state.rodada);
    const bloco = contextoEhBloco() ? blocoDaRodada(rodada) : null;
    if (bloco) {
      const inicio = Number(bloco.rodada_inicio);
      const fim = Number(bloco.rodada_fim);
      return {
        tipo: "bloco",
        bloco,
        rodadas: Array.from({ length: Math.max(0, fim - inicio + 1) }, (_, i) => inicio + i),
        totalJogos: 30,
        label: bloco.nome || `Bloco ${inicio}–${fim}`,
        slug: `bloco-${inicio}-${fim}`
      };
    }
    const cfg = configDaRodada(rodada);
    const totalDetectado = jogosDaRodada(rodada).length;
    const totalConfigurado = Number((cfg && cfg.total_jogos) || 0);
    return {
      tipo: "rodada",
      bloco: null,
      rodadas: [rodada],
      totalJogos: Math.max(totalDetectado, totalConfigurado, 0),
      label: `Rodada ${rodada}`,
      slug: `rodada-${rodada}`
    };
  }

  function agregarProgressoAdminPorContexto(lotes, totalJogos) {
    const porParticipante = new Map();
    for (const lote of lotes || []) {
      for (const linha of lote || []) {
        const chave = String(linha.participante_id || linha.login || linha.nome || "");
        if (!chave) continue;
        if (!porParticipante.has(chave)) {
          porParticipante.set(chave, {
            ...linha,
            total_palpites: 0,
            total_jogos: Number(totalJogos || 0),
            percentual: 0
          });
        }
        const acumulado = porParticipante.get(chave);
        acumulado.total_palpites += Number(linha.total_palpites || 0);
        acumulado.ativo = Boolean(linha.ativo);
        acumulado.admin = Boolean(linha.admin);
      }
    }
    const total = Number(totalJogos || 0);
    return Array.from(porParticipante.values())
      .map(linha => ({
        ...linha,
        total_jogos: total,
        percentual: total > 0 ? Math.round((Number(linha.total_palpites || 0) / total) * 1000) / 10 : 0
      }))
      .sort((a, b) => String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR"));
  }

  async function carregarProgressoAdminContexto(nomeRpc, parametrosExtras = {}) {
    const contexto = contextoAdminAtual();
    const totalPorRodada = contexto.tipo === "bloco" ? 10 : contexto.totalJogos;
    const lotes = await Promise.all(contexto.rodadas.map(rodada => rpcRows(nomeRpc, {
      p_admin_id: state.usuario.id,
      p_token: state.token,
      p_temporada: CFG.temporada || 2026,
      p_rodada: rodada,
      p_total_jogos: totalPorRodada,
      ...parametrosExtras
    })));
    return agregarProgressoAdminPorContexto(lotes, contexto.totalJogos);
  }

  function mesmoContextoRodadas(a, b) {
    if (Number(a) === 20 || Number(b) === 20) return Number(a) === Number(b);
    const ba = blocoEstaticoDaRodada(a);
    const bb = blocoEstaticoDaRodada(b);
    return Boolean(ba && bb && Number(ba.rodada_inicio) === Number(bb.rodada_inicio));
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
    const datas = jogos.filter(jogoTemHorarioConfiavel).map(j => parseData(j.data_iso)).filter(Boolean).sort((a, b) => a - b);
    // Nunca inventar uma janela usando "agora" quando a rodada ainda não possui
    // kickoff confiável. Esse fallback fazia especialmente o admin enxergar blocos
    // distantes (como R36–38) como se já fossem o contexto atual.
    if (!datas.length) {
      return { rodada: Number(rodada), abre_em: null, fecha_em: null, status: "futura", origem: "sem-kickoff-confiavel" };
    }
    const primeira = datas[0];
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
    const existente = configDaRodada(rodada);
    if (Number(rodada) >= 21 && !isAdminGlobal() && (!existente || !existente.bloco_id)) {
      return {
        rodada: Number(rodada),
        abre_em: null,
        fecha_em: null,
        publica_em: null,
        status: "futura",
        observacao: "Aguardando configuração administrativa do bloco.",
        bloco_id: null,
        bloco_nome: null,
        bloco_rodada_inicio: null,
        bloco_rodada_fim: null,
        bloco_primeiro_jogo_em: null,
        bloco_versao: null
      };
    }
    if (!existente && Number(rodada) >= 21 && state.blocosInfraDisponivel) {
      return {
        rodada: Number(rodada), abre_em: null, fecha_em: null, publica_em: null, status: "futura",
        observacao: "Aguardando configuração administrativa do bloco.", bloco_id: null, bloco_nome: null,
        bloco_rodada_inicio: null, bloco_rodada_fim: null, bloco_primeiro_jogo_em: null, bloco_versao: null
      };
    }
    const cfg = existente || janelaPadrao(rodada);
    return {
      rodada: Number(rodada),
      abre_em: cfg.abre_em,
      fecha_em: cfg.fecha_em,
      publica_em: cfg.publica_em || null,
      status: cfg.status || "programada",
      observacao: cfg.observacao || "",
      bloco_id: cfg.bloco_id || null,
      bloco_nome: cfg.bloco_nome || null,
      bloco_rodada_inicio: cfg.bloco_rodada_inicio == null ? null : Number(cfg.bloco_rodada_inicio),
      bloco_rodada_fim: cfg.bloco_rodada_fim == null ? null : Number(cfg.bloco_rodada_fim),
      bloco_primeiro_jogo_em: cfg.bloco_primeiro_jogo_em || null,
      bloco_versao: cfg.bloco_versao == null ? null : Number(cfg.bloco_versao),
      bloco_status: cfg.bloco_status || null,
      bloco_jogos_apurados: cfg.bloco_jogos_apurados == null ? null : Number(cfg.bloco_jogos_apurados),
      bloco_apuracao_concluida: cfg.bloco_apuracao_concluida == null ? null : Boolean(cfg.bloco_apuracao_concluida),
      bloco_sincronizado_em: cfg.bloco_sincronizado_em || null
    };
  }

  function blocoDaRodada(rodada) {
    const r = Number(rodada);
    const admin = (state.blocosApostas || []).find(b => r >= Number(b.rodada_inicio) && r <= Number(b.rodada_fim));
    if (admin) return admin;
    const cfg = configDaRodada(r);
    if (cfg && cfg.bloco_id) {
      return {
        bloco_id: cfg.bloco_id,
        rodada_inicio: Number(cfg.bloco_rodada_inicio),
        rodada_fim: Number(cfg.bloco_rodada_fim),
        nome: cfg.bloco_nome || `Bloco ${cfg.bloco_rodada_inicio}–${cfg.bloco_rodada_fim}`,
        primeiro_jogo_em: cfg.bloco_primeiro_jogo_em || null,
        abre_em: cfg.abre_em || null,
        fecha_em: cfg.fecha_em || null,
        status: cfg.bloco_status || cfg.status || "futura",
        versao: cfg.bloco_versao || null,
        jogos_apurados: cfg.bloco_jogos_apurados == null ? 0 : Number(cfg.bloco_jogos_apurados),
        apuracao_concluida: Boolean(cfg.bloco_apuracao_concluida),
        sincronizado_em: cfg.bloco_sincronizado_em || null
      };
    }
    return blocoEstaticoDaRodada(r);
  }

  function blocoAdminAtual() {
    const lista = state.blocosApostas || [];
    if (!lista.length) return null;
    const escolhido = lista.find(b => String(b.bloco_id) === String(state.blocoAdminSelecionado));
    if (escolhido) return escolhido;
    const daRodada = blocoDaRodada(state.rodada);
    return daRodada || lista[0];
  }

  function primeiroJogoDetectadoBloco(bloco) {
    if (!bloco) return null;
    // O deadline pertence ao bloco inteiro: uma partida antecipada da R25/R26
    // pode ocorrer antes da primeira partida da R24. Por isso os 30 jogos são
    // sempre considerados, nunca apenas a rodada inicial do bloco.
    const datas = jogosDoBloco(bloco)
      .filter(jogoTemHorarioConfiavel)
      .map(j => parseData(j.data_iso))
      .filter(Boolean)
      .sort((a, b) => a - b);
    return datas[0] || null;
  }

  function fechamentoRecomendado(primeiroJogo) {
    const d = primeiroJogo instanceof Date ? primeiroJogo : parseData(primeiroJogo);
    return d ? new Date(d.getTime() - 60 * 60 * 1000) : null;
  }

  function datasIguais(a, b) {
    const da = a instanceof Date ? a : parseData(a);
    const db = b instanceof Date ? b : parseData(b);
    if (!da && !db) return true;
    if (!da || !db) return false;
    return Math.abs(da.getTime() - db.getTime()) < 1000;
  }

  function rodadaAberta(rodada) {
    const cfg = configEfetiva(rodada);
    const agora = new Date();
    const abre = parseData(cfg.abre_em);
    const fecha = parseData(cfg.fecha_em);
    const status = String(cfg.status || "programada").toLowerCase();
    if (Number(rodada) < Number(CFG.rodadaInicialApostas || 20)) return false;
    if (["fechada", "apurada", "publicada", "bloqueada", "encerrada"].includes(status)) return false;
    if (!abre || !fecha) return false;

    // "futura" e "programada" são estados de programação, não travas permanentes.
    // Assim que a abertura chega, o relógio passa a comandar a janela. Isso também
    // protege a interface caso exista um registro antigo com datas completas e status
    // ainda igual a "futura".
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
    const bloco = blocoDaRodada(rodada);
    const alvo = bloco ? (bloco.nome || `Bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}`) : `Rodada ${rodada}`;
    if (rodadaPublica(rodada)) return { classe: "done", texto: "Palpites publicados", detalhe: `${alvo} publicado` };
    if (["fechada", "apurada", "bloqueada", "encerrada"].includes(status)) return { classe: "lock", texto: bloco ? "Bloco fechado" : "Rodada fechada", detalhe: fecha ? `Fechado em ${fmtDataLonga(fecha)}` : `${alvo} bloqueado` };
    if (!abre || !fecha) return { classe: "warn", texto: "Aguardando programação", detalhe: `${alvo} ainda sem janela completa` };
    if (agora < abre) return { classe: "warn", texto: "Aguardando abertura", detalhe: `Abre em ${fmtDataLonga(abre)}` };
    if (agora >= fecha) return { classe: "lock", texto: "Janela encerrada", detalhe: `Fechou em ${fmtDataLonga(fecha)}` };
    return { classe: "open", texto: "Apostas abertas", detalhe: status === "aberta" ? `Aberta pelo admin · até ${fmtDataLonga(fecha)}` : `Até ${fmtDataLonga(fecha)}` };
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

  // ── Auto-refresh inteligente do ranking/apuração ───────────────────────
  // Perto de jogo, o backend pode publicar resultado+pontuação logo após FINAL;
  // nesse período consultamos os dois JSONs a cada 60 s. Fora da janela de jogo,
  // 5 min são suficientes. São arquivos estáticos e não acionam workflow.
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

  function intervaloAutoRefreshApuracao() {
    const agora = Date.now();
    const jogos = (state.calendarioCompletoJson && state.calendarioCompletoJson.jogos) || [];
    const janelaRapida = jogos.some(j => {
      if (!jogoTemHorarioConfiavel(j)) return false;
      const data = parseData(j.data_iso);
      if (!data) return false;
      const delta = agora - data.getTime();
      return delta >= -30 * 60 * 1000 && delta <= 5 * 60 * 60 * 1000;
    });
    return janelaRapida ? 60 * 1000 : 5 * 60 * 1000;
  }

  function iniciarAutoRefresh() {
    pararAutoRefresh();
    if (!rodadaAtiva()) return;
    state._autoRefreshTimer = setTimeout(async () => {
      await recarregarApuracao();
      iniciarAutoRefresh(); // recalcula a cadência conforme a janela dos jogos
    }, intervaloAutoRefreshApuracao());
  }

  function pararAutoRefresh() {
    if (state._autoRefreshTimer) {
      clearTimeout(state._autoRefreshTimer);
      state._autoRefreshTimer = null;
    }
  }

  async function carregarBase() {
    const arq = CFG.arquivos || {};
    const [jogosJson, resultadosJson, espnEventosJson, calendarioCompletoJson, configLocal, apuracao, rankingApostas, clubesJson] = await Promise.all([
      fetchJson(arq.jogos || "jogos.json", { jogos: [] }),
      fetchJson(arq.resultados || "resultados.json", { resultados: [] }),
      fetchJson(arq.eventos || "espn_eventos.json", { eventos: [] }),
      fetchJson(arq.calendarioCompleto || "dados-br/calendario-completo.json", { jogos: [] }),
      fetchJson(arq.configRodadas || "dados-br/apostas-config.json", { rodadas: [] }),
      fetchJson("dados-br/apuracao.json", { rodadas: [], ranking_geral: [] }),
      fetchJson("dados-br/ranking-apostas.json", { ranking_geral: [] }),
      fetchJson("dados-br/clubes.json", { clubes: [] })
    ]);
    state.jogosJson = jogosJson;
    state.resultadosJson = resultadosJson;
    state.espnEventosJson = espnEventosJson;
    state.calendarioCompletoJson = calendarioCompletoJson;
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
      state.configSupabase = await rpcRows("br_listar_config_rodadas_v4", { p_temporada: CFG.temporada || 2026 });
    } catch (errV4) {
      try {
        state.configSupabase = await rpcRows("br_listar_config_rodadas_v3", { p_temporada: CFG.temporada || 2026 });
      } catch (errV3) {
        try {
          state.configSupabase = await rpcRows("br_listar_config_rodadas_v2", { p_temporada: CFG.temporada || 2026 });
        } catch (errV2) {
          try {
            state.configSupabase = await rpcRows("br_listar_config_rodadas", { p_temporada: CFG.temporada || 2026 });
          } catch (err) {
            console.warn("Config Supabase indisponível", errV4, errV3, errV2, err);
            state.configSupabase = [];
          }
        }
      }
    }
  }

  async function carregarBlocosApostasAdmin() {
    if (!state.supabase || !isAdminGlobal()) {
      state.blocosApostas = [];
      state.blocosInfraDisponivel = false;
      state.blocoAdminSelecionado = null;
      return;
    }
    try {
      let rows;
      try {
        rows = await rpcRows("br_admin_listar_blocos_apostas_v2", {
          p_admin_id: state.usuario.id,
          p_token: state.token,
          p_temporada: CFG.temporada || 2026
        });
      } catch (errV2) {
        rows = await rpcRows("br_admin_listar_blocos_apostas_v1", {
          p_admin_id: state.usuario.id,
          p_token: state.token,
          p_temporada: CFG.temporada || 2026
        });
      }
      state.blocosApostas = Array.isArray(rows) ? rows : [];
      state.blocosInfraDisponivel = true;
      const selecionadoExiste = state.blocosApostas.some(b => String(b.bloco_id) === String(state.blocoAdminSelecionado));
      if (!selecionadoExiste) {
        const daRodada = blocoDaRodada(state.rodada);
        state.blocoAdminSelecionado = (daRodada || state.blocosApostas[0] || {}).bloco_id || null;
      }
    } catch (err) {
      console.warn("Infraestrutura de blocos ainda indisponível", err);
      state.blocosApostas = [];
      state.blocosInfraDisponivel = false;
      state.blocoAdminSelecionado = null;
    }
  }

  async function carregarMeusPalpites() {
    if (!state.usuario) return;
    state.comprovanteBloco = null;
    state.progressoBloco = null;
    if (!contextoEhBloco()) {
      state.exec3InfraDisponivel = false;
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
      return;
    }

    const bloco = blocoDaRodada(state.rodada);
    if (!bloco?.bloco_id) {
      state.meusPalpites = [];
      state.exec3InfraDisponivel = false;
      return;
    }
    try {
      const [palpites, comprovantes, progressos] = await Promise.all([
        rpcRows("br_listar_meus_palpites_bloco_v1", {
          p_participante_id: state.usuario.id,
          p_token: state.token,
          p_bloco_id: bloco.bloco_id,
          p_temporada: CFG.temporada || 2026
        }),
        rpcRows("br_listar_comprovante_bloco_v1", {
          p_participante_id: state.usuario.id,
          p_token: state.token,
          p_bloco_id: bloco.bloco_id,
          p_temporada: CFG.temporada || 2026
        }),
        rpcRows("br_progresso_bloco_v1", {
          p_participante_id: state.usuario.id,
          p_token: state.token,
          p_bloco_id: bloco.bloco_id,
          p_temporada: CFG.temporada || 2026
        })
      ]);
      state.meusPalpites = Array.isArray(palpites) ? palpites : [];
      state.comprovanteBloco = (comprovantes || [])[0] || null;
      state.progressoBloco = (progressos || [])[0] || null;
      state.exec3InfraDisponivel = true;
    } catch (err) {
      console.warn("Infraestrutura da Execução 3 indisponível", err);
      state.meusPalpites = [];
      state.comprovanteBloco = null;
      state.progressoBloco = null;
      state.exec3InfraDisponivel = false;
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
    if (!jogos.every(j => resultadoFinalizado(j.resultado || {}, j.event_id))) return false;
    const locais = ((state.resultadosJson && state.resultadosJson.resultados) || []).filter(r => Number(r.rodada) === Number(ap.rodada));
    const idsLocais = new Set(locais.map(r => String(r.event_id || r.id || "")).filter(Boolean));
    const apurados = Number(ap.jogos_apurados || 0);
    if (apurados < 0 || apurados > 10 || apurados > idsLocais.size) return false;
    if (ap.concluida && apurados !== 10) return false;
    return true;
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
      if (contextoEhBloco()) {
        const bloco = blocoDaRodada(state.rodada);
        if (!bloco?.bloco_id || !state.usuario) { state.publicos = []; return; }
        state.publicos = await rpcRows("br_listar_palpites_publicos_bloco_v1", {
          p_participante_id: state.usuario.id,
          p_token: state.token,
          p_bloco_id: bloco.bloco_id,
          p_liga_id: state.ligaAtual || null,
          p_temporada: CFG.temporada || 2026
        });
        return;
      }
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
      console.warn("Palpites públicos indisponíveis", err);
      state.publicos = [];
    }
  }

  function htmlTeam(time, cls) {
    const esc = timeEscudo(time);
    return `<div class="team ${cls || ""}">${esc ? `<img src="${esc}" alt="">` : ""}<div><div class="team-name">${timeNome(time)}</div><div class="team-sigla">${timeSigla(time)}</div></div></div>`;
  }

  function palpiteSalvoPara(ref) {
    const id = typeof ref === "object" && ref ? jogoId(ref) : String(ref || "");
    const exato = state.meusPalpites.find(p => String(p.event_id) === String(id));
    if (exato || !ref || typeof ref !== "object") return exato;
    const chave = chaveConfrontoRodada(ref);
    return chave ? state.meusPalpites.find(p => chaveConfrontoRodada(p) === chave) : undefined;
  }

  function jogoIdAposta(j) {
    const salvo = palpiteSalvoPara(j);
    return String((salvo && salvo.event_id) || jogoId(j) || idSinteticoJogo(j));
  }


  function hashServidorAtual() {
    return state.comprovanteBloco?.hash_bloco || state.meusPalpites.find(p => p.hash_bloco)?.hash_bloco || "";
  }

  function chaveRascunhoBloco() {
    if (!state.usuario || !contextoEhBloco()) return "";
    const bloco = blocoDaRodada(state.rodada);
    if (!bloco) return "";
    return `brApostasRascunhoV1:${CFG.temporada || 2026}:${state.usuario.id}:${bloco.rodada_inicio}-${bloco.rodada_fim}`;
  }

  function lerRascunhoBloco() {
    const chave = chaveRascunhoBloco();
    if (!chave) return null;
    try {
      const valor = JSON.parse(localStorage.getItem(chave) || "null");
      if (!valor || typeof valor !== "object" || !valor.valores) return null;
      const hashAtual = hashServidorAtual();
      if (valor.hashServidor && hashAtual && valor.hashServidor !== hashAtual) {
        localStorage.removeItem(chave);
        return null;
      }
      return valor;
    } catch (err) {
      console.warn("Rascunho local inválido", err);
      return null;
    }
  }

  function salvarRascunhoBloco() {
    const form = $("#form-palpites-bloco");
    const chave = chaveRascunhoBloco();
    if (!form || !chave) return;
    const valores = {};
    $$('input[data-event-id]', form).forEach(input => {
      const id = input.dataset.eventId;
      if (!valores[id]) valores[id] = { pm: "", pv: "" };
      valores[id][input.dataset.lado] = input.value;
    });
    localStorage.setItem(chave, JSON.stringify({
      versao: 1,
      hashServidor: hashServidorAtual(),
      atualizadoEm: new Date().toISOString(),
      valores
    }));
    state.draftDirty = true;
  }

  function limparRascunhoBloco() {
    const chave = chaveRascunhoBloco();
    if (chave) localStorage.removeItem(chave);
    state.draftDirty = false;
    state.draftRestaurado = false;
  }

  function confirmarDescarteRascunho() {
    if (!state.draftDirty) return true;
    return confirmarAcao("Existem alterações locais ainda não salvas. Deseja descartá-las e continuar?");
  }

  function valoresAtuaisFormularioBloco() {
    const valores = {};
    const form = $("#form-palpites-bloco");
    if (!form) return valores;
    $$('input[data-event-id]', form).forEach(input => {
      const id = input.dataset.eventId;
      if (!valores[id]) valores[id] = { pm: "", pv: "" };
      valores[id][input.dataset.lado] = input.value;
    });
    return valores;
  }

  function contarPreenchidosBloco() {
    const valores = valoresAtuaisFormularioBloco();
    const preenchidos = new Set(
      (state.meusPalpites || []).map(p => String(p.event_id || "")).filter(Boolean)
    );
    Object.entries(valores).forEach(([eventId, valor]) => {
      if (valor.pm !== "" && valor.pv !== "") preenchidos.add(String(eventId));
    });
    return Math.min(30, preenchidos.size);
  }

  function atualizarProgressoFormularioBloco() {
    const preenchidos = contarPreenchidosBloco();
    const faltantes = Math.max(0, 30 - preenchidos);
    $$("[data-progresso-bloco]").forEach(el => { el.textContent = `${preenchidos}/30 preenchidos`; });
    $$("[data-faltantes-bloco]").forEach(el => { el.textContent = faltantes ? `Faltam ${faltantes}` : "Bloco completo"; });
    const barra = $("#barra-progresso-bloco");
    if (barra) barra.style.width = `${Math.min(100, (preenchidos / 30) * 100)}%`;
    const btn = $("#salvar-palpites-bloco");
    const btnFixo = $("#salvar-palpites-bloco-fixo");
    [btn, btnFixo].filter(Boolean).forEach(b => { b.disabled = state.salvandoPalpites || !rodadaAberta(state.rodada) || preenchidos === 0; });
  }

  function restaurarValoresServidorBloco() {
    const form = $("#form-palpites-bloco");
    if (!form) return;
    $$('input[data-event-id]', form).forEach(input => {
      const salvo = palpiteSalvoPara(input.dataset.eventId);
      input.value = input.dataset.lado === "pm" ? (salvo?.placar_mandante ?? "") : (salvo?.placar_visitante ?? "");
    });
    limparRascunhoBloco();
    atualizarProgressoFormularioBloco();
    toast("Alterações locais descartadas. Os palpites salvos foram restaurados.", "ok");
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
      .filter(jogoTemHorarioConfiavel)
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

  function estadoBlocoResumo(inicio) {
    const start = Number(inicio);
    const bloco = blocoDaRodada(start) || blocoEstaticoDaRodada(start);
    if (!bloco) return null;
    const cfg = configEfetiva(start);
    const ap = apuracaoBlocoPorInicio(start);
    const jogosApurados = Number(ap?.jogos_apurados ?? bloco?.jogos_apurados ?? cfg?.bloco_jogos_apurados ?? 0);
    const concluido = Boolean(ap?.concluido || ap?.concluida || bloco?.apuracao_concluida || cfg?.bloco_apuracao_concluida || jogosApurados >= 30);
    const antecedenciaDias = Number(state.configLocal?.blocosAutomaticos?.antecedenciaAberturaDias || 7);
    const antecedenciaFechamentoMin = Number(state.configLocal?.blocosAutomaticos?.fechamentoAntesPrimeiroJogoMinutos || 60);

    // A seleção AUTOMÁTICA do bloco nunca confia cegamente em uma janela antiga
    // gravada no Supabase. Ela precisa ser sustentada pelo calendário canônico que
    // o navegador acabou de carregar. Isso impede que um bloco futuro sem kickoff
    // confirmado (ex.: R36–38) vire "rodada atual" por causa de configuração stale.
    const primeiroCanonico = primeiroJogoDetectadoBloco(bloco);
    const totalCanonicos = jogosDoBloco(bloco).length;
    const automaticoElegivel = Boolean(primeiroCanonico && totalCanonicos === 30);
    const abreCanonica = automaticoElegivel ? new Date(primeiroCanonico.getTime() - antecedenciaDias * 86400000) : null;
    const fechaCanonica = automaticoElegivel ? new Date(primeiroCanonico.getTime() - antecedenciaFechamentoMin * 60000) : null;

    const primeiroBanco = parseData(bloco.primeiro_jogo_em || cfg.bloco_primeiro_jogo_em);
    const abreBanco = parseData(bloco.abre_em || cfg.abre_em);
    const fechaBanco = parseData(bloco.fecha_em || cfg.fecha_em);
    const primeiroConfiavel = primeiroCanonico || primeiroBanco;
    const abre = abreCanonica || abreBanco;
    const fecha = fechaCanonica || fechaBanco;

    let statusApostas = String(bloco.status || cfg.bloco_status || cfg.status || "futura").toLowerCase();
    const agora = new Date();
    if (automaticoElegivel) {
      if (agora < abreCanonica) statusApostas = "programada";
      else if (agora < fechaCanonica) statusApostas = "aberta";
      else if (!["bloqueada", "publicada", "apurada"].includes(statusApostas)) statusApostas = "fechada";
    } else if (start >= 21 && !concluido && !["publicada", "apurada", "bloqueada"].includes(statusApostas)) {
      // Sem 30 jogos + kickoff canônico confiável, o bloco pode ser exibido como
      // futuro, mas jamais assumir automaticamente a navegação principal.
      statusApostas = "futura";
    }

    return {
      inicio: start, fim: Number(bloco.rodada_fim || start + 2), bloco, cfg, ap,
      statusApostas, jogosApurados, concluido, abre, fecha,
      primeiroConfiavel, primeiroCanonico, abreCanonica, fechaCanonica,
      automaticoElegivel, totalCanonicos,
      parcial: jogosApurados > 0 && jogosApurados < 30 && !concluido
    };
  }

  function blocosResumoOrdenados() {
    return BLOCOS_3_RODADAS.map(b => estadoBlocoResumo(b.inicio)).filter(Boolean);
  }

  function blocoAcaoAtual() {
    const agora = new Date();
    const blocos = blocosResumoOrdenados();

    // AÇÃO DE APOSTA e BLOCO ATUAL são conceitos diferentes.
    // Um bloco futuro pode abrir 7 dias antes para receber palpites sem virar o
    // contexto principal do campeonato. Esta função serve apenas aos CTAs de aposta.
    const abertos = blocos
      .filter(b => b.automaticoElegivel && b.statusApostas === "aberta" && b.abreCanonica && b.fechaCanonica)
      .filter(b => b.abreCanonica <= agora && agora < b.fechaCanonica)
      .sort((a, b) => b.inicio - a.inicio);
    if (abertos.length) return abertos[0];

    const futuros = blocos
      .filter(b => b.automaticoElegivel && b.abreCanonica && b.abreCanonica > agora)
      .sort((a, b) => a.abreCanonica - b.abreCanonica);
    return futuros[0] || null;
  }

  function blocoCampeonatoAtual() {
    const agora = new Date();
    const blocos = blocosResumoOrdenados();

    // REGRA DE UX: o bloco principal só avança quando uma partida daquele bloco
    // realmente começa. Abrir R24–26 para apostas em 15/08 NÃO tira o usuário de
    // R21–23 enquanto a R23 ainda está sendo disputada. Quando o primeiro jogo de
    // R24–26 começar, aí sim o contexto muda, mesmo se R21–23 continuar em apuração
    // por partidas adiadas.
    const iniciados = blocos
      .filter(b => b.automaticoElegivel && b.primeiroCanonico && b.primeiroCanonico <= agora)
      .sort((a, b) => b.inicio - a.inicio);
    if (iniciados.length) return iniciados[0];

    const publicados = blocosRanking()
      .filter(b => b && b.publicada === true && b.sigilosa !== true)
      .sort((a, b) => Number(b.rodada_inicio || 0) - Number(a.rodada_inicio || 0));
    return publicados.length ? estadoBlocoResumo(Number(publicados[0].rodada_inicio)) : null;
  }

  function determinarRodadaAtual() {
    const rodadas = (state.rodadas || []).slice().sort((a, b) => a - b);
    if (!rodadas.length) return Number(CFG.rodadaInicialApostas || 20);

    // "Atual" significa o bloco cuja disputa já começou, não o próximo bloco que
    // apenas abriu para receber palpites.
    const campeonato = blocoCampeonatoAtual();
    if (campeonato) return campeonato.inicio;

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
    if (force || !state.rodadaEscolhidaManualmente) {
      state.rodada = atual;
    }
    state.rodadaAutomaticaResolvida = true;
  }

  function renderResumo() {
    const jogos = jogosDoContexto();
    const st = statusJanela(state.rodada);
    const salvos = state.meusPalpites.length;
    const totalEsperado = contextoEhBloco() ? 30 : jogos.length;
    const pct = totalEsperado ? Math.round((salvos / totalEsperado) * 100) : 0;
    $("#numero-rodada").textContent = contextoEhBloco() ? contextoLabel().replace("Bloco ", "") : state.rodada;
    $("#total-jogos").textContent = jogos.length;
    $("#texto-janela").textContent = st.texto;
    const badge = $("#badge-janela");
    badge.textContent = st.detalhe;
    badge.className = `badge ${st.classe}`;
    $("#meu-percentual").textContent = `${pct}%`;
    $("#meu-total-salvo").textContent = salvos;
    const labelRodada = $("#resumo-contexto-label");
    if (labelRodada) labelRodada.textContent = contextoEhBloco() ? "Bloco selecionado" : "Rodada selecionada";
    const labelJanela = $("#resumo-janela-label");
    if (labelJanela) labelJanela.textContent = contextoEhBloco() ? "Janela do bloco" : "Janela da rodada";
    const labelPreenchimento = $("#resumo-preenchimento-texto");
    if (labelPreenchimento) labelPreenchimento.textContent = contextoEhBloco() ? "palpites salvos neste bloco." : "palpites salvos nesta rodada.";
  }

  function renderPainelBlocosStatus() {
    const root = $("#painel-blocos-status");
    if (!root) return;
    const blocos = blocosResumoOrdenados();
    if (!blocos.length) { root.hidden = true; root.innerHTML = ""; return; }
    const agora = new Date();
    const aberto = blocos.filter(b => b.statusApostas === "aberta" && (!b.fecha || agora < b.fecha))
      .sort((a,b)=>(a.fecha?.getTime()||Infinity)-(b.fecha?.getTime()||Infinity))[0] || null;
    const parcial = blocos.filter(b => b.parcial && (!aberto || b.inicio !== aberto.inicio))
      .sort((a,b)=>b.inicio-a.inicio)[0] || null;
    const proximo = blocos.filter(b => ["programada","futura"].includes(b.statusApostas) && b.abre && b.abre > agora && (!aberto || b.inicio !== aberto.inicio))
      .sort((a,b)=>a.abre-b.abre)[0] || null;
    const cards = [];
    if (aberto) {
      const selecionadoEhAberto = mesmoContextoRodadas(state.rodada, aberto.inicio);
      const progresso = selecionadoEhAberto ? `${state.meusPalpites.length}/30 palpites salvos · ` : "";
      cards.push({
        tipo:"action", icon:"🟢", kicker:"AÇÃO AGORA", titulo:`Bloco ${aberto.inicio}–${aberto.fim} · apostas abertas`,
        texto:`${progresso}fecha ${fmtDataLonga(aberto.fecha)}`,
        botao:"Fazer/revisar palpites", inicio:aberto.inicio, aba:"apostas"
      });
    }
    if (parcial) cards.push({
      tipo:"partial", icon:"⏳", kicker:"EM APURAÇÃO", titulo:`Bloco ${parcial.inicio}–${parcial.fim} · ${parcial.jogosApurados}/30`,
      texto:`${30-parcial.jogosApurados} jogo(s) ainda pendente(s). O bloco seguinte funciona normalmente.`,
      botao:"Ver ranking parcial", inicio:parcial.inicio, aba:"ranking"
    });
    if (!aberto && proximo) cards.push({
      tipo:"next", icon:"🕒", kicker:"PRÓXIMO BLOCO", titulo:`Bloco ${proximo.inicio}–${proximo.fim}`,
      texto:`Abertura automática em ${fmtDataLonga(proximo.abre)}.`,
      botao:"Consultar bloco", inicio:proximo.inicio, aba:"apostas"
    });
    if (!cards.length) { root.hidden = true; root.innerHTML = ""; return; }
    root.hidden = false;
    root.innerHTML = cards.map(c => `<article class="block-status-card ${c.tipo}"><div><div class="kicker">${c.icon} ${c.kicker}</div><strong>${escapeHtml(c.titulo)}</strong><span>${escapeHtml(c.texto)}</span></div><button type="button" class="btn secondary" data-painel-bloco="${c.inicio}" data-painel-aba="${c.aba}">${escapeHtml(c.botao)}</button></article>`).join("");
    root.querySelectorAll("[data-painel-bloco]").forEach(btn => btn.addEventListener("click", async () => {
      state.abaEscolhidaManualmente = true;
      state.destinoCronologicoResolvido = true;
      state.aba = btn.dataset.painelAba || "apostas";
      await trocarRodada(Number(btn.dataset.painelBloco), true);
    }));
  }

  function renderRodadas() {
    const tabs = $("#rodadas");
    const contexto = $("#rodada-contexto");
    const voltar = $("#voltar-rodada-atual");
    const titulo = $("#controle-titulo");
    const descricao = $("#controle-descricao");
    if (!tabs) return;
    const manual = !mesmoContextoRodadas(state.rodada, state.rodadaAutomatica);
    const itens = [{ inicio: 20, fim: 20, nome: "R20" }, ...BLOCOS_3_RODADAS];
    tabs.innerHTML = itens.map(item => {
      const active = item.inicio === 20 ? Number(state.rodada) === 20 : Number(state.rodada) >= item.inicio && Number(state.rodada) <= item.fim;
      const current = item.inicio === 20 ? Number(state.rodadaAutomatica) === 20 : Number(state.rodadaAutomatica) >= item.inicio && Number(state.rodadaAutomatica) <= item.fim;
      const label = item.inicio === 20 ? "R20" : `${item.inicio}–${item.fim}`;
      let stateTag = "";
      let ariaState = "";
      if (item.inicio >= 21) {
        const resumo = estadoBlocoResumo(item.inicio);
        if (resumo?.concluido) { stateTag = '<span class="round-state done" aria-hidden="true">✅</span>'; ariaState = ", concluído"; }
        else if (resumo?.statusApostas === "aberta") { stateTag = '<span class="round-state open" aria-hidden="true">🟢</span>'; ariaState = ", apostas abertas"; }
        else if (resumo?.parcial) { stateTag = `<span class="round-state partial" aria-hidden="true">⏳ ${resumo.jogosApurados}/30</span>`; ariaState = `, ${resumo.jogosApurados} de 30 jogos apurados`; }
      }
      return `<button type="button" class="${active ? "active" : ""} ${current ? "current" : ""}" data-rodada="${item.inicio}" role="tab" aria-selected="${active}" aria-label="${item.inicio === 20 ? "Rodada 20" : `Bloco das rodadas ${item.inicio} a ${item.fim}`}${current ? ", bloco atual do campeonato" : ""}${ariaState}"><span>${label}</span>${stateTag}${current ? `<span class="current-dot" aria-hidden="true"></span>` : ""}</button>`;
    }).join("");
    tabs.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => trocarRodada(Number(btn.dataset.rodada), true)));
    const atualLabel = contextoLabel(state.rodadaAutomatica);
    const acaoApostas = blocoAcaoAtual();
    const acaoLabel = acaoApostas && acaoApostas.statusApostas === "aberta" ? ` · apostas abertas: <strong>Bloco ${acaoApostas.inicio}–${acaoApostas.fim}</strong>` : "";
    if (contexto) contexto.innerHTML = manual
      ? `Consultando <strong>${contextoLabel()}</strong> · bloco atual: <strong>${atualLabel}</strong>${acaoLabel}`
      : `Bloco atual: <strong>${atualLabel}</strong>${acaoLabel}`;
    if (voltar) voltar.hidden = !manual;
    if (titulo) titulo.textContent = manual ? `Consultando ${contextoLabel().toLowerCase()}` : `${atualLabel}`;
    if (descricao) descricao.textContent = manual
      ? "Você está consultando outro bloco. Use o botão ao lado para voltar ao bloco atual."
      : "Um bloco futuro pode estar aberto para palpites sem substituir o bloco que está sendo disputado agora.";
  }

  function renderUsuario() {
    const chip = $("#usuario-chip");
    if (!state.usuario) { chip.hidden = true; return; }
    chip.hidden = false;
    chip.innerHTML = `${canAdminAny() ? "🛠️ " : "👤 "}${escapeHtml(state.usuario.nome)}<br><small>${escapeHtml(nomeLigaAtual())} · ${escapeHtml(adminPerfilTexto())}</small><br><button class="btn ghost" type="button" id="sair">sair</button>`;
    $("#sair")?.addEventListener("click", () => {
      if (!confirmarDescarteRascunho()) return;
      clearSession(); renderLogin(); status("Sessão encerrada.", "warn");
    });
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

  function renderApostasRodadaLegado() {
    const root = $("#conteudo");
    const jogos = jogosDaRodada(state.rodada);
    const aberta = rodadaAberta(state.rodada);
    const st = statusJanela(state.rodada);
    if (!jogos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>Rodada ${state.rodada} ainda sem jogos no JSON.</strong><p>Quando o workflow ESPN trouxer a tabela da rodada, os confrontos aparecem aqui.</p></div></section>`;
      return;
    }
    const aviso = aberta
      ? `<div class="status ok">Janela aberta. Você pode salvar ou alterar seus palpites até o fechamento.</div>`
      : `<div class="status warn">${st.texto}. ${st.detalhe}. Os campos ficam bloqueados fora da janela.</div>`;
    root.innerHTML = `${aviso}<form id="form-palpites" class="matches">${jogos.map(j => {
      const id = jogoId(j);
      const salvo = palpiteSalvoPara(id);
      return `<article class="match-card" data-event-id="${escapeAttr(id)}">
        <div class="match-top"><span>Rodada ${j.rodada} · ${fmtDataJogo(j)}</span><span class="badge ${aberta ? "open" : "lock"}">${aberta ? "aberto" : "travado"}</span></div>
        <div class="match-body">${htmlTeam(j.mandante, "home")}<div class="score-inputs">
          <input name="pm-${escapeAttr(id)}" type="number" inputmode="numeric" min="0" max="30" value="${salvo?.placar_mandante ?? ""}" ${aberta ? "" : "disabled"} aria-label="Placar ${escapeAttr(timeNome(j.mandante))}"><span>x</span>
          <input name="pv-${escapeAttr(id)}" type="number" inputmode="numeric" min="0" max="30" value="${salvo?.placar_visitante ?? ""}" ${aberta ? "" : "disabled"} aria-label="Placar ${escapeAttr(timeNome(j.visitante))}">
        </div>${htmlTeam(j.visitante, "away")}</div>
        <div class="match-extra"><span class="badge info">${escapeHtml(j.estadio || "estádio a confirmar")}</span>${salvo ? `<span class="badge open saved-pill">salvo ${fmtDataLonga(salvo.atualizado_em || salvo.criado_em)}</span>` : `<span class="badge">não salvo</span>`}</div>
      </article>`;
    }).join("")}<div class="actions"><button class="btn" type="submit" ${aberta ? "" : "disabled"}>💾 Salvar palpites da rodada</button><button class="btn secondary" type="button" id="limpar-campos" ${aberta ? "" : "disabled"}>limpar campos</button></div></form>`;
    $("#form-palpites")?.addEventListener("submit", salvarPalpitesRodadaLegado);
    $("#limpar-campos")?.addEventListener("click", () => {
      if (!confirmarAcao("Limpar os placares preenchidos nesta tela? Nenhum dado já salvo será apagado.")) return;
      $$("#form-palpites input").forEach(i => { i.value = ""; });
      toast("Campos limpos. Os palpites já salvos foram preservados.", "ok");
    });
  }

  function coletarPalpitesRodadaLegado() {
    const payload = [];
    for (const j of jogosDaRodada(state.rodada)) {
      const id = jogoId(j);
      const pmEl = $(`[name="pm-${CSS.escape(id)}"]`);
      const pvEl = $(`[name="pv-${CSS.escape(id)}"]`);
      const pm = pmEl?.value === "" ? null : Number(pmEl?.value);
      const pv = pvEl?.value === "" ? null : Number(pvEl?.value);
      if (pm === null && pv === null) continue;
      if (!Number.isInteger(pm) || !Number.isInteger(pv) || pm < 0 || pv < 0 || pm > 30 || pv > 30) throw new Error(`Placar inválido em ${timeNome(j.mandante)} x ${timeNome(j.visitante)}.`);
      payload.push({ event_id: id, jogo_chave: jogoChave(j), jogo_uid: jogoUidCanonico(j), mandante: timeNome(j.mandante), visitante: timeNome(j.visitante), placar_mandante: pm, placar_visitante: pv, kickoff: j.data_iso || null, fecha_em: configEfetiva(state.rodada).fecha_em });
    }
    return payload;
  }

  async function salvarPalpitesRodadaLegado(ev) {
    ev.preventDefault();
    try {
      if (!rodadaAberta(state.rodada)) throw new Error("Rodada fora da janela de apostas.");
      const payload = coletarPalpitesRodadaLegado();
      if (!payload.length) throw new Error("Preencha ao menos um placar antes de salvar.");
      status("Salvando palpites com hash de comprovante...", "warn");
      const rows = await rpcRows("br_salvar_palpites", { p_participante_id: state.usuario.id, p_token: state.token, p_temporada: CFG.temporada || 2026, p_rodada: state.rodada, p_palpites: payload });
      const comprovante = rows[0] || {};
      await carregarMeusPalpites();
      renderResumo();
      renderApostasRodadaLegado();
      $("#conteudo")?.insertAdjacentHTML("afterbegin", `<div class="comprovante"><strong>🧾 Comprovante gerado</strong><p>Rodada ${state.rodada} · ${payload.length} palpites enviados.</p><p class="hash">${escapeHtml(comprovante.hash_fechamento || comprovante.hash || "hash indisponível")}</p></div>`);
      status(`✅ PALPITES GRAVADOS COM SUCESSO! Comprovante da rodada ${state.rodada} gerado.`, "ok");
      toast(`Palpites da rodada ${state.rodada} salvos com sucesso.`, "ok");
    } catch (err) {
      console.error(err); status(err.message || "Falha ao salvar palpites.", "err"); toast(err.message || "Falha ao salvar palpites.", "err");
    }
  }

  function valorCampoBloco(id, lado, rascunho) {
    const valorDraft = rascunho?.valores?.[id]?.[lado];
    if (valorDraft !== undefined) return valorDraft;
    const salvo = palpiteSalvoPara(id);
    return lado === "pm" ? (salvo?.placar_mandante ?? "") : (salvo?.placar_visitante ?? "");
  }

  function renderApostasBloco() {
    const root = $("#conteudo");
    const bloco = blocoDaRodada(state.rodada);
    const jogos = jogosDoBloco(bloco);
    const aberta = rodadaAberta(state.rodada);
    const st = statusJanela(state.rodada);
    if (!bloco?.bloco_id || !state.exec3InfraDisponivel) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>A infraestrutura das 30 partidas ainda não está ativa.</strong><p>Execute <code>supabase/brasileirao_apostas_exec19_apostas_blocos_30_partidas.sql</code> depois da Execução 2. Nenhum dado da rodada 20 foi alterado.</p></div></section>`;
      return;
    }
    if (!jogos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>${escapeHtml(bloco.nome)} ainda sem jogos no calendário.</strong><p>Os cards aparecerão assim que o workflow carregar as três rodadas.</p></div></section>`;
      return;
    }

    const rascunho = lerRascunhoBloco();
    state.draftRestaurado = Boolean(rascunho);
    state.draftDirty = Boolean(rascunho);
    const mobile = global.matchMedia?.("(max-width: 720px)")?.matches;
    const totalSalvo = state.meusPalpites.length;
    const avisoJanela = aberta
      ? `<div class="status ok">Janela única aberta para as 30 partidas. Salve quantas quiser e complete o restante depois.</div>`
      : `<div class="status warn">${st.texto}. ${st.detalhe}. Os 30 palpites ficam bloqueados juntos.</div>`;
    const avisoRascunho = rascunho ? `<div class="draft-banner" role="status"><strong>📝 Rascunho local restaurado</strong><span>Alterações não enviadas foram recuperadas neste navegador.</span><button type="button" class="btn ghost" id="descartar-rascunho-topo">Descartar</button></div>` : "";
    const avisoCobertura = jogos.length === 30 ? "" : `<div class="status warn"><strong>Calendário incompleto:</strong> ${jogos.length} de 30 partidas estão disponíveis. O progresso continua calculado sobre 30 e o jogo ausente aparecerá automaticamente quando o workflow atualizar o calendário.</div>`;
    const filtros = ["todos", ...Array.from({length: 3}, (_, i) => String(Number(bloco.rodada_inicio) + i))];

    root.innerHTML = `<section class="panel block-bet-hero"><div class="panel-inner">
      <div class="block-bet-heading"><div><div class="kicker">Apostas do bloco</div><h2>${escapeHtml(bloco.nome)}</h2><p>Uma única trava e um único comprovante para as três rodadas.</p></div><div class="block-deadline"><span>Prazo</span><strong>${escapeHtml(st.detalhe)}</strong></div></div>
      <div class="block-progress-line"><div class="block-progress-track"><span id="barra-progresso-bloco" style="width:${Math.min(100, (totalSalvo / 30) * 100)}%"></span></div><strong data-progresso-bloco>${totalSalvo}/30 preenchidos</strong><small data-faltantes-bloco>${totalSalvo === 30 ? "Bloco completo" : `Faltam ${30-totalSalvo}`}</small></div>
      <div class="block-round-filter" role="tablist" aria-label="Filtrar partidas do bloco">${filtros.map(f => `<button type="button" class="${state.filtroRodadaBloco === f ? "active" : ""}" data-filtro-bloco="${f}" role="tab" aria-selected="${state.filtroRodadaBloco === f}">${f === "todos" ? "Todos os 30 jogos" : `Rodada ${f}`}</button>`).join("")}</div>
    </div></section>${avisoJanela}${avisoCobertura}${avisoRascunho}
    <form id="form-palpites-bloco" class="block-matches-form">${Array.from({length: 3}, (_, idx) => Number(bloco.rodada_inicio) + idx).map((rodada, idx) => {
      const jogosRodada = jogosDaRodada(rodada);
      const salvosRodada = state.meusPalpites.filter(p => Number(p.rodada) === rodada).length;
      const visivel = state.filtroRodadaBloco === "todos" || state.filtroRodadaBloco === String(rodada);
      const open = !mobile || state.filtroRodadaBloco !== "todos" || idx === 0;
      return `<details class="round-bet-section" data-rodada-section="${rodada}" ${visivel ? "" : "hidden"} ${open ? "open" : ""}><summary><span><strong>Rodada ${rodada}</strong><small>${salvosRodada}/10 salvos</small></span><span class="round-section-chevron" aria-hidden="true">⌄</span></summary><div class="round-bet-content"><div class="matches">${jogosRodada.map(j => {
        const id = jogoIdAposta(j); const salvo = palpiteSalvoPara(j);
        const pm = valorCampoBloco(id, "pm", rascunho); const pv = valorCampoBloco(id, "pv", rascunho);
        return `<article class="match-card" data-event-id="${escapeAttr(id)}"><div class="match-top"><span>Rodada ${rodada} · ${fmtDataJogo(j)}</span><span class="badge ${aberta ? "open" : "lock"}">${aberta ? "aberto" : "travado"}</span></div><div class="match-body">${htmlTeam(j.mandante, "home")}<div class="score-inputs"><input data-event-id="${escapeAttr(id)}" data-lado="pm" type="number" inputmode="numeric" min="0" max="30" value="${escapeAttr(pm)}" ${aberta ? "" : "disabled"} aria-label="Placar ${escapeAttr(timeNome(j.mandante))}"><span>x</span><input data-event-id="${escapeAttr(id)}" data-lado="pv" type="number" inputmode="numeric" min="0" max="30" value="${escapeAttr(pv)}" ${aberta ? "" : "disabled"} aria-label="Placar ${escapeAttr(timeNome(j.visitante))}"></div>${htmlTeam(j.visitante, "away")}</div><div class="match-extra"><span class="badge info">${escapeHtml(j.estadio || "estádio a confirmar")}</span>${salvo ? `<span class="badge open saved-pill">salvo ${fmtDataLonga(salvo.atualizado_em || salvo.criado_em)}</span>` : `<span class="badge">não salvo</span>`}</div></article>`;
      }).join("") || `<div class="empty">Jogos da rodada ${rodada} ainda não carregados.</div>`}</div></div></details>`;
    }).join("")}
      <div class="block-form-actions"><button class="btn" type="submit" id="salvar-palpites-bloco" ${aberta ? "" : "disabled"}>💾 Salvar palpites preenchidos</button><button class="btn secondary" type="button" id="restaurar-servidor-bloco">Descartar alterações locais</button><span class="muted-note">O salvamento é progressivo: palpites omitidos permanecem como estavam.</span></div>
    </form>
    <div class="mobile-save-bar" id="mobile-save-bar"><div><strong data-progresso-bloco>${totalSalvo}/30 preenchidos</strong><small data-faltantes-bloco>${totalSalvo === 30 ? "Bloco completo" : `Faltam ${30-totalSalvo}`}</small></div><button class="btn" type="button" id="salvar-palpites-bloco-fixo" ${aberta ? "" : "disabled"}>Salvar palpites</button></div>`;

    $$('[data-filtro-bloco]').forEach(btn => btn.addEventListener("click", () => {
      state.filtroRodadaBloco = btn.dataset.filtroBloco;
      renderApostasBloco();
      global.scrollTo({ top: $("#conteudo")?.offsetTop || 0, behavior: "smooth" });
    }));
    const form = $("#form-palpites-bloco");
    form?.addEventListener("submit", salvarPalpitesBloco);
    $$('input[data-event-id]', form).forEach(input => input.addEventListener("input", () => { salvarRascunhoBloco(); atualizarProgressoFormularioBloco(); }));
    $("#salvar-palpites-bloco-fixo")?.addEventListener("click", () => form?.requestSubmit());
    $("#restaurar-servidor-bloco")?.addEventListener("click", () => { if (confirmarAcao("Descartar as alterações locais e restaurar os palpites já salvos?")) restaurarValoresServidorBloco(); });
    $("#descartar-rascunho-topo")?.addEventListener("click", restaurarValoresServidorBloco);
    atualizarProgressoFormularioBloco();
  }

  function coletarPalpitesBloco() {
    const bloco = blocoDaRodada(state.rodada);
    const valores = valoresAtuaisFormularioBloco();
    const payload = [];
    for (const j of jogosDoBloco(bloco)) {
      const id = jogoIdAposta(j); const v = valores[id] || { pm: "", pv: "" };
      if (v.pm === "" && v.pv === "") continue;
      const pm = Number(v.pm), pv = Number(v.pv);
      if (!Number.isInteger(pm) || !Number.isInteger(pv) || pm < 0 || pv < 0 || pm > 30 || pv > 30) throw new Error(`Placar inválido em ${timeNome(j.mandante)} x ${timeNome(j.visitante)}.`);
      payload.push({ rodada: Number(j.rodada), event_id: id, jogo_chave: jogoChave(j), jogo_uid: jogoUidCanonico(j), mandante: timeNome(j.mandante), visitante: timeNome(j.visitante), placar_mandante: pm, placar_visitante: pv, kickoff: j.data_iso || null });
    }
    return payload;
  }

  async function salvarPalpitesBloco(ev) {
    ev.preventDefault();
    if (state.salvandoPalpites) return;
    const bloco = blocoDaRodada(state.rodada);
    try {
      if (!bloco?.bloco_id || !state.exec3InfraDisponivel) throw new Error("A infraestrutura da Execução 3 ainda não está ativa.");
      if (!rodadaAberta(state.rodada)) throw new Error("Bloco fora da janela de apostas.");
      const payload = coletarPalpitesBloco();
      if (!payload.length) throw new Error("Preencha ao menos um placar antes de salvar.");
      state.salvandoPalpites = true; atualizarProgressoFormularioBloco();
      $$("#salvar-palpites-bloco, #salvar-palpites-bloco-fixo").forEach(b => { b.textContent = "Salvando…"; });
      status(`Salvando ${payload.length} palpites e recalculando o comprovante do bloco...`, "warn");
      const rows = await rpcRows("br_salvar_palpites_bloco_v1", { p_participante_id: state.usuario.id, p_token: state.token, p_temporada: CFG.temporada || 2026, p_bloco_id: bloco.bloco_id, p_palpites: payload });
      const comprovante = rows[0] || {};
      limparRascunhoBloco();
      await carregarMeusPalpites();
      renderResumo(); renderApostasBloco();
      const faltantes = Number(comprovante.faltantes ?? Math.max(0, 30 - Number(comprovante.total_palpites || 0)));
      $("#conteudo")?.insertAdjacentHTML("afterbegin", `<div class="comprovante block-receipt-inline"><strong>🧾 Comprovante do ${escapeHtml(bloco.nome)}</strong><p>${escapeHtml(String(comprovante.total_palpites || 0))} palpites persistidos${faltantes ? ` · ainda faltam ${faltantes}` : " · bloco completo"}.</p><p class="hash">${escapeHtml(comprovante.hash_bloco || "hash indisponível")}</p></div>`);
      const msg = faltantes ? `${comprovante.total_palpites} palpites salvos. Ainda faltam ${faltantes} partidas.` : `Todos os 30 palpites do ${bloco.nome} foram salvos.`;
      status(`✅ ${msg}`, "ok"); toast(msg, "ok");
    } catch (err) {
      console.error(err); status(err.message || "Falha ao salvar o bloco.", "err"); toast(err.message || "Falha ao salvar o bloco.", "err");
    } finally {
      state.salvandoPalpites = false;
      $$("#salvar-palpites-bloco, #salvar-palpites-bloco-fixo").forEach(b => {
        b.textContent = b.id === "salvar-palpites-bloco-fixo" ? "Salvar palpites" : "💾 Salvar palpites preenchidos";
      });
      atualizarProgressoFormularioBloco();
    }
  }

  function renderApostas() {
    return contextoEhBloco() ? renderApostasBloco() : renderApostasRodadaLegado();
  }

  function renderMeusRodadaLegado() {
    const root = $("#conteudo");
    if (!state.meusPalpites.length) { root.innerHTML = `<section class="panel"><div class="panel-inner empty">Você ainda não tem palpites salvos na rodada ${state.rodada}.</div></section>`; return; }
    const hash = state.meusPalpites.find(p => p.hash_fechamento)?.hash_fechamento || "—";
    root.innerHTML = `<section class="panel"><div class="panel-inner"><div class="kicker">Meus palpites</div><h2>Rodada ${state.rodada}</h2><p>Você pode consultar seus próprios palpites a qualquer momento.</p><div class="comprovante"><strong>Hash atual da rodada</strong><p class="hash">${escapeHtml(hash)}</p></div><div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Jogo</th><th>Meu palpite</th><th>Atualizado</th></tr></thead><tbody>${state.meusPalpites.map(p => `<tr><td>${escapeHtml(p.mandante)} x ${escapeHtml(p.visitante)}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td>${fmtDataLonga(p.atualizado_em || p.criado_em)}</td></tr>`).join("")}</tbody></table></div></div></section>`;
  }

  function renderMeusBloco() {
    const root = $("#conteudo"); const bloco = blocoDaRodada(state.rodada); const c = state.comprovanteBloco;
    if (!state.exec3InfraDisponivel) { root.innerHTML = `<section class="panel"><div class="panel-inner empty">A consulta de comprovantes do bloco será liberada após a migração da Execução 3.</div></section>`; return; }
    if (!state.meusPalpites.length) { root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>Nenhum palpite salvo no ${escapeHtml(bloco.nome)}.</strong><p>O comprovante único será criado no primeiro salvamento.</p></div></section>`; return; }
    root.innerHTML = `<section class="panel"><div class="panel-inner"><div class="kicker">Meu comprovante</div><h2>${escapeHtml(bloco.nome)}</h2><p>O hash representa o conjunto completo atualmente persistido nas três rodadas.</p><div class="receipt-grid"><div><span>Palpites</span><strong>${c?.total_palpites ?? state.meusPalpites.length}/30</strong></div><div><span>Última atualização</span><strong>${fmtDataLonga(c?.atualizado_em || state.meusPalpites[0]?.atualizado_em)}</strong></div><div class="receipt-hash"><span>SHA-256 do bloco</span><code>${escapeHtml(c?.hash_bloco || state.meusPalpites[0]?.hash_bloco || "—")}</code></div></div></div></section>${Array.from({length:3},(_,i)=>Number(bloco.rodada_inicio)+i).map(r => { const lista=state.meusPalpites.filter(p=>Number(p.rodada)===r); return `<details class="panel receipt-round" open><summary><strong>Rodada ${r}</strong><span>${lista.length}/10 palpites</span></summary><div class="panel-inner"><div class="table-wrap"><table class="data-table"><thead><tr><th>Jogo</th><th>Meu palpite</th><th>Atualizado</th></tr></thead><tbody>${lista.map(p=>`<tr><td>${escapeHtml(p.mandante)} x ${escapeHtml(p.visitante)}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td>${fmtDataLonga(p.atualizado_em || p.criado_em)}</td></tr>`).join("") || `<tr><td colspan="3">Nenhum palpite salvo nesta rodada.</td></tr>`}</tbody></table></div></div></details>`; }).join("")}`;
  }

  function renderMeus() {
    return contextoEhBloco() ? renderMeusBloco() : renderMeusRodadaLegado();
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

  function apuracaoBlocoPorInicio(inicio) {
    const lista = (state.apuracao && state.apuracao.blocos) || (state.rankingApostas && state.rankingApostas.ranking_blocos) || [];
    return lista.find(b => Number(b.rodada_inicio) === Number(inicio)) || null;
  }

  function rankingObjetoPorLiga(obj) {
    const pontuacaoConfiavel = payloadPontuacaoConfiavel(state.apuracao) || payloadPontuacaoConfiavel(state.rankingApostas);
    if (!obj || obj.sigilosa || !pontuacaoConfiavel) return [];
    const porLiga = obj.rankings_por_liga || obj.ranking_por_liga || {};
    const liga = ligaAtualObj();
    const chaves = [liga?.liga_id, liga?.slug, normalizarTexto(liga?.nome || ""), "liga-geral"].filter(Boolean).map(String);

    // Um alias/UUID de liga pode existir no payload com array vazio enquanto o
    // slug canônico (almoco-de-sexta) contém o ranking válido. Não interromper a
    // busca no primeiro array vazio: isso foi o que zerou visualmente R21–23.
    for (const chave of chaves) {
      const candidato = porLiga[chave];
      if (Array.isArray(candidato) && candidato.length) return candidato;
    }
    if (Array.isArray(obj.ranking) && obj.ranking.length) return obj.ranking;
    for (const chave of chaves) {
      if (Array.isArray(porLiga[chave])) return porLiga[chave];
    }
    return Array.isArray(obj.ranking) ? obj.ranking : [];
  }

  function estadoApuracaoTexto(obj) {
    const estado = String(obj?.estado_apuracao || "");
    if (obj?.concluida || obj?.concluido || estado === "concluida") return { texto: "Concluído", classe: "ok", icone: "✅" };
    if (estado === "atualizado") return { texto: "Atualizado", classe: "ok", icone: "📊" };
    if (estado === "parcial") return { texto: "Em apuração", classe: "warn", icone: "⏳" };
    if (estado === "aguardando_resultados") return { texto: "Aguardando resultados", classe: "warn", icone: "🕒" };
    if (obj?.sigilosa || estado === "sigilosa") return { texto: "Sigiloso", classe: "lock", icone: "🔒" };
    return { texto: "Em validação", classe: "warn", icone: "🔎" };
  }

  function lideresDoRanking(ranking) {
    if (!Array.isArray(ranking) || !ranking.length) return [];
    const top = ranking[0];
    return ranking.filter(r => Number(r.pontos||0)===Number(top.pontos||0) && Number(r.cravadas||0)===Number(top.cravadas||0) && Number(r.saldos||0)===Number(top.saldos||0) && Number(r.resultados||0)===Number(top.resultados||0) && Number(r.erros||0)===Number(top.erros||0)).map(r => r.membro);
  }

  function palpitesPublicosDaApuracao(rodada) {
    const ap = apuracaoRodada(rodada);
    const linhas = [];
    (ap?.jogos || []).forEach(jogo => {
      const resultado = jogo.resultado || {};
      const eventId = String(resultado.event_id || jogo.event_id || "");
      (jogo.palpites || []).forEach(palpite => {
        linhas.push({
          participante_id: palpite.participante_id || null,
          membro: palpite.membro || "",
          rodada: Number(rodada),
          event_id: eventId,
          mandante: resultado.mandante || "",
          visitante: resultado.visitante || "",
          placar_mandante: palpite.placar_mandante,
          placar_visitante: palpite.placar_visitante
        });
      });
    });
    return linhas;
  }

  function palpitesParticipanteRodada(membro, participanteId, rodada, opcoes={}) {
    const linhas = [
      ...(state.publicos || []).filter(p => Number(p.rodada || state.rodada) === Number(rodada)),
      ...palpitesPublicosDaApuracao(rodada)
    ];
    const filtrados = linhas.filter(p =>
      (participanteId && p.participante_id && String(p.participante_id) === String(participanteId))
      || ((!participanteId || !p.participante_id) && normalizarTexto(p.membro || "") === normalizarTexto(membro || ""))
    );
    const vistos = new Set();
    const minha = filtrados.filter(p => {
      const chave = String(p.event_id || "");
      if (!chave || vistos.has(chave)) return false;
      vistos.add(chave);
      return true;
    });
    const pontosMap = mapaPontosRodada(rodada);
    const ap = apuracaoRodada(rodada);
    const resultados = new Map();
    (ap?.jogos || []).forEach(j => {
      const r = j.resultado || {};
      resultados.set(String(r.event_id || j.event_id || ""), r);
    });

    const exibidos = opcoes.somenteApurados
      ? minha.filter(p => resultados.has(String(p.event_id || "")))
      : minha;
    if (!exibidos.length) return '<p class="muted-note" style="margin:8px 0">Nenhum palpite apurado nesta visão.</p>';

    exibidos.sort((a, b) => {
      const ra = resultados.get(String(a.event_id || ""));
      const rb = resultados.get(String(b.event_id || ""));
      return String(ra?.data_iso || "").localeCompare(String(rb?.data_iso || ""));
    });

    return `<div class="palpite-expand-grid">${exibidos.map(p => {
      const det = (p.participante_id && pontosMap.get(`id:${p.participante_id}::${p.event_id || ""}`))
        || pontosMap.get(`nome:${normalizarTexto(p.membro || "")}::${p.event_id || ""}`)
        || {};
      const real = resultados.get(String(p.event_id || ""));
      const cls = det.pontos != null ? pontosClasse(det.pontos) : "";
      return `<div class="palpite-card ${cls}"><div class="pex-jogo">${escapeHtml(p.mandante || real?.mandante || "Mandante")} <em>×</em> ${escapeHtml(p.visitante || real?.visitante || "Visitante")}</div><div class="pex-resultado-real ${cls}"><span class="pex-score">${real ? `${real.placar_mandante} × ${real.placar_visitante}` : "—"}</span>${det.pontos != null ? `<span class="pex-veredito ${cls}">${escapeHtml(tipoLabel(det.tipo))} · ${det.pontos} pts</span>` : ""}</div><div class="pex-palpite-row"><span class="pex-pal-label">Palpite:</span><span class="pex-pal-score">${p.placar_mandante} × ${p.placar_visitante}</span></div></div>`;
    }).join("")}</div>`;
  }

  function palpitesParticipanteBloco(membro, participanteId, bloco) {
    const inicio = Number(bloco?.rodada_inicio);
    const fim = Number(bloco?.rodada_fim);
    if (!Number.isFinite(inicio) || !Number.isFinite(fim) || fim < inicio) {
      return '<p class="muted-note" style="margin:8px 0">Palpites não disponíveis neste bloco.</p>';
    }
    const secoes = [];
    for (let rodada = inicio; rodada <= fim; rodada += 1) {
      const ap = apuracaoRodada(rodada);
      if (!ap || Number(ap.jogos_apurados || 0) <= 0) continue;
      const detalhes = palpitesParticipanteRodada(
        membro,
        participanteId,
        rodada,
        { somenteApurados: true }
      );
      if (!detalhes.includes("palpite-card")) continue;
      secoes.push(`<section class="palpite-block-round"><div class="kicker">Rodada ${rodada}</div>${detalhes}</section>`);
    }
    return secoes.join("") || '<p class="muted-note" style="margin:8px 0">Nenhum palpite apurado neste bloco.</p>';
  }

  function rankingCardsHtml(ranking, opcoes={}) {
    const lideres = new Set(opcoes.lideres || lideresDoRanking(ranking));
    const final = Boolean(opcoes.final);
    const rodadaDetalhe = opcoes.rodadaDetalhe;
    const blocoDetalhe = opcoes.blocoDetalhe;
    const estiloRodada20 = Boolean(opcoes.estiloRodada20);
    const posIcons = ["", "🥇", "🥈", "🥉"];
    return (ranking || []).map((r, idx) => {
      const destaque = lideres.has(r.membro);
      const indice = Number(r.indice_aproveitamento || 0).toFixed(1).replace(".", ",");
      const badges = estiloRodada20
        ? `<span class="rk-badge">✅ ${r.cravadas || 0} cravada${Number(r.cravadas || 0) !== 1 ? "s" : ""}</span><span class="rk-badge">📊 ${r.resultados || 0} resultado${Number(r.resultados || 0) !== 1 ? "s" : ""}</span><span class="rk-badge">💧 saldo +${r.saldos || 0}</span><span class="rk-badge rk-badge-err">❌ ${r.erros || 0} erro${Number(r.erros || 0) !== 1 ? "s" : ""}</span>`
        : `<span class="rk-badge">✅ ${r.cravadas || 0} exato${Number(r.cravadas||0)!==1?"s":""}</span><span class="rk-badge">💧 ${r.saldos || 0} saldo${Number(r.saldos||0)!==1?"s":""}</span><span class="rk-badge">📊 ${r.resultados || 0} resultado${Number(r.resultados||0)!==1?"s":""}</span><span class="rk-badge rk-badge-err">❌ ${r.erros || 0} erro${Number(r.erros||0)!==1?"s":""}</span><span class="rk-badge rk-index">🎯 ${indice}%</span>`;
      const textoDetalhes = estiloRodada20 || blocoDetalhe ? "Ver palpites" : "Ver palpites da rodada";
      const corpoDetalhes = blocoDetalhe
        ? palpitesParticipanteBloco(r.membro, r.participante_id, blocoDetalhe)
        : rodadaDetalhe
          ? palpitesParticipanteRodada(r.membro, r.participante_id, rodadaDetalhe)
          : "";
      return `<article class="rk-card${destaque ? " rk-vencedor" : ""}" id="rk-${idx}-${normalizarTexto(r.membro)}"><div class="rk-main"><div class="rk-pos">${posIcons[r.pos] || r.pos}</div><div class="rk-info"><div class="rk-nome">${escapeHtml(r.membro)}${destaque ? (final ? " 🏆" : " ⭐") : ""}</div><div class="rk-badges">${badges}</div></div><div class="rk-pts"><strong>${r.pontos || 0}</strong><small>pts</small></div></div>${corpoDetalhes ? `<details class="rk-palpites"><summary><span>${textoDetalhes}</span><i aria-hidden="true"></i></summary><div class="rk-palpites-body">${corpoDetalhes}</div></details>` : ""}</article>`;
    }).join("");
  }

  function rankingHeaderHtml({kicker, titulo, objeto, ranking, final=false}) {
    const estado = estadoApuracaoTexto(objeto);
    const apurados = Number(objeto?.jogos_apurados || state.rankingApostas?.resumo?.jogos_apurados_publicados || 0);
    const total = Number(objeto?.total_jogos || objeto?.jogos_previstos || (kicker === "Ranking geral" ? apurados : 0));
    const lideres = lideresDoRanking(ranking);
    return `<div class="rk-header"><div><div class="kicker">${escapeHtml(kicker)}</div><h2>${escapeHtml(titulo)} · ${escapeHtml(nomeLigaAtual())}</h2><p class="rk-winner-line">${estado.icone} <strong>${escapeHtml(estado.texto)}</strong>${lideres.length ? ` · ${final ? "vencedor" : "liderança"}: ${lideres.map(escapeHtml).join(", ")}` : ""}</p></div><div class="rk-header-kpis"><span><strong>${ranking.length}</strong><small>participantes</small></span><span><strong>${apurados}${total ? `/${total}` : ""}</strong><small>jogos apurados</small></span></div></div>`;
  }

  function renderRankingR20() {
    const rodada = 20;
    const ap = apuracaoRodada(rodada);
    if (!ap || ap.sigilosa) {
      state.rankingExportAtual = null;
      return '<div class="panel"><div class="panel-inner empty"><strong>Ranking da Rodada 20 indisponível.</strong></div></div>';
    }
    const ranking = apuracaoRodadaConfiavel(ap) ? rankingRodadaPorLiga(ap, state.ligaAtual) : [];
    const final = Boolean(ap.concluida);
    state.rankingExportAtual = { tipo: "rodada", nome: "rodada-20", rodada, ranking, jogos_apurados: Number(ap.jogos_apurados || 0) };
    return `${rankingHeaderHtml({kicker:"Ranking",titulo:"Rodada 20",objeto:ap,ranking,final})}${ranking.length ? `<div class="export-row"><button class="btn secondary" type="button" id="export-ranking">⬇️ Exportar CSV</button></div><div class="rk-list">${rankingCardsHtml(ranking,{final,rodadaDetalhe:20,estiloRodada20:true})}</div>` : '<div class="panel"><div class="panel-inner empty">Nenhum resultado apurado na Rodada 20.</div></div>'}`;
  }

  function objetoTemRanking(obj) {
    if (!obj) return false;
    if (Array.isArray(obj.ranking) && obj.ranking.length) return true;
    const porLiga = obj.rankings_por_liga || obj.ranking_por_liga || {};
    return Object.values(porLiga).some(v => Array.isArray(v) && v.length);
  }

  function mesclarBlocoRanking(apuracao, publico) {
    if (!apuracao) return publico || null;
    if (!publico) return apuracao;
    // Metadados de progresso vêm preferencialmente da apuração mais recente; os
    // arrays de ranking podem vir do artefato público quando ele for o único dos
    // dois a possuir dados. Isso evita um JSON parcial/transitório zerar a tela.
    const principal = Number(apuracao.jogos_apurados || 0) >= Number(publico.jogos_apurados || 0) ? apuracao : publico;
    const auxiliar = principal === apuracao ? publico : apuracao;
    const out = { ...auxiliar, ...principal };
    if (!objetoTemRanking(principal) && objetoTemRanking(auxiliar)) {
      out.ranking = auxiliar.ranking;
      out.rankings_por_liga = auxiliar.rankings_por_liga || auxiliar.ranking_por_liga || {};
      out.ranking_por_liga = auxiliar.ranking_por_liga || auxiliar.rankings_por_liga || {};
    }
    if ((!Array.isArray(out.rodadas) || !out.rodadas.length) && Array.isArray(auxiliar.rodadas)) out.rodadas = auxiliar.rodadas;
    if ((!Array.isArray(out.pendencias) || !out.pendencias.length) && Array.isArray(auxiliar.pendencias)) out.pendencias = auxiliar.pendencias;
    return out;
  }

  function blocosRanking() {
    const a = Array.isArray(state.apuracao?.blocos) ? state.apuracao.blocos : [];
    const b = Array.isArray(state.rankingApostas?.ranking_blocos) ? state.rankingApostas.ranking_blocos : [];
    const inicios = new Set([...a, ...b].map(x => Number(x?.rodada_inicio || 0)).filter(Boolean));
    return Array.from(inicios).sort((x, y) => x - y).map(inicio => mesclarBlocoRanking(
      a.find(x => Number(x?.rodada_inicio || 0) === inicio) || null,
      b.find(x => Number(x?.rodada_inicio || 0) === inicio) || null
    )).filter(Boolean);
  }

  function blocoRankingCronologicoMaisAtual(blocos) {
    return (Array.isArray(blocos) ? blocos : [])
      .filter(bloco => bloco && bloco.publicada === true && bloco.sigilosa !== true)
      .slice()
      .sort((a, b) => Number(b.rodada_inicio || 0) - Number(a.rodada_inicio || 0))[0] || null;
  }

  function aplicarDestinoCronologicoInicial() {
    if (
      !state.usuario
      || state.destinoCronologicoResolvido
      || state.abaInicialExplicita
      || state.contextoInicialExplicito
      || state.abaEscolhidaManualmente
    ) return;

    state.destinoCronologicoResolvido = true;
    const campeonato = blocoCampeonatoAtual();
    if (campeonato) {
      state.rodadaAutomatica = campeonato.inicio;
      state.rodadaAutomaticaResolvida = true;
      state.rodadaEscolhidaManualmente = false;
      state.rodada = campeonato.inicio;
      // O bloco futuro aberto aparece no cartão "AÇÃO AGORA", mas não sequestra
      // a navegação. Enquanto a R23 está em curso, abrir a página Ranking mostra
      // R21–23. O avanço para R24–26 ocorre no primeiro kickoff desse bloco.
      state.aba = "ranking";
      return;
    }

    const blocoPublicado = blocoRankingCronologicoMaisAtual(blocosRanking());
    const inicioBlocoPublicado = Number(blocoPublicado?.rodada_inicio);
    if (!Number.isFinite(inicioBlocoPublicado)) return;
    state.rodadaAutomatica = inicioBlocoPublicado;
    state.rodadaAutomaticaResolvida = true;
    state.rodadaEscolhidaManualmente = false;
    state.rodada = inicioBlocoPublicado;
    state.aba = "ranking";
  }

  function renderRankingBloco() {
    const contexto = blocoDaRodada(state.rodada) || blocoEstaticoDaRodada(state.rodada);
    const inicio = Number(contexto?.rodada_inicio || 0);
    const bloco = blocosRanking().find(b => Number(b.rodada_inicio) === inicio) || null;
    if (!bloco) {
      state.rankingExportAtual = null;
      return '<div class="panel"><div class="panel-inner empty">Ranking deste bloco ainda não disponível.</div></div>';
    }
    if (bloco.sigilosa) {
      state.rankingExportAtual = null;
      const resumo = estadoBlocoResumo(inicio);
      const aberta = resumo?.statusApostas === "aberta";
      return `<div class="panel"><div class="panel-inner empty"><strong>Bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}${aberta ? " · apostas abertas" : ""}.</strong><p>O ranking ficará visível automaticamente quando os palpites forem publicados no fechamento do bloco.</p></div></div>`;
    }
    const ranking = rankingObjetoPorLiga(bloco);
    const final = Boolean(bloco.concluido);
    const apurados = Number(bloco.jogos_apurados || 0);
    const pendentes = Math.max(0, Number(bloco.jogos_pendentes ?? (30 - apurados)));
    const adiados = (bloco.pendencias || []).filter(p => p && p.adiado).length;
    state.rankingExportAtual = { tipo:"bloco", nome:`bloco-${bloco.rodada_inicio}-${bloco.rodada_fim}`, ranking, jogos_apurados:apurados };
    const situacao = final
      ? ''
      : `<div class="status warn"><strong>⏳ EM APURAÇÃO</strong> · ${pendentes} jogo${pendentes === 1 ? "" : "s"} pendente${pendentes === 1 ? "" : "s"}${adiados ? ` / adiado${adiados === 1 ? "" : "s"}` : ""}. O bloco seguinte funciona normalmente quando chegar a vez dele.</div>`;
    return `${rankingHeaderHtml({kicker:"Ranking do bloco",titulo:bloco.nome||`Bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}`,objeto:bloco,ranking,final})}${situacao}<div class="block-round-progress">${(bloco.rodadas||[]).map(r=>`<div><span>Rodada ${r.rodada}</span><strong>${r.jogos_apurados}/10</strong><small>${r.concluida?'concluída':'em andamento'}</small></div>`).join('')}</div>${ranking.length?`<div class="export-row"><button class="btn secondary" type="button" id="export-ranking">⬇️ Exportar CSV</button></div><div class="rk-list">${rankingCardsHtml(ranking,{final,blocoDetalhe:bloco,estiloRodada20:true})}</div>`:'<div class="panel"><div class="panel-inner empty">Aguardando o primeiro resultado final do bloco.</div></div>'}`;
  }

  function renderRanking() {
    const root = $("#conteudo");
    const conteudo = Number(state.rodada) === 20 ? renderRankingR20() : renderRankingBloco();
    root.innerHTML = `<section class="ranking-rodada-section">${conteudo}</section>`;
    $('#export-ranking')?.addEventListener('click', exportarRankingCsv);
  }

  function renderPublicoRodadaLegado() {
    const root = $("#conteudo");
    const ap = apuracaoRodada(state.rodada);
    const pontosMap = mapaPontosRodada(state.rodada);
    if (!rodadaPublica(state.rodada) && !state.publicos.length) {
      root.innerHTML = `<section class="panel"><div class="panel-inner empty"><strong>Palpites ainda sigilosos.</strong><p>A rodada ${state.rodada} só abre para todos após o fechamento/publicação.</p></div></section>`;
      return;
    }
    if (!state.publicos.length) { root.innerHTML = `<section class="panel"><div class="panel-inner empty">Nenhum palpite público encontrado para a rodada ${state.rodada}.</div></section>`; return; }
    const apConfiavel = ap && !ap.sigilosa && apuracaoRodadaConfiavel(ap);
    const jogosApurados = apConfiavel ? Number(ap.jogos_apurados || 0) : 0;
    root.innerHTML = `<section class="panel"><div class="panel-inner"><div class="kicker">Palpites públicos</div><h2>Rodada ${state.rodada} · ${escapeHtml(nomeLigaAtual())}</h2><p>Lista aberta após a publicação da rodada.</p>${jogosApurados > 0 ? `<div class="status ok">Apuração publicada · ${jogosApurados} jogos encerrados e apurados.</div>` : `<div class="status warn">Palpites publicados; a pontuação aparecerá após o encerramento dos jogos.</div>`}<div class="export-row"><button class="btn secondary" type="button" id="export-publicos">⬇️ Exportar palpites CSV</button></div><div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Participante</th><th>Jogo</th><th>Palpite</th><th>Pontos</th><th>Tipo</th><th>Hash</th></tr></thead><tbody>${state.publicos.map(p => { const det=(p.participante_id && pontosMap.get(`id:${p.participante_id}::${p.event_id || ""}`)) || pontosMap.get(`nome:${normalizarTexto(p.membro || "")}::${p.event_id || ""}`) || {}; return `<tr><td>${escapeHtml(p.membro)}</td><td>${escapeHtml(p.mandante)} x ${escapeHtml(p.visitante)}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td class="num ${pontosClasse(det.pontos)}">${det.pontos ?? "—"}</td><td>${escapeHtml(tipoLabel(det.tipo))}</td><td class="hash">${escapeHtml(p.hash_fechamento || "—")}</td></tr>`; }).join("")}</tbody></table></div></div></section>`;
    $("#export-publicos")?.addEventListener("click", exportarPublicosCsv);
  }

  function renderPublicoBloco() {
    const root = $("#conteudo"); const bloco = blocoDaRodada(state.rodada);
    if (!state.exec3InfraDisponivel) { root.innerHTML = `<section class="panel"><div class="panel-inner empty">A visualização pública por bloco será liberada após a migração da Execução 3.</div></section>`; return; }
    const filtros = ["bloco", ...Array.from({length:3},(_,i)=>String(Number(bloco.rodada_inicio)+i))];
    const lista = state.publicoFiltro === "bloco" ? state.publicos : state.publicos.filter(p => Number(p.rodada) === Number(state.publicoFiltro));
    const rodadasPublicadas = Array.from(new Set(state.publicos.map(p => Number(p.rodada)))).sort((a,b)=>a-b);
    root.innerHTML = `<section class="panel"><div class="panel-inner"><div class="kicker">Palpites públicos</div><h2>${escapeHtml(bloco.nome)} · ${escapeHtml(nomeLigaAtual())}</h2><p>Você pode consultar o bloco completo ou isolar uma das rodadas já publicadas. Rodadas ainda sigilosas não são retornadas pelo banco.</p><div class="block-round-filter public-filter" role="tablist">${filtros.map(f => `<button type="button" data-publico-filtro="${f}" class="${state.publicoFiltro===f ? "active" : ""}" role="tab" aria-selected="${state.publicoFiltro===f}">${f === "bloco" ? "Bloco completo" : `Rodada ${f}`}</button>`).join("")}</div>${rodadasPublicadas.length ? `<div class="status ok">Rodadas públicas neste bloco: ${rodadasPublicadas.join(", ")}.</div>` : `<div class="status warn">Os palpites continuam sigilosos. Nenhuma rodada do bloco foi publicada.</div>`}<div class="export-row"><button class="btn secondary" type="button" id="export-publicos" ${lista.length ? "" : "disabled"}>⬇️ Exportar visão atual CSV</button></div>${lista.length ? `<div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Rodada</th><th>Participante</th><th>Jogo</th><th>Palpite</th><th>Pontos</th><th>Tipo</th><th>Hash do bloco</th></tr></thead><tbody>${lista.map(p => { const pontosMap=mapaPontosRodada(p.rodada); const det=(p.participante_id && pontosMap.get(`id:${p.participante_id}::${p.event_id || ""}`)) || pontosMap.get(`nome:${normalizarTexto(p.membro || "")}::${p.event_id || ""}`) || {}; return `<tr><td>R${p.rodada}</td><td>${escapeHtml(p.membro)}</td><td>${escapeHtml(p.mandante)} x ${escapeHtml(p.visitante)}</td><td class="num">${p.placar_mandante} x ${p.placar_visitante}</td><td class="num ${pontosClasse(det.pontos)}">${det.pontos ?? "—"}</td><td>${escapeHtml(tipoLabel(det.tipo))}</td><td class="hash">${escapeHtml(p.hash_bloco || "—")}</td></tr>`; }).join("")}</tbody></table></div>` : `<div class="empty">Nenhum palpite disponível nesta visão.</div>`}</div></section>`;
    $$('[data-publico-filtro]').forEach(btn => btn.addEventListener("click", () => { state.publicoFiltro=btn.dataset.publicoFiltro; renderPublicoBloco(); }));
    $("#export-publicos")?.addEventListener("click", exportarPublicosCsv);
  }

  async function renderPublico() {
    await carregarPublicos();
    return contextoEhBloco() ? renderPublicoBloco() : renderPublicoRodadaLegado();
  }

  async function carregarAdmin() {
    if (!canAdminAny()) return;
    await carregarBlocosApostasAdmin();
    try {
      const [participantes, ligas] = await Promise.all([
        rpcRows("br_admin_listar_participantes", { p_admin_id: state.usuario.id, p_token: state.token }),
        rpcRows("br_admin_listar_ligas", { p_admin_id: state.usuario.id, p_token: state.token })
      ]);
      state.participantes = participantes;
      state.ligasAdmin = ligas;
      if (!state.adminLigaSelecionada && ligas.length) state.adminLigaSelecionada = ligas[0].liga_id;
      const [progresso, ligaMembros] = await Promise.all([
        carregarProgressoAdminContexto("br_admin_progresso_rodada_liga", {
          p_liga_id: state.adminLigaSelecionada || null
        }),
        rpcRows("br_admin_listar_liga_participantes", { p_admin_id: state.usuario.id, p_token: state.token, p_liga_id: null })
      ]);
      state.progresso = progresso;
      state.ligaMembros = ligaMembros;
    } catch (err) {
      console.warn("Admin por liga indisponível; tentando fallback geral", err);
      try {
        state.progresso = await carregarProgressoAdminContexto("br_admin_progresso_rodada");
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
    const atual = state.rankingExportAtual || { tipo: "geral", nome: "ranking-geral", ranking: rankingGeralConfiavel(), jogos_apurados: 0 };
    const linhas = [["tipo", "liga", "contexto", "pos", "participante", "pontos", "indice_aproveitamento", "jogos_apurados", "cravadas", "saldos", "resultados", "erros", "palpites_validos", "vitorias_rodada", "vitorias_bloco"]];
    (atual.ranking || []).forEach(r => linhas.push([atual.tipo, nomeLigaAtual(), atual.nome, r.pos, r.membro, r.pontos, r.indice_aproveitamento ?? "", r.jogos_apurados ?? atual.jogos_apurados ?? "", r.cravadas || 0, r.saldos || 0, r.resultados || 0, r.erros || 0, r.palpites_validos || 0, r.vitorias_rodada || 0, r.vitorias_bloco || 0]));
    baixarCsv(`ranking-${ligaSlugAtual()}-${atual.nome || atual.tipo}.csv`, linhas);
  }

  function exportarPublicosCsv() {
    const linhas = [["liga", "contexto", "rodada", "participante", "jogo", "palpite", "pontos", "tipo", "hash", "atualizado_em"]];
    const lista = contextoEhBloco() && state.publicoFiltro !== "bloco" ? state.publicos.filter(p => Number(p.rodada) === Number(state.publicoFiltro)) : state.publicos;
    lista.forEach(p => {
      const rodada = Number(p.rodada || state.rodada);
      const pontosMap = mapaPontosRodada(rodada);
      const det = (p.participante_id && pontosMap.get(`id:${p.participante_id}::${p.event_id || ""}`)) || pontosMap.get(`nome:${normalizarTexto(p.membro || "")}::${p.event_id || ""}`) || {};
      linhas.push([nomeLigaAtual(), contextoLabel(), rodada, p.membro, `${p.mandante} x ${p.visitante}`, `${p.placar_mandante} x ${p.placar_visitante}`, det.pontos ?? "", tipoLabel(det.tipo), p.hash_bloco || p.hash_fechamento || "", p.atualizado_em || ""]);
    });
    const sufixo = contextoEhBloco() ? `${blocoDaRodada(state.rodada).rodada_inicio}-${blocoDaRodada(state.rodada).rodada_fim}-${state.publicoFiltro}` : `rodada-${state.rodada}`;
    baixarCsv(`palpites-publicos-${ligaSlugAtual()}-${sufixo}.csv`, linhas);
  }

  function exportarAuditoriaCsv() {
    const linhas = [["liga", "rodada", "participante", "login", "preenchido", "total_jogos", "percentual", "hash", "primeiro_envio", "ultimo_envio", "alteracoes"]];
    state.auditoria.forEach(r => linhas.push([nomeLigaRelatorio(), state.rodada, r.nome, r.login, r.total_palpites, r.total_jogos, r.percentual, r.hash_fechamento || "", r.primeiro_envio || "", r.ultimo_envio || "", r.alteracoes || 0]));
    baixarCsv(`auditoria-${slugLigaRelatorio()}-rodada-${state.rodada}.csv`, linhas);
  }

  function exportarProgressoCsv() {
    const contexto = contextoAdminAtual();
    const rodadas = contexto.rodadas.join("-");
    const linhas = [["liga", "contexto", "rodadas", "participante", "login", "status", "preenchido", "total_jogos", "percentual"]];
    state.progresso.forEach(p => linhas.push([nomeLigaRelatorio(), contexto.label, rodadas, p.nome, p.login, p.ativo ? "ativo" : "inativo", p.total_palpites, p.total_jogos, p.percentual]));
    baixarCsv(`progresso-${slugLigaRelatorio()}-${contexto.slug}.csv`, linhas);
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


  function classeStatusBloco(bloco) {
    const st = String(bloco?.status || "futura").toLowerCase();
    if (["fechada", "bloqueada"].includes(st)) return "lock";
    if (st === "aberta") return "open";
    if (st === "programada") return "warn";
    return "neutral";
  }

  function renderPainelBlocosAdminHtml() {
    if (!isAdminGlobal()) return "";
    if (!state.blocosInfraDisponivel) {
      return `<article class="panel admin-section admin-block-panel" id="admin-blocos"><div class="panel-inner">
        <div class="kicker">Execução 2 · infraestrutura</div><h2>Blocos de três rodadas</h2>
        <div class="status warn"><strong>Migração ainda não aplicada no Supabase.</strong><br>Rode o arquivo <code>supabase/brasileirao_apostas_exec18_blocos_3_rodadas.sql</code>. Até lá, a Rodada 20 e toda a interface da Execução 1 continuam funcionando normalmente.</div>
      </div></article>`;
    }

    const bloco = blocoAdminAtual();
    if (!bloco) {
      return `<article class="panel admin-section admin-block-panel" id="admin-blocos"><div class="panel-inner empty"><strong>Nenhum bloco cadastrado.</strong><p>Reexecute a migração idempotente da Execução 2.</p></div></article>`;
    }

    const detectado = primeiroJogoDetectadoBloco(bloco);
    const recomendado = bloco.fechamento_recomendado_em || fechamentoRecomendado(bloco.primeiro_jogo_em);
    const conforme = Boolean(bloco.fechamento_conforme_recomendacao);
    const options = (state.blocosApostas || []).map(b => `<option value="${escapeAttr(b.bloco_id)}" ${String(b.bloco_id) === String(bloco.bloco_id) ? "selected" : ""}>${escapeHtml(b.nome)} · R${b.rodada_inicio}–R${b.rodada_fim}</option>`).join("");
    const statusOptions = ["futura", "programada", "aberta", "fechada", "bloqueada"].map(st => `<option value="${st}" ${String(bloco.status) === st ? "selected" : ""}>${st}</option>`).join("");
    const recomendacaoTexto = recomendado ? fmtDataLonga(recomendado) : "aguardando o primeiro jogo";
    const apuracaoBloco = apuracaoBlocoPorInicio(bloco.rodada_inicio);
    const jogosApuradosBloco = Number(apuracaoBloco?.jogos_apurados ?? bloco.jogos_apurados ?? 0);
    const apuracaoConcluidaBloco = Boolean(apuracaoBloco?.concluido ?? bloco.apuracao_concluida);
    const divergencia = bloco.fecha_em && recomendado && !conforme
      ? `<div class="block-warning">⚠️ O fechamento salvo difere da regra recomendada de 1 hora. Uma nova alteração exigirá confirmação e justificativa.</div>`
      : `<div class="block-rule-ok">✓ Regra operacional: fechamento 1 hora antes do primeiro jogo da Rodada ${bloco.rodada_inicio}.</div>`;

    return `<article class="panel admin-section admin-block-panel" id="admin-blocos"><div class="panel-inner">
      <div class="kicker">Execução 2 · infraestrutura Supabase</div>
      <div class="admin-window-title"><div><h2>Blocos de três rodadas</h2><p>Uma única abertura e um único fechamento valem para as três rodadas. A Rodada 20 não pertence a bloco algum.</p></div><span class="badge ${classeStatusBloco(bloco)}">${escapeHtml(bloco.status || "futura")}</span></div>
      <div class="block-selector-row"><label>Bloco para configurar<select id="admin-bloco-selecionado">${options}</select></label><div class="block-version">Versão <strong>${Number(bloco.versao || 1)}</strong><span>controle contra sobrescrita</span></div></div>
      <div class="block-metrics">
        <div><span>Rodadas</span><strong>${bloco.rodada_inicio}–${bloco.rodada_fim}</strong></div>
        <div><span>Configurações vinculadas</span><strong>${Number(bloco.rodadas_configuradas || 0)}/3</strong></div>
        <div><span>Palpites vinculados</span><strong>${Number(bloco.total_palpites || 0)}</strong></div>
        <div><span>Apuração automática</span><strong>${jogosApuradosBloco}/30</strong><small>${apuracaoConcluidaBloco ? "concluída" : "em acompanhamento"}</small></div>
        <div><span>Fechamento recomendado</span><strong>${escapeHtml(recomendacaoTexto)}</strong></div>
      </div>
      ${divergencia}
      <form id="admin-bloco-form" class="admin-form admin-block-form">
        <div class="two"><label>Primeiro jogo da Rodada ${bloco.rodada_inicio}<input id="bloco-primeiro-jogo" type="datetime-local" value="${toDatetimeLocal(bloco.primeiro_jogo_em)}"></label><label>Abertura do bloco<input id="bloco-abre" type="datetime-local" value="${toDatetimeLocal(bloco.abre_em)}"></label></div>
        <div class="two"><label>Fechamento único<input id="bloco-fecha" type="datetime-local" value="${toDatetimeLocal(bloco.fecha_em)}"></label><label>Status do bloco<select id="bloco-status">${statusOptions}</select></label></div>
        <label>Observação / justificativa<textarea id="bloco-observacao" rows="3" placeholder="Obrigatória para horário diferente da recomendação ou alteração sensível">${escapeHtml(bloco.observacao || "")}</textarea></label>
        <div class="block-tools">
          <button class="btn secondary" type="button" id="usar-primeiro-jogo-detectado" ${detectado ? "" : "disabled"}>⚽ Usar 1º jogo detectado${detectado ? ` · ${escapeHtml(fmtDataLonga(detectado))}` : ""}</button>
          <button class="btn secondary" type="button" id="aplicar-fechamento-recomendado">⏱️ Aplicar fechamento de 1h</button>
        </div>
        <div class="actions admin-save-row"><button class="btn" type="submit">💾 Salvar bloco inteiro</button><span class="muted-note">A gravação materializa a mesma janela nas três rodadas e registra versão, administrador, antes/depois e justificativa.</span></div>
        <div id="bloco-inline-feedback" class="admin-inline-feedback" aria-live="polite">Última atualização: ${escapeHtml(fmtDataLonga(bloco.atualizado_em))}.</div>
      </form>
    </div></article>`;
  }

  function renderPainelRodadaVinculadaHtml(cfg, bloco) {
    const cfgPersistida = configDaRodada(state.rodada);
    const materializada = Boolean(cfgPersistida && cfgPersistida.bloco_id && String(cfgPersistida.bloco_id) === String(bloco.bloco_id));
    if (!materializada) {
      return `<article class="panel admin-section admin-window-panel linked-round-panel" id="admin-janela"><div class="panel-inner">
        <div class="kicker">2. Rodada vinculada · aguardando configuração</div>
        <div class="admin-window-title"><div><h2>Rodada ${state.rodada} · ${escapeHtml(bloco.nome)}</h2><p>Esta rodada pertence ao bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}, mas a janela ainda não foi materializada no Supabase.</p></div><span class="badge warn">Aguardando programação</span></div>
        <div class="linked-window-summary"><div><span>Abre em</span><strong>${escapeHtml(fmtDataLonga(bloco.abre_em))}</strong></div><div><span>Fecha em</span><strong>${escapeHtml(fmtDataLonga(bloco.fecha_em))}</strong></div><div><span>Primeiro jogo-base</span><strong>${escapeHtml(fmtDataLonga(bloco.primeiro_jogo_em))}</strong></div></div>
        <div class="status warn" style="margin-top:12px">Configure e salve o ${escapeHtml(bloco.nome)} no painel acima. Só depois disso a publicação e a apuração individual desta rodada serão habilitadas.</div>
      </div></article>`;
    }
    const statusAtual = String(cfg.status || "programada").toLowerCase();
    const blocoFechado = ["fechada", "bloqueada"].includes(String(bloco.status || "").toLowerCase()) || (parseData(bloco.fecha_em) && new Date() >= parseData(bloco.fecha_em));
    const apuracao = apuracaoRodada(state.rodada);
    const apurados = Number(apuracao?.jogos_apurados ?? cfg.jogos_apurados ?? 0);
    const concluida = Boolean(apuracao?.concluida ?? cfg.apuracao_concluida ?? statusAtual === "apurada");
    let acao;
    if (concluida) {
      acao = `<div class="admin-next-action done"><strong>✅ Apuração concluída automaticamente</strong><span>Os 10 resultados finais foram confirmados pelo pipeline. Nenhuma ação manual é necessária.</span></div>`;
    } else if (rodadaPublica(state.rodada)) {
      acao = `<div class="admin-next-action"><strong>🧮 Apuração automática ativa</strong><span>${apurados}/10 jogos confirmados. O ranking é atualizado a cada resultado; a rodada só será concluída em 10/10.</span></div>`;
    } else if (blocoFechado) {
      acao = `<div class="admin-next-action"><strong>📣 Publicação automática em processamento</strong><span>O fechamento já ocorreu. O próximo ciclo do workflow publicará os palpites e iniciará a apuração sem liberar resultados inexistentes.</span><button class="btn secondary" type="button" id="publicar-rodada-vinculada">Publicar agora em emergência</button></div>`;
    } else {
      acao = `<div class="admin-next-action"><strong>Janela controlada pelo ${escapeHtml(bloco.nome)}</strong><span>A publicação ocorrerá automaticamente no fechamento. Depois disso, o pipeline acompanhará os 10 resultados desta rodada.</span></div>`;
    }

    return `<article class="panel admin-section admin-window-panel linked-round-panel" id="admin-janela"><div class="panel-inner">
      <div class="kicker">2. Rodada vinculada · publicação individual</div><div class="admin-window-title"><div><h2>Rodada ${state.rodada} · ${escapeHtml(bloco.nome)}</h2><p>A janela é herdada do bloco ${bloco.rodada_inicio}–${bloco.rodada_fim}; a publicação e a apuração continuam por rodada.</p></div><span class="badge ${statusJanela(state.rodada).classe}">${escapeHtml(statusJanela(state.rodada).texto)}</span></div>
      ${adminEtapasHtml(cfg)}
      <div class="linked-window-summary"><div><span>Abre em</span><strong>${escapeHtml(fmtDataLonga(bloco.abre_em))}</strong></div><div><span>Fecha em</span><strong>${escapeHtml(fmtDataLonga(bloco.fecha_em))}</strong></div><div><span>Primeiro jogo-base</span><strong>${escapeHtml(fmtDataLonga(bloco.primeiro_jogo_em))}</strong></div></div>
      <form id="admin-rodada-vinculada" class="admin-form admin-window-form">
        <div class="two"><label>Publica em<input id="cfg-publica-vinculada" type="datetime-local" value="${toDatetimeLocal(cfg.publica_em)}"></label><label>Observação da rodada<input id="cfg-obs-vinculada" value="${escapeAttr(cfg.observacao || "")}" placeholder="Informação opcional desta rodada"></label></div>
        <div class="actions admin-save-row"><button class="btn secondary" type="submit">💾 Salvar metadados da rodada</button><span class="muted-note">A janela permanece idêntica à do bloco.</span></div>
        ${acao}
        <details class="admin-advanced"><summary>Opções avançadas da rodada</summary><div class="admin-advanced-body"><p class="muted-note">Essas opções não alteram a janela do bloco.</p><label>Status manual<select id="cfg-status-vinculada"><option value="publicada">publicada</option><option value="apurada">apurada</option><option value="bloqueada">bloqueada</option></select></label><button class="btn secondary" type="button" id="aplicar-status-vinculada">Aplicar status manual</button></div></details>
        <div class="admin-inline-feedback">Bloco versão ${Number(bloco.versao || 1)} · janela protegida contra alteração isolada.</div>
      </form>
    </div></article>`;
  }

  function renderPainelRodadaLegadoHtml(cfg, globalAdmin) {
    if (!globalAdmin) return `<article class="panel admin-section admin-window-panel" id="admin-janela"><div class="panel-inner"><div class="kicker">1. Janela e publicação</div><h2>Rodada ${state.rodada}</h2><p class="muted-note">A janela é global e somente o administrador global pode alterá-la.</p><p><span class="badge ${statusJanela(state.rodada).classe}">${escapeHtml(statusJanela(state.rodada).detalhe)}</span></p></div></article>`;
    return `<article class="panel admin-section admin-window-panel" id="admin-janela"><div class="panel-inner">
      <div class="kicker">2. Janela e publicação</div><div class="admin-window-title"><div><h2>Rodada ${state.rodada}</h2><p>Configure os horários e siga apenas a próxima ação indicada pelo sistema.</p></div><span class="badge ${statusJanela(state.rodada).classe}">${escapeHtml(statusJanela(state.rodada).texto)}</span></div>
      ${adminEtapasHtml(cfg)}
      <form id="admin-rodada" class="admin-form admin-window-form">
        <div class="two"><label>Abre em <input id="cfg-abre" type="datetime-local" value="${toDatetimeLocal(cfg.abre_em)}"></label><label>Fecha em <input id="cfg-fecha" type="datetime-local" value="${toDatetimeLocal(cfg.fecha_em)}"></label></div>
        <div class="two"><label>Publica em <input id="cfg-publica" type="datetime-local" value="${toDatetimeLocal(cfg.publica_em)}"></label><label>Observação <input id="cfg-obs" value="${escapeAttr(cfg.observacao || "")}" placeholder="Informação opcional para a administração"></label></div>
        <div class="actions admin-save-row"><button class="btn" type="submit">💾 Salvar programação</button><span class="muted-note">Salva datas e observação sem executar uma mudança de etapa inesperada.</span></div>
        ${adminAcaoContextualHtml(cfg)}
        <details class="admin-advanced"><summary>Opções avançadas de emergência</summary><div class="admin-advanced-body"><p class="muted-note">Use apenas para corrigir um estado excepcional. O fluxo normal deve seguir a ação recomendada acima.</p><label>Status manual <select id="cfg-status"><option value="programada">programada</option><option value="aberta">aberta</option><option value="fechada">fechada</option><option value="publicada">publicada</option><option value="apurada">apurada</option><option value="bloqueada">bloqueada</option></select></label><button class="btn secondary" type="button" id="aplicar-status-manual">Aplicar status manual</button></div></details>
        <div id="admin-inline-feedback" class="admin-inline-feedback" aria-live="polite">Última configuração carregada: ${escapeHtml(statusJanela(state.rodada).detalhe)}.</div>
      </form>
    </div></article>`;
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
    const contextoAdmin = contextoAdminAtual();
    const blocoRodada = globalAdmin && Number(state.rodada) >= 21 ? blocoDaRodada(state.rodada) : null;
    const painelBlocos = globalAdmin ? renderPainelBlocosAdminHtml() : "";
    const painelAdministracaoAnual = globalAdmin ? `<article class="panel admin-section" id="admin-anual"><div class="panel-inner">
        <div class="kicker">Administração integrada</div><h2>Ranking anual e aniversários</h2>
        <p>As ferramentas históricas continuam em uma área separada e protegida.</p>
        <div class="actions"><a class="btn secondary" href="./?brasileirao=1&view=participantes&admin=1">⚙️ Abrir administração anual</a></div>
      </div></article>` : "";
    const painelParticipantes = globalAdmin ? `<article class="panel admin-section" id="admin-participantes"><div class="panel-inner">
        <div class="kicker">${globalAdmin ? "4. " : "3. "}Participantes</div><h2>Criar ou alterar acesso</h2>
        <form id="admin-participante" class="admin-form">
          <input type="hidden" id="admin-participante-id">
          <input type="hidden" id="admin-nome-atual">
          <label>Usuário/login <input id="admin-login" required placeholder="ex.: laercio" autocomplete="off"></label>
          <div class="actions"><button class="btn" type="submit">Salvar participante</button><button class="btn ghost" type="button" id="limpar-admin">Limpar formulário</button></div>
          <div class="switch-row"><label><input type="checkbox" id="admin-e-admin"> administrador global</label><label><input type="checkbox" id="admin-ativo" checked> ativo</label></div>
          <p class="muted-note">Ao salvar, o sistema gera um PIN novo e oferece o envio por WhatsApp. Para preservar o histórico, inative o acesso ou remova o participante da liga.</p>
        </form>
      </div></article>` : `<article class="panel admin-section" id="admin-participantes"><div class="panel-inner empty"><strong>Perfil: admin de liga</strong><p>Você acompanha os participantes das suas ligas. A criação de usuários e a janela global ficam com o administrador global.</p></div></article>`;
    const painelRodada = blocoRodada
      ? renderPainelRodadaVinculadaHtml(cfg, blocoRodada)
      : renderPainelRodadaLegadoHtml(cfg, globalAdmin);
    const painelProgresso = `<article class="panel admin-section" id="admin-preenchimento"><div class="panel-inner">
        <div class="kicker">${globalAdmin ? "3" : "2"}. Preenchimento</div><h2>Progresso do ${escapeHtml(contextoAdmin.label)} sem revelar placares</h2>
        <p>O percentual considera a liga selecionada e ${contextoAdmin.tipo === "bloco" ? "os 30 jogos das três rodadas do bloco" : `os ${contextoAdmin.totalJogos} jogos da rodada`}. Antes da publicação, o administrador acompanha apenas a quantidade preenchida.</p>
        <div class="export-row"><button class="btn secondary" type="button" id="export-progresso">⬇️ Exportar progresso CSV</button></div>
        <div class="table-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>Participante</th><th>Login</th><th>Status</th><th>Ligas</th><th>Preenchido</th><th>%</th><th>Ações</th></tr></thead><tbody>
          ${state.progresso.map(p => `<tr><td>${escapeHtml(p.nome)}</td><td>${escapeHtml(p.login)}</td><td>${p.ativo ? "ativo" : "inativo"}${p.admin ? " · admin" : ""}</td><td>${ligasDoParticipante(p.participante_id).map(escapeHtml).join(", ") || "—"}</td><td>${p.total_palpites}/${p.total_jogos}</td><td><div class="progress-wrap"><div class="progress-bar" style="width:${Math.max(0, Math.min(100, Number(p.percentual || 0)))}%"></div></div></td><td class="action-cell">${globalAdmin ? `<button class="btn secondary" type="button" data-edit="${escapeAttr(p.participante_id)}">editar</button>${p.ativo ? `<button class="btn danger" type="button" data-inativar="${escapeAttr(p.participante_id)}">inativar</button>` : `<button class="btn secondary" type="button" data-reativar="${escapeAttr(p.participante_id)}">reativar</button>`}` : `<span class="muted-note">gerencie pela liga</span>`}</td></tr>`).join("")}
        </tbody></table></div>
      </div></article>`;
    const painelAuditoria = `<article class="panel admin-section" id="admin-auditoria"><div class="panel-inner"><div class="kicker">${globalAdmin ? "5" : "4"}. Auditoria</div><h2>Conferir registros da rodada</h2><p>Visualize hashes, horários e alterações sem expor palpites antes da publicação.</p><div class="actions"><button class="btn secondary" type="button" id="abrir-auditoria-admin">🧾 Abrir auditoria detalhada</button></div></div></article>`;
    const painelLigas = `<div class="admin-section admin-ligas-last" id="admin-ligas"><div class="admin-section-label"><span>${globalAdmin ? "6" : "5"}. Ligas</span><small>Área de uso menos frequente, mantida por último.</small></div>${renderLigasAdminHtml()}</div>`;
    root.innerHTML = `<section class="admin-workspace">
      <nav class="admin-section-nav" aria-label="Seções administrativas">${globalAdmin ? '<a href="#admin-blocos">1. Blocos</a>' : ''}<a href="#admin-janela">${globalAdmin ? '2' : '1'}. Rodada</a><a href="#admin-preenchimento">${globalAdmin ? '3' : '2'}. Preenchimento</a><a href="#admin-participantes">${globalAdmin ? '4' : '3'}. Participantes</a><a href="#admin-auditoria">${globalAdmin ? '5' : '4'}. Auditoria</a><a href="#admin-ligas">${globalAdmin ? '6' : '5'}. Ligas</a></nav>
      <section class="admin-grid">
        ${painelBlocos}
        ${painelRodada}
        ${painelProgresso}
        ${painelParticipantes}
        ${painelAdministracaoAnual}
        ${painelAuditoria}
        ${painelLigas}
      </section>
    </section>`;
    if (globalAdmin) {
      if ($("#cfg-status")) $("#cfg-status").value = cfg.status || "programada";
      $("#admin-bloco-selecionado")?.addEventListener("change", async ev => { state.blocoAdminSelecionado = ev.target.value; await renderAdmin(); });
      $("#admin-bloco-form")?.addEventListener("submit", salvarBlocoAdmin);
      $("#usar-primeiro-jogo-detectado")?.addEventListener("click", usarPrimeiroJogoDetectado);
      $("#aplicar-fechamento-recomendado")?.addEventListener("click", aplicarFechamentoRecomendado);
      $("#admin-rodada-vinculada")?.addEventListener("submit", salvarMetadadosRodadaVinculada);
      $("#publicar-rodada-vinculada")?.addEventListener("click", async () => { if (!confirmarAcao(`Liberar os palpites públicos da rodada ${state.rodada}?`)) return; await salvarStatusRodadaVinculada("publicada"); });
      $("#aplicar-status-vinculada")?.addEventListener("click", async () => { const novo = $("#cfg-status-vinculada").value; if (!confirmarAcao(`Aplicar o status “${novo}” à rodada ${state.rodada}, sem alterar a janela do bloco?`)) return; await salvarStatusRodadaVinculada(novo); });
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

  function escapeAttr(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); }

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

  function usarPrimeiroJogoDetectado() {
    const bloco = blocoAdminAtual();
    const detectado = primeiroJogoDetectadoBloco(bloco);
    if (!detectado) {
      toast("O JSON ainda não possui o primeiro jogo da rodada inicial deste bloco.", "warn");
      return;
    }
    const campo = $("#bloco-primeiro-jogo");
    if (campo) campo.value = toDatetimeLocal(detectado);
    aplicarFechamentoRecomendado();
    toast(`Primeiro jogo detectado: ${fmtDataLonga(detectado)}.`, "ok");
  }

  function aplicarFechamentoRecomendado() {
    const campoPrimeiro = $("#bloco-primeiro-jogo");
    const campoFecha = $("#bloco-fecha");
    if (!campoPrimeiro?.value || !campoFecha) {
      toast("Informe primeiro o horário do primeiro jogo.", "warn");
      return;
    }
    const recomendado = fechamentoRecomendado(new Date(campoPrimeiro.value));
    if (!recomendado) {
      toast("Horário do primeiro jogo inválido.", "err");
      return;
    }
    campoFecha.value = toDatetimeLocal(recomendado);
    const feedback = $("#bloco-inline-feedback");
    if (feedback) feedback.textContent = `Fechamento recomendado aplicado: ${fmtDataLonga(recomendado)}.`;
  }

  async function salvarBlocoAdmin(ev) {
    ev.preventDefault();
    const bloco = blocoAdminAtual();
    if (!bloco) return;
    try {
      const primeiro = $("#bloco-primeiro-jogo")?.value ? new Date($("#bloco-primeiro-jogo").value) : null;
      const abre = $("#bloco-abre")?.value ? new Date($("#bloco-abre").value) : null;
      const fecha = $("#bloco-fecha")?.value ? new Date($("#bloco-fecha").value) : null;
      let statusNovo = $("#bloco-status")?.value || "futura";
      const observacao = String($("#bloco-observacao")?.value || "").trim();

      // Uma janela completa nunca deve permanecer em "futura": o estado correto é
      // "programada" e a abertura ocorrerá automaticamente pelo relógio.
      if (statusNovo === "futura" && primeiro && abre && fecha) statusNovo = "programada";

      if (statusNovo !== "futura" && (!primeiro || !abre || !fecha)) throw new Error("Informe primeiro jogo, abertura e fechamento antes de programar o bloco.");
      if (abre && fecha && abre >= fecha) throw new Error("A abertura deve ser anterior ao fechamento.");
      if (primeiro && fecha && fecha >= primeiro) throw new Error("O fechamento deve ocorrer antes do primeiro jogo.");

      const recomendado = fechamentoRecomendado(primeiro);
      const fechamentoDiferente = Boolean(fecha && recomendado && !datasIguais(fecha, recomendado));
      const alterouJanela = !datasIguais(bloco.primeiro_jogo_em, primeiro)
        || !datasIguais(bloco.abre_em, abre)
        || !datasIguais(bloco.fecha_em, fecha)
        || String(bloco.status || "") !== String(statusNovo);
      const reabertura = ["fechada", "bloqueada"].includes(String(bloco.status || "")) && ["programada", "aberta"].includes(statusNovo);
      const alteracaoSensivel = (Number(bloco.total_palpites || 0) > 0 && alterouJanela) || reabertura;

      if ((fechamentoDiferente || alteracaoSensivel) && !observacao) {
        throw new Error("Informe uma justificativa na observação para esta alteração protegida.");
      }
      if (fechamentoDiferente && !confirmarAcao(`O fechamento informado não corresponde a 1 hora antes do primeiro jogo (${fmtDataLonga(recomendado)}). Confirmar a exceção?`)) return;
      if (alteracaoSensivel && !confirmarAcao(`Este bloco possui ${Number(bloco.total_palpites || 0)} palpites vinculados ou está sendo reaberto. Confirmar a alteração sensível com registro em auditoria?`)) return;

      status(`Salvando ${bloco.nome}...`, "warn");
      await rpcRows("br_admin_salvar_bloco_apostas_v1", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_bloco_id: bloco.bloco_id,
        p_versao_esperada: Number(bloco.versao),
        p_primeiro_jogo_em: primeiro ? primeiro.toISOString() : null,
        p_abre_em: abre ? abre.toISOString() : null,
        p_fecha_em: fecha ? fecha.toISOString() : null,
        p_status: statusNovo,
        p_observacao: observacao || null,
        p_confirmar_alteracao_sensivel: alteracaoSensivel,
        p_confirmar_fechamento_diferente: fechamentoDiferente
      });
      await carregarConfigsSupabase();
      await carregarBlocosApostasAdmin();
      status(`✅ ${bloco.nome} salvo com a mesma janela nas três rodadas.`, "ok");
      toast(`${bloco.nome} salvo com sucesso.`, "ok");
      await renderAdmin();
    } catch (err) {
      const msg = String(err?.message || err || "Falha ao salvar bloco.");
      if (/outra sessão|Conflito de versão|versão/i.test(msg)) {
        status("O bloco mudou em outra sessão. O painel foi recarregado; confira os dados antes de salvar novamente.", "err");
        toast("Conflito de versão: confira o bloco recarregado.", "err");
        await carregarBlocosApostasAdmin();
        await renderAdmin();
      } else if (/function.*does not exist|Could not find the function|PGRST202|PGRST/i.test(msg)) {
        status("A infraestrutura de blocos ainda não existe no banco. Rode supabase/brasileirao_apostas_exec18_blocos_3_rodadas.sql.", "err");
        toast("Aplique a migração da Execução 2 no Supabase.", "err");
      } else {
        status(msg, "err");
        toast(msg, "err");
      }
    }
  }

  async function salvarStatusRodadaVinculada(statusNovo) {
    const cfg = configDaRodada(state.rodada);
    const bloco = blocoDaRodada(state.rodada);
    if (!cfg || !bloco) {
      toast("A rodada ainda não foi materializada pelo bloco.", "err");
      return;
    }
    try {
      status(`Atualizando a rodada ${state.rodada} sem alterar a janela do bloco...`, "warn");
      await rpcRows("br_admin_definir_rodada", {
        p_admin_id: state.usuario.id,
        p_token: state.token,
        p_temporada: CFG.temporada || 2026,
        p_rodada: state.rodada,
        p_abre_em: cfg.abre_em,
        p_fecha_em: cfg.fecha_em,
        p_publica_em: $("#cfg-publica-vinculada")?.value ? new Date($("#cfg-publica-vinculada").value).toISOString() : (cfg.publica_em || null),
        p_status: statusNovo,
        p_observacao: $("#cfg-obs-vinculada")?.value || cfg.observacao || null
      });
      await carregarConfigsSupabase();
      const mensagem = mensagemStatusRodada(statusNovo);
      status(mensagem, "ok");
      toast(mensagem.replace(/^[^A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9]+/i, ""), "ok");
      await renderAdmin();
    } catch (err) {
      const msg = String(err?.message || err || "Falha ao atualizar a rodada.");
      status(msg, "err");
      toast(msg, "err");
    }
  }

  async function salvarMetadadosRodadaVinculada(ev) {
    ev.preventDefault();
    const cfg = configDaRodada(state.rodada);
    await salvarStatusRodadaVinculada(String(cfg?.status || "programada"));
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
    renderPainelBlocosStatus();
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
    aplicarDestinoCronologicoInicial();
    if (state.usuario) {
      await carregarLigas();
      await carregarMeusPalpites();
    }
    renderLogin();
    renderConteudo();
    renderLigaBox();
  }

  async function trocarRodada(rodada, manual = true) {
    const destino = Number(rodada);
    if (!mesmoContextoRodadas(destino, state.rodada) && !confirmarDescarteRascunho()) return;
    if (!mesmoContextoRodadas(destino, state.rodada)) limparRascunhoBloco();
    state.rodada = destino;
    state.filtroRodadaBloco = "todos";
    state.publicoFiltro = "bloco";
    if (isAdminGlobal() && Number(state.rodada) >= 21) {
      const bloco = blocoDaRodada(state.rodada);
      if (bloco?.bloco_id) state.blocoAdminSelecionado = bloco.bloco_id;
    }
    state.rodadaEscolhidaManualmente = Boolean(manual && !mesmoContextoRodadas(state.rodada, state.rodadaAutomatica));
    await refresh();
  }

  async function voltarRodadaAtual() {
    if (!mesmoContextoRodadas(state.rodadaAutomatica, state.rodada) && !confirmarDescarteRascunho()) return;
    if (!mesmoContextoRodadas(state.rodadaAutomatica, state.rodada)) limparRascunhoBloco();
    state.rodadaEscolhidaManualmente = false;
    state.filtroRodadaBloco = "todos";
    state.publicoFiltro = "bloco";
    resolverRodadaAutomatica(true);
    await refresh();
    toast(`Você voltou para o bloco atual: ${contextoLabel(state.rodadaAutomatica)}.`, "ok");
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
      state.abaInicialExplicita = Boolean(abaInicialPorUrl());
      state.contextoInicialExplicito = Number.isFinite(contextoInicialPorUrl());
      state.abaEscolhidaManualmente = false;
      state.destinoCronologicoResolvido = state.abaInicialExplicita || state.contextoInicialExplicito;
      state.rodadaEscolhidaManualmente = state.contextoInicialExplicito;
      const contextoUrl = contextoInicialPorUrl();
      if (Number.isFinite(contextoUrl)) state.rodada = contextoUrl;
      await refresh();
    } catch (err) {
      console.error(err);
      clearSession();
      status(err.message || "Usuário ou PIN inválido.", "err");
      renderLogin();
    }
  }

  function bindBaseEvents() {
    global.addEventListener("beforeunload", ev => {
      if (!state.draftDirty) return;
      ev.preventDefault();
      ev.returnValue = "";
    });
    $("#form-login")?.addEventListener("submit", onLogin);
    $("#voltar-rodada-atual")?.addEventListener("click", voltarRodadaAtual);
    $$("[data-aba]").forEach(btn => btn.addEventListener("click", async () => {
      state.abaEscolhidaManualmente = true;
      state.destinoCronologicoResolvido = true;
      state.aba = btn.dataset.aba;
      await refresh();
    }));
  }

  async function init() {
    const abaUrl = abaInicialPorUrl();
    const contextoUrl = contextoInicialPorUrl();
    state.abaInicialExplicita = Boolean(abaUrl);
    state.contextoInicialExplicito = Number.isFinite(contextoUrl);
    if (abaUrl) {
      state.aba = abaUrl;
      state.destinoCronologicoResolvido = true;
    }
    if (Number.isFinite(contextoUrl)) {
      state.rodada = contextoUrl;
      state.rodadaEscolhidaManualmente = true;
      state.destinoCronologicoResolvido = true;
    }
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
    if (state.usuario && !abaUrl && !Number.isFinite(contextoUrl)) {
      await carregarLigas();
      state.rodadaEscolhidaManualmente = false;
    }
    if (!state.usuario && state.supabase) {
      status("Entre com usuário e PIN para acessar a área restrita.", "warn");
    }
    await refresh();
    iniciarAutoRefresh();
  }

  if (global.__BR_APOSTAS_TEST__) {
    global.__BR_APOSTAS_TEST_HOOKS = {
      state,
      determinarRodadaAtual,
      resolverRodadaAutomatica,
      blocoRankingCronologicoMaisAtual,
      blocosRanking,
      estadoBlocoResumo,
      blocoAcaoAtual,
      blocoCampeonatoAtual,
      renderRodadas,
      aplicarDestinoCronologicoInicial,
      contextoInicialPorUrl,
      palpitesParticipanteRodada,
      palpitesParticipanteBloco,
      rankingCardsHtml,
      rankingObjetoPorLiga,
      renderRankingBloco
    };
  }

  document.addEventListener("DOMContentLoaded", init);
})(window, document);

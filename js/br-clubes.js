(function(){
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const fmtData = new Intl.DateTimeFormat("pt-BR", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" });
  const cacheBust = () => "?v=" + Date.now();
  const state = { clubes: [], tabela: [], ranking: [], rankingHistory: { snapshots: [] }, probabilidades: {}, resultadosManuais: {}, eventos: [], mascotes: {}, filtroTexto: "", filtroRegiao: "Todas", selecionado: "", jogosExpandidos: false };

  function escapeHtml(value){
    return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[ch]));
  }
  function escapeAttr(value){ return escapeHtml(value); }
  function slug(value){
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }
  async function fetchJson(path, fallback){
    try {
      const res = await fetch(path + cacheBust(), { cache: "no-store" });
      if (!res.ok) throw new Error(path + " HTTP " + res.status);
      return await res.json();
    } catch (err) {
      console.warn("Falha ao carregar", path, err);
      return fallback;
    }
  }
  function escudoHtml(c, cls="club-logo"){
    const fallback = "img/escudo-neutro.svg";
    const src = String(c && c.escudo || "");
    return `<img class="${escapeAttr(cls)}${src ? "" : " is-neutral-shield"}" src="${escapeAttr(src || fallback)}" alt="" loading="lazy" onerror="this.onerror=null; this.src='${fallback}'; this.classList.add('is-neutral-shield')">`;
  }

  // Nomes de clubes com acento resolvem para arquivos de mascote SEM acento,
  // que existem no repositório. Acentos em nomes de arquivo servidos por URL
  // (GitHub Pages) causam falha de encoding (Grêmio -> Gr%C3%AAmio.png não
  // bate). Este mapa garante o caminho ASCII correto.
  const MASCOTE_ARQUIVO = {
    "Grêmio": "img/mascotes/Gremio.png",
    "Vitória": "img/mascotes/Vitoria.png",
    "Atlético-MG": "img/mascotes/Atletico-MG.png",
    "São Paulo": "img/mascotes/Sao Paulo.png",
  };

  function mascoteSrc(clube){
    const nome = clube && clube.nome ? clube.nome : "";
    if (MASCOTE_ARQUIVO[nome]) return MASCOTE_ARQUIVO[nome];
    return `img/mascotes/${nome}.png`;
  }

  function mascotInfo(clube){
    if (!clube) return { nome: "", arquivo: "" };
    const direto = state.mascotes?.[clube.nome];
    if (typeof direto === "string") return { nome: clube.mascote || "Mascote", arquivo: direto };
    if (direto && typeof direto === "object") return { nome: direto.nome || clube.mascote || "Mascote", arquivo: direto.arquivo || "" };
    return { nome: clube.mascote || "Mascote", arquivo: mascoteSrc(clube) };
  }
  function mascotCardHtml(clube){
    const info = mascotInfo(clube);
    const nomeMascote = escapeHtml(info.nome || clube?.mascote || "Mascote");
    const src = escapeAttr(info.arquivo || mascoteSrc(clube));
    return `<div class="info-card mascot-card">
      <span>Mascote</span>
      <button type="button" class="mascot-frame mascot-zoom-trigger" data-mascote-src="${src}" data-mascote-clube="${escapeAttr(clube?.nome || '')}" aria-label="Abrir mascote do ${escapeAttr(clube?.nome || '')} em tamanho maior">
        <img class="mascot-figure" src="${src}" alt="Mascote do ${escapeAttr(clube?.nome || '')}" loading="lazy" onerror="this.closest('.mascot-card').classList.add('is-fallback'); this.remove();">
        <div class="mascot-fallback" aria-hidden="true">🦁</div>
      </button>
      <strong class="mascot-caption">${nomeMascote}</strong>
    </div>`;
  }
  function tabelaDo(nome){ return state.tabela.find(t => t.time === nome) || {}; }
  function rankingDo(nome){ return state.ranking.find(r => r.time === nome) || {}; }
  function numeroRanking(v){ const n = Number(v); return Number.isFinite(n) ? n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "—"; }
  function numeroInteiro(v){ const n = Number(v); return Number.isFinite(n) ? String(Math.round(n)) : "—"; }
  function probabilidadeDo(nome){ return state.probabilidades[slug(nome)] || null; }
  function probValor(p, campo){
    const probs = p && p.probabilidades_pct ? p.probabilidades_pct : {};
    if (campo === "libertadores") return Number(probs.libertadores ?? probs.libertadores_base ?? probs.g6);
    if (campo === "sul_americana") return Number(probs.sul_americana ?? probs.sul_americana_base);
    return Number(probs[campo]);
  }
  function probDetalhe(p, campo){
    const detalhes = p && p.probabilidades_detalhes ? p.probabilidades_detalhes : {};
    if (campo === "libertadores") return detalhes.libertadores || detalhes.libertadores_base || null;
    if (campo === "sul_americana") return detalhes.sul_americana || detalhes.sul_americana_base || null;
    return detalhes[campo] || null;
  }
  function pctCompacto(valor, detalhe=null){
    const explicito = String(detalhe && detalhe.exibicao || "").trim();
    if (explicito) return explicito;
    const n = Number(valor);
    if (!Number.isFinite(n)) return "—";
    if (n >= 0 && n < 0.1) return "<0,1%";
    if (n > 99.9 && n < 100) return ">99,9%";
    return `${n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  }
  function posicaoProjetada(p){
    const n = Number(p && (p.posicao_projetada ?? p.posicao_projetada_mediana ?? p.posicao_projetada_media));
    return Number.isFinite(n) ? Math.max(1, Math.min(20, Math.round(n))) : null;
  }
  function pontosProjetados(p){
    const pontos = p && p.pontos_projetados;
    const n = Number(typeof pontos === "object" && pontos !== null ? (pontos.mediana ?? pontos.media ?? pontos.media_estimada) : pontos);
    return Number.isFinite(n) ? Math.round(n) : null;
  }
  function probabilidadeResumoHtml(p){
    if (!p) return `<span class="club-probability-pill muted">🎲 Projeção AF: aguardando</span>`;
    const pos = posicaoProjetada(p);
    const pts = pontosProjetados(p);
    const campeao = probValor(p, "campeao");
    const lib = probValor(p, "libertadores");
    const sula = probValor(p, "sul_americana");
    const queda = probValor(p, "rebaixamento");
    const chips = [];
    if (Number.isFinite(campeao) && campeao >= 5) chips.push(`Título ${pctCompacto(campeao, probDetalhe(p, "campeao"))}`);
    if (Number.isFinite(lib)) chips.push(`Lib ${pctCompacto(lib, probDetalhe(p, "libertadores"))}`);
    if (Number.isFinite(sula)) chips.push(`Sula ${pctCompacto(sula, probDetalhe(p, "sul_americana"))}`);
    if (Number.isFinite(queda)) chips.push(`Queda ${pctCompacto(queda, probDetalhe(p, "rebaixamento"))}`);
    return `<span class="club-probability-pill"><strong>🎲 Projeção AF: ${pos ? `${pos}º` : "—"}${pts ? ` · ${pts} pts` : ""}</strong><small>${escapeHtml(chips.slice(0, 3).join(" · ") || "probabilidades em atualização")}</small></span>`;
  }
  function probabilidadeCardHtml(p){
    if (!p) return `<section class="club-probability-card muted"><div class="club-probability-title">Projeção AF</div><p>Probabilidades ainda não publicadas para este clube.</p></section>`;
    const pos = posicaoProjetada(p);
    const pts = pontosProjetados(p);
    const faixa = p.faixa_posicao_80 || {};
    const faixaTxt = Number.isFinite(Number(faixa.melhor)) && Number.isFinite(Number(faixa.pior)) ? `${Math.min(Number(faixa.melhor), Number(faixa.pior))}º–${Math.max(Number(faixa.melhor), Number(faixa.pior))}º` : "—";
    const metrics = [
      ["Título", probValor(p, "campeao")],
      ["Libertadores", probValor(p, "libertadores")],
      ["Sul-Americana", probValor(p, "sul_americana")],
      ["Queda", probValor(p, "rebaixamento")]
    ];
    return `<section class="club-probability-card" aria-label="Probabilidades do ${escapeAttr(p.clube || '')}">
      <div class="club-probability-header"><div><span>Projeção AF</span><strong>${pos ? `${pos}º` : "—"}${pts ? ` · ${pts} pts` : ""}</strong></div><small>faixa provável ${escapeHtml(faixaTxt)}</small></div>
      <div class="club-probability-metrics">${metrics.map(([label, value]) => {
        const campo = label === "Título" ? "campeao" : label === "Libertadores" ? "libertadores" : label === "Sul-Americana" ? "sul_americana" : "rebaixamento";
        return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(pctCompacto(value, probDetalhe(p, campo)))}</strong></div>`;
      }).join("")}</div>
      <a class="club-performance-method" href="estatisticas.html#probabilidades">Ver previsão completa →</a>
    </section>`;
  }
  function manualResultMap(dados){
    const raw = dados && dados.jogos && typeof dados.jogos === "object" ? dados.jogos : {};
    const mapa = {};
    Object.values(raw).forEach(item => {
      if (!item || item.ativo === false) return;
      const id = String(item.event_id || "");
      if (id) mapa[id] = item;
      const key = `${slug(item.mandante)}|${slug(item.visitante)}|${String(item.data_iso || '').slice(0,10)}`;
      if (key !== "||") mapa[key] = item;
    });
    return mapa;
  }
  function aplicarResultadoManualEvento(e){
    if (!e) return e;
    const id = String(e.event_id || "");
    const key = `${slug(e.mandante)}|${slug(e.visitante)}|${String(e.data_iso || '').slice(0,10)}`;
    const manual = state.resultadosManuais[id] || state.resultadosManuais[key];
    if (!manual) return e;
    return { ...e, estado: "post", concluido: true, status: manual.status || "Encerrado", placar_mandante: manual.placar_mandante, placar_visitante: manual.placar_visitante, resultado_manual: true };
  }
  function rankingResumoHtml(r){
    if (!r || !r.time) return `<span class="club-ranking-pill muted">⚡ Ranking desempenho: aguardando</span>`;
    return `<span class="club-ranking-pill">⚡ Ranking desempenho: <strong>${escapeHtml(r.pos || "—")}º</strong> · índice <strong>${escapeHtml(numeroRanking(r.indice_final ?? r.score))}</strong></span>`;
  }
  function rankingComponentesHtml(r){
    if (!r || !r.time) return `<section class="club-performance-card muted"><div class="club-performance-title">Ranking de desempenho</div><p>Aguardando dados suficientes.</p></section>`;
    const comps = [["Ataque", r.ataque], ["Defesa", r.defesa], ["Domínio", r.dominio], ["Eficiência", r.eficiencia], ["Disciplina", r.disciplina]];
    const score = numeroRanking(r.indice_final ?? r.score);
    return `<section class="club-performance-card" aria-label="Desempenho do ${escapeAttr(r.time)}">
      <div class="club-performance-header"><div><span>AF-Score</span><strong>Ranking de desempenho</strong></div><div class="club-performance-score"><b>${escapeHtml(score)}</b><small>${escapeHtml(r.pos || "—")}º lugar</small></div></div>
      <div class="club-performance-bars">${comps.map(([label, valor]) => { const n = Math.max(0, Math.min(100, Number(valor) || 0)); return `<div class="club-performance-row"><span>${escapeHtml(label)}</span><div><i style="width:${n.toFixed(1)}%"></i></div><strong>${escapeHtml(numeroRanking(valor))}</strong></div>`; }).join("")}</div>
      <a class="club-performance-method" href="estatisticas.html#metodologia-ranking">Entenda como o ranking é calculado →</a>
    </section>`;
  }
  function historicoRankingDo(nome){
    const snapshots = Array.isArray(state.rankingHistory?.snapshots) ? state.rankingHistory.snapshots : [];
    return snapshots
      .filter(snapshot => snapshot?.destaque_interface || snapshot?.id === "atual")
      .map(snapshot => {
        const item = (Array.isArray(snapshot?.ranking) ? snapshot.ranking : []).find(row => slug(row?.time) === slug(nome));
        return item ? { snapshot, item } : null;
      })
      .filter(Boolean);
  }
  function movimentoRanking(atual, anterior){
    if (anterior === null || anterior === undefined) return `<span class="is-same">• início</span>`;
    const a = Number(atual);
    const b = Number(anterior);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) return `<span class="is-same">• manteve</span>`;
    const delta = Math.abs(b - a);
    return a < b ? `<span class="is-up">▲ ${delta}</span>` : `<span class="is-down">▼ ${delta}</span>`;
  }
  function historicoRankingHtml(nome){
    const rows = historicoRankingDo(nome);
    if (!rows.length) return `<div class="empty-state">O histórico do AF-Score será exibido após a atualização do workflow.</div>`;
    return `<section class="club-ranking-history-card" aria-label="Evolução do Ranking de Desempenho de ${escapeAttr(nome)}">
      <div class="club-ranking-history-head"><div><span>AF-Score</span><strong>Evolução do desempenho</strong></div><small>marcos com amostras iguais</small></div>
      <div class="club-ranking-history-strip">${rows.map(({ snapshot, item }, index) => {
        const anterior = index ? rows[index - 1].item : null;
        const atual = snapshot.id === "atual";
        const jogos = Number(item.jogos);
        const rotulo = atual ? `Atual${Number.isFinite(jogos) ? ` · ${numeroInteiro(jogos)} jogos` : ""}` : snapshot.nome;
        return `<article class="club-ranking-history-item${atual ? " is-current" : ""}">
          <span>${escapeHtml(rotulo || "Marco")}</span>
          <strong>${numeroInteiro(item.pos)}º <i>·</i> ${numeroRanking(item.indice_final)}</strong>
          <small>posição · AF-Score ${movimentoRanking(item.pos, anterior?.pos)}</small>
        </article>`;
      }).join("")}</div>
      <p>Os marcos de 5 jogos comparam todos os clubes com a mesma quantidade de partidas, sem distorção por jogos atrasados.</p>
      <a href="estatisticas.html#desempenho">Ver Ranking de Desempenho completo →</a>
    </section>`;
  }
  function eventosDo(nome){
    return state.eventos.filter(e => e.mandante === nome || e.visitante === nome)
      .map(aplicarResultadoManualEvento)
      .sort((a,b) => String(a.data_iso||"").localeCompare(String(b.data_iso||"")));
  }
  function isPost(e){
    const d = new Date(String(e.data_iso || '').length <= 16 ? `${e.data_iso}:00-03:00` : e.data_iso);
    if (Number.isNaN(d.getTime()) || d.getTime() > Date.now() - (90 * 60 * 1000)) return false;
    const status = String(e.status || '').trim().toLowerCase();
    if (String(e.estado || '').toLowerCase() === 'pre' || status === "0'" || status === '0') return false;
    return String(e.estado || "").toLowerCase() === "post" || (e.placar_mandante !== null && e.placar_mandante !== undefined && e.placar_visitante !== null && e.placar_visitante !== undefined);
  }
  function dataCurta(iso){
    try { return fmtData.format(new Date(iso)); } catch { return "—"; }
  }

  function garantirMascoteModal(){
    let modal = document.getElementById("mascote-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "mascote-modal";
    modal.className = "mascote-modal";
    modal.hidden = true;
    modal.innerHTML = `<div class="mascote-modal-backdrop" data-close="1"></div>
      <div class="mascote-modal-card" role="dialog" aria-modal="true" aria-label="Mascote em tamanho ampliado">
        <button type="button" class="mascote-modal-close" data-close="1" aria-label="Fechar mascote">×</button>
        <img class="mascote-modal-img" alt="">
        <div class="mascote-modal-title"></div>
      </div>`;
    document.body.appendChild(modal);
    const fecharPeloControle = ev => {
      const alvo = ev.target && ev.target.closest ? ev.target.closest("[data-close]") : null;
      if (!alvo || !modal.contains(alvo)) return;
      ev.preventDefault();
      ev.stopPropagation();
      fecharMascoteModal();
    };
    modal.addEventListener("click", fecharPeloControle);
    modal.addEventListener("pointerup", fecharPeloControle);
    modal.addEventListener("touchend", fecharPeloControle, { passive: false });
    document.addEventListener("keydown", ev => { if (ev.key === "Escape") fecharMascoteModal(); });
    return modal;
  }
  function abrirMascoteModal(src, clube){
    const modal = garantirMascoteModal();
    const img = modal.querySelector(".mascote-modal-img");
    const title = modal.querySelector(".mascote-modal-title");
    img.src = src;
    img.alt = `Mascote do ${clube}`;
    title.textContent = clube ? `Mascote — ${clube}` : "Mascote";
    modal.hidden = false;
    document.body.classList.add("modal-open");
  }
  function fecharMascoteModal(){
    const modal = document.getElementById("mascote-modal");
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }
  function ativarZoomMascote(){
    document.querySelectorAll(".mascot-zoom-trigger").forEach(btn => {
      btn.addEventListener("click", () => abrirMascoteModal(btn.dataset.mascoteSrc || "", btn.dataset.mascoteClube || ""));
    });
  }

  function renderChips(){
    const regioes = ["Todas", ...new Set(state.clubes.map(c => c.regiao).filter(Boolean).sort())];
    $("#chips-regiao").innerHTML = regioes.map(r => `<button class="chip ${state.filtroRegiao === r ? "active" : ""}" type="button" data-regiao="${escapeAttr(r)}">${escapeHtml(r)}</button>`).join("");
    $("#chips-regiao").querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
      state.filtroRegiao = btn.dataset.regiao || "Todas";
      render();
    }));
  }
  function clubesFiltrados(){
    const termo = slug(state.filtroTexto);
    return state.clubes.filter(c => {
      if (state.filtroRegiao !== "Todas" && c.regiao !== state.filtroRegiao) return false;
      if (!termo) return true;
      const hay = slug([c.nome, c.nome_completo, c.cidade, c.uf, c.estadio, c.mascote, c.apelido].join(" "));
      return hay.includes(termo);
    });
  }
  function renderGrid(){
    const lista = clubesFiltrados();
    if (!lista.length) {
      $("#grid-clubes").innerHTML = `<div class="empty-state">Nenhum clube encontrado para o filtro atual.</div>`;
      return;
    }
    $("#grid-clubes").innerHTML = lista.map(c => {
      const t = tabelaDo(c.nome);
      const r = rankingDo(c.nome);
      const p = probabilidadeDo(c.nome);
      return `<article class="club-card ${state.selecionado === c.nome ? "active" : ""}" tabindex="0" role="button" data-clube="${escapeAttr(c.nome)}">
        <div class="club-head">
          ${escudoHtml(c)}
          <div><div class="club-name">${escapeHtml(c.nome)}</div><div class="club-sub">${escapeHtml(c.cidade)}-${escapeHtml(c.uf)} · ${escapeHtml(c.apelido)}</div></div>
        </div>
        <p>${escapeHtml(c.curiosidade)}</p>
        <div class="club-kpis">
          <div class="kpi"><strong>${t.pos || "—"}º</strong><span>posição</span></div>
          <div class="kpi"><strong>${t.pontos ?? "—"}</strong><span>pontos</span></div>
          <div class="kpi"><strong>${r.pos || "—"}º</strong><span>desemp.</span></div>
        </div>
        ${probabilidadeResumoHtml(p)}
        ${rankingResumoHtml(r)}
      </article>`;
    }).join("");
    $("#grid-clubes").querySelectorAll(".club-card").forEach(card => {
      const select = () => selecionar(card.dataset.clube);
      card.addEventListener("click", select);
      card.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(); } });
    });
  }
  function clubeDoHash(){
    const hash = decodeURIComponent(location.hash.replace("#", ""));
    if (!hash) return null;
    return state.clubes.find(c => slug(c.nome) === hash) || null;
  }
  function rolarParaDetalhe(behavior="auto"){
    const detalhe = document.getElementById("detalhe-wrapper");
    if (!detalhe || detalhe.hidden) return;
    const executar = () => detalhe.scrollIntoView({ behavior, block: "start", inline: "nearest" });
    executar();
    requestAnimationFrame(() => requestAnimationFrame(executar));
    window.setTimeout(executar, 120);
    window.setTimeout(executar, 420);
  }
  function selecionar(nome, { atualizarHash=true, behavior="smooth" } = {}){
    if (state.selecionado !== nome) state.jogosExpandidos = false;
    state.selecionado = nome;
    const novoHash = `#${slug(nome)}`;
    if (atualizarHash && location.hash !== novoHash) history.pushState(null, "", novoHash);
    renderGrid();
    renderDetalhe();
    rolarParaDetalhe(behavior);
  }
  function renderDetalhe(){
    const c = state.clubes.find(x => x.nome === state.selecionado) || state.clubes[0];
    if (!c) return;
    state.selecionado = c.nome;
    const t = tabelaDo(c.nome);
    const r = rankingDo(c.nome);
    const p = probabilidadeDo(c.nome);
    $("#detalhe-wrapper").hidden = false;
    $("#detalhe-clube").innerHTML = `
      <div class="detail-hero">
        ${escudoHtml(c)}
        <div>
          <div class="kicker">${escapeHtml(c.nome_completo)}</div>
          <h2>${escapeHtml(c.nome)}</h2>
          <p>${escapeHtml(c.momento)}</p>
        </div>
      </div>
      <div class="info-grid">
        <div class="info-card"><span>Cidade / UF</span><strong>${escapeHtml(c.cidade)}-${escapeHtml(c.uf)}</strong></div>
        <div class="info-card"><span>Estádio</span><strong>${escapeHtml(c.estadio)}</strong></div>
        <div class="info-card"><span>Capacidade</span><strong>${escapeHtml(c.capacidade)}</strong></div>
        <div class="info-card"><span>Fundação</span><strong>${escapeHtml(c.fundacao)}</strong></div>
        ${mascotCardHtml(c)}
        <div class="info-card"><span>Títulos BR</span><strong>${escapeHtml(c.titulos_brasileiros)}</strong></div>
        <div class="info-card"><span>Torcida</span><strong>${escapeHtml(c.torcida)}</strong></div>
        <div class="info-card"><span>Tabela atual</span><strong>${t.pos ? `${t.pos}º · ${t.pontos} pts · SG ${t.sg}` : "aguardando"}</strong></div>
      </div>
      ${rankingComponentesHtml(r)}
      ${probabilidadeCardHtml(p)}
      <p><strong>Curiosidade:</strong> ${escapeHtml(c.curiosidade)}</p>
    `;
    ativarZoomMascote();
    renderJogos(c.nome);
    renderHistoricoRanking(c.nome);
  }
  function renderJogos(nome){
    const eventos = eventosDo(nome);
    const agora = new Date();
    const ultimosTodos = eventos.filter(isPost).reverse();
    const proximosTodos = eventos.filter(e => !isPost(e) && new Date(e.data_iso) >= agora);
    const ultimos = state.jogosExpandidos ? ultimosTodos : ultimosTodos.slice(0,3);
    const proximos = state.jogosExpandidos ? proximosTodos : proximosTodos.slice(0,3);
    const bloco = [];
    if (proximos.length) {
      bloco.push(`<div class="kicker">Próximos</div>`);
      proximos.forEach(e => bloco.push(rowJogo(e, false)));
    }
    if (ultimos.length) {
      bloco.push(`<div class="kicker" style="margin-top:${proximos.length ? 12 : 0}px">Últimos</div>`);
      ultimos.forEach(e => bloco.push(rowJogo(e, true)));
    }
    const total = ultimosTodos.length + proximosTodos.length;
    if (total > 6) {
      bloco.push(`<button type="button" class="club-games-toggle" data-toggle-club-games>${state.jogosExpandidos ? "Mostrar somente 3 próximos e 3 últimos ↑" : `Ver todos os jogos do clube (${total}) ↓`}</button>`);
    }
    $("#jogos-clube").innerHTML = bloco.join("") || `<div class="empty-state">Ainda não há jogos mapeados para este clube nos snapshots locais.</div>`;
    $("#jogos-clube").querySelector("[data-toggle-club-games]")?.addEventListener("click", () => {
      state.jogosExpandidos = !state.jogosExpandidos;
      renderJogos(nome);
    });
  }
  function renderHistoricoRanking(nome){
    const target = $("#historico-ranking-clube");
    if (target) target.innerHTML = historicoRankingHtml(nome);
  }
  function rowJogo(e, finalizado){
    const placar = finalizado ? `${e.placar_mandante ?? "—"} × ${e.placar_visitante ?? "—"}` : "vs";
    return `<div class="row"><span class="date">${escapeHtml(dataCurta(e.data_iso))}</span><span>${escapeHtml(e.mandante)} × ${escapeHtml(e.visitante)}<br><small>${escapeHtml(e.estadio || "estádio a confirmar")}</small></span><span class="score">${escapeHtml(placar)}</span></div>`;
  }
  function render(){
    renderChips(); renderGrid(); renderDetalhe();
  }
  async function init(){
    const [clubesData, tabelaData, rankingData, rankingHistoryData, probabilidadesData, eventosData, mascotesData, resultadosManuaisData] = await Promise.all([
      fetchJson("dados-br/clubes.json", { clubes: [] }),
      fetchJson("tabela.json", { tabela: [] }),
      fetchJson("dados-br/ranking-desempenho.json", { ranking: [] }),
      fetchJson("dados-br/historico-ranking-desempenho.json", { snapshots: [] }),
      fetchJson("dados-br/probabilidades-brasileirao.json", { clubes: [] }),
      fetchJson("espn_eventos.json", { eventos: [] }),
      fetchJson("dados-br/mascotes.json", { mascotes: {} }),
      fetchJson("dados-br/resultados-manuais.json", { jogos: {} })
    ]);
    state.clubes = (clubesData.clubes || []).sort((a,b) => a.nome.localeCompare(b.nome, "pt-BR"));
    state.tabela = tabelaData.tabela || [];
    state.ranking = rankingData.ranking || [];
    state.rankingHistory = rankingHistoryData || { snapshots: [] };
    state.probabilidades = Object.fromEntries((probabilidadesData.clubes || []).map(item => [slug(item.clube), item]));
    state.eventos = eventosData.eventos || [];
    state.mascotes = mascotesData.mascotes || {};
    state.resultadosManuais = manualResultMap(resultadosManuaisData);
    const clubeInicialHash = clubeDoHash();
    const inicial = clubeInicialHash?.nome || state.tabela[0]?.time || state.clubes[0]?.nome || "";
    state.selecionado = inicial;
    $("#busca-clube")?.addEventListener("input", ev => { state.filtroTexto = ev.target.value; renderGrid(); });
    window.addEventListener("hashchange", () => {
      const clube = clubeDoHash();
      if (!clube) return;
      selecionar(clube.nome, { atualizarHash:false, behavior:"auto" });
    });
    render();
    if (clubeInicialHash) {
      rolarParaDetalhe("auto");
      window.addEventListener("load", () => rolarParaDetalhe("auto"), { once:true });
    }
  }
  document.addEventListener("DOMContentLoaded", init);
})();

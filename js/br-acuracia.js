(function (window, document) {
  "use strict";

  var DATA_URL = "dados-br/acuracia-af-previsao.json";
  var MIN_BIN = 5; // amostra mínima para um bin entrar na curva principal
  var state = { data: null, club: "", metric: "posicao" };

  function el(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>'"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
    });
  }
  function number(value, digits) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("pt-BR", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits == null ? 1 : digits });
  }
  function pct(value, digits) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "Em acompanhamento";
    return number(n, digits == null ? 1 : digits) + "%";
  }
  function dateLabel(value) {
    if (!value) return "";
    var d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  }
  function shortHash(value) {
    if (!value) return "";
    return String(value).slice(0, 10);
  }
  function createSvg(width, height) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    return svg;
  }
  function svgNode(name, attrs, text) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text != null) node.textContent = text;
    return node;
  }
  function straightPath(points) {
    return points.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2); }).join(" ");
  }
  function smoothLinePath(points) {
    if (!points.length) return "";
    if (points.length === 1) return "M" + points[0][0].toFixed(2) + " " + points[0][1].toFixed(2);
    var d = "M" + points[0][0].toFixed(2) + " " + points[0][1].toFixed(2);
    for (var i = 0; i < points.length - 1; i += 1) {
      var p0 = points[i], p1 = points[i + 1];
      d += " Q" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) + " " + ((p0[0] + p1[0]) / 2).toFixed(2) + " " + ((p0[1] + p1[1]) / 2).toFixed(2);
    }
    var last = points[points.length - 1];
    return d + " T" + last[0].toFixed(2) + " " + last[1].toFixed(2);
  }

  /* Área da faixa de 80% montada diretamente a partir dos dois contornos.
     A versão anterior remontava o path com regex, o que produzia
     preenchimentos torcidos quando o primeiro comando mudava de forma. */
  function bandPath(upper, lower) {
    if (!upper.length || upper.length !== lower.length) return "";
    var top = upper.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2); }).join(" ");
    var bottom = lower.slice().reverse().map(function (p) { return "L" + p[0].toFixed(2) + " " + p[1].toFixed(2); }).join(" ");
    return top + " " + bottom + " Z";
  }

  /* Gradiente ancorado no topo e na base REAIS da faixa (userSpaceOnUse).
     Antes o gradiente ia de 0 a 1 do objeto e desbotava para fora da faixa,
     produzindo a mancha sem borda definida. */
  function addBandGradient(svg, yTop, yBottom) {
    var defs = svgNode("defs");
    var grad = svgNode("linearGradient", {
      id: "afBandGradient", gradientUnits: "userSpaceOnUse",
      x1: "0", y1: String(yTop), x2: "0", y2: String(yBottom)
    });
    grad.appendChild(svgNode("stop", { offset: "0%", "stop-color": "#a3e635", "stop-opacity": ".16" }));
    grad.appendChild(svgNode("stop", { offset: "50%", "stop-color": "#a3e635", "stop-opacity": ".10" }));
    grad.appendChild(svgNode("stop", { offset: "100%", "stop-color": "#a3e635", "stop-opacity": ".16" }));
    defs.appendChild(grad);
    svg.appendChild(defs);
  }
  function chartEmpty(target, message) {
    target.innerHTML = '<div class="empty-state" style="margin:12px">' + esc(message) + '</div>';
  }

  /* ---------- tooltip tátil (funciona em celular, ao contrário de <title>) ---------- */
  function tip(target) {
    var node = target.querySelector(".af-tip");
    if (!node) { node = document.createElement("div"); node.className = "af-tip"; target.appendChild(node); }
    return node;
  }
  function bindTip(target, node, html) {
    function show(event) {
      event.stopPropagation();
      var box = tip(target), rect = target.getBoundingClientRect();
      var point = event.touches && event.touches[0] ? event.touches[0] : event;
      box.innerHTML = html;
      box.classList.add("is-on");
      var x = point.clientX - rect.left, y = point.clientY - rect.top;
      box.style.left = Math.min(Math.max(x, 96), rect.width - 96) + "px";
      box.style.top = Math.max(y - 16, 12) + "px";
    }
    node.addEventListener("mouseenter", show);
    node.addEventListener("mousemove", show);
    node.addEventListener("touchstart", show, { passive: true });
    node.addEventListener("mouseleave", function () { tip(target).classList.remove("is-on"); });
  }
  function closeTips() {
    Array.prototype.forEach.call(document.querySelectorAll(".af-tip"), function (n) { n.classList.remove("is-on"); });
  }
  document.addEventListener("click", closeTips);
  document.addEventListener("touchstart", closeTips, { passive: true });

  /* ---------- cartões de resumo: a resposta antes da ferramenta ---------- */
  function renderSummary() {
    var games = (state.data || {}).jogos || {};
    var integrity = (state.data || {}).integridade || {};
    var technical = games.metricas_tecnicas || {};
    var favourite = games.maior_probabilidade || {};

    var badge = el("accuracy-games-badge");
    if (badge) badge.textContent = games.jogos_avaliados ? number(games.jogos_avaliados, 0) + " jogos avaliados" : "Coleta iniciada";

    var cards = el("accuracy-summary");
    if (!cards) return;
    var sample = Number(favourite.amostra) || 0;
    var thin = sample < 30;

    cards.innerHTML = [
      '<article class="af-card">' +
        '<span>Jogos avaliados</span>' +
        '<strong>' + number(games.jogos_avaliados, 0) + '</strong>' +
        '<small>Previsões registradas antes da bola rolar. Nenhuma é reconstruída depois.</small>' +
      '</article>',
      '<article class="af-card' + (thin ? " af-card-thin" : "") + '">' +
        '<span>Favorito confirmado</span>' +
        '<strong>' + pct(favourite.taxa_confirmacao_pct, 0) + '</strong>' +
        '<small>' + number(favourite.confirmadas, 0) + ' de ' + number(favourite.amostra, 0) + ' jogos.' +
        (thin ? ' Amostra ainda pequena para conclusão.' : '') + '</small>' +
      '</article>',
      '<article class="af-card">' +
        '<span>Brier multiclasse</span>' +
        '<strong>' + number(technical.brier_multiclasse_medio, 3) + '</strong>' +
        '<small>Quanto menor, melhor. Mede acerto e honestidade da probabilidade juntos.</small>' +
      '</article>',
      '<article class="af-card">' +
        '<span>Log Loss</span>' +
        '<strong>' + number(technical.log_loss_medio, 3) + '</strong>' +
        '<small>Penaliza previsão confiante que não se confirma.</small>' +
      '</article>'
    ].join("");

    var seal = el("accuracy-seal");
    if (seal) {
      seal.innerHTML = '<div class="af-seal">' +
        '<div class="af-seal-icon" aria-hidden="true">🔒</div>' +
        '<div><strong>' + number(integrity.historico_pre_jogo_total, 0) + ' previsões travadas por SHA-256</strong>' +
        '<p>Cada previsão é registrada antes do jogo e encadeada ao hash anterior. Alterar uma previsão passada quebraria toda a cadeia — e isso é verificável. ' +
        'Último elo: <code>' + esc(shortHash(integrity.hash_pre_jogo)) + '…</code> · ' +
        number(integrity.snapshots_temporada, 0) + ' snapshots de temporada.</p></div></div>';
    }
  }

  /* ---------- calibração ---------- */
  /* Intervalo de Wilson: com n=2 a barra atravessa o gráfico, e isso é a mensagem. */
  function wilson(successes, n) {
    if (!n) return [0, 100];
    var z = 1.96, p = successes / n;
    var denom = 1 + z * z / n;
    var centre = (p + z * z / (2 * n)) / denom;
    var margin = (z / denom) * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
    return [Math.max(0, (centre - margin) * 100), Math.min(1, centre + margin) * 100];
  }

  function renderCalibration() {
    var target = el("accuracy-calibration");
    var all = ((state.data.jogos || {}).calibracao || []).filter(function (r) { return Number(r.amostra) > 0; });
    if (!all.length) {
      chartEmpty(target, "A calibração aparecerá automaticamente assim que houver partidas com previsão pré-jogo registrada e resultado final.");
      el("accuracy-calibration-note").textContent = "Nenhuma previsão passada é reconstruída: a série começa apenas com probabilidades realmente registradas antes do jogo.";
      renderTechnical();
      return;
    }

    target.innerHTML = "";
    var width = 780, height = 360, left = 58, right = 26, top = 26, bottom = 56;
    var w = width - left - right, h = height - top - bottom;
    var svg = createSvg(width, height);
    function X(v) { return left + w * v / 100; }
    function Y(v) { return top + h - h * v / 100; }

    [0, 20, 40, 60, 80, 100].forEach(function (t) {
      svg.appendChild(svgNode("line", { x1: left, y1: Y(t), x2: width - right, y2: Y(t), class: "grid" }));
      svg.appendChild(svgNode("line", { x1: X(t), y1: top, x2: X(t), y2: height - bottom, class: "grid" }));
      svg.appendChild(svgNode("text", { x: left - 10, y: Y(t) + 4, "text-anchor": "end" }, t + "%"));
      svg.appendChild(svgNode("text", { x: X(t), y: height - bottom + 22, "text-anchor": "middle" }, t + "%"));
    });
    svg.appendChild(svgNode("line", { x1: left, y1: height - bottom, x2: width - right, y2: height - bottom, class: "axis" }));
    svg.appendChild(svgNode("line", { x1: left, y1: top, x2: left, y2: height - bottom, class: "axis" }));
    // diagonal de calibração perfeita: reta, e reta de verdade
    svg.appendChild(svgNode("line", { x1: X(0), y1: Y(0), x2: X(100), y2: Y(100), class: "ideal" }));

    var strong = all.filter(function (r) { return Number(r.amostra) >= MIN_BIN; });
    var weak = all.filter(function (r) { return Number(r.amostra) < MIN_BIN; });

    // barras de erro primeiro, para ficarem atrás dos pontos
    all.forEach(function (row) {
      var n = Number(row.amostra);
      var obs = Number(row.frequencia_observada_pct);
      var ci = wilson(Math.round(obs / 100 * n), n);
      var x = X(Number(row.probabilidade_media_pct));
      svg.appendChild(svgNode("line", {
        x1: x, y1: Y(ci[0]), x2: x, y2: Y(ci[1]),
        class: n >= MIN_BIN ? "err" : "err err-weak"
      }));
    });

    // curva apenas entre bins com amostra suficiente, e com segmentos RETOS.
    // Calibração é um conjunto de bins discretos: não existe valor entre dois bins.
    if (strong.length > 1) {
      svg.appendChild(svgNode("path", {
        d: straightPath(strong.map(function (r) { return [X(Number(r.probabilidade_media_pct)), Y(Number(r.frequencia_observada_pct))]; })),
        class: "line-main"
      }));
    }

    all.forEach(function (row) {
      var n = Number(row.amostra);
      var x = X(Number(row.probabilidade_media_pct));
      var y = Y(Number(row.frequencia_observada_pct));
      var r = 4 + Math.sqrt(n) * 1.7; // raio proporcional à amostra
      var dot = svgNode("circle", { cx: x, cy: y, r: r.toFixed(1), class: n >= MIN_BIN ? "dot-main" : "dot-weak" });
      bindTip(target, dot,
        "<b>Faixa " + row.faixa_pct[0] + "–" + row.faixa_pct[1] + "%</b><br>" +
        "Modelo indicou: " + pct(row.probabilidade_media_pct, 1) + "<br>" +
        "Aconteceu em: " + pct(row.frequencia_observada_pct, 1) + "<br>" +
        "Amostra: <b>" + number(n, 0) + (n === 1 ? " jogo" : " jogos") + "</b>" +
        (n < MIN_BIN ? "<br><i>Amostra insuficiente — não entra na curva.</i>" : ""));
      svg.appendChild(dot);
    });

    svg.appendChild(svgNode("text", { x: left + w / 2, y: height - 8, "text-anchor": "middle", class: "axis-label" }, "Probabilidade indicada pelo modelo"));
    svg.appendChild(svgNode("text", { x: 16, y: top + h / 2, transform: "rotate(-90 16 " + (top + h / 2) + ")", "text-anchor": "middle", class: "axis-label" }, "Frequência observada"));
    target.appendChild(svg);

    el("accuracy-calibration-note").innerHTML =
      '<span class="accuracy-legend">' +
        '<span><i></i>bin com amostra ≥ ' + MIN_BIN + '</span>' +
        '<span><i class="weak"></i>amostra menor que ' + MIN_BIN + '</span>' +
        '<span><i class="bar"></i>intervalo de 95%</span>' +
        '<span><i class="muted"></i>calibração perfeita</span>' +
      '</span>' +
      '<p class="af-read">O tamanho do ponto é a quantidade de jogos naquele bin. A barra vertical é a incerteza: ' +
      'quanto menor a amostra, mais alta a barra. ' + (weak.length ? 'Há ' + weak.length + ' bins com pouquíssimos jogos — eles aparecem apagados justamente porque ainda não dizem nada.' : '') + '</p>';
    renderTechnical();
  }

  function renderTechnical() {
    var t = ((state.data.jogos || {}).metricas_tecnicas || {});
    var scope = (state.data || {}).escopo_publico || {};
    el("accuracy-technical").innerHTML = '<div class="accuracy-technical-grid">' +
      '<div><strong>Brier multiclasse médio</strong><br>' + esc(number(t.brier_multiclasse_medio, 4)) + '<br><small>Quanto menor, melhor. Métrica técnica, não manchete.</small></div>' +
      '<div><strong>Log Loss médio</strong><br>' + esc(number(t.log_loss_medio, 4)) + '<br><small>Penaliza previsões excessivamente confiantes quando o evento não ocorre.</small></div>' +
      '<div><strong>Início do histórico de jogos</strong><br>' + esc(dateLabel(scope.inicio_historico_jogos) || "—") + '<br><small>' + esc(scope.observacao || "") + '</small></div>' +
      '</div>';
  }

  /* ---------- timeline por clube ---------- */
  function clubRows() { return (((state.data || {}).timeline_clubes || {})[state.club] || []); }

  function setClubOptions() {
    var clubs = Object.keys((state.data || {}).timeline_clubes || {}).sort(function (a, b) { return a.localeCompare(b, "pt-BR"); });
    var select = el("accuracy-club-select");
    select.innerHTML = clubs.map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join("");
    state.club = clubs[0] || "";
    select.value = state.club;
    select.addEventListener("change", function () { state.club = select.value; renderTimeline(); });
  }

  function renderCurrent(rows) {
    var current = rows[rows.length - 1];
    if (!current) { el("accuracy-timeline-current").innerHTML = ""; return; }
    var interval = current.faixa_posicao_80 || {}, pointRange = current.faixa_pontos_80 || {};
    el("accuracy-timeline-current").innerHTML = [
      ["Jogos", current.jogos_atuais],
      ["Posição atual", current.posicao_atual ? current.posicao_atual + "º" : "—"],
      ["Projetada", current.posicao_projetada ? current.posicao_projetada + "º" : "—"],
      ["Faixa 80%", interval.melhor && interval.pior ? interval.melhor + "º–" + interval.pior + "º" : "—"],
      ["Pontos projetados", current.pontos_projetados == null ? "—" : current.pontos_projetados],
      ["Faixa pontos 80%", pointRange.min != null && pointRange.max != null ? pointRange.min + "–" + pointRange.max : "—"]
    ].map(function (i) { return '<span>' + esc(i[0]) + ': <b>' + esc(i[1]) + '</b></span>'; }).join("");
  }

  function bounds(values, fallbackMin, fallbackMax, minSpan) {
    var f = values.map(Number).filter(Number.isFinite);
    if (!f.length) return [fallbackMin, fallbackMax];
    var min = Math.min.apply(null, f), max = Math.max.apply(null, f);
    var span = max - min;
    if (minSpan && span < minSpan) { var grow = (minSpan - span) / 2; min -= grow; max += grow; }
    var pad = Math.max(0.6, (max - min) * 0.10);
    return [min - pad, max + pad];
  }

  function timelineBase(rows, yMin, yMax, invertY, yFormatter) {
    var width = 820, height = 360, left = 60, right = 24, top = 26, bottom = 58;
    var w = width - left - right, h = height - top - bottom;
    function x(i) { return rows.length <= 1 ? left + w / 2 : left + w * i / (rows.length - 1); }
    function y(v) {
      var ratio = (Number(v) - yMin) / (yMax - yMin || 1);
      if (invertY) ratio = 1 - ratio;
      return top + h - h * ratio;
    }
    var svg = createSvg(width, height);
    for (var i = 0; i <= 4; i += 1) {
      var value = yMin + (yMax - yMin) * i / 4, yy = y(value);
      svg.appendChild(svgNode("line", { x1: left, y1: yy, x2: width - right, y2: yy, class: "grid" }));
      svg.appendChild(svgNode("text", { x: left - 10, y: yy + 4, "text-anchor": "end" }, yFormatter(value)));
    }
    svg.appendChild(svgNode("line", { x1: left, y1: height - bottom, x2: width - right, y2: height - bottom, class: "axis" }));
    svg.appendChild(svgNode("line", { x1: left, y1: top, x2: left, y2: height - bottom, class: "axis" }));

    // rótulos de rodada, não "22J"
    var idx = [];
    if (rows.length <= 6) { for (var j = 0; j < rows.length; j += 1) idx.push(j); }
    else { idx = [0, Math.round((rows.length - 1) / 3), Math.round(2 * (rows.length - 1) / 3), rows.length - 1]; }
    var used = {}, seenLabel = {};
    idx.forEach(function (i2) {
      if (used[i2]) return; used[i2] = 1;
      var row = rows[i2];
      var label = row.rodada_referencia != null ? "R" + row.rodada_referencia : Number(row.jogos_atuais || 0) + " jogos";
      // Vários snapshots podem pertencer à mesma rodada; repetir "R22" duas vezes
      // no eixo confunde. Na repetição, mostra a data do snapshot.
      if (seenLabel[label]) { label = dateLabel(row.gerado_em) || label; }
      seenLabel[label] = 1;
      svg.appendChild(svgNode("text", { x: x(i2), y: height - bottom + 22, "text-anchor": "middle" }, label));
    });
    return { svg: svg, width: width, height: height, left: left, right: right, top: top, bottom: bottom, w: w, h: h, x: x, y: y };
  }

  function addBand(svg, base, rows, lowAccessor, highAccessor) {
    var upper = [], lower = [];
    rows.forEach(function (row, i) {
      var low = lowAccessor(row), high = highAccessor(row);
      if (low == null || high == null) return;
      var a = Number(low), b = Number(high);
      if (!Number.isFinite(a) || !Number.isFinite(b)) return;
      upper.push([base.x(i), base.y(b)]);
      lower.push([base.x(i), base.y(a)]);
    });
    if (upper.length < 2) return;
    var ys = upper.concat(lower).map(function (p) { return p[1]; });
    addBandGradient(svg, Math.min.apply(null, ys), Math.max.apply(null, ys));
    svg.appendChild(svgNode("path", { d: bandPath(upper, lower), class: "area-80" }));
    svg.appendChild(svgNode("path", { d: straightPath(upper), class: "area-edge" }));
    svg.appendChild(svgNode("path", { d: straightPath(lower), class: "area-edge" }));
  }

  function addSeries(target, svg, base, rows, accessor, className, dotClass, label, digits, suffix) {
    var points = [];
    rows.forEach(function (row, i) {
      var raw = accessor(row);
      if (raw == null || raw === "") return;
      var v = Number(raw);
      if (Number.isFinite(v)) points.push([base.x(i), base.y(v), row, v]);
    });
    if (points.length > 1) svg.appendChild(svgNode("path", { d: smoothLinePath(points.map(function (p) { return [p[0], p[1]]; })), class: className }));
    points.forEach(function (p) {
      var c = svgNode("circle", { cx: p[0], cy: p[1], r: 4.2, class: dotClass });
      bindTip(target, c,
        "<b>" + esc(label) + ": " + number(p[3], digits == null ? 1 : digits) + (suffix || "") + "</b><br>" +
        "Após " + number(p[2].jogos_atuais, 0) + " jogos · " + dateLabel(p[2].gerado_em) + "<br>" +
        (p[2].hash_previsao_clube ? '<span class="af-tip-hash">🔒 ' + esc(shortHash(p[2].hash_previsao_clube)) + "…</span>" : ""));
      svg.appendChild(c);
    });
  }

  function renderPosition(rows, target) {
    // domínio dinâmico: a escala fixa 1..20 espremia toda a série num canto
    var values = [];
    rows.forEach(function (r) {
      var range = r.faixa_posicao_80 || {};
      values.push(r.posicao_atual, r.posicao_projetada, range.melhor, range.pior);
    });
    var b = bounds(values, 1, 20, 6);
    var yMin = Math.max(1, Math.floor(b[0])), yMax = Math.min(20, Math.ceil(b[1]));
    var base = timelineBase(rows, yMin, yMax, true, function (v) { return Math.round(v) + "º"; }), svg = base.svg;
    addBand(svg, base, rows, function (r) { return (r.faixa_posicao_80 || {}).pior; }, function (r) { return (r.faixa_posicao_80 || {}).melhor; });
    addSeries(target, svg, base, rows, function (r) { return r.posicao_projetada; }, "line-main", "dot-main", "Posição projetada", 0, "º");
    addSeries(target, svg, base, rows, function (r) { return r.posicao_atual; }, "line-secondary", "dot-secondary", "Posição real no momento", 0, "º");
    target.appendChild(svg);
    el("accuracy-timeline-legend").innerHTML = '<span><i class="area"></i>faixa central de 80%</span><span><i></i>posição projetada</span><span><i class="secondary"></i>posição real no momento</span>';
  }

  function renderPoints(rows, target) {
    var values = [];
    rows.forEach(function (r) { var range = r.faixa_pontos_80 || {}; values.push(r.pontos_atuais, r.pontos_projetados, range.min, range.max); });
    var b = bounds(values, 0, 114, 12);
    var base = timelineBase(rows, Math.max(0, b[0]), Math.min(114, b[1]), false, function (v) { return String(Math.round(v)); }), svg = base.svg;
    addBand(svg, base, rows, function (r) { return (r.faixa_pontos_80 || {}).min; }, function (r) { return (r.faixa_pontos_80 || {}).max; });
    addSeries(target, svg, base, rows, function (r) { return r.pontos_projetados; }, "line-main", "dot-main", "Pontos finais projetados", 0, "");
    addSeries(target, svg, base, rows, function (r) { return r.pontos_atuais; }, "line-secondary", "dot-secondary", "Pontos acumulados", 0, "");
    target.appendChild(svg);
    el("accuracy-timeline-legend").innerHTML = '<span><i class="area"></i>faixa central de 80%</span><span><i></i>pontos finais projetados</span><span><i class="secondary"></i>pontos acumulados</span>';
  }

  function renderProbabilities(rows, target) {
    var values = [];
    rows.forEach(function (r) { var p = r.probabilidades_pct || {}; values.push(p.campeao, p.libertadores, p.sul_americana); });
    var b = bounds(values, 0, 100, 25);
    var base = timelineBase(rows, Math.max(0, b[0]), Math.min(100, b[1]), false, function (v) { return Math.round(v) + "%"; }), svg = base.svg;
    addSeries(target, svg, base, rows, function (r) { return (r.probabilidades_pct || {}).campeao; }, "line-gold", "dot-gold", "Campeão", 1, "%");
    addSeries(target, svg, base, rows, function (r) { return (r.probabilidades_pct || {}).libertadores; }, "line-main", "dot-main", "Libertadores", 1, "%");
    addSeries(target, svg, base, rows, function (r) { return (r.probabilidades_pct || {}).sul_americana; }, "line-secondary", "dot-secondary", "Sul-Americana", 1, "%");
    target.appendChild(svg);
    el("accuracy-timeline-legend").innerHTML = '<span><i class="gold"></i>campeão</span><span><i></i>Libertadores</span><span><i class="secondary"></i>Sul-Americana</span>';
  }

  function renderTimeline() {
    var target = el("accuracy-timeline"), rows = clubRows();
    target.innerHTML = "";
    renderCurrent(rows);
    if (!rows.length) { chartEmpty(target, "Ainda não há histórico auditável para este clube."); el("accuracy-timeline-legend").innerHTML = ""; return; }
    if (state.metric === "pontos") renderPoints(rows, target);
    else if (state.metric === "probabilidades") renderProbabilities(rows, target);
    else renderPosition(rows, target);
  }

  function wireTabs() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-accuracy-metric]"), function (button) {
      button.addEventListener("click", function () {
        state.metric = button.getAttribute("data-accuracy-metric") || "posicao";
        Array.prototype.forEach.call(document.querySelectorAll("[data-accuracy-metric]"), function (other) {
          var active = other === button;
          other.classList.toggle("active", active);
          other.setAttribute("aria-selected", active ? "true" : "false");
        });
        renderTimeline();
      });
    });
  }

  function milestoneHtml(rows) {
    if (!rows || !rows.length) return "";
    return '<div class="accuracy-milestones">' + rows.slice(-6).map(function (row) {
      return '<div class="accuracy-milestone"><span>Após ' + number(row.apos_jogos, 0) + ' jogos</span>' +
        '<div class="accuracy-milestone-track"><i style="width:' + Math.max(0, Math.min(100, Number(row.cobertura_pct) || 0)) + '%"></i></div>' +
        '<b>' + pct(row.cobertura_pct, 1) + '</b></div>';
    }).join("") + '</div>';
  }

  function renderRange() {
    var range = (((state.data.classificacao || {}).faixa_80) || {}), target = el("accuracy-range-cards"), history = el("accuracy-range-history");
    if (range.status !== "concluido") {
      target.innerHTML = '<div class="accuracy-waiting" style="grid-column:1/-1"><strong>Em acompanhamento.</strong><br>A posição e a pontuação finais ainda não existem; o painel preserva as faixas publicadas agora e fará a aferição automaticamente no encerramento do Brasileirão.</div>';
      history.innerHTML = ""; return;
    }
    var position = (range.posicao || {}).destaque || {}, points = (range.pontos || {}).destaque || {};
    target.innerHTML = '<article class="accuracy-range-card"><span>Posição final dentro da faixa</span><strong>' + pct(position.cobertura_pct, 1) + '</strong><small>Referência: após ' + number(position.apos_jogos, 0) + ' jogos · amostra ' + number(position.amostra, 0) + ' clubes</small></article>' +
      '<article class="accuracy-range-card"><span>Pontuação final dentro da faixa</span><strong>' + pct(points.cobertura_pct, 1) + '</strong><small>Referência: após ' + number(points.apos_jogos, 0) + ' jogos · amostra ' + number(points.amostra, 0) + ' clubes</small></article>';
    history.innerHTML = '<div class="accuracy-note"><strong>Evolução da cobertura por estágio</strong></div>' + milestoneHtml((range.posicao || {}).marcos || []);
  }

  function eventLabel(key) { return { campeao: "Campeão", libertadores: "Libertadores", sul_americana: "Sul-Americana" }[key] || key; }

  function renderSeasonEvents() {
    var section = state.data.eventos_temporada || {}, target = el("accuracy-season-events");
    if (section.status !== "concluido") {
      target.innerHTML = '<div class="accuracy-waiting" style="grid-column:1/-1"><strong>Em acompanhamento.</strong><br>' + esc(section.mensagem || "Os desfechos ainda não estão definidos.") + '</div>';
      return;
    }
    var events = section.eventos || {};
    target.innerHTML = ["campeao", "libertadores", "sul_americana"].map(function (key) {
      var high = (events[key] || {}).alta_confianca_80 || {};
      return '<article class="accuracy-event-card"><span>' + esc(eventLabel(key)) + ' · confiança ≥80%</span><strong>' + pct(high.taxa_confirmacao_pct, 1) + '</strong><small>' +
        (high.amostra ? number(high.confirmadas, 0) + ' confirmações em ' + number(high.amostra, 0) + ' previsões de alta confiança' : 'Sem amostra ≥80%') + '</small></article>';
    }).join("");
  }

  function renderAll() {
    renderSummary(); renderCalibration(); setClubOptions(); wireTabs();
    renderTimeline(); renderRange(); renderSeasonEvents();
  }

  async function init() {
    try {
      var response = await fetch(DATA_URL + "?_=" + Date.now(), { cache: "no-store", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var data = await response.json();
      if (!data || data.status !== "ok") throw new Error("JSON de acurácia inválido");
      state.data = data;
      renderAll();
    } catch (error) {
      el("accuracy-app").insertAdjacentHTML("afterbegin", '<div class="accuracy-error"><strong>Não foi possível carregar a acurácia agora.</strong><br>' + esc(error && error.message ? error.message : "Falha desconhecida") + '</div>');
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})(window, document);

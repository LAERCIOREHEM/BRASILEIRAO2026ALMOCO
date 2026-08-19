/* onde-assistir.js — lista de jogos da Copa com data, hora (Brasília), canais,
   placar, gols e preparo para jogo completo.
   Fonte principal: feed ESPN. Lances são carregados sob demanda via summary para
   não pesar a página. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var API = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard";
  var SUMMARY_API = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary";
  var TV_CAT = {
    globo: ["Globo", "#0a7cff"], sbt: ["SBT", "#00a651"], sportv: ["SporTV", "#ff7a00"],
    getv: ["ge tv", "#06aa48"], gplay: ["Globoplay", "#fb0234"], caze: ["CazéTV", "#f7d116"]
  };
  var SEL = {}, ISO = {}, SELECOES = [], TVS = {}, JC = {}, JOGOS = [], LANCES_CACHE = {};
  var ESTRUT = null, TERMAP = null, FAIRPLAY = {}, PROJ_EVENT = {};
  var FILTROS = { selecao: "", data: "", campo: "data", direcao: "desc" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch];
    });
  }
  function fmtData(d) {
    return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", weekday: "short", day: "2-digit", month: "2-digit" }).format(d);
  }
  function fmtHora(d) {
    return new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" }).format(d);
  }
  function diaChave(d) {
    var p = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric" }).formatToParts(d);
    var o = {}; p.forEach(function (x) { if (x.type !== "literal") o[x.type] = x.value; });
    return o.year + "-" + o.month + "-" + o.day;
  }
  function optionHTML(value, text) {
    return '<option value="' + esc(value) + '">' + esc(text) + '</option>';
  }
  function nomeSelecao(id) {
    return SEL[id] || id || "";
  }
  function nomePrincipalOrdenacao(j) {
    var a = nomeSelecao(j.a);
    var b = nomeSelecao(j.b);
    return (a || "").localeCompare(b || "", "pt-BR") <= 0 ? a : b;
  }
  function temSelecao(j, id) {
    return !id || j.a === id || j.b === id;
  }
  function flag(id) {
    var c = ISO[id];
    return c ? '<img class="oa-flag" src="https://flagcdn.com/w40/' + c + '.png" alt="" onerror="this.style.display=\'none\'">' : "";
  }
  function linkSelecaoHTML(id, conteudo, classeExtra) {
    var sig = siglaTimeTexto(id) || id;
    if (!sig || !SEL[sig]) return conteudo;
    var nome = SEL[sig] || sig;
    var cls = classeExtra ? " " + classeExtra : "";
    return '<a class="team-link' + cls + '" href="selecoes.html#' + encodeURIComponent(sig) + '" title="Ver seleção: ' + esc(nome) + '" aria-label="Ver seleção ' + esc(nome) + '">' + conteudo + '</a>';
  }
  function chave(aId, bId) { return [aId, bId].filter(Boolean).sort().join("-"); }
  function jogoCompleto(aId, bId) {
    var k = chave(aId, bId);
    return JC[k] || null;
  }

  function statsBlocoOA(j) {
    if (!window.COPA_JOGO_STATS || !j || !j.id) return "";
    return window.COPA_JOGO_STATS.bloco({
      eventId: j.id,
      homeId: j.a,
      awayId: j.b,
      homeName: j.an || j.a,
      awayName: j.bn || j.b
    });
  }

  function chips(aId, bId) {
    var k = chave(aId, bId);
    var extras = (TVS.jogos && TVS.jogos[k]) || [];
    var lista = Object.keys(TV_CAT).filter(function (c) { return c === "caze" || extras.indexOf(c) !== -1; });
    return lista.map(function (c) {
      return '<span class="tvchip" style="background:' + TV_CAT[c][1] + ';color:' + (c === "caze" ? "#3a2a00" : "#fff") + '">' + TV_CAT[c][0] + "</span>";
    }).join("");
  }

  function grupoId(id) {
    var t = SELECOES.find(function (s) { return s.id === id; });
    return t ? t.grupo : "";
  }
  function ehJogoGrupo(j) {
    var ga = grupoId(j.a), gb = grupoId(j.b);
    return !!ga && ga === gb;
  }
  function jogoBaseGrupo(aId, bId) {
    if (!window.COPA_ENGINE || !SELECOES.length) return null;
    return COPA_ENGINE.gerarJogosGrupos(SELECOES).find(function (x) {
      return (x.a === aId && x.b === bId) || (x.a === bId && x.b === aId);
    }) || null;
  }
  function placaresGruposOnde(somentePost) {
    var res = [];
    JOGOS.forEach(function (j) {
      if (!ehJogoGrupo(j) || j.scoreA == null || j.scoreB == null) return;
      if (j.state === "pre") return;
      if (somentePost && j.state !== "post") return;
      var jb = jogoBaseGrupo(j.a, j.b);
      if (!jb) return;
      if (jb.a === j.a) res.push({ jogo_id: jb.jogo_id, grupo: jb.grupo, a: jb.a, b: jb.b, ga: j.scoreA, gb: j.scoreB, state: j.state });
      else res.push({ jogo_id: jb.jogo_id, grupo: jb.grupo, a: jb.a, b: jb.b, ga: j.scoreB, gb: j.scoreA, state: j.state });
    });
    return res;
  }
  function classificacaoPorPlacaresOnde(placares) {
    try {
      var plac = {}; (placares || []).forEach(function (p) { plac[p.jogo_id] = p; });
      var jogos = COPA_ENGINE.gerarJogosGrupos(SELECOES);
      var seed = {}; SELECOES.forEach(function (s) { seed[s.id] = s.seed; });
      var porGrupo = {};
      jogos.forEach(function (j) {
        var p = plac[j.jogo_id];
        var jj = Object.assign({}, j, { ga: p ? p.ga : null, gb: p ? p.gb : null });
        (porGrupo[j.grupo] = porGrupo[j.grupo] || []).push(jj);
      });
      var out = {};
      Object.keys(porGrupo).sort().forEach(function (G) {
        var times = [];
        porGrupo[G].forEach(function (j) { if (times.indexOf(j.a) < 0) times.push(j.a); if (times.indexOf(j.b) < 0) times.push(j.b); });
        out[G] = COPA_ENGINE.classificarGrupo(porGrupo[G], times, seed, FAIRPLAY || {}).map(function (t) { return Object.assign({}, t, { grupo: G }); });
      });
      return out;
    } catch (e) { return {}; }
  }
  function rankingTerceirosOnde(classificacao) {
    var seed = {}; SELECOES.forEach(function (s) { seed[s.id] = s.seed; });
    return Object.keys(classificacao || {}).sort().map(function (G) {
      var t = classificacao[G] && classificacao[G][2];
      return t ? Object.assign({}, t, { grupo: G }) : null;
    }).filter(Boolean).sort(function (x, y) {
      return (y.pts || 0) - (x.pts || 0) || (y.sg || 0) - (x.sg || 0) || (y.gf || 0) - (x.gf || 0) ||
        (FAIRPLAY[y.id] || 0) - (FAIRPLAY[x.id] || 0) || (seed[x.id] || 999) - (seed[y.id] || 999);
    });
  }
  function gruposOrdenadosOnde() {
    var out = [];
    SELECOES.forEach(function (s) { if (out.indexOf(s.grupo) < 0) out.push(s.grupo); });
    return out.sort();
  }
  function completosOnde(placPost) {
    var cnt = {}, out = {};
    (placPost || []).forEach(function (p) { cnt[p.grupo] = (cnt[p.grupo] || 0) + 1; });
    gruposOrdenadosOnde().forEach(function (G) { out[G] = (cnt[G] || 0) >= 6; });
    return out;
  }
  function subconjuntosOnde(arr, max) {
    var res = [];
    function rec(i, cur) {
      if (cur.length > max) return;
      if (i >= arr.length) { res.push(cur.slice()); return; }
      rec(i + 1, cur); cur.push(arr[i]); rec(i + 1, cur); cur.pop();
    }
    rec(0, []);
    return res;
  }
  function chavesPossiveisOnde(placPost) {
    if (!TERMAP || !TERMAP.mapa) return [];
    var comp = completosOnde(placPost);
    var classPost = classificacaoPorPlacaresOnde(placPost);
    var ranking = rankingTerceirosOnde(classPost).filter(function (t) { return comp[t.grupo]; });
    var incompletos = gruposOrdenadosOnde().filter(function (G) { return !comp[G]; });
    if (!incompletos.length) {
      var key0 = ranking.slice(0, 8).map(function (t) { return t.grupo; }).sort().join("");
      return key0 && TERMAP.mapa[key0] ? [key0] : [];
    }
    if (incompletos.length > 4) return [];
    var flut = Math.min(8, incompletos.length);
    var garantidos = ranking.slice(0, Math.max(0, 8 - flut)).map(function (t) { return t.grupo; });
    var suplentes = ranking.slice(garantidos.length, garantidos.length + flut).map(function (t) { return t.grupo; });
    var keys = {};
    subconjuntosOnde(incompletos, flut).forEach(function (sub) {
      var faltam = flut - sub.length;
      var grupos = garantidos.concat(sub).concat(suplentes.slice(0, faltam));
      var uniq = [];
      grupos.forEach(function (g) { if (uniq.indexOf(g) < 0) uniq.push(g); });
      uniq.sort();
      if (uniq.length === 8) {
        var k = uniq.join("");
        if (TERMAP.mapa[k]) keys[k] = true;
      }
    });
    return Object.keys(keys);
  }
  function ganhouConfrontoOnde(cand, outro, placMap) {
    var j = COPA_ENGINE.gerarJogosGrupos(SELECOES).find(function (x) { return (x.a === cand && x.b === outro) || (x.a === outro && x.b === cand); });
    if (!j || !placMap[j.jogo_id]) return false;
    var p = placMap[j.jogo_id], gc = (j.a === cand) ? p.ga : p.gb, go = (j.a === cand) ? p.gb : p.ga;
    return gc > go;
  }
  function primeiroTravadoOnde(G, classPost, placPost) {
    var lista = classPost && classPost[G]; if (!lista || !lista.length) return false;
    var cand = lista[0].id, placMap = {}; (placPost || []).forEach(function (p) { placMap[p.jogo_id] = p; });
    var stats = {}; (classPost[G] || []).forEach(function (t) { stats[t.id] = { pts: t.pts || 0, rest: 0 }; });
    COPA_ENGINE.gerarJogosGrupos(SELECOES).filter(function (j) { return j.grupo === G; }).forEach(function (j) {
      if (!placMap[j.jogo_id]) { if (stats[j.a]) stats[j.a].rest++; if (stats[j.b]) stats[j.b].rest++; }
    });
    var pts = stats[cand] ? stats[cand].pts : 0;
    return Object.keys(stats).every(function (id) {
      if (id === cand) return true;
      var max = stats[id].pts + stats[id].rest * 3;
      if (max > pts) return false;
      if (max < pts) return true;
      return ganhouConfrontoOnde(cand, id, placMap);
    });
  }
  function montarR32Onde(d, placPost) {
    var out = [];
    if (!d || !ESTRUT || !TERMAP) return out;
    var classPost = classificacaoPorPlacaresOnde(placPost), comp = completosOnde(placPost), keys = chavesPossiveisOnde(placPost);
    var tokens = {}, cnt = {};
    placPost.forEach(function (p) { cnt[p.grupo] = (cnt[p.grupo] || 0) + 1; });
    Object.keys(classPost).forEach(function (G) {
      if ((cnt[G] || 0) >= 6) { tokens["1" + G] = true; tokens["2" + G] = true; }
      else if (primeiroTravadoOnde(G, classPost, placPost)) tokens["1" + G] = true;
    });
    var mapaAtual = d.chave && TERMAP.mapa[d.chave] ? TERMAP.mapa[d.chave] : null;
    (d.r32 || []).forEach(function (j) {
      var e = ESTRUT.r32.find(function (x) { return x.id === j.id; }); if (!e) return;
      var slotA, slotB, travA, travB;
      if (e.tipo === "fixo") { slotA = e.a; slotB = e.b; travA = !!tokens[slotA]; travB = !!tokens[slotB]; }
      else {
        slotA = e.host;
        var grupoAtual = mapaAtual && mapaAtual[e.host];
        slotB = grupoAtual ? ("3" + grupoAtual) : null;
        travA = !!tokens[slotA];
        var terceiroAtual = grupoAtual && classPost[grupoAtual] && classPost[grupoAtual][2] ? classPost[grupoAtual][2].id : null;
        var mesmoGrupo = !!grupoAtual && keys.length > 0 && keys.every(function (k) { return TERMAP.mapa[k] && TERMAP.mapa[k][e.host] === grupoAtual; });
        travB = !!(mesmoGrupo && comp[grupoAtual] && terceiroAtual && terceiroAtual === j.b);
      }
      out.push({ id: j.id, a: j.a, b: j.b, slotA: slotA, slotB: slotB, travA: travA, travB: travB });
    });
    return out;
  }
  function normTokenMataOnde(s) { return String(s || "").toUpperCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Z0-9]/g, ""); }
  function textosEventoOnde(ev) {
    var textos = [];
    try {
      textos.push(ev.id, ev.name, ev.shortName);
      var c = ev.competitions && ev.competitions[0] ? ev.competitions[0] : {};
      textos.push(c.name, c.shortName, c.note, c.notes);
      (c.competitors || []).forEach(function (cc) { var t = cc.team || {}; textos.push(t.abbreviation, t.shortDisplayName, t.displayName, t.name, t.location, t.nickname); });
    } catch (e) {}
    return textos.filter(Boolean).map(normTokenMataOnde);
  }
  function eventoTemTokenOnde(ev, token) {
    var nt = normTokenMataOnde(token); if (!nt) return false;
    var textos = textosEventoOnde(ev);
    if (textos.some(function (t) { return t === nt || t.indexOf(nt) >= 0; })) return true;
    var mw = nt.match(/^([WL])M(\d+)$/); if (mw) { var curto = mw[1] + mw[2]; if (textos.some(function (t) { return t === curto || t.indexOf(curto) >= 0; })) return true; }
    var m = nt.match(/^([123])([A-L])$/);
    if (m) {
      var pos = m[1], grupo = m[2];
      return textos.some(function (t) {
        if (t.indexOf(pos + grupo) >= 0) return true;
        if (pos === "3" && /^3[A-L]+$/.test(t) && t.indexOf(grupo) >= 0) return true;
        if (pos === "3" && t.indexOf("THIRD") >= 0 && t.indexOf("GROUP") >= 0 && t.indexOf(grupo) >= 0) return true;
        return false;
      });
    }
    return false;
  }
  function eventoIdOnde(ev, id) { var mid = normTokenMataOnde(id); return !!mid && textosEventoOnde(ev).some(function (t) { return t.indexOf(mid) >= 0; }); }
  function eventoExatoOnde(aId, bId) {
    return JOGOS.find(function (j) { return (j.a === aId && j.b === bId) || (j.a === bId && j.b === aId); }) || null;
  }
  function eventoDeSlotOnde(j) {
    var aId = siglaTimeTexto(j.a), bId = siglaTimeTexto(j.b);
    var porId = JOGOS.find(function (x) { return x.raw && eventoIdOnde(x.raw, j.id); });
    if (porId) return porId;
    if (aId && bId) { var ex = eventoExatoOnde(aId, bId); if (ex) return ex; }
    var alvosA = [aId, j.slotA, j.a].filter(Boolean), alvosB = [bId, j.slotB, j.b].filter(Boolean);
    return JOGOS.find(function (x) { return x.raw && alvosA.some(function (a) { return eventoTemTokenOnde(x.raw, a); }) && alvosB.some(function (b) { return eventoTemTokenOnde(x.raw, b); }); }) || null;
  }
  function aplicarProjecoesMata() {
    PROJ_EVENT = {};
    if (!window.COPA_ENGINE || !ESTRUT || !TERMAP || !SELECOES.length) return;
    try {
      var d = COPA_ENGINE.derivar(SELECOES, placaresGruposOnde(false), {}, ESTRUT, TERMAP, FAIRPLAY || {});
      var lista = montarR32Onde(d, placaresGruposOnde(true));
      lista.forEach(function (j) {
        var ev = eventoDeSlotOnde(j);
        if (ev && ev.id) PROJ_EVENT[String(ev.id)] = j;
      });
      JOGOS.forEach(function (j) { j.proj = PROJ_EVENT[String(j.id)] || null; });
    } catch (e) { PROJ_EVENT = {}; }
  }
  function projLado(j, lado) {
    if (!j.proj || j.state !== "pre") return null;
    if (lado === "a" && j.proj.a) return { id:j.proj.a, travado:!!j.proj.travA };
    if (lado === "b" && j.proj.b) return { id:j.proj.b, travado:!!j.proj.travB };
    return null;
  }
  function timeHTML(j, lado) {
    var p = projLado(j, lado);
    var id = p ? p.id : (lado === "a" ? j.a : j.b);
    var nome = p ? (SEL[id] || id) : (lado === "a" ? (j.an || j.a) : (j.bn || j.b));
    var mark = p ? '<span class="oa-slot-mark ' + (p.travado ? 'ok' : 'wait') + '" title="' + (p.travado ? 'Vaga confirmada' : 'Projeção como está agora') + '">' + (p.travado ? '✓' : '⌛') + '</span>' : '';
    var img = flag(id);
    var texto = '<span>' + esc(nome) + mark + '</span>';
    var corpo = lado === "a" ? (img + texto) : (texto + img);
    return '<div class="oa-team ' + (lado === "a" ? 'oa-home' : 'oa-away') + '">' + linkSelecaoHTML(id, corpo, "team-link-oa") + '</div>';
  }

  function getPath(obj, path, def) {
    var cur = obj;
    for (var i = 0; i < path.length; i++) {
      var p = path[i];
      if (cur && typeof cur === "object" && p in cur) cur = cur[p];
      else return def;
    }
    return cur == null ? def : cur;
  }
  function scoreNum(v) {
    if (v == null || v === "") return null;
    var n = parseInt(String(v).replace(/[^0-9-]/g, ""), 10);
    return isNaN(n) ? null : n;
  }
  function scoreCompetidor(c) {
    var vals = [c && c.score, c && c.displayScore, c && c.curScore, c && c.currentScore, getPath(c, ["score", "value"], null)];
    for (var i = 0; i < vals.length; i++) {
      var n = scoreNum(vals[i]);
      if (n != null) return n;
    }
    var ls = c && c.linescores;
    if (Array.isArray(ls) && ls.length) {
      var ultimo = ls[ls.length - 1];
      var n2 = scoreNum(ultimo && (ultimo.value != null ? ultimo.value : ultimo.displayValue));
      if (n2 != null) return n2;
    }
    return null;
  }
  function placarPenaltiCompetidor(c) {
    var vals = [
      c && c.shootoutScore,
      c && c.shootoutDisplayScore,
      c && c.penaltyScore,
      getPath(c, ["shootoutScore", "value"], null),
      getPath(c, ["penaltyScore", "value"], null)
    ];
    for (var i = 0; i < vals.length; i++) {
      var n = scoreNum(vals[i]);
      if (n != null) return n;
    }
    return null;
  }
  function linhaPenaltisOnde(j) {
    if (!j || j.state !== "post" || j.penA == null || j.penB == null) return "";
    var vencedor = j.vencedor ? (SEL[j.vencedor] || j.vencedor) : "";
    return '<div class="oa-penalti">pênaltis ' + esc(j.penA) + '-' + esc(j.penB) + (vencedor ? ' · <b>' + esc(vencedor) + '</b> venceu' : '') + '</div>';
  }
  function textoTipo(o) {
    var t = o && o.type;
    if (!t) return "";
    if (typeof t === "string") return t;
    if (typeof t === "object") return [t.id, t.text, t.name, t.displayName, t.abbreviation].filter(Boolean).join(" ");
    return String(t);
  }
  function textoLance(o) {
    return String((o && (o.text || o.description || o.shortText || o.displayText || o.headline)) || "");
  }
  function nomeAtleta(a) {
    if (!a || typeof a !== "object") return "";
    if (a.athlete) return nomeAtleta(a.athlete);
    return String(a.displayName || a.fullName || a.shortName || a.name || "").replace(/\s+/g, " ").trim();
  }
  function jogadorDoLance(o) {
    if (!o || typeof o !== "object") return "";
    var chaves = ["athlete", "player", "scorer"];
    for (var i = 0; i < chaves.length; i++) { var n = nomeAtleta(o[chaves[i]]); if (n) return n; }
    var listas = ["athletes", "participants", "athletesInvolved", "players"];
    for (var j = 0; j < listas.length; j++) {
      var arr = o[listas[j]];
      if (Array.isArray(arr)) for (var k = 0; k < arr.length; k++) { var n2 = nomeAtleta(arr[k]); if (n2) return n2; }
    }
    return String(o.displayName || o.athleteDisplayName || o.name || "").replace(/\s+/g, " ").trim();
  }
  function minutoDoLance(o) {
    var v = getPath(o, ["clock", "displayValue"], "") || getPath(o, ["time", "displayValue"], "") || o.displayClock || o.clock || o.minute || "";
    v = String(v || "").trim();
    if (!v) return "";
    if (/^\d+$/.test(v)) return v + "'";
    return v.replace(/\s+/g, " ");
  }
  function golDoTexto(txt) {
    if (!txt) return "";
    var pats = [
      /Goal!.*?\.\s*([^\.]+?)\s*\((?:[^)]*)\)/i,
      /Gol!.*?\.\s*([^\.]+?)\s*\((?:[^)]*)\)/i,
      /^\s*([^\.]+?)\s+\((?:[^)]*)\)\s*(?:right|left|header|converts|marca|finaliza|chuta)/i
    ];
    for (var i = 0; i < pats.length; i++) {
      var m = txt.match(pats[i]);
      if (m && m[1] && m[1].length <= 60) return m[1].replace(/\s+/g, " ").trim();
    }
    return "";
  }
  function ehGolContra(lance) {
    var raw = (textoTipo(lance) + " " + textoLance(lance)).toLowerCase();
    return /own goal|gol contra|autogol/.test(raw);
  }
  function nomeGolContraDoTexto(txt) {
    txt = String(txt || "");
    var pats = [/own goal by\s+([^,.]+)(?:[,\.]|$)/i, /gol contra de\s+([^,.]+)(?:[,\.]|$)/i, /autogol de\s+([^,.]+)(?:[,\.]|$)/i];
    for (var i = 0; i < pats.length; i++) { var m = txt.match(pats[i]); if (m && m[1]) return m[1].replace(/\s+/g, " ").trim(); }
    return "";
  }
  function dpNorm(s) { return String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim(); }
  function siglaTimeTexto(txt) {
    var n = dpNorm(txt);
    if (!n) return "";
    for (var k in SEL) if (dpNorm(SEL[k]) === n || dpNorm(k) === n) return k;
    return "";
  }
  function timeDoTexto(txt) {
    if (!txt) return "";
    var pats = [/Goal!.*?\.\s*[^\.]+?\s*\(([^)]+)\)/i, /Gol!.*?\.\s*[^\.]+?\s*\(([^)]+)\)/i, /^\s*[^\.]+?\s+\(([^)]+)\)/i];
    for (var i = 0; i < pats.length; i++) {
      var m = txt.match(pats[i]);
      if (m && m[1]) return siglaTimeTexto(m[1]) || m[1].replace(/\s+/g, " ").trim();
    }
    return "";
  }
  function scoreDoLance(o) {
    var pares = [["homeScore", "awayScore"], ["home_score", "away_score"], ["homeTeamScore", "awayTeamScore"], ["home", "away"]];
    for (var i = 0; i < pares.length; i++) {
      var h = pares[i][0], a = pares[i][1];
      if (!o || !(h in o) || !(a in o)) continue;
      var hs = scoreNum(o[h]), as = scoreNum(o[a]);
      if (hs != null && as != null) return { home: hs, away: as };
    }
    var sh = getPath(o, ["score", "home"], null), sa = getPath(o, ["score", "away"], null);
    var hs2 = scoreNum(sh), as2 = scoreNum(sa);
    if (hs2 != null && as2 != null) return { home: hs2, away: as2 };
    return null;
  }
  function arraysLances(summary) {
    var out = [];
    [["scoringPlays"], ["competitions", 0, "scoringPlays"], ["header", "competitions", 0, "scoringPlays"]].forEach(function (p) {
      var arr = getPath(summary, p, []); if (Array.isArray(arr)) out = out.concat(arr);
    });
    return out;
  }
  function arraysComentario(summary) {
    var out = [];
    [["commentary"], ["plays"], ["competitions", 0, "details"]].forEach(function (p) {
      var arr = getPath(summary, p, []);
      if (arr && !Array.isArray(arr) && typeof arr === "object") arr = arr.items || arr.plays || [];
      if (Array.isArray(arr)) out = out.concat(arr);
    });
    return out;
  }
  function siglaObjTime(o) {
    if (!o || typeof o !== "object") return "";
    var cand = [o.team, o.scoringTeam, o.competitor, o.participant, o.club];
    for (var i = 0; i < cand.length; i++) {
      var t = cand[i]; if (!t || typeof t !== "object") continue;
      var sig = siglaTimeTexto(t.abbreviation) || siglaTimeTexto(t.shortDisplayName) || siglaTimeTexto(t.displayName) || siglaTimeTexto(t.name);
      if (sig) return sig;
    }
    return siglaTimeTexto(timeDoTexto(textoLance(o)));
  }
  function extrairLances(summary, j) {
    var gols = [], usados = new Set(), ultimoScore = { home: 0, away: 0 };
    var finalHome = j.scoreA, finalAway = j.scoreB;

    function ladoDoGol(lance) {
      var og = ehGolContra(lance);
      if (!og) {
        var sig = siglaObjTime(lance);
        if (sig && sig === j.a) return "home";
        if (sig && sig === j.b) return "away";
      }
      var sc = scoreDoLance(lance);
      if (sc) {
        if (sc.home > ultimoScore.home && sc.away === ultimoScore.away) return "home";
        if (sc.away > ultimoScore.away && sc.home === ultimoScore.home) return "away";
      }
      return "";
    }
    function ordemMinuto(g) {
      var m = String(g.minuto || "").match(/\d+/);
      return m ? parseInt(m[0], 10) : 999;
    }
    function registrarGol(lance) {
      var og = ehGolContra(lance), txt = textoLance(lance);
      var nome = og ? (nomeGolContraDoTexto(txt) || jogadorDoLance(lance) || golDoTexto(txt)) : (jogadorDoLance(lance) || golDoTexto(txt));
      if (!nome) return;
      var min = minutoDoLance(lance);
      var key = min + "|" + nome.toLowerCase() + "|" + (og ? "OG" : "GOL");
      if (usados.has(key)) return;
      usados.add(key);
      gols.push({ minuto: min, nome: nome, lado: ladoDoGol(lance), og: og });
      var sc = scoreDoLance(lance); if (sc) ultimoScore = sc;
    }

    arraysLances(summary).forEach(function (sp) {
      var raw = (textoTipo(sp) + " " + textoLance(sp)).toLowerCase();
      if (/shootout|penalty shootout|disputa de p[eê]naltis/.test(raw)) return;
      if (!(raw.indexOf("goal") >= 0 || raw.indexOf("gol") >= 0 || parseInt(sp.scoreValue || "0", 10) === 1)) return;
      registrarGol(sp);
    });
    arraysComentario(summary).forEach(function (ev2) {
      var raw = (textoTipo(ev2) + " " + textoLance(ev2)).toLowerCase();
      if (/shootout|penalty shootout|disputa de p[eê]naltis/.test(raw)) return;
      if (!(raw.indexOf("goal") >= 0 || raw.indexOf("gol!") >= 0 || ehGolContra(ev2))) return;
      registrarGol(ev2);
    });

    if (finalHome != null && finalAway != null) {
      var h = gols.filter(function (g) { return g.lado === "home"; }).length;
      var a = gols.filter(function (g) { return g.lado === "away"; }).length;
      gols.filter(function (g) { return !g.lado; }).sort(function (x, y) { return ordemMinuto(x) - ordemMinuto(y); }).forEach(function (g) {
        var faltaH = Math.max(0, finalHome - h), faltaA = Math.max(0, finalAway - a);
        if (faltaH > 0 && faltaA <= 0) { g.lado = "home"; h++; }
        else if (faltaA > 0 && faltaH <= 0) { g.lado = "away"; a++; }
        else if (faltaH >= faltaA && faltaH > 0) { g.lado = "home"; h++; }
        else if (faltaA > 0) { g.lado = "away"; a++; }
      });
    }
    gols = gols.sort(function (x, y) { return ordemMinuto(x) - ordemMinuto(y); });
    return { gols: gols, golsHome: gols.filter(function (g) { return g.lado === "home"; }), golsAway: gols.filter(function (g) { return g.lado === "away"; }) };
  }
  function chipGol(g) {
    var og = g && g.og ? ' <span class="og-tag" title="Gol contra">OG</span>' : "";
    return '<span class="gol-chip">⚽ ' + (g.minuto ? esc(g.minuto) + " " : "") + esc(g.nome) + og + '</span>';
  }
  function htmlLances(dados) {
    if (!dados || !dados.gols || !dados.gols.length) return "";
    return '<div class="oa-gols-grid"><div class="gols-time gols-home">' + (dados.golsHome || []).map(chipGol).join("") + '</div><div class="gols-centro"></div><div class="gols-time gols-away">' + (dados.golsAway || []).map(chipGol).join("") + '</div></div>';
  }
  async function carregarLancesJogo(j) {
    var el = document.getElementById("oa-gols-" + j.id);
    if (!el || j.state === "pre") return;
    try {
      var c = LANCES_CACHE[j.id];
      var ttl = j.state === "in" ? 25000 : 6 * 60 * 60 * 1000;
      var dados;
      if (c && (Date.now() - c.ts) < ttl) dados = c.dados;
      else {
        var url = SUMMARY_API + "?event=" + encodeURIComponent(j.id) + (j.state === "in" ? "&_=" + Date.now() : "");
        var summary = await fetch(url).then(function (r) { return r.json(); });
        dados = extrairLances(summary, j);
        LANCES_CACHE[j.id] = { ts: Date.now(), dados: dados };
      }
      el.innerHTML = htmlLances(dados);
    } catch (e) {}
  }
  function observarLances() {
    var itens = document.querySelectorAll("[data-lances-id]");
    if (!("IntersectionObserver" in window)) {
      Array.prototype.slice.call(itens, 0, 12).forEach(function (el) {
        var j = JOGOS.find(function (x) { return String(x.id) === String(el.dataset.lancesId); });
        if (j) carregarLancesJogo(j);
      });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        io.unobserve(el);
        var j = JOGOS.find(function (x) { return String(x.id) === String(el.dataset.lancesId); });
        if (j) carregarLancesJogo(j);
      });
    }, { rootMargin: "240px 0px" });
    itens.forEach(function (el) { io.observe(el); });
  }

  function datasDisponiveis() {
    var mapa = {};
    JOGOS.forEach(function (j) { mapa[diaChave(j.date)] = fmtData(j.date); });
    return Object.keys(mapa).sort().map(function (k) { return { id:k, label:mapa[k] }; });
  }

  function preencherFiltros() {
    var sel = $("#oa-filtro-selecao");
    var dt = $("#oa-filtro-data");
    if (sel) {
      var optsSel = SELECOES.slice().sort(function (a, b) {
        return String(a.nome || a.id).localeCompare(String(b.nome || b.id), "pt-BR");
      }).map(function (s) { return optionHTML(s.id, (s.nome || s.id) + " (" + s.id + ")"); }).join("");
      sel.innerHTML = '<option value="">Todas as seleções</option>' + optsSel;
    }
    if (dt) {
      dt.innerHTML = '<option value="">Todas as datas</option>' + datasDisponiveis().map(function (d) {
        return optionHTML(d.id, d.label);
      }).join("");
    }
  }

  function lerFiltrosDoFormulario() {
    var sel = $("#oa-filtro-selecao");
    var dt = $("#oa-filtro-data");
    var campo = $("#oa-ordem-campo");
    var dir = $("#oa-ordem-direcao");
    FILTROS.selecao = sel ? sel.value : "";
    FILTROS.data = dt ? dt.value : "";
    FILTROS.campo = campo ? campo.value : "data";
    FILTROS.direcao = dir ? dir.value : "desc";
  }

  function jogosFiltradosOrdenados() {
    lerFiltrosDoFormulario();
    var lista = JOGOS.filter(function (j) {
      if (!temSelecao(j, FILTROS.selecao)) return false;
      if (FILTROS.data && diaChave(j.date) !== FILTROS.data) return false;
      return true;
    });
    lista.sort(function (a, b) {
      var r;
      if (FILTROS.campo === "selecao") {
        r = nomePrincipalOrdenacao(a).localeCompare(nomePrincipalOrdenacao(b), "pt-BR") ||
            nomeSelecao(a.a).localeCompare(nomeSelecao(b.a), "pt-BR") ||
            nomeSelecao(a.b).localeCompare(nomeSelecao(b.b), "pt-BR") ||
            (a.date - b.date);
      } else {
        r = (a.date - b.date) ||
            nomePrincipalOrdenacao(a).localeCompare(nomePrincipalOrdenacao(b), "pt-BR");
      }
      return FILTROS.direcao === "desc" ? -r : r;
    });
    return lista;
  }

  function atualizarResumoFiltros(total) {
    var el = $("#oa-filtro-resumo");
    if (!el) return;
    var partes = [];
    if (FILTROS.selecao) partes.push(nomeSelecao(FILTROS.selecao));
    if (FILTROS.data) partes.push(fmtData(JOGOS.find(function (j) { return diaChave(j.date) === FILTROS.data; }).date));
    var base = total === 1 ? "1 jogo" : total + " jogos";
    el.textContent = partes.length ? base + " encontrados · " + partes.join(" · ") : base + " no total";
  }

  function ligarFiltros() {
    ["oa-filtro-selecao", "oa-filtro-data", "oa-ordem-campo", "oa-ordem-direcao"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.dataset.oaFiltroLigado) {
        el.dataset.oaFiltroLigado = "1";
        el.addEventListener("change", render);
      }
    });
    var limpar = $("#oa-limpar-filtros");
    if (limpar && !limpar.dataset.oaFiltroLigado) {
      limpar.dataset.oaFiltroLigado = "1";
      limpar.addEventListener("click", function () {
        var s = $("#oa-filtro-selecao"), d = $("#oa-filtro-data"), c = $("#oa-ordem-campo"), o = $("#oa-ordem-direcao");
        if (s) s.value = "";
        if (d) d.value = "";
        if (c) c.value = "data";
        if (o) o.value = "desc";
        render();
      });
    }
  }

  function placarHTML(j) {
    if (j.scoreA == null || j.scoreB == null || j.state === "pre") return '<b>×</b>';
    return '<span class="oa-score"><b>' + j.scoreA + '</b><em>×</em><b>' + j.scoreB + '</b></span>';
  }
  function statusHTML(j) {
    if (j.state === "post") return '<span class="oa-fim">encerrado' + (j.penA != null && j.penB != null ? ' (pên.)' : '') + '</span>';
    if (j.state === "in") return '<span class="oa-vivo">🔴 ao vivo</span>';
    return '<span class="oa-hora">' + fmtHora(j.date) + '</span>';
  }
  function botoesPosJogo(j) {
    var jc = j.state === "post" ? jogoCompleto(j.a, j.b) : null;
    var out = "";
    if (jc && jc.url) out += '<a class="oa-completo" href="' + esc(jc.url) + '" target="_blank" rel="noopener">🎥 JOGO COMPLETO — assista como foi</a>';
    return out;
  }

  function render() {
    if (!JOGOS.length) {
      $("#lista").innerHTML = '<p class="vazio">Não consegui carregar os jogos agora. Tente recarregar a página.</p>';
      atualizarResumoFiltros(0);
      return;
    }
    var lista = jogosFiltradosOrdenados();
    atualizarResumoFiltros(lista.length);
    if (!lista.length) {
      $("#lista").innerHTML = '<div class="oa-sem-resultados">Nenhum jogo encontrado com esses filtros.<br>Use “Limpar filtros” para voltar à lista completa.</div>';
      return;
    }

    var html = "", diaAtual = "";
    lista.forEach(function (j) {
      var dk = diaChave(j.date);
      if (FILTROS.campo !== "selecao" && dk !== diaAtual) {
        diaAtual = dk;
        html += '<div class="dia-cab">' + fmtData(j.date) + "</div>";
      }
      var botoes = botoesPosJogo(j);
      html += '<div class="oa-jogo">' +
        (FILTROS.campo === "selecao" ? '<div class="dia-cab" style="margin-top:0">' + fmtData(j.date) + "</div>" : "") +
        '<div class="oa-matchline">' +
          timeHTML(j, "a") +
          placarHTML(j) +
          timeHTML(j, "b") +
        '</div>' +
        linhaPenaltisOnde(j) +
        '<div id="oa-gols-' + esc(j.id) + '" class="oa-gols-wrap" data-lances-id="' + esc(j.id) + '"></div>' +
        '<div class="oa-info">' + statusHTML(j) + (j.venue ? ' · <span class="oa-loc">' + esc(j.venue) + "</span>" : "") + "</div>" +
        (botoes || '<div class="oa-tv">📺 ' + chips(j.a, j.b) + "</div>") +
        statsBlocoOA(j) +
        "</div>";
    });
    $("#lista").innerHTML = html;
    if (window.COPA_JOGO_STATS) window.COPA_JOGO_STATS.bind();
    observarLances();
  }

  function baixarICS() {
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    function dt(d) { return d.getUTCFullYear() + pad(d.getUTCMonth() + 1) + pad(d.getUTCDate()) + "T" + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + "00Z"; }
    var linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bolao Copa 2026//PT-BR", "CALSCALE:GREGORIAN"];
    JOGOS.forEach(function (j) {
      var fim = new Date(j.date.getTime() + 2 * 3600 * 1000);
      linhas.push("BEGIN:VEVENT");
      linhas.push("UID:" + j.id + "@brasileirao2026almoco");
      linhas.push("DTSTAMP:" + dt(new Date()));
      linhas.push("DTSTART:" + dt(j.date));
      linhas.push("DTEND:" + dt(fim));
      linhas.push("SUMMARY:" + (j.an || j.a) + " x " + (j.bn || j.b) + " — Copa 2026");
      if (j.venue) linhas.push("LOCATION:" + j.venue.replace(/,/g, "\\,"));
      linhas.push("DESCRIPTION:Copa do Mundo 2026. Assista na CazéTV e acompanhe em brasileirao2026almoco.com.br/copa2026");
      linhas.push("END:VEVENT");
    });
    linhas.push("END:VCALENDAR");
    var blob = new Blob([linhas.join("\r\n")], { type: "text/calendar;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "copa-2026-jogos.ics";
    document.body.appendChild(a); a.click(); a.remove();
  }

  function compartilhar() {
    var url = "https://brasileirao2026almoco.com.br/copa2026/onde-assistir.html";
    var texto = "Acompanhe a Copa 2026: jogos, horários, onde assistir, placares e jogos completos 🏆⚽";
    if (navigator.share) navigator.share({ title: "Copa 2026 — jogos e onde assistir", text: texto, url: url }).catch(function () {});
    else window.open("https://wa.me/?text=" + encodeURIComponent(texto + " " + url), "_blank");
  }

  function init() {
    Promise.all([
      fetch("dados/selecoes.json").then(function (r) { return r.json(); }),
      fetch("dados/transmissoes.json").then(function (r) { return r.json(); }).catch(function () { return {}; }),
      fetch(API + "?dates=20260611-20260719&limit=200&_=" + Date.now()).then(function (r) { return r.json(); }),
      fetch("dados/jogos-completos.json?t=" + Date.now()).then(function (r) { return r.json(); }).catch(function () { return {}; }),
      fetch("dados/estrutura_mata_mata.json?t=" + Date.now()).then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch("dados/terceiros_map.json?t=" + Date.now()).then(function (r) { return r.json(); }).catch(function () { return null; }),
      fetch("dados/fairplay.json?t=" + Date.now()).then(function (r) { return r.json(); }).catch(function () { return {}; })
    ]).then(function (res) {
      JC = (res[3] && res[3].jogos) || {};
      ESTRUT = res[4] || null;
      TERMAP = res[5] || null;
      FAIRPLAY = (res[6] && res[6].fairplay) || {};
      SELECOES = (res[0].selecoes || []);
      SELECOES.forEach(function (s) { SEL[s.id] = s.nome; ISO[s.id] = s.iso2; });
      TVS = res[1] || {};
      (res[2].events || []).forEach(function (ev) {
        var c = ev.competitions && ev.competitions[0]; if (!c) return;
        var cs = c.competitors || [];
        var h = cs.find(function (x) { return x.homeAway === "home"; }) || cs[0];
        var a = cs.find(function (x) { return x.homeAway === "away"; }) || cs[1];
        if (!h || !a) return;
        var aRaw = (h.team || {}).abbreviation, bRaw = (a.team || {}).abbreviation;
        var aId = siglaTimeTexto(aRaw) || aRaw, bId = siglaTimeTexto(bRaw) || bRaw;
        JOGOS.push({
          id: ev.id, raw: ev, date: new Date(ev.date), state: getPath(c, ["status", "type", "state"], "pre"),
          a: aId, b: bId, an: SEL[aId] || getPath(h, ["team", "shortDisplayName"], aId), bn: SEL[bId] || getPath(a, ["team", "shortDisplayName"], bId),
          scoreA: scoreCompetidor(h), scoreB: scoreCompetidor(a),
          penA: placarPenaltiCompetidor(h), penB: placarPenaltiCompetidor(a),
          vencedor: h.winner ? aId : (a.winner ? bId : ""),
          venue: (c.venue && c.venue.fullName) || ""
        });
      });
      aplicarProjecoesMata();
      preencherFiltros();
      ligarFiltros();
      render();
      var bi = $("#btn-ics"); if (bi) bi.onclick = baixarICS;
      var bc = $("#btn-share"); if (bc) bc.onclick = compartilhar;
    }).catch(function () {
      $("#lista").innerHTML = '<p class="vazio">Não consegui carregar os jogos agora. Tente recarregar.</p>';
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

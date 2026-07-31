/* ========================================================================== 
   Desafios na Mesa — consulta privada e administração por RPC
   --------------------------------------------------------------------------
   O navegador nunca acessa as tabelas diretamente. A sessão é validada pelo
   menu global e cada RPC repete a validação no servidor.
   ========================================================================== */
(function (global, document) {
  "use strict";

  var STORAGE_KEY = "brApostasSessaoV2";
  var TIMEZONE = "America/Sao_Paulo";
  var STATUS_LABELS = {
    em_andamento: "Em andamento",
    aguardando_resultado: "Aguardando resultado",
    encerrado: "Encerrado · aguardando cumprimento",
    cumprido: "Cumprido",
    cancelado: "Cancelado"
  };
  var RESTRICTED = /(?:\bdinheiro\b|\bpix\b|r\s*\$|\breais?\b|\bbet(?:s)?\b|\bcassino\b|\bjogos?\s+de\s+azar\b|\bvinhos?\b|\bchamp(?:agne|anhe)\b|\bespumantes?\b|\bcervejas?\b|\bwhisk(?:y|ey)\b|\bvodka\b|\bcacha[cç]as?\b|\bgins?\b|\brum\b|\blicores?\b|\bbebidas?\s+alco[oó]licas?\b)/i;

  var state = {
    usuario: null,
    token: "",
    desafios: [],
    participantes: [],
    admin: false,
    loading: false
  };

  function byId(id) { return document.getElementById(id); }

  function safeJson(value) {
    try { return JSON.parse(value || "null"); }
    catch (_) { return null; }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setStatus(message, tone) {
    var el = byId("desafios-status");
    if (!el) return;
    el.textContent = message;
    el.className = "status " + (tone || "warn");
  }

  function toast(message, tone) {
    var region = byId("desafios-toast");
    if (!region) return;
    var item = document.createElement("div");
    item.className = "toast " + (tone || "ok");
    item.textContent = message;
    region.appendChild(item);
    global.setTimeout(function () { item.remove(); }, 4200);
  }

  function config() {
    var cfg = global.BR_CFG && global.BR_CFG.supabase ? global.BR_CFG.supabase : {};
    return { url: String(cfg.url || "").replace(/\/$/, ""), key: String(cfg.key || "") };
  }

  async function rpc(name, payload) {
    var cfg = config();
    if (!cfg.url || !cfg.key) throw new Error("Configuração do serviço indisponível.");
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? global.setTimeout(function () { controller.abort(); }, 12000) : null;
    try {
      var response = await global.fetch(cfg.url + "/rest/v1/rpc/" + name, {
        method: "POST",
        cache: "no-store",
        headers: {
          "apikey": cfg.key,
          "Authorization": "Bearer " + cfg.key,
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify(payload || {}),
        signal: controller ? controller.signal : undefined
      });
      var text = await response.text();
      var data = safeJson(text);
      if (!response.ok) {
        var message = data && (data.message || data.hint) ? (data.message || data.hint) : "Falha HTTP " + response.status + ".";
        var error = new Error(message);
        error.status = response.status;
        error.code = data && data.code ? data.code : "";
        throw error;
      }
      return data;
    } catch (error) {
      if (error && error.name === "AbortError") throw new Error("A consulta demorou além do esperado. Tente novamente.");
      throw error;
    } finally {
      if (timer) global.clearTimeout(timer);
    }
  }

  function rows(data) {
    if (Array.isArray(data)) return data;
    if (data == null) return [];
    return [data];
  }

  function formatDate(value) {
    if (!value) return "—";
    var parts = String(value).slice(0, 10).split("-");
    if (parts.length !== 3) return "—";
    return parts[2] + "/" + parts[1] + "/" + parts[0];
  }

  function formatDateTime(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("pt-BR", {
      timeZone: TIMEZONE,
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date).replace(",", " às");
  }

  function isoToLocalInput(value) {
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    var parts = new Intl.DateTimeFormat("sv-SE", {
      timeZone: TIMEZONE,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false
    }).formatToParts(date).reduce(function (acc, part) {
      acc[part.type] = part.value;
      return acc;
    }, {});
    return parts.year + "-" + parts.month + "-" + parts.day + "T" + parts.hour + ":" + parts.minute;
  }

  function localInputToIso(value) {
    if (!value) return null;
    var match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
    if (!match) return null;
    var utcGuess = Date.UTC(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]);
    var probe = new Date(utcGuess);
    var brHour = Number(new Intl.DateTimeFormat("en-US", { timeZone: TIMEZONE, hour: "2-digit", hour12: false }).format(probe));
    var brDay = Number(new Intl.DateTimeFormat("en-US", { timeZone: TIMEZONE, day: "2-digit" }).format(probe));
    var wantedDay = Number(match[3]);
    var dayDelta = brDay === wantedDay ? 0 : (brDay < wantedDay || (brDay > 20 && wantedDay < 10) ? 1 : -1);
    var offsetHours = (+match[4]) - brHour + (dayDelta * 24);
    return new Date(utcGuess + offsetHours * 3600000).toISOString();
  }

  function todayKey() {
    return new Intl.DateTimeFormat("sv-SE", { timeZone: TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  }

  function participantMap() {
    var map = {};
    state.participantes.forEach(function (item) { map[item.participante_id] = item.nome; });
    state.desafios.forEach(function (item) {
      if (item.participante_a_id) map[item.participante_a_id] = item.participante_a_nome;
      if (item.participante_b_id) map[item.participante_b_id] = item.participante_b_nome;
    });
    return map;
  }

  function allParticipants() {
    var map = participantMap();
    return Object.keys(map).map(function (id) { return { participante_id: id, nome: map[id] }; })
      .filter(function (item) { return item.participante_id && item.nome; })
      .sort(function (a, b) { return a.nome.localeCompare(b.nome, "pt-BR"); });
  }

  function refreshParticipantFilter() {
    var select = byId("filtro-participante");
    var selected = select.value;
    select.innerHTML = '<option value="">Todos os participantes</option>' + allParticipants().map(function (item) {
      return '<option value="' + escapeHtml(item.participante_id) + '">' + escapeHtml(item.nome) + "</option>";
    }).join("");
    select.value = selected;
  }

  function updateSummary() {
    function count(status) { return state.desafios.filter(function (item) { return item.status === status; }).length; }
    byId("total-andamento").textContent = count("em_andamento");
    byId("total-apuracao").textContent = count("aguardando_resultado");
    byId("total-pendentes").textContent = count("encerrado");
    byId("total-cumpridos").textContent = count("cumprido");
  }

  function selectedChallenges() {
    var query = String(byId("filtro-busca").value || "").trim().toLocaleLowerCase("pt-BR");
    var status = byId("filtro-status").value;
    var participant = byId("filtro-participante").value;
    return state.desafios.filter(function (item) {
      if (status === "ativos" && ["em_andamento", "aguardando_resultado", "encerrado"].indexOf(item.status) < 0) return false;
      if (status !== "ativos" && status !== "todos" && item.status !== status) return false;
      if (participant && item.participante_a_id !== participant && item.participante_b_id !== participant) return false;
      if (query) {
        var haystack = [item.titulo, item.participante_a_nome, item.participante_b_nome, item.descricao, item.criterio_resultado, item.compromisso_simbolico]
          .join(" ").toLocaleLowerCase("pt-BR");
        if (haystack.indexOf(query) < 0) return false;
      }
      return true;
    });
  }

  function resultHtml(item) {
    if (!item.vencedor_id || !item.perdedor_id) return "";
    var done = item.cumprido ? "Compromisso cumprido" + (item.data_cumprimento ? " em " + formatDate(item.data_cumprimento) : "") : "Cumprimento pendente";
    return '<div class="result-banner"><strong>🏅 Vencedor: ' + escapeHtml(item.vencedor_nome || "—") + "</strong><br>Responsável pelo compromisso: " + escapeHtml(item.perdedor_nome || "—") + " · " + escapeHtml(done) + "</div>";
  }

  function cardHtml(item) {
    var active = ["em_andamento", "aguardando_resultado"].indexOf(item.status) >= 0;
    var overdue = active && item.prazo && item.prazo < todayKey();
    var classes = "desafio-card" + (overdue ? " is-overdue" : "") + (item.status === "cumprido" ? " is-done" : "") + (item.status === "cancelado" ? " is-cancelled" : "");
    var adminActions = state.admin ? '<div class="desafio-card-actions"><button type="button" class="btn secondary" data-edit="' + escapeHtml(item.id) + '">✏️ Editar</button>' + (item.status !== "cancelado" ? '<button type="button" class="btn danger" data-cancel="' + escapeHtml(item.id) + '">Cancelar</button>' : "") + "</div>" : "";
    var observations = item.observacoes ? '<div class="detail-box wide"><span class="detail-label">Observações</span><span class="detail-value">' + escapeHtml(item.observacoes) + "</span></div>" : "";
    return '<article class="' + classes + '">' +
      '<header class="desafio-card-head"><div><span class="status-pill ' + escapeHtml(item.status) + '">' + escapeHtml(STATUS_LABELS[item.status] || item.status) + "</span><h2>" + escapeHtml(item.titulo) + "</h2></div>" + adminActions + "</header>" +
      '<div class="desafio-card-body"><div class="desafio-versus"><div class="desafio-person">' + escapeHtml(item.participante_a_nome) + '</div><span class="versus-label">DESAFIO</span><div class="desafio-person">' + escapeHtml(item.participante_b_nome) + "</div></div>" +
      '<p class="desafio-description">' + escapeHtml(item.descricao) + "</p>" +
      '<div class="desafio-details">' +
      '<div class="detail-box wide"><span class="detail-label">Critério de resultado</span><span class="detail-value">' + escapeHtml(item.criterio_resultado) + "</span></div>" +
      '<div class="detail-box"><span class="detail-label">Compromisso simbólico</span><span class="detail-value">' + escapeHtml(item.compromisso_simbolico) + "</span></div>" +
      '<div class="detail-box"><span class="detail-label">Data-limite</span><span class="detail-value">' + escapeHtml(formatDate(item.prazo)) + (overdue ? " · prazo vencido" : "") + "</span></div>" +
      '<div class="detail-box"><span class="detail-label">Alerta programado</span><span class="detail-value">' + escapeHtml(formatDateTime(item.alerta_em)) + (item.alerta_enviado_em ? " · enviado" : "") + "</span></div>" +
      observations + resultHtml(item) + "</div></div></article>";
  }

  function render() {
    updateSummary();
    refreshParticipantFilter();
    var list = byId("desafios-lista");
    var selected = selectedChallenges();
    list.setAttribute("aria-busy", "false");
    if (!selected.length) {
      list.innerHTML = '<div class="empty-state"><strong>Nenhum desafio neste filtro.</strong><span>Altere os filtros' + (state.admin ? " ou use o botão “Novo desafio”." : ".") + "</span></div>";
      return;
    }
    list.innerHTML = selected.map(cardHtml).join("");
  }

  function friendlyLoadError(error) {
    var missing = error && (error.status === 404 || error.code === "PGRST202" || error.code === "42883");
    if (missing && state.admin) return "A infraestrutura dos Desafios na Mesa ainda não foi ativada. Execute supabase/brasileirao_desafios_mesa.sql no Supabase e recarregue a página.";
    if (missing) return "A área de desafios ainda está em configuração. Procure a administração.";
    return error && error.message ? error.message : "Não foi possível carregar os desafios.";
  }

  async function loadData() {
    if (state.loading) return;
    state.loading = true;
    setStatus("Carregando desafios…", "warn");
    byId("desafios-lista").setAttribute("aria-busy", "true");
    try {
      var calls = [rpc("br_desafios_listar", { p_participante_id: state.usuario.id, p_token: state.token })];
      if (state.admin) calls.push(rpc("br_desafios_admin_participantes", { p_admin_id: state.usuario.id, p_token: state.token }));
      var result = await Promise.all(calls);
      state.desafios = rows(result[0]);
      state.participantes = state.admin ? rows(result[1]) : [];
      render();
      setStatus(state.desafios.length + (state.desafios.length === 1 ? " desafio registrado." : " desafios registrados.") + (state.admin ? " Você pode administrar os registros." : " Consulta liberada para participante."), "ok");
    } catch (error) {
      state.desafios = [];
      render();
      setStatus(friendlyLoadError(error), "err");
    } finally {
      state.loading = false;
    }
  }

  function fillParticipantSelect(select, selected, placeholder) {
    select.innerHTML = '<option value="">' + escapeHtml(placeholder) + "</option>" + state.participantes.filter(function (item) { return item.ativo !== false; }).map(function (item) {
      return '<option value="' + escapeHtml(item.participante_id) + '">' + escapeHtml(item.nome) + "</option>";
    }).join("");
    select.value = selected || "";
  }

  function updateResultOptions(winner, loser) {
    var ids = [byId("participante-a").value, byId("participante-b").value].filter(Boolean);
    var map = participantMap();
    [byId("desafio-vencedor"), byId("desafio-perdedor")].forEach(function (select, index) {
      var value = index === 0 ? winner : loser;
      select.innerHTML = '<option value="">Ainda não definido</option>' + ids.map(function (id) {
        return '<option value="' + escapeHtml(id) + '">' + escapeHtml(map[id] || "Participante") + "</option>";
      }).join("");
      select.value = value || "";
    });
  }

  function openForm(item) {
    if (!state.admin) return;
    byId("desafio-form").reset();
    byId("form-erro").hidden = true;
    byId("form-titulo").textContent = item ? "Editar desafio" : "Novo desafio";
    byId("desafio-id").value = item ? item.id : "";
    fillParticipantSelect(byId("participante-a"), item && item.participante_a_id, "Selecione");
    fillParticipantSelect(byId("participante-b"), item && item.participante_b_id, "Selecione");
    byId("desafio-titulo").value = item ? item.titulo : "";
    byId("desafio-descricao").value = item ? item.descricao : "";
    byId("desafio-criterio").value = item ? item.criterio_resultado : "";
    byId("desafio-compromisso").value = item ? item.compromisso_simbolico : "";
    byId("desafio-prazo").value = item ? String(item.prazo || "").slice(0, 10) : "";
    byId("desafio-alerta").value = item ? isoToLocalInput(item.alerta_em) : "";
    byId("desafio-status-campo").value = item && item.status !== "cancelado" ? item.status : "em_andamento";
    byId("desafio-cumprido").checked = Boolean(item && item.cumprido);
    byId("desafio-data-cumprimento").value = item ? String(item.data_cumprimento || "").slice(0, 10) : "";
    byId("desafio-observacoes").value = item ? (item.observacoes || "") : "";
    updateResultOptions(item && item.vencedor_id, item && item.perdedor_id);
    var dialog = byId("desafio-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    global.setTimeout(function () { byId("desafio-titulo").focus(); }, 40);
  }

  function closeForm() {
    var dialog = byId("desafio-dialog");
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function formValue(id) { return String(byId(id).value || "").trim(); }

  function validateForm(payload) {
    if (!payload.p_titulo || !payload.p_descricao || !payload.p_criterio_resultado || !payload.p_compromisso_simbolico) return "Preencha todos os campos obrigatórios.";
    if (!payload.p_participante_a_id || !payload.p_participante_b_id) return "Selecione os dois participantes.";
    if (payload.p_participante_a_id === payload.p_participante_b_id) return "Os dois participantes precisam ser diferentes.";
    if (!payload.p_prazo || !payload.p_alerta_em) return "Informe a data-limite e a data do alerta.";
    var safeText = [payload.p_titulo, payload.p_descricao, payload.p_criterio_resultado, payload.p_compromisso_simbolico, payload.p_observacoes || ""].join(" ");
    if (RESTRICTED.test(safeText)) return "Use somente compromissos simbólicos: sem dinheiro, itens restritos ou jogos de azar.";
    var hasWinner = Boolean(payload.p_vencedor_id);
    var hasLoser = Boolean(payload.p_perdedor_id);
    if (hasWinner !== hasLoser) return "Defina vencedor e responsável pelo compromisso juntos.";
    if (hasWinner && payload.p_vencedor_id === payload.p_perdedor_id) return "Vencedor e responsável pelo compromisso precisam ser pessoas diferentes.";
    if (["encerrado", "cumprido"].indexOf(payload.p_status) >= 0 && (!hasWinner || !hasLoser)) return "Para encerrar, defina o resultado completo.";
    if (payload.p_cumprido && (!payload.p_data_cumprimento || payload.p_status !== "cumprido")) return "Marque a situação como Cumprido e informe a data do cumprimento.";
    if (payload.p_status === "cumprido" && (!payload.p_cumprido || !payload.p_data_cumprimento)) return "Confirme o cumprimento e informe a data.";
    if (new Date(payload.p_alerta_em).getTime() > new Date(payload.p_prazo + "T23:59:59-03:00").getTime()) return "O alerta deve ocorrer até a data-limite.";
    return "";
  }

  async function saveForm(event) {
    event.preventDefault();
    if (!state.admin) return;
    var payload = {
      p_admin_id: state.usuario.id,
      p_token: state.token,
      p_desafio_id: formValue("desafio-id") || null,
      p_titulo: formValue("desafio-titulo"),
      p_participante_a_id: formValue("participante-a") || null,
      p_participante_b_id: formValue("participante-b") || null,
      p_descricao: formValue("desafio-descricao"),
      p_criterio_resultado: formValue("desafio-criterio"),
      p_compromisso_simbolico: formValue("desafio-compromisso"),
      p_prazo: formValue("desafio-prazo") || null,
      p_alerta_em: localInputToIso(formValue("desafio-alerta")),
      p_status: formValue("desafio-status-campo"),
      p_vencedor_id: formValue("desafio-vencedor") || null,
      p_perdedor_id: formValue("desafio-perdedor") || null,
      p_cumprido: byId("desafio-cumprido").checked,
      p_data_cumprimento: formValue("desafio-data-cumprimento") || null,
      p_observacoes: formValue("desafio-observacoes") || null
    };
    var error = validateForm(payload);
    var errorBox = byId("form-erro");
    if (error) {
      errorBox.textContent = error;
      errorBox.hidden = false;
      return;
    }
    errorBox.hidden = true;
    var button = byId("salvar-desafio");
    button.disabled = true;
    button.textContent = "Salvando…";
    try {
      await rpc("br_desafios_admin_salvar", payload);
      closeForm();
      toast("Desafio salvo com sucesso.", "ok");
      await loadData();
    } catch (saveError) {
      errorBox.textContent = saveError && saveError.message ? saveError.message : "Não foi possível salvar.";
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Salvar desafio";
    }
  }

  async function cancelChallenge(id) {
    if (!state.admin) return;
    var item = state.desafios.find(function (candidate) { return candidate.id === id; });
    if (!item) return;
    var confirmed = global.confirm("Cancelar o desafio “" + item.titulo + "”? O histórico será preservado.");
    if (!confirmed) return;
    try {
      await rpc("br_desafios_admin_cancelar", { p_admin_id: state.usuario.id, p_token: state.token, p_desafio_id: id });
      toast("Desafio cancelado; o histórico foi preservado.", "ok");
      await loadData();
    } catch (error) {
      toast(error && error.message ? error.message : "Não foi possível cancelar.", "err");
    }
  }

  function wireEvents() {
    byId("filtro-busca").addEventListener("input", render);
    byId("filtro-status").addEventListener("change", render);
    byId("filtro-participante").addEventListener("change", render);
    byId("novo-desafio").addEventListener("click", function () { openForm(null); });
    byId("fechar-form").addEventListener("click", closeForm);
    byId("cancelar-form").addEventListener("click", closeForm);
    byId("desafio-form").addEventListener("submit", saveForm);
    byId("participante-a").addEventListener("change", function () { updateResultOptions("", ""); });
    byId("participante-b").addEventListener("change", function () { updateResultOptions("", ""); });
    byId("desafio-cumprido").addEventListener("change", function () {
      if (this.checked) byId("desafio-status-campo").value = "cumprido";
    });
    byId("desafio-status-campo").addEventListener("change", function () {
      if (this.value !== "cumprido") byId("desafio-cumprido").checked = false;
    });
    byId("desafios-lista").addEventListener("click", function (event) {
      var edit = event.target.closest("[data-edit]");
      if (edit) {
        var item = state.desafios.find(function (candidate) { return candidate.id === edit.getAttribute("data-edit"); });
        if (item) openForm(item);
        return;
      }
      var cancel = event.target.closest("[data-cancel]");
      if (cancel) cancelChallenge(cancel.getAttribute("data-cancel"));
    });
  }

  async function init() {
    wireEvents();
    try {
      var auth = await global.BR_AUTH_READY;
      if (!auth || !auth.authenticated || !auth.usuario) return;
      var stored = safeJson(global.localStorage.getItem(STORAGE_KEY));
      if (!stored || !stored.token || !stored.usuario || stored.usuario.id !== auth.usuario.id) {
        global.location.replace("apostas.html?retorno=" + encodeURIComponent("desafios-mesa.html"));
        return;
      }
      state.usuario = auth.usuario;
      state.token = stored.token;
      state.admin = Boolean(auth.usuario.admin);
      Array.prototype.forEach.call(document.querySelectorAll(".admin-only"), function (element) { element.hidden = !state.admin; });
      await loadData();
    } catch (error) {
      setStatus("Não foi possível validar o acesso. Entre novamente.", "err");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window, document);

/* ========================================================================== 
   br-menu.js — menu público/logado e proteção de rotas do Brasileirão 2026
   --------------------------------------------------------------------------
   - Visitante: Jogos, Ao vivo, Tabela, Resultados, Estatísticas, Clubes,
     Museu, Copa 2026 e Login.
   - Participante validado: acrescenta Apostas, Bolão, Regras e Aniversariantes;
     o item Login passa a exibir o nome do participante e permite sair.
   - A sessão local é sempre validada no Supabase antes de liberar área privada.
   ========================================================================== */
(function (global, document) {
  "use strict";

  var STORAGE_KEY = "brApostasSessaoV2";
  var PRIVATE_VIEWS = { rank: true, aniversariantes: true, participantes: true };
  var authState = {
    pending: true,
    authenticated: false,
    usuario: null,
    token: "",
    validationError: ""
  };
  var readyResolve;
  var operationalState = {
    loaded: false,
    loading: false,
    update: null,
    deploy: null,
    error: ""
  };

  global.BR_AUTH_READY = new Promise(function (resolve) { readyResolve = resolve; });

  function safeJson(value) {
    try { return JSON.parse(value || "null"); }
    catch (_) { return null; }
  }

  function sessionPayload() {
    try { return safeJson(global.localStorage.getItem(STORAGE_KEY)); }
    catch (_) { return null; }
  }

  function clearStoredSession() {
    try { global.localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  function basename() {
    var path = String(global.location.pathname || "");
    var last = path.split("/").filter(Boolean).pop() || "";
    return last.toLowerCase();
  }

  function currentView() {
    var path = String(global.location.pathname || "").replace(/\/+$/, "").toLowerCase();
    var cleanRoutes = { "/jogos": "jogos", "/tabela": "tabela", "/resultados": "resultados", "/bolao": "rank", "/aniversariantes": "aniversariantes" };
    if (cleanRoutes[path]) return cleanRoutes[path];
    try { return String(new URLSearchParams(global.location.search || "").get("view") || "").toLowerCase(); }
    catch (_) { return ""; }
  }

  function cleanUrlForView(view) {
    var routes = { jogos: "/jogos", tabela: "/tabela", resultados: "/resultados", rank: "/bolao", aniversariantes: "/aniversariantes" };
    return routes[String(view || "").toLowerCase()] || "";
  }

  function normalizeMenuLinks(nav) {
    if (!nav) return;
    Array.prototype.forEach.call(nav.querySelectorAll("a[data-br-view]"), function (link) {
      var clean = cleanUrlForView(link.getAttribute("data-br-view"));
      if (clean) link.setAttribute("href", clean);
    });
  }

  function isPrivateRoute() {
    if (document.body && document.body.getAttribute("data-br-private-page") === "1") return true;
    if (basename() === "regras.html") return true;
    return Boolean(PRIVATE_VIEWS[currentView()]);
  }

  function isAdminRoute() {
    var file = basename();
    if (file !== "" && file !== "index.html") return false;
    if (currentView() !== "participantes") return false;
    try { return String(new URLSearchParams(global.location.search || "").get("admin") || "") === "1"; }
    catch (_) { return false; }
  }

  function returnTarget() {
    var cleanView = currentView();
    var cleanTargets = { jogos: "/jogos", tabela: "/tabela", resultados: "/resultados", rank: "/bolao", aniversariantes: "/aniversariantes" };
    if (cleanTargets[cleanView]) return cleanTargets[cleanView] + (global.location.hash || "");
    var file = basename();
    if (file === "" || file === "index.html") {
      return "/jogos" + (global.location.hash || "");
    }
    return file + (global.location.search || "") + (global.location.hash || "");
  }

  function loginUrl(target) {
    var url = "apostas.html";
    if (target) url += "?retorno=" + encodeURIComponent(target);
    return url;
  }

  function redirectToLogin() {
    var target = returnTarget();
    try { global.sessionStorage.setItem("brLoginRetorno", target); } catch (_) {}
    global.location.replace(loginUrl(target));
  }

  function supabaseConfig() {
    var cfg = global.BR_CFG && global.BR_CFG.supabase ? global.BR_CFG.supabase : {};
    return { url: String(cfg.url || "").replace(/\/$/, ""), key: String(cfg.key || "") };
  }

  async function validateRemote(sess) {
    if (!sess || !sess.usuario || !sess.usuario.id || !sess.token) return { valid: false, definitive: true };
    var cfg = supabaseConfig();
    if (!cfg.url || !cfg.key) return { valid: false, definitive: false, error: "Configuração do Supabase indisponível." };

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? global.setTimeout(function () { controller.abort(); }, 8000) : null;
    try {
      var res = await global.fetch(cfg.url + "/rest/v1/rpc/br_validar_sessao", {
        method: "POST",
        cache: "no-store",
        headers: {
          "apikey": cfg.key,
          "Authorization": "Bearer " + cfg.key,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          p_participante_id: sess.usuario.id,
          p_token: sess.token,
          p_exige_admin: false
        }),
        signal: controller ? controller.signal : undefined
      });
      if (!res.ok) {
        var body = "";
        try { body = await res.text(); } catch (_) {}
        return { valid: false, definitive: res.status >= 400 && res.status < 500, error: "HTTP " + res.status + (body ? "" : "") };
      }
      var data = await res.json();
      var valid = data === true || (data && data.br_validar_sessao === true);
      return { valid: Boolean(valid), definitive: true };
    } catch (err) {
      return { valid: false, definitive: false, error: err && err.message ? err.message : "Falha ao validar sessão." };
    } finally {
      if (timer) global.clearTimeout(timer);
    }
  }

  async function fetchOperationalJson(url) {
    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller ? global.setTimeout(function () { controller.abort(); }, 7000) : null;
    try {
      var res = await global.fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(), {
        cache: "no-store",
        headers: { "Accept": "application/json" },
        signal: controller ? controller.signal : undefined
      });
      if (!res.ok) return null;
      var data = await res.json();
      return data && typeof data === "object" ? data : null;
    } catch (_) {
      return null;
    } finally {
      if (timer) global.clearTimeout(timer);
    }
  }

  function operationalDate(value) {
    if (!value) return "não registrado";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat("pt-BR", {
        dateStyle: "short",
        timeStyle: "short",
        timeZone: "America/Sao_Paulo"
      }).format(date);
    } catch (_) {
      return date.toLocaleString("pt-BR");
    }
  }

  function operationalTone(status) {
    var value = String(status || "").toLowerCase();
    if (value === "ok") return "ok";
    if (value === "aviso" || value === "preservado") return "warning";
    return "error";
  }

  function createText(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = String(text == null ? "" : text);
    return el;
  }

  function operationalHost() {
    var existing = document.querySelector("[data-br-operational-status]");
    if (existing) return existing;
    var nav = document.querySelector(".nav[data-br-auth-menu]");
    if (!nav || !nav.parentNode) return null;
    var host = document.createElement("section");
    host.className = "br-operational-stack";
    host.setAttribute("data-br-operational-status", "1");
    host.setAttribute("aria-live", "polite");
    nav.parentNode.insertBefore(host, nav.nextSibling);
    return host;
  }

  function appendOperationalLink(container, href, label) {
    if (!href) return;
    var link = document.createElement("a");
    link.className = "br-data-status-link";
    link.href = String(href);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    container.appendChild(link);
  }

  function renderOperationalStatus() {
    var host = operationalHost();
    if (!host) return;
    host.textContent = "";
    var update = operationalState.update;
    var isAdmin = Boolean(authState.authenticated && authState.usuario && authState.usuario.admin);

    if (update && update.mostrar_publico === true) {
      var publicBox = document.createElement("div");
      publicBox.className = "br-data-status br-data-status--" + operationalTone(update.status);
      publicBox.setAttribute("role", String(update.status) === "erro" ? "alert" : "status");
      publicBox.appendChild(createText("span", "br-data-status-icon", String(update.status) === "erro" ? "!" : "i"));
      var publicBody = document.createElement("div");
      publicBody.className = "br-data-status-body";
      publicBody.appendChild(createText("strong", "", "Atualização dos dados"));
      publicBody.appendChild(createText("p", "", update.mensagem_publica || "Estamos exibindo o último levantamento confiável."));
      if (update.ultimo_snapshot_valido || update.ultimo_sucesso) {
        publicBody.appendChild(createText("small", "", "Último levantamento confiável: " + operationalDate(update.ultimo_snapshot_valido || update.ultimo_sucesso) + "."));
      }
      publicBox.appendChild(publicBody);
      host.appendChild(publicBox);
    }

    if (isAdmin) {
      var adminBox = document.createElement("details");
      var adminStatus = update ? update.status : "erro";
      adminBox.className = "br-data-status br-data-status--admin br-data-status--" + operationalTone(adminStatus);
      if (update && update.status !== "ok") adminBox.open = true;
      var summary = document.createElement("summary");
      summary.appendChild(createText("span", "br-data-status-admin-dot", ""));
      summary.appendChild(createText("strong", "", update ? "Saúde do Brasileirão: " + String(update.status || "indefinido").toUpperCase() : "Saúde do Brasileirão: indisponível"));
      if (update && update.ultima_tentativa) summary.appendChild(createText("small", "", operationalDate(update.ultima_tentativa)));
      adminBox.appendChild(summary);
      var detail = document.createElement("div");
      detail.className = "br-data-status-admin-grid";
      if (update) {
        detail.appendChild(createText("p", "br-data-status-wide", update.mensagem_admin || "Sem mensagem técnica."));
        detail.appendChild(createText("p", "", "Última tentativa: " + operationalDate(update.ultima_tentativa)));
        detail.appendChild(createText("p", "", "Último sucesso: " + operationalDate(update.ultimo_sucesso)));
        detail.appendChild(createText("p", "", "Fonte principal: " + String(update.fonte_principal || "ESPN")));
        var complementary = Array.isArray(update.fontes_complementares) && update.fontes_complementares.length ? update.fontes_complementares.join(", ") : "nenhuma";
        detail.appendChild(createText("p", "", "Fontes complementares: " + complementary));
        detail.appendChild(createText("p", "", "Tentativas: " + String(update.tentativas == null ? "—" : update.tentativas)));
        detail.appendChild(createText("p", "", "Snapshot: " + String(update.snapshot_hash || "").slice(0, 12) + (update.snapshot_hash ? "…" : "não registrado")));
        appendOperationalLink(detail, update.run_url, "Abrir atualização no GitHub Actions");
      } else {
        detail.appendChild(createText("p", "br-data-status-wide", operationalState.error || "Não foi possível carregar o arquivo de status operacional."));
      }
      if (operationalState.deploy) {
        detail.appendChild(createText("p", "", "Deploy publicado: " + operationalDate(operationalState.deploy.publicado_em)));
        detail.appendChild(createText("p", "", "Commit publicado: " + String(operationalState.deploy.source_commit || "").slice(0, 12) + (operationalState.deploy.source_commit ? "…" : "não registrado")));
        appendOperationalLink(detail, operationalState.deploy.run_url, "Abrir deploy no GitHub Actions");
      } else {
        detail.appendChild(createText("p", "", "Deploy: status ainda não disponível."));
      }
      adminBox.appendChild(detail);
      host.appendChild(adminBox);
    }

    host.hidden = host.childElementCount === 0;
    resetFloatingOrigins();
  }

  async function loadOperationalStatus() {
    if (operationalState.loading) return;
    operationalState.loading = true;
    var values = await Promise.all([
      fetchOperationalJson("/dados-br/status-atualizacao.json"),
      fetchOperationalJson("/dados-br/status-deploy.json")
    ]);
    operationalState.update = values[0];
    operationalState.deploy = values[1];
    operationalState.loaded = true;
    operationalState.loading = false;
    operationalState.error = values[0] ? "" : "Status operacional indisponível nesta publicação.";
    renderOperationalStatus();
  }

  function displayName(usuario) {
    var nome = String(usuario && (usuario.nome || usuario.login) || "Participante").trim();
    if (!nome) return "Participante";
    if (nome.length <= 18) return nome;
    return nome.split(/\s+/)[0] || nome.slice(0, 18);
  }

  function centerActive(nav, behavior) {
    if (!nav) return;
    var active = nav.querySelector(".active:not([hidden])");
    if (!active) return;
    var left = active.offsetLeft - (nav.clientWidth / 2) + (active.offsetWidth / 2);
    if (!Number.isFinite(left)) return;
    try { nav.scrollTo({ left: Math.max(0, left), behavior: behavior || "smooth" }); }
    catch (_) { nav.scrollLeft = Math.max(0, left); }
  }


  var floatingNavsReady = false;
  var floatingNavRaf = 0;

  function floatingTopOffset() {
    var safe = 0;
    try {
      safe = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sat")) || 0;
    } catch (_) {}
    return (global.matchMedia && global.matchMedia("(max-width: 820px)").matches ? 4 : 8) + safe;
  }

  function pageScrollY() {
    return Number(global.scrollY || global.pageYOffset || document.documentElement.scrollTop || 0);
  }

  function ensureFloatingNav(nav) {
    if (!nav || nav.dataset.brFloatingReady === "1") return;
    var marker = document.createElement("div");
    marker.className = "br-nav-placeholder";
    marker.setAttribute("aria-hidden", "true");
    nav.parentNode.insertBefore(marker, nav);
    nav.dataset.brFloatingReady = "1";
    nav._brFloatingMarker = marker;
    nav._brFloatingOriginY = null;
  }

  function outerHeight(el) {
    var rect = el.getBoundingClientRect();
    var cs = global.getComputedStyle ? global.getComputedStyle(el) : null;
    var mt = cs ? parseFloat(cs.marginTop || "0") || 0 : 0;
    var mb = cs ? parseFloat(cs.marginBottom || "0") || 0 : 0;
    return Math.ceil(rect.height + mt + mb);
  }

  function setMarkerHeight(marker, value) {
    if (!marker) return;
    marker.style.setProperty("height", Math.max(0, Math.ceil(value || 0)) + "px", "important");
  }

  function updateFloatingNavs() {
    floatingNavRaf = 0;
    var scrollY = pageScrollY();
    var navs = Array.prototype.slice.call(document.querySelectorAll(".nav[data-br-auth-menu]"));
    navs.forEach(function (nav) {
      ensureFloatingNav(nav);
      var marker = nav._brFloatingMarker;
      var fixed = nav.classList.contains("br-nav-floating");
      // Elementos position:fixed podem ter offsetParent nulo. Não interrompa
      // a atualização nesse estado, pois é justamente ela que remove a classe
      // quando o usuário volta ao ponto original do menu.
      if (!marker || nav.hidden || (!fixed && nav.offsetParent === null)) return;

      var top = floatingTopOffset();
      if (!Number.isFinite(nav._brFloatingOriginY)) {
        var anchor = fixed ? marker : nav;
        nav._brFloatingOriginY = anchor.getBoundingClientRect().top + scrollY;
      }
      var originY = Number(nav._brFloatingOriginY);
      var shouldFloat = scrollY + top >= originY;

      if (shouldFloat) {
        if (!fixed || !Number.isFinite(nav._brFloatingPlaceholderHeight)) {
          nav._brFloatingPlaceholderHeight = outerHeight(nav);
        }
        marker.classList.add("is-active");
        setMarkerHeight(marker, nav._brFloatingPlaceholderHeight);
        var rect = marker.getBoundingClientRect();
        var width = rect.width || nav.getBoundingClientRect().width;
        nav.style.setProperty("--br-nav-fixed-left", Math.round(rect.left) + "px");
        nav.style.setProperty("--br-nav-fixed-width", Math.round(width) + "px");
        nav.classList.add("br-nav-floating");
      } else {
        nav.classList.remove("br-nav-floating");
        nav.style.removeProperty("--br-nav-fixed-left");
        nav.style.removeProperty("--br-nav-fixed-width");
        marker.classList.remove("is-active");
        setMarkerHeight(marker, 0);
        nav._brFloatingPlaceholderHeight = null;
      }
    });
  }

  function requestFloatingNavUpdate() {
    if (floatingNavRaf) return;
    floatingNavRaf = global.requestAnimationFrame ? global.requestAnimationFrame(updateFloatingNavs) : global.setTimeout(updateFloatingNavs, 16);
  }

  function resetFloatingOrigins() {
    Array.prototype.forEach.call(document.querySelectorAll(".nav[data-br-auth-menu]"), function (nav) {
      nav._brFloatingOriginY = null;
      nav._brFloatingPlaceholderHeight = null;
    });
    requestFloatingNavUpdate();
  }

  function initFloatingNavs() {
    if (floatingNavsReady) { requestFloatingNavUpdate(); return; }
    floatingNavsReady = true;
    Array.prototype.forEach.call(document.querySelectorAll(".nav[data-br-auth-menu]"), ensureFloatingNav);
    global.addEventListener("scroll", requestFloatingNavUpdate, { passive: true });
    global.addEventListener("resize", resetFloatingOrigins);
    global.addEventListener("load", resetFloatingOrigins);
    global.addEventListener("orientationchange", function () { global.setTimeout(resetFloatingOrigins, 120); });
    Array.prototype.forEach.call(document.querySelectorAll(".hero img, .hero-header img"), function (img) {
      if (!img.complete) img.addEventListener("load", resetFloatingOrigins, { once: true });
    });
    requestFloatingNavUpdate();
    global.setTimeout(resetFloatingOrigins, 250);
  }

  function updateAuthItem(item) {
    if (!item) return;
    if (authState.authenticated) {
      var nome = displayName(authState.usuario);
      item.textContent = "👤 " + nome;
      item.setAttribute("title", "Participante: " + String(authState.usuario.nome || nome) + " — clique para sair");
      item.setAttribute("aria-label", "Participante " + nome + ". Clique para sair");
      item.setAttribute("href", "#sair");
      item.classList.remove("active");
      item.removeAttribute("aria-current");
      item.dataset.brLogged = "1";
    } else {
      item.textContent = "🔐 Login";
      item.setAttribute("title", "Entrar na área do participante");
      item.setAttribute("aria-label", "Login da área do participante");
      item.setAttribute("href", "apostas.html");
      delete item.dataset.brLogged;
      if (basename() === "apostas.html") {
        item.classList.add("active");
        item.setAttribute("aria-current", "page");
      } else {
        item.classList.remove("active");
        item.removeAttribute("aria-current");
      }
    }
  }

  function applyMenu(nav) {
    if (!nav) return;
    normalizeMenuLinks(nav);
    Array.prototype.forEach.call(nav.querySelectorAll("[data-br-private]"), function (item) {
      item.hidden = !authState.authenticated;
      item.setAttribute("aria-hidden", authState.authenticated ? "false" : "true");
      if (!authState.authenticated) item.classList.remove("active");
    });

    updateAuthItem(nav.querySelector("[data-br-auth-link]"));
    nav.dataset.brAuthReady = "1";
    nav.style.visibility = "visible";
    global.setTimeout(function () { centerActive(nav, "auto"); requestFloatingNavUpdate(); }, 20);
    global.setTimeout(function () { centerActive(nav, "smooth"); requestFloatingNavUpdate(); }, 180);
    initFloatingNavs();
  }

  function applyAllMenus() {
    Array.prototype.forEach.call(document.querySelectorAll(".nav[data-br-auth-menu]"), applyMenu);
  }

  function revealPage() {
    document.documentElement.classList.remove("br-private-pending");
  }

  function publishState() {
    global.BR_AUTH.pending = authState.pending;
    global.BR_AUTH.authenticated = authState.authenticated;
    global.BR_AUTH.usuario = authState.usuario;
    global.BR_AUTH.validationError = authState.validationError;
  }

  function dispatchReady() {
    try {
      document.dispatchEvent(new CustomEvent("br:auth-ready", { detail: {
        authenticated: authState.authenticated,
        usuario: authState.usuario,
        validationError: authState.validationError
      }}));
    } catch (_) {}
  }

  function finishAuth(next) {
    authState.pending = false;
    authState.authenticated = Boolean(next && next.authenticated);
    authState.usuario = authState.authenticated ? next.usuario : null;
    authState.token = authState.authenticated ? next.token : "";
    authState.validationError = String(next && next.validationError || "");
    publishState();

    if (!authState.authenticated && isPrivateRoute()) {
      redirectToLogin();
      return;
    }
    if (isAdminRoute() && !(authState.usuario && authState.usuario.admin)) {
      global.location.replace("apostas.html?aba=admin");
      return;
    }

    applyAllMenus();
    renderOperationalStatus();
    revealPage();
    dispatchReady();
    if (readyResolve) {
      readyResolve({ authenticated: authState.authenticated, usuario: authState.usuario, validationError: authState.validationError });
      readyResolve = null;
    }
  }

  async function refreshAuth() {
    authState.pending = true;
    publishState();
    var sess = sessionPayload();
    if (!sess || !sess.usuario || !sess.token) {
      finishAuth({ authenticated: false });
      return false;
    }

    var result = await validateRemote(sess);
    if (result.valid) {
      finishAuth({ authenticated: true, usuario: sess.usuario, token: sess.token });
      return true;
    }

    if (result.definitive) clearStoredSession();
    finishAuth({ authenticated: false, validationError: result.error || "Sessão inválida ou expirada." });
    return false;
  }

  function logout() {
    var sair = true;
    try { sair = global.confirm("Sair da área do participante?"); } catch (_) {}
    if (!sair) return;
    clearStoredSession();
    authState.pending = false;
    authState.authenticated = false;
    authState.usuario = null;
    authState.token = "";
    authState.validationError = "";
    publishState();
    try { document.dispatchEvent(new CustomEvent("br:session-changed", { detail: { authenticated: false } })); } catch (_) {}

    if (isPrivateRoute()) {
      global.location.replace("/jogos");
      return;
    }
    if (basename() === "apostas.html") {
      global.location.replace("apostas.html");
      return;
    }
    applyAllMenus();
    renderOperationalStatus();
  }

  function wireNav(nav) {
    if (!nav || nav.dataset.brMenuReady === "1") return;
    nav.dataset.brMenuReady = "1";

    nav.addEventListener("click", function (ev) {
      var el = ev.target && ev.target.closest ? ev.target.closest("a,button") : null;
      if (!el) return;

      if (el.hasAttribute("data-br-auth-link")) {
        if (authState.authenticated) {
          ev.preventDefault();
          ev.stopPropagation();
          logout();
        } else if (String(el.tagName || "").toLowerCase() === "button") {
          ev.preventDefault();
          global.location.href = el.getAttribute("href") || "apostas.html";
        }
        return;
      }

      var view = el.getAttribute("data-br-view");
      if (view) {
        try { global.sessionStorage.setItem("brViewInicial", view); } catch (_) {}
        var clean = cleanUrlForView(view);
        if (clean && String(el.tagName || "").toLowerCase() === "a") {
          ev.preventDefault();
          global.location.href = clean;
          return;
        }
      }
      global.setTimeout(function () { centerActive(nav); }, 100);
    });

    var obs = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i += 1) {
        if (mutations[i].attributeName === "class" || mutations[i].attributeName === "hidden") {
          global.setTimeout(function () { centerActive(nav); }, 30);
          break;
        }
      }
    });
    Array.prototype.forEach.call(nav.querySelectorAll("a,button"), function (item) {
      obs.observe(item, { attributes: true, attributeFilter: ["class", "hidden"] });
    });
  }

  function wireAllMenus() {
    Array.prototype.forEach.call(document.querySelectorAll(".nav[data-br-auth-menu]"), wireNav);
  }

  global.BR_AUTH = {
    pending: true,
    authenticated: false,
    usuario: null,
    validationError: "",
    refresh: refreshAuth,
    logout: logout,
    requireLogin: function (target) { global.location.href = loginUrl(target || returnTarget()); },
    isPrivateView: function (view) { return Boolean(PRIVATE_VIEWS[String(view || "").toLowerCase()]); }
  };

  global.BR_CENTER_ACTIVE_NAV = function () {
    Array.prototype.forEach.call(document.querySelectorAll(".nav[data-br-auth-menu]"), function (nav) { centerActive(nav); });
  };

  function init() {
    wireAllMenus();
    loadOperationalStatus();
    refreshAuth();
  }

  document.addEventListener("br:session-changed", function () { refreshAuth(); });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
    document.addEventListener("DOMContentLoaded", initFloatingNavs);
  } else {
    init();
    initFloatingNavs();
  }
})(window, document);

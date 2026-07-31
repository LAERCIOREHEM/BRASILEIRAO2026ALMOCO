/* =========================================================================
   avisos-site.js — Toast de novidade da PÁGINA PRINCIPAL do Brasileirão.

   Mesma origem de dados do módulo da Copa (RPC copa_aviso_site no Supabase),
   administrado pela mesma tela de avisos. A diferença é onde ele aparece:
   antes só em /copa2026/index.html, agora na raiz do site.

   Autossuficiente de propósito: o toast da Copa dependia de regras do
   copa2026/css/copa.css, que a raiz não carrega. Em vez de importar aquele
   CSS inteiro — o que colidiria com o layout do Brasileirão — o estilo vai
   injetado aqui, com as variáveis já resolvidas para valores literais.
   ========================================================================= */
(function () {
  "use strict";

  if (window.__brAvisoSiteIniciado) return;
  window.__brAvisoSiteIniciado = true;

  // A raiz define BR_CFG; o módulo da Copa define COPA_CFG. Ambos apontam
  // para o mesmo projeto Supabase, então qualquer um dos dois serve.
  const CFG =
    (window.BR_CFG && window.BR_CFG.supabase) ||
    window.COPA_CFG ||
    { url: "", key: "" };

  // Chave própria da home canônica. Assim, quem chegou a visualizar o aviso
  // antigo pela Copa ou por /?brasileirao=1 ainda o recebe uma única vez no
  // endereço correto após esta migração.
  const STORAGE_PREFIX = "br_home_aviso_site_visto_";
  const DEFAULT_DELAY_MS = 1000;
  const FADE_MS = 520;
  const CSS_ID = "br-aviso-site-estilo";

  function isPaginaPrincipal() {
    const path = String(location.pathname || "").replace(/\/+$/, "");
    const raiz = path === "" || path === "/index.html" || path === "/index";
    // O aviso pertence somente à home canônica. URLs legadas ou de contexto,
    // como /?brasileirao=1 e /?view=..., não podem consumi-lo como "visto".
    return raiz && !String(location.search || "");
  }

  function injetarEstilo() {
    if (document.getElementById(CSS_ID)) return;
    const style = document.createElement("style");
    style.id = CSS_ID;
    style.textContent = [
      ".br-aviso-site{position:fixed;left:50%;top:52%;bottom:auto;",
      "width:min(520px,calc(100vw - 40px));z-index:9999;display:flex;",
      "align-items:flex-start;gap:14px;",
      "background:radial-gradient(360px 160px at 18% 0%,rgba(244,197,66,.18),transparent 70%),",
      "linear-gradient(180deg,rgba(19,41,75,.985),rgba(11,31,58,.985));",
      "border:1px solid rgba(244,197,66,.62);border-radius:22px;",
      "padding:20px 18px 18px 20px;",
      "box-shadow:0 22px 70px rgba(0,0,0,.50),0 0 0 1px rgba(255,255,255,.05) inset;",
      "transform:translate(-50%,-42%) scale(.965);opacity:0;pointer-events:auto;",
      "transition:opacity .32s ease,transform .32s ease}",
      ".br-aviso-site.visivel{opacity:1;transform:translate(-50%,-50%) scale(1)}",
      ".br-aviso-site.saindo{opacity:0;transform:translate(-50%,-58%) scale(.985)}",
      ".br-aviso-corpo{min-width:0;flex:1}",
      ".br-aviso-titulo{font-weight:900;font-size:21px;letter-spacing:.3px;",
      "color:#f4c542;line-height:1.12;margin-bottom:8px}",
      ".br-aviso-msg{font-size:15px;line-height:1.5;color:#eaf3ff;",
      "word-wrap:break-word;white-space:pre-line}",
      ".br-aviso-fechar{flex:0 0 auto;background:rgba(244,197,66,.12);",
      "border:1px solid rgba(244,197,66,.48);color:#f4c542;font-family:inherit;",
      "font-size:12.5px;font-weight:800;border-radius:999px;padding:8px 12px;",
      "cursor:pointer;line-height:1}",
      ".br-aviso-fechar:hover{background:rgba(244,197,66,.20);",
      "border-color:rgba(244,197,66,.75)}",
      ".br-aviso-fechar:focus-visible{outline:2px solid rgba(244,197,66,.95);",
      "outline-offset:2px}",
      "@media(max-width:480px){",
      ".br-aviso-site{top:51%;width:calc(100vw - 32px);border-radius:20px;",
      "padding:18px 14px 16px 16px;gap:11px}",
      ".br-aviso-titulo{font-size:19px;margin-bottom:7px}",
      ".br-aviso-msg{font-size:14px;line-height:1.46}",
      ".br-aviso-fechar{font-size:11.5px;padding:7px 10px}}",
      "@media(max-width:360px){",
      ".br-aviso-site{width:calc(100vw - 24px);padding:16px 12px 14px 14px;gap:9px}",
      ".br-aviso-titulo{font-size:17px}",
      ".br-aviso-msg{font-size:13.4px}",
      ".br-aviso-fechar{padding:7px 9px}}"
    ].join("");
    document.head.appendChild(style);
  }

  function rpc(fn, body) {
    return fetch(`${CFG.url}/rest/v1/rpc/${fn}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "apikey": CFG.key,
        "Authorization": "Bearer " + CFG.key
      },
      body: JSON.stringify(body || {})
    }).then(async r => {
      if (!r.ok) throw new Error("RPC " + fn + " HTTP " + r.status);
      return r.json();
    });
  }

  function idSeguro(id) {
    return String(id || "")
      .trim()
      .toLowerCase()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 90);
  }

  function visto(id) {
    try { return localStorage.getItem(STORAGE_PREFIX + idSeguro(id)) === "1"; }
    catch (e) { return false; }
  }

  function marcarVisto(id) {
    try { localStorage.setItem(STORAGE_PREFIX + idSeguro(id), "1"); }
    catch (e) {}
  }

  function dentroDaJanela(aviso) {
    const agora = Date.now();
    const ini = aviso && aviso.data_inicio ? new Date(aviso.data_inicio).getTime() : NaN;
    const fim = aviso && aviso.data_fim ? new Date(aviso.data_fim).getTime() : NaN;
    if (!Number.isNaN(ini) && agora < ini) return false;
    if (!Number.isNaN(fim) && agora > fim) return false;
    return true;
  }

  function limparTexto(txt, limite) {
    return String(txt || "").replace(/\s+/g, " ").trim().slice(0, limite);
  }

  function normalizarAviso(raw) {
    const aviso = raw && typeof raw === "object" ? raw : null;
    if (!aviso || aviso.ativo !== true) return null;
    const id = idSeguro(aviso.id || aviso.id_aviso || "");
    const titulo = limparTexto(aviso.titulo || "🚀 Novidades no site", 80);
    const mensagem = limparTexto(aviso.mensagem || "", 420);
    const tempo = Math.min(15, Math.max(5, parseInt(aviso.tempo_segundos || aviso.tempo || 9, 10) || 9));
    if (!id || !mensagem) return null;
    return {
      id,
      titulo,
      mensagem,
      tempo_segundos: tempo,
      data_inicio: aviso.data_inicio || null,
      data_fim: aviso.data_fim || null
    };
  }

  function criarToast(aviso) {
    if (window.__brAvisoSiteMostrado || document.getElementById("br-aviso-site")) return;
    window.__brAvisoSiteMostrado = true;
    marcarVisto(aviso.id);
    injetarEstilo();

    const el = document.createElement("aside");
    el.id = "br-aviso-site";
    el.className = "br-aviso-site";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");

    const corpo = document.createElement("div");
    corpo.className = "br-aviso-corpo";

    const titulo = document.createElement("div");
    titulo.className = "br-aviso-titulo";
    titulo.textContent = aviso.titulo;

    const msg = document.createElement("div");
    msg.className = "br-aviso-msg";
    msg.textContent = aviso.mensagem;

    const fechar = document.createElement("button");
    fechar.type = "button";
    fechar.className = "br-aviso-fechar";
    fechar.textContent = "Fechar";
    fechar.setAttribute("aria-label", "Fechar aviso de novidade");

    corpo.append(titulo, msg);
    el.append(corpo, fechar);
    document.body.appendChild(el);

    let fechado = false;
    function fecharToast() {
      if (fechado) return;
      fechado = true;
      el.classList.remove("visivel");
      el.classList.add("saindo");
      setTimeout(() => { if (el && el.parentNode) el.parentNode.removeChild(el); }, FADE_MS);
    }

    fechar.addEventListener("click", fecharToast);
    requestAnimationFrame(() => el.classList.add("visivel"));
    setTimeout(fecharToast, aviso.tempo_segundos * 1000);
  }

  async function iniciar() {
    if (!isPaginaPrincipal()) return;
    if (!CFG.url || !CFG.key) return;
    try {
      const aviso = normalizarAviso(await rpc("copa_aviso_site", {}));
      if (!aviso || !dentroDaJanela(aviso) || visto(aviso.id)) return;
      setTimeout(() => criarToast(aviso), DEFAULT_DELAY_MS);
    } catch (e) {
      // Falha silenciosa: aviso não pode quebrar a página principal.
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();

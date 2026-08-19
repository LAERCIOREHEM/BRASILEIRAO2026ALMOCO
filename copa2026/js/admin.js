/* =========================================================================
   admin.js — Área do organizador (ligada ao Supabase)
   Tudo passa por funções 'copa_admin_*' no banco, que exigem a senha do
   organizador (validada no servidor). A chave pública sozinha não faz nada.
   ========================================================================= */
(function () {
  "use strict";

  const CFG = window.COPA_CFG || { url: "", key: "" };
  const $ = s => document.querySelector(s);
  let SENHA = null;

  async function rpc(fn, body) {
    const r = await fetch(`${CFG.url}/rest/v1/rpc/${fn}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "apikey": CFG.key, "Authorization": "Bearer " + CFG.key },
      body: JSON.stringify(body || {})
    });
    if (!r.ok) throw new Error("RPC " + fn + " HTTP " + r.status + ": " + (await r.text()));
    return r.json();
  }

  function pin6() { return String(Math.floor(100000 + Math.random() * 900000)); }
  function linkBase() { return location.href.replace(/admin\.html.*$/, "index.html"); }
  function msgWhats(nome, pin) {
    return "🏆 *Bolão Copa 2026*\n\nOi, " + nome + "! Seus dados de acesso:\n*PIN:* " + pin +
      "\n\nAcesse: " + linkBase() + "\nEntre com seu nome e esse PIN. Trava dos palpites: 10/06 às 23h59.";
  }
  function copiar(txt, btn) {
    navigator.clipboard.writeText(txt).then(() => {
      const a = btn.textContent; btn.textContent = "Copiado ✓"; setTimeout(() => btn.textContent = a, 1400);
    }).catch(() => alerta("Copie manualmente: " + txt, false));
  }
  function alerta(m, ok) { const e = $("#msg"); e.textContent = m; e.className = "msg " + (ok ? "ok" : "erro"); e.classList.remove("oculto"); setTimeout(() => e.classList.add("oculto"), 4000); }


  // ---------- aviso de novidade da página principal ----------
  function slugDataHoje() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dia = String(d.getDate()).padStart(2, "0");
    return `novidades-${y}-${m}-${dia}`;
  }

  function limparIdAviso(v) {
    return String(v || "")
      .trim()
      .toLowerCase()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80);
  }

  function setValor(id, valor) {
    const el = $(id);
    if (el) el.value = valor == null ? "" : valor;
  }

  function getValor(id) {
    const el = $(id);
    return el ? String(el.value || "").trim() : "";
  }

  function normalizarAviso(raw) {
    const aviso = raw && typeof raw === "object" ? raw : {};
    return {
      ativo: aviso.ativo === true,
      id: limparIdAviso(aviso.id || aviso.id_aviso || "") || slugDataHoje(),
      titulo: String(aviso.titulo || "🚀 Novidades no site").slice(0, 80),
      mensagem: String(aviso.mensagem || "").slice(0, 420),
      tempo_segundos: Math.min(15, Math.max(5, parseInt(aviso.tempo_segundos || aviso.tempo || 9, 10) || 9)),
      data_inicio: aviso.data_inicio || "",
      data_fim: aviso.data_fim || ""
    };
  }

  function preencherAviso(aviso) {
    const a = normalizarAviso(aviso);
    setValor("#aviso-ativo", a.ativo ? "true" : "false");
    setValor("#aviso-id", a.id);
    setValor("#aviso-titulo", a.titulo);
    setValor("#aviso-mensagem", a.mensagem);
    setValor("#aviso-tempo", a.tempo_segundos);
    setValor("#aviso-inicio", a.data_inicio || "");
    setValor("#aviso-fim", a.data_fim || "");
    atualizarPreviewAviso();
  }

  function atualizarPreviewAviso() {
    const box = $("#aviso-preview");
    if (!box) return;
    const ativo = getValor("#aviso-ativo") === "true";
    const id = limparIdAviso(getValor("#aviso-id")) || slugDataHoje();
    const titulo = getValor("#aviso-titulo") || "🚀 Novidades no site";
    const msg = getValor("#aviso-mensagem");
    const tempo = Math.min(15, Math.max(5, parseInt(getValor("#aviso-tempo") || "9", 10) || 9));
    const estado = ativo ? "<b>ATIVO</b>" : "<b>INATIVO</b>";
    box.innerHTML = "Status: " + estado + " · ID: <b>" + id + "</b> · tempo: <b>" + tempo + "s</b><br>" +
      "Prévia: <b>" + escapeHtml(titulo) + "</b>" + (msg ? " — " + escapeHtml(msg) : "");
  }

  function escapeHtml(txt) {
    return String(txt || "").replace(/[&<>'"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
  }

  async function carregarAvisoSite() {
    if (!$("#painel-aviso-site")) return;
    preencherAviso(null);
    try {
      const atual = await rpc("copa_admin_obter_aviso_site", { p_senha: SENHA });
      if (atual && atual.erro) throw new Error(atual.erro);
      if (atual) preencherAviso(atual);
    } catch (e) {
      const box = $("#aviso-preview");
      if (box) box.innerHTML = "Status: não consegui carregar o aviso. Confirme se o SQL do recurso já foi rodado no Supabase.";
    }
  }

  function lerFormularioAviso(forcarAtivo) {
    const id = limparIdAviso(getValor("#aviso-id")) || slugDataHoje();
    const titulo = getValor("#aviso-titulo") || "🚀 Novidades no site";
    const mensagem = getValor("#aviso-mensagem");
    const tempo = Math.min(15, Math.max(5, parseInt(getValor("#aviso-tempo") || "9", 10) || 9));
    const ativo = typeof forcarAtivo === "boolean" ? forcarAtivo : getValor("#aviso-ativo") === "true";
    if (ativo && !mensagem) throw new Error("Escreva a mensagem do aviso antes de ativar.");
    return {
      ativo,
      id,
      titulo: titulo.slice(0, 80),
      mensagem: mensagem.slice(0, 420),
      tempo_segundos: tempo,
      data_inicio: getValor("#aviso-inicio") || null,
      data_fim: getValor("#aviso-fim") || null,
      atualizado_em: new Date().toISOString()
    };
  }

  async function salvarAvisoSite(forcarAtivo) {
    let aviso;
    try { aviso = lerFormularioAviso(forcarAtivo); }
    catch (e) { alerta(e.message, false); return; }
    preencherAviso(aviso);
    let res;
    try { res = await rpc("copa_admin_salvar_aviso_site", { p_senha: SENHA, p_aviso: aviso }); }
    catch (e) { alerta("Não consegui salvar o aviso. Rode o SQL do recurso no Supabase e tente de novo.", false); return; }
    if (res === "OK" || (res && res.ok)) {
      alerta(aviso.ativo ? "Aviso salvo e ativo na página principal." : "Aviso salvo como inativo.", true);
      atualizarPreviewAviso();
    } else {
      alerta("Não consegui salvar o aviso.", false);
    }
  }

  // ---------- gate ----------
  async function tentaLogin(s, silencioso) {
    try {
      const ok = await rpc("copa_admin_login", { p_senha: s });
      if (ok === true) { SENHA = s; localStorage.setItem("copa_admin_senha", s); abrir(); return true; }
    } catch (e) {}
    if (!silencioso) { const e = $("#gate-erro"); e.textContent = "Senha incorreta."; e.classList.remove("oculto"); }
    return false;
  }
  function abrir() { $("#gate").style.display = "none"; $("#painel-admin").style.display = ""; carregar(); carregarAvisoSite(); }

  // ---------- carregar lista ----------
  async function carregar() {
    const tb = $("#lista"); tb.innerHTML = '<tr><td colspan="4" style="color:var(--cinza)">Carregando…</td></tr>';
    let data;
    try { data = await rpc("copa_admin_listar", { p_senha: SENHA }); }
    catch (e) { tb.innerHTML = '<tr><td colspan="4">Erro ao carregar.</td></tr>'; return; }
    if (data && data.erro) { sair(); return; }
    let LAC = {};
    try { (await rpc("copa_lacres", {})).forEach(r => LAC[r.nome] = { em: r.lacrado_em, vol: r.voluntario }); } catch (e) {}
    const fmtData = iso => new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    const lista = data.participantes || [];
    const completos = lista.filter(x => x.pct >= 100).length;
    $("#contador").textContent = lista.length + " participantes · " + completos + " completos (100%)";
    tb.innerHTML = "";
    lista.forEach(x => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td>' + x.nome + '</td>' +
        '<td><span class="rank-barra" style="display:inline-block;width:90px;vertical-align:middle"><span class="rank-fill" style="width:' + x.pct + '%"></span></span> ' +
        '<b style="color:' + (x.pct >= 100 ? "var(--verde)" : "var(--branco)") + '">' + x.pct + '%</b></td>' +
        '<td>' + (x.enviado
          ? (LAC[x.nome] && LAC[x.nome].em
              ? '<span class="tag ok">' + fmtData(LAC[x.nome].em) + (LAC[x.nome].vol ? ' 🔒' : ' ⏰') + '</span>'
              : '<span class="tag ok">enviou</span>')
          : '<span class="tag">vazio</span>') + '</td>' +
        '<td class="acoes-td"></td>';
      const td = tr.querySelector(".acoes-td");
      td.append(
        botao("Reset PIN", () => resetar(x.nome), "sec"),
        botao("Remover", () => remover(x.nome), "del")
      );
      tb.appendChild(tr);
    });
  }
  function botao(txt, fn, tipo) { const b = document.createElement("button"); b.textContent = txt; b.className = "mini " + (tipo || ""); b.onclick = fn; return b; }

  // ---------- adicionar (em lote) ----------
  async function adicionar() {
    const nomes = $("#nomes").value.split("\n").map(s => s.trim()).filter(Boolean);
    if (!nomes.length) return alerta("Digite ao menos um nome (um por linha).", false);
    const criados = [];
    for (const nome of nomes) {
      const pin = pin6();
      let res; try { res = await rpc("copa_admin_add", { p_senha: SENHA, p_nome: nome, p_pin: pin }); } catch (e) { res = "ERRO"; }
      criados.push({ nome, pin, res });
    }
    $("#nomes").value = "";
    mostrarPins(criados.filter(c => c.res === "OK"), criados.filter(c => c.res !== "OK"));
    carregar();
  }

  function mostrarPins(ok, falhas) {
    const box = $("#pin-box"); box.classList.remove("oculto");
    let html = "";
    if (ok.length) {
      html += "<h4>Novos acessos (envie por WhatsApp):</h4>";
      ok.forEach(c => {
        const id = "w_" + Math.random().toString(36).slice(2, 8);
        html += '<div class="pin-linha"><span><b>' + c.nome + '</b> — PIN <b class="pin-num">' + c.pin + '</b></span>' +
          '<button class="mini" data-msg="' + encodeURIComponent(msgWhats(c.nome, c.pin)) + '" id="' + id + '">WhatsApp</button></div>';
      });
      html += '<button class="mini" id="copiar-todos" style="margin-top:8px">Copiar todos (lista)</button>';
    }
    if (falhas.length) html += '<p class="msg erro" style="margin-top:10px">Não criados (já existem?): ' + falhas.map(f => f.nome).join(", ") + '</p>';
    box.innerHTML = html;
    box.querySelectorAll("button[data-msg]").forEach(b => b.onclick = () => copiar(decodeURIComponent(b.dataset.msg), b));
    const ct = $("#copiar-todos");
    if (ct) ct.onclick = () => copiar(ok.map(c => c.nome + ": PIN " + c.pin).join("\n"), ct);
  }

  async function resetar(nome) {
    if (!confirm("Gerar um novo PIN para " + nome + "? O antigo deixa de funcionar.")) return;
    const pin = pin6();
    let res; try { res = await rpc("copa_admin_reset", { p_senha: SENHA, p_nome: nome, p_pin: pin }); } catch (e) { res = "ERRO"; }
    if (res === "OK") { mostrarPins([{ nome, pin, res }], []); alerta("PIN de " + nome + " trocado.", true); }
    else alerta("Não consegui resetar (" + res + ").", false);
  }

  async function remover(nome) {
    if (!confirm("Remover " + nome + " definitivamente? Apaga também o palpite dele.")) return;
    let res; try { res = await rpc("copa_admin_remover", { p_senha: SENHA, p_nome: nome }); } catch (e) { res = "ERRO"; }
    if (res === "OK") { alerta(nome + " removido.", true); carregar(); }
    else alerta("Não consegui remover (" + res + ").", false);
  }

  async function trocarSenha() {
    const nova = $("#nova-senha").value.trim();
    if (nova.length < 4) return alerta("A nova senha precisa ter ao menos 4 caracteres.", false);
    let res; try { res = await rpc("copa_admin_trocar_senha", { p_senha: SENHA, p_nova: nova }); } catch (e) { res = "ERRO"; }
    if (res === "OK") { SENHA = nova; localStorage.setItem("copa_admin_senha", nova); $("#nova-senha").value = ""; alerta("Senha do administrador trocada.", true); }
    else alerta("Não consegui trocar (" + res + ").", false);
  }



  function sair() {
    localStorage.removeItem("copa_admin_senha"); SENHA = null;
    $("#painel-admin").style.display = "none"; $("#gate").style.display = "";
    const e = $("#gate-erro"); e.textContent = "Sessão encerrada ou senha alterada. Entre de novo."; e.classList.remove("oculto");
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#gate-btn").onclick = () => tentaLogin($("#gate-pass").value.trim(), false);
    $("#gate-pass").onkeydown = ev => { if (ev.key === "Enter") $("#gate-btn").click(); };
    $("#btn-add").onclick = adicionar;
    $("#btn-refresh").onclick = carregar;
    $("#btn-senha").onclick = trocarSenha;
    $("#btn-sair-admin").onclick = sair;
    const avisoSalvar = $("#aviso-salvar"); if (avisoSalvar) avisoSalvar.onclick = () => salvarAvisoSite();
    const avisoDesativar = $("#aviso-desativar"); if (avisoDesativar) avisoDesativar.onclick = () => salvarAvisoSite(false);
    ["#aviso-ativo", "#aviso-id", "#aviso-titulo", "#aviso-mensagem", "#aviso-tempo", "#aviso-inicio", "#aviso-fim"].forEach(sel => {
      const el = $(sel); if (el) { el.addEventListener("input", atualizarPreviewAviso); el.addEventListener("change", atualizarPreviewAviso); }
    });

    const guard = localStorage.getItem("copa_admin_senha");
    if (guard) tentaLogin(guard, true); else $("#gate-pass").focus();
  });
})();

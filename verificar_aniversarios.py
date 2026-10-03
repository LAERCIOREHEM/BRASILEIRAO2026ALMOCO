#!/usr/bin/env python3
"""
Script que verifica aniversariantes do dia no grupo Almoço de Sexta (membros.json).

E envia email via Resend.com com os aniversariantes do dia.

Roda 1x por dia (08:00 BRT = 11:00 UTC) pelo GitHub Actions.

Variáveis de ambiente esperadas (configuradas como secrets no GitHub):
- RESEND_API_KEY: chave da API do Resend (re_...)
- EMAIL_DESTINO: email pra receber o aviso
- Remetente fixo do projeto: 'Brasileirão 2026 Almoço <avisos@brasileirao2026almoco.com.br>'
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from urllib.parse import quote


FUSO_BRASILIA = timezone(timedelta(hours=-3))
DEFAULT_EMAIL_SENDER = "Brasileirão 2026 Almoço <avisos@brasileirao2026almoco.com.br>"


def agora_brasilia():
    return datetime.now(FUSO_BRASILIA)


def ler_arquivo_membros(nome_arquivo):
    """Le arquivo JSON de membros (generico para os dois grupos)."""
    if not os.path.exists(nome_arquivo):
        print(f"AVISO: {nome_arquivo} nao encontrado.")
        return []
    try:
        with open(nome_arquivo, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("membros", [])
    except Exception as e:
        print(f"Erro ao ler {nome_arquivo}: {e}")
        return []


def aniversariantes_de_hoje(membros):
    """Filtra membros que fazem aniversario HOJE em Brasilia."""
    hoje = agora_brasilia()
    dia_hoje = hoje.day
    mes_hoje = hoje.month

    resultado = []
    for m in membros:
        aniv = m.get("aniversario")
        if not aniv:
            continue
        if aniv.get("dia") == dia_hoje and aniv.get("mes") == mes_hoje:
            resultado.append(m)
    return resultado


def link_whatsapp(nome):
    """Gera link wa.me com mensagem pre-pronta."""
    msg = f"Parabens, {nome}! Tudo de bom no seu dia!"
    return f"https://wa.me/?text={quote(msg)}"


def montar_secao_grupo(titulo_grupo, aniversariantes, cor_borda):
    """Monta a secao de um grupo dentro do email."""
    if not aniversariantes:
        return ""

    html = f"""
    <div style="margin-bottom: 24px;">
      <h2 style="font-size: 14px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.8px; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 2px solid {cor_borda};">{titulo_grupo} - {len(aniversariantes)} aniversariante(s)</h2>
"""
    for p in aniversariantes:
        nome = p.get("nome", "?")
        link = link_whatsapp(nome)
        html += f"""
      <div style="background:#fdf2f8; border:1px solid #f9a8d4; border-radius:10px; padding:14px; margin-bottom:8px;">
        <div style="font-size:17px; font-weight:600; color:#db2777; margin-bottom:8px;">{nome}</div>
        <a href="{link}" style="display:inline-block; background:#22c55e; color:white; padding:8px 16px; border-radius:8px; text-decoration:none; font-weight:500; font-size:13px;">
          Mandar parabens no WhatsApp
        </a>
      </div>
"""
    html += "    </div>"
    return html


def montar_html_email(aniv_almoco):
    """Monta corpo HTML do email com os dois grupos."""
    total = len(aniv_almoco)
    titulo = "Aniversariante de hoje!" if total == 1 else f"{total} aniversariantes de hoje!"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background:#f5f5f5; padding:20px; margin:0;">
  <div style="max-width:580px; margin:0 auto; background:white; border-radius:12px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <h1 style="font-size:22px; margin:0 0 6px; color:#1f2937;">&#127874; {titulo}</h1>
    <p style="font-size:13px; color:#9ca3af; margin:0 0 20px;">Aniversariantes do dia nos seus grupos</p>
"""

    if aniv_almoco:
        html += montar_secao_grupo("Almoco de Sexta", aniv_almoco, "#f472b6")


    html += """
    <p style="font-size:12px; color:#9ca3af; margin:20px 0 0; padding-top:16px; border-top:1px solid #e5e7eb;">
      Clique no botao e o WhatsApp abrira com a mensagem ja pronta. Escolha o grupo certo e envie.
    </p>
    <p style="font-size:11px; color:#d1d5db; margin:12px 0 0; text-align:center;">
      <a href="https://brasileirao2026almoco.com.br" style="color:#9ca3af;">brasileirao2026almoco.com.br</a>
    </p>
  </div>
</body>
</html>"""
    return html


def enviar_email_resend(api_key, remetente, destinatario, assunto, html_corpo):
    """Envia email via API do Resend."""
    payload = {
        "from": remetente,
        "to": [destinatario],
        "subject": assunto,
        "html": html_corpo,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # User-Agent explicito: o Cloudflare que protege a API do Resend
            # bloqueia o User-Agent padrao do urllib (erro 403 / code 1010).
            "User-Agent": "BolaoBrasileirao2026/1.0 (+https://brasileirao2026almoco.com.br)",
            "Accept": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
        status = resp.getcode()
        return status, body


def main():
    inicio = agora_brasilia()
    print("=" * 70)
    print("Verificacao de aniversariantes (Almoco de Sexta)")
    print("=" * 70)
    print(f"Inicio: {inicio.strftime('%d/%m/%Y %H:%M:%S BRT')}")
    print()

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    destino = os.environ.get("EMAIL_DESTINO", "").strip()
    remetente = DEFAULT_EMAIL_SENDER

    if not api_key:
        print("ERRO: variavel RESEND_API_KEY nao configurada.")
        sys.exit(1)
    if not destino:
        print("ERRO: variavel EMAIL_DESTINO nao configurada.")
        sys.exit(1)

    print(f"Remetente: {remetente}")
    print(f"Destinatario: {destino}")
    print()

    membros_almoco = ler_arquivo_membros("membros.json")

    print(f"Membros Almoco: {len(membros_almoco)}")
    print()

    aniv_almoco = aniversariantes_de_hoje(membros_almoco)

    print(f"Aniversariantes Almoco hoje: {len(aniv_almoco)}")
    for a in aniv_almoco:
        print(f"  - {a.get('nome')}")
    total = len(aniv_almoco)
    if total == 0:
        print("\nNenhum aniversariante hoje. Nada a enviar.")
        return

    print("\nMontando email...")
    html_email = montar_html_email(aniv_almoco)

    todos_nomes = [a.get("nome", "?") for a in aniv_almoco]
    nomes = ", ".join(todos_nomes)
    assunto = f"Hoje: aniversario de {nomes}"

    print(f"Enviando email para {destino}...")
    try:
        status, body = enviar_email_resend(api_key, remetente, destino, assunto, html_email)
        print(f"Status HTTP: {status}")
        print(f"Resposta: {body[:500]}")
        if 200 <= status < 300:
            print("\nEmail enviado com sucesso!")
        else:
            print(f"\nERRO: status {status}")
            sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        print(f"ERRO HTTP {e.code}")
        print(f"Cabecalhos da resposta: {dict(e.headers)}")
        print(f"Corpo da resposta: {body[:800]}")
        # Dica de diagnostico
        if "1010" in body or e.code == 403:
            print("\nDICA: erro 403/1010 costuma ser bloqueio do Cloudflare.")
            print("Verifique se o User-Agent esta presente na requisicao.")
        sys.exit(1)
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

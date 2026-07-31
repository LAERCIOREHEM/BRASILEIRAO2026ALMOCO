#!/usr/bin/env python3
"""Envia um e-mail consolidado com alertas vencidos dos Desafios na Mesa.

O workflow consulta apenas uma RPC protegida para service_role. Os registros só
são marcados como enviados depois que o provedor confirma o e-mail, permitindo
nova tentativa automática em caso de falha.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


FUSO_BRASILIA = timezone(timedelta(hours=-3))
SITE_URL = "https://brasileirao2026almoco.com.br/desafios-mesa.html"


def agora_brasilia() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def formatar_data(valor: str | None) -> str:
    if not valor:
        return "—"
    try:
        return datetime.strptime(valor[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def request_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 25) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body.strip() else None


def consultar_alertas(supabase_url: str, service_key: str, instante: datetime) -> list[dict[str, Any]]:
    data = request_json(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/br_desafios_alertas_pendentes",
        {"p_agora": instante.astimezone(timezone.utc).isoformat()},
        {"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    return data if isinstance(data, list) else []


def marcar_enviados(supabase_url: str, service_key: str, ids: list[str], instante: datetime) -> int:
    data = request_json(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/br_desafios_marcar_alertas_enviados",
        {"p_ids": ids, "p_enviado_em": instante.astimezone(timezone.utc).isoformat()},
        {"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    return int(data or 0)


def montar_html(alertas: list[dict[str, Any]], instante: datetime) -> str:
    cards: list[str] = []
    for item in alertas:
        titulo = html.escape(str(item.get("titulo") or "Desafio"))
        participante_a = html.escape(str(item.get("participante_a_nome") or "Participante A"))
        participante_b = html.escape(str(item.get("participante_b_nome") or "Participante B"))
        descricao = html.escape(str(item.get("descricao") or ""))
        criterio = html.escape(str(item.get("criterio_resultado") or ""))
        compromisso = html.escape(str(item.get("compromisso_simbolico") or ""))
        prazo = formatar_data(str(item.get("prazo") or ""))
        cards.append(
            f"""
            <section style="border:1px solid #d9e6c0;border-radius:14px;padding:16px;margin:0 0 14px;background:#f8fbf3;">
              <div style="font-size:12px;font-weight:800;color:#56820f;text-transform:uppercase;letter-spacing:.06em;">Prazo: {prazo}</div>
              <h2 style="font-size:19px;color:#17220b;margin:5px 0 7px;">{titulo}</h2>
              <p style="font-size:14px;font-weight:700;color:#334155;margin:0 0 8px;">{participante_a} × {participante_b}</p>
              <p style="font-size:13px;line-height:1.5;color:#475569;margin:0 0 8px;">{descricao}</p>
              <p style="font-size:12px;line-height:1.5;color:#64748b;margin:0 0 5px;"><strong>Critério:</strong> {criterio}</p>
              <p style="font-size:12px;line-height:1.5;color:#64748b;margin:0;"><strong>Compromisso simbólico:</strong> {compromisso}</p>
            </section>"""
        )

    total = len(alertas)
    data_execucao = instante.strftime("%d/%m/%Y às %H:%M BRT")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:22px;background:#eef2f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
  <main style="max-width:620px;margin:0 auto;background:#fff;border-radius:18px;padding:24px;box-shadow:0 4px 18px rgba(15,23,42,.08);">
    <h1 style="font-size:23px;color:#17220b;margin:0 0 6px;">🤝 Desafios na Mesa</h1>
    <p style="font-size:13px;color:#64748b;margin:0 0 20px;">{total} lembrete{'s' if total != 1 else ''} programado{'s' if total != 1 else ''} · {data_execucao}</p>
    {''.join(cards)}
    <a href="{SITE_URL}" style="display:inline-block;background:#84cc16;color:#17220b;text-decoration:none;font-weight:800;border-radius:10px;padding:11px 17px;">Abrir os desafios</a>
    <p style="font-size:11px;color:#94a3b8;margin:18px 0 0;border-top:1px solid #e2e8f0;padding-top:14px;">Registro recreativo privado do Almoço de Sexta. Sem dinheiro, itens restritos ou jogos de azar.</p>
  </main>
</body></html>"""


def enviar_email(api_key: str, remetente: str, destino: str, assunto: str, corpo: str) -> dict[str, Any]:
    result = request_json(
        "https://api.resend.com/emails",
        {"from": remetente, "to": [destino], "subject": assunto, "html": corpo},
        {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "BrasileiraoAlmocoDesafios/1.0 (+https://brasileirao2026almoco.com.br)",
        },
    )
    return result if isinstance(result, dict) else {}


def self_test() -> None:
    sample = [{
        "id": "00000000-0000-0000-0000-000000000001",
        "titulo": "Melhor colocação",
        "participante_a_nome": "Ana & Cia",
        "participante_b_nome": "Bruno <teste>",
        "descricao": "Terminar melhor na classificação.",
        "criterio_resultado": "Posição oficial ao fim da competição.",
        "compromisso_simbolico": "Um almoço",
        "prazo": "2026-12-06",
    }]
    body = montar_html(sample, datetime(2026, 7, 31, 8, 0, tzinfo=FUSO_BRASILIA))
    assert "Ana &amp; Cia" in body
    assert "Bruno &lt;teste&gt;" in body
    assert "06/12/2026" in body
    assert SITE_URL in body
    assert formatar_data("valor-invalido") == "—"
    print("OK: montagem, escape de HTML, datas e link validados.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    required = {
        "SUPABASE_URL": os.getenv("SUPABASE_URL", "").strip(),
        "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        "RESEND_API_KEY": os.getenv("RESEND_API_KEY", "").strip(),
        "EMAIL_DESTINO": os.getenv("EMAIL_DESTINO", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print("ERRO: secrets ausentes: " + ", ".join(missing))
        return 1

    remetente = os.getenv("EMAIL_REMETENTE", "onboarding@resend.dev").strip()
    instante = agora_brasilia()
    try:
        alertas = consultar_alertas(required["SUPABASE_URL"], required["SUPABASE_SERVICE_ROLE_KEY"], instante)
        print(f"Alertas pendentes: {len(alertas)}")
        if not alertas:
            print("Nenhum alerta a enviar.")
            return 0

        corpo = montar_html(alertas, instante)
        assunto = f"Desafios na Mesa: {len(alertas)} lembrete{'s' if len(alertas) != 1 else ''}"
        response = enviar_email(required["RESEND_API_KEY"], remetente, required["EMAIL_DESTINO"], assunto, corpo)
        if not response.get("id"):
            raise RuntimeError("O provedor não confirmou o identificador do e-mail.")

        ids = [str(item["id"]) for item in alertas if item.get("id")]
        total = marcar_enviados(required["SUPABASE_URL"], required["SUPABASE_SERVICE_ROLE_KEY"], ids, instante)
        if total != len(ids):
            raise RuntimeError(f"E-mail enviado, mas apenas {total}/{len(ids)} alertas foram confirmados no banco.")
        print(f"E-mail {response['id']} enviado e {total} alerta(s) confirmado(s).")
        return 0
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace") if hasattr(error, "read") else ""
        print(f"ERRO HTTP {error.code}: {body[:800]}")
        return 1
    except Exception as error:
        print(f"ERRO: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

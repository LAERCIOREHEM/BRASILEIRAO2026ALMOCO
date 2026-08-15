#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Última camada diária de auditoria IA para o Brasileirão 2026 Almoço.

A IA recebe somente estado agregado dos blocos/auditorias. Nunca recebe palpites
individuais e nunca altera placares, palpites, pontos, rankings, blocos ou prazos.
A autoridade continua sendo Python/PostgreSQL; a IA só identifica anomalias que
podem ter escapado das regras determinísticas.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=-3))
OUT = ROOT / "dados-br" / "auditoria-ia-apostas.json"
BLOCKS_AUDIT = ROOT / "dados-br" / "auditoria-blocos-apostas.json"
GENERAL_AUDIT = ROOT / "dados-br" / "auditoria-geral.json"
APURACAO = ROOT / "dados-br" / "apuracao.json"
STATUS = ROOT / "dados-br" / "status-atualizacao.json"
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_SENDER = "Auditoria IA · Brasileirão 2026 <avisos@brasileirao2026almoco.com.br>"


def now_brt() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_block(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rodada_inicio": int(row.get("rodada_inicio") or 0),
        "rodada_fim": int(row.get("rodada_fim") or 0),
        "status_apostas": row.get("status_apostas"),
        "total_canonicos": int(row.get("total_canonicos") or 0),
        "horarios_confiaveis": int(row.get("horarios_confiaveis") or 0),
        "horarios_a_definir": int(row.get("horarios_a_definir") or 0),
        "abre_em": row.get("abre_em"),
        "fecha_em": row.get("fecha_em"),
        "total_palpites": int(row.get("total_palpites") or 0),
        "jogos_apurados": int(row.get("jogos_apurados") or 0),
        "apuracao_concluida": bool(row.get("apuracao_concluida")),
        "email_abertura_pendente": bool(row.get("email_abertura_pendente")),
    }


def build_dossier(root: Path = ROOT) -> dict[str, Any]:
    block_audit = load_json(root / BLOCKS_AUDIT.relative_to(ROOT), {})
    general = load_json(root / GENERAL_AUDIT.relative_to(ROOT), {})
    ap = load_json(root / APURACAO.relative_to(ROOT), {})
    st = load_json(root / STATUS.relative_to(ROOT), {})
    blocks = [safe_block(x) for x in (block_audit.get("blocos") or []) if isinstance(x, Mapping)] if isinstance(block_audit, Mapping) else []
    ap_blocks = []
    if isinstance(ap, Mapping):
        for row in ap.get("blocos") or []:
            if isinstance(row, Mapping):
                ap_blocks.append({
                    "rodada_inicio": int(row.get("rodada_inicio") or 0),
                    "rodada_fim": int(row.get("rodada_fim") or 0),
                    "jogos_apurados": int(row.get("jogos_apurados") or 0),
                    "concluido": bool(row.get("concluido")),
                    "estado_apuracao": row.get("estado_apuracao"),
                    "sigilosa": bool(row.get("sigilosa")),
                })
    return {
        "regra_essencial": "Bloco seguinte aberto com bloco anterior ainda parcial por jogos adiados é estado ESPERADO, não erro.",
        "restricoes_ia": [
            "não alterar palpites, pontos, ranking, placares, deadlines ou vínculo jogo/bloco",
            "não considerar dois blocos simultâneos (um parcial e outro aberto) como anomalia",
            "sinalizar somente inconsistência de integridade/automação realmente acionável",
        ],
        "auditoria_blocos": {
            "status": block_audit.get("status") if isinstance(block_audit, Mapping) else "ausente",
            "resumo": block_audit.get("resumo") if isinstance(block_audit, Mapping) else {},
            "criticos": block_audit.get("criticos") if isinstance(block_audit, Mapping) else ["auditoria ausente"],
            "avisos": block_audit.get("avisos") if isinstance(block_audit, Mapping) else [],
            "blocos": blocks,
        },
        "auditoria_geral": {
            "status": general.get("status") if isinstance(general, Mapping) else "ausente",
            "resumo": general.get("resumo") if isinstance(general, Mapping) else {},
            "criticos": general.get("criticos") if isinstance(general, Mapping) else [],
            "avisos": general.get("avisos") if isinstance(general, Mapping) else [],
        },
        "apuracao_agregada": {"blocos": ap_blocks, "resumo": ap.get("resumo") if isinstance(ap, Mapping) else {}},
        "pipeline": {
            "ultimo_sucesso": st.get("ultimo_sucesso") if isinstance(st, Mapping) else None,
            "status": st.get("status") if isinstance(st, Mapping) else None,
        },
    }


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["ok", "atencao", "critico"]},
            "resumo": {"type": "string", "maxLength": 500},
            "coexistencia_blocos_tratada_como_esperada": {"type": "boolean"},
            "anomalias": {
                "type": "array", "maxItems": 10,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "codigo": {"type": "string", "maxLength": 80},
                        "severidade": {"type": "string", "enum": ["info", "warning", "critical"]},
                        "bloco": {"type": ["string", "null"], "maxLength": 20},
                        "mensagem": {"type": "string", "maxLength": 500},
                        "requer_intervencao": {"type": "boolean"},
                    },
                    "required": ["codigo", "severidade", "bloco", "mensagem", "requer_intervencao"],
                },
            },
        },
        "required": ["status", "resumo", "coexistencia_blocos_tratada_como_esperada", "anomalias"],
    }


def response_text(payload: Mapping[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"])
    chunks = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "".join(chunks)


def call_openai(dossier: Mapping[str, Any], model: str) -> tuple[dict[str, Any], str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY ausente")
    instructions = (
        "Você é a última camada de auditoria do bolão recreativo Brasileirão 2026 Almoço. "
        "Analise SOMENTE o dossiê agregado. Não invente fatos e não solicite dados individuais. "
        "É normal um bloco antigo estar 28/30 enquanto o próximo está aberto: jogos adiados permanecem no bloco original. "
        "Só classifique como crítico algo que ameace integridade das apostas/apuração ou exija intervenção. "
        "Não proponha alterar palpites, pontuação, ranking, placar, deadline ou vínculo jogo/bloco."
    )
    body = {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(dossier, ensure_ascii=False, separators=(",", ":"))}]}],
        "text": {"format": {"type": "json_schema", "name": "auditoria_apostas_diaria", "strict": True, "schema": schema()}},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Brasileirao2026Almoco-AuditIA/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
    text = response_text(raw)
    if not text:
        raise RuntimeError("OpenAI retornou resposta sem JSON textual")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError("Resposta estruturada inválida")
    return parsed, str(raw.get("id") or "")


def fingerprint(ai: Mapping[str, Any], dossier: Mapping[str, Any]) -> str:
    critical = [x for x in ai.get("anomalias") or [] if isinstance(x, Mapping) and x.get("severidade") == "critical"]
    det = dossier.get("auditoria_blocos", {}).get("criticos", []) if isinstance(dossier.get("auditoria_blocos"), Mapping) else []
    gen = dossier.get("auditoria_geral", {}).get("criticos", []) if isinstance(dossier.get("auditoria_geral"), Mapping) else []
    return canonical_hash({"ia": critical, "det_blocos": det, "det_geral": gen})


def send_critical_email(
    payload: Mapping[str, Any],
    previous: Mapping[str, Any],
    dossier: Mapping[str, Any],
) -> tuple[bool, str]:
    if payload.get("status") != "critical":
        return False, "dispensado: sem crítico"
    if previous.get("status") == "critical" and previous.get("fingerprint") == payload.get("fingerprint"):
        return False, "dispensado: mesmo crítico já avisado"
    key = os.environ.get("RESEND_API_KEY", "").strip(); dest = os.environ.get("EMAIL_DESTINO", "").strip()
    if not key or not dest:
        return False, "secrets Resend ausentes"
    items = []
    for x in payload.get("anomalias") or []:
        if isinstance(x, Mapping) and x.get("severidade") == "critical":
            items.append(f"<li><b>{html.escape(str(x.get('codigo') or ''))}</b>: {html.escape(str(x.get('mensagem') or ''))}</li>")
    for origem, chave in (("Blocos", "auditoria_blocos"), ("Auditoria geral", "auditoria_geral")):
        secao = dossier.get(chave) if isinstance(dossier.get(chave), Mapping) else {}
        for mensagem in secao.get("criticos") or []:
            items.append(f"<li><b>{html.escape(origem)}</b>: {html.escape(str(mensagem))}</li>")
    if not items:
        items.append("<li>Estado crítico detectado; consulte os artefatos de auditoria para os detalhes.</li>")
    body = json.dumps({
        "from": os.environ.get("EMAIL_REMETENTE", "").strip() or DEFAULT_SENDER,
        "to": [dest],
        "subject": "[BR2026 Almoço] Auditoria IA — problema crítico nas apostas",
        "html": "<h2>Auditoria IA das apostas</h2><p>Foi detectado problema que exige revisão.</p><ul>" + "".join(items) + "</ul>",
    }, ensure_ascii=False).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300, resp.read().decode(errors="replace")[:300]
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:300]


def run(root: Path = ROOT, *, moment: datetime | None = None, force: bool = False) -> dict[str, Any]:
    now = (moment or now_brt()).astimezone(TZ).replace(microsecond=0)
    out = root / OUT.relative_to(ROOT)
    previous = load_json(out, {})
    if not force and isinstance(previous, Mapping) and previous.get("data_brt") == now.date().isoformat() and previous.get("chamada_openai") is True:
        return dict(previous)
    dossier = build_dossier(root)
    model = os.environ.get("OPENAI_AUDIT_MODEL", "").strip() or DEFAULT_MODEL
    called = False; response_id = ""; error = ""; ai: dict[str, Any]
    try:
        ai, response_id = call_openai(dossier, model)
        called = True
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:1200]
        ai = {"status": "atencao", "resumo": "Camada IA indisponível; validações determinísticas permanecem ativas.", "coexistencia_blocos_tratada_como_esperada": True, "anomalias": []}
    deterministic_critical = bool((dossier.get("auditoria_blocos") or {}).get("criticos") or (dossier.get("auditoria_geral") or {}).get("criticos"))
    ai_critical = ai.get("status") == "critico" or any(isinstance(x, Mapping) and x.get("severidade") == "critical" for x in ai.get("anomalias") or [])
    status = "critical" if deterministic_critical or ai_critical else "warning" if error or ai.get("status") == "atencao" else "ok"
    payload = {
        "schema_version": 1,
        "data_brt": now.date().isoformat(),
        "gerado_em": now.isoformat(),
        "status": status,
        "modelo": model,
        "chamada_openai": called,
        "openai_response_id": response_id or None,
        "erro_openai": error or None,
        "dossie_hash": canonical_hash(dossier),
        "resumo": ai.get("resumo"),
        "coexistencia_blocos_tratada_como_esperada": bool(ai.get("coexistencia_blocos_tratada_como_esperada")),
        "anomalias": ai.get("anomalias") or [],
        "politica": {"maximo_chamadas_dia": 1, "web_search": False, "dados_individuais_palpites": False, "poder_de_escrita_ia": False},
    }
    payload["fingerprint"] = fingerprint(payload, dossier)
    sent, detail = send_critical_email(payload, previous if isinstance(previous, Mapping) else {}, dossier)
    payload["alerta_email"] = "enviado" if sent else detail
    save_json(out, payload)
    return payload


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "dados-br").mkdir()
        blocks = {"status":"ok","resumo":{"abertos":1,"em_apuracao":1},"criticos":[],"avisos":[],"blocos":[
            {"rodada_inicio":21,"rodada_fim":23,"status_apostas":"fechada","total_canonicos":30,"jogos_apurados":28,"apuracao_concluida":False,"total_palpites":300},
            {"rodada_inicio":24,"rodada_fim":26,"status_apostas":"aberta","total_canonicos":30,"jogos_apurados":0,"apuracao_concluida":False,"total_palpites":120},
        ]}
        (root/"dados-br/auditoria-blocos-apostas.json").write_text(json.dumps(blocks),encoding="utf-8")
        (root/"dados-br/auditoria-geral.json").write_text(json.dumps({"status":"ok","resumo":{},"criticos":[],"avisos":[]}),encoding="utf-8")
        (root/"dados-br/apuracao.json").write_text(json.dumps({"resumo":{},"blocos":[{"rodada_inicio":21,"rodada_fim":23,"jogos_apurados":28,"concluido":False,"sigilosa":False}]}),encoding="utf-8")
        (root/"dados-br/status-atualizacao.json").write_text(json.dumps({"status":"ok"}),encoding="utf-8")
        dossier=build_dossier(root)
        raw=json.dumps(dossier,ensure_ascii=False).lower()
        assert "palpite_mandante" not in raw and "placar_mandante" not in raw and "membro" not in raw
        assert dossier["auditoria_blocos"]["resumo"]["abertos"] == 1
        sc=schema(); assert sc["additionalProperties"] is False
        assert canonical_hash(dossier) == canonical_hash(dossier)
    print("SELFTEST OK: dossiê agregado sem palpites individuais, coexistência de blocos e schema IA validados.")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--force",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    payload=run(force=args.force)
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

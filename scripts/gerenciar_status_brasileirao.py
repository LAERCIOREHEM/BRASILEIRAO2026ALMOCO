#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o estado operacional do Brasileirão e envia alertas privados.

O arquivo público contém somente mensagens editoriais seguras. Detalhes técnicos,
link do run e fontes de fallback são exibidos no painel administrativo.

A notificação usa RESEND_API_KEY e EMAIL_DESTINO. O remetente operacional
é fixado em avisos@brasileirao2026almoco.com.br para não depender de secret
de remetente e para impedir o uso acidental de endereços de outros projetos.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dados-br" / "status-atualizacao.json"
TZ = timezone(timedelta(hours=-3))
FAILURE_ALERT_COOLDOWN = timedelta(hours=6)
DEFAULT_EMAIL_SENDER = "Avisos · Brasileirão 2026 <avisos@brasileirao2026almoco.com.br>"
FAILURE_STATUSES = frozenset({"preservado", "erro"})
STATUS_REFRESH_INTERVAL = timedelta(hours=1)
SNAPSHOT_FILES = (
    ROOT / "tabela.json",
    ROOT / "resultados.json",
    ROOT / "jogos.json",
    ROOT / "espn_eventos.json",
)


def now_brt() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def snapshot_hash() -> str:
    digest = hashlib.sha256()
    for path in SNAPSHOT_FILES:
        digest.update(path.name.encode("utf-8"))
        if not path.exists():
            digest.update(b"<ausente>")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Timestamps não alteram o estado esportivo.
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in {"atualizado_em", "atualizado_em_br"}}
            raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except Exception:  # noqa: BLE001
            raw = path.read_bytes()
        digest.update(raw)
    return digest.hexdigest()


def parse_fallbacks(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def status_from_env(previous: dict[str, Any], *, force_error: bool = False) -> dict[str, Any]:
    current = now_brt()
    raw_status = "erro" if force_error else os.environ.get("BR_STATUS", "ok").strip().lower()
    if raw_status not in {"ok", "aviso", "preservado", "erro"}:
        raw_status = "erro"
    motivo = " ".join(os.environ.get("BR_MOTIVO", "").splitlines()).strip()
    fallbacks = parse_fallbacks(os.environ.get("BR_FALLBACKS", "[]"))
    tentativas = int(os.environ.get("BR_TENTATIVAS", "0") or 0)
    sincronizado = os.environ.get("BR_SINCRONIZADO", "false").strip().lower() == "true"
    current_snapshot_hash = snapshot_hash()

    # Uma verificação normal sem mudança esportiva não precisa gerar commit e
    # deploy apenas para trocar horário. O status volta a mudar em novo snapshot,
    # fallback, preservação, erro ou recuperação.
    if (
        raw_status == "ok"
        and str(previous.get("status") or "") == "ok"
        and str(previous.get("snapshot_hash") or "") == current_snapshot_hash
        and int(previous.get("schema_version") or 0) == 1
    ):
        return dict(previous)

    if raw_status == "ok":
        nivel = "normal"
        admin = motivo or "Atualização concluída e auditada sem uso de fonte complementar."
        public = ""
        show_public = False
    elif raw_status == "aviso":
        nivel = "aviso"
        admin = motivo or "Atualização concluída com fonte complementar auditada."
        public = "Dados atualizados e conferidos com fonte oficial complementar."
        show_public = False
    elif raw_status == "preservado":
        nivel = "aviso"
        admin = motivo or "Não foi possível atualizar com segurança; o último snapshot íntegro foi preservado."
        public = "Atualização em verificação: estamos exibindo o último levantamento confiável enquanto as fontes de dados são conferidas."
        show_public = True
    else:
        nivel = "critico"
        admin = motivo or "Falha no workflow Atualizar Brasileirão. Verifique o run no GitHub Actions."
        public = "Atualização temporariamente indisponível. Estamos exibindo o último levantamento confiável."
        show_public = True

    last_success = previous.get("ultimo_sucesso") or ""
    if sincronizado and raw_status in {"ok", "aviso"}:
        last_success = current.isoformat()

    explicit_run_url = os.environ.get("BR_RUN_URL", "").strip()
    run_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("BR_SOURCE_RUN_ID", "").strip() or os.environ.get("GITHUB_RUN_ID", "").strip()
    if explicit_run_url:
        run_url = explicit_run_url
    elif repo and run_id:
        run_url = f"{run_url}/{repo}/actions/runs/{run_id}"
    else:
        run_url = previous.get("run_url") or ""

    workflow_name = os.environ.get("BR_WORKFLOW", "Atualizar Brasileirao (ESPN)").strip() or "Atualizar Brasileirao (ESPN)"
    site_name = os.environ.get("BR_SITE", "Brasileirão 2026 Almoço").strip() or "Brasileirão 2026 Almoço"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "site": site_name,
        "workflow": workflow_name,
        "status": raw_status,
        "status_anterior": str(previous.get("status") or ""),
        "nivel": nivel,
        "ultima_tentativa": current.isoformat(),
        "ultimo_sucesso": last_success,
        "ultimo_snapshot_valido": last_success or previous.get("ultimo_snapshot_valido") or "",
        "snapshot_hash": current_snapshot_hash,
        "fonte_principal": "ESPN",
        "fontes_complementares": sorted({str(item.get("fonte") or "") for item in fallbacks if item.get("fonte")}),
        "fallbacks": fallbacks,
        "tentativas": tentativas,
        "sincronizado": sincronizado,
        "mensagem_admin": admin,
        "mensagem_publica": public,
        "mostrar_publico": show_public,
        "run_url": run_url,
        "run_id": run_id,
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "branch": os.environ.get("GITHUB_REF_NAME", "main"),
    }
    fingerprint_source = json.dumps(
        {
            "workflow": workflow_name,
            "status": raw_status,
            "mensagem": admin,
            "fallbacks": [(x.get("event_id"), x.get("fonte"), x.get("placar")) for x in fallbacks],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    payload["fingerprint"] = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    payload["ultimo_alerta_em"] = previous.get("ultimo_alerta_em") or ""
    payload["ultimo_alerta_fingerprint"] = previous.get("ultimo_alerta_fingerprint") or ""

    # Evita um commit/deploy a cada acionamento quando a mesma anomalia segue
    # ativa. A mensagem pública e o alerta já publicados permanecem válidos; o
    # status é renovado em até uma hora, ou imediatamente quando muda o estado,
    # o snapshot, a mensagem, o fallback ou ocorre recuperação.
    previous_attempt = parse_dt(previous.get("ultima_tentativa"))
    if (
        raw_status != "ok"
        and str(previous.get("status") or "") == raw_status
        and str(previous.get("snapshot_hash") or "") == current_snapshot_hash
        and str(previous.get("fingerprint") or "") == payload["fingerprint"]
        and previous_attempt is not None
        and current - previous_attempt < STATUS_REFRESH_INTERVAL
    ):
        return dict(previous)
    return payload


def should_notify(payload: dict[str, Any]) -> bool:
    """Autoriza e-mail somente quando houve falha operacional real.

    ``aviso`` representa atualização íntegra com fonte complementar auditada e
    nunca gera e-mail. ``ok`` e recuperação também não geram e-mail.
    ``preservado`` é tratado como falha de atualização, pois o sistema não
    conseguiu publicar um snapshot novo com segurança. Alertas idênticos de
    falha respeitam o cooldown para evitar enxurrada de mensagens.
    """
    status = str(payload.get("status") or "").strip().lower()
    if status not in FAILURE_STATUSES:
        return False
    previous_fp = str(payload.get("ultimo_alerta_fingerprint") or "")
    current_fp = str(payload.get("fingerprint") or "")
    if current_fp != previous_fp:
        return True
    last = parse_dt(payload.get("ultimo_alerta_em"))
    return last is None or now_brt() - last >= FAILURE_ALERT_COOLDOWN


def failure_label(payload: dict[str, Any]) -> str:
    return "SNAPSHOT PRESERVADO" if str(payload.get("status") or "").lower() == "preservado" else "ERRO"


def email_html(payload: dict[str, Any]) -> str:
    status = failure_label(payload)
    fallback_lines = "".join(
        "<li>"
        + html.escape(str(item.get("jogo") or item.get("event_id") or "Jogo"))
        + " — "
        + html.escape(str(item.get("fonte") or "fonte complementar"))
        + (" — " + html.escape(str(item.get("placar"))) if item.get("placar") else "")
        + "</li>"
        for item in payload.get("fallbacks") or []
    )
    fallbacks = f"<h3>Fallbacks</h3><ul>{fallback_lines}</ul>" if fallback_lines else ""
    run_url = html.escape(str(payload.get("run_url") or ""), quote=True)
    run_link = f'<p><a href="{run_url}">Abrir execução no GitHub Actions</a></p>' if run_url else ""
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#172033">
      <h2>Brasileirão 2026 Almoço — {html.escape(status)}</h2>
      <p><strong>{html.escape(str(payload.get('mensagem_admin') or ''))}</strong></p>
      <p>Última tentativa: {html.escape(str(payload.get('ultima_tentativa') or ''))}<br>
         Último sucesso: {html.escape(str(payload.get('ultimo_sucesso') or 'não registrado'))}<br>
         Tentativas da fonte: {int(payload.get('tentativas') or 0)}</p>
      {fallbacks}
      {run_link}
      <p style="font-size:12px;color:#667085">O último snapshot íntegro é preservado quando a auditoria não fecha.</p>
    </div>
    """


def send_resend(payload: dict[str, Any]) -> tuple[bool, str]:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    destination = os.environ.get("EMAIL_DESTINO", "").strip()
    sender = os.environ.get("EMAIL_REMETENTE", DEFAULT_EMAIL_SENDER).strip() or DEFAULT_EMAIL_SENDER
    if not key or not destination:
        return False, "secrets RESEND_API_KEY/EMAIL_DESTINO não configurados"
    status_label = failure_label(payload)
    subject = f"[BR2026 Almoço] {str(payload.get('workflow') or 'Workflow')} — {status_label}"
    data = json.dumps({
        "from": sender,
        "to": [destination],
        "subject": subject,
        "html": email_html(payload),
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Brasileirao2026AlmocoStatus/1.0 (+https://brasileirao2026almoco.com.br)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 300, body[:500]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {body[:500]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def run(*, force_error: bool = False, notify: bool = False) -> dict[str, Any]:
    previous = load_json(OUTPUT, {})
    payload = status_from_env(previous, force_error=force_error)
    if notify and should_notify(payload):
        sent, detail = send_resend(payload)
        if sent:
            payload["ultimo_alerta_em"] = now_brt().isoformat()
            payload["ultimo_alerta_fingerprint"] = payload["fingerprint"]
            payload["alerta_email"] = "enviado"
            print("Alerta operacional enviado por e-mail.")
        else:
            # A falta do secret ou uma indisponibilidade do Resend não pode
            # derrubar a atualização dos dados.
            payload["alerta_email"] = "não enviado"
            payload["alerta_email_detalhe"] = detail
            print(f"::warning::Alerta operacional não enviado: {detail}")
    elif notify:
        status = str(payload.get("status") or "").lower()
        payload["alerta_email"] = (
            "dispensado: atualização sem falha"
            if status not in FAILURE_STATUSES
            else "dispensado por deduplicação/cooldown"
        )
    atomic_write(OUTPUT, payload)
    print(
        f"Status operacional gravado: {payload['status']} | "
        f"mostrar_publico={str(payload['mostrar_publico']).lower()}"
    )
    return payload


def selftest() -> None:
    import tempfile

    global OUTPUT, SNAPSHOT_FILES
    original_output = OUTPUT
    original_files = SNAPSHOT_FILES
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        OUTPUT = root / "status.json"
        SNAPSHOT_FILES = tuple(root / name for name in ("tabela.json", "resultados.json", "jogos.json", "espn_eventos.json"))
        for item in SNAPSHOT_FILES:
            item.write_text('{"fonte":"ESPN"}\n', encoding="utf-8")

        os.environ.update({
            "BR_STATUS": "ok",
            "BR_MOTIVO": "Tudo certo",
            "BR_SINCRONIZADO": "true",
            "BR_TENTATIVAS": "1",
            "BR_FALLBACKS": "[]",
            "BR_WORKFLOW": "Atualizar Brasileirao (ESPN)",
        })
        ok = run()
        assert ok["status"] == "ok" and ok["ultimo_sucesso"] and not ok["mostrar_publico"]
        assert not should_notify(ok), "status normal nunca deve enviar e-mail"
        unchanged = run()
        assert unchanged == ok, "status normal sem mudança deveria ser idempotente"

        os.environ.update({
            "BR_STATUS": "aviso",
            "BR_MOTIVO": "Snapshot auditado com override manual conhecido",
            "BR_SINCRONIZADO": "true",
            "BR_FALLBACKS": '[{"event_id":"1","fonte":"override manual","placar":"2 x 0"}]',
        })
        warning = run()
        assert warning["status"] == "aviso" and not warning["mostrar_publico"]
        assert not should_notify(warning), "fallback auditado não pode enviar e-mail"

        os.environ.update({
            "BR_STATUS": "preservado",
            "BR_MOTIVO": "Fonte fora de sincronia",
            "BR_SINCRONIZADO": "false",
            "BR_FALLBACKS": "[]",
        })
        preserved = run()
        assert preserved["status"] == "preservado" and preserved["mostrar_publico"]
        assert preserved["ultimo_sucesso"] == warning["ultimo_sucesso"]
        assert should_notify(preserved), "snapshot preservado representa falha de atualização"
        preserved["ultimo_alerta_em"] = now_brt().isoformat()
        preserved["ultimo_alerta_fingerprint"] = preserved["fingerprint"]
        assert not should_notify(preserved), "falha idêntica deve respeitar o cooldown"

        os.environ.update({
            "BR_STATUS": "erro",
            "BR_MOTIVO": "Falha crítica",
            "BR_SINCRONIZADO": "false",
        })
        error = status_from_env(preserved)
        assert should_notify(error), "erro novo deve enviar e-mail"

        os.environ.update({
            "BR_STATUS": "ok",
            "BR_MOTIVO": "Fonte normalizada",
            "BR_SINCRONIZADO": "true",
        })
        recovered = status_from_env(error)
        assert recovered["status_anterior"] == "erro"
        assert not should_notify(recovered), "recuperação não deve enviar e-mail"
        assert DEFAULT_EMAIL_SENDER == "Avisos · Brasileirão 2026 <avisos@brasileirao2026almoco.com.br>"

    OUTPUT = original_output
    SNAPSHOT_FILES = original_files
    print("Selftest do status operacional OK: e-mail somente em falha real")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-env", action="store_true")
    parser.add_argument("--error", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.from_env and not args.error:
        parser.error("use --from-env ou --error")
    run(force_error=args.error, notify=args.notify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

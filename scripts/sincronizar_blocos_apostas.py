#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincroniza automaticamente as janelas dos blocos de apostas 21–38.

A matriz canônica decide a composição dos blocos; o relógio de apostas é
independente da apuração. O script não move jogos entre rodadas, não pontua
palpites e não reabre bloco fechado.

Fluxo:
1. lê os 30 confrontos canônicos de cada bloco;
2. encontra o PRIMEIRO kickoff confiável entre todos os 30;
3. recomenda abertura 7 dias antes e fechamento 60 min antes;
4. delega a mutação segura à RPC service_role da Execução 21;
5. envia um único e-mail quando um bloco entra em ABERTA;
6. envia um único e-mail quando um bloco chega a 30/30, com vencedor e pontos;
7. grava auditoria agregada sem expor palpites/placares dos participantes.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Sao_Paulo")
TEMPORADA = int(os.environ.get("BRASILEIRAO_TEMPORADA", "2026"))
CALENDAR_PATH = ROOT / "dados-br" / "calendario-completo.json"
CONFIG_PATH = ROOT / "dados-br" / "apostas-config.json"
AUDIT_PATH = ROOT / "dados-br" / "auditoria-blocos-apostas.json"
APURACAO_PATH = ROOT / "dados-br" / "apuracao.json"
SITE_RANKING_URL = "https://brasileirao2026almoco.com.br/apostas.html?aba=ranking"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
DEFAULT_SENDER = "Bolão Brasileirão 2026 <avisos@brasileirao2026almoco.com.br>"
BLOCOS = ((21, 23), (24, 26), (27, 29), (30, 32), (33, 35), (36, 38))


def now_brt() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def team_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("nome") or value.get("time") or value.get("name") or "").strip()
    return str(value or "").strip()


def canonical_uid(row: Mapping[str, Any], season: int = TEMPORADA) -> str:
    try:
        round_number = int(row.get("rodada") or 0)
    except (TypeError, ValueError):
        round_number = 0
    home = team_name(row.get('mandante')).lower()
    away = team_name(row.get('visitante')).lower()
    if round_number <= 0 or not home or not away:
        return ""
    return f"{season}|{round_number}|{home}|{away}"


def kickoff_reliable(row: Mapping[str, Any]) -> bool:
    if row.get("data_definir") is True:
        return False
    if row.get("kickoff_provisorio") is True or row.get("horario_provisorio") is True:
        return False
    return parse_dt(row.get("data_iso")) is not None


def auto_policy(config: Mapping[str, Any]) -> dict[str, Any]:
    raw = config.get("blocosAutomaticos") if isinstance(config, Mapping) else {}
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "habilitado": bool(raw.get("habilitado", True)),
        "abertura_dias": int(raw.get("antecedenciaAberturaDias") or 7),
        "fechamento_minutos": int(raw.get("fechamentoAntesPrimeiroJogoMinutos") or 60),
        "exigir_canonicos": int(raw.get("exigirConfrontosCanonicos") or 30),
        "email_ao_abrir": bool(raw.get("emailAoAbrir", True)),
        "email_ao_concluir": bool(raw.get("emailAoConcluir", True)),
    }


def build_proposals(calendar_payload: Mapping[str, Any], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = list(calendar_payload.get("jogos") or calendar_payload.get("partidas") or [])
    policy = auto_policy(config)
    proposals: list[dict[str, Any]] = []
    for start, end in BLOCOS:
        games = [row for row in rows if isinstance(row, Mapping) and start <= int(row.get("rodada") or 0) <= end]
        reliable = sorted(
            (parse_dt(row.get("data_iso")) for row in games if kickoff_reliable(row)),
            key=lambda value: value or datetime.max.replace(tzinfo=TZ),
        )
        reliable = [dt for dt in reliable if dt is not None]
        first = reliable[0] if reliable else None
        open_at = first - timedelta(days=policy["abertura_dias"]) if first else None
        close_at = first - timedelta(minutes=policy["fechamento_minutos"]) if first else None
        uids = {canonical_uid(row) for row in games if canonical_uid(row)}
        proposals.append({
            "rodada_inicio": start,
            "rodada_fim": end,
            "nome": f"Bloco {start}–{end}",
            "total_canonicos": len(uids),
            "horarios_confiaveis": len(reliable),
            "horarios_a_definir": max(0, len(uids) - len(reliable)),
            "primeiro_jogo_em": first.isoformat() if first else None,
            "abre_recomendado_em": open_at.isoformat() if open_at else None,
            "fecha_recomendado_em": close_at.isoformat() if close_at else None,
            "jogos": [
                {
                    "jogo_uid": canonical_uid(row),
                    "rodada": int(row.get("rodada") or 0),
                    "event_id": str(row.get("event_id") or ""),
                    "mandante": team_name(row.get("mandante")),
                    "visitante": team_name(row.get("visitante")),
                    "data_iso": row.get("data_iso"),
                    "horario_confiavel": kickoff_reliable(row),
                }
                for row in games
            ],
        })
    return proposals


def status_by_clock(now: datetime, open_at: datetime | None, close_at: datetime | None) -> str:
    if not open_at or not close_at:
        return "futura"
    if now < open_at:
        return "programada"
    if now < close_at:
        return "aberta"
    return "fechada"


def reconcile_window(
    existing: Mapping[str, Any], proposal: Mapping[str, Any], bet_count: int, now: datetime
) -> dict[str, Any]:
    """Espelho puro das regras críticas aplicadas pela RPC, usado em testes."""
    first = parse_dt(proposal.get("primeiro_jogo_em"))
    open_calc = parse_dt(proposal.get("abre_recomendado_em"))
    close_calc = parse_dt(proposal.get("fecha_recomendado_em"))
    if int(proposal.get("total_canonicos") or 0) != 30 or not first or not open_calc or not close_calc:
        return dict(existing)
    old_first = parse_dt(existing.get("primeiro_jogo_em"))
    old_open = parse_dt(existing.get("abre_em"))
    old_close = parse_dt(existing.get("fecha_em"))
    if bet_count <= 0:
        new_first, new_open, new_close = first, open_calc, close_calc
    else:
        new_first = min(old_first, first) if old_first else first
        new_open = old_open or open_calc
        new_close = min(old_close, close_calc) if old_close else close_calc
    old_status = str(existing.get("status") or "futura").lower()
    status = old_status if old_status in {"fechada", "bloqueada"} else status_by_clock(now, new_open, new_close)
    return {
        **dict(existing),
        "primeiro_jogo_em": new_first.isoformat(),
        "abre_em": new_open.isoformat(),
        "fecha_em": new_close.isoformat(),
        "status": status,
    }


def supabase_headers() -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY não configurados")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def rpc_service(name: str, payload: Mapping[str, Any]) -> Any:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/{name}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=supabase_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"RPC {name} falhou ({exc.code}): {detail}") from exc


def email_opening(block: Mapping[str, Any]) -> tuple[bool, str]:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    destination = os.environ.get("EMAIL_DESTINO", "").strip()
    sender = os.environ.get("EMAIL_REMETENTE", DEFAULT_SENDER).strip() or DEFAULT_SENDER
    if not key or not destination:
        return False, "RESEND_API_KEY/EMAIL_DESTINO não configurados"
    start = int(block.get("rodada_inicio") or 0)
    end = int(block.get("rodada_fim") or 0)
    close = parse_dt(block.get("fecha_em"))
    close_text = close.strftime("%d/%m/%Y às %H:%M") if close else "horário configurado no site"
    subject = f"Brasileirão 2026 Almoço — Rodadas {start}–{end} abertas"
    html = (
        f"<h2>Rodadas {start}–{end} estão abertas!</h2>"
        "<p><strong>Envie mensagem no grupo para fazerem seus palpites.</strong></p>"
        f"<p>São 30 jogos, das rodadas {start}, {start + 1} e {end}. O prazo atual termina em <strong>{close_text}</strong>.</p>"
        "<p>Um bloco anterior ainda em apuração por causa de jogo adiado não impede este bloco de funcionar normalmente.</p>"
    )
    body = json.dumps({"from": sender, "to": [destination], "subject": subject, "html": html}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Brasileirao2026Almoco-Blocos/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return 200 <= response.status < 300, response.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:500]



def completion_details(block: Mapping[str, Any], apuracao: Mapping[str, Any]) -> dict[str, Any] | None:
    start = int(block.get("rodada_inicio") or 0)
    end = int(block.get("rodada_fim") or 0)
    item = next((row for row in (apuracao.get("blocos") or []) if isinstance(row, Mapping)
                 and int(row.get("rodada_inicio") or 0) == start
                 and int(row.get("rodada_fim") or 0) == end), None)
    if not item or not item.get("concluido") or int(item.get("jogos_apurados") or 0) != 30:
        return None
    ranking = [row for row in (item.get("ranking") or []) if isinstance(row, Mapping)]
    if not ranking:
        return None
    top_points = int(ranking[0].get("pontos") or 0)
    winners = [str(name).strip() for name in (item.get("vencedores") or []) if str(name).strip()]
    if not winners:
        winners = [str(ranking[0].get("membro") or "").strip()]
    winners = [name for name in winners if name]
    if not winners:
        return None
    return {
        "rodada_inicio": start,
        "rodada_fim": end,
        "vencedores": winners,
        "pontos": top_points,
        "jogos_apurados": 30,
    }


def email_completion(block: Mapping[str, Any], details: Mapping[str, Any]) -> tuple[bool, str]:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    destination = os.environ.get("EMAIL_DESTINO", "").strip()
    sender = os.environ.get("EMAIL_REMETENTE", DEFAULT_SENDER).strip() or DEFAULT_SENDER
    if not key or not destination:
        return False, "RESEND_API_KEY/EMAIL_DESTINO não configurados"
    start = int(details.get("rodada_inicio") or block.get("rodada_inicio") or 0)
    end = int(details.get("rodada_fim") or block.get("rodada_fim") or 0)
    winners = [str(x).strip() for x in (details.get("vencedores") or []) if str(x).strip()]
    points = int(details.get("pontos") or 0)
    if not winners:
        return False, "ranking concluído sem vencedor identificável"
    if len(winners) == 1:
        winner_text = f"Vencedor: {winners[0]} — {points} pontos."
        subject_suffix = winners[0]
    else:
        winner_text = f"Vencedores: {', '.join(winners[:-1])} e {winners[-1]} — {points} pontos."
        subject_suffix = "empate no 1º lugar"
    link = f"{SITE_RANKING_URL}&bloco={start}-{end}"
    subject = f"Brasileirão 2026 Almoço — Bloco {start}–{end} concluído · {subject_suffix}"
    html = (
        f"<h2>Bloco {start}–{end} concluído!</h2>"
        f"<p><strong>{winner_text}</strong></p>"
        f'<p><a href="{link}">Confira o ranking no site</a>.</p>'
    )
    body = json.dumps({"from": sender, "to": [destination], "subject": subject, "html": html}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Brasileirao2026Almoco-Blocos/1.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return 200 <= response.status < 300, response.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:500]


def merge_completion_email_state(db_blocks: Sequence[Mapping[str, Any]], states: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("bloco_id") or ""): row for row in states if isinstance(row, Mapping)}
    by_start = {int(row.get("rodada_inicio") or 0): row for row in states if isinstance(row, Mapping)}
    merged: list[dict[str, Any]] = []
    for original in db_blocks:
        block = dict(original)
        state = by_id.get(str(block.get("bloco_id") or "")) or by_start.get(int(block.get("rodada_inicio") or 0)) or {}
        for key in (
            "email_conclusao_pendente",
            "conclusao_email_enviado_em",
            "conclusao_email_ultima_tentativa_em",
            "apurado_em",
        ):
            if key in state:
                block[key] = state.get(key)
        merged.append(block)
    return merged


def build_audit(
    proposals: Sequence[Mapping[str, Any]],
    db_blocks: Sequence[Mapping[str, Any]] | None,
    now: datetime,
    sync_error: str = "",
    email_state_error: str = "",
    emails: Sequence[Mapping[str, Any]] = (),
    completion_emails: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    by_start = {int(row.get("rodada_inicio") or 0): dict(row) for row in (db_blocks or []) if isinstance(row, Mapping)}
    blocks: list[dict[str, Any]] = []
    critical: list[str] = []
    warnings: list[str] = []
    next_events: list[datetime] = []
    for proposal in proposals:
        start = int(proposal.get("rodada_inicio") or 0)
        db = by_start.get(start, {})
        status = str(db.get("status") or status_by_clock(now, parse_dt(proposal.get("abre_recomendado_em")), parse_dt(proposal.get("fecha_recomendado_em"))))
        open_at = parse_dt(db.get("abre_em") or proposal.get("abre_recomendado_em"))
        close_at = parse_dt(db.get("fecha_em") or proposal.get("fecha_recomendado_em"))
        if int(proposal.get("total_canonicos") or 0) != 30:
            critical.append(f"Bloco {start}–{start+2} não possui 30 confrontos canônicos.")
        if status == "aberta" and close_at and close_at <= now:
            critical.append(f"Bloco {start}–{start+2} está aberto depois do deadline.")
        if status in {"futura", "programada"} and open_at and open_at <= now < (close_at or now):
            critical.append(f"Bloco {start}–{start+2} deveria estar aberto pelo relógio, mas está {status}.")
        if status == "aberta" and open_at and open_at > now:
            critical.append(f"Bloco {start}–{start+2} abriu antes da abertura programada.")
        if status == "programada" and open_at and open_at > now:
            next_events.append(open_at)
        if status == "aberta" and close_at and close_at > now:
            next_events.append(close_at)
        if not proposal.get("primeiro_jogo_em"):
            warnings.append(f"Bloco {start}–{start+2} ainda sem kickoff confiável; permanece sem janela automática nova.")
        blocks.append({
            "bloco_id": db.get("bloco_id"),
            "rodada_inicio": start,
            "rodada_fim": start + 2,
            "nome": proposal.get("nome"),
            "total_canonicos": int(proposal.get("total_canonicos") or 0),
            "horarios_confiaveis": int(proposal.get("horarios_confiaveis") or 0),
            "horarios_a_definir": int(proposal.get("horarios_a_definir") or 0),
            "primeiro_jogo_em": db.get("primeiro_jogo_em") or proposal.get("primeiro_jogo_em"),
            "abre_em": db.get("abre_em") or proposal.get("abre_recomendado_em"),
            "fecha_em": db.get("fecha_em") or proposal.get("fecha_recomendado_em"),
            "status_apostas": status,
            "total_palpites": int(db.get("total_palpites") or 0),
            "jogos_apurados": int(db.get("jogos_apurados") or 0),
            "apuracao_concluida": bool(db.get("apuracao_concluida")),
            "email_abertura_pendente": bool(db.get("email_abertura_pendente")),
            "email_abertura_enviado_em": db.get("abertura_email_enviado_em"),
            "email_conclusao_pendente": bool(db.get("email_conclusao_pendente")),
            "email_conclusao_enviado_em": db.get("conclusao_email_enviado_em"),
            "sincronizado": bool(db),
        })
    if sync_error:
        critical.append(f"Sincronização dos blocos indisponível: {sync_error}")
    if email_state_error:
        warnings.append(f"Estado de deduplicação do e-mail de conclusão indisponível: {email_state_error}")
    status = "critical" if critical else "warning" if warnings else "ok"
    return {
        "schema_version": 1,
        "gerado_em": now.isoformat(),
        "temporada": TEMPORADA,
        "status": status,
        "resumo": {
            "blocos": len(blocks),
            "criticos": len(critical),
            "avisos": len(warnings),
            "abertos": sum(1 for b in blocks if b["status_apostas"] == "aberta"),
            "em_apuracao": sum(1 for b in blocks if 0 < b["jogos_apurados"] < 30),
            "concluidos": sum(1 for b in blocks if b["apuracao_concluida"]),
        },
        "blocos": blocks,
        "criticos": critical,
        "avisos": warnings,
        "emails_abertura": list(emails),
        "emails_conclusao": list(completion_emails),
        "proximo_evento_em": min(next_events).isoformat() if next_events else None,
        "politica": {
            "composicao": "30 jogos pela rodada canônica; jogo adiado nunca muda de bloco.",
            "abertura": "7 dias antes do primeiro kickoff confiável entre os 30 jogos.",
            "fechamento": "60 minutos antes do primeiro kickoff confiável entre os 30 jogos.",
            "apos_primeiro_palpite": "deadline pode encurtar por antecipação; nunca é estendido automaticamente.",
            "reabertura": "proibida automaticamente.",
            "independencia": "bloco seguinte pode abrir com bloco anterior ainda em apuração.",
            "email_conclusao": "uma única vez quando o bloco chega a 30/30; vencedor e pontos vêm exclusivamente da apuração determinística.",
        },
    }


def run(*, dry_run: bool = False, moment: datetime | None = None, notify_opening: bool = True, notify_completion: bool = True) -> dict[str, Any]:
    now = (moment or now_brt()).astimezone(TZ).replace(microsecond=0)
    config = load_json(CONFIG_PATH, {})
    calendar = load_json(CALENDAR_PATH, {})
    policy = auto_policy(config)
    proposals = build_proposals(calendar, config)
    if not policy["habilitado"]:
        audit = build_audit(proposals, [], now)
        audit["status"] = "disabled"
        save_json(AUDIT_PATH, audit)
        return audit

    if dry_run or not SUPABASE_URL or not SUPABASE_KEY:
        audit = build_audit(proposals, [], now, "" if dry_run else "SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY não configurados")
        if dry_run:
            audit["dry_run"] = True
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return audit

    response = rpc_service("br_pipeline_sincronizar_blocos_v1", {
        "p_temporada": TEMPORADA,
        "p_agora": now.isoformat(),
        "p_abertura_antecedencia_dias": policy["abertura_dias"],
        "p_fechamento_antecedencia_minutos": policy["fechamento_minutos"],
        "p_blocos": [
            {
                "rodada_inicio": p["rodada_inicio"],
                "rodada_fim": p["rodada_fim"],
                "total_canonicos": p["total_canonicos"],
                "primeiro_jogo_em": p["primeiro_jogo_em"],
            }
            for p in proposals
        ],
        "p_origem": os.environ.get("GITHUB_WORKFLOW", "pipeline-exec21")[:200],
    })
    db_blocks = list((response or {}).get("blocos") or []) if isinstance(response, Mapping) else []
    completion_state_error = ""
    try:
        completion_states_raw = rpc_service("br_pipeline_status_emails_conclusao_v1", {"p_temporada": TEMPORADA})
        completion_states = list(completion_states_raw or []) if isinstance(completion_states_raw, list) else []
        db_blocks = merge_completion_email_state(db_blocks, completion_states)
    except Exception as exc:  # noqa: BLE001
        completion_state_error = str(exc)[:500]
    email_results: list[dict[str, Any]] = []
    completion_email_results: list[dict[str, Any]] = []
    if notify_opening and policy["email_ao_abrir"]:
        for block in db_blocks:
            if not block.get("email_abertura_pendente"):
                continue
            last_try = parse_dt(block.get("abertura_email_ultima_tentativa_em"))
            if last_try and (now - last_try).total_seconds() < 3600:
                email_results.append({"bloco": f"{block.get('rodada_inicio')}–{block.get('rodada_fim')}", "enviado": False, "detalhe": "tentativa recente; aguardando 60 min"})
                continue
            rpc_service("br_pipeline_marcar_tentativa_email_abertura_v1", {
                "p_temporada": TEMPORADA,
                "p_bloco_id": block.get("bloco_id"),
                "p_tentativa_em": now.isoformat(),
            })
            sent, detail = email_opening(block)
            if sent:
                rpc_service("br_pipeline_marcar_email_abertura_v1", {
                    "p_temporada": TEMPORADA,
                    "p_bloco_id": block.get("bloco_id"),
                    "p_enviado_em": now.isoformat(),
                })
                block["email_abertura_pendente"] = False
                block["abertura_email_enviado_em"] = now.isoformat()
            email_results.append({
                "bloco": f"{block.get('rodada_inicio')}–{block.get('rodada_fim')}",
                "enviado": sent,
                "detalhe": detail,
            })

    if notify_completion and policy["email_ao_concluir"] and not completion_state_error:
        apuracao = load_json(APURACAO_PATH, {})
        for block in db_blocks:
            if not block.get("email_conclusao_pendente"):
                continue
            label = f"{block.get('rodada_inicio')}–{block.get('rodada_fim')}"
            details = completion_details(block, apuracao if isinstance(apuracao, Mapping) else {})
            if not details:
                completion_email_results.append({"bloco": label, "enviado": False, "detalhe": "30/30 no banco, mas apuração local ainda não contém ranking final validado"})
                continue
            last_try = parse_dt(block.get("conclusao_email_ultima_tentativa_em"))
            if last_try and (now - last_try).total_seconds() < 3600:
                completion_email_results.append({"bloco": label, "enviado": False, "detalhe": "tentativa recente; aguardando 60 min"})
                continue
            rpc_service("br_pipeline_marcar_tentativa_email_conclusao_v1", {
                "p_temporada": TEMPORADA,
                "p_bloco_id": block.get("bloco_id"),
                "p_tentativa_em": now.isoformat(),
            })
            sent, detail = email_completion(block, details)
            if sent:
                rpc_service("br_pipeline_marcar_email_conclusao_v1", {
                    "p_temporada": TEMPORADA,
                    "p_bloco_id": block.get("bloco_id"),
                    "p_enviado_em": now.isoformat(),
                })
                block["email_conclusao_pendente"] = False
                block["conclusao_email_enviado_em"] = now.isoformat()
            completion_email_results.append({
                "bloco": label,
                "enviado": sent,
                "vencedores": details.get("vencedores"),
                "pontos": details.get("pontos"),
                "detalhe": detail,
            })

    audit = build_audit(proposals, db_blocks, now, email_state_error=completion_state_error, emails=email_results, completion_emails=completion_email_results)
    save_json(AUDIT_PATH, audit)
    print(json.dumps(audit["resumo"], ensure_ascii=False, indent=2))
    return audit


def self_test() -> int:
    config = {"blocosAutomaticos": {"antecedenciaAberturaDias": 7, "fechamentoAntesPrimeiroJogoMinutos": 60}}
    rows = []
    for start, end in BLOCOS:
        idx = 0
        for round_number in range(start, end + 1):
            for game in range(10):
                idx += 1
                rows.append({
                    "rodada": round_number,
                    "mandante": f"M{start}-{round_number}-{game}",
                    "visitante": f"V{start}-{round_number}-{game}",
                    "event_id": str(idx),
                    "data_iso": (datetime(2026, 8, 22, 16, 0, tzinfo=TZ) + timedelta(days=(start - 21) * 2 + game)).isoformat(),
                    "data_definir": False,
                })
    proposals = build_proposals({"jogos": rows}, config)
    assert len(proposals) == 6
    assert all(p["total_canonicos"] == 30 for p in proposals)
    p = proposals[0]
    assert parse_dt(p["abre_recomendado_em"]) == datetime(2026, 8, 15, 16, 0, tzinfo=TZ)
    assert parse_dt(p["fecha_recomendado_em"]) == datetime(2026, 8, 22, 15, 0, tzinfo=TZ)
    # O primeiro jogo é procurado em TODOS os 30: uma antecipação na terceira
    # rodada deve dominar um kickoff mais tarde da primeira rodada.
    rows2 = [dict(x) for x in rows]
    target = next(x for x in rows2 if x["rodada"] == 23)
    target["data_iso"] = "2026-08-20T19:00:00-03:00"
    p2 = build_proposals({"jogos": rows2}, config)[0]
    assert parse_dt(p2["primeiro_jogo_em"]) == datetime(2026, 8, 20, 19, 0, tzinfo=TZ)
    # Horário a definir não pode encerrar aposta ficticiamente.
    target["data_definir"] = True
    p3 = build_proposals({"jogos": rows2}, config)[0]
    assert parse_dt(p3["primeiro_jogo_em"]) == datetime(2026, 8, 22, 16, 0, tzinfo=TZ)
    # Depois de existir palpite, adiamento não estende o prazo; antecipação encurta.
    existing = {
        "primeiro_jogo_em": "2026-08-22T16:00:00-03:00",
        "abre_em": "2026-08-15T16:00:00-03:00",
        "fecha_em": "2026-08-22T15:00:00-03:00",
        "status": "aberta",
    }
    delayed = {**p, "primeiro_jogo_em": "2026-08-23T16:00:00-03:00", "abre_recomendado_em": "2026-08-16T16:00:00-03:00", "fecha_recomendado_em": "2026-08-23T15:00:00-03:00"}
    merged = reconcile_window(existing, delayed, 1, datetime(2026, 8, 18, 12, 0, tzinfo=TZ))
    assert merged["fecha_em"].startswith("2026-08-22T15:00:00")
    earlier = {**p, "primeiro_jogo_em": "2026-08-21T16:00:00-03:00", "abre_recomendado_em": "2026-08-14T16:00:00-03:00", "fecha_recomendado_em": "2026-08-21T15:00:00-03:00"}
    merged2 = reconcile_window(existing, earlier, 1, datetime(2026, 8, 18, 12, 0, tzinfo=TZ))
    assert merged2["fecha_em"].startswith("2026-08-21T15:00:00")
    closed = reconcile_window({**existing, "status": "fechada"}, delayed, 1, datetime(2026, 8, 18, 12, 0, tzinfo=TZ))
    assert closed["status"] == "fechada"
    # O cenário real da próxima janela: kickoff 22/08 16h -> em 15/08 17:06 já aberta.
    assert status_by_clock(
        datetime(2026, 8, 15, 17, 6, tzinfo=TZ),
        datetime(2026, 8, 15, 16, 0, tzinfo=TZ),
        datetime(2026, 8, 22, 15, 0, tzinfo=TZ),
    ) == "aberta"
    final_payload = {"blocos": [{
        "rodada_inicio": 21, "rodada_fim": 23, "concluido": True, "jogos_apurados": 30,
        "vencedores": ["Fulano"], "ranking": [{"membro": "Fulano", "pontos": 77}, {"membro": "Beltrano", "pontos": 72}],
    }]}
    details = completion_details({"rodada_inicio": 21, "rodada_fim": 23}, final_payload)
    assert details == {"rodada_inicio": 21, "rodada_fim": 23, "vencedores": ["Fulano"], "pontos": 77, "jogos_apurados": 30}
    assert completion_details({"rodada_inicio": 21, "rodada_fim": 23}, {"blocos": [{"rodada_inicio":21,"rodada_fim":23,"concluido":False,"jogos_apurados":29,"ranking":[]}]} ) is None
    merged_states = merge_completion_email_state(
        [{"bloco_id":"x","rodada_inicio":21}],
        [{"bloco_id":"x","rodada_inicio":21,"email_conclusao_pendente":True,"conclusao_email_enviado_em":None}],
    )
    assert merged_states[0]["email_conclusao_pendente"] is True
    print("SELFTEST OK: 30 jogos/bloco, janela automática, não-reabertura e e-mail final 30/30 validados.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agora", default="")
    parser.add_argument("--sem-email", action="store_true", help="Não enviar e-mails de abertura nem conclusão")
    parser.add_argument("--sem-email-abertura", action="store_true")
    parser.add_argument("--sem-email-conclusao", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    moment = parse_dt(args.agora) if args.agora else None
    run(
        dry_run=args.dry_run,
        moment=moment,
        notify_opening=not (args.sem_email or args.sem_email_abertura),
        notify_completion=not (args.sem_email or args.sem_email_conclusao),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

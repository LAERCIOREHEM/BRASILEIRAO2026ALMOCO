#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Orquestrador determinístico do Brasileirão 2026 Almoço.

O script não usa IA e não altera o repositório. Em cada ciclo ele lê o estado
publicado, sonda a ESPN somente na janela de partidas relevantes e consulta o
histórico recente do GitHub Actions. A saída é UMA única próxima ação útil.

Princípios:
- gol/empate/virada AO VIVO não disparam pipeline pesado: o navegador já usa o
  scoreboard ESPN para a apresentação live;
- FINAL ainda não incorporado tem prioridade máxima;
- apuração e AF possuem recuperação independente se ficarem atrás dos resultados;
- públicos e melhores momentos usam backoff e só rodam enquanto houver pendência;
- grade de TV roda no máximo uma vez ao dia; player GE TV/CazéTV não é acionado
  automaticamente;
- no máximo um workflow escritor é despachado por ciclo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "dados-br" / "config-orquestrador.json"
CALENDARIO_PATH = ROOT / "dados-br" / "calendario-completo.json"
RESULTADOS_PATH = ROOT / "resultados.json"
STATUS_PATH = ROOT / "dados-br" / "status-atualizacao.json"
APURACAO_PATH = ROOT / "dados-br" / "apuracao.json"
RANKING_PATH = ROOT / "dados-br" / "ranking-apostas.json"
APOSTAS_CONFIG_PATH = ROOT / "dados-br" / "apostas-config.json"
AUD_AF_PATH = ROOT / "dados-br" / "auditoria-probabilidades.json"
PROB_BOLAO_PATH = ROOT / "dados-br" / "probabilidades-bolao.json"
DETAILS_PATH = ROOT / "dados-br" / "jogos-detalhes.json"
PUBLIC_COMPLEMENTS_PATH = ROOT / "dados-br" / "publicos-complementares.json"
PUBLIC_AUDIT_PATH = ROOT / "dados-br" / "auditoria-publicos.json"
MM_PATH = ROOT / "dados-br" / "melhores-momentos.json"
MM_MANUAL_PATH = ROOT / "dados-br" / "melhores-momentos-manual.json"
TV_AUDIT_PATH = ROOT / "dados-br" / "auditoria-transmissoes-tv.json"
GENERAL_AUDIT_PATH = ROOT / "dados-br" / "auditoria-geral.json"

WORKFLOW_MAIN = "Atualizar Brasileirao (ESPN)"
WORKFLOW_APURAR = "Apurar Apostas Brasileirão"
WORKFLOW_PUBLICOS = "Atualizar públicos do Brasileirão"
WORKFLOW_MM = "Buscar melhores momentos Brasileirão oficiais"
WORKFLOW_TV = "Buscar transmissões ao vivo do Brasileirão"

REPO_WRITERS = {
    "Apurar Apostas Brasileirão",
    "Atualizar Brasileirao (ESPN)",
    "Atualizar Elencos Brasileirao (ESPN)",
    "Atualizar tudo (agora somente Copa - ranking de desempenho)",
    "Auditar modelos AF-Previsão",
    "Buscar melhores momentos Brasileirão oficiais",
    "Buscar transmissões ao vivo do Brasileirão",
    "Atualizar públicos do Brasileirão",
    "Atualiza fair play (cartões)",
    "Buscar melhores momentos (CazéTV)",
    "Revisar melhores momentos Brasileirão oficiais",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "America/Sao_Paulo",
    "atualizar_brasileirao": {
        "sondagem_antes_minutos": 45,
        "sondagem_depois_minutos": 240,
        "intervalo_pre_jogo_minutos": 60,
        "retentativa_final_pendente_minutos": 10,
        "fallback_final_estimado_minutos": 105,
        "manutencao_diaria_apos": "05:10",
    },
    "apuracao": {"tolerancia_atraso_segundos": 20, "retentativa_minutos": 10},
    "af_previsao": {"retentativa_minutos": 20},
    "publicos": {
        "primeira_tentativa_apos_final_minutos": 15,
        "intervalos_retentativa": [
            {"ate_horas": 2, "minutos": 30},
            {"ate_horas": 6, "minutos": 60},
            {"ate_horas": 24, "minutos": 120},
            {"ate_horas": 72, "minutos": 360},
            {"ate_horas": 168, "minutos": 720},
            {"ate_horas": 99999, "minutos": 1440},
        ],
    },
    "melhores_momentos": {
        "primeira_tentativa_apos_final_minutos": 10,
        "intervalos_retentativa": [
            {"ate_horas": 2, "minutos": 10},
            {"ate_horas": 6, "minutos": 30},
            {"ate_horas": 24, "minutos": 120},
            {"ate_horas": 72, "minutos": 360},
            {"ate_horas": 99999, "minutos": 720},
        ],
    },
    "transmissoes": {"tv_diaria_apos": "06:30"},
    "artefatos": {
        "auditoria_geral_max_horas": 30,
        "auditoria_transmissoes_max_horas": 36,
    },
    "github": {"branch": "main", "historico_runs": 200, "bloquear_se_writer_ativo": True},
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(default, ensure_ascii=False))


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)  # type: ignore[arg-type]
        else:
            out[key] = value
    return out


def parse_dt(value: Any, tz: ZoneInfo) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def now_local(tz: ZoneInfo, override: str = "") -> datetime:
    raw = override or os.environ.get("BR_ORQ_AGORA", "")
    return parse_dt(raw, tz) if raw and parse_dt(raw, tz) else datetime.now(tz).replace(microsecond=0)


def minutes_since(moment: datetime | None, now: datetime) -> float:
    if moment is None:
        return 10**9
    return max(0.0, (now - moment).total_seconds() / 60.0)


def time_reached(now: datetime, hhmm: str) -> bool:
    try:
        hh, mm = [int(x) for x in str(hhmm).split(":", 1)]
    except (TypeError, ValueError):
        return True
    return (now.hour, now.minute) >= (hh, mm)


def score_value(value: Any) -> int | None:
    if isinstance(value, Mapping):
        value = value.get("value") if value.get("value") is not None else value.get("displayValue")
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Game:
    event_id: str
    kickoff: datetime
    home: str
    away: str
    round_number: int

    @property
    def label(self) -> str:
        return f"{self.home} x {self.away}"


@dataclass(frozen=True)
class Decision:
    action: str = "none"
    reason: str = "Estado consistente; nenhum workflow pesado precisa rodar agora."
    event_id: str = ""
    round_number: str = ""
    mode: str = ""
    details: tuple[str, ...] = ()


def load_games(tz: ZoneInfo) -> list[Game]:
    payload = load_json(CALENDARIO_PATH, {})
    rows = payload.get("jogos") if isinstance(payload, Mapping) else []
    out: list[Game] = []
    for raw in rows or []:
        if not isinstance(raw, Mapping):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        kickoff = parse_dt(raw.get("data_iso"), tz)
        if not event_id or not kickoff or raw.get("data_definir") is True:
            continue
        out.append(
            Game(
                event_id=event_id,
                kickoff=kickoff,
                home=str(raw.get("mandante") or "").strip(),
                away=str(raw.get("visitante") or "").strip(),
                round_number=int(raw.get("rodada") or 0),
            )
        )
    return out


def known_final_ids() -> set[str]:
    payload = load_json(RESULTADOS_PATH, {})
    rows = payload.get("resultados") if isinstance(payload, Mapping) else []
    return {
        str(row.get("event_id") or row.get("id") or "").strip()
        for row in (rows or [])
        if isinstance(row, Mapping) and str(row.get("event_id") or row.get("id") or "").strip()
    }


def espn_probe(games: Sequence[Game], now: datetime, before: int, after: int) -> tuple[dict[str, dict[str, Any]], list[str]]:
    relevant = [g for g in games if g.kickoff - timedelta(minutes=before) <= now <= g.kickoff + timedelta(minutes=after)]
    groups: dict[str, list[Game]] = {}
    for game in relevant:
        groups.setdefault(game.kickoff.strftime("%Y%m%d"), []).append(game)
    states: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for day, group in groups.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?dates={day}&limit=100"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; BrasileiraoAlmoco-Orquestrador/1.0)",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"ESPN {day}: {type(exc).__name__}: {exc}")
            continue
        wanted = {g.event_id for g in group}
        for event in data.get("events") or []:
            eid = str(event.get("id") or "")
            if eid not in wanted:
                continue
            st = ((event.get("status") or {}).get("type") or {})
            state = str(st.get("state") or "").lower()
            if bool(st.get("completed")):
                state = "post"
            if state not in {"pre", "in", "post"}:
                state = ""
            home = away = None
            comps = event.get("competitions") or []
            comp = comps[0] if comps and isinstance(comps[0], Mapping) else {}
            for competitor in comp.get("competitors") or []:
                if not isinstance(competitor, Mapping):
                    continue
                side = str(competitor.get("homeAway") or "").lower()
                value = score_value(competitor.get("score"))
                if side == "home":
                    home = value
                elif side == "away":
                    away = value
            states[eid] = {"state": state, "home_score": home, "away_score": away}
    return states, errors


def github_runs(token: str, repo: str, branch: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    if not token or not repo:
        return [], "histórico GitHub indisponível: token/repositório ausentes"
    target = max(20, min(int(limit or 200), 500))
    rows: list[dict[str, Any]] = []
    page = 1
    try:
        while len(rows) < target:
            query = urllib.parse.urlencode({"branch": branch, "per_page": 100, "page": page})
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/runs?{query}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                    "User-Agent": "BrasileiraoAlmoco-Orquestrador/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            batch = [dict(x) for x in (payload.get("workflow_runs") or []) if isinstance(x, Mapping)]
            rows.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return rows[:target], ""
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return rows, f"histórico GitHub parcialmente indisponível: {type(exc).__name__}: {exc}"


def run_time(run: Mapping[str, Any], tz: ZoneInfo) -> datetime | None:
    return parse_dt(run.get("run_started_at") or run.get("created_at") or run.get("updated_at"), tz)


def last_run(runs: Sequence[Mapping[str, Any]], name: str, tz: ZoneInfo, *, success_only: bool = False, title_contains: str = "") -> tuple[datetime | None, Mapping[str, Any] | None]:
    needle = title_contains.lower().strip()
    found: list[tuple[datetime, Mapping[str, Any]]] = []
    for run in runs:
        if str(run.get("name") or "") != name:
            continue
        if success_only and str(run.get("conclusion") or "") != "success":
            continue
        if needle and needle not in str(run.get("display_title") or "").lower():
            continue
        when = run_time(run, tz)
        if when:
            found.append((when, run))
    if not found:
        return None, None
    found.sort(key=lambda x: x[0], reverse=True)
    return found[0]


def active_writer(runs: Sequence[Mapping[str, Any]], current_run_id: str = "") -> Mapping[str, Any] | None:
    for run in runs:
        if current_run_id and str(run.get("id") or "") == current_run_id:
            continue
        if str(run.get("name") or "") not in REPO_WRITERS:
            continue
        if str(run.get("status") or "") in {"queued", "in_progress", "waiting", "pending", "requested"}:
            return run
    return None


def artifact_fallback_runs(tz: ZoneInfo) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    def add(name: str, value: Any, title: str = "") -> None:
        dt = parse_dt(value, tz)
        if dt:
            out.append({"name": name, "status": "completed", "conclusion": "success", "created_at": dt.isoformat(), "display_title": title or name, "synthetic": True})
    status = load_json(STATUS_PATH, {})
    add(WORKFLOW_MAIN, status.get("ultimo_sucesso") if isinstance(status, Mapping) else None)
    ap = load_json(APURACAO_PATH, {})
    add(WORKFLOW_APURAR, ap.get("atualizado_em") if isinstance(ap, Mapping) else None)
    pub = load_json(PUBLIC_AUDIT_PATH, {})
    add(WORKFLOW_PUBLICOS, pub.get("gerado_em") if isinstance(pub, Mapping) else None)
    mm = load_json(MM_PATH, {})
    add(WORKFLOW_MM, mm.get("atualizado_em") if isinstance(mm, Mapping) else None)
    tv = load_json(TV_AUDIT_PATH, {})
    add(WORKFLOW_TV, tv.get("atualizado_em") if isinstance(tv, Mapping) else None, "Transmissões · tv")
    return out


def main_decision(config: Mapping[str, Any], now: datetime, games: Sequence[Game], states: Mapping[str, Mapping[str, Any]], probe_errors: Sequence[str], final_ids: set[str], runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    cfg = config["atualizar_brasileirao"]
    last_success, _ = last_run(runs, WORKFLOW_MAIN, tz, success_only=True)
    last_any, _ = last_run(runs, WORKFLOW_MAIN, tz)
    before = int(cfg.get("sondagem_antes_minutos") or 45)
    after = int(cfg.get("sondagem_depois_minutos") or 240)
    retry = int(cfg.get("retentativa_final_pendente_minutos") or 10)
    estimated = int(cfg.get("fallback_final_estimado_minutos") or 105)

    final_pending: list[Game] = []
    fallback: list[Game] = []
    imminent: list[Game] = []
    for game in games:
        if not (game.kickoff - timedelta(minutes=before) <= now <= game.kickoff + timedelta(minutes=after)):
            continue
        known = game.event_id in final_ids
        state = str((states.get(game.event_id) or {}).get("state") or "")
        if state == "post" and not known:
            final_pending.append(game)
        elif state == "pre" and game.kickoff >= now and game.kickoff <= now + timedelta(minutes=before):
            imminent.append(game)
        elif not state and not known and now >= game.kickoff + timedelta(minutes=estimated):
            fallback.append(game)

    if final_pending:
        labels = ", ".join(x.label for x in final_pending[:4])
        return Decision("atualizar_brasileirao", f"ESPN marcou FINAL ainda não incorporado: {labels}.", details=tuple(probe_errors[:3]))
    if fallback and minutes_since(last_any, now) >= retry:
        labels = ", ".join(x.label for x in fallback[:4])
        return Decision("atualizar_brasileirao", f"Contingência pós-jogo: {labels} passou da duração estimada e ainda não consta como resultado final.", details=tuple(probe_errors[:3]))

    # Estado 'in' e mudança de placar são deliberadamente ignorados aqui.
    if imminent and minutes_since(last_success, now) >= int(cfg.get("intervalo_pre_jogo_minutos") or 60):
        return Decision("atualizar_brasileirao", f"Pré-jogo: sincronização de segurança antes de {', '.join(x.label for x in imminent[:4])}.")

    after_hhmm = str(cfg.get("manutencao_diaria_apos") or "05:10")
    if time_reached(now, after_hhmm) and (last_success is None or last_success.date() < now.date()):
        return Decision("atualizar_brasileirao", "Manutenção diária de segurança: ainda não houve atualização completa bem-sucedida hoje.")
    return None


def apuracao_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    resultados = load_json(RESULTADOS_PATH, {})
    apuracao = load_json(APURACAO_PATH, {})
    ranking = load_json(RANKING_PATH, {})
    apostas_cfg = load_json(APOSTAS_CONFIG_PATH, {})
    rodada_inicial = int((apostas_cfg or {}).get("rodadaInicialApostas") or 20) if isinstance(apostas_cfg, Mapping) else 20

    valid = (
        isinstance(apuracao, Mapping) and apuracao.get("schema_version") == 4
        and isinstance(ranking, Mapping) and ranking.get("schema_version") == 4
    )
    stale = not valid
    divergencias: list[str] = []
    if valid:
        finais_por_rodada: dict[int, int] = {}
        for row in (resultados.get("resultados") or []) if isinstance(resultados, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            rodada = int(row.get("rodada") or 0)
            if rodada >= rodada_inicial:
                finais_por_rodada[rodada] = finais_por_rodada.get(rodada, 0) + 1
        ap_por_rodada = {
            int(row.get("rodada") or 0): int(row.get("jogos_apurados") or 0)
            for row in (apuracao.get("rodadas") or [])
            if isinstance(row, Mapping) and int(row.get("rodada") or 0) >= rodada_inicial
        }
        for rodada, esperados in sorted(finais_por_rodada.items()):
            atuais = int(ap_por_rodada.get(rodada, 0))
            if atuais != esperados:
                divergencias.append(f"R{rodada}: apurados={atuais}, resultados={esperados}")
        stale = bool(divergencias)

    if not stale:
        return None
    last_any, _ = last_run(runs, WORKFLOW_APURAR, tz)
    retry = int(config["apuracao"].get("retentativa_minutos") or 10)
    if minutes_since(last_any, now) < retry:
        return None
    detalhe = "; ".join(divergencias[:4]) if divergencias else "artefato de apuração/ranking ausente ou inválido"
    return Decision("apurar_apostas", f"A apuração está atrás dos resultados do bolão ({detalhe}); reprocessar somente a pontuação.")


def af_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    resultados = load_json(RESULTADOS_PATH, {})
    finais = resultados.get("resultados") if isinstance(resultados, Mapping) else []
    total = len(finais or [])
    aud = load_json(AUD_AF_PATH, {})
    prob = load_json(PROB_BOLAO_PATH, {})
    integ = aud.get("integridade") if isinstance(aud, Mapping) else {}
    count_af = int((integ or {}).get("partidas_2026_concluidas") or -1) if isinstance(integ, Mapping) else -1
    status_ok = isinstance(aud, Mapping) and str(aud.get("status") or "") == "ok" and isinstance(prob, Mapping) and str(prob.get("status") or "") == "ok"
    if status_ok and count_af == total:
        return None
    last_any, _ = last_run(runs, WORKFLOW_MAIN, tz)
    retry = int(config["af_previsao"].get("retentativa_minutos") or 20)
    if minutes_since(last_any, now) < retry:
        return None
    return Decision("atualizar_brasileirao_forcar_af", f"AF/Probabilidade do bolão está defasado: resultados={total}, AF reconhece={count_af}; forçar recomputação.")


def attendance_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            n = int(round(float(value)))
        else:
            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if not digits:
                return None
            n = int(digits)
    except (TypeError, ValueError):
        return None
    return n if 100 <= n <= 250000 else None


def final_time(row: Mapping[str, Any], tz: ZoneInfo) -> datetime | None:
    exact = parse_dt(row.get("finalizado_em"), tz)
    if exact:
        return exact
    kickoff = parse_dt(row.get("data_iso"), tz)
    return kickoff + timedelta(minutes=115) if kickoff else None


def retry_interval(age_hours: float, rows: Sequence[Mapping[str, Any]], default: int) -> int:
    for row in rows:
        try:
            if age_hours <= float(row.get("ate_horas")):
                return int(row.get("minutos"))
        except (TypeError, ValueError):
            continue
    return default


def pending_publics(config: Mapping[str, Any], now: datetime, tz: ZoneInfo) -> list[tuple[dict[str, Any], datetime]]:
    results = load_json(RESULTADOS_PATH, {})
    details_payload = load_json(DETAILS_PATH, {})
    comp_payload = load_json(PUBLIC_COMPLEMENTS_PATH, {})
    details = details_payload.get("jogos") if isinstance(details_payload, Mapping) else {}
    comps = comp_payload.get("jogos") if isinstance(comp_payload, Mapping) else {}
    if not isinstance(details, Mapping): details = {}
    if not isinstance(comps, Mapping): comps = {}
    min_age = int(config["publicos"].get("primeira_tentativa_apos_final_minutos") or 15)
    out: list[tuple[dict[str, Any], datetime]] = []
    for raw in (results.get("resultados") or []) if isinstance(results, Mapping) else []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        eid = str(row.get("event_id") or "").strip()
        if not eid:
            continue
        detail = details.get(eid) if isinstance(details, Mapping) else None
        comp = comps.get(eid) if isinstance(comps, Mapping) else None
        if attendance_number((detail or {}).get("publico") if isinstance(detail, Mapping) else None) or attendance_number((comp or {}).get("publico") if isinstance(comp, Mapping) else None):
            continue
        finished = final_time(row, tz)
        if finished and now >= finished + timedelta(minutes=min_age):
            out.append((row, finished))
    out.sort(key=lambda x: x[1])
    return out


def public_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    pending = pending_publics(config, now, tz)
    if not pending:
        return None
    last_any, _ = last_run(runs, WORKFLOW_PUBLICOS, tz)
    oldest_row, oldest_final = pending[0]
    age_h = max(0.0, (now - oldest_final).total_seconds() / 3600.0)
    interval = retry_interval(age_h, config["publicos"].get("intervalos_retentativa") or [], 1440)
    if last_any and last_any >= oldest_final and minutes_since(last_any, now) < interval:
        return None
    eid = str(oldest_row.get("event_id") or "")
    return Decision("publicos", f"Há {len(pending)} jogo(s) FINAL sem público; janela/backoff de coleta vencido ({interval} min).", event_id=eid, mode="incremental")


def linked_mm_ids() -> set[str]:
    out: set[str] = set()
    for path in (MM_PATH, MM_MANUAL_PATH):
        payload = load_json(path, {})
        games = payload.get("jogos") if isinstance(payload, Mapping) else {}
        if not isinstance(games, Mapping):
            continue
        for key, row in games.items():
            eid = str((row or {}).get("event_id") or key or "").strip() if isinstance(row, Mapping) else str(key)
            if eid:
                out.add(eid)
    return out


def pending_mm(config: Mapping[str, Any], now: datetime, tz: ZoneInfo) -> list[tuple[dict[str, Any], datetime]]:
    results = load_json(RESULTADOS_PATH, {})
    linked = linked_mm_ids()
    min_age = int(config["melhores_momentos"].get("primeira_tentativa_apos_final_minutos") or 10)
    out: list[tuple[dict[str, Any], datetime]] = []
    for raw in (results.get("resultados") or []) if isinstance(results, Mapping) else []:
        if not isinstance(raw, Mapping):
            continue
        eid = str(raw.get("event_id") or "").strip()
        if not eid or eid in linked:
            continue
        finished = final_time(raw, tz)
        if finished and now >= finished + timedelta(minutes=min_age):
            out.append((dict(raw), finished))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def mm_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    pending = pending_mm(config, now, tz)
    if not pending:
        return None
    last_any, _ = last_run(runs, WORKFLOW_MM, tz)
    # Prioriza o FINAL mais recente sem vídeo.
    row, finished = pending[0]
    age_h = max(0.0, (now - finished).total_seconds() / 3600.0)
    interval = retry_interval(age_h, config["melhores_momentos"].get("intervalos_retentativa") or [], 720)
    # Se nunca houve busca depois deste FINAL, é a primeira tentativa e entra já aos 10 min.
    if last_any is None or last_any < finished:
        return Decision("melhores_momentos", f"Primeira busca de melhores momentos após FINAL: {row.get('mandante',{}).get('nome','')} x {row.get('visitante',{}).get('nome','')}.", event_id=str(row.get("event_id") or ""), round_number=str(row.get("rodada") or ""), mode="incremental")
    if minutes_since(last_any, now) >= interval:
        return Decision("melhores_momentos", f"Ainda há {len(pending)} jogo(s) sem melhores momentos; backoff atual {interval} min venceu.", event_id=str(row.get("event_id") or ""), round_number=str(row.get("rodada") or ""), mode="incremental")
    return None


def artifact_age_hours(path: Path, now: datetime, tz: ZoneInfo, *fields: str) -> float | None:
    payload = load_json(path, {})
    if not isinstance(payload, Mapping):
        return None
    for field in fields:
        stamp = parse_dt(payload.get(field), tz)
        if stamp is not None:
            return max(0.0, (now - stamp).total_seconds() / 3600.0)
    return None


def artifact_health_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    """Recupera artefatos que ficaram velhos apesar dos workflows normais.

    A checagem é deliberadamente simples e local: não cria novas fontes nem
    substitui as decisões esportivas. Ela só detecta quando uma auditoria que
    deveria acompanhar o site parou de ser renovada.
    """
    cfg = config.get("artefatos") or {}
    geral_max = float(cfg.get("auditoria_geral_max_horas") or 30)
    tv_max = float(cfg.get("auditoria_transmissoes_max_horas") or 36)

    geral_age = artifact_age_hours(GENERAL_AUDIT_PATH, now, tz, "gerado_em", "atualizado_em")
    if geral_age is None or geral_age > geral_max:
        last_main, _ = last_run(runs, WORKFLOW_MAIN, tz)
        # Evita martelar o workflow quando ele acabou de tentar regenerar a auditoria.
        if minutes_since(last_main, now) >= 60:
            motivo = (
                "Auditoria geral ainda não existe; executar atualização completa para criá-la."
                if geral_age is None
                else f"Auditoria geral está envelhecida ({geral_age:.1f}h > {geral_max:.0f}h); regenerar o snapshot e a auditoria."
            )
            return Decision("atualizar_brasileirao", motivo)

    tv_age = artifact_age_hours(TV_AUDIT_PATH, now, tz, "atualizado_em", "gerado_em")
    if tv_age is not None and tv_age > tv_max and time_reached(now, str(config["transmissoes"].get("tv_diaria_apos") or "06:30")):
        last_tv, _ = last_run(runs, WORKFLOW_TV, tz)
        if minutes_since(last_tv, now) >= 60:
            return Decision("transmissoes_tv", f"Auditoria de transmissões está envelhecida ({tv_age:.1f}h > {tv_max:.0f}h); refazer grade futura.", mode="tv")
    return None


def tv_decision(config: Mapping[str, Any], now: datetime, runs: Sequence[Mapping[str, Any]], tz: ZoneInfo) -> Decision | None:
    after = str(config["transmissoes"].get("tv_diaria_apos") or "06:30")
    if not time_reached(now, after):
        return None
    last_tv, _ = last_run(runs, WORKFLOW_TV, tz, success_only=True, title_contains="tv")
    if last_tv is None or last_tv.date() < now.date():
        return Decision("transmissoes_tv", "Atualização diária da grade futura de TV ainda não executada hoje.", mode="tv")
    return None


def decide(config: Mapping[str, Any], now: datetime, games: Sequence[Game], states: Mapping[str, Mapping[str, Any]], probe_errors: Sequence[str], runs: Sequence[Mapping[str, Any]], tz: ZoneInfo, current_run_id: str = "") -> Decision:
    if bool(config.get("github", {}).get("bloquear_se_writer_ativo", True)):
        active = active_writer(runs, current_run_id)
        if active:
            return Decision("none", f"Aguardando workflow escritor já ativo: {active.get('name')} ({active.get('status')}).")

    finals = known_final_ids()
    main = main_decision(config, now, games, states, probe_errors, finals, runs, tz)
    if main:
        return main
    ap = apuracao_decision(config, now, runs, tz)
    if ap:
        return ap
    af = af_decision(config, now, runs, tz)
    if af:
        return af
    health = artifact_health_decision(config, now, runs, tz)
    if health:
        return health
    pub = public_decision(config, now, runs, tz)
    if pub:
        return pub
    mm = mm_decision(config, now, runs, tz)
    if mm:
        return mm
    tv = tv_decision(config, now, runs, tz)
    if tv:
        return tv
    return Decision("none", "Estado consistente; nenhum workflow pesado precisa rodar agora.", details=tuple(probe_errors[:3]))


def write_output(path: str, decision: Decision) -> None:
    if not path:
        return
    values = {
        "acao": decision.action,
        "motivo": decision.reason.replace("\n", " ").replace("\r", " "),
        "event_id": decision.event_id,
        "rodada": decision.round_number,
        "modo": decision.mode,
    }
    with open(path, "a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")


def self_test() -> int:
    tz = ZoneInfo("America/Sao_Paulo")
    config = deep_merge(DEFAULT_CONFIG, {})
    now = datetime(2026, 8, 9, 21, 30, tzinfo=tz)
    game = Game("1", datetime(2026, 8, 9, 19, 30, tzinfo=tz), "Flamengo", "Vitória", 22)
    assert time_reached(now, "06:30")
    assert retry_interval(1, config["publicos"]["intervalos_retentativa"], 1440) == 30
    assert retry_interval(3, config["melhores_momentos"]["intervalos_retentativa"], 720) == 30
    recent = [{"name": WORKFLOW_MAIN, "status": "completed", "conclusion": "success", "created_at": "2026-08-10T00:25:00Z"}]
    # Gol AO VIVO não dispara pipeline.
    assert main_decision(config, now, [game], {"1": {"state": "in", "home_score": 1, "away_score": 0}}, [], set(), recent, tz) is None
    # FINAL não incorporado dispara imediatamente.
    dec = main_decision(config, now, [game], {"1": {"state": "post", "home_score": 2, "away_score": 0}}, [], set(), recent, tz)
    assert dec and dec.action == "atualizar_brasileirao"
    # Writer ativo bloqueia novo dispatch.
    assert active_writer(recent + [{"name": WORKFLOW_MM, "status": "in_progress", "id": 3}]) is not None

    # Saúde de artefatos: ausente/velho recupera, recente não interfere.
    import tempfile
    global GENERAL_AUDIT_PATH, TV_AUDIT_PATH
    old_general, old_tv = GENERAL_AUDIT_PATH, TV_AUDIT_PATH
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        GENERAL_AUDIT_PATH = base / "auditoria-geral.json"
        TV_AUDIT_PATH = base / "auditoria-tv.json"
        sem_run_recente: list[dict[str, Any]] = []
        health = artifact_health_decision(config, now, sem_run_recente, tz)
        assert health and health.action == "atualizar_brasileirao"
        GENERAL_AUDIT_PATH.write_text(json.dumps({"gerado_em": now.isoformat()}), encoding="utf-8")
        TV_AUDIT_PATH.write_text(json.dumps({"atualizado_em": now.isoformat()}), encoding="utf-8")
        assert artifact_health_decision(config, now, sem_run_recente, tz) is None
        GENERAL_AUDIT_PATH.write_text(json.dumps({"gerado_em": (now - timedelta(hours=31)).isoformat()}), encoding="utf-8")
        health = artifact_health_decision(config, now, sem_run_recente, tz)
        assert health and health.action == "atualizar_brasileirao"
        GENERAL_AUDIT_PATH.write_text(json.dumps({"gerado_em": now.isoformat()}), encoding="utf-8")
        TV_AUDIT_PATH.write_text(json.dumps({"atualizado_em": (now - timedelta(hours=37)).isoformat()}), encoding="utf-8")
        health = artifact_health_decision(config, now, sem_run_recente, tz)
        assert health and health.action == "transmissoes_tv"
    GENERAL_AUDIT_PATH, TV_AUDIT_PATH = old_general, old_tv

    print("OK self-test: FINAL, gol sem pipeline, backoff, artefatos envelhecidos e exclusão mútua validados.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--sem-rede", action="store_true")
    parser.add_argument("--agora", default="")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    raw = load_json(CONFIG_PATH, {})
    config = deep_merge(DEFAULT_CONFIG, raw if isinstance(raw, Mapping) else {})
    tz = ZoneInfo(str(config.get("timezone") or "America/Sao_Paulo"))
    now = now_local(tz, args.agora)
    games = load_games(tz)

    if args.sem_rede:
        states: dict[str, dict[str, Any]] = {}
        probe_errors = ["sondagem ESPN/GitHub desativada por --sem-rede"]
        runs = artifact_fallback_runs(tz)
    else:
        before = int(config["atualizar_brasileirao"].get("sondagem_antes_minutos") or 45)
        after = int(config["atualizar_brasileirao"].get("sondagem_depois_minutos") or 240)
        states, probe_errors = espn_probe(games, now, before, after)
        runs, gh_error = github_runs(
            os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "",
            os.environ.get("GITHUB_REPOSITORY") or "",
            str(config.get("github", {}).get("branch") or "main"),
            int(config.get("github", {}).get("historico_runs") or 200),
        )
        if gh_error:
            probe_errors.append(gh_error)
            runs = list(runs) + artifact_fallback_runs(tz)

    decision = decide(config, now, games, states, probe_errors, runs, tz, str(os.environ.get("GITHUB_RUN_ID") or ""))
    write_output(args.github_output, decision)
    print(json.dumps({
        "agora": now.isoformat(),
        "acao": decision.action,
        "motivo": decision.reason,
        "event_id": decision.event_id,
        "rodada": decision.round_number,
        "modo": decision.mode,
        "detalhes": list(decision.details),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

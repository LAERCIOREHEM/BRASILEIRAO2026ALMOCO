#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditoria cruzada e determinística do Brasileirão 2026 Almoço.

Cruza, em uma única passada, calendário canônico, ESPN, agenda, resultados,
tabela, detalhes/estatísticas, públicos, melhores momentos, transmissões e AF.
A auditoria nunca corrige placares ou cálculos. Ela classifica inconsistências
estruturais e só envia e-mail quando existe problema CRÍTICO novo.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=-3))
OUT = ROOT / "dados-br" / "auditoria-geral.json"
DEFAULT_EMAIL_SENDER = "Auditoria · Brasileirão 2026 <avisos@brasileirao2026almoco.com.br>"

FILES = {
    "calendario": ROOT / "dados-br" / "calendario-completo.json",
    "eventos": ROOT / "espn_eventos.json",
    "jogos": ROOT / "jogos.json",
    "resultados": ROOT / "resultados.json",
    "tabela": ROOT / "tabela.json",
    "apuracao": ROOT / "dados-br" / "apuracao.json",
    "ranking_apostas": ROOT / "dados-br" / "ranking-apostas.json",
    "aud_blocos": ROOT / "dados-br" / "auditoria-blocos-apostas.json",
    "detalhes": ROOT / "dados-br" / "jogos-detalhes.json",
    "aud_detalhes": ROOT / "dados-br" / "auditoria-jogos-detalhes.json",
    "aud_cobertura": ROOT / "dados-br" / "auditoria-cobertura-resultados.json",
    "aud_publicos": ROOT / "dados-br" / "auditoria-publicos.json",
    "aud_mm": ROOT / "dados-br" / "auditoria-melhores-momentos.json",
    "aud_tv": ROOT / "dados-br" / "auditoria-transmissoes-tv.json",
    "aud_af": ROOT / "dados-br" / "auditoria-probabilidades.json",
    "status": ROOT / "dados-br" / "status-atualizacao.json",
}


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
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def team_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("nome") or value.get("time") or value.get("displayName") or "").strip()
    return str(value or "").strip()


def matchup(row: Mapping[str, Any]) -> tuple[str, str]:
    return team_name(row.get("mandante")), team_name(row.get("visitante"))


def issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    out = {"codigo": code, "mensagem": message}
    if details:
        out["detalhes"] = details
    return out


def stable_fingerprint(items: list[dict[str, Any]]) -> str:
    """Fingerprint do incidente, não do relógio.

    Campos voláteis de idade/timestamp são removidos para que o mesmo problema
    persistente não gere um novo e-mail apenas porque passou mais uma hora.
    """
    volatile = {"horas", "idade_horas", "gerado_em", "atualizado_em", "timestamp"}

    def limpar(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {k: limpar(v) for k, v in value.items() if k not in volatile}
        if isinstance(value, list):
            return [limpar(v) for v in value]
        return value

    raw = json.dumps(limpar(items), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def age_hours(payload: Mapping[str, Any], *fields: str, now: datetime) -> float | None:
    for field in fields:
        dt = parse_dt(payload.get(field))
        if dt:
            return max(0.0, (now - dt).total_seconds() / 3600.0)
    return None


def final_time(row: Mapping[str, Any]) -> datetime | None:
    end = parse_dt(row.get("finalizado_em"))
    if end:
        return end
    start = parse_dt(row.get("data_iso"))
    return start + timedelta(hours=2) if start else None


def audit(root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    now = now or now_brt()
    paths = {key: (root / path.relative_to(ROOT)) for key, path in FILES.items()}
    data = {key: load_json(path, {}) for key, path in paths.items()}

    critical: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    infos: list[dict[str, Any]] = []

    cal_rows = list((data["calendario"] or {}).get("jogos") or (data["calendario"] or {}).get("partidas") or [])
    table_rows = list((data["tabela"] or {}).get("tabela") or [])
    expected_teams = {str(x.get("time") or "").strip() for x in table_rows if isinstance(x, Mapping)}
    by_round: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    by_matchup: dict[tuple[str, str], Mapping[str, Any]] = {}
    pair_count: Counter[frozenset[str]] = Counter()
    club_count: Counter[str] = Counter()
    duplicate_matchups: list[tuple[str, str]] = []
    for row in cal_rows:
        if not isinstance(row, Mapping):
            continue
        r = int(row.get("rodada") or 0)
        home, away = matchup(row)
        by_round[r].append(row)
        if home and away:
            if (home, away) in by_matchup:
                duplicate_matchups.append((home, away))
            by_matchup[(home, away)] = row
            club_count.update((home, away))
            pair_count[frozenset((home, away))] += 1

    bad_rounds = []
    for r in range(1, 39):
        arr = by_round.get(r, [])
        clubs = [name for row in arr for name in matchup(row) if name]
        if len(arr) != 10 or len(clubs) != 20 or len(set(clubs)) != 20 or (expected_teams and set(clubs) != expected_teams):
            bad_rounds.append(r)
    bad_clubs = {club: club_count.get(club, 0) for club in expected_teams if club_count.get(club, 0) != 38}
    bad_pairs = [sorted(p) for p, count in pair_count.items() if len(p) == 2 and count != 2]
    if len(cal_rows) != 380 or bad_rounds or bad_clubs or bad_pairs or duplicate_matchups:
        critical.append(issue(
            "CALENDARIO_ESTRUTURAL",
            "A matriz canônica do campeonato perdeu uma invariável estrutural.",
            partidas=len(cal_rows), rodadas_invalidas=bad_rounds, clubes_invalidos=bad_clubs,
            confrontos_invalidos=bad_pairs[:20], mandos_duplicados=duplicate_matchups[:20],
        ))

    # A rodada estrutural é a autoridade para todos os artefatos operacionais.
    round_diffs: dict[str, list[dict[str, Any]]] = {}
    for key, list_key in (("eventos", "eventos"), ("jogos", "jogos"), ("resultados", "resultados")):
        rows = list((data[key] or {}).get(list_key) or [])
        diffs = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            home, away = matchup(row)
            canonical = by_matchup.get((home, away))
            if not canonical:
                continue
            current = int(row.get("rodada") or 0)
            expected = int(canonical.get("rodada") or 0)
            if current != expected:
                diffs.append({"event_id": str(row.get("event_id") or row.get("id") or ""), "jogo": f"{home} x {away}", "rodada": current, "esperada": expected})
        round_diffs[key] = diffs
        if diffs:
            critical.append(issue(
                f"RODADA_DIVERGENTE_{key.upper()}",
                f"{len(diffs)} registro(s) de {key} divergem da rodada canônica.",
                exemplos=diffs[:20],
            ))

    # Resultados físicos e tabela precisam representar o mesmo número de partidas.
    result_rows = [r for r in ((data["resultados"] or {}).get("resultados") or []) if isinstance(r, Mapping)]
    result_matchups = [matchup(r) for r in result_rows if all(matchup(r))]
    duplicate_results = [list(k) for k, n in Counter(result_matchups).items() if n > 1]
    ids = [str(r.get("event_id") or r.get("id") or "").strip() for r in result_rows]
    duplicate_ids = [k for k, n in Counter(i for i in ids if i).items() if n > 1]
    table_games_sum = sum(int(row.get("jogos") or 0) for row in table_rows if isinstance(row, Mapping))
    table_physical_games = table_games_sum // 2 if table_games_sum % 2 == 0 else -1
    if duplicate_results or duplicate_ids:
        critical.append(issue(
            "RESULTADOS_DUPLICADOS",
            "Há resultado físico/event_id duplicado no snapshot publicado.",
            confrontos=duplicate_results[:20], event_ids=duplicate_ids[:20],
        ))
    if table_physical_games != len(set(result_matchups)):
        critical.append(issue(
            "TABELA_RESULTADOS_DIVERGENTES",
            "A quantidade de partidas contabilizadas na tabela diverge dos resultados físicos.",
            tabela_partidas=table_physical_games, resultados_fisicos=len(set(result_matchups)), resultados_registros=len(result_rows),
        ))

    # Apuração do bolão: a partir da R20, jogos apurados precisam acompanhar
    # exatamente os resultados finais publicados, sem adiantar rodada futura.
    apuracao = data["apuracao"] if isinstance(data["apuracao"], Mapping) else {}
    ranking_apostas = data["ranking_apostas"] if isinstance(data["ranking_apostas"], Mapping) else {}
    finais_por_rodada: Counter[int] = Counter(
        int(row.get("rodada") or 0) for row in result_rows if int(row.get("rodada") or 0) >= 20
    )
    total_finais_bolao = sum(finais_por_rodada.values())
    if not apuracao or int(apuracao.get("schema_version") or 0) != 4:
        critical.append(issue("APURACAO_AUSENTE_INVALIDA", "A apuração do bolão está ausente ou fora do schema 4."))
    else:
        ap_por_rodada = {
            int(row.get("rodada") or 0): int(row.get("jogos_apurados") or 0)
            for row in (apuracao.get("rodadas") or []) if isinstance(row, Mapping)
        }
        ap_diffs = []
        for rodada in range(20, 39):
            esperado = int(finais_por_rodada.get(rodada, 0))
            atual = int(ap_por_rodada.get(rodada, 0))
            if atual != esperado:
                ap_diffs.append({"rodada": rodada, "resultados_finais": esperado, "jogos_apurados": atual})
        resumo_ap = apuracao.get("resumo") if isinstance(apuracao.get("resumo"), Mapping) else {}
        total_declarado = int((resumo_ap or {}).get("jogos_apurados_publicados") or 0)
        if ap_diffs or total_declarado != total_finais_bolao:
            critical.append(issue(
                "APURACAO_RESULTADOS_DIVERGENTES",
                "A pontuação do bolão não acompanha exatamente os resultados finais publicados desde a R20.",
                total_resultados_finais=total_finais_bolao, total_apurado_declarado=total_declarado,
                rodadas=ap_diffs[:20],
            ))
    if not ranking_apostas or int(ranking_apostas.get("schema_version") or 0) != 4:
        critical.append(issue("RANKING_APOSTAS_AUSENTE_INVALIDO", "O ranking do bolão está ausente ou fora do schema 4."))
    else:
        resumo_rank = ranking_apostas.get("resumo") if isinstance(ranking_apostas.get("resumo"), Mapping) else {}
        total_rank = int((resumo_rank or {}).get("jogos_apurados_publicados") or 0)
        if total_rank != total_finais_bolao:
            critical.append(issue(
                "RANKING_APOSTAS_DEFASADO",
                "O ranking geral do bolão declara quantidade de jogos diferente dos resultados finais publicados.",
                resultados_finais=total_finais_bolao, ranking_jogos=total_rank,
            ))

    # Integridade dos seis blocos é auditada separadamente e agregada aqui.
    # Um bloco anterior parcial junto de um bloco seguinte aberto é um estado
    # esperado, não uma inconsistência.
    aud_blocos = data["aud_blocos"] if isinstance(data["aud_blocos"], Mapping) else {}
    blocos_status = str(aud_blocos.get("status") or "").lower()
    blocos_resumo = aud_blocos.get("resumo") if isinstance(aud_blocos.get("resumo"), Mapping) else {}
    if not aud_blocos:
        warnings.append(issue("AUDITORIA_BLOCOS_AUSENTE", "A auditoria dos blocos de apostas ainda não foi materializada."))
    elif blocos_status == "critical":
        critical.append(issue(
            "BLOCOS_APOSTAS_INTEGRIDADE",
            "A automação dos blocos de apostas detectou uma inconsistência crítica.",
            problemas=(aud_blocos.get("criticos") or [])[:20],
        ))
    elif blocos_status == "warning":
        warnings.append(issue(
            "BLOCOS_APOSTAS_ATENCAO",
            "A automação dos blocos possui pendências não críticas.",
            avisos=(aud_blocos.get("avisos") or [])[:20],
        ))

    # Cobertura de estatísticas: ausência isolada é warning, não corrupção.
    details_games = (data["detalhes"] or {}).get("jogos") or {}
    if not isinstance(details_games, Mapping):
        details_games = {}
    missing_stats = []
    for row in result_rows:
        eid = str(row.get("event_id") or row.get("id") or "")
        det = details_games.get(eid) if eid else None
        stats = (det or {}).get("stats") if isinstance(det, Mapping) else None
        if not stats:
            home, away = matchup(row)
            missing_stats.append({"event_id": eid, "jogo": f"{home} x {away}", "rodada": int(row.get("rodada") or 0)})
    if missing_stats:
        warnings.append(issue(
            "ESTATISTICAS_AUSENTES",
            f"{len(missing_stats)} jogo(s) encerrado(s) ainda estão sem estatísticas avançadas.",
            exemplos=missing_stats[:30],
        ))

    aud_det = data["aud_detalhes"] if isinstance(data["aud_detalhes"], Mapping) else {}
    reported_snapshot_missing = aud_det.get("total_sem_estatisticas_no_snapshot")
    if reported_snapshot_missing is not None and int(reported_snapshot_missing) != len(missing_stats):
        critical.append(issue(
            "AUDITORIA_DETALHES_INCOERENTE",
            "A auditoria de detalhes não fecha com o snapshot de jogos-detalhes.",
            auditoria=int(reported_snapshot_missing), recalculado=len(missing_stats),
        ))

    # Públicos: o coletor já é fonte de verdade; falha ampla vira crítica.
    aud_pub = data["aud_publicos"] if isinstance(data["aud_publicos"], Mapping) else {}
    missing_public = int(aud_pub.get("total_partidas_fisicas_sem_publico") or aud_pub.get("total_sem_publico") or 0)
    if missing_public:
        level = critical if missing_public >= 8 else warnings
        level.append(issue(
            "PUBLICOS_PENDENTES",
            f"{missing_public} partida(s) física(s) seguem sem público confirmado.",
            exemplos=(aud_pub.get("partidas_fisicas_sem_publico") or aud_pub.get("sem_publico") or [])[:20],
        ))

    # Melhores momentos: carência deliberada. >24h warning; >48h só vira crítico em lote.
    linked_ids: set[str] = set()
    for mm_name in ("melhores-momentos.json", "melhores-momentos-manual.json"):
        mm = load_json(root / "dados-br" / mm_name, {})
        games = mm.get("jogos") if isinstance(mm, Mapping) else {}
        if isinstance(games, Mapping):
            for key, row in games.items():
                if isinstance(row, Mapping):
                    linked_ids.add(str(row.get("event_id") or key or "").strip())
    old_24, old_48 = [], []
    for row in result_rows:
        eid = str(row.get("event_id") or row.get("id") or "").strip()
        if not eid or eid in linked_ids:
            continue
        ended = final_time(row)
        if not ended:
            continue
        age = (now - ended).total_seconds() / 3600
        home, away = matchup(row)
        item = {"event_id": eid, "jogo": f"{home} x {away}", "horas": round(age, 1)}
        if age >= 48:
            old_48.append(item)
        elif age >= 24:
            old_24.append(item)
    if old_24:
        warnings.append(issue("MELHORES_MOMENTOS_24H", f"{len(old_24)} jogo(s) estão sem vídeo há mais de 24h.", exemplos=old_24[:20]))
    if old_48:
        target = critical if len(old_48) >= 3 else warnings
        target.append(issue("MELHORES_MOMENTOS_48H", f"{len(old_48)} jogo(s) estão sem vídeo há mais de 48h.", exemplos=old_48[:20]))

    # Grade de TV: artefato diário envelhecido é recuperação operacional.
    aud_tv = data["aud_tv"] if isinstance(data["aud_tv"], Mapping) else {}
    tv_age = age_hours(aud_tv, "atualizado_em", "gerado_em", now=now)
    if tv_age is None:
        warnings.append(issue("AUDITORIA_TV_AUSENTE", "Auditoria de transmissões não possui timestamp válido."))
    elif tv_age > 72:
        critical.append(issue("AUDITORIA_TV_MUITO_ANTIGA", "A grade de transmissões está sem auditoria há mais de 72h.", horas=round(tv_age, 1)))
    elif tv_age > 36:
        warnings.append(issue("AUDITORIA_TV_ANTIGA", "A grade de transmissões está sem auditoria há mais de 36h.", horas=round(tv_age, 1)))
    tv_summary = aud_tv.get("resumo") if isinstance(aud_tv, Mapping) else {}
    if isinstance(tv_summary, Mapping):
        critical_tv = int(tv_summary.get("jogos_criticos_sem_transmissao_72h") or 0)
        if critical_tv >= 3:
            critical.append(issue("TRANSMISSOES_CRITICAS_PENDENTES", f"{critical_tv} jogos a menos de 72h estão sem transmissão confirmada."))
        elif critical_tv:
            warnings.append(issue("TRANSMISSOES_PENDENTES", f"{critical_tv} jogo(s) a menos de 72h estão sem transmissão confirmada."))

    # AF: só é crítico se o próprio artefato publicado disser que está inválido.
    aud_af = data["aud_af"] if isinstance(data["aud_af"], Mapping) else {}
    if aud_af and str(aud_af.get("status") or "").lower() not in {"ok", "preservado"}:
        critical.append(issue("AF_PREVISAO_INVALIDO", "A auditoria publicada do AF-Previsão não está em estado íntegro.", status=aud_af.get("status")))
    if aud_af:
        integ_af = aud_af.get("integridade") if isinstance(aud_af.get("integridade"), Mapping) else {}
        concluidos_af = (integ_af or {}).get("partidas_2026_concluidas")
        if concluidos_af is not None and int(concluidos_af) != len(set(result_matchups)):
            critical.append(issue(
                "AF_RESULTADOS_DIVERGENTES",
                "O AF-Previsão reconhece quantidade de partidas concluídas diferente do snapshot de resultados.",
                af_concluidos=int(concluidos_af), resultados_fisicos=len(set(result_matchups)),
            ))

    # Saúde/frescor do pipeline principal.
    status = data["status"] if isinstance(data["status"], Mapping) else {}
    last_success_age = age_hours(status, "ultimo_sucesso", "ultimo_snapshot_valido", now=now)
    if last_success_age is not None and last_success_age > 48:
        critical.append(issue("ATUALIZACAO_PRINCIPAL_CONGELADA", "O último snapshot principal bem-sucedido tem mais de 48h.", horas=round(last_success_age, 1)))
    elif last_success_age is not None and last_success_age > 30:
        warnings.append(issue("ATUALIZACAO_PRINCIPAL_ANTIGA", "O último snapshot principal bem-sucedido tem mais de 30h.", horas=round(last_success_age, 1)))

    if not critical and not warnings:
        infos.append(issue("SITE_INTEGRO", "Nenhuma inconsistência relevante foi detectada."))

    status_name = "critical" if critical else ("warning" if warnings else "ok")
    fp = stable_fingerprint(critical)
    return {
        "schema_version": 1,
        "gerado_em": now.isoformat(),
        "status": status_name,
        "fingerprint_critico": fp,
        "resumo": {
            "criticos": len(critical),
            "avisos": len(warnings),
            "informativos": len(infos),
            "calendario_partidas": len(cal_rows),
            "resultados_registros": len(result_rows),
            "resultados_fisicos": len(set(result_matchups)),
            "tabela_partidas": table_physical_games,
            "jogos_finais_bolao_desde_r20": total_finais_bolao,
            "jogos_apurados_bolao": int(((apuracao.get("resumo") or {}) if isinstance(apuracao, Mapping) else {}).get("jogos_apurados_publicados") or 0),
            "blocos_apostas_abertos": int((blocos_resumo or {}).get("abertos") or 0),
            "blocos_apostas_em_apuracao": int((blocos_resumo or {}).get("em_apuracao") or 0),
            "blocos_apostas_concluidos": int((blocos_resumo or {}).get("concluidos") or 0),
            "jogos_sem_estatisticas": len(missing_stats),
            "partidas_sem_publico": missing_public,
            "melhores_momentos_sem_video_24_48h": len(old_24),
            "melhores_momentos_sem_video_mais_48h": len(old_48),
            "auditoria_tv_idade_horas": round(tv_age, 1) if tv_age is not None else None,
        },
        "criticos": critical,
        "avisos": warnings,
        "informativos": infos,
        "rodadas_divergentes_por_artefato": round_diffs,
        "politica": {
            "melhores_momentos": "0-24h não é falha; 24-48h aviso; >48h só é crítico em lote de 3 ou mais.",
            "email": "Somente status critical novo/diferente dispara e-mail; ok/warning ficam silenciosos.",
            "fontes": "Auditoria local; nenhum dado esportivo é inventado ou recalculado pela auditoria.",
            "blocos": "Blocos independentes: um bloco anterior parcial pode coexistir normalmente com o seguinte aberto.",
        },
    }


def email_html(payload: Mapping[str, Any]) -> str:
    rows = []
    for item in payload.get("criticos") or []:
        rows.append(f"<li><b>{html.escape(str(item.get('codigo') or ''))}</b>: {html.escape(str(item.get('mensagem') or ''))}</li>")
    return (
        "<h2>Brasileirão 2026 Almoço — auditoria crítica</h2>"
        f"<p>Detectados <b>{len(payload.get('criticos') or [])}</b> problema(s) crítico(s).</p>"
        f"<ul>{''.join(rows)}</ul>"
        "<p>O último snapshot íntegro é preservado pelos workflows. Consulte <code>dados-br/auditoria-geral.json</code> e o GitHub Actions para detalhes.</p>"
    )


def maybe_notify(payload: dict[str, Any], previous: Mapping[str, Any]) -> tuple[bool, str]:
    if payload.get("status") != "critical":
        return False, "dispensado: sem problema crítico"
    if str(previous.get("status") or "") == "critical" and previous.get("fingerprint_critico") == payload.get("fingerprint_critico"):
        return False, "dispensado: mesmo problema crítico já registrado"
    key = os.environ.get("RESEND_API_KEY", "").strip()
    destination = os.environ.get("EMAIL_DESTINO", "").strip()
    if not key or not destination:
        return False, "secrets RESEND_API_KEY/EMAIL_DESTINO não configurados"
    body = json.dumps({
        "from": os.environ.get("EMAIL_REMETENTE", DEFAULT_EMAIL_SENDER).strip() or DEFAULT_EMAIL_SENDER,
        "to": [destination],
        "subject": f"[BR2026 Almoço] Auditoria CRÍTICA — {len(payload.get('criticos') or [])} problema(s)",
        "html": email_html(payload),
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Brasileirao2026AlmocoAudit/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return 200 <= response.status < 300, response.read().decode("utf-8", errors="replace")[:300]
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "dados-br").mkdir(parents=True)
        teams = [f"T{i:02d}" for i in range(20)]
        # round-robin circle method, ida e volta, 380 jogos.
        rotation = teams[:]
        rounds: list[list[tuple[str, str]]] = []
        for r in range(19):
            pairings = []
            for i in range(10):
                a, b = rotation[i], rotation[-1-i]
                pairings.append((a, b) if (r + i) % 2 == 0 else (b, a))
            rounds.append(pairings)
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
        cal=[]
        for r, games in enumerate(rounds, 1):
            for h,a in games: cal.append({"rodada":r,"mandante":h,"visitante":a,"event_id":f"{r}-{h}-{a}","data_iso":None,"data_definir":True})
            for h,a in games: cal.append({"rodada":r+19,"mandante":a,"visitante":h,"event_id":f"{r+19}-{a}-{h}","data_iso":None,"data_definir":True})
        cal.sort(key=lambda x:(x["rodada"],x["mandante"],x["visitante"]))
        (root/"dados-br/calendario-completo.json").write_text(json.dumps({"jogos":cal}),encoding="utf-8")
        (root/"tabela.json").write_text(json.dumps({"tabela":[{"time":t,"jogos":0} for t in teams]}),encoding="utf-8")
        for name,key in (("espn_eventos.json","eventos"),("jogos.json","jogos"),("resultados.json","resultados")):
            (root/name).write_text(json.dumps({key:[]}),encoding="utf-8")
        (root/"dados-br/jogos-detalhes.json").write_text(json.dumps({"jogos":{}}),encoding="utf-8")
        (root/"dados-br/auditoria-jogos-detalhes.json").write_text(json.dumps({"total_sem_estatisticas_no_snapshot":0}),encoding="utf-8")
        (root/"dados-br/auditoria-publicos.json").write_text(json.dumps({"total_partidas_fisicas_sem_publico":0}),encoding="utf-8")
        (root/"dados-br/auditoria-transmissoes-tv.json").write_text(json.dumps({"atualizado_em":"2026-08-15T08:00:00-03:00","resumo":{"jogos_criticos_sem_transmissao_72h":0}}),encoding="utf-8")
        (root/"dados-br/apuracao.json").write_text(json.dumps({"schema_version":4,"resumo":{"jogos_apurados_publicados":0},"rodadas":[]}),encoding="utf-8")
        (root/"dados-br/ranking-apostas.json").write_text(json.dumps({"schema_version":4,"resumo":{"jogos_apurados_publicados":0}}),encoding="utf-8")
        (root/"dados-br/auditoria-blocos-apostas.json").write_text(json.dumps({"schema_version":1,"status":"ok","resumo":{"abertos":1,"em_apuracao":1,"concluidos":0},"criticos":[],"avisos":[]}),encoding="utf-8")
        (root/"dados-br/auditoria-probabilidades.json").write_text(json.dumps({"status":"ok","integridade":{"partidas_2026_concluidas":0}}),encoding="utf-8")
        (root/"dados-br/status-atualizacao.json").write_text(json.dumps({"ultimo_sucesso":"2026-08-15T08:00:00-03:00"}),encoding="utf-8")
        payload = audit(root, datetime(2026,8,15,12,0,tzinfo=TZ))
        assert payload["status"] == "ok", payload
        # Introduz divergência de rodada operacional: deve ser crítica.
        first=cal[0]
        bad={"eventos":[{"event_id":"x","rodada":38,"mandante":first["mandante"],"visitante":first["visitante"]}]}
        (root/"espn_eventos.json").write_text(json.dumps(bad),encoding="utf-8")
        payload = audit(root, datetime(2026,8,15,12,0,tzinfo=TZ))
        assert payload["status"] == "critical"
        assert any(x["codigo"]=="RODADA_DIVERGENTE_EVENTOS" for x in payload["criticos"])
        # A idade de um mesmo incidente não pode produzir outro alerta.
        a = stable_fingerprint([issue("STALE", "artefato antigo", horas=80.0)])
        b = stable_fingerprint([issue("STALE", "artefato antigo", horas=81.0)])
        assert a == b
    print("SELFTEST OK: matriz 380, cruzamento operacional, criticidade, tolerâncias e deduplicação de alertas")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--saida", default="dados-br/auditoria-geral.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--notify-critical", action="store_true")
    parser.add_argument("--strict", action="store_true", help="retorna exit 2 em estado critical")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = Path(args.root).resolve()
    out = root / args.saida
    previous = load_json(out, {})
    payload = audit(root)
    if args.notify_critical:
        sent, detail = maybe_notify(payload, previous if isinstance(previous, Mapping) else {})
        payload["alerta_email"] = "enviado" if sent else detail
        if sent:
            payload["alerta_email_em"] = now_brt().isoformat()
        elif payload.get("status") == "critical" and "secrets" not in detail and "dispensado" not in detail:
            print(f"::warning::Falha ao enviar alerta crítico: {detail}")
    atomic_write(out, payload)
    print(json.dumps(payload["resumo"], ensure_ascii=False, indent=2))
    print(f"Auditoria geral: {payload['status']} -> {out}")
    if args.strict and payload.get("status") == "critical":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

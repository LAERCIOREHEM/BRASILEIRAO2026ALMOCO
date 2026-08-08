#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_auditoria_estatisticas_brasileirao.py

Audita os novos dados estatísticos do módulo Brasileirão e bloqueia regressões
gritantes antes do commit automático.

Saída:
  - dados-br/auditoria-estatisticas.json
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atualizar_espn import CANONICOS, FUSO_BRASILIA  # type: ignore

OUT = ROOT / "dados-br" / "auditoria-estatisticas.json"

SUSPICIOUS = (
    "with a cross", "with the cross", "right footed", "left footed",
    "from the centre", "assisted by", "yellow card", "red card", "goal!",
)


def now_iso() -> str:
    return datetime.now(FUSO_BRASILIA).isoformat()


def norm(v: Any) -> str:
    s = unicodedata.normalize("NFD", str(v or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_team(value: Any, home: str, away: str) -> str:
    """Resolve apenas os dois clubes do jogo, sem adivinhar equipe desconhecida."""
    target = norm(value)
    if target and target == norm(home):
        return home
    if target and target == norm(away):
        return away
    return ""


def classify_game_events(event_id: str, game: dict[str, Any]) -> dict[str, Any]:
    """Classifica divergências sem confundir atraso da ficha com corrupção.

    O coletor marca ``validacao_eventos.ok=false`` tanto quando existe uma
    inconsistência real quanto quando o placar final já chegou, mas a ESPN ainda
    não publicou todos os autores dos gols. A auditoria precisa separar esses dois
    estados antes de decidir se bloqueia o workflow.
    """
    validation = game.get("validacao_eventos") or {}
    is_pending_manual = (
        game.get("resultado_manual") is True
        and validation.get("resultado_confirmado") is True
        and validation.get("pendente_detalhes") is True
    )
    if is_pending_manual:
        return {
            "pending_manual": (
                f"{event_id}: resultado manual confirmado; eventos nominais aguardando ESPN"
            ),
            "errors": [],
            "incomplete": None,
            "duplicates": [],
            "narrative_false_positives": [],
        }

    is_safe_espn_pending = (
        validation.get("pendente_detalhes") is True
        and validation.get("tipo_pendencia") == "ficha_espn_incompleta"
        and validation.get("gols_compativeis") is True
        and validation.get("cartoes_compativeis") is True
    )
    if is_safe_espn_pending:
        return {
            "pending_manual": None,
            "errors": [],
            "incomplete": (
                f"{event_id}: ficha ESPN incompleta sem contradição"
                + (f" ({validation.get('motivo')})" if validation.get("motivo") else "")
            ),
            "duplicates": [],
            "narrative_false_positives": [],
        }

    home = str(game.get("mandante") or "")
    away = str(game.get("visitante") or "")
    errors: list[str] = []
    duplicates: list[str] = []
    narrative_false_positives: list[str] = []
    incomplete: str | None = None

    if not home or not away or norm(home) == norm(away):
        errors.append("mandante/visitante ausente ou inválido")

    expected = {
        home: int(game.get("placar_mandante") or 0),
        away: int(game.get("placar_visitante") or 0),
    }
    extracted = {home: 0, away: 0}
    unknown_goals: list[str] = []
    seen_goals: set[tuple[str, str, str, str]] = set()
    for goal in game.get("gols") or []:
        if not isinstance(goal, dict):
            continue
        team = canonical_team(goal.get("time"), home, away)
        if team:
            extracted[team] += 1
        else:
            unknown_goals.append(
                f"{goal.get('minuto') or '?'} {goal.get('jogador') or 'autor não informado'}"
            )
        key = (
            norm(goal.get("minuto")),
            norm(team or goal.get("time")),
            norm(goal.get("jogador")),
            norm(goal.get("descricao")),
        )
        if key in seen_goals:
            duplicates.append(
                f"{event_id}: gol duplicado {goal.get('minuto')} {goal.get('jogador')}"
            )
        seen_goals.add(key)
        desc = norm(goal.get("descricao"))
        if "attempt saved" in desc or "shot is saved" in desc:
            narrative_false_positives.append(f"{event_id}: {goal.get('jogador')}")

    if unknown_goals:
        errors.append("gol(s) sem equipe reconhecida: " + ", ".join(unknown_goals[:4]))

    if extracted != expected:
        exceeded = any(extracted[team] > expected[team] for team in expected)
        if exceeded:
            errors.append(f"gols extraídos {extracted} excedem o placar {expected}")
        elif not unknown_goals:
            incomplete = (
                f"{event_id}: ficha nominal incompleta ({sum(extracted.values())}"
                f"/{sum(expected.values())} gols publicados pela ESPN)"
            )

    seen_cards: set[tuple[str, str, str, str]] = set()
    unknown_cards: list[str] = []
    for card in game.get("cartoes") or []:
        if not isinstance(card, dict):
            continue
        team = canonical_team(card.get("time"), home, away)
        if not team:
            unknown_cards.append(
                f"{card.get('minuto') or '?'} {card.get('jogador') or 'atleta não informado'}"
            )
        key = (
            norm(card.get("tipo")),
            norm(card.get("minuto")),
            norm(team or card.get("time")),
            norm(card.get("jogador")),
        )
        if key in seen_cards:
            duplicates.append(
                f"{event_id}: cartão duplicado {card.get('minuto')} {card.get('jogador')}"
            )
        seen_cards.add(key)

    if unknown_cards:
        errors.append("cartão(ões) sem equipe reconhecida: " + ", ".join(unknown_cards[:4]))

    # ``cartoes_ok=false`` no coletor representa excesso, duplicidade ou equipe
    # inválida — nunca mera ausência de eventos nominais. Portanto permanece
    # crítico. Já ``gols_ok=false`` pode ser apenas publicação tardia da ficha.
    if validation:
        if validation.get("cartoes_ok") is False:
            errors.append("validação de cartões reprovada")
        if validation.get("gols_ok") is False and extracted == expected:
            errors.append("validação de gols diverge da recontagem independente")
        if validation.get("ok") is False:
            tolerated_incomplete = (
                incomplete is not None
                and validation.get("gols_ok") is False
                and validation.get("cartoes_ok") is not False
                and not errors
            )
            if not tolerated_incomplete and not errors:
                errors.append("validação de eventos reprovada sem causa tolerável")
    else:
        errors.append("validacao_eventos ausente")

    unique_errors = list(dict.fromkeys(errors))
    return {
        "pending_manual": None,
        "errors": [f"{event_id}: {'; '.join(unique_errors)}"] if unique_errors else [],
        "incomplete": incomplete,
        "duplicates": duplicates,
        "narrative_false_positives": narrative_false_positives,
    }


def self_test() -> None:
    base = {
        "mandante": "Time A",
        "visitante": "Time B",
        "placar_mandante": 2,
        "placar_visitante": 1,
        "cartoes": [],
    }
    delayed = classify_game_events(
        "atraso",
        {
            **base,
            "gols": [
                {"time": "Time A", "minuto": "10'", "jogador": "A1"},
                {"time": "Time B", "minuto": "20'", "jogador": "B1"},
            ],
            "validacao_eventos": {"ok": False, "gols_ok": False, "cartoes_ok": True},
        },
    )
    assert not delayed["errors"] and delayed["incomplete"], delayed

    excess = classify_game_events(
        "excesso",
        {
            **base,
            "placar_mandante": 1,
            "placar_visitante": 0,
            "gols": [
                {"time": "Time A", "minuto": "10'", "jogador": "A1"},
                {"time": "Time A", "minuto": "11'", "jogador": "A2"},
            ],
            "validacao_eventos": {"ok": False, "gols_ok": False, "cartoes_ok": True},
        },
    )
    assert excess["errors"] and not excess["incomplete"], excess

    bad_cards = classify_game_events(
        "cartao",
        {
            **base,
            "gols": [
                {"time": "Time A", "minuto": "10'", "jogador": "A1"},
                {"time": "Time A", "minuto": "30'", "jogador": "A2"},
                {"time": "Time B", "minuto": "20'", "jogador": "B1"},
            ],
            "cartoes": [{"tipo": "amarelo", "time": "", "minuto": "40'", "jogador": "X"}],
            "validacao_eventos": {"ok": False, "gols_ok": True, "cartoes_ok": False},
        },
    )
    assert bad_cards["errors"], bad_cards
    print("SELF-TEST OK: atraso nominal tolerado; excesso e cartões inválidos bloqueados.")


def main() -> None:
    leaders = read(ROOT / "dados-br" / "lideres-jogadores.json", {})
    leader_audit = read(ROOT / "dados-br" / "auditoria-lideres-jogadores.json", {})
    details = read(ROOT / "dados-br" / "jogos-detalhes.json", {})
    details_audit = read(ROOT / "dados-br" / "auditoria-jogos-detalhes.json", {})
    competition = read(ROOT / "dados-br" / "estatisticas-competicao.json", {})
    players = read(ROOT / "dados-br" / "jogadores.json", {})
    stats = read(ROOT / "dados-br" / "estatisticas.json", {})
    table = read(ROOT / "tabela.json", {})
    results = read(ROOT / "resultados.json", {})

    critical: list[str] = []
    warnings: list[str] = []

    goals = leaders.get("artilharia") or []
    assists = leaders.get("assistencias") or []
    if leaders.get("status") != "valido":
        critical.append("lideres-jogadores.json não está marcado como válido")
    if len(goals) < 40:
        critical.append(f"artilharia completa com apenas {len(goals)} jogadores; esperado ao menos 40")
    if len(assists) < 20:
        critical.append(f"assistências completas com apenas {len(assists)} jogadores; esperado ao menos 20")
    if goals and int(goals[0].get("gols") or 0) <= 0:
        critical.append("artilheiro líder sem gols positivos")
    if assists and int(assists[0].get("assistencias") or 0) <= 0:
        critical.append("líder de assistências sem valor positivo")

    suspicious_names = []
    for item in list(goals) + list(assists):
        name = str(item.get("nome") or "")
        if any(tok in norm(name) for tok in SUSPICIOUS):
            suspicious_names.append(name)
        if not item.get("time"):
            critical.append(f"jogador sem clube: {name}")
    if suspicious_names:
        critical.append("nomes contaminados por narração: " + ", ".join(sorted(set(suspicious_names))))

    table_rows = table.get("tabela") or []
    if len(table_rows) != 20:
        critical.append(f"tabela com {len(table_rows)} clubes, esperado 20")
    table_names = {str(x.get("time") or "") for x in table_rows}
    missing_teams = sorted(set(CANONICOS) - table_names)
    if missing_teams:
        critical.append("clubes ausentes da tabela: " + ", ".join(missing_teams))

    result_rows = results.get("resultados") or []
    detail_games = details.get("jogos") or {}
    if not isinstance(detail_games, dict):
        critical.append("jogos-detalhes.json sem objeto jogos")
        detail_games = {}
    finalized_ids = {str(x.get("event_id") or "") for x in result_rows if x.get("event_id")}
    detail_ids = set(detail_games)
    missing_details = sorted(finalized_ids - detail_ids)
    if len(missing_details) > max(10, int(len(finalized_ids) * 0.25)):
        critical.append(f"detalhes ausentes para {len(missing_details)} jogos finalizados")
    elif missing_details:
        warnings.append(f"detalhes ausentes para {len(missing_details)} jogos")

    event_errors: list[str] = []
    pending_manual_details: list[str] = []
    duplicate_events: list[str] = []
    incomplete_events: list[str] = []
    narrative_false_positives: list[str] = []
    for event_id, game in detail_games.items():
        if not isinstance(game, dict):
            event_errors.append(f"{event_id}: registro inválido")
            continue
        classification = classify_game_events(str(event_id), game)
        if classification["pending_manual"]:
            # O placar foi confirmado por exceção editorial auditável, mas a ESPN
            # ainda não publicou eventos compatíveis. Não inventamos autores dos
            # gols/cartões e não tratamos essa pendência declarada como corrupção.
            pending_manual_details.append(classification["pending_manual"])
            continue
        event_errors.extend(classification["errors"])
        if classification["incomplete"]:
            incomplete_events.append(classification["incomplete"])
        duplicate_events.extend(classification["duplicates"])
        narrative_false_positives.extend(classification["narrative_false_positives"])
    if pending_manual_details:
        warnings.append(
            f"{len(pending_manual_details)} resultado(s) manual(is) confirmado(s) aguardando detalhes nominais da ESPN"
        )
    if incomplete_events:
        # Trava de segurança: atraso pontual da ESPN é normal; atraso generalizado
        # indica coleta quebrada e volta a ser crítico.
        limite = max(4, int(len(detail_games) * 0.05))
        if len(incomplete_events) > limite:
            critical.append(
                f"{len(incomplete_events)} jogo(s) com ficha nominal incompleta "
                f"(limite tolerado: {limite}) — coleta de eventos provavelmente quebrada"
            )
        else:
            warnings.append(
                f"{len(incomplete_events)} jogo(s) aguardando eventos nominais da ESPN: "
                + "; ".join(incomplete_events[:4])
            )
    if event_errors:
        critical.append(f"{len(event_errors)} jogo(s) com gols/cartões incompatíveis")
    if duplicate_events:
        critical.append(f"{len(duplicate_events)} evento(s) duplicado(s)")
    if narrative_false_positives:
        critical.append(f"{len(narrative_false_positives)} falso(s) gol(s) originado(s) de finalização/defesa")

    with_public = sum(1 for g in detail_games.values() if (g or {}).get("publico") not in (None, "", 0, "0"))
    with_stats = sum(1 for g in detail_games.values() if (g or {}).get("stats") or (g or {}).get("estatisticas"))
    if with_stats == 0:
        critical.append("nenhum jogo com estatísticas detalhadas")
    if with_public == 0:
        warnings.append("nenhum público coletado ainda; conferir retorno da ESPN summary")
    elif detail_games and with_public < int(len(detail_games) * 0.80):
        warnings.append(f"público disponível em somente {with_public}/{len(detail_games)} jogos")

    comp_summary = competition.get("resumo") or {}
    if int(comp_summary.get("clubes") or 0) != 20:
        critical.append("estatisticas-competicao.json sem 20 clubes")
    club_goals = competition.get("gols_por_clube") or []
    if len(club_goals) != 20:
        critical.append(f"gols por clube com {len(club_goals)} itens, esperado 20")
    short_club_scorers = [
        f"{item.get('time')}: {len(item.get('marcadores') or [])}"
        for item in club_goals if int(item.get("gols_pro") or 0) > 0 and len(item.get("marcadores") or []) < 5
    ]
    if short_club_scorers:
        critical.append("clubes com menos de cinco marcadores individualizados: " + ", ".join(short_club_scorers))
    attendance = competition.get("publico") or {}
    if int(attendance.get("jogos_com_publico") or 0) != with_public:
        critical.append("contagem de jogos com público diverge entre detalhes e competição")

    if len(players.get("artilharia") or []) < 5 or len(players.get("assistencias") or []) < 5:
        critical.append("dados-br/jogadores.json não recebeu os rankings oficiais")
    if len(stats.get("artilharia") or []) < 40 or len(stats.get("garcons") or []) < 20:
        critical.append("dados-br/estatisticas.json não recebeu os rankings completos")

    rosters = read(ROOT / "dados-br" / "elencos.json", {})
    roster_audit = read(ROOT / "dados-br" / "auditoria-elencos.json", {})
    roster_map = rosters.get("elencos") or {}
    if not isinstance(roster_map, dict) or len(roster_map) != 20:
        critical.append("elencos.json sem os 20 clubes")
        roster_map = {}
    incomplete_rosters = [f"{club}: {len(rows or [])}" for club, rows in roster_map.items() if not isinstance(rows, list) or len(rows) < 15]
    if incomplete_rosters:
        critical.append("elencos incompletos: " + ", ".join(incomplete_rosters))
    if roster_audit and roster_audit.get("status") != "ok":
        critical.append("auditoria-elencos.json não está OK")

    status = "ok" if not critical else "erro"
    payload = {
        "gerado_em": now_iso(),
        "status": status,
        "resumo": {
            "clubes": len(table_rows),
            "jogos_finalizados": len(result_rows),
            "jogos_com_detalhes": len(detail_games),
            "jogos_com_estatisticas": with_stats,
            "jogos_com_publico": with_public,
            "artilheiros": len(goals),
            "assistentes": len(assists),
            "lider_gols": goals[0] if goals else None,
            "lider_assistencias": assists[0] if assists else None,
            "erros_criticos": len(critical),
            "avisos": len(warnings),
        },
        "fontes": {
            "lideres": leaders.get("fonte"),
            "lideres_aceitas": leaders.get("fonte_aceita"),
            "detalhes": details.get("fonte"),
            "competicao": competition.get("fonte"),
        },
        "auditorias_relacionadas": {
            "lideres": leader_audit.get("resumo"),
            "detalhes": {
                "total_processados": details_audit.get("total_processados"),
                "total_com_estatisticas": details_audit.get("total_com_estatisticas"),
                "total_com_publico": details_audit.get("total_com_publico"),
                "total_falhas": details_audit.get("total_falhas"),
            },
        },
        "jogos_sem_detalhes": missing_details,
        "eventos_inconsistentes": event_errors,
        "resultados_manuais_pendentes_detalhes": pending_manual_details,
        "eventos_duplicados": duplicate_events,
        "falsos_gols_de_narracao": narrative_false_positives,
        "elencos_incompletos": incomplete_rosters,
        "nomes_suspeitos": suspicious_names,
        "erros_criticos": critical,
        "avisos": warnings,
    }
    write(OUT, payload)
    print(json.dumps(payload["resumo"], ensure_ascii=False, indent=2))
    if critical:
        raise RuntimeError("Auditoria de estatísticas falhou: " + " | ".join(critical))
    print(f"OK: auditoria em {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()

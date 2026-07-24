#!/usr/bin/env python3
"""Gera probabilidades pré-jogo de vitória, empate e derrota.

Esta etapa usa exatamente o mesmo modelo Poisson log-linear MAP do AF-Previsão,
com regularização, vantagem de mando, decaimento temporal e ajuste recente por
EWMA. As probabilidades V/E/D são somadas diretamente na matriz de placares do
jogo; por isso não dependem do ruído Monte Carlo usado na classificação final.

Uso:
    python scripts/gerar_probabilidades_jogos.py
    python scripts/gerar_probabilidades_jogos.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from gerar_probabilidades_brasileirao import (
    AUDIT_MODELS_PATH,
    BRT,
    CALENDAR_PATH,
    CONFIG_PATH,
    CurrentDataNotSynchronized,
    EVENTS_PATH,
    Fixture,
    HIST_DIR,
    RESULTS_PATH,
    TABLE_PATH,
    build_forecasts,
    build_model_state_hash,
    calculate_recent_trends,
    extract_map_config,
    fit_poisson_map,
    latest_concluded_datetime,
    load_current_matches,
    load_current_state,
    load_fixtures,
    load_historical_matches,
    load_json,
    serialize_match_forecasts,
    validate_current_results_against_table,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "dados-br" / "probabilidades-jogos.json"
AUDIT_PATH = ROOT / "dados-br" / "auditoria-probabilidades-jogos.json"


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def percentage_partition(values: Sequence[float], decimals: int) -> tuple[float, ...]:
    """Arredonda os percentuais preservando soma exata de 100."""
    if decimals < 0 or decimals > 6:
        raise ValueError("quantidade de casas decimais inválida")
    numbers = [float(value) for value in values]
    if not numbers or any(not math.isfinite(value) or value < 0.0 for value in numbers):
        raise ValueError("probabilidades inválidas")
    total = sum(numbers)
    if total <= 0.0 or abs(total - 1.0) > 5e-5:
        raise ValueError(f"probabilidades não somam 1: {total:.12f}")
    normalized = [value / total for value in numbers]
    scale = 10**decimals
    total_units = 100 * scale
    exact = [value * total_units for value in normalized]
    units = [math.floor(value + 1e-12) for value in exact]
    remaining = total_units - sum(units)
    order = sorted(
        range(len(units)),
        key=lambda index: (exact[index] - units[index], normalized[index], -index),
        reverse=True,
    )
    for index in order[:remaining]:
        units[index] += 1
    return tuple(round(value / scale, decimals) for value in units)


def pt_percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


def build_document(
    rows: Sequence[dict[str, Any]],
    *,
    generated_at: str,
    input_hash: str,
    model_version: str,
    responsible: Any,
    championship_simulations: int,
    concluded_matches: int,
) -> dict[str, Any]:
    games: list[dict[str, Any]] = []
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        home = str(row.get("mandante") or "").strip()
        away = str(row.get("visitante") or "").strip()
        if not event_id or not home or not away or home == away:
            raise ValueError(f"partida inválida: {event_id!r} {home!r} x {away!r}")

        source_probabilities = row.get("probabilidades_pct") or {}
        values = (
            float(source_probabilities.get("mandante") or 0.0) / 100.0,
            float(source_probabilities.get("empate") or 0.0) / 100.0,
            float(source_probabilities.get("visitante") or 0.0) / 100.0,
        )
        raw = percentage_partition(values, 4)
        display = percentage_partition(values, 1)
        rates = row.get("gols_esperados") or {}
        modal = row.get("placar_modal") or {}

        games.append(
            {
                "event_id": event_id,
                "rodada": int(row.get("rodada") or 0),
                "data_iso": row.get("data_iso"),
                "mandante": home,
                "visitante": away,
                "estadio": str(row.get("estadio") or ""),
                "status": "pre_jogo",
                "valido_ate": "inicio_da_partida",
                "probabilidades_pct": {
                    "mandante": raw[0],
                    "empate": raw[1],
                    "visitante": raw[2],
                },
                "probabilidades_exibicao_pct": {
                    "mandante": display[0],
                    "empate": display[1],
                    "visitante": display[2],
                },
                "exibicao": {
                    "mandante": pt_percent(display[0]),
                    "empate": pt_percent(display[1]),
                    "visitante": pt_percent(display[2]),
                },
                "gols_esperados": {
                    "mandante": round(float(rates.get("mandante") or 0.0), 4),
                    "visitante": round(float(rates.get("visitante") or 0.0), 4),
                },
                "placar_modal": {
                    "mandante": int(modal.get("mandante") or 0),
                    "visitante": int(modal.get("visitante") or 0),
                },
            }
        )

    games.sort(key=lambda item: (str(item.get("data_iso") or "9999"), item["rodada"], item["event_id"]))
    return {
        "schema_version": 1,
        "projeto": "AF-Previsão",
        "tipo": "probabilidades_pre_jogo",
        "temporada": 2026,
        "status": "ok",
        "gerado_em": generated_at,
        "hash_entrada": input_hash,
        "versao_modelo": model_version,
        "responsavel": responsible,
        "metodologia": {
            "calculo": "soma analítica da matriz de placares Poisson do AF-Previsão",
            "componentes": [
                "força ofensiva e defensiva regularizada",
                "vantagem de mando",
                "decaimento temporal",
                "tendência recente por suavização exponencial controlada",
            ],
            "simulacoes_monte_carlo_do_campeonato": int(championship_simulations),
            "observacao": (
                "As probabilidades V/E/D são obtidas diretamente da matriz de placares; "
                "as simulações Monte Carlo são usadas nas projeções do campeonato e não adicionam ruído a esta soma."
            ),
        },
        "base_corrente": {
            "partidas_concluidas": int(concluded_matches),
            "partidas_restantes": len(games),
            "partidas_totais": int(concluded_matches) + len(games),
        },
        "total_jogos": len(games),
        "jogos": games,
        "avisos": [
            "Probabilidades pré-jogo: deixam de representar o estado da partida quando a bola começa a rolar.",
            "Não são cotações de apostas nem garantia de resultado.",
        ],
    }


def validate_document(
    document: dict[str, Any], expected_rows: Sequence[dict[str, Any]] | None = None
) -> dict[str, Any]:
    games = document.get("jogos") or []
    if document.get("status") != "ok" or document.get("tipo") != "probabilidades_pre_jogo":
        raise ValueError("documento pré-jogo inválido")
    if not isinstance(games, list) or int(document.get("total_jogos") or -1) != len(games):
        raise ValueError("total de jogos divergente")
    base = document.get("base_corrente") or {}
    if int(base.get("partidas_concluidas") or 0) + int(base.get("partidas_restantes") or 0) != 380:
        raise ValueError("partição do campeonato não totaliza 380 jogos")
    if int(base.get("partidas_restantes") or -1) != len(games):
        raise ValueError("base corrente não corresponde aos jogos publicados")

    ids: set[str] = set()
    max_raw_delta = 0.0
    max_display_delta = 0.0
    for game in games:
        event_id = str(game.get("event_id") or "")
        if not event_id or event_id in ids:
            raise ValueError(f"event_id ausente ou duplicado: {event_id!r}")
        ids.add(event_id)
        if game.get("status") != "pre_jogo" or game.get("valido_ate") != "inicio_da_partida":
            raise ValueError(f"status ou validade inválida em {event_id}")
        if not str(game.get("mandante") or "").strip() or not str(game.get("visitante") or "").strip():
            raise ValueError(f"clubes ausentes em {event_id}")

        raw = game.get("probabilidades_pct") or {}
        display = game.get("probabilidades_exibicao_pct") or {}
        for block_name, block in (("bruto", raw), ("exibição", display)):
            values = [float(block.get(field)) for field in ("mandante", "empate", "visitante")]
            if any(not math.isfinite(value) or not 0.0 <= value <= 100.0 for value in values):
                raise ValueError(f"probabilidade {block_name} inválida em {event_id}")
            delta = abs(sum(values) - 100.0)
            if delta > 1e-9:
                raise ValueError(f"probabilidades {block_name} não fecham 100% em {event_id}")
            if block_name == "bruto":
                max_raw_delta = max(max_raw_delta, delta)
            else:
                max_display_delta = max(max_display_delta, delta)

        rates = game.get("gols_esperados") or {}
        if any(
            not math.isfinite(float(rates.get(field))) or float(rates.get(field)) <= 0.0
            for field in ("mandante", "visitante")
        ):
            raise ValueError(f"taxa de gols inválida em {event_id}")

    if expected_rows is not None:
        expected = {
            str(row.get("event_id") or ""): (
                str(row.get("mandante") or ""),
                str(row.get("visitante") or ""),
            )
            for row in expected_rows
        }
        actual = {game["event_id"]: (game["mandante"], game["visitante"]) for game in games}
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise ValueError(f"cobertura divergente; ausentes={missing}, extras={extra}")

    return {
        "jogos": len(games),
        "ids_unicos": True,
        "somas_brutas_100": True,
        "somas_exibicao_100": True,
        "maior_desvio_soma_bruta_pp": round(max_raw_delta, 10),
        "maior_desvio_soma_exibicao_pp": round(max_display_delta, 10),
        "jogos_sem_data_definida": sum(1 for game in games if not game.get("data_iso")),
    }


def build_audit(document: dict[str, Any], expected_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    checks = validate_document(document, expected_rows)
    return {
        "schema_version": 1,
        "projeto": "AF-Previsão",
        "tipo": "auditoria_probabilidades_pre_jogo",
        "temporada": 2026,
        "status": "ok",
        "gerado_em": document.get("gerado_em"),
        "hash_entrada": document.get("hash_entrada"),
        "hash_saida": canonical_hash(document),
        "versao_modelo": document.get("versao_modelo"),
        "validacoes": checks,
        "observacao": "A publicação é bloqueada se houver jogo duplicado, taxa inválida ou soma diferente de 100%.",
    }


def validate_previous_publication() -> tuple[bool, str]:
    """Confere se os dois artefatos pré-jogo anteriores podem ser preservados.

    O fallback é deliberadamente restrito à dessincronia transitória entre os
    feeds. Qualquer outro erro continua interrompendo a execução.
    """
    if not OUTPUT_PATH.exists() or not AUDIT_PATH.exists():
        return False, "arquivos anteriores ausentes"
    try:
        document = load_json(OUTPUT_PATH)
        audit = load_json(AUDIT_PATH)
        checks = validate_document(document)
        if audit.get("status") != "ok" or audit.get("tipo") != "auditoria_probabilidades_pre_jogo":
            return False, "auditoria anterior inválida"
        if audit.get("hash_entrada") != document.get("hash_entrada"):
            return False, "hash de entrada divergente entre documento e auditoria"
        if audit.get("hash_saida") != canonical_hash(document):
            return False, "hash de saída da auditoria não corresponde ao documento"
        if audit.get("gerado_em") != document.get("gerado_em"):
            return False, "instantes de geração divergentes"
        if audit.get("versao_modelo") != document.get("versao_modelo"):
            return False, "versões do modelo divergentes"
        audited_checks = audit.get("validacoes") or {}
        for field, value in checks.items():
            if audited_checks.get(field) != value:
                return False, f"validação anterior divergente em {field}"
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return False, f"artefatos anteriores não passaram na validação: {type(exc).__name__}: {exc}"
    return True, "documento e auditoria anteriores íntegros e coerentes"


def enrich_fixture_event_ids(
    fixtures: Sequence[Fixture], events: dict[str, Any]
) -> list[Fixture]:
    """Troca IDs sintéticos pelo ID ESPN quando o calendário ainda não o gravou.

    O calendário completo preserva os 380 confrontos mesmo antes de a ESPN
    atribuir data/ID definitivo. Assim que o scoreboard passa a oferecer o ID,
    a previsão precisa usar esse identificador para ser encontrada em Jogos.
    """
    event_map: dict[tuple[str, str], dict[str, Any]] = {}
    for item in events.get("eventos") or []:
        event_id = str(item.get("event_id") or "").strip()
        home = str(item.get("mandante") or "").strip()
        away = str(item.get("visitante") or "").strip()
        round_no = int(item.get("rodada") or 0)
        if not event_id or not home or not away or round_no <= 0:
            continue
        key = (home, away)
        current = event_map.get(key)
        if current and str(current.get("event_id")) != event_id:
            raise ValueError(f"mais de um event_id ESPN para {key}: {current.get('event_id')} e {event_id}")
        event_map[key] = item

    enriched: list[Fixture] = []
    seen_ids: set[str] = set()
    for fixture in fixtures:
        item = event_map.get((fixture.home, fixture.away))
        event_id = fixture.event_id
        kickoff = fixture.kickoff
        stadium = fixture.stadium
        if item is not None:
            event_id = str(item.get("event_id") or event_id).strip() or event_id
            kickoff = str(item.get("data_iso") or kickoff or "").strip() or None
            stadium = str(item.get("estadio") or stadium or "").strip()
        if event_id in seen_ids:
            raise ValueError(f"event_id duplicado após enriquecimento ESPN: {event_id}")
        seen_ids.add(event_id)
        enriched.append(
            Fixture(
                event_id=event_id,
                round_no=fixture.round_no,
                home=fixture.home,
                away=fixture.away,
                kickoff=kickoff,
                stadium=stadium,
            )
        )
    enriched.sort(key=lambda item: (item.kickoff or "9999-12-31", item.round_no, item.event_id))
    return enriched


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_json(CONFIG_PATH)
    audit_models = load_json(AUDIT_MODELS_PATH)
    table = load_json(TABLE_PATH)
    events = load_json(EVENTS_PATH)
    results = load_json(RESULTS_PATH) if RESULTS_PATH.exists() else {"resultados": []}
    calendar = load_json(CALENDAR_PATH)

    state = load_current_state(table)
    allowed_teams = set(state.teams)
    historical = load_historical_matches()
    current = load_current_matches(events, allowed_teams, results)
    validate_current_results_against_table(current, state)
    concluded_ids = {str(match.source_id) for match in current}
    fixtures, _ = load_fixtures(calendar, concluded_ids, allowed_teams)
    fixtures = enrich_fixture_event_ids(fixtures, events)
    if len(current) + len(fixtures) != 380:
        raise ValueError("quantidade de partidas correntes não totaliza 380")

    reference = latest_concluded_datetime(events, current)
    latest_played = max((match.played_on for match in current), default=reference.date())
    as_of = max(reference.date(), latest_played) + timedelta(days=1)
    map_config = extract_map_config(audit_models)
    execution = config.get("execucao_2") or {}
    configured_prior = float(execution.get("desvio_prior", map_config.prior_sd))
    configured_half_life = execution.get("meia_vida_dias", map_config.half_life_days)
    configured_half_life = None if configured_half_life is None else float(configured_half_life)
    if abs(configured_prior - map_config.prior_sd) > 1e-12 or configured_half_life != map_config.half_life_days:
        raise ValueError("configuração de produção diverge dos hiperparâmetros selecionados no backtesting")

    model = fit_poisson_map([*historical, *current], as_of, map_config)
    rho_production = float(execution.get("rho_dixon_coles_producao") or 0.0)
    execution_4 = config.get("execucao_4") or {}
    trend_settings = execution_4.get("tendencia_recente") or {}
    recent_trends = calculate_recent_trends(current, model, state.teams, trend_settings)
    forecasts = build_forecasts(
        fixtures,
        model,
        rho_production,
        recent_trends=recent_trends,
        max_fixture_adjustment_pct=float(trend_settings.get("limite_ajuste_taxa_partida_pct") or 10.0),
    )
    rows = serialize_match_forecasts(forecasts)
    input_hash = build_model_state_hash(config, audit_models, state, current, fixtures)
    generated_at = reference.replace(microsecond=0).isoformat()
    model_version = str(config.get("versao_modelo") or "AF-Previsão")
    simulations = int(execution.get("simulacoes_monte_carlo") or 2_000_000)

    document = build_document(
        rows,
        generated_at=generated_at,
        input_hash=input_hash,
        model_version=model_version,
        responsible=config.get("responsavel"),
        championship_simulations=simulations,
        concluded_matches=len(current),
    )
    audit = build_audit(document, rows)
    return document, audit


def self_test() -> None:
    thirds = percentage_partition((1 / 3, 1 / 3, 1 / 3), 1)
    if abs(sum(thirds) - 100.0) > 1e-9 or sorted(thirds) != [33.3, 33.3, 33.4]:
        raise AssertionError("arredondamento por maiores restos falhou")

    rows = [
        {
            "event_id": "teste-1",
            "rodada": 1,
            "data_iso": "2026-01-01T16:00:00-03:00",
            "mandante": "Clube A",
            "visitante": "Clube B",
            "estadio": "Estádio",
            "gols_esperados": {"mandante": 1.5, "visitante": 1.0},
            "probabilidades_pct": {"mandante": 45.0, "empate": 28.0, "visitante": 27.0},
            "placar_modal": {"mandante": 1, "visitante": 0},
        },
        {
            "event_id": "teste-2",
            "rodada": 1,
            "data_iso": None,
            "mandante": "Clube C",
            "visitante": "Clube D",
            "estadio": "",
            "gols_esperados": {"mandante": 1.1, "visitante": 1.1},
            "probabilidades_pct": {"mandante": 33.3333, "empate": 33.3333, "visitante": 33.3334},
            "placar_modal": {"mandante": 1, "visitante": 1},
        },
    ]
    document = build_document(
        rows,
        generated_at="2026-07-20T03:00:00-03:00",
        input_hash="hash-teste",
        model_version="AF-Previsão teste",
        responsible={"nome": "Teste"},
        championship_simulations=2_000_000,
        concluded_matches=378,
    )
    audit = build_audit(document, rows)
    if document["total_jogos"] != 2 or audit["status"] != "ok":
        raise AssertionError("documento pré-jogo incompleto")

    tampered = json.loads(json.dumps(document))
    tampered["jogos"][0]["probabilidades_exibicao_pct"]["empate"] += 0.1
    try:
        validate_document(tampered, rows)
    except ValueError:
        pass
    else:
        raise AssertionError("auditoria não bloqueou soma diferente de 100%")

    duplicated = json.loads(json.dumps(document))
    duplicated["jogos"][1]["event_id"] = duplicated["jogos"][0]["event_id"]
    try:
        validate_document(duplicated)
    except ValueError:
        pass
    else:
        raise AssertionError("auditoria não bloqueou event_id duplicado")

    enriched = enrich_fixture_event_ids(
        [Fixture("AF-38-Clube A-Clube B", 38, "Clube A", "Clube B", None, "")],
        {"eventos": [{
            "event_id": "espn-123", "rodada": 38, "mandante": "Clube A",
            "visitante": "Clube B", "data_iso": "2026-12-01T16:00", "estadio": "Arena",
        }]},
    )
    if enriched[0].event_id != "espn-123" or enriched[0].kickoff != "2026-12-01T16:00":
        raise AssertionError("ID ESPN não substituiu o identificador sintético")
    print("Self-test probabilidades pré-jogo: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        document, audit = generate()
    except CurrentDataNotSynchronized as exc:
        previous_valid, diagnosis = validate_previous_publication()
        if not previous_valid:
            raise
        print(
            "::warning title=Probabilidades pré-jogo aguardando sincronização da ESPN::"
            f"{exc}. {diagnosis}; os arquivos anteriores foram preservados sem alteração."
        )
        return 0
    write_json(OUTPUT_PATH, document)
    write_json(AUDIT_PATH, audit)
    print(
        "Probabilidades pré-jogo geradas: "
        f"{document['base_corrente']['partidas_concluidas']} concluídos, "
        f"{document['total_jogos']} restantes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

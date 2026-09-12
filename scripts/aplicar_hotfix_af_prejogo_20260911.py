#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gerar_probabilidades_jogos.py"
MARKER = "HOTFIX_AF_PREJOGO_20260911"

HELPER = r"""
def reconcile_previous_publication_with_current_schedule() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    # HOTFIX_AF_PREJOGO_20260911:
    # Se os feeds ESPN ainda estiverem em transição, reaproveita os valores
    # probabilísticos antigos SOMENTE para jogos que continuam futuros.
    previous = load_json(OUTPUT_PATH)
    table = load_json(TABLE_PATH)
    events = load_json(EVENTS_PATH)
    results = load_json(RESULTS_PATH) if RESULTS_PATH.exists() else {"resultados": []}
    calendar = load_json(CALENDAR_PATH)

    validate_document(previous)

    def team_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("nome") or "").strip()
        return str(value or "").strip()

    result_rows = results.get("resultados") or []
    concluded_ids = {
        str(item.get("event_id") or item.get("id") or "").strip()
        for item in result_rows
        if str(item.get("event_id") or item.get("id") or "").strip()
    }
    concluded_matchups = {
        (team_name(item.get("mandante")), team_name(item.get("visitante")))
        for item in result_rows
        if team_name(item.get("mandante")) and team_name(item.get("visitante"))
    }

    state = load_current_state(table)
    allowed_teams = set(state.teams)
    fixtures, _ = load_fixtures(calendar, concluded_ids, allowed_teams)
    fixtures = enrich_fixture_event_ids(fixtures, events)
    fixtures = [
        fixture for fixture in fixtures
        if (fixture.home, fixture.away) not in concluded_matchups
    ]

    old_games = previous.get("jogos") or []
    old_by_matchup = {
        (str(game.get("mandante") or "").strip(), str(game.get("visitante") or "").strip()): game
        for game in old_games
    }

    reconciled: list[dict[str, Any]] = []
    missing: list[str] = []
    for fixture in fixtures:
        old = old_by_matchup.get((fixture.home, fixture.away))
        if old is None:
            missing.append(f"{fixture.home} x {fixture.away} ({fixture.event_id})")
            continue
        game = dict(old)
        game["event_id"] = fixture.event_id
        game["rodada"] = int(fixture.round_no)
        game["data_iso"] = fixture.kickoff
        game["estadio"] = fixture.stadium
        game["status"] = "pre_jogo"
        game["valido_ate"] = "inicio_da_partida"
        reconciled.append(game)

    if missing:
        raise RuntimeError(
            "fallback pré-jogo sem previsão anterior para fixture(s) futuros: "
            + "; ".join(missing)
        )

    reconciled.sort(
        key=lambda item: (
            str(item.get("data_iso") or "9999"),
            int(item.get("rodada") or 0),
            str(item.get("event_id") or ""),
        )
    )

    ids_before = {
        str(game.get("event_id") or "").strip()
        for game in old_games
        if str(game.get("event_id") or "").strip()
    }
    ids_after = {
        str(game.get("event_id") or "").strip()
        for game in reconciled
        if str(game.get("event_id") or "").strip()
    }
    removed = sorted(ids_before - ids_after)

    document = dict(previous)
    document["jogos"] = reconciled
    document["total_jogos"] = len(reconciled)
    document["base_corrente"] = {
        "partidas_concluidas": 380 - len(reconciled),
        "partidas_restantes": len(reconciled),
        "partidas_totais": 380,
    }
    document["escopo_reconciliado_em"] = (
        results.get("atualizado_em")
        or results.get("atualizado_em_br")
        or previous.get("gerado_em")
    )
    document["fallback_transitorio"] = {
        "ativo": True,
        "motivo": "feeds ESPN temporariamente dessincronizados",
        "probabilidades_reutilizadas": True,
        "escopo_reconciliado_com_resultados": True,
        "jogos_retirados_por_resultado": removed,
    }

    audit = build_audit(document, reconciled)
    audit["fallback_transitorio"] = dict(document["fallback_transitorio"])
    return document, audit, {
        "antes": len(old_games),
        "depois": len(reconciled),
        "removidos": removed,
    }

"""

def patch_script(text: str) -> str:
    if MARKER in text:
        return text

    anchor = "\ndef generate() -> tuple[dict[str, Any], dict[str, Any]]:\n"
    if anchor not in text:
        raise SystemExit("ERRO: âncora def generate() não encontrada.")
    text = text.replace(anchor, "\n" + HELPER.rstrip() + "\n\n" + anchor.lstrip(), 1)

    old = (
        "    except CurrentDataNotSynchronized as exc:\n"
        "        previous_valid, diagnosis = validate_previous_publication()\n"
        "        if not previous_valid:\n"
        "            raise\n"
        "        print(\n"
        "            \"::warning title=Probabilidades pré-jogo aguardando sincronização da ESPN::\"\n"
        "            f\"{exc}. {diagnosis}; os arquivos anteriores foram preservados sem alteração.\"\n"
        "        )\n"
        "        return 0\n"
    )
    new = (
        "    except CurrentDataNotSynchronized as exc:\n"
        "        previous_valid, diagnosis = validate_previous_publication()\n"
        "        if not previous_valid:\n"
        "            raise\n"
        "        document, audit, reconciliation = reconcile_previous_publication_with_current_schedule()\n"
        "        write_json(OUTPUT_PATH, document)\n"
        "        write_json(AUDIT_PATH, audit)\n"
        "        print(\n"
        "            \"::warning title=Probabilidades pré-jogo reconciliadas durante sincronização da ESPN::\"\n"
        "            f\"{exc}. {diagnosis}; probabilidades anteriores foram mantidas somente para jogos futuros. \"\n"
        "            f\"Escopo: {reconciliation['antes']} -> {reconciliation['depois']} jogos; \"\n"
        "            f\"retirados={reconciliation['removidos']}.\"\n"
        "        )\n"
        "        return 0\n"
    )
    if old not in text:
        raise SystemExit("ERRO: bloco CurrentDataNotSynchronized esperado não encontrado.")
    return text.replace(old, new, 1)



def main() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    SCRIPT.write_text(patch_script(script), encoding="utf-8", newline="\n")
    print("HOTFIX_AF_PREJOGO_20260911_V2 aplicado sem alterar arquivos em .github/workflows permanentes.")


if __name__ == "__main__":
    main()

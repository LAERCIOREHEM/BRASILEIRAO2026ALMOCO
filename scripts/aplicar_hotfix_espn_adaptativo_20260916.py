#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "atualizar_espn.py"
WORKER = ROOT / "cloudflare" / "orchestrator-br-almoco" / "src" / "index.js"
WORKER_TEST = ROOT / "cloudflare" / "orchestrator-br-almoco" / "test" / "orchestrator.test.mjs"

MARKER = "HOTFIX_ESPN_SCOREBOARD_ADAPTATIVO_20260916"

ADAPTIVE_FUNCTION = r'''
def _scoreboard_dates_param(inicio: datetime, fim: datetime) -> str:
    # Usa formato diário quando a faixa tem um único dia.
    if inicio.date() == fim.date():
        return inicio.strftime("%Y%m%d")
    return datas_url(inicio, fim)


def _buscar_scoreboard_faixa_adaptativa(
    inicio: datetime,
    fim: datetime,
    estatisticas: dict[str, int],
) -> list[dict[str, Any]]:
    # HOTFIX_ESPN_SCOREBOARD_ADAPTATIVO_20260916:
    # ranges longos que retornarem erro são subdivididos até consulta diária.
    periodo = _scoreboard_dates_param(inicio, fim)
    url = f"{URL_SCOREBOARD}?dates={periodo}&limit=200"
    print(f"Fonte: {url}")
    estatisticas["chamadas"] = estatisticas.get("chamadas", 0) + 1
    try:
        data = fetch_json(url, timeout=30, tentativas=1)
    except Exception as exc:  # noqa: BLE001
        dias = (fim.date() - inicio.date()).days + 1
        if dias <= 1:
            raise
        estatisticas["subdivisoes"] = estatisticas.get("subdivisoes", 0) + 1
        esquerda_dias = max(1, dias // 2)
        fim_esquerda = inicio + timedelta(days=esquerda_dias - 1)
        inicio_direita = fim_esquerda + timedelta(days=1)
        print(
            "::warning::Scoreboard rejeitou faixa "
            f"{periodo} ({type(exc).__name__}: {exc}); "
            f"subdividindo em {_scoreboard_dates_param(inicio, fim_esquerda)} "
            f"e {_scoreboard_dates_param(inicio_direita, fim)}."
        )
        return (
            _buscar_scoreboard_faixa_adaptativa(inicio, fim_esquerda, estatisticas)
            + _buscar_scoreboard_faixa_adaptativa(inicio_direita, fim, estatisticas)
        )

    eventos = data.get("events") or []
    if not isinstance(eventos, list):
        raise RuntimeError(f"scoreboard inválido em {periodo}: campo events não é lista")
    return [ev for ev in eventos if isinstance(ev, dict)]


def _buscar_eventos_periodo(
    inicio: datetime,
    fim: datetime,
    *,
    bloco_dias: int,
) -> list[dict[str, Any]]:
    eventos_por_id: dict[str, dict[str, Any]] = {}
    cursor = inicio
    estatisticas = {"chamadas": 0, "subdivisoes": 0}

    bloco_efetivo = max(1, min(int(bloco_dias), ESPN_BLOCO_SEGURO_DIAS))
    print(
        "Scoreboard: "
        f"bloco solicitado={max(1, int(bloco_dias))}d; "
        f"bloco inicial efetivo={bloco_efetivo}d; "
        "fallback adaptativo até 1 dia."
    )

    while cursor <= fim:
        proximo = min(cursor + timedelta(days=bloco_efetivo - 1), fim)
        eventos = _buscar_scoreboard_faixa_adaptativa(cursor, proximo, estatisticas)
        for ev in eventos:
            eid = str(ev.get("id") or "")
            if eid:
                eventos_por_id[eid] = ev
        cursor = proximo + timedelta(days=1)

    print(
        "Chamadas ao scoreboard: "
        f"{estatisticas['chamadas']}; "
        f"subdivisões adaptativas: {estatisticas['subdivisoes']}; "
        f"eventos brutos recebidos: {len(eventos_por_id)}"
    )
    if not eventos_por_id:
        raise RuntimeError(
            "A ESPN não retornou eventos para a janela consultada; mantendo JSONs anteriores."
        )
    return list(eventos_por_id.values())
'''

def patch_collector(text: str) -> str:
    if MARKER not in text:
        const_anchor = (
            'ESPN_BLOCO_COMPLETO_DIAS = max(28, min(120, '
            'int(os.environ.get("ESPN_BLOCO_COMPLETO_DIAS", "112"))))'
        )
        if const_anchor not in text:
            raise RuntimeError("Constante ESPN_BLOCO_COMPLETO_DIAS não encontrada.")
        text = text.replace(
            const_anchor,
            const_anchor + '\n'
            '# ' + MARKER + ': bloco inicial seguro; fallback divide até 1 dia.\n'
            'ESPN_BLOCO_SEGURO_DIAS = max(1, min(31, '
            'int(os.environ.get("ESPN_BLOCO_SEGURO_DIAS", "14"))))',
            1,
        )

        start = text.find("def _buscar_eventos_periodo(")
        end = text.find("\ndef buscar_eventos_scoreboard()", start)
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError("Bloco _buscar_eventos_periodo não localizado.")
        text = text[:start] + ADAPTIVE_FUNCTION.strip() + "\n\n" + text[end+1:]
    return text


def patch_worker(text: str) -> str:
    replacements = {
        '[ACTIONS.FINAL]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "true", forcar_af: "false" } },':
        '[ACTIONS.FINAL]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "false" } },',
        '[ACTIONS.MAIN]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "true", forcar_af: "false" } },':
        '[ACTIONS.MAIN]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "false" } },',
        '[ACTIONS.MAIN_AF]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "true", forcar_af: "true" } },':
        '[ACTIONS.MAIN_AF]: { file: "atualizar-brasileirao.yml", inputs: { coleta_completa: "false", forcar_af: "true" } },',
    }
    confirmed = 0
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
            confirmed += 1
        elif new in text:
            confirmed += 1
    if confirmed != 3:
        raise RuntimeError(f"Inputs coleta_completa do Worker inesperados (confirmados={confirmed}).")
    return text


def patch_worker_test(text: str) -> str:
    replacements = [
        (
            'assert.deepEqual(dispatches[0].inputs, { coleta_completa: "true", forcar_af: "false", event_ids: "g1" });',
            'assert.deepEqual(dispatches[0].inputs, { coleta_completa: "false", forcar_af: "false", event_ids: "g1" });',
        ),
        (
            'test("orquestrador sempre chama atualização completa nos fluxos pesados", () => {',
            'test("orquestrador usa coleta incremental nos fluxos automáticos e deixa a completa para manutenção", () => {',
        ),
        (
            'assert.deepEqual(WORKFLOW_BY_ACTION[ACTIONS.MAIN].inputs, { coleta_completa: "true", forcar_af: "false" });',
            'assert.deepEqual(WORKFLOW_BY_ACTION[ACTIONS.MAIN].inputs, { coleta_completa: "false", forcar_af: "false" });',
        ),
        (
            'assert.deepEqual(WORKFLOW_BY_ACTION[ACTIONS.MAIN_AF].inputs, { coleta_completa: "true", forcar_af: "true" });',
            'assert.deepEqual(WORKFLOW_BY_ACTION[ACTIONS.MAIN_AF].inputs, { coleta_completa: "false", forcar_af: "true" });',
        ),
        (
            'assert.deepEqual(dispatches[0].body, { ref: "main", inputs: { coleta_completa: "true", forcar_af: "false", event_ids: "g1" } });',
            'assert.deepEqual(dispatches[0].body, { ref: "main", inputs: { coleta_completa: "false", forcar_af: "false", event_ids: "g1" } });',
        ),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise RuntimeError(f"Expectativa de teste não encontrada: {old[:90]}")
    return text


def main() -> None:
    COLLECTOR.write_text(
        patch_collector(COLLECTOR.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="\n",
    )
    WORKER.write_text(
        patch_worker(WORKER.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="\n",
    )
    WORKER_TEST.write_text(
        patch_worker_test(WORKER_TEST.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="\n",
    )
    print("HOTFIX ESPN adaptativo aplicado com sucesso.")


if __name__ == "__main__":
    main()

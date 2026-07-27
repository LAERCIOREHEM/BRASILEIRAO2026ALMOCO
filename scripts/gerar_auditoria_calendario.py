#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera auditoria e mapa completo do calendário do Brasileirão 2026.

Entradas normalizadas pelo atualizar_espn.py:
  - espn_eventos.json
  - jogos.json
  - resultados.json
  - tabela.json
  - dados-br/ajustes-calendario.json

Saídas:
  - dados-br/calendario-completo.json: os 380 confrontos (38 rodadas), usando
    as 19 rodadas do primeiro turno como matriz e invertendo os mandos no
    segundo turno; datas/event_id da ESPN são preservados quando disponíveis.
  - dados-br/auditoria-calendario.json: invariantes, jogos disputados por clube,
    adiados sem data e eventuais falhas estruturais.

Nenhum arquivo de copa2026/ é lido ou alterado.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FUSO_BRASILIA = timezone(timedelta(hours=-3))
ARQ_EVENTOS = ROOT / "espn_eventos.json"
ARQ_JOGOS = ROOT / "jogos.json"
ARQ_RESULTADOS = ROOT / "resultados.json"
ARQ_TABELA = ROOT / "tabela.json"
ARQ_AJUSTES = ROOT / "dados-br" / "ajustes-calendario.json"
ARQ_CALENDARIO = ROOT / "dados-br" / "calendario-completo.json"
ARQ_SAIDA = ROOT / "dados-br" / "auditoria-calendario.json"


def ler(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def nome_time(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("nome") or "").strip()
    return str(obj or "").strip()


def chave_evento(e: dict[str, Any]) -> tuple[int, str, str]:
    return (
        int(e.get("rodada") or 0),
        nome_time(e.get("mandante")),
        nome_time(e.get("visitante")),
    )


def _data_iso_brt(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASILIA)
    return dt.astimezone(FUSO_BRASILIA)


def _horario_futuro_inconsistente(fonte: dict[str, Any]) -> bool:
    data = _data_iso_brt(fonte.get("data_iso"))
    if not data:
        return False
    estado = str(fonte.get("estado") or "").strip().lower()
    status = str(fonte.get("status") or "").strip().lower()
    return (
        estado == "post"
        and fonte.get("concluido") is not True
        and status in {"", "0", "0'", "0:00", "0’"}
        and data > datetime.now(FUSO_BRASILIA) + timedelta(minutes=15)
    )


def item_calendario(
    rodada: int,
    mandante: str,
    visitante: str,
    fonte: dict[str, Any] | None,
    origem: str,
) -> dict[str, Any]:
    fonte = fonte or {}
    inconsistente = _horario_futuro_inconsistente(fonte)
    data_iso = None if inconsistente else fonte.get("data_iso")
    return {
        "rodada": rodada,
        "mandante": mandante,
        "visitante": visitante,
        "event_id": str(fonte.get("event_id") or ""),
        "data_iso": data_iso,
        "estado": "pre" if inconsistente else str(fonte.get("estado") or ""),
        "concluido": bool(fonte.get("concluido") is True),
        "adiado": bool(fonte.get("adiado") is True),
        "data_definir": bool(inconsistente or fonte.get("data_definir") is True or not data_iso),
        "estadio": str(fonte.get("estadio") or ""),
        "origem": origem,
        "horario_descartado_inconsistente": inconsistente,
    }


def montar_calendario_completo(eventos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Monta as 38 rodadas a partir da matriz íntegra do primeiro turno."""
    falhas: list[dict[str, Any]] = []
    por_chave = {chave_evento(e): e for e in eventos}
    ida_por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in eventos:
        r = int(e.get("rodada") or 0)
        if 1 <= r <= 19:
            ida_por_rodada[r].append(e)

    calendario: list[dict[str, Any]] = []
    for rodada in range(1, 20):
        ida = sorted(
            ida_por_rodada.get(rodada, []),
            key=lambda x: (nome_time(x.get("mandante")), nome_time(x.get("visitante"))),
        )
        if len(ida) != 10:
            falhas.append({
                "tipo": "primeiro_turno_incompleto",
                "rodada": rodada,
                "jogos_mapeados": len(ida),
                "esperado": 10,
            })
        for e in ida:
            mandante = nome_time(e.get("mandante"))
            visitante = nome_time(e.get("visitante"))
            calendario.append(item_calendario(rodada, mandante, visitante, e, "ESPN/primeiro turno"))

            rodada_volta = rodada + 19
            retorno = por_chave.get((rodada_volta, visitante, mandante))
            calendario.append(item_calendario(
                rodada_volta,
                visitante,
                mandante,
                retorno,
                "ESPN/segundo turno" if retorno else "mando invertido do primeiro turno",
            ))

    calendario.sort(key=lambda x: (int(x["rodada"]), x["mandante"], x["visitante"]))
    return calendario, falhas


def auditar_calendario_completo(
    calendario: list[dict[str, Any]], clubes_esperados: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    falhas: list[dict[str, Any]] = []
    rodadas: list[dict[str, Any]] = []
    por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    por_clube: Counter[str] = Counter()
    mandos: Counter[tuple[str, str]] = Counter()
    pares: Counter[frozenset[str]] = Counter()

    for jogo in calendario:
        r = int(jogo.get("rodada") or 0)
        mandante = nome_time(jogo.get("mandante"))
        visitante = nome_time(jogo.get("visitante"))
        por_rodada[r].append(jogo)
        por_clube.update([mandante, visitante])
        mandos[(mandante, visitante)] += 1
        pares[frozenset((mandante, visitante))] += 1

    for rodada in range(1, 39):
        arr = por_rodada.get(rodada, [])
        clubes: list[str] = []
        for jogo in arr:
            clubes += [nome_time(jogo.get("mandante")), nome_time(jogo.get("visitante"))]
        repetidos = sorted(k for k, n in Counter(clubes).items() if k and n > 1)
        ausentes = sorted(clubes_esperados - set(clubes))
        integra = len(arr) == 10 and not repetidos and not ausentes and len(set(clubes)) == 20
        item = {
            "rodada": rodada,
            "jogos_mapeados": len(arr),
            "clubes_repetidos": repetidos,
            "clubes_ausentes": ausentes,
            "integra": integra,
        }
        rodadas.append(item)
        if not integra:
            falhas.append({"tipo": "rodada_incompleta_no_calendario_completo", **item})

    clubes_incorretos = [
        {"time": clube, "jogos_mapeados": por_clube.get(clube, 0), "esperado": 38}
        for clube in sorted(clubes_esperados)
        if por_clube.get(clube, 0) != 38
    ]
    if clubes_incorretos:
        falhas.append({"tipo": "clube_sem_38_jogos", "itens": clubes_incorretos})

    pares_incorretos = []
    for par, qtd in pares.items():
        times = sorted(par)
        if len(times) != 2:
            continue
        a, b = times
        ab = mandos.get((a, b), 0)
        ba = mandos.get((b, a), 0)
        if qtd != 2 or ab != 1 or ba != 1:
            pares_incorretos.append({
                "times": times,
                "jogos": qtd,
                "mando_a_b": ab,
                "mando_b_a": ba,
            })
    if pares_incorretos:
        falhas.append({"tipo": "confronto_sem_ida_e_volta", "itens": pares_incorretos})

    resumo = {
        "partidas_mapeadas": len(calendario),
        "rodadas_com_10_jogos": sum(1 for r in rodadas if r["integra"]),
        "clubes_com_38_jogos": sum(1 for clube in clubes_esperados if por_clube.get(clube, 0) == 38),
        "confrontos_com_ida_e_volta": sum(
            1 for par, qtd in pares.items()
            if len(par) == 2
            and qtd == 2
            and mandos.get(tuple(sorted(par)), 0) == 1
            and mandos.get(tuple(reversed(sorted(par))), 0) == 1
        ),
        "partidas_com_data_confirmada": sum(1 for j in calendario if j.get("data_iso")),
        "partidas_com_data_a_definir": sum(1 for j in calendario if not j.get("data_iso")),
    }
    return resumo, rodadas, falhas


def main() -> None:
    eventos = list(ler(ARQ_EVENTOS).get("eventos") or [])
    jogos = list(ler(ARQ_JOGOS).get("jogos") or [])
    resultados = list(ler(ARQ_RESULTADOS).get("resultados") or [])
    tabela = list(ler(ARQ_TABELA).get("tabela") or [])
    ajustes = list(ler(ARQ_AJUSTES).get("ajustes") or []) if ARQ_AJUSTES.exists() else []
    clubes_esperados = {str(x.get("time") or "").strip() for x in tabela if x.get("time")}

    calendario, falhas_calendario = montar_calendario_completo(eventos)
    resumo_completo, rodadas_completas, falhas_invariantes = auditar_calendario_completo(
        calendario, clubes_esperados
    )

    calendario_payload = {
        "gerado_em": datetime.now(FUSO_BRASILIA).isoformat(),
        "fonte": "ESPN + matriz de mandos do primeiro turno",
        "regra": "Rodadas 20 a 38 são o espelho obrigatório das rodadas 1 a 19, com mandos invertidos.",
        "total_partidas": len(calendario),
        "partidas_com_data_confirmada": resumo_completo["partidas_com_data_confirmada"],
        "partidas_com_data_a_definir": resumo_completo["partidas_com_data_a_definir"],
        "jogos": calendario,
    }
    ARQ_CALENDARIO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_CALENDARIO.write_text(
        json.dumps(calendario_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    por_rodada_espn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in eventos:
        por_rodada_espn[int(e.get("rodada") or 0)].append(e)

    rodadas_espn = []
    falhas: list[dict[str, Any]] = [*falhas_calendario, *falhas_invariantes]
    for r in sorted(k for k in por_rodada_espn if k):
        arr = por_rodada_espn[r]
        clubes: list[str] = []
        for e in arr:
            clubes += [nome_time(e.get("mandante")), nome_time(e.get("visitante"))]
        repetidos = sorted(k for k, n in Counter(clubes).items() if k and n > 1)
        ausentes = sorted(clubes_esperados - set(clubes)) if len(arr) >= 8 else []
        item = {
            "rodada": r,
            "jogos_mapeados": len(arr),
            "clubes_repetidos": repetidos,
            "clubes_ausentes": ausentes,
            "integra": len(arr) == 10 and not repetidos and len(set(clubes)) == 20,
        }
        rodadas_espn.append(item)
        if len(arr) > 10 or repetidos:
            falhas.append({"tipo": "rodada_espn_inconsistente", **item})

    jogos_sem_data = [
        {
            "event_id": e.get("event_id"), "rodada": e.get("rodada"),
            "mandante": nome_time(e.get("mandante")), "visitante": nome_time(e.get("visitante")),
            "status": e.get("status") or "Data a definir",
        }
        for e in eventos if e.get("data_definir") is True
    ]

    jogos_por_clube = sorted(
        ({"time": str(t.get("time")), "jogos_disputados": int(t.get("jogos") or 0)} for t in tabela),
        key=lambda x: (-x["jogos_disputados"], x["time"]),
    )
    distribuicao_jogos = Counter(x["jogos_disputados"] for x in jogos_por_clube)

    chaves_resultados = {chave_evento(r) for r in resultados}
    chaves_jogos = {chave_evento(j) for j in jogos}
    duplicados_publicos = sorted(chaves_resultados & chaves_jogos)
    if duplicados_publicos:
        falhas.append({"tipo": "jogo_em_resultados_e_proximos", "total": len(duplicados_publicos)})

    resumo = {
        "clubes": len(tabela),
        "partidas_previstas_campeonato": 380,
        "partidas_mapeadas_calendario_completo": resumo_completo["partidas_mapeadas"],
        "rodadas_com_10_jogos": resumo_completo["rodadas_com_10_jogos"],
        "clubes_com_38_jogos": resumo_completo["clubes_com_38_jogos"],
        "confrontos_com_ida_e_volta": resumo_completo["confrontos_com_ida_e_volta"],
        "partidas_com_data_confirmada": resumo_completo["partidas_com_data_confirmada"],
        "partidas_com_data_a_definir": resumo_completo["partidas_com_data_a_definir"],
        "resultados_publicados": len(resultados),
        "proximos_publicados": len(jogos),
        "eventos_espn_na_janela": len(eventos),
        "ajustes_calendario_configurados": len(ajustes),
        "jogos_adiados_sem_data": len(jogos_sem_data),
        "rodadas_espn_com_clube_repetido": sum(1 for r in rodadas_espn if r["clubes_repetidos"]),
        "falhas_graves": len(falhas),
    }

    saida = {
        "gerado_em": datetime.now(FUSO_BRASILIA).isoformat(),
        "fonte": "auditoria local sobre JSONs normalizados da ESPN",
        "escopo": "módulo Brasileirão; nenhum arquivo da Copa",
        "resumo": resumo,
        "distribuicao_jogos_disputados": {
            str(k): v for k, v in sorted(distribuicao_jogos.items(), reverse=True)
        },
        "jogos_disputados_por_clube": jogos_por_clube,
        "jogos_adiados_sem_data": jogos_sem_data,
        "rodadas_calendario_completo": rodadas_completas,
        "rodadas_presentes_na_janela_espn": rodadas_espn,
        "duplicados_entre_resultados_e_proximos": [
            {"rodada": r, "mandante": m, "visitante": v}
            for r, m, v in duplicados_publicos
        ],
        "falhas": falhas,
        "observacao": (
            "A ESPN é consultada de 1º de janeiro até 60 dias à frente. "
            "O calendario-completo.json preserva datas conhecidas e completa os 380 confrontos "
            "pela inversão obrigatória dos mandos do primeiro turno."
        ),
    }
    ARQ_SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Calendário completo gerado: {ARQ_CALENDARIO.relative_to(ROOT)}")
    print(f"Auditoria gerada: {ARQ_SAIDA.relative_to(ROOT)}")
    print(json.dumps(saida["resumo"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

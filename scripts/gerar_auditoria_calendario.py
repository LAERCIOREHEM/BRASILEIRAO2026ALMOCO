#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera e audita o calendário completo do Brasileirão 2026.

A matriz estrutural tem 380 partidas. A ESPN é a fonte preferencial para
rodadas, datas e IDs, mas o feed pode omitir temporariamente jogos já
conhecidos. Nessas situações, o último calendário estruturalmente íntegro é
usado como base e apenas os campos oficiais disponíveis são atualizados.

O arquivo válido anterior nunca é substituído por um calendário incompleto.
"""
from __future__ import annotations

import argparse
import json
import tempfile
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


def chave_mando(e: dict[str, Any]) -> tuple[str, str]:
    """Identidade estrutural: cada mando ocorre exatamente uma vez no campeonato."""
    return (nome_time(e.get("mandante")), nome_time(e.get("visitante")))


def escolher_fonte_evento(candidatos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Escolhe deterministicamente o evento útil entre IDs antigos/reagendados."""
    if not candidatos:
        return None

    def prioridade(item: dict[str, Any]) -> tuple[int, int, int, str, str]:
        estado = str(item.get("estado") or "").lower()
        concluido = item.get("concluido") is True or estado == "post"
        return (
            1 if item.get("resultado_manual") is True else 0,
            1 if concluido else 0,
            0 if item.get("adiado") is True and not concluido else 1,
            str(item.get("data_iso") or ""),
            str(item.get("event_id") or ""),
        )

    return max(candidatos, key=prioridade)


def gravar_json_atomico(path: Path, payload: dict[str, Any]) -> None:
    """Grava sem deixar arquivo parcial em caso de interrupção."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temporario = Path(tmp.name)
    temporario.replace(path)


def item_calendario(
    rodada: int,
    mandante: str,
    visitante: str,
    fonte: dict[str, Any] | None,
    origem: str,
) -> dict[str, Any]:
    fonte = fonte or {}
    data_bruta = fonte.get("data_iso")
    data_definir = bool(fonte.get("data_definir") is True or not data_bruta)
    # Se a própria origem marcou o kickoff como provisório/data a definir, o
    # calendário canônico não mantém esse timestamp no campo operacional. O
    # valor bruto continua disponível apenas para auditoria/proveniência.
    data_iso = None if data_definir else data_bruta
    data_anterior = str(fonte.get("data_espn_original") or fonte.get("data_fonte_anterior") or "")
    if data_definir and data_bruta and not data_anterior:
        data_anterior = str(data_bruta)
    return {
        "rodada": rodada,
        "mandante": mandante,
        "visitante": visitante,
        "event_id": str(fonte.get("event_id") or ""),
        "data_iso": data_iso,
        "estado": str(fonte.get("estado") or ""),
        "concluido": bool(fonte.get("concluido") is True),
        "adiado": bool(fonte.get("adiado") is True),
        "data_definir": data_definir,
        "estadio": str(fonte.get("estadio") or ""),
        "origem": origem,
        "fonte_calendario": str(fonte.get("fonte_calendario") or ""),
        "origem_calendario": str(fonte.get("origem_calendario") or ""),
        "data_fonte_anterior": data_anterior,
        "motivo_calendario": str(fonte.get("motivo_calendario") or ""),
    }


def rodada_estruturalmente_integra(
    itens: list[dict[str, Any]], clubes_esperados: set[str]
) -> bool:
    if len(itens) != 10:
        return False
    clubes: list[str] = []
    chaves: set[tuple[int, str, str]] = set()
    for item in itens:
        mandante = nome_time(item.get("mandante"))
        visitante = nome_time(item.get("visitante"))
        if not mandante or not visitante or mandante == visitante:
            return False
        chave = chave_evento(item)
        if chave in chaves:
            return False
        chaves.add(chave)
        clubes.extend((mandante, visitante))
    return (
        len(clubes) == 20
        and len(set(clubes)) == 20
        and (not clubes_esperados or set(clubes) == clubes_esperados)
    )


def calendario_anterior_valido(
    payload: dict[str, Any] | None, clubes_esperados: set[str]
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    jogos = list(payload.get("jogos") or payload.get("partidas") or [])
    if len(jogos) != 380:
        return []
    por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for jogo in jogos:
        por_rodada[int(jogo.get("rodada") or 0)].append(jogo)
    if any(
        not rodada_estruturalmente_integra(por_rodada.get(rodada, []), clubes_esperados)
        for rodada in range(1, 39)
    ):
        return []
    return jogos


def montar_calendario_completo(
    eventos: list[dict[str, Any]],
    clubes_esperados: set[str],
    calendario_anterior: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Monta 38 rodadas sem degradar um calendário válido por falha transitória."""
    falhas: list[dict[str, Any]] = []
    avisos: list[dict[str, Any]] = []
    anterior = list(calendario_anterior or [])

    atual_por_chave = {chave_evento(e): e for e in eventos if chave_evento(e)[0]}
    anterior_por_chave = {chave_evento(e): e for e in anterior if chave_evento(e)[0]}

    # A ESPN pode mudar a rodada editorial de um jogo adiado/reagendado. Como
    # cada combinação mandante->visitante ocorre uma única vez no Brasileirão,
    # o mando é a identidade estrutural mais estável para reaproveitar metadados.
    atuais_por_mando: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    anteriores_por_mando: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for evento in eventos:
        if all(chave_mando(evento)):
            atuais_por_mando[chave_mando(evento)].append(evento)
    for evento in anterior:
        if all(chave_mando(evento)):
            anteriores_por_mando[chave_mando(evento)].append(evento)
    atual_por_mando = {chave: escolher_fonte_evento(itens) for chave, itens in atuais_por_mando.items()}
    anterior_por_mando = {chave: escolher_fonte_evento(itens) for chave, itens in anteriores_por_mando.items()}

    atual_por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    anterior_por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for evento in eventos:
        rodada = int(evento.get("rodada") or 0)
        if 1 <= rodada <= 19:
            atual_por_rodada[rodada].append(evento)
    for evento in anterior:
        rodada = int(evento.get("rodada") or 0)
        if 1 <= rodada <= 19:
            anterior_por_rodada[rodada].append(evento)

    matriz_ida: dict[int, list[dict[str, Any]]] = {}
    for rodada in range(1, 20):
        atuais = atual_por_rodada.get(rodada, [])
        anteriores = anterior_por_rodada.get(rodada, [])
        if rodada_estruturalmente_integra(atuais, clubes_esperados):
            matriz_ida[rodada] = atuais
            continue
        if rodada_estruturalmente_integra(anteriores, clubes_esperados):
            matriz_ida[rodada] = anteriores
            avisos.append({
                "tipo": "rodada_preservada_do_calendario_anterior",
                "rodada": rodada,
                "jogos_espn_recebidos": len(atuais),
                "jogos_preservados": 10,
            })
            continue
        falhas.append({
            "tipo": "primeiro_turno_sem_base_integra",
            "rodada": rodada,
            "jogos_espn_recebidos": len(atuais),
            "jogos_calendario_anterior": len(anteriores),
            "esperado": 10,
        })

    if falhas:
        return [], falhas, avisos

    calendario: list[dict[str, Any]] = []
    for rodada in range(1, 20):
        ida = sorted(
            matriz_ida[rodada],
            key=lambda x: (nome_time(x.get("mandante")), nome_time(x.get("visitante"))),
        )
        for estrutura in ida:
            mandante = nome_time(estrutura.get("mandante"))
            visitante = nome_time(estrutura.get("visitante"))
            chave_ida = (rodada, mandante, visitante)
            mando_ida = (mandante, visitante)
            fonte_ida = (
                atual_por_mando.get(mando_ida)
                or atual_por_chave.get(chave_ida)
                or anterior_por_mando.get(mando_ida)
                or anterior_por_chave.get(chave_ida)
                or estrutura
            )
            origem_ida = (
                "ESPN/primeiro turno"
                if fonte_ida is not None and atual_por_mando.get(mando_ida) is fonte_ida
                else "calendário anterior íntegro/primeiro turno"
            )
            calendario.append(item_calendario(
                rodada, mandante, visitante, fonte_ida, origem_ida
            ))

            rodada_volta = rodada + 19
            chave_volta = (rodada_volta, visitante, mandante)
            mando_volta = (visitante, mandante)
            fonte_volta = (
                atual_por_mando.get(mando_volta)
                or atual_por_chave.get(chave_volta)
                or anterior_por_mando.get(mando_volta)
                or anterior_por_chave.get(chave_volta)
            )
            origem_volta = (
                "ESPN/segundo turno"
                if fonte_volta is not None and atual_por_mando.get(mando_volta) is fonte_volta
                else (
                    "calendário anterior íntegro/segundo turno"
                    if fonte_volta is not None
                    else "mando invertido do primeiro turno"
                )
            )
            calendario.append(item_calendario(
                rodada_volta, visitante, mandante, fonte_volta, origem_volta
            ))

    calendario.sort(key=lambda x: (int(x["rodada"]), x["mandante"], x["visitante"]))
    return calendario, falhas, avisos


def marcar_kickoffs_herdados_provisorios(
    calendario: list[dict[str, Any]], agora: datetime
) -> list[dict[str, Any]]:
    """Remove horários-placeholder herdados que não têm confirmação corrente.

    Critério deliberadamente conservador: em uma rodada futura, se 4 a 9
    partidas herdadas do calendário anterior têm exatamente o mesmo kickoff,
    não possuem confirmação CBF e coexistem com partidas ainda sem data, o
    timestamp é preservado apenas em ``data_fonte_anterior`` e deixa de ser
    publicado como horário confirmado.
    """
    por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in calendario:
        rodada = int(item.get("rodada") or 0)
        if 1 <= rodada <= 38:
            por_rodada[rodada].append(item)

    avisos: list[dict[str, Any]] = []
    for rodada, itens in sorted(por_rodada.items()):
        herdados: list[tuple[dict[str, Any], datetime]] = []
        for item in itens:
            if "calendário anterior íntegro" not in str(item.get("origem") or ""):
                continue
            if "CBF oficial" in str(item.get("fonte_calendario") or ""):
                continue
            # Aceita tanto o horário ainda ativo quanto o valor já suprimido
            # em execução anterior. Isso torna a auditoria idempotente e mantém
            # a razão da supressão visível em todas as execuções futuras.
            bruto = str(item.get("data_iso") or item.get("data_fonte_anterior") or "").strip()
            if not bruto:
                continue
            try:
                kickoff = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(tzinfo=FUSO_BRASILIA)
                kickoff = kickoff.astimezone(FUSO_BRASILIA)
            except ValueError:
                continue
            if kickoff < agora - timedelta(hours=6):
                continue
            herdados.append((item, kickoff))

        # O padrão só é suspeito quando a rodada não tem dez kickoffs distintos
        # e 4 a 9 jogos herdados compartilham exatamente o mesmo timestamp. Uma
        # rodada completa simultânea (caso clássico da R38) permanece.
        sem_data = sum(1 for item in itens if item.get("data_definir") is True or not item.get("data_iso"))
        timestamps = {kickoff.strftime("%Y-%m-%dT%H:%M") for _, kickoff in herdados}
        if not (4 <= len(herdados) < 10 and sem_data > 0 and len(timestamps) == 1):
            continue
        timestamp = next(iter(timestamps))
        for item, _ in herdados:
            anterior = str(item.get("data_iso") or "").strip()
            if anterior and not str(item.get("data_fonte_anterior") or "").strip():
                item["data_fonte_anterior"] = anterior
            item["data_iso"] = None
            item["data_definir"] = True
            item["motivo_calendario"] = (
                f"kickoff herdado provisório ({len(herdados)} jogos da R{rodada} em {timestamp})"
            )
        avisos.append({
            "tipo": "kickoff_herdado_provisorio",
            "rodada": rodada,
            "data_iso_anterior": timestamp,
            "jogos": len(herdados),
        })
    return avisos


def auditar_calendario_completo(
    calendario: list[dict[str, Any]], clubes_esperados: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    falhas: list[dict[str, Any]] = []
    rodadas: list[dict[str, Any]] = []
    por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    por_clube: Counter[str] = Counter()
    mandos: Counter[tuple[str, str]] = Counter()
    pares: Counter[frozenset[str]] = Counter()
    ids: Counter[str] = Counter()

    for jogo in calendario:
        r = int(jogo.get("rodada") or 0)
        mandante = nome_time(jogo.get("mandante"))
        visitante = nome_time(jogo.get("visitante"))
        por_rodada[r].append(jogo)
        por_clube.update([mandante, visitante])
        mandos[(mandante, visitante)] += 1
        pares[frozenset((mandante, visitante))] += 1
        event_id = str(jogo.get("event_id") or "").strip()
        if event_id:
            ids[event_id] += 1

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

    ids_duplicados = sorted(event_id for event_id, qtd in ids.items() if qtd > 1)
    if ids_duplicados:
        falhas.append({"tipo": "event_id_duplicado", "event_ids": ids_duplicados})

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
        "partidas_com_data_confirmada": sum(
            1 for j in calendario if j.get("data_iso") and j.get("data_definir") is not True
        ),
        "partidas_com_data_a_definir": sum(
            1 for j in calendario if j.get("data_definir") is True or not j.get("data_iso")
        ),
    }
    return resumo, rodadas, falhas


def executar_self_test() -> None:
    clubes = {f"Time {i:02d}" for i in range(1, 21)}
    times = sorted(clubes)
    rotacao = times[:]
    ida: list[dict[str, Any]] = []
    for rodada in range(1, 20):
        for i in range(10):
            a = rotacao[i]
            b = rotacao[-(i + 1)]
            mandante, visitante = (a, b) if (rodada + i) % 2 else (b, a)
            ida.append({
                "rodada": rodada,
                "mandante": mandante,
                "visitante": visitante,
                "event_id": f"IDA-{rodada:02d}-{i:02d}",
                "data_iso": "2026-01-01T16:00",
            })
        rotacao = [rotacao[0], rotacao[-1], *rotacao[1:-1]]

    completo, falhas, _ = montar_calendario_completo(ida, clubes, [])
    assert not falhas and len(completo) == 380
    resumo, _, falhas_auditoria = auditar_calendario_completo(completo, clubes)
    assert not falhas_auditoria
    assert resumo["partidas_mapeadas"] == 380
    assert resumo["rodadas_com_10_jogos"] == 38

    incompleto = [x for x in ida if not (x["rodada"] == 7 and x["event_id"].endswith("-03"))]
    preservado, falhas, avisos = montar_calendario_completo(incompleto, clubes, completo)
    assert not falhas and len(preservado) == 380
    assert any(x["rodada"] == 7 for x in avisos)
    resumo, _, falhas_auditoria = auditar_calendario_completo(preservado, clubes)
    assert not falhas_auditoria and resumo["partidas_mapeadas"] == 380

    # Regressão: a ESPN pode devolver uma partida com outra rodada após
    # reagendamento. O calendário mantém a rodada estrutural, mas incorpora o
    # novo event_id/data pelo mando, sem criar a 381ª partida.
    alvo = completo[0]
    reagendado = {
        "rodada": 99,
        "mandante": alvo["mandante"],
        "visitante": alvo["visitante"],
        "event_id": "ESPN-REAGENDADO",
        "data_iso": "2026-12-31T20:30",
        "estado": "pre",
    }
    com_reagendamento = [*ida, reagendado]
    recalc, falhas, _ = montar_calendario_completo(com_reagendamento, clubes, completo)
    assert not falhas and len(recalc) == 380
    recalc_alvo = next(
        x for x in recalc
        if x["mandante"] == alvo["mandante"] and x["visitante"] == alvo["visitante"]
    )
    assert recalc_alvo["rodada"] == alvo["rodada"]
    assert recalc_alvo["event_id"] == "ESPN-REAGENDADO"

    # Regressão: lote parcial herdado com horário idêntico não pode virar
    # kickoff público só porque existia no snapshot anterior.
    lote = []
    for i in range(5):
        lote.append({
            "rodada": 27, "mandante": f"A{i}", "visitante": f"B{i}",
            "data_iso": "2026-09-12T15:00", "data_definir": False,
            "origem": "calendário anterior íntegro/segundo turno",
            "fonte_calendario": "",
        })
    for i in range(5, 10):
        lote.append({
            "rodada": 27, "mandante": f"A{i}", "visitante": f"B{i}",
            "data_iso": None, "data_definir": True,
            "origem": "calendário anterior íntegro/segundo turno",
            "fonte_calendario": "",
        })
    avisos_lote = marcar_kickoffs_herdados_provisorios(
        lote, datetime(2026, 8, 15, 8, 0, tzinfo=FUSO_BRASILIA)
    )
    assert len(avisos_lote) == 1 and avisos_lote[0]["jogos"] == 5
    assert all(x.get("data_definir") is True for x in lote)
    assert all(x.get("data_iso") is None for x in lote)

    sem_base, falhas, _ = montar_calendario_completo(incompleto, clubes, [])
    assert not sem_base and falhas
    print("Self-test do calendário: OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        executar_self_test()
        return

    eventos = list(ler(ARQ_EVENTOS).get("eventos") or [])
    jogos = list(ler(ARQ_JOGOS).get("jogos") or [])
    resultados = list(ler(ARQ_RESULTADOS).get("resultados") or [])
    tabela = list(ler(ARQ_TABELA).get("tabela") or [])
    ajustes = list(ler(ARQ_AJUSTES).get("ajustes") or []) if ARQ_AJUSTES.exists() else []
    clubes_esperados = {str(x.get("time") or "").strip() for x in tabela if x.get("time")}
    if len(clubes_esperados) != 20:
        raise RuntimeError(f"Tabela inválida para gerar calendário: {len(clubes_esperados)} clubes")

    anterior_payload = ler(ARQ_CALENDARIO) if ARQ_CALENDARIO.exists() else None
    anterior = calendario_anterior_valido(anterior_payload, clubes_esperados)

    calendario, falhas_montagem, avisos = montar_calendario_completo(
        eventos, clubes_esperados, anterior
    )
    agora = datetime.now(FUSO_BRASILIA)
    avisos.extend(marcar_kickoffs_herdados_provisorios(calendario, agora))
    if falhas_montagem:
        raise RuntimeError(
            "Calendário não foi alterado: feed atual incompleto e não existe base anterior íntegra. "
            + json.dumps(falhas_montagem, ensure_ascii=False)
        )

    resumo_completo, rodadas_completas, falhas_invariantes = auditar_calendario_completo(
        calendario, clubes_esperados
    )
    if falhas_invariantes or resumo_completo["partidas_mapeadas"] != 380:
        raise RuntimeError(
            "Calendário candidato rejeitado antes da gravação: "
            + json.dumps(falhas_invariantes, ensure_ascii=False)
        )

    preservados_sem_confirmacao: list[dict[str, Any]] = []
    for item in calendario:
        data_iso = str(item.get("data_iso") or "").strip()
        if not data_iso or "calendário anterior íntegro" not in str(item.get("origem") or ""):
            continue
        try:
            kickoff = datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=FUSO_BRASILIA)
            kickoff = kickoff.astimezone(FUSO_BRASILIA)
        except ValueError:
            continue
        if kickoff < agora - timedelta(hours=6):
            continue
        if "CBF oficial" in str(item.get("fonte_calendario") or ""):
            continue
        aviso = {
            "tipo": "kickoff_futuro_preservado_sem_confirmacao_atual",
            "rodada": int(item.get("rodada") or 0),
            "mandante": item.get("mandante"),
            "visitante": item.get("visitante"),
            "data_iso": data_iso,
        }
        preservados_sem_confirmacao.append(aviso)
    avisos.extend(preservados_sem_confirmacao)

    por_rodada_espn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in eventos:
        por_rodada_espn[int(e.get("rodada") or 0)].append(e)

    provisorios_espn: list[dict[str, Any]] = []
    for r, arr in sorted(por_rodada_espn.items()):
        if not (1 <= r <= 38):
            continue

        # Quando o normalizador já identificou o lote como placeholder, mantém
        # essa informação visível na auditoria mesmo com data_definir=true.
        marcados = [
            e for e in arr
            if "kickoff ESPN provisório" in str(e.get("motivo_ajuste") or "")
        ]
        if marcados:
            datas_marcadas = {str(e.get("data_iso") or "").strip() for e in marcados if e.get("data_iso")}
            provisorios_espn.append({
                "tipo": "kickoff_espn_provisorio",
                "rodada": r,
                "data_iso": next(iter(datas_marcadas)) if len(datas_marcadas) == 1 else None,
                "jogos": len(marcados),
            })
            continue

        futuros_datados = [
            e for e in arr
            if str(e.get("estado") or "pre").lower() != "post"
            and e.get("data_definir") is not True
            and str(e.get("data_iso") or "").strip()
        ]
        datas = [str(e.get("data_iso") or "").strip() for e in futuros_datados]
        # Mesmo critério conservador usado pela agenda pública: feed incompleto
        # com >=4 jogos no exato mesmo timestamp é tratado como lote provisório
        # até detalhamento da ESPN ou confirmação da CBF. Uma rodada completa
        # simultânea (ex.: R38) não entra nesta regra.
        if 4 <= len(datas) < 10 and len(set(datas)) == 1:
            provisorios_espn.append({
                "tipo": "kickoff_espn_provisorio",
                "rodada": r,
                "data_iso": datas[0],
                "jogos": len(datas),
            })
    avisos.extend(provisorios_espn)

    rodadas_espn = []
    falhas: list[dict[str, Any]] = []
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
        "jogos_adiados_sem_data": sum(
            1 for e in eventos if e.get("data_definir") is True and e.get("adiado") is True
        ),
        "jogos_com_data_a_definir": len(jogos_sem_data),
        "rodadas_espn_com_clube_repetido": sum(1 for r in rodadas_espn if r["clubes_repetidos"]),
        "rodadas_preservadas_do_calendario_anterior": sum(
            1 for aviso in avisos if aviso.get("tipo") == "rodada_preservada_do_calendario_anterior"
        ),
        "kickoffs_confirmados_cbf": sum(
            1 for item in calendario if "CBF oficial" in str(item.get("fonte_calendario") or "")
        ),
        "kickoffs_preservados_sem_confirmacao_atual": len(preservados_sem_confirmacao),
        "kickoffs_espn_provisorios_suprimidos_da_agenda": sum(int(x.get("jogos") or 0) for x in provisorios_espn),
        "kickoffs_herdados_provisorios_suprimidos": sum(
            int(x.get("jogos") or 0) for x in avisos if x.get("tipo") == "kickoff_herdado_provisorio"
        ),
        "falhas_graves": len(falhas),
    }

    calendario_payload = {
        "gerado_em": datetime.now(FUSO_BRASILIA).isoformat(),
        "fonte": "ESPN + último calendário íntegro + matriz de mandos do primeiro turno",
        "regra": (
            "O feed ESPN atualiza dados oficiais. Se uma rodada do primeiro turno vier incompleta, "
            "a estrutura válida anterior é preservada. Rodadas 20 a 38 espelham as rodadas 1 a 19."
        ),
        "total_partidas": 380,
        "partidas_com_data_confirmada": resumo_completo["partidas_com_data_confirmada"],
        "partidas_com_data_a_definir": resumo_completo["partidas_com_data_a_definir"],
        "jogos": calendario,
    }

    saida = {
        "gerado_em": datetime.now(FUSO_BRASILIA).isoformat(),
        "fonte": "auditoria local sobre JSONs normalizados da ESPN",
        "escopo": "módulo Brasileirão; nenhum arquivo da Copa",
        "resumo": resumo,
        "avisos": avisos,
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
            "O calendário só é substituído depois de validar 380 partidas, 38 rodadas íntegras, "
            "20 clubes com 38 jogos e 190 confrontos de ida e volta."
        ),
    }

    # A gravação ocorre somente depois de todas as invariantes estruturais passarem.
    gravar_json_atomico(ARQ_CALENDARIO, calendario_payload)
    gravar_json_atomico(ARQ_SAIDA, saida)
    print(f"Calendário completo gerado: {ARQ_CALENDARIO.relative_to(ROOT)}")
    print(f"Auditoria gerada: {ARQ_SAIDA.relative_to(ROOT)}")
    if avisos:
        for aviso in avisos:
            if aviso.get("tipo") == "rodada_preservada_do_calendario_anterior":
                print(
                    "::warning::Calendário preservou a rodada "
                    f"{aviso['rodada']} porque a ESPN retornou {aviso['jogos_espn_recebidos']}/10 jogos."
                )
            elif aviso.get("tipo") == "kickoff_futuro_preservado_sem_confirmacao_atual":
                print(
                    "::warning::Kickoff futuro preservado sem confirmação CBF nesta execução: "
                    f"R{aviso['rodada']} {aviso['mandante']} x {aviso['visitante']} — {aviso['data_iso']}"
                )
            elif aviso.get("tipo") == "kickoff_espn_provisorio":
                print(
                    "::warning::Lote de kickoff ESPN tratado como provisório e suprimido da agenda pública: "
                    f"R{aviso['rodada']} — {aviso['jogos']} jogos em {aviso['data_iso']}"
                )
            elif aviso.get("tipo") == "kickoff_herdado_provisorio":
                print(
                    "::warning::Kickoff herdado tratado como provisório e removido do calendário confirmado: "
                    f"R{aviso['rodada']} — {aviso['jogos']} jogos em {aviso['data_iso_anterior']}"
                )
    print(json.dumps(saida["resumo"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

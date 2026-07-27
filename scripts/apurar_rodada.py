#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apurar_rodada.py — Apuração auditável das apostas do Brasileirão 2026.

Execução 4:
  - preserva a Rodada 20 e os formatos anteriores;
  - pontua somente partidas comprovadamente encerradas;
  - atualiza rankings parciais por rodada, bloco, geral e liga;
  - calcula índice transparente de aproveitamento;
  - só conclui rodada com 10/10 e bloco com 30/30;
  - mantém jogos adiados/sem resultado como pendentes;
  - sincroniza a finalização automática no Supabase por RPC restrita ao
    service_role;
  - gera JSONs públicos sem quebrar consumidores antigos.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

FUSO_BRT = timezone(timedelta(hours=-3))
TEMPORADA = int(os.environ.get("BRASILEIRAO_TEMPORADA", "2026"))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ROOT = Path(__file__).resolve().parents[1]
ESTADOS_FINAIS = {"post", "final", "finished", "complete", "completed", "encerrado"}
ESTADOS_ADIADOS = {"postponed", "adiado", "adiada", "suspended", "suspenso", "cancelled", "canceled"}
BLOCOS_PADRAO = (
    (21, 23, "Bloco 21–23"),
    (24, 26, "Bloco 24–26"),
    (27, 29, "Bloco 27–29"),
    (30, 32, "Bloco 30–32"),
    (33, 35, "Bloco 33–35"),
    (36, 38, "Bloco 36–38"),
)


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRT)


def iso_agora() -> str:
    return agora_brt().isoformat()


def carregar_json(nome: str, fallback: Any) -> Any:
    caminho = ROOT / nome
    if not caminho.exists():
        return fallback
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: não consegui ler {nome}: {exc}")
        return fallback


def parse_dt(valor: Any) -> datetime | None:
    if not valor:
        return None
    texto = str(valor)
    try:
        if texto.endswith("Z"):
            return datetime.fromisoformat(texto.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=FUSO_BRT)
        return dt
    except ValueError:
        return None


def normalizar(valor: Any) -> str:
    import re
    import unicodedata

    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "-", texto.lower()).strip("-")


def nome_time(valor: Any) -> str:
    if isinstance(valor, dict):
        return str(valor.get("nome") or valor.get("name") or "")
    return str(valor or "")


def jogo_id(jogo: dict[str, Any]) -> str:
    if jogo.get("event_id"):
        return str(jogo["event_id"])
    if jogo.get("id"):
        return str(jogo["id"])
    mandante = normalizar(nome_time(jogo.get("mandante")))
    visitante = normalizar(nome_time(jogo.get("visitante")))
    data = str(jogo.get("data_iso") or "")[:16]
    return f"{jogo.get('rodada')}-{mandante}-{visitante}-{data}"


def placar_disponivel(jogo: dict[str, Any]) -> bool:
    return jogo.get("placar_mandante") is not None and jogo.get("placar_visitante") is not None


def resultado_temporalmente_plausivel(jogo: dict[str, Any]) -> bool:
    kickoff = parse_dt(jogo.get("data_iso"))
    return not kickoff or kickoff <= agora_brt() + timedelta(minutes=5)


def jogo_finalizado(jogo: dict[str, Any]) -> bool:
    if not placar_disponivel(jogo):
        return False
    estado = str(jogo.get("estado") or jogo.get("state") or "").strip().lower()
    concluido = jogo.get("concluido") is True or jogo.get("completed") is True
    return (estado in ESTADOS_FINAIS or concluido) and resultado_temporalmente_plausivel(jogo)


def jogo_adiado(jogo: dict[str, Any]) -> bool:
    estado = str(
        jogo.get("estado")
        or jogo.get("state")
        or jogo.get("status")
        or ""
    ).strip().lower()
    texto = normalizar(estado)
    return bool(jogo.get("adiado") is True or estado in ESTADOS_ADIADOS or any(x in texto for x in ESTADOS_ADIADOS))


def jogo_para_evento(evento: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": evento.get("event_id"),
        "rodada": evento.get("rodada"),
        "data_iso": evento.get("data_iso"),
        "mandante": {"nome": evento.get("mandante")},
        "visitante": {"nome": evento.get("visitante")},
        "placar_mandante": evento.get("placar_mandante"),
        "placar_visitante": evento.get("placar_visitante"),
        "estado": evento.get("estado"),
        "concluido": evento.get("concluido"),
        "status": evento.get("status"),
        "finalizado_em": evento.get("finalizado_em"),
        "fonte_resultado": evento.get("fonte_resultado"),
        "adiado": evento.get("adiado"),
    }


def escolher_mais_confiavel(
    atual: dict[str, Any] | None,
    candidato: dict[str, Any],
) -> dict[str, Any]:
    if atual is None:
        return candidato
    if jogo_finalizado(candidato) and not jogo_finalizado(atual):
        return candidato
    if jogo_finalizado(atual) and not jogo_finalizado(candidato):
        return atual
    riqueza_atual = sum(
        atual.get(k) not in (None, "")
        for k in ("estado", "concluido", "finalizado_em", "fonte_resultado", "status")
    )
    riqueza_candidato = sum(
        candidato.get(k) not in (None, "")
        for k in ("estado", "concluido", "finalizado_em", "fonte_resultado", "status")
    )
    return candidato if riqueza_candidato >= riqueza_atual else atual


def carregar_todos_jogos() -> list[dict[str, Any]]:
    jogos = carregar_json("jogos.json", {}).get("jogos", []) or []
    resultados = carregar_json("resultados.json", {}).get("resultados", []) or []
    eventos = carregar_json("espn_eventos.json", {}).get("eventos", []) or []
    todos: dict[str, dict[str, Any]] = {}
    for item in jogos:
        if isinstance(item, dict):
            jid = jogo_id(item)
            todos[jid] = escolher_mais_confiavel(todos.get(jid), item)
    for item in resultados:
        if isinstance(item, dict):
            jid = jogo_id(item)
            todos[jid] = escolher_mais_confiavel(todos.get(jid), item)
    for evento in eventos:
        if isinstance(evento, dict):
            item = jogo_para_evento(evento)
            jid = jogo_id(item)
            todos[jid] = escolher_mais_confiavel(todos.get(jid), item)
    return list(todos.values())


def carregar_resultados_finais() -> list[dict[str, Any]]:
    resultados = carregar_json("resultados.json", {}).get("resultados", []) or []
    finais: list[dict[str, Any]] = []
    for jogo in resultados:
        if not isinstance(jogo, dict):
            continue
        if jogo_finalizado(jogo):
            finais.append(jogo)
        else:
            print(f"Aviso: resultado rejeitado por estado/tempo inconsistente: {jogo_id(jogo)}")
    return finais


def resultado_mapa(jogos: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapa: dict[str, dict[str, Any]] = {}
    for jogo in jogos:
        if not jogo_finalizado(jogo):
            continue
        rid = jogo_id(jogo)
        resultado = {
            "event_id": rid,
            "rodada": int(jogo.get("rodada") or 0),
            "mandante": nome_time(jogo.get("mandante")),
            "visitante": nome_time(jogo.get("visitante")),
            "placar_mandante": int(jogo["placar_mandante"]),
            "placar_visitante": int(jogo["placar_visitante"]),
            "data_iso": jogo.get("data_iso"),
            "estado": str(jogo.get("estado") or "post").lower(),
            "concluido": bool(
                jogo.get("concluido") is True
                or str(jogo.get("estado") or "").lower() in ESTADOS_FINAIS
            ),
            "finalizado_em": jogo.get("finalizado_em"),
            "fonte_resultado": jogo.get("fonte_resultado") or "ESPN/resultados.json",
        }
        mapa[rid] = resultado
        if jogo.get("event_id"):
            mapa[str(jogo["event_id"])] = resultado
    return mapa


def sinal(n: int) -> int:
    return 1 if n > 0 else -1 if n < 0 else 0


def calcular(palpite: dict[str, Any], resultado: dict[str, Any]) -> dict[str, Any]:
    pm, pv = int(palpite["placar_mandante"]), int(palpite["placar_visitante"])
    rm, rv = int(resultado["placar_mandante"]), int(resultado["placar_visitante"])
    if pm == rm and pv == rv:
        return {"pontos": 5, "tipo": "exato"}
    sinal_palpite, sinal_real = sinal(pm - pv), sinal(rm - rv)
    if sinal_palpite != sinal_real:
        return {"pontos": 0, "tipo": "erro"}
    if sinal_real == 0:
        return {"pontos": 2, "tipo": "resultado"}
    if (pm - pv) == (rm - rv):
        return {"pontos": 3, "tipo": "saldo"}
    return {"pontos": 2, "tipo": "resultado"}


def palpite_valido_no_prazo(palpite: dict[str, Any]) -> bool:
    atualizado = parse_dt(palpite.get("atualizado_em") or palpite.get("criado_em"))
    fecha = parse_dt(palpite.get("fecha_em"))
    if not atualizado or not fecha:
        return True
    return atualizado <= fecha


def cabecalhos_supabase() -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY precisam estar cadastrados nos Secrets do GitHub."
        )
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def rest_get(tabela: str, params: dict[str, str]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{tabela}?{query}"
    req = urllib.request.Request(url, headers=cabecalhos_supabase())
    with urllib.request.urlopen(req, timeout=45) as resposta:
        data = json.loads(resposta.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Resposta inesperada do Supabase em {tabela}: {data!r}")
    return data


def rpc_service(nome: str, payload: dict[str, Any]) -> Any:
    url = f"{SUPABASE_URL}/rest/v1/rpc/{nome}"
    bruto = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=bruto,
        headers=cabecalhos_supabase(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resposta:
            texto = resposta.read().decode("utf-8")
            return json.loads(texto) if texto else None
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"RPC {nome} falhou ({exc.code}): {corpo}") from exc


def buscar_supabase() -> dict[str, list[dict[str, Any]]]:
    dados: dict[str, list[dict[str, Any]]] = {}
    dados["palpites"] = rest_get(
        "br_palpites",
        {
            "temporada": f"eq.{TEMPORADA}",
            "select": "*",
            "order": "rodada.asc,membro.asc,kickoff.asc",
        },
    )
    dados["configs"] = rest_get(
        "br_config_rodadas",
        {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada.asc"},
    )
    dados["comprovantes"] = rest_get(
        "br_comprovantes",
        {
            "temporada": f"eq.{TEMPORADA}",
            "select": "*",
            "order": "rodada.asc,atualizado_em.desc",
        },
    )
    dados["auditoria"] = rest_get(
        "br_palpites_auditoria",
        {
            "temporada": f"eq.{TEMPORADA}",
            "select": "*",
            "order": "rodada.asc,criado_em.desc",
        },
    )
    dados["participantes"] = rest_get(
        "br_participantes",
        {"select": "id,nome,login,ativo,admin", "order": "nome.asc"},
    )
    try:
        dados["ligas"] = rest_get(
            "br_ligas",
            {"select": "id,nome,slug,descricao,ativa", "order": "nome.asc"},
        )
        dados["liga_participantes"] = rest_get(
            "br_liga_participantes",
            {"select": "liga_id,participante_id,papel,ativo", "order": "liga_id.asc"},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: tabelas de liga indisponíveis; rankings por liga ficarão vazios: {exc}")
        dados["ligas"], dados["liga_participantes"] = [], []
    try:
        dados["blocos"] = rest_get(
            "br_blocos_apostas",
            {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada_inicio.asc"},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: tabela de blocos indisponível; usando os seis intervalos fixos: {exc}")
        dados["blocos"] = []
    return dados


def config_publica(config: dict[str, Any] | None) -> bool:
    if not config:
        return False
    status = str(config.get("status") or "").lower()
    if status in {"apurada", "publicada"}:
        return True
    publica = parse_dt(config.get("publica_em"))
    if not publica and config.get("bloco_id"):
        publica = parse_dt(config.get("fecha_em"))
    return bool(publica and agora_brt() >= publica)


def por_rodada_config(configs: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    saida: dict[int, dict[str, Any]] = {}
    for config in configs:
        try:
            saida[int(config.get("rodada"))] = config
        except Exception:  # noqa: BLE001
            continue
    return saida


def jogos_por_rodada(jogos: Iterable[dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    saida: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for jogo in jogos:
        try:
            rodada = int(jogo.get("rodada") or 0)
        except Exception:  # noqa: BLE001
            continue
        if rodada <= 0:
            continue
        jid = jogo_id(jogo)
        saida[rodada][jid] = escolher_mais_confiavel(saida[rodada].get(jid), jogo)
    return saida


def resumo_auditoria(
    rodada: int,
    palpites: list[dict[str, Any]],
    comprovantes: list[dict[str, Any]],
    auditoria: list[dict[str, Any]],
    total_jogos: int,
) -> list[dict[str, Any]]:
    por_participante: dict[str, dict[str, Any]] = {}
    for palpite in palpites:
        if int(palpite.get("rodada") or 0) != rodada:
            continue
        chave = str(palpite.get("participante_id") or palpite.get("membro") or "")
        if not chave:
            continue
        item = por_participante.setdefault(
            chave,
            {
                "participante_id": palpite.get("participante_id"),
                "membro": palpite.get("membro") or "—",
                "total_jogos": total_jogos,
                "total_palpites": 0,
                "primeiro_envio": None,
                "ultimo_envio": None,
                "hash_fechamento": palpite.get("hash_fechamento"),
                "hash_bloco": palpite.get("hash_bloco"),
                "alteracoes": 0,
            },
        )
        item["total_palpites"] += 1
        for campo in ("criado_em", "atualizado_em"):
            dt = parse_dt(palpite.get(campo))
            if not dt:
                continue
            if item["primeiro_envio"] is None or dt < parse_dt(item["primeiro_envio"]):
                item["primeiro_envio"] = dt.isoformat()
            if item["ultimo_envio"] is None or dt > parse_dt(item["ultimo_envio"]):
                item["ultimo_envio"] = dt.isoformat()
        if palpite.get("hash_fechamento"):
            item["hash_fechamento"] = palpite.get("hash_fechamento")
        if palpite.get("hash_bloco"):
            item["hash_bloco"] = palpite.get("hash_bloco")
    for comprovante in comprovantes:
        if int(comprovante.get("rodada") or 0) != rodada:
            continue
        chave = str(comprovante.get("participante_id") or "")
        item = por_participante.setdefault(
            chave,
            {
                "participante_id": comprovante.get("participante_id"),
                "membro": chave,
                "total_jogos": total_jogos,
                "total_palpites": int(comprovante.get("total_palpites") or 0),
                "primeiro_envio": comprovante.get("criado_em"),
                "ultimo_envio": comprovante.get("atualizado_em"),
                "hash_fechamento": comprovante.get("hash_fechamento"),
                "alteracoes": 0,
            },
        )
        item["hash_fechamento"] = comprovante.get("hash_fechamento") or item.get("hash_fechamento")
    for evento in auditoria:
        if int(evento.get("rodada") or 0) != rodada:
            continue
        chave = str(evento.get("participante_id") or evento.get("membro") or "")
        item = por_participante.setdefault(
            chave,
            {
                "participante_id": evento.get("participante_id"),
                "membro": evento.get("membro") or chave,
                "total_jogos": total_jogos,
                "total_palpites": 0,
                "alteracoes": 0,
            },
        )
        item["alteracoes"] = int(item.get("alteracoes") or 0) + 1
    for item in por_participante.values():
        total = int(item.get("total_jogos") or 0)
        preenchidos = int(item.get("total_palpites") or 0)
        item["percentual"] = round((preenchidos / total) * 100, 1) if total else 0
    return sorted(por_participante.values(), key=lambda x: str(x.get("membro") or ""))


def chave_desempate(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        int(row.get("pontos") or 0),
        int(row.get("cravadas") or 0),
        int(row.get("saldos") or 0),
        int(row.get("resultados") or 0),
        -int(row.get("erros") or 0),
    )


def indice_aproveitamento(pontos: int, jogos_apurados: int) -> float:
    if jogos_apurados <= 0:
        return 0.0
    return round((pontos / (5 * jogos_apurados)) * 100, 1)


def completar_metricas_ranking(
    rows: Iterable[dict[str, Any]],
    jogos_apurados: int,
) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        row["jogos_apurados"] = jogos_apurados
        row["maximo_pontos"] = jogos_apurados * 5
        row["indice_aproveitamento"] = indice_aproveitamento(
            int(row.get("pontos") or 0), jogos_apurados
        )
        saida.append(row)
    return saida


def ordenar_ranking(
    rows: Iterable[dict[str, Any]],
    jogos_apurados: int | None = None,
) -> list[dict[str, Any]]:
    saida = sorted(
        (dict(row) for row in rows),
        key=lambda x: (
            -int(x.get("pontos") or 0),
            -int(x.get("cravadas") or 0),
            -int(x.get("saldos") or 0),
            -int(x.get("resultados") or 0),
            int(x.get("erros") or 0),
            str(x.get("membro") or "").casefold(),
        ),
    )
    if jogos_apurados is not None:
        saida = completar_metricas_ranking(saida, jogos_apurados)
    for posicao, row in enumerate(saida, 1):
        row["pos"] = posicao
    return saida


def vencedores_ranking(ranking: list[dict[str, Any]]) -> list[str]:
    if not ranking:
        return []
    chave_topo = chave_desempate(ranking[0])
    return [str(row.get("membro") or "") for row in ranking if chave_desempate(row) == chave_topo]


def gerar_indices_ligas(
    ligas: Iterable[dict[str, Any]],
    liga_participantes: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    ligas_map: dict[str, dict[str, Any]] = {}
    membros_por_liga: dict[str, set[str]] = defaultdict(set)
    for liga in ligas:
        if not liga.get("ativa", True):
            continue
        lid = str(liga.get("id") or "")
        if not lid:
            continue
        slug = str(liga.get("slug") or normalizar(liga.get("nome")) or lid)
        ligas_map[lid] = {
            "id": lid,
            "nome": liga.get("nome"),
            "slug": slug,
            "descricao": liga.get("descricao"),
        }
    for vinculo in liga_participantes:
        if not vinculo.get("ativo", True):
            continue
        lid = str(vinculo.get("liga_id") or "")
        pid = str(vinculo.get("participante_id") or "")
        if lid in ligas_map and pid:
            membros_por_liga[lid].add(pid)
    return ligas_map, membros_por_liga


def ranking_ligas(
    ranking: list[dict[str, Any]],
    ligas_map: dict[str, dict[str, Any]],
    membros_por_liga: dict[str, set[str]],
    jogos_apurados: int,
) -> dict[str, list[dict[str, Any]]]:
    saida: dict[str, list[dict[str, Any]]] = {}
    for lid, liga in ligas_map.items():
        membros = membros_por_liga.get(lid, set())
        rows = [dict(row) for row in ranking if str(row.get("participante_id") or "") in membros]
        rows = ordenar_ranking(rows, jogos_apurados)
        saida[lid] = rows
        if liga.get("slug"):
            saida[str(liga["slug"])] = rows
    return saida


def vencedores_ligas(rankings_por_liga: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {chave: vencedores_ranking(ranking) for chave, ranking in rankings_por_liga.items()}


def nova_linha(participante_id: str, membro: str) -> dict[str, Any]:
    return {
        "participante_id": participante_id,
        "membro": membro,
        "pontos": 0,
        "cravadas": 0,
        "saldos": 0,
        "resultados": 0,
        "erros": 0,
        "palpites_validos": 0,
    }


def somar_linha(destino: dict[str, Any], origem: dict[str, Any]) -> None:
    for campo in ("pontos", "cravadas", "saldos", "resultados", "erros", "palpites_validos"):
        destino[campo] = int(destino.get(campo) or 0) + int(origem.get(campo) or 0)


def agregar_rankings(
    rankings: Iterable[list[dict[str, Any]]],
    jogos_apurados: int,
) -> list[dict[str, Any]]:
    acumulado: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for row in ranking:
            pid = str(row.get("participante_id") or row.get("membro") or "")
            membro = str(row.get("membro") or "").strip()
            if not pid or not membro:
                continue
            destino = acumulado.setdefault(pid, nova_linha(pid, membro))
            somar_linha(destino, row)
    return ordenar_ranking(acumulado.values(), jogos_apurados)


def agregar_rankings_liga(
    itens: Iterable[dict[str, list[dict[str, Any]]]],
    ligas_map: dict[str, dict[str, Any]],
    jogos_apurados: int,
) -> dict[str, list[dict[str, Any]]]:
    saida: dict[str, list[dict[str, Any]]] = {}
    for lid, liga in ligas_map.items():
        chaves = [lid, str(liga.get("slug") or "")]
        listas: list[list[dict[str, Any]]] = []
        for item in itens:
            ranking = next((item[chave] for chave in chaves if chave and isinstance(item.get(chave), list)), None)
            if ranking is not None:
                listas.append(ranking)
        agregado = agregar_rankings(listas, jogos_apurados)
        saida[lid] = agregado
        if liga.get("slug"):
            saida[str(liga["slug"])] = agregado
    return saida


def estado_apuracao(publicada: bool, jogos_apurados: int, total_esperado: int, concluida: bool) -> str:
    if not publicada:
        return "sigilosa"
    if concluida:
        return "concluida"
    if jogos_apurados <= 0:
        return "aguardando_resultados"
    if jogos_apurados < total_esperado:
        return "parcial"
    return "validacao_pendente"


def pendencias_rodada(
    rodada: int,
    jogos_rodada: dict[str, dict[str, Any]],
    resultados: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    pendentes: list[dict[str, Any]] = []
    for jid, jogo in sorted(jogos_rodada.items(), key=lambda item: str(item[1].get("data_iso") or "")):
        if jid in resultados or str(jogo.get("event_id") or "") in resultados:
            continue
        pendentes.append(
            {
                "event_id": jid,
                "rodada": rodada,
                "mandante": nome_time(jogo.get("mandante")),
                "visitante": nome_time(jogo.get("visitante")),
                "data_iso": jogo.get("data_iso"),
                "adiado": jogo_adiado(jogo),
                "status": jogo.get("status") or jogo.get("estado") or "Aguardando resultado final",
            }
        )
    faltantes_calendario = max(0, 10 - len(jogos_rodada))
    for indice in range(faltantes_calendario):
        pendentes.append(
            {
                "event_id": f"calendario-a-confirmar-r{rodada}-{indice + 1}",
                "rodada": rodada,
                "mandante": "A confirmar",
                "visitante": "A confirmar",
                "data_iso": None,
                "adiado": False,
                "status": "Partida ainda ausente do calendário consolidado",
            }
        )
    return pendentes


def apurar_rodada(
    rodada: int,
    config: dict[str, Any] | None,
    palpites: list[dict[str, Any]],
    comprovantes: list[dict[str, Any]],
    auditoria: list[dict[str, Any]],
    jogos_rodada: dict[str, dict[str, Any]],
    resultados: dict[str, dict[str, Any]],
    ligas_map: dict[str, dict[str, Any]],
    membros_por_liga: dict[str, set[str]],
) -> dict[str, Any]:
    publicada = config_publica(config)
    palpites_rodada = [p for p in palpites if int(p.get("rodada") or 0) == rodada]
    ids_finais: set[str] = set()
    detalhes_jogos: dict[str, dict[str, Any]] = {}
    acumulado: dict[str, dict[str, Any]] = {}
    descartados = 0

    if publicada:
        for palpite in palpites_rodada:
            membro = str(palpite.get("membro") or "").strip()
            participante_id = str(palpite.get("participante_id") or membro)
            if not membro or not participante_id:
                continue
            eid = str(palpite.get("event_id") or palpite.get("jogo_chave") or "")
            resultado = resultados.get(eid)
            if not resultado:
                continue
            if not palpite_valido_no_prazo(palpite):
                descartados += 1
                continue
            detalhe = calcular(palpite, resultado)
            rid = str(resultado.get("event_id") or eid)
            ids_finais.add(rid)
            row = acumulado.setdefault(participante_id, nova_linha(participante_id, membro))
            row["pontos"] += detalhe["pontos"]
            row["palpites_validos"] += 1
            if detalhe["tipo"] == "exato":
                row["cravadas"] += 1
            elif detalhe["tipo"] == "saldo":
                row["saldos"] += 1
            elif detalhe["tipo"] == "resultado":
                row["resultados"] += 1
            else:
                row["erros"] += 1

            jogo = detalhes_jogos.setdefault(
                rid,
                {"event_id": rid, "resultado": resultado, "palpites": []},
            )
            jogo["palpites"].append(
                {
                    "participante_id": participante_id,
                    "membro": membro,
                    "palpite": f"{palpite.get('placar_mandante')}×{palpite.get('placar_visitante')}",
                    "placar_mandante": int(palpite.get("placar_mandante")),
                    "placar_visitante": int(palpite.get("placar_visitante")),
                    "pontos": detalhe["pontos"],
                    "tipo": detalhe["tipo"],
                    "hash_fechamento": palpite.get("hash_fechamento"),
                    "hash_bloco": palpite.get("hash_bloco"),
                    "atualizado_em": palpite.get("atualizado_em"),
                }
            )

    # A quantidade de partidas encerradas independe de haver palpite para elas.
    for jid, jogo in jogos_rodada.items():
        resultado = resultados.get(jid) or resultados.get(str(jogo.get("event_id") or ""))
        if resultado:
            ids_finais.add(str(resultado.get("event_id") or jid))

    jogos_apurados = len(ids_finais) if publicada else 0
    jogos_carregados = len(jogos_rodada)
    concluida = publicada and jogos_carregados >= 10 and jogos_apurados == 10
    ranking = ordenar_ranking(acumulado.values(), jogos_apurados) if publicada else []
    rankings_por_liga = (
        ranking_ligas(ranking, ligas_map, membros_por_liga, jogos_apurados) if publicada else {}
    )
    pendentes = pendencias_rodada(rodada, jogos_rodada, resultados)

    return {
        "rodada": rodada,
        "status": (config or {}).get("status") or "sem_configuracao",
        "publicada": publicada,
        "sigilosa": not publicada,
        "estado_apuracao": estado_apuracao(publicada, jogos_apurados, 10, concluida),
        "concluida": concluida,
        "participantes": len(
            {p.get("participante_id") or p.get("membro") for p in palpites_rodada}
        ),
        "total_jogos": 10,
        "jogos_carregados": jogos_carregados,
        "jogos_apurados": jogos_apurados,
        "jogos_pendentes": max(0, 10 - jogos_apurados),
        "palpites_descartados_fora_do_prazo": descartados,
        "lideres_parciais": vencedores_ranking(ranking),
        "vencedores": vencedores_ranking(ranking) if concluida else [],
        "vencedores_por_liga": vencedores_ligas(rankings_por_liga) if concluida else {},
        "ranking": ranking,
        "rankings_por_liga": rankings_por_liga,
        "jogos": sorted(
            detalhes_jogos.values(),
            key=lambda x: str((x.get("resultado") or {}).get("data_iso") or ""),
        ),
        "pendencias": pendentes,
        "auditoria_resumo": resumo_auditoria(
            rodada, palpites, comprovantes, auditoria, 10
        ),
    }


def blocos_normalizados(blocos_db: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    por_intervalo: dict[tuple[int, int], dict[str, Any]] = {}
    for bloco in blocos_db:
        try:
            inicio = int(bloco.get("rodada_inicio"))
            fim = int(bloco.get("rodada_fim"))
        except Exception:  # noqa: BLE001
            continue
        por_intervalo[(inicio, fim)] = dict(bloco)
    saida: list[dict[str, Any]] = []
    for inicio, fim, nome in BLOCOS_PADRAO:
        bloco = por_intervalo.get((inicio, fim), {})
        saida.append(
            {
                **bloco,
                "rodada_inicio": inicio,
                "rodada_fim": fim,
                "nome": bloco.get("nome") or nome,
            }
        )
    return saida


def gerar_blocos_apuracao(
    rodadas_map: dict[int, dict[str, Any]],
    blocos_db: Iterable[dict[str, Any]],
    ligas_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for bloco in blocos_normalizados(blocos_db):
        inicio, fim = int(bloco["rodada_inicio"]), int(bloco["rodada_fim"])
        rodadas = [rodadas_map.get(r) for r in range(inicio, fim + 1)]
        rodadas_validas = [r for r in rodadas if r is not None]
        publicada = len(rodadas_validas) == 3 and all(r.get("publicada") for r in rodadas_validas)
        jogos_apurados = sum(int(r.get("jogos_apurados") or 0) for r in rodadas_validas) if publicada else 0
        jogos_carregados = sum(int(r.get("jogos_carregados") or 0) for r in rodadas_validas)
        concluido = publicada and jogos_carregados >= 30 and jogos_apurados == 30
        ranking = agregar_rankings(
            [r.get("ranking", []) for r in rodadas_validas], jogos_apurados
        ) if publicada else []
        rankings_por_liga = agregar_rankings_liga(
            [r.get("rankings_por_liga", {}) for r in rodadas_validas],
            ligas_map,
            jogos_apurados,
        ) if publicada else {}
        pendencias = [p for r in rodadas_validas for p in (r.get("pendencias") or [])]
        saida.append(
            {
                "bloco_id": bloco.get("id") or bloco.get("bloco_id"),
                "nome": bloco["nome"],
                "rodada_inicio": inicio,
                "rodada_fim": fim,
                "status": bloco.get("status") or "futura",
                "publicada": publicada,
                "sigilosa": not publicada,
                "estado_apuracao": estado_apuracao(publicada, jogos_apurados, 30, concluido),
                "concluido": concluido,
                "jogos_previstos": 30,
                "jogos_carregados": jogos_carregados,
                "jogos_apurados": jogos_apurados,
                "jogos_pendentes": max(0, 30 - jogos_apurados),
                "rodadas": [
                    {
                        "rodada": r,
                        "publicada": bool(rodadas_map.get(r, {}).get("publicada")),
                        "concluida": bool(rodadas_map.get(r, {}).get("concluida")),
                        "jogos_apurados": int(rodadas_map.get(r, {}).get("jogos_apurados") or 0),
                        "jogos_pendentes": int(rodadas_map.get(r, {}).get("jogos_pendentes") or 10),
                    }
                    for r in range(inicio, fim + 1)
                ],
                "lideres_parciais": vencedores_ranking(ranking),
                "vencedores": vencedores_ranking(ranking) if concluido else [],
                "vencedores_por_liga": vencedores_ligas(rankings_por_liga) if concluido else {},
                "ranking": ranking,
                "rankings_por_liga": rankings_por_liga,
                "pendencias": pendencias,
                "apurado_em": bloco.get("apurado_em"),
            }
        )
    return saida


def gerar_ranking_geral(
    rodadas: list[dict[str, Any]],
    blocos: list[dict[str, Any]],
    ligas_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    publicadas = [r for r in rodadas if r.get("publicada")]
    jogos_apurados = sum(int(r.get("jogos_apurados") or 0) for r in publicadas)
    ranking = agregar_rankings([r.get("ranking", []) for r in publicadas], jogos_apurados)
    rankings_por_liga = agregar_rankings_liga(
        [r.get("rankings_por_liga", {}) for r in publicadas],
        ligas_map,
        jogos_apurados,
    )

    vitorias_rodada: dict[str, int] = defaultdict(int)
    for rodada in publicadas:
        for nome in rodada.get("vencedores") or []:
            vitorias_rodada[str(nome)] += 1
    vitorias_bloco: dict[str, int] = defaultdict(int)
    for bloco in blocos:
        for nome in bloco.get("vencedores") or []:
            vitorias_bloco[str(nome)] += 1
    for row in ranking:
        row["rodadas_pontuadas"] = sum(
            1
            for rodada in publicadas
            if any(
                str(r.get("participante_id") or "") == str(row.get("participante_id") or "")
                for r in rodada.get("ranking") or []
            )
        )
        row["vitorias_rodada"] = vitorias_rodada.get(str(row.get("membro") or ""), 0)
        row["vitorias_bloco"] = vitorias_bloco.get(str(row.get("membro") or ""), 0)
    for ranking_liga in rankings_por_liga.values():
        for row in ranking_liga:
            row["rodadas_pontuadas"] = sum(
                1
                for rodada in publicadas
                if any(
                    str(r.get("participante_id") or "") == str(row.get("participante_id") or "")
                    for r in rodada.get("ranking") or []
                )
            )
    return ranking, rankings_por_liga


def validar_payload(payload: dict[str, Any]) -> None:
    erros: list[str] = []
    if not payload.get("validacao_resultados", {}).get("somente_finalizados"):
        erros.append("payload sem trava somente_finalizados")
    for rodada in payload.get("rodadas", []) or []:
        jogos = rodada.get("jogos", []) or []
        ids: set[str] = set()
        for item in jogos:
            resultado = item.get("resultado") or {}
            if not jogo_finalizado(resultado):
                erros.append(
                    f"rodada {rodada.get('rodada')}: resultado não finalizado {resultado.get('event_id')}"
                )
            rid = str(resultado.get("event_id") or item.get("event_id") or "")
            if rid:
                ids.add(rid)
        if rodada.get("publicada") and int(rodada.get("jogos_apurados") or 0) < len(ids):
            erros.append(
                f"rodada {rodada.get('rodada')}: jogos detalhados excedem jogos_apurados"
            )
        if rodada.get("concluida") and int(rodada.get("jogos_apurados") or 0) != 10:
            erros.append(f"rodada {rodada.get('rodada')}: concluída sem 10/10")
        if rodada.get("sigilosa") and (rodada.get("ranking") or rodada.get("jogos")):
            erros.append(f"rodada {rodada.get('rodada')}: sigilo violado")
        for row in rodada.get("ranking", []) or []:
            indice = float(row.get("indice_aproveitamento") or 0)
            if indice < 0 or indice > 100:
                erros.append(f"rodada {rodada.get('rodada')}: índice fora da faixa")
    for bloco in payload.get("blocos", []) or []:
        if bloco.get("concluido") and int(bloco.get("jogos_apurados") or 0) != 30:
            erros.append(f"bloco {bloco.get('nome')}: concluído sem 30/30")
        if bloco.get("sigilosa") and bloco.get("ranking"):
            erros.append(f"bloco {bloco.get('nome')}: ranking exposto durante sigilo")
    if erros:
        raise RuntimeError("Apuração bloqueada por inconsistência: " + "; ".join(erros))


def apurar(dados: dict[str, list[dict[str, Any]]], jogos: list[dict[str, Any]], resultados: dict[str, dict[str, Any]]) -> dict[str, Any]:
    configs = dados["configs"]
    palpites = dados["palpites"]
    comprovantes = dados["comprovantes"]
    auditoria = dados["auditoria"]
    ligas_map, membros_por_liga = gerar_indices_ligas(
        dados.get("ligas", []), dados.get("liga_participantes", [])
    )
    cfgs = por_rodada_config(configs)
    mapa_jogos = jogos_por_rodada(jogos)
    rodadas_existentes = {
        int(p.get("rodada") or 0) for p in palpites if int(p.get("rodada") or 0) >= 20
    } | {r for r in cfgs if r >= 20}
    # Garante os contextos da Rodada 20 e dos seis blocos, mesmo antes de haver
    # palpites ou configuração completa.
    rodadas_existentes.add(20)
    rodadas_existentes.update(range(21, 39))

    rodadas = [
        apurar_rodada(
            rodada,
            cfgs.get(rodada),
            palpites,
            comprovantes,
            auditoria,
            mapa_jogos.get(rodada, {}),
            resultados,
            ligas_map,
            membros_por_liga,
        )
        for rodada in sorted(rodadas_existentes)
    ]
    rodadas_map = {int(r["rodada"]): r for r in rodadas}
    blocos = gerar_blocos_apuracao(rodadas_map, dados.get("blocos", []), ligas_map)
    ranking_geral, rankings_por_liga = gerar_ranking_geral(rodadas, blocos, ligas_map)
    jogos_apurados_total = sum(int(r.get("jogos_apurados") or 0) for r in rodadas if r.get("publicada"))

    payload = {
        "schema_version": 4,
        "temporada": TEMPORADA,
        "atualizado_em": iso_agora(),
        "fonte": "Supabase br_palpites + resultados finais auditados dos JSONs locais",
        "politica_sigilo": "Rodadas e blocos não publicados não expõem palpites nem rankings no JSON público.",
        "regra_pontuacao": {
            "placar_exato": 5,
            "saldo_exato": 3,
            "resultado": 2,
            "erro": 0,
            "desempate": [
                "pontos",
                "placares exatos",
                "saldos",
                "resultados",
                "menor quantidade de erros",
                "nome",
            ],
            "indice_aproveitamento": "pontos / (5 × jogos apurados) × 100",
        },
        "validacao_resultados": {
            "versao": 4,
            "somente_finalizados": True,
            "criterios": [
                "placar presente",
                "estado final ou concluido=true",
                "kickoff não futuro",
                "resultado presente em resultados.json",
            ],
            "conclusao_rodada": "10 de 10 jogos finalizados",
            "conclusao_bloco": "30 de 30 jogos finalizados",
            "adiamentos": "mantêm a apuração parcial e impedem a conclusão até o resultado final",
        },
        "resumo": {
            "jogos_apurados_publicados": jogos_apurados_total,
            "rodadas_concluidas": sum(1 for r in rodadas if r.get("concluida")),
            "blocos_concluidos": sum(1 for b in blocos if b.get("concluido")),
            "ranking_parcial": any(r.get("estado_apuracao") == "parcial" for r in rodadas),
        },
        "ligas": list(ligas_map.values()),
        "rodadas": rodadas,
        "blocos": blocos,
        "ranking_geral": ranking_geral,
        "rankings_por_liga": rankings_por_liga,
    }
    validar_payload(payload)
    return payload


def payload_hash(payload: dict[str, Any]) -> str:
    canonico = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def sincronizar_supabase(payload: dict[str, Any]) -> Any:
    resumo_rodadas = [
        {
            "rodada": r["rodada"],
            "total_jogos": r["total_jogos"],
            "jogos_apurados": r["jogos_apurados"],
            "concluida": r["concluida"],
            "publicada": r["publicada"],
        }
        for r in payload.get("rodadas", [])
    ]
    resumo_blocos = [
        {
            "rodada_inicio": b["rodada_inicio"],
            "rodada_fim": b["rodada_fim"],
            "jogos_apurados": b["jogos_apurados"],
            "concluido": b["concluido"],
        }
        for b in payload.get("blocos", [])
    ]
    return rpc_service(
        "br_pipeline_sincronizar_apuracao_v1",
        {
            "p_temporada": TEMPORADA,
            "p_payload_hash": payload_hash(payload),
            "p_rodadas": resumo_rodadas,
            "p_blocos": resumo_blocos,
            "p_resumo": payload.get("resumo", {}),
        },
    )


def ranking_publico(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "temporada": TEMPORADA,
        "atualizado_em": payload["atualizado_em"],
        "fonte": payload["fonte"],
        "politica_sigilo": payload["politica_sigilo"],
        "regra_pontuacao": payload["regra_pontuacao"],
        "validacao_resultados": payload["validacao_resultados"],
        "resumo": payload["resumo"],
        "ligas": payload.get("ligas", []),
        "ranking_geral": payload["ranking_geral"],
        "rankings_por_liga": payload.get("rankings_por_liga", {}),
        "rankings_por_rodada": {
            str(r["rodada"]): {
                "rodada": r["rodada"],
                "publicada": r["publicada"],
                "concluida": r["concluida"],
                "estado_apuracao": r["estado_apuracao"],
                "jogos_apurados": r["jogos_apurados"],
                "jogos_pendentes": r["jogos_pendentes"],
                "ranking": r["ranking"],
                "rankings_por_liga": r["rankings_por_liga"],
            }
            for r in payload.get("rodadas", [])
        },
        "ranking_blocos": [
            {
                "bloco_id": b.get("bloco_id"),
                "nome": b["nome"],
                "rodada_inicio": b["rodada_inicio"],
                "rodada_fim": b["rodada_fim"],
                "publicada": b["publicada"],
                "concluido": b["concluido"],
                "estado_apuracao": b["estado_apuracao"],
                "jogos_apurados": b["jogos_apurados"],
                "jogos_pendentes": b["jogos_pendentes"],
                "ranking": b["ranking"],
                "rankings_por_liga": b["rankings_por_liga"],
                "lideres_parciais": b["lideres_parciais"],
                "vencedores": b["vencedores"],
            }
            for b in payload.get("blocos", [])
        ],
    }


def gravar(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporario = path.with_suffix(path.suffix + ".tmp")
    temporario.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporario.replace(path)


def executar_self_tests() -> None:
    futuro = {
        "event_id": "futuro",
        "estado": "pre",
        "concluido": False,
        "placar_mandante": 0,
        "placar_visitante": 0,
    }
    ao_vivo = {
        "event_id": "live",
        "estado": "in",
        "concluido": False,
        "placar_mandante": 0,
        "placar_visitante": 0,
    }
    final_zero = {
        "event_id": "final0",
        "estado": "post",
        "concluido": False,
        "placar_mandante": 0,
        "placar_visitante": 0,
    }
    final_flag = {
        "event_id": "final1",
        "estado": "",
        "concluido": True,
        "placar_mandante": 2,
        "placar_visitante": 1,
    }
    falso_final_futuro = {
        "event_id": "future-post",
        "estado": "post",
        "concluido": True,
        "placar_mandante": 0,
        "placar_visitante": 0,
        "data_iso": (agora_brt() + timedelta(days=2)).isoformat(),
    }
    assert not jogo_finalizado(futuro)
    assert not jogo_finalizado(ao_vivo)
    assert jogo_finalizado(final_zero)
    assert jogo_finalizado(final_flag)
    assert not jogo_finalizado(falso_final_futuro)
    mapa = resultado_mapa([futuro, ao_vivo, final_zero, final_flag, falso_final_futuro])
    assert set(mapa) == {"final0", "final1"}
    assert escolher_mais_confiavel(futuro, final_zero)["event_id"] == "final0"
    assert calcular({"placar_mandante": 0, "placar_visitante": 0}, mapa["final0"]) == {
        "pontos": 5,
        "tipo": "exato",
    }
    assert calcular({"placar_mandante": 3, "placar_visitante": 1}, {"placar_mandante": 2, "placar_visitante": 0}) == {
        "pontos": 3,
        "tipo": "saldo",
    }
    assert indice_aproveitamento(38, 10) == 76.0
    ranking = ordenar_ranking(
        [
            {**nova_linha("2", "B"), "pontos": 10, "cravadas": 1},
            {**nova_linha("1", "A"), "pontos": 10, "cravadas": 2},
        ],
        3,
    )
    assert ranking[0]["membro"] == "A" and ranking[0]["indice_aproveitamento"] == 66.7
    assert vencedores_ranking(ranking) == ["A"]
    bloco_incompleto = {
        "validacao_resultados": {"somente_finalizados": True},
        "rodadas": [],
        "blocos": [{"nome": "Teste", "concluido": False, "jogos_apurados": 29, "sigilosa": False, "ranking": []}],
    }
    validar_payload(bloco_incompleto)
    bloco_invalido = {
        "validacao_resultados": {"somente_finalizados": True},
        "rodadas": [],
        "blocos": [{"nome": "Teste", "concluido": True, "jogos_apurados": 29, "sigilosa": False, "ranking": []}],
    }
    try:
        validar_payload(bloco_invalido)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Bloco não poderia concluir com 29/30")


def main() -> int:
    if "--self-test" in sys.argv:
        executar_self_tests()
        print("Self-tests da apuração da Execução 4 concluídos com sucesso.")
        return 0

    executar_self_tests()
    try:
        dados = buscar_supabase()
        jogos = carregar_todos_jogos()
        resultados = resultado_mapa(carregar_resultados_finais())
        payload = apurar(dados, jogos, resultados)
        sincronizacao = sincronizar_supabase(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: {exc}")
        return 1

    gravar(ROOT / "dados-br" / "apuracao.json", payload)
    gravar(ROOT / "dados-br" / "ranking-apostas.json", ranking_publico(payload))

    print("Apuração parcial/final concluída com rankings por rodada, bloco, geral e liga.")
    print(f"Jogos apurados e publicados: {payload['resumo']['jogos_apurados_publicados']}")
    print(f"Rodadas concluídas: {payload['resumo']['rodadas_concluidas']}")
    print(f"Blocos concluídos: {payload['resumo']['blocos_concluidos']}")
    print(f"Sincronização Supabase: {sincronizacao}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

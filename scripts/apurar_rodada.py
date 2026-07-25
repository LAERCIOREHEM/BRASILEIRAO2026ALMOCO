#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apurar_rodada.py — Apuração auditável das apostas do Brasileirão 2026.

Execução 15:
  - mantém sigilo das rodadas não publicadas;
  - gera ranking geral;
  - gera rankings acumulados e por rodada também por liga;
  - a aposta continua única por participante/rodada.
  - só pontua partidas comprovadamente encerradas;
  - rejeita o placar inicial 0 x 0 de jogos futuros ou em andamento;
  - publica metadados de validação para defesa adicional no front-end.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FUSO_BRT = timezone(timedelta(hours=-3))
TEMPORADA = int(os.environ.get("BRASILEIRAO_TEMPORADA", "2026"))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ROOT = Path(__file__).resolve().parents[1]
ESTADOS_FINAIS = {"post", "final", "finished", "complete", "completed", "encerrado"}


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRT)


def iso_agora() -> str:
    return agora_brt().isoformat()


def carregar_json(nome: str, fallback: Any) -> Any:
    p = ROOT / nome
    if not p.exists():
        return fallback
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: não consegui ler {nome}: {exc}")
        return fallback


def parse_dt(valor: Any) -> datetime | None:
    if not valor:
        return None
    s = str(valor)
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=FUSO_BRT)
        return dt
    except ValueError:
        return None


def normalizar(s: Any) -> str:
    import re
    import unicodedata

    txt = unicodedata.normalize("NFD", str(s or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^a-zA-Z0-9]+", "-", txt.lower()).strip("-")
    return txt


def nome_time(valor: Any) -> str:
    if isinstance(valor, dict):
        return str(valor.get("nome") or valor.get("name") or "")
    return str(valor or "")


def jogo_id(j: dict[str, Any]) -> str:
    if j.get("event_id"):
        return str(j["event_id"])
    if j.get("id"):
        return str(j["id"])
    mand = normalizar(nome_time(j.get("mandante")))
    vis = normalizar(nome_time(j.get("visitante")))
    dt = str(j.get("data_iso") or "")[:16]
    return f"{j.get('rodada')}-{mand}-{vis}-{dt}"


def placar_disponivel(j: dict[str, Any]) -> bool:
    return j.get("placar_mandante") is not None and j.get("placar_visitante") is not None


def resultado_temporalmente_plausivel(j: dict[str, Any]) -> bool:
    """Rejeita finais impossíveis, como jogo futuro marcado como concluído pelo feed."""
    kickoff = parse_dt(j.get("data_iso"))
    agora = agora_brt()
    if kickoff and kickoff > agora + timedelta(minutes=5):
        return False
    return True


def jogo_finalizado(j: dict[str, Any]) -> bool:
    """Confirma que o placar representa resultado final, não o 0 x 0 inicial do feed."""
    if not placar_disponivel(j):
        return False
    estado = str(j.get("estado") or j.get("state") or "").strip().lower()
    concluido = j.get("concluido") is True or j.get("completed") is True
    return (estado in ESTADOS_FINAIS or concluido) and resultado_temporalmente_plausivel(j)


def jogo_para_evento(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": e.get("event_id"),
        "rodada": e.get("rodada"),
        "data_iso": e.get("data_iso"),
        "mandante": {"nome": e.get("mandante")},
        "visitante": {"nome": e.get("visitante")},
        "placar_mandante": e.get("placar_mandante"),
        "placar_visitante": e.get("placar_visitante"),
        "estado": e.get("estado"),
        "concluido": e.get("concluido"),
        "status": e.get("status"),
        "finalizado_em": e.get("finalizado_em"),
        "fonte_resultado": e.get("fonte_resultado"),
    }


def escolher_mais_confiavel(atual: dict[str, Any] | None, candidato: dict[str, Any]) -> dict[str, Any]:
    """Prefere sempre um resultado final sobre uma versão pré-jogo do mesmo evento."""
    if atual is None:
        return candidato
    if jogo_finalizado(candidato) and not jogo_finalizado(atual):
        return candidato
    if jogo_finalizado(atual) and not jogo_finalizado(candidato):
        return atual
    # Em empate de estado, mantém a versão mais rica e mais recente da cadeia.
    riqueza_atual = sum(atual.get(k) not in (None, "") for k in ("estado", "concluido", "finalizado_em", "fonte_resultado"))
    riqueza_candidato = sum(candidato.get(k) not in (None, "") for k in ("estado", "concluido", "finalizado_em", "fonte_resultado"))
    return candidato if riqueza_candidato >= riqueza_atual else atual


def carregar_todos_jogos() -> list[dict[str, Any]]:
    jogos = carregar_json("jogos.json", {}).get("jogos", []) or []
    resultados = carregar_json("resultados.json", {}).get("resultados", []) or []
    eventos = carregar_json("espn_eventos.json", {}).get("eventos", []) or []
    todos: dict[str, dict[str, Any]] = {}
    for j in jogos:
        if not isinstance(j, dict):
            continue
        jid = jogo_id(j)
        todos[jid] = escolher_mais_confiavel(todos.get(jid), j)
    # resultados.json é a fonte local autoritativa de partidas encerradas.
    for j in resultados:
        if not isinstance(j, dict):
            continue
        jid = jogo_id(j)
        todos[jid] = escolher_mais_confiavel(todos.get(jid), j)
    for e in eventos:
        if not isinstance(e, dict):
            continue
        j = jogo_para_evento(e)
        jid = jogo_id(j)
        todos[jid] = escolher_mais_confiavel(todos.get(jid), j)
    return list(todos.values())


def carregar_resultados_finais() -> list[dict[str, Any]]:
    """Carrega exclusivamente o arquivo transacional de resultados encerrados."""
    resultados = carregar_json("resultados.json", {}).get("resultados", []) or []
    finais: list[dict[str, Any]] = []
    for j in resultados:
        if not isinstance(j, dict):
            continue
        if jogo_finalizado(j):
            finais.append(j)
        else:
            print(f"Aviso: resultado rejeitado por estado/tempo inconsistente: {jogo_id(j)}")
    return finais


def resultado_mapa(jogos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapa: dict[str, dict[str, Any]] = {}
    for j in jogos:
        if not jogo_finalizado(j):
            continue
        rid = jogo_id(j)
        obj = {
            "event_id": rid,
            "rodada": int(j.get("rodada") or 0),
            "mandante": nome_time(j.get("mandante")),
            "visitante": nome_time(j.get("visitante")),
            "placar_mandante": int(j["placar_mandante"]),
            "placar_visitante": int(j["placar_visitante"]),
            "data_iso": j.get("data_iso"),
            "estado": str(j.get("estado") or "post").lower(),
            "concluido": bool(j.get("concluido") is True or str(j.get("estado") or "").lower() in ESTADOS_FINAIS),
            "finalizado_em": j.get("finalizado_em"),
            "fonte_resultado": j.get("fonte_resultado") or "ESPN/resultados.json",
        }
        mapa[rid] = obj
        if j.get("event_id"):
            mapa[str(j["event_id"])] = obj
    return mapa


def validar_payload(payload: dict[str, Any]) -> None:
    """Impede publicação de pontuação derivada de partida não encerrada."""
    erros: list[str] = []
    for rodada in payload.get("rodadas", []) or []:
        jogos = rodada.get("jogos", []) or []
        ids = set()
        for item in jogos:
            resultado = item.get("resultado") or {}
            if not jogo_finalizado(resultado):
                erros.append(f"rodada {rodada.get('rodada')}: resultado não finalizado {resultado.get('event_id')}")
            rid = str(resultado.get("event_id") or item.get("event_id") or "")
            if rid:
                ids.add(rid)
        if int(rodada.get("jogos_apurados") or 0) != len(ids):
            erros.append(
                f"rodada {rodada.get('rodada')}: jogos_apurados={rodada.get('jogos_apurados')} difere de {len(ids)}"
            )
        if not ids and (rodada.get("ranking") or []):
            erros.append(f"rodada {rodada.get('rodada')}: ranking publicado sem jogo encerrado")
    if erros:
        raise RuntimeError("Apuração bloqueada por inconsistência de resultados: " + "; ".join(erros))


def executar_self_tests() -> None:
    futuro = {"event_id": "futuro", "estado": "pre", "concluido": False, "placar_mandante": 0, "placar_visitante": 0}
    ao_vivo = {"event_id": "live", "estado": "in", "concluido": False, "placar_mandante": 0, "placar_visitante": 0}
    final_zero = {"event_id": "final0", "estado": "post", "concluido": False, "placar_mandante": 0, "placar_visitante": 0}
    final_flag = {"event_id": "final1", "estado": "", "concluido": True, "placar_mandante": 2, "placar_visitante": 1}
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
    escolhido = escolher_mais_confiavel(futuro, final_zero)
    assert escolhido["event_id"] == "final0" and jogo_finalizado(escolhido)
    palpite = {"placar_mandante": 0, "placar_visitante": 0}
    assert calcular(palpite, mapa["final0"]) == {"pontos": 5, "tipo": "exato"}
    invalido = {
        "rodadas": [{"rodada": 20, "jogos_apurados": 1, "ranking": [{"membro": "Teste"}], "jogos": [{"event_id": "futuro", "resultado": futuro}]}]
    }
    try:
        validar_payload(invalido)
    except RuntimeError:
        pass
    else:
        raise AssertionError("validar_payload deveria bloquear pontuação de jogo não encerrado")


def sinal(n: int) -> int:
    return 1 if n > 0 else -1 if n < 0 else 0


def calcular(p: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    pm, pv = int(p["placar_mandante"]), int(p["placar_visitante"])
    rm, rv = int(r["placar_mandante"]), int(r["placar_visitante"])
    if pm == rm and pv == rv:
        return {"pontos": 5, "tipo": "exato"}
    sp, sr = sinal(pm - pv), sinal(rm - rv)
    if sp != sr:
        return {"pontos": 0, "tipo": "erro"}
    if sr == 0:
        return {"pontos": 2, "tipo": "resultado"}
    if (pm - pv) == (rm - rv):
        return {"pontos": 3, "tipo": "saldo"}
    return {"pontos": 2, "tipo": "resultado"}


def palpite_valido_no_prazo(p: dict[str, Any]) -> bool:
    atualizado = parse_dt(p.get("atualizado_em") or p.get("criado_em"))
    fecha = parse_dt(p.get("fecha_em"))
    if not atualizado or not fecha:
        return True
    return atualizado <= fecha


def rest_get(tabela: str, params: dict[str, str]) -> list[dict[str, Any]]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY precisam estar cadastrados nos Secrets do GitHub.")
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{tabela}?{query}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Resposta inesperada do Supabase em {tabela}: {data!r}")
    return data


def buscar_supabase() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    palpites = rest_get("br_palpites", {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada.asc,membro.asc,kickoff.asc"})
    configs = rest_get("br_config_rodadas", {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada.asc"})
    comprovantes = rest_get("br_comprovantes", {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada.asc,atualizado_em.desc"})
    auditoria = rest_get("br_palpites_auditoria", {"temporada": f"eq.{TEMPORADA}", "select": "*", "order": "rodada.asc,criado_em.desc"})
    participantes = rest_get("br_participantes", {"select": "id,nome,login,ativo,admin", "order": "nome.asc"})
    try:
        ligas = rest_get("br_ligas", {"select": "id,nome,slug,descricao,ativa", "order": "nome.asc"})
        liga_participantes = rest_get("br_liga_participantes", {"select": "liga_id,participante_id,papel,ativo", "order": "liga_id.asc"})
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: tabelas de liga indisponíveis; ranking por liga não será gerado: {exc}")
        ligas, liga_participantes = [], []
    return palpites, configs, comprovantes, auditoria, participantes, ligas, liga_participantes


def config_publica(cfg: dict[str, Any] | None) -> bool:
    if not cfg:
        return False
    status = str(cfg.get("status") or "").lower()
    if status in {"apurada", "publicada"}:
        return True
    pub = parse_dt(cfg.get("publica_em"))
    return bool(pub and agora_brt() >= pub)


def por_rodada_config(configs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for c in configs:
        try:
            out[int(c.get("rodada"))] = c
        except Exception:  # noqa: BLE001
            continue
    return out


def total_jogos_rodada(jogos: list[dict[str, Any]], rodada: int) -> int:
    ids = {jogo_id(j) for j in jogos if int(j.get("rodada") or 0) == int(rodada)}
    return len(ids)


def resumo_auditoria(rodada: int, palpites: list[dict[str, Any]], comprovantes: list[dict[str, Any]], auditoria: list[dict[str, Any]], total_jogos: int) -> list[dict[str, Any]]:
    por_part: dict[str, dict[str, Any]] = {}
    for p in palpites:
        if int(p.get("rodada") or 0) != rodada:
            continue
        key = str(p.get("participante_id") or p.get("membro") or "")
        if not key:
            continue
        item = por_part.setdefault(key, {"participante_id": p.get("participante_id"), "membro": p.get("membro") or "—", "total_jogos": total_jogos, "total_palpites": 0, "primeiro_envio": None, "ultimo_envio": None, "hash_fechamento": p.get("hash_fechamento"), "alteracoes": 0})
        item["total_palpites"] += 1
        for campo in ("criado_em", "atualizado_em"):
            dt = parse_dt(p.get(campo))
            if not dt:
                continue
            if item["primeiro_envio"] is None or dt < parse_dt(item["primeiro_envio"]):
                item["primeiro_envio"] = dt.isoformat()
            if item["ultimo_envio"] is None or dt > parse_dt(item["ultimo_envio"]):
                item["ultimo_envio"] = dt.isoformat()
        if p.get("hash_fechamento"):
            item["hash_fechamento"] = p.get("hash_fechamento")
    for c in comprovantes:
        if int(c.get("rodada") or 0) != rodada:
            continue
        key = str(c.get("participante_id") or "")
        item = por_part.setdefault(key, {"participante_id": c.get("participante_id"), "membro": key, "total_jogos": total_jogos, "total_palpites": int(c.get("total_palpites") or 0), "primeiro_envio": c.get("criado_em"), "ultimo_envio": c.get("atualizado_em"), "hash_fechamento": c.get("hash_fechamento"), "alteracoes": 0})
        item["hash_fechamento"] = c.get("hash_fechamento") or item.get("hash_fechamento")
    for a in auditoria:
        if int(a.get("rodada") or 0) != rodada:
            continue
        key = str(a.get("participante_id") or a.get("membro") or "")
        item = por_part.setdefault(key, {"participante_id": a.get("participante_id"), "membro": a.get("membro") or key, "total_jogos": total_jogos, "total_palpites": 0, "alteracoes": 0})
        item["alteracoes"] = int(item.get("alteracoes") or 0) + 1
    for item in por_part.values():
        total = int(item.get("total_jogos") or 0)
        preenchidos = int(item.get("total_palpites") or 0)
        item["percentual"] = round((preenchidos / total) * 100, 1) if total else 0
    return sorted(por_part.values(), key=lambda x: str(x.get("membro") or ""))


def ordenar_ranking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = sorted(rows, key=lambda x: (-int(x.get("pontos") or 0), -int(x.get("cravadas") or 0), -int(x.get("saldos") or 0), -int(x.get("resultados") or 0), int(x.get("erros") or 0), str(x.get("membro") or "")))
    for pos, row in enumerate(out, 1):
        row["pos"] = pos
    return out


def gerar_indices_ligas(ligas: list[dict[str, Any]], liga_participantes: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    ligas_map: dict[str, dict[str, Any]] = {}
    membros_por_liga: dict[str, set[str]] = defaultdict(set)
    for l in ligas:
        if not l.get("ativa", True):
            continue
        lid = str(l.get("id") or "")
        if not lid:
            continue
        slug = str(l.get("slug") or normalizar(l.get("nome")) or lid)
        ligas_map[lid] = {"id": lid, "nome": l.get("nome"), "slug": slug, "descricao": l.get("descricao")}
    for lp in liga_participantes:
        if not lp.get("ativo", True):
            continue
        lid = str(lp.get("liga_id") or "")
        pid = str(lp.get("participante_id") or "")
        if lid in ligas_map and pid:
            membros_por_liga[lid].add(pid)
    return ligas_map, membros_por_liga


def ranking_ligas(ranking: list[dict[str, Any]], ligas_map: dict[str, dict[str, Any]], membros_por_liga: dict[str, set[str]]) -> dict[str, list[dict[str, Any]]]:
    saida: dict[str, list[dict[str, Any]]] = {}
    for lid, liga in ligas_map.items():
        membros = membros_por_liga.get(lid, set())
        rows = [dict(r) for r in ranking if str(r.get("participante_id") or "") in membros]
        rows = ordenar_ranking(rows)
        # Publica tanto por id quanto por slug para o front encontrar com segurança.
        saida[lid] = rows
        if liga.get("slug"):
            saida[str(liga["slug"])] = rows
    return saida


def vencedores_ligas(rankings_por_liga: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for chave, ranking in rankings_por_liga.items():
        if not ranking:
            out[chave] = []
            continue
        top = ranking[0]
        out[chave] = [r["membro"] for r in ranking if r.get("pontos") == top.get("pontos") and r.get("cravadas") == top.get("cravadas") and r.get("saldos") == top.get("saldos")]
    return out


def apurar(palpites: list[dict[str, Any]], configs: list[dict[str, Any]], comprovantes: list[dict[str, Any]], auditoria: list[dict[str, Any]], jogos: list[dict[str, Any]], resultados: dict[str, dict[str, Any]], ligas: list[dict[str, Any]], liga_participantes: list[dict[str, Any]]) -> dict[str, Any]:
    cfgs = por_rodada_config(configs)
    rodadas = sorted({int(p.get("rodada") or 0) for p in palpites if int(p.get("rodada") or 0) > 0} | set(cfgs.keys()))
    saida_rodadas: list[dict[str, Any]] = []
    geral: dict[str, dict[str, Any]] = {}
    ligas_map, membros_por_liga = gerar_indices_ligas(ligas, liga_participantes)

    for rodada in rodadas:
        if rodada < 20:
            continue
        cfg = cfgs.get(rodada)
        publica = config_publica(cfg)
        total_jogos = total_jogos_rodada(jogos, rodada)
        palp_rodada = [p for p in palpites if int(p.get("rodada") or 0) == rodada]
        base_rodada = {"rodada": rodada, "status": (cfg or {}).get("status") or "sem_configuracao", "publicada": publica, "sigilosa": not publica, "participantes": len({p.get("participante_id") or p.get("membro") for p in palp_rodada}), "total_jogos": total_jogos, "jogos_apurados": 0, "palpites_descartados_fora_do_prazo": 0, "vencedores": [], "vencedores_por_liga": {}, "ranking": [], "rankings_por_liga": {}, "jogos": [], "auditoria_resumo": resumo_auditoria(rodada, palpites, comprovantes, auditoria, total_jogos)}
        if not publica:
            saida_rodadas.append(base_rodada)
            continue

        acumulado: dict[str, dict[str, Any]] = {}
        detalhes_jogos: dict[str, dict[str, Any]] = {}
        jogos_apurados: set[str] = set()
        descartados = 0

        for p in palp_rodada:
            membro = str(p.get("membro") or "").strip()
            participante_id = str(p.get("participante_id") or membro)
            if not membro:
                continue
            eid = str(p.get("event_id") or p.get("jogo_chave") or "")
            r = resultados.get(eid)
            if not r:
                continue
            if not palpite_valido_no_prazo(p):
                descartados += 1
                continue
            det = calcular(p, r)
            jogos_apurados.add(eid)

            row = acumulado.setdefault(participante_id, {"participante_id": participante_id, "membro": membro, "pontos": 0, "cravadas": 0, "saldos": 0, "resultados": 0, "erros": 0, "palpites_validos": 0})
            row["pontos"] += det["pontos"]
            row["palpites_validos"] += 1
            if det["tipo"] == "exato": row["cravadas"] += 1
            elif det["tipo"] == "saldo": row["saldos"] += 1
            elif det["tipo"] == "resultado": row["resultados"] += 1
            else: row["erros"] += 1

            g = geral.setdefault(participante_id, {"participante_id": participante_id, "membro": membro, "pontos": 0, "cravadas": 0, "saldos": 0, "resultados": 0, "erros": 0, "palpites_validos": 0, "rodadas_pontuadas": 0, "vitorias_rodada": 0})
            g["pontos"] += det["pontos"]
            g["palpites_validos"] += 1
            if det["tipo"] == "exato": g["cravadas"] += 1
            elif det["tipo"] == "saldo": g["saldos"] += 1
            elif det["tipo"] == "resultado": g["resultados"] += 1
            else: g["erros"] += 1

            jogo = detalhes_jogos.setdefault(eid, {"event_id": eid, "resultado": r, "palpites": []})
            jogo["palpites"].append({"participante_id": participante_id, "membro": membro, "palpite": f"{p.get('placar_mandante')}×{p.get('placar_visitante')}", "placar_mandante": int(p.get("placar_mandante")), "placar_visitante": int(p.get("placar_visitante")), "pontos": det["pontos"], "tipo": det["tipo"], "hash_fechamento": p.get("hash_fechamento"), "atualizado_em": p.get("atualizado_em")})

        ranking = ordenar_ranking(list(acumulado.values()))
        for row in ranking:
            if row["palpites_validos"] and row["participante_id"] in geral:
                geral[row["participante_id"]]["rodadas_pontuadas"] += 1

        vencedores: list[str] = []
        if ranking:
            top = ranking[0]
            vencedores = [r["membro"] for r in ranking if r["pontos"] == top["pontos"] and r["cravadas"] == top["cravadas"] and r["saldos"] == top["saldos"]]
            for nome in vencedores:
                for g in geral.values():
                    if g["membro"] == nome:
                        g["vitorias_rodada"] += 1

        rankings_por_liga = ranking_ligas(ranking, ligas_map, membros_por_liga)
        base_rodada.update({"jogos_apurados": len(jogos_apurados), "palpites_descartados_fora_do_prazo": descartados, "vencedores": vencedores, "vencedores_por_liga": vencedores_ligas(rankings_por_liga), "ranking": ranking, "rankings_por_liga": rankings_por_liga, "jogos": sorted(detalhes_jogos.values(), key=lambda x: str((x.get("resultado") or {}).get("data_iso") or ""))})
        saida_rodadas.append(base_rodada)

    ranking_geral = ordenar_ranking(list(geral.values()))
    rankings_por_liga = ranking_ligas(ranking_geral, ligas_map, membros_por_liga)

    payload = {
        "temporada": TEMPORADA,
        "atualizado_em": iso_agora(),
        "fonte": "Supabase br_palpites + resultados finais auditados dos JSONs locais",
        "politica_sigilo": "Rodadas não publicadas não expõem palpites nem ranking no JSON público.",
        "validacao_resultados": {
            "versao": 2,
            "somente_finalizados": True,
            "criterios": ["estado final (post/final/finished/complete/completed/encerrado)", "ou concluido=true"],
        },
        "ligas": list(ligas_map.values()),
        "rodadas": saida_rodadas,
        "ranking_geral": ranking_geral,
        "rankings_por_liga": rankings_por_liga,
    }
    validar_payload(payload)
    return payload


def gravar(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if "--self-test" in sys.argv:
        executar_self_tests()
        print("Self-tests da apuração concluídos com sucesso.")
        return 0

    executar_self_tests()
    try:
        palpites, configs, comprovantes, auditoria, participantes, ligas, liga_participantes = buscar_supabase()
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: {exc}")
        return 1

    jogos = carregar_todos_jogos()
    resultados = resultado_mapa(carregar_resultados_finais())
    payload = apurar(palpites, configs, comprovantes, auditoria, jogos, resultados, ligas, liga_participantes)
    gravar(ROOT / "dados-br" / "apuracao.json", payload)
    gravar(ROOT / "dados-br" / "ranking-apostas.json", {
        "temporada": TEMPORADA,
        "atualizado_em": payload["atualizado_em"],
        "fonte": payload["fonte"],
        "politica_sigilo": payload["politica_sigilo"],
        "validacao_resultados": payload["validacao_resultados"],
        "ligas": payload.get("ligas", []),
        "ranking_geral": payload["ranking_geral"],
        "rankings_por_liga": payload.get("rankings_por_liga", {}),
    })

    print("Apuração concluída com política de sigilo e rankings por liga.")
    print(f"Rodadas no arquivo: {len(payload['rodadas'])}")
    print(f"Participantes no ranking geral publicado: {len(payload['ranking_geral'])}")
    print(f"Ligas publicadas: {len(payload.get('ligas', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

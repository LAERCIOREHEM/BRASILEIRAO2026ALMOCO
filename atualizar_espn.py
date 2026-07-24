#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atualizar_espn.py — Fonte ESPN para o módulo Brasileirão 2026.

Execução 1 da migração:
  - tabela.json        -> classificação via ESPN standings, preservando o
                         formato e os nomes canônicos que alimentam o Ranking.
  - jogos.json         -> próximos jogos via ESPN scoreboard.
  - resultados.json    -> resultados já encerrados via ESPN scoreboard.
  - espn_eventos.json  -> índice de eventos ESPN usado pelo AO VIVO/onde assistir.

Regras de segurança:
  1. O Ranking atual usa nomes exatos nos palpites. Por isso, todos os times
     gravados continuam nos 20 nomes canônicos do site.
  2. Se a tabela vier incompleta, duplicada ou com time não mapeado, o script
     falha antes de gravar tabela.json. O arquivo anterior fica preservado.
  3. Tabela e resultados só são gravados quando standings e scoreboard
     descrevem exatamente o mesmo estado esportivo. Em indisponibilidade ou
     dessincronia transitória, a coleta repete e preserva o último snapshot
     íntegro sem publicar arquivos parciais.
  4. Nenhum arquivo de copa2026/ é lido ou alterado.

Só usa biblioteca padrão, para rodar direto no GitHub Actions.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import copy
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fontes_brasileirao import (
    CBF_TABELA_DETALHADA_URL,
    buscar_tabela_detalhada_cbf,
    fetch_api_football_fixtures,
    localizar_fixture_api_football,
    localizar_partida_cbf,
)

FUSO_BRASILIA = timezone(timedelta(hours=-3))
TEMPORADA = int(os.environ.get("BRASILEIRAO_TEMPORADA", "2026"))

URLS_STANDINGS = [
    f"https://site.api.espn.com/apis/v2/sports/soccer/bra.1/standings?season={TEMPORADA}",
    "https://site.api.espn.com/apis/v2/sports/soccer/bra.1/standings",
    f"https://site.web.api.espn.com/apis/v2/sports/soccer/bra.1/standings?season={TEMPORADA}",
]
URL_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard"
URL_RESUMO_EVENTO = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary"
ARQ_AJUSTES_CALENDARIO = Path("dados-br/ajustes-calendario.json")
ARQ_RESULTADOS_MANUAIS = Path("dados-br/resultados-manuais.json")
MAX_TENTATIVAS_SINCRONIA = max(1, int(os.environ.get("ESPN_MAX_TENTATIVAS_SINCRONIA", "3")))
ESPERA_SINCRONIA_SEGUNDOS = max(0, int(os.environ.get("ESPN_ESPERA_SINCRONIA_SEGUNDOS", "45")))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

CANONICOS = [
    "Athletico-PR", "Atlético-MG", "Bahia", "Botafogo", "Bragantino",
    "Chapecoense", "Corinthians", "Coritiba", "Cruzeiro", "Flamengo",
    "Fluminense", "Grêmio", "Internacional", "Mirassol", "Palmeiras",
    "Remo", "Santos", "São Paulo", "Vasco da Gama", "Vitória",
]

ESCUDOS_TIMES = {
    "Athletico-PR":  {"escudo": "https://s.sde.globo.com/media/organizations/2026/01/07/Athletico-PR.svg", "sigla": "CAP"},
    "Atlético-MG":   {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/10/atletico-mg.svg", "sigla": "CAM"},
    "Bahia":         {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/11/bahia.svg", "sigla": "BAH"},
    "Botafogo":      {"escudo": "https://s.sde.globo.com/media/organizations/2019/02/04/botafogo-svg.svg", "sigla": "BOT"},
    "Bragantino":    {"escudo": "https://s.sde.globo.com/media/organizations/2021/06/28/bragantino.svg", "sigla": "RBB"},
    "Chapecoense":   {"escudo": "https://s.sde.globo.com/media/organizations/2021/06/21/CHAPECOENSE-2018.svg", "sigla": "CHA"},
    "Corinthians":   {"escudo": "https://s.sde.globo.com/media/organizations/2024/10/09/Corinthians_2024_Q4ahot4.svg", "sigla": "COR"},
    "Coritiba":      {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/11/coritiba.svg", "sigla": "CFC"},
    "Cruzeiro":      {"escudo": "https://s.sde.globo.com/media/organizations/2021/02/13/cruzeiro_2021.svg", "sigla": "CRU"},
    "Flamengo":      {"escudo": "https://s.sde.globo.com/media/organizations/2018/04/10/Flamengo-2018.svg", "sigla": "FLA"},
    "Fluminense":    {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/11/fluminense.svg", "sigla": "FLU"},
    "Grêmio":        {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/12/gremio.svg", "sigla": "GRE"},
    "Internacional": {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/11/internacional.svg", "sigla": "INT"},
    "Mirassol":      {"escudo": "https://s.sde.globo.com/media/organizations/2024/08/20/mirassol-novo-svg-71690.svg", "sigla": "MIR"},
    "Palmeiras":     {"escudo": "https://s.sde.globo.com/media/organizations/2019/07/06/Palmeiras.svg", "sigla": "PAL"},
    "Remo":          {"escudo": "https://s.sde.globo.com/media/organizations/2021/02/25/Remo-PA.svg", "sigla": "REM"},
    "Santos":        {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/12/santos.svg", "sigla": "SAN"},
    "São Paulo":     {"escudo": "https://s.sde.globo.com/media/organizations/2018/03/11/sao-paulo.svg", "sigla": "SAO"},
    "Vasco da Gama": {"escudo": "https://s.sde.globo.com/media/organizations/2021/09/04/vasco_SVG.svg", "sigla": "VAS"},
    "Vitória":       {"escudo": "https://s.sde.globo.com/media/organizations/2025/12/18/Vitoria_2025.svg", "sigla": "VIT"},
}

ALIASES = {
    "athletico-pr": "Athletico-PR", "athletico paranaense": "Athletico-PR", "athletico": "Athletico-PR",
    "atletico paranaense": "Athletico-PR", "atletico-pr": "Athletico-PR", "cap": "Athletico-PR",
    "atletico-mg": "Atlético-MG", "atletico mineiro": "Atlético-MG", "atletico mg": "Atlético-MG",
    "clube atletico mineiro": "Atlético-MG", "cam": "Atlético-MG",
    "bahia": "Bahia", "ec bahia": "Bahia", "esporte clube bahia": "Bahia", "bah": "Bahia",
    "botafogo": "Botafogo", "botafogo rj": "Botafogo", "botafogo de futebol e regatas": "Botafogo", "bot": "Botafogo",
    "bragantino": "Bragantino", "red bull bragantino": "Bragantino", "rb bragantino": "Bragantino", "rbb": "Bragantino",
    "chapecoense": "Chapecoense", "chapecoense-sc": "Chapecoense", "associacao chapecoense de futebol": "Chapecoense", "cha": "Chapecoense",
    "corinthians": "Corinthians", "sc corinthians paulista": "Corinthians", "corinthians paulista": "Corinthians", "cor": "Corinthians",
    "coritiba": "Coritiba", "coritiba fc": "Coritiba", "coritiba foot ball club": "Coritiba", "cfc": "Coritiba",
    "cruzeiro": "Cruzeiro", "cruzeiro ec": "Cruzeiro", "cruzeiro esporte clube": "Cruzeiro", "cru": "Cruzeiro",
    "flamengo": "Flamengo", "cr flamengo": "Flamengo", "clube de regatas do flamengo": "Flamengo", "fla": "Flamengo",
    "fluminense": "Fluminense", "fluminense fc": "Fluminense", "fluminense football club": "Fluminense", "flu": "Fluminense",
    "gremio": "Grêmio", "gremio fbpa": "Grêmio", "gremio foot-ball porto alegrense": "Grêmio", "gre": "Grêmio",
    "internacional": "Internacional", "sc internacional": "Internacional", "sport club internacional": "Internacional", "inter de porto alegre": "Internacional", "int": "Internacional",
    "mirassol": "Mirassol", "mirassol fc": "Mirassol", "mirassol futebol clube": "Mirassol", "mir": "Mirassol",
    "palmeiras": "Palmeiras", "se palmeiras": "Palmeiras", "sociedade esportiva palmeiras": "Palmeiras", "pal": "Palmeiras",
    "remo": "Remo", "clube do remo": "Remo", "rem": "Remo",
    "santos": "Santos", "santos fc": "Santos", "santos futebol clube": "Santos", "san": "Santos",
    "sao paulo": "São Paulo", "sao paulo fc": "São Paulo", "sao paulo futebol clube": "São Paulo", "sao": "São Paulo",
    "vasco": "Vasco da Gama", "vasco da gama": "Vasco da Gama", "cr vasco da gama": "Vasco da Gama", "club de regatas vasco da gama": "Vasco da Gama", "vas": "Vasco da Gama",
    "vitoria": "Vitória", "ec vitoria": "Vitória", "esporte clube vitoria": "Vitória", "vitoria ba": "Vitória", "vit": "Vitória",
}

TOKENS_DECISIVOS = [
    ("paranaense", "Athletico-PR"), ("athletico", "Athletico-PR"), ("mineiro", "Atlético-MG"),
    ("bragantino", "Bragantino"), ("chapecoense", "Chapecoense"), ("corinthians", "Corinthians"),
    ("coritiba", "Coritiba"), ("cruzeiro", "Cruzeiro"), ("flamengo", "Flamengo"),
    ("fluminense", "Fluminense"), ("gremio", "Grêmio"), ("internacional", "Internacional"),
    ("mirassol", "Mirassol"), ("palmeiras", "Palmeiras"), ("remo", "Remo"),
    ("santos", "Santos"), ("vasco", "Vasco da Gama"), ("botafogo", "Botafogo"),
    ("bahia", "Bahia"), ("vitoria", "Vitória"),
]


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def iso_agora_brt() -> str:
    return agora_brt().isoformat()


def normalizar(nome: Any) -> str:
    if nome is None:
        return ""
    s = unicodedata.normalize("NFD", str(nome))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9\- ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def para_canonico(*candidatos: Any) -> str | None:
    for cand in candidatos:
        n = normalizar(cand)
        if not n:
            continue
        if n in ALIASES:
            return ALIASES[n]
        for c in CANONICOS:
            if n == normalizar(c):
                return c
    texto = " ".join(normalizar(c) for c in candidatos if c)
    for token, canonico in TOKENS_DECISIVOS:
        if re.search(r"\b" + re.escape(token) + r"\b", texto):
            return canonico
    return None


def info_time(nome: str) -> dict[str, str]:
    canonico = para_canonico(nome) or nome
    base = ESCUDOS_TIMES.get(canonico, {})
    return {
        "nome": canonico,
        "escudo": base.get("escudo", ""),
        "sigla": base.get("sigla", normalizar(canonico)[:3].upper()),
    }


def fetch_json(url: str, timeout: int = 25, tentativas: int = 3) -> dict[str, Any]:
    ultimo: Exception | None = None
    for i in range(1, tentativas + 1):
        try:
            sep = "&" if "?" in url else "?"
            req = urllib.request.Request(
                f"{url}{sep}_={int(time.time())}",
                headers=HEADERS,
            )
            with urllib.request.urlopen(req, timeout=timeout + 10 * (i - 1)) as r:
                charset = r.headers.get_content_charset() or "utf-8"
                bruto = r.read().decode(charset, errors="replace")
                return json.loads(bruto)
        except Exception as e:  # noqa: BLE001
            ultimo = e
            print(f"  tentativa {i}/{tentativas} falhou: {type(e).__name__}: {e}")
            if i < tentativas:
                time.sleep(2 * i)
    raise RuntimeError(f"falha ao buscar JSON: {url} :: {ultimo}")


def gravar_json_atomico(caminho: str | Path, payload: dict[str, Any]) -> None:
    path = Path(caminho)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# STANDINGS -> tabela.json
# ---------------------------------------------------------------------------
def coletar_entries(no: Any, achados: list[dict[str, Any]]) -> None:
    if isinstance(no, dict):
        if "team" in no and isinstance(no.get("stats"), list):
            achados.append(no)
        for v in no.values():
            coletar_entries(v, achados)
    elif isinstance(no, list):
        for v in no:
            coletar_entries(v, achados)


def stat_valor(stats: list[dict[str, Any]], *nomes: str) -> int | None:
    alvos = {normalizar(n) for n in nomes}
    for s in stats:
        chaves = {
            normalizar(s.get("name")),
            normalizar(s.get("type")),
            normalizar(s.get("abbreviation")),
            normalizar(s.get("shortDisplayName")),
            normalizar(s.get("displayName")),
        }
        if chaves & alvos:
            v = s.get("value", s.get("displayValue"))
            try:
                return int(round(float(str(v).replace("%", ""))))
            except (TypeError, ValueError):
                continue
    return None


def gerar_tabela() -> dict[str, Any]:
    print("== TABELA (ESPN standings) ==")
    data: dict[str, Any] | None = None
    erro: Exception | None = None
    for url in URLS_STANDINGS:
        print(f"Fonte: {url}")
        try:
            data = fetch_json(url)
            break
        except Exception as e:  # noqa: BLE001
            erro = e
            continue
    if data is None:
        raise RuntimeError(f"standings indisponível em todas as URLs: {erro}")

    entries: list[dict[str, Any]] = []
    coletar_entries(data, entries)
    vistos: set[str] = set()
    unicos: list[dict[str, Any]] = []
    for e in entries:
        team = e.get("team") or {}
        tid = str(team.get("id") or team.get("uid") or team.get("displayName") or id(e))
        if tid not in vistos:
            vistos.add(tid)
            unicos.append(e)
    print(f"Entradas de time encontradas: {len(unicos)}")

    linhas: list[dict[str, Any]] = []
    nao_mapeados: list[str] = []
    de_para: list[str] = []
    for e in unicos:
        team = e.get("team") or {}
        stats = e.get("stats") or []
        canonico = para_canonico(
            team.get("displayName"), team.get("shortDisplayName"), team.get("name"),
            team.get("location"), team.get("abbreviation"), team.get("slug"),
        )
        if not canonico:
            nao_mapeados.append(team.get("displayName") or team.get("name") or "?")
            continue
        de_para.append(f"  ESPN '{team.get('displayName') or team.get('name')}' -> '{canonico}'")

        j = stat_valor(stats, "gamesPlayed", "GP", "J")
        v = stat_valor(stats, "wins", "W", "V")
        emp = stat_valor(stats, "ties", "draws", "D", "E")
        der = stat_valor(stats, "losses", "L")
        gp = stat_valor(stats, "pointsFor", "goalsFor", "GF", "F")
        gc = stat_valor(stats, "pointsAgainst", "goalsAgainst", "GA", "A")
        sg = stat_valor(stats, "pointDifferential", "goalDifferential", "GD", "SG")
        p = stat_valor(stats, "points", "PTS", "P")
        rank = stat_valor(stats, "rank", "RANK")

        if p is None and None not in (v, emp):
            p = 3 * int(v) + int(emp)
        if sg is None and None not in (gp, gc):
            sg = int(gp) - int(gc)
        if j is None and None not in (v, emp, der):
            j = int(v) + int(emp) + int(der)

        obrigatorios = {"pontos": p, "jogos": j, "vitorias": v, "empates": emp, "derrotas": der, "gp": gp, "gc": gc}
        faltando = [k for k, val in obrigatorios.items() if val is None]
        if faltando:
            raise RuntimeError(
                f"Time '{canonico}': stats ausentes na ESPN: {faltando}. "
                "Abortando sem gravar tabela.json."
            )

        linhas.append({
            "time": canonico,
            "pontos": int(p), "jogos": int(j), "vitorias": int(v),
            "empates": int(emp), "derrotas": int(der), "gp": int(gp), "gc": int(gc),
            "sg": int(sg if sg is not None else int(gp) - int(gc)),
            "aproveitamento": int(round(100.0 * int(p) / (3 * int(j)))) if int(j) else 0,
            "_rank": rank,
        })

    print("De-para aplicado:")
    print("\n".join(de_para))

    if nao_mapeados:
        raise RuntimeError(
            "Times da ESPN sem correspondência canônica: "
            + ", ".join(sorted(set(nao_mapeados)))
            + " — adicione ao ALIASES e rode de novo."
        )
    nomes = [l["time"] for l in linhas]
    if sorted(nomes) != sorted(CANONICOS):
        faltam = sorted(set(CANONICOS) - set(nomes))
        sobram = sorted(set(nomes) - set(CANONICOS))
        raise RuntimeError(f"Tabela inconsistente. Faltam: {faltam} | Sobram: {sobram}.")
    if len(nomes) != len(set(nomes)):
        raise RuntimeError("Time duplicado na tabela. Abortando.")

    if all(l.get("_rank") for l in linhas):
        linhas.sort(key=lambda l: int(l["_rank"]))
    else:
        linhas.sort(key=lambda l: (-l["pontos"], -l["vitorias"], -l["sg"], -l["gp"], l["time"]))

    tabela = []
    for i, l in enumerate(linhas, 1):
        l.pop("_rank", None)
        tabela.append({"pos": i, **l})

    saida = {
        "atualizado_em": iso_agora_brt(),
        "fonte": "ESPN",
        "tabela": tabela,
    }
    return saida


# ---------------------------------------------------------------------------
# SCOREBOARD -> jogos.json / resultados.json / espn_eventos.json
# ---------------------------------------------------------------------------
def periodo_temporada() -> tuple[datetime, datetime]:
    # Para o workflow de 10 em 10 minutos, não faz sentido consultar dezembro
    # inteiro em julho. Buscamos a temporada desde 1º/jan até 60 dias à frente,
    # mantendo os resultados acumulados e os próximos jogos sem pressionar a API.
    inicio = datetime(TEMPORADA, 1, 1, tzinfo=timezone.utc)
    fim_temporada = datetime(TEMPORADA, 12, 31, 23, 59, tzinfo=timezone.utc)
    fim_janela = datetime.now(timezone.utc) + timedelta(days=60)
    return inicio, min(fim_temporada, fim_janela)


def datas_url(inicio: datetime, fim: datetime) -> str:
    return f"{inicio.strftime('%Y%m%d')}-{fim.strftime('%Y%m%d')}"


def buscar_eventos_scoreboard() -> list[dict[str, Any]]:
    print("== EVENTOS/JOGOS/RESULTADOS (ESPN scoreboard) ==")
    inicio, fim = periodo_temporada()
    eventos_por_id: dict[str, dict[str, Any]] = {}
    cursor = inicio
    while cursor <= fim:
        proximo = min(cursor + timedelta(days=27), fim)
        url = f"{URL_SCOREBOARD}?dates={datas_url(cursor, proximo)}&limit=200"
        print(f"Fonte: {url}")
        data = fetch_json(url, timeout=25, tentativas=2)
        for ev in data.get("events") or []:
            eid = str(ev.get("id") or "")
            if eid:
                eventos_por_id[eid] = ev
        cursor = proximo + timedelta(days=1)
    eventos = list(eventos_por_id.values())
    print(f"Eventos brutos encontrados na temporada: {len(eventos)}")
    if not eventos:
        raise RuntimeError("A ESPN não retornou eventos para a temporada; mantendo JSONs anteriores.")
    return eventos


def primeira_competicao(ev: dict[str, Any]) -> dict[str, Any]:
    comps = ev.get("competitions") or []
    return comps[0] if comps else {}


def status_evento(ev: dict[str, Any]) -> dict[str, Any]:
    comp = primeira_competicao(ev)
    return comp.get("status") or ev.get("status") or {}


def tipo_status(ev: dict[str, Any]) -> dict[str, Any]:
    return status_evento(ev).get("type") or {}


def competidores(ev: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    comp = primeira_competicao(ev)
    cs = comp.get("competitors") or []
    casa = next((c for c in cs if c.get("homeAway") == "home"), None)
    fora = next((c for c in cs if c.get("homeAway") == "away"), None)
    return casa, fora


def canonico_competidor(c: dict[str, Any] | None) -> str | None:
    if not c:
        return None
    t = c.get("team") or {}
    return para_canonico(
        t.get("displayName"), t.get("shortDisplayName"), t.get("name"),
        t.get("location"), t.get("abbreviation"), t.get("slug"),
    )


def parse_data_evento_brt(ev: dict[str, Any]) -> datetime | None:
    valor = ev.get("date") or primeira_competicao(ev).get("date")
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).astimezone(FUSO_BRASILIA)
    except ValueError:
        return None


def placar_competidor(c: dict[str, Any] | None) -> int | None:
    if not c:
        return None
    v = c.get("score")
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def transmissao_evento(ev: dict[str, Any]) -> str:
    comp = primeira_competicao(ev)
    nomes: list[str] = []
    for b in comp.get("broadcasts") or []:
        nomes.extend(str(n).strip() for n in (b.get("names") or []) if str(n).strip())
        for k in ("shortName", "name"):
            v = str(b.get(k) or "").strip()
            if v:
                nomes.append(v)
    for g in comp.get("geoBroadcasts") or []:
        media = g.get("media") or {}
        for k in ("shortName", "name"):
            v = str(media.get(k) or "").strip()
            if v:
                nomes.append(v)
    # Dedup preservando ordem.
    vistos: set[str] = set()
    saida: list[str] = []
    for n in nomes:
        chave = normalizar(n)
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(n)
    return " / ".join(saida)


def extrair_rodada_evento(ev: dict[str, Any]) -> int | None:
    comp = primeira_competicao(ev)
    candidatos: list[Any] = []
    for no in (ev, comp, ev.get("season") or {}, comp.get("season") or {}, ev.get("week") or {}, comp.get("week") or {}, comp.get("round") or {}):
        if isinstance(no, dict):
            for k in ("number", "week", "round", "value"):
                candidatos.append(no.get(k))
            for k in ("displayName", "name", "shortName", "text", "description"):
                candidatos.append(no.get(k))
    for nota in comp.get("notes") or []:
        if isinstance(nota, dict):
            candidatos.extend(nota.values())
        else:
            candidatos.append(nota)
    for c in candidatos:
        if c is None or c == "":
            continue
        if isinstance(c, (int, float)) and 1 <= int(c) <= 38:
            return int(c)
        m = re.search(r"(?:rodada|round|week|matchday)?\s*([1-3]?\d)\b", str(c), flags=re.I)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 38:
                return n
    return None


def carregar_rodadas_legadas() -> dict[tuple[str, str, str], int]:
    """Usa os JSONs atuais apenas como fallback de rodada se a ESPN omitir week."""
    mapa: dict[tuple[str, str, str], int] = {}
    for arquivo, chave_lista in (("jogos.json", "jogos"), ("resultados.json", "resultados")):
        p = Path(arquivo)
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get(chave_lista) or []:
            try:
                mand = para_canonico((item.get("mandante") or {}).get("nome"))
                vis = para_canonico((item.get("visitante") or {}).get("nome"))
                rodada = int(item.get("rodada") or 0)
                dt = str(item.get("data_iso") or "")[:10]
                if mand and vis and rodada:
                    mapa[(mand, vis, dt)] = rodada
            except Exception:
                continue
    return mapa



def carregar_ajustes_calendario() -> list[dict[str, Any]]:
    """Lê correções manuais para partidas adiadas/reagendadas.

    O arquivo é deliberadamente pequeno e versionado. Ele só altera jogos cujo
    event_id ou confronto coincida; qualquer entrada inválida é ignorada com aviso.
    """
    if not ARQ_AJUSTES_CALENDARIO.exists():
        return []
    try:
        dados = json.loads(ARQ_AJUSTES_CALENDARIO.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Falha ao ler {ARQ_AJUSTES_CALENDARIO}: {exc}") from exc
    ajustes = dados.get("ajustes") or []
    if not isinstance(ajustes, list):
        raise RuntimeError(f"{ARQ_AJUSTES_CALENDARIO}: campo ajustes deve ser lista")
    return [a for a in ajustes if isinstance(a, dict)]


def _parse_data_manual_brt(valor: Any) -> datetime | None:
    if not valor:
        return None
    texto = str(valor).strip()
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASILIA)
    return dt.astimezone(FUSO_BRASILIA)


def aplicar_ajustes_calendario(eventos: list[dict[str, Any]]) -> None:
    ajustes = carregar_ajustes_calendario()
    if not ajustes:
        return
    aplicados = 0
    for ajuste in ajustes:
        event_id = str(ajuste.get("event_id") or "").strip()
        mand = para_canonico(ajuste.get("mandante"))
        vis = para_canonico(ajuste.get("visitante"))
        alvo = None
        for e in eventos:
            bate_id = bool(event_id and str(e.get("event_id") or "") == event_id)
            bate_jogo = bool(mand and vis and e.get("mandante_nome") == mand and e.get("visitante_nome") == vis)
            if bate_id or bate_jogo:
                alvo = e
                break
        if alvo is None:
            print(f"Aviso: ajuste de calendário não encontrou evento: {event_id or (mand + ' x ' + vis if mand and vis else '?')}")
            continue

        fonte_finalizada = bool(alvo.get("concluido") is True)
        rodada = ajuste.get("rodada")
        if rodada not in (None, ""):
            alvo["rodada"] = int(rodada)
        alvo["adiado"] = True
        alvo["ajuste_calendario"] = True
        alvo["motivo_ajuste"] = str(ajuste.get("motivo") or "").strip()

        if ajuste.get("data_definir") is True:
            alvo["data_definir"] = True
            alvo["data_iso"] = None
            alvo["data_dt"] = None
            alvo["_sort"] = float("inf")
        elif ajuste.get("data_iso"):
            dt = _parse_data_manual_brt(ajuste.get("data_iso"))
            if not dt:
                raise RuntimeError(f"Data manual inválida no ajuste {event_id}: {ajuste.get('data_iso')}")
            alvo["data_definir"] = False
            alvo["data_dt"] = dt
            alvo["data_iso"] = dt.strftime("%Y-%m-%dT%H:%M")
            alvo["_sort"] = dt.timestamp()

        # Depois que a ESPN confirmar o jogo como concluído, preserva placar e
        # status oficiais. Campos de estado do ajuste só valem até pouco antes
        # do novo horário: depois disso a fonte esportiva volta a ser soberana.
        # Isso evita que um reagendamento antigo mantenha eternamente um jogo
        # já disputado como "Agendado/AO VIVO".
        campos_estado = ("estado", "status", "placar_mandante", "placar_visitante", "concluido")
        for campo in ("estadio", "transmissao"):
            if campo in ajuste and ajuste[campo]:
                alvo[campo] = ajuste[campo]
        inicio_ajustado = alvo.get("data_dt")
        estado_manual_ainda_valido = not isinstance(inicio_ajustado, datetime) or agora_brt() < inicio_ajustado - timedelta(minutes=15)
        if not fonte_finalizada and estado_manual_ainda_valido:
            for campo in campos_estado:
                if campo in ajuste:
                    alvo[campo] = ajuste[campo]
        aplicados += 1
    print(f"Ajustes de calendário aplicados: {aplicados}/{len(ajustes)}")


def normalizar_eventos_scoreboard(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    legadas = carregar_rodadas_legadas()
    normalizados: list[dict[str, Any]] = []
    nao_mapeados: list[str] = []

    for ev in eventos:
        casa, fora = competidores(ev)
        mand = canonico_competidor(casa)
        vis = canonico_competidor(fora)
        if not mand or not vis:
            label = ev.get("shortName") or ev.get("name") or ev.get("id") or "?"
            nao_mapeados.append(str(label))
            continue
        dt_brt = parse_data_evento_brt(ev)
        if not dt_brt:
            continue
        comp = primeira_competicao(ev)
        st = tipo_status(ev)
        estado = str(st.get("state") or "pre").lower()
        if st.get("completed") is True:
            estado = "post"

        rodada = extrair_rodada_evento(ev)
        if not rodada:
            rodada = legadas.get((mand, vis, dt_brt.strftime("%Y-%m-%d")))

        normalizados.append({
            "event_id": str(ev.get("id") or ""),
            "rodada": rodada,
            "data_dt": dt_brt,
            "data_iso": dt_brt.strftime("%Y-%m-%dT%H:%M"),
            "mandante_nome": mand,
            "visitante_nome": vis,
            "mandante": info_time(mand),
            "visitante": info_time(vis),
            "estadio": ((comp.get("venue") or {}).get("fullName") or ""),
            "transmissao": transmissao_evento(ev),
            "status": status_evento(ev).get("displayClock") or st.get("shortDetail") or st.get("detail") or "",
            "estado": estado,
            "concluido": bool(st.get("completed") is True),
            "placar_mandante": placar_competidor(casa),
            "placar_visitante": placar_competidor(fora),
            "_sort": dt_brt.timestamp(),
        })

    if nao_mapeados:
        print("Aviso: eventos ESPN com clubes fora do de-para foram ignorados:")
        for n in sorted(set(nao_mapeados)):
            print(f"  - {n}")

    normalizados.sort(key=lambda e: e["_sort"])
    inferir_rodadas_faltantes(normalizados)
    aplicar_ajustes_calendario(normalizados)
    normalizados = sanear_eventos_por_rodada(normalizados)
    return normalizados


def inferir_rodadas_faltantes(eventos: list[dict[str, Any]]) -> None:
    """Fallback conservador: se a ESPN não trouxer rodada, usa blocos de 10 jogos."""
    for i, e in enumerate(eventos):
        if e.get("rodada"):
            continue
        # Rodada aproximada pelo calendário completo da temporada; serve só como
        # plano B para não quebrar visual. Quando a ESPN/JSON legado traz rodada,
        # essa inferência não entra.
        e["rodada"] = max(1, min(38, (i // 10) + 1))


def prefixo_evento_espn(event_id: Any) -> str:
    s = str(event_id or "")
    return s[:6] if len(s) >= 6 else s


def sanear_eventos_por_rodada(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Garante a regra estrutural do Brasileirão: no máximo 10 jogos por rodada,
    e nenhum clube duplicado dentro da mesma rodada.

    A ESPN eventualmente inclui jogos isolados/reagendados com o mesmo número de
    rodada do calendário regular. Isso gera rodadas com 11 jogos e às vezes com
    o mesmo clube em dois confrontos da mesma rodada — inviável para o site e o
    bolão.

    Ordem de prioridade dentro da rodada (nada é descartado sem passar por ela):
      1. jogos com ajuste manual do calendário (ajuste_calendario=True) — nunca
         são cortados; se cortarmos um, perdemos placar/estado importantes;
      2. jogos concluídos com placar válido — segundo em prioridade para não
         perder resultado que já aconteceu;
      3. jogos por data crescente — critério neutro para os demais.

    A dedup por clube roda em toda rodada — mesmo com 10 jogos exatos — se
    detectar duplicata. Se um jogo for "sobrando" na rodada, ele volta para o
    balde 'sem rodada' (por dedução, pertence a outra rodada) para não sumir do
    site; se for realmente inconsistente, é logado como aviso.
    """
    def _prioridade(e: dict[str, Any]) -> tuple[int, int, float]:
        # Menor tupla = maior prioridade.
        ajuste = 0 if e.get("ajuste_calendario") else 1
        concluido = 0 if (e.get("concluido") is True or e.get("estado") == "post") else 1
        return (ajuste, concluido, float(e.get("_sort") or 0))

    def _placar_valido(e: dict[str, Any]) -> bool:
        pm, pv = e.get("placar_mandante"), e.get("placar_visitante")
        return (e.get("concluido") is True or e.get("estado") == "post") and isinstance(pm, int) and isinstance(pv, int)

    por_rodada: dict[int, list[dict[str, Any]]] = {}
    sem_rodada: list[dict[str, Any]] = []
    for e in eventos:
        r = int(e.get("rodada") or 0)
        if not r:
            sem_rodada.append(e)
            continue
        por_rodada.setdefault(r, []).append(e)

    saneados: list[dict[str, Any]] = []
    for rodada in sorted(por_rodada):
        arr = sorted(por_rodada[rodada], key=_prioridade)
        original = len(arr)

        # Detecta duplicata de clube na rodada.
        contagem: dict[str, int] = {}
        for e in arr:
            for nome in (str(e.get("mandante_nome") or ""), str(e.get("visitante_nome") or "")):
                if nome:
                    contagem[nome] = contagem.get(nome, 0) + 1
        tem_duplicata = any(n > 1 for n in contagem.values())

        # Se a rodada está limpa (≤ 10 jogos e sem duplicata), não mexe em nada.
        if original <= 10 and not tem_duplicata:
            saneados.extend(arr)
            continue

        # Passo 1 (só se > 10): prioriza prefixo dominante de event_id da ESPN
        # (bloco regular do campeonato). Preserva ajustes manuais mesmo que
        # tenham prefixo minoritário.
        if original > 10:
            cont: dict[str, int] = {}
            for e in arr:
                pref = prefixo_evento_espn(e.get("event_id"))
                if pref:
                    cont[pref] = cont.get(pref, 0) + 1
            dominante = max(cont.items(), key=lambda kv: kv[1])[0] if cont else ""
            filtrada = [
                e for e in arr
                if e.get("ajuste_calendario") or prefixo_evento_espn(e.get("event_id")) == dominante
            ]
            if len(filtrada) >= 10:
                arr = filtrada

        # Passo 2: dedup por clube preservando a ordem de prioridade acima.
        # Nunca cortamos um jogo com ajuste manual. Se um jogo cair fora,
        # tenta reencaixá-lo no balde 'sem rodada' — ele vai sobrar como
        # anomalia registrada.
        usados: set[str] = set()
        selecionados: list[dict[str, Any]] = []
        excedentes: list[dict[str, Any]] = []
        for e in arr:
            mand = str(e.get("mandante_nome") or "")
            vis = str(e.get("visitante_nome") or "")
            if not mand or not vis:
                excedentes.append(e)
                continue
            colisao = mand in usados or vis in usados
            if colisao:
                # Nunca descarta ajuste manual e nunca descarta jogo com placar
                # válido — se algum deles bate com uso anterior, é indício de
                # inconsistência da ESPN; segurar o extra em 'sem_rodada' para
                # não sumir do site.
                if e.get("ajuste_calendario") or _placar_valido(e):
                    print(
                        f"  ATENÇÃO: rodada {rodada}: jogo prioritário colidiu "
                        f"com {mand} x {vis} (event {e.get('event_id')}); "
                        f"mantido fora da rodada para inspeção."
                    )
                    excedentes.append(e)
                else:
                    print(
                        f"  extra ignorado: rodada {rodada}: {mand} x {vis} "
                        f"({e.get('data_iso')}, {e.get('event_id')})"
                    )
                continue
            if len(selecionados) >= 10:
                excedentes.append(e)
                continue
            usados.add(mand)
            usados.add(vis)
            selecionados.append(e)

        if original != len(selecionados):
            print(
                f"Rodada {rodada}: ESPN retornou {original} jogos; publicando "
                f"{len(selecionados)} (dedup ativo)."
            )
        saneados.extend(selecionados)
        # Excedentes com ajuste ou placar viram anomalias visíveis em 'sem_rodada'
        # para o AF-Previsão / auditoria detectar. Extras neutros são descartados
        # com log acima. A rodada é limpa (0) para não contar duas vezes.
        for e in excedentes:
            if e.get("ajuste_calendario") or _placar_valido(e):
                anomalia = dict(e)
                anomalia["rodada"] = 0
                anomalia["rodada_original_espn"] = int(e.get("rodada") or 0)
                anomalia["excedente_sanear"] = True
                sem_rodada.append(anomalia)

    saneados.extend(sem_rodada)
    saneados.sort(key=lambda e: e.get("_sort") or 0)
    return saneados


def carregar_resultados_manuais() -> list[dict[str, Any]]:
    """Lê correções pontuais de resultados quando a ESPN mantém um evento
    reagendado em estado antigo. O arquivo é transparente, versionado e só
    aceita placares finais completos.
    """
    if not ARQ_RESULTADOS_MANUAIS.exists():
        return []
    try:
        dados = json.loads(ARQ_RESULTADOS_MANUAIS.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Falha ao ler {ARQ_RESULTADOS_MANUAIS}: {exc}") from exc
    jogos = dados.get("jogos") or {}
    if isinstance(jogos, dict):
        itens = []
        for chave, valor in jogos.items():
            if isinstance(valor, dict):
                item = dict(valor)
                item.setdefault("event_id", str(chave))
                itens.append(item)
        return itens
    if isinstance(jogos, list):
        return [dict(x) for x in jogos if isinstance(x, dict)]
    raise RuntimeError(f"{ARQ_RESULTADOS_MANUAIS}: campo jogos deve ser objeto ou lista")


def _placar_manual(valor: Any, campo: str) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Resultado manual com {campo} inválido: {valor!r}") from exc
    if numero < 0 or numero > 30:
        raise RuntimeError(f"Resultado manual com {campo} fora do intervalo: {numero}")
    return numero


def aplicar_resultados_manuais(eventos: list[dict[str, Any]]) -> int:
    """Aplica fallback final somente quando a fonte ainda não encerrou o jogo.

    Se a ESPN já publicou o resultado, o placar oficial é preservado. Qualquer
    divergência entre ESPN finalizada e o cadastro manual interrompe a geração,
    evitando que uma correção antiga sobrescreva um resultado oficial.
    """
    aplicados = 0
    for ajuste in carregar_resultados_manuais():
        if ajuste.get("ativo") is False:
            continue
        event_id = str(ajuste.get("event_id") or "").strip()
        mand = para_canonico(ajuste.get("mandante"))
        vis = para_canonico(ajuste.get("visitante"))
        alvo = None
        for evento in eventos:
            bate_id = bool(event_id and str(evento.get("event_id") or "") == event_id)
            bate_jogo = bool(mand and vis and evento.get("mandante_nome") == mand and evento.get("visitante_nome") == vis)
            if bate_id or bate_jogo:
                alvo = evento
                break
        if alvo is None:
            if not (event_id and mand and vis and ajuste.get("data_iso")):
                raise RuntimeError(f"Resultado manual não encontrou evento e não possui dados para criá-lo: {event_id or '?'}")
            data_dt = _parse_data_manual_brt(ajuste.get("data_iso"))
            if not data_dt:
                raise RuntimeError(f"Resultado manual com data inválida: {ajuste.get('data_iso')}")
            alvo = {
                "event_id": event_id,
                "rodada": int(ajuste.get("rodada") or 0),
                "data_dt": data_dt,
                "data_iso": data_dt.strftime("%Y-%m-%dT%H:%M"),
                "mandante_nome": mand,
                "visitante_nome": vis,
                "mandante": info_time(mand),
                "visitante": info_time(vis),
                "estadio": str(ajuste.get("estadio") or ""),
                "transmissao": str(ajuste.get("transmissao") or ""),
                "adiado": bool(ajuste.get("adiado") is True),
                "data_definir": False,
                "_sort": data_dt.timestamp(),
            }
            eventos.append(alvo)

        pm = _placar_manual(ajuste.get("placar_mandante"), "placar_mandante")
        pv = _placar_manual(ajuste.get("placar_visitante"), "placar_visitante")
        oficial_final = bool(alvo.get("concluido") is True or str(alvo.get("estado") or "").lower() == "post")
        if oficial_final:
            oficial_pm = alvo.get("placar_mandante")
            oficial_pv = alvo.get("placar_visitante")
            placar_oficial_presente = oficial_pm is not None and oficial_pv is not None
            placar_divergente = placar_oficial_presente and (int(oficial_pm), int(oficial_pv)) != (pm, pv)
            sobrescrever_finalizada = bool(
                ajuste.get("permitir_sobrescrever_espn_finalizada") is True
                or ajuste.get("sobrescrever_espn_finalizada") is True
            )
            if placar_divergente and not sobrescrever_finalizada:
                raise RuntimeError(
                    f"Resultado manual diverge da ESPN finalizada em {event_id or mand + ' x ' + vis}: "
                    f"ESPN {oficial_pm}x{oficial_pv}, manual {pm}x{pv}"
                )
            if not placar_divergente:
                continue
            print(
                "::warning::Resultado manual autorizado sobrepôs placar ESPN finalizado "
                f"em {event_id or mand + ' x ' + vis}: ESPN {oficial_pm}x{oficial_pv}, manual {pm}x{pv}"
            )

        if ajuste.get("data_iso"):
            data_dt = _parse_data_manual_brt(ajuste.get("data_iso"))
            if not data_dt:
                raise RuntimeError(f"Resultado manual com data inválida: {ajuste.get('data_iso')}")
            alvo["data_dt"] = data_dt
            alvo["data_iso"] = data_dt.strftime("%Y-%m-%dT%H:%M")
            alvo["_sort"] = data_dt.timestamp()
        if ajuste.get("rodada") not in (None, ""):
            alvo["rodada"] = int(ajuste.get("rodada"))
        alvo["placar_mandante"] = pm
        alvo["placar_visitante"] = pv
        alvo["estado"] = "post"
        alvo["concluido"] = True
        alvo["status"] = str(ajuste.get("status") or "Encerrado")
        alvo["resultado_manual"] = True
        alvo["resultado_fallback"] = True
        alvo["fonte_resultado"] = "override manual"
        alvo["origem_resultado"] = str(ajuste.get("origem") or "fallback manual versionado")
        alvo["motivo_resultado_manual"] = str(ajuste.get("motivo") or "Fonte principal manteve estado inconsistente")
        alvo["motivo_fallback"] = alvo["motivo_resultado_manual"]
        alvo["adiado"] = bool(ajuste.get("adiado", alvo.get("adiado") is True))
        aplicados += 1
    eventos.sort(key=lambda e: e.get("_sort") or 0)
    if aplicados:
        print(f"Resultados manuais aplicados: {aplicados}")
    return aplicados



def _clubes_das_discrepancias(discrepancias: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("clube") or "")
        for item in discrepancias
        if str(item.get("clube") or "") in CANONICOS
    }


def _eventos_candidatos_fallback(
    eventos: list[dict[str, Any]],
    discrepancias: list[dict[str, Any]],
    *,
    permitir_finalizados_espn: bool = False,
) -> list[dict[str, Any]]:
    clubes = _clubes_das_discrepancias(discrepancias)
    agora = agora_brt()
    candidatos: list[dict[str, Any]] = []
    for evento in eventos:
        inicio = evento.get("data_dt")
        if not isinstance(inicio, datetime) or inicio > agora - timedelta(minutes=90):
            continue
        mandante = str(evento.get("mandante_nome") or "")
        visitante = str(evento.get("visitante_nome") or "")
        if clubes and mandante not in clubes and visitante not in clubes:
            continue
        # Regra geral: uma fonte auxiliar não substitui silenciosamente um
        # resultado ESPN já considerado final. A exceção é a CBF, autoridade
        # oficial da competição: ela pode corrigir um placar final da ESPN, mas
        # a mudança só é aceita se a auditoria completa reduzir a divergência.
        if evento_realmente_finalizado(evento, agora) and not permitir_finalizados_espn:
            continue
        candidatos.append(evento)
    candidatos.sort(key=lambda item: item.get("_sort") or 0, reverse=True)
    return candidatos


def _aplicar_placar_complementar(
    evento: dict[str, Any],
    *,
    placar_mandante: int,
    placar_visitante: int,
    fonte: str,
    origem: str,
    motivo: str,
    status: str = "Encerrado",
) -> None:
    evento["placar_mandante"] = int(placar_mandante)
    evento["placar_visitante"] = int(placar_visitante)
    evento["estado"] = "post"
    evento["concluido"] = True
    evento["status"] = status
    evento["resultado_fallback"] = fonte != "ESPN summary"
    evento["fonte_resultado"] = fonte
    evento["origem_resultado"] = origem
    evento["motivo_fallback"] = motivo


def _evento_bruto_do_summary(payload: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions else None
    if not isinstance(competition, dict):
        return None
    return {
        "id": str(header.get("id") or event_id),
        "date": competition.get("date") or header.get("date"),
        "status": competition.get("status") or header.get("status"),
        "competitions": [competition],
    }


def aplicar_resumos_alternativos_espn(
    eventos: list[dict[str, Any]], discrepancias: list[dict[str, Any]]
) -> int:
    """Tenta o summary individual da ESPN antes de abandonar a fonte principal."""
    aplicados = 0
    for alvo in _eventos_candidatos_fallback(eventos, discrepancias)[:8]:
        event_id = str(alvo.get("event_id") or "").strip()
        if not event_id:
            continue
        try:
            payload = fetch_json(f"{URL_RESUMO_EVENTO}?event={urllib.parse.quote(event_id)}", timeout=20, tentativas=1)
            bruto = _evento_bruto_do_summary(payload, event_id)
            if not bruto:
                continue
            normalizados = normalizar_eventos_scoreboard([bruto])
            if not normalizados:
                continue
            resumo = normalizados[0]
            if not evento_realmente_finalizado(resumo, agora_brt()):
                continue
            if resumo.get("placar_mandante") is None or resumo.get("placar_visitante") is None:
                continue
            # Confirma o confronto. O ID pode ter sido duplicado/reagendado pela ESPN.
            if (
                resumo.get("mandante_nome") != alvo.get("mandante_nome")
                or resumo.get("visitante_nome") != alvo.get("visitante_nome")
            ):
                continue
            antes = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
            _aplicar_placar_complementar(
                alvo,
                placar_mandante=int(resumo["placar_mandante"]),
                placar_visitante=int(resumo["placar_visitante"]),
                fonte="ESPN summary",
                origem=f"{URL_RESUMO_EVENTO}?event={event_id}",
                motivo="Scoreboard geral divergente; resultado confirmado no summary individual da ESPN.",
                status=str(resumo.get("status") or "Encerrado"),
            )
            depois = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
            if antes != depois:
                aplicados += 1
        except Exception as exc:  # noqa: BLE001
            print(f"::warning::Summary ESPN indisponível para {event_id}: {type(exc).__name__}: {exc}")
    if aplicados:
        print(f"Resultados recuperados por endpoint alternativo da ESPN: {aplicados}")
    return aplicados


def aplicar_resultados_cbf(
    eventos: list[dict[str, Any]], discrepancias: list[dict[str, Any]]
) -> int:
    """Usa a tabela detalhada oficial da CBF apenas para placares já encerrados."""
    try:
        linhas = buscar_tabela_detalhada_cbf(resolver=para_canonico)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::Fallback CBF indisponível: {type(exc).__name__}: {exc}")
        return 0

    aplicados = 0
    agora = agora_brt()
    for alvo in _eventos_candidatos_fallback(
        eventos, discrepancias, permitir_finalizados_espn=True
    ):
        linha = localizar_partida_cbf(
            linhas,
            mandante=str(alvo.get("mandante_nome") or ""),
            visitante=str(alvo.get("visitante_nome") or ""),
            rodada=int(alvo.get("rodada") or 0),
            data_iso=str(alvo.get("data_iso") or ""),
        )
        if not linha or linha.placar_mandante is None or linha.placar_visitante is None:
            continue
        inicio = parse_iso_brt(linha.data_iso)
        if not inicio or inicio > agora - timedelta(minutes=90):
            continue
        antes = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
        _aplicar_placar_complementar(
            alvo,
            placar_mandante=linha.placar_mandante,
            placar_visitante=linha.placar_visitante,
            fonte="CBF",
            origem=linha.origem,
            motivo=(
                "A ESPN permaneceu divergente da classificação; placar final "
                f"confirmado na tabela detalhada oficial da CBF (ref. {linha.referencia or 'não informada'})."
            ),
        )
        depois = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
        if antes != depois or alvo.get("fonte_resultado") != "CBF":
            aplicados += 1
    if aplicados:
        print(f"Resultados confirmados pela CBF: {aplicados}")
    return aplicados


def aplicar_resultados_api_football(
    eventos: list[dict[str, Any]], discrepancias: list[dict[str, Any]]
) -> int:
    """Fallback opcional e cirúrgico; não consome quota sem divergência."""
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    league_id = os.environ.get("API_FOOTBALL_LEAGUE_ID", "").strip()
    if not api_key or not league_id:
        print("API-Football não configurada; fallback opcional ignorado.")
        return 0

    candidatos = _eventos_candidatos_fallback(eventos, discrepancias)
    por_data: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evento in candidatos:
        inicio = evento.get("data_dt")
        if isinstance(inicio, datetime):
            por_data[inicio.date().isoformat()].append(evento)

    aplicados = 0
    for data_iso, itens in por_data.items():
        try:
            fixtures = fetch_api_football_fixtures(
                api_key=api_key,
                league_id=league_id,
                season=TEMPORADA,
                match_date=datetime.fromisoformat(data_iso).date(),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"::warning::API-Football indisponível em {data_iso}: {type(exc).__name__}: {exc}")
            continue
        for alvo in itens:
            fixture = localizar_fixture_api_football(
                fixtures,
                mandante=str(alvo.get("mandante_nome") or ""),
                visitante=str(alvo.get("visitante_nome") or ""),
                resolver=para_canonico,
            )
            if not fixture:
                continue
            antes = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
            _aplicar_placar_complementar(
                alvo,
                placar_mandante=int(fixture["placar_mandante"]),
                placar_visitante=int(fixture["placar_visitante"]),
                fonte="API-Football",
                origem=f"API-Football fixture {fixture.get('fixture_id') or '?'}",
                motivo="ESPN e CBF não resolveram a divergência; resultado final confirmado pela API auxiliar.",
            )
            depois = (alvo.get("placar_mandante"), alvo.get("placar_visitante"), alvo.get("estado"), alvo.get("concluido"))
            if antes != depois or alvo.get("fonte_resultado") != "API-Football":
                aplicados += 1
    if aplicados:
        print(f"Resultados confirmados pela API-Football: {aplicados}")
    return aplicados


def listar_fallbacks_eventos(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for evento in eventos:
        fonte = str(evento.get("fonte_resultado") or "")
        if not fonte or fonte == "ESPN":
            continue
        out.append({
            "event_id": str(evento.get("event_id") or ""),
            "rodada": int(evento.get("rodada") or 0),
            "jogo": f"{evento.get('mandante_nome')} x {evento.get('visitante_nome')}",
            "placar": f"{evento.get('placar_mandante')} x {evento.get('placar_visitante')}",
            "fonte": fonte,
            "origem": str(evento.get("origem_resultado") or ""),
            "motivo": str(evento.get("motivo_fallback") or ""),
        })
    return out

def carregar_transmissoes_manuais() -> list[dict[str, Any]]:
    p = Path("transmissoes.json")
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return list(d.get("transmissoes") or [])
    except Exception:
        return []


def aplicar_transmissoes_manuais(eventos: list[dict[str, Any]]) -> None:
    manuais = carregar_transmissoes_manuais()
    for e in eventos:
        for t in manuais:
            if (
                para_canonico(t.get("mandante")) == e["mandante_nome"]
                and para_canonico(t.get("visitante")) == e["visitante_nome"]
                and (not t.get("rodada") or int(t.get("rodada")) == int(e.get("rodada") or 0))
            ):
                if t.get("transmissao"):
                    e["transmissao"] = str(t["transmissao"])



def parse_iso_brt(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        obj = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=FUSO_BRASILIA)
        return obj.astimezone(FUSO_BRASILIA)
    except (TypeError, ValueError):
        return None


def carregar_snapshot_eventos_anterior() -> tuple[dict[str, dict[str, Any]], datetime | None]:
    caminho = Path("espn_eventos.json")
    if not caminho.exists():
        return {}, None
    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}, None
    eventos = {
        str(item.get("event_id") or ""): item
        for item in (payload.get("eventos") or [])
        if item.get("event_id")
    }
    return eventos, parse_iso_brt(payload.get("atualizado_em"))


def estimar_finalizado_em(e: dict[str, Any], agora: datetime, anterior: dict[str, Any] | None = None,
                          snapshot_anterior_em: datetime | None = None) -> datetime:
    """Estima o apito final sem reiniciar a janela a cada deploy/reload.

    A API de scoreboard não publica um timestamp explícito de encerramento. O
    melhor sinal estável é o horário de início somado ao tempo efetivamente
    jogado, ao intervalo e a uma pequena margem operacional. Quando o snapshot
    anterior ainda mostrava o jogo em andamento, ele também funciona como piso.
    """
    inicio = e.get("data_dt")
    status = str(e.get("status") or "")
    m = re.search(r"(\d{1,3})\s*['’]?\s*(?:\+\s*(\d+))?", status)
    if m:
        minutos_totais = max(90, int(m.group(1))) + int(m.group(2) or 0) + 18
    else:
        # FT sem relógio: duração conservadora de 1h55 desde o horário oficial.
        minutos_totais = 115
    if isinstance(inicio, datetime):
        estimado = inicio + timedelta(minutes=minutos_totais)
    else:
        estimado = agora

    anterior = anterior or {}
    anterior_era_ao_vivo = str(anterior.get("estado") or "").lower() != "post" and not bool(anterior.get("concluido"))
    if anterior_era_ao_vivo and snapshot_anterior_em and estimado < snapshot_anterior_em:
        estimado = snapshot_anterior_em
    if estimado > agora:
        estimado = agora
    return estimado.astimezone(FUSO_BRASILIA)


def aplicar_finalizados_em(eventos: list[dict[str, Any]], anteriores: dict[str, dict[str, Any]],
                            snapshot_anterior_em: datetime | None, agora: datetime) -> None:
    for e in eventos:
        if not (e.get("estado") == "post" or e.get("concluido") is True):
            e.pop("finalizado_em", None)
            continue
        event_id = str(e.get("event_id") or "")
        anterior = anteriores.get(event_id) or {}
        preservado = parse_iso_brt(anterior.get("finalizado_em"))
        finalizado = preservado or estimar_finalizado_em(e, agora, anterior, snapshot_anterior_em)
        e["finalizado_em"] = finalizado.replace(microsecond=0).isoformat()


def payload_jogo(e: dict[str, Any], incluir_placar: bool = True) -> dict[str, Any]:
    status_publico = str(e.get("status") or "")
    if str(e.get("estado") or "").lower() == "post" and status_publico.strip().lower() in {"", "0'", "0", "0:00"}:
        status_publico = "Encerrado"
    obj = {
        "event_id": e.get("event_id", ""),
        "rodada": int(e.get("rodada") or 0),
        "data_iso": e["data_iso"],
        "mandante": e["mandante"],
        "visitante": e["visitante"],
        "estadio": e.get("estadio", ""),
        "transmissao": e.get("transmissao", ""),
        "status": status_publico,
        "estado": e.get("estado", "pre"),
        "adiado": bool(e.get("adiado") is True),
        "data_definir": bool(e.get("data_definir") is True),
    }
    if e.get("finalizado_em"):
        obj["finalizado_em"] = e["finalizado_em"]
    if e.get("resultado_fallback") is True:
        obj["resultado_fallback"] = True
        obj["fonte_resultado"] = e.get("fonte_resultado", "fonte complementar")
        obj["origem_resultado"] = e.get("origem_resultado", "")
        obj["motivo_fallback"] = e.get("motivo_fallback", "")
    if e.get("resultado_manual") is True:
        obj["resultado_manual"] = True
        obj["motivo_resultado_manual"] = e.get("motivo_resultado_manual", "")
    if incluir_placar:
        obj["placar_mandante"] = e.get("placar_mandante")
        obj["placar_visitante"] = e.get("placar_visitante")
    return obj



def evento_realmente_finalizado(e: dict[str, Any], agora: datetime) -> bool:
    """Resultado só entra no resultados.json depois que o jogo já aconteceu.

    A ESPN às vezes devolve placar 0x0 e estado/status inconsistentes para jogo
    futuro. Por isso a data também precisa estar no passado com margem de segurança.
    """
    if e.get("placar_mandante") is None or e.get("placar_visitante") is None:
        return False
    dt = e.get("data_dt")
    if not isinstance(dt, datetime):
        return False
    if dt > agora - timedelta(minutes=90):
        return False
    status = str(e.get("status") or "").strip().lower()
    estado = str(e.get("estado") or "").strip().lower()
    if estado == "pre":
        return False
    # Alguns jogos encerrados em 0 x 0 chegam com state="post", placar final,
    # mas completed=false e displayClock="0'". O relógio zerado só é suspeito
    # enquanto a fonte ainda não declarou o estado pós-jogo. A data mínima de
    # 90 minutos acima continua impedindo que um 0 x 0 futuro vire resultado.
    if estado != "post" and status in {"0'", "0", "0:00"}:
        return False
    return bool(e.get("concluido") is True or estado == "post" or dt < agora - timedelta(hours=2))

def gerar_jogos_resultados_eventos(eventos_brutos: list[dict[str, Any]],
                                     anteriores: dict[str, dict[str, Any]] | None = None,
                                     snapshot_anterior_em: datetime | None = None,
                                     *,
                                     eventos_ja_normalizados: bool = False,
                                     aplicar_manuais: bool = True) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    eventos = eventos_brutos if eventos_ja_normalizados else normalizar_eventos_scoreboard(eventos_brutos)
    if aplicar_manuais:
        aplicar_resultados_manuais(eventos)
    aplicar_transmissoes_manuais(eventos)
    if not eventos:
        raise RuntimeError("Nenhum evento ESPN foi normalizado; abortando para não publicar JSON vazio.")

    agora = agora_brt()
    aplicar_finalizados_em(eventos, anteriores or {}, snapshot_anterior_em, agora)
    futuros = [
        e for e in eventos
        if isinstance(e.get("data_dt"), datetime)
        and e["data_dt"] >= agora - timedelta(hours=3)
        and e.get("estado") != "post"
        and e.get("data_definir") is not True
    ]
    finalizados = [e for e in eventos if evento_realmente_finalizado(e, agora)]

    # Agenda pública por DATA REAL, não por duas rodadas numéricas. Assim jogos
    # adiados da rodada 4 aparecem no meio da rodada 19 na ordem correta.
    futuros.sort(key=lambda e: e["_sort"])
    proximos: list[dict[str, Any]] = []
    rodadas_usadas: list[int] = []
    if futuros:
        limite_data = futuros[0]["data_dt"] + timedelta(days=28)
        proximos = [e for e in futuros if e["data_dt"] <= limite_data][:60]
        if len(proximos) < min(20, len(futuros)):
            proximos = futuros[:20]
        rodadas_usadas = sorted({int(e.get("rodada") or 0) for e in proximos if e.get("rodada")})

    finalizados.sort(key=lambda e: e["_sort"], reverse=True)
    times_resultados = sorted({e["mandante_nome"] for e in finalizados} | {e["visitante_nome"] for e in finalizados}, key=lambda x: normalizar(x))
    rodadas_resultados = sorted({int(e.get("rodada") or 0) for e in finalizados if e.get("rodada")})

    atualizado_em = iso_agora_brt()
    atualizado_br = agora_brt().strftime("%d/%m/%Y %H:%M BRT")
    fallbacks_resultado = listar_fallbacks_eventos(eventos)
    fontes_complementares = sorted({item["fonte"] for item in fallbacks_resultado if item.get("fonte")})

    jogos_json = {
        "atualizado_em": atualizado_em,
        "atualizado_em_br": atualizado_br,
        "fonte": "ESPN",
        "fontes_complementares": fontes_complementares,
        "fallbacks_resultado": fallbacks_resultado,
        "rodada_atual": rodadas_usadas[0] if rodadas_usadas else None,
        "rodadas_consultadas": rodadas_usadas,
        "total_jogos": len(proximos),
        "jogos": [payload_jogo(e, incluir_placar=True) for e in proximos],
    }

    resultados_json = {
        "atualizado_em": atualizado_em,
        "atualizado_em_br": atualizado_br,
        "fonte": "ESPN",
        "fontes_complementares": fontes_complementares,
        "fallbacks_resultado": fallbacks_resultado,
        "ultima_rodada_disputada": max(rodadas_resultados) if rodadas_resultados else None,
        "rodadas_consultadas": rodadas_resultados,
        "total_resultados": len(finalizados),
        "times": times_resultados,
        "resultados": [payload_jogo(e, incluir_placar=True) for e in finalizados],
    }

    eventos_json = {
        "atualizado_em": atualizado_em,
        "fonte": "ESPN",
        "fontes_complementares": fontes_complementares,
        "fallbacks_resultado": fallbacks_resultado,
        "total": len(eventos),
        "eventos": [
            {
                "event_id": e.get("event_id", ""),
                "rodada": int(e.get("rodada") or 0),
                "data_iso": e["data_iso"],
                "mandante": e["mandante_nome"],
                "visitante": e["visitante_nome"],
                "estadio": e.get("estadio", ""),
                "transmissao": e.get("transmissao", ""),
                "status": e.get("status", ""),
                "estado": e.get("estado", ""),
                "concluido": bool(e.get("concluido") is True),
                "placar_mandante": e.get("placar_mandante"),
                "placar_visitante": e.get("placar_visitante"),
                "adiado": bool(e.get("adiado") is True),
                "data_definir": bool(e.get("data_definir") is True),
                "finalizado_em": e.get("finalizado_em", ""),
                "rodada_corrigida_de": e.get("rodada_corrigida_de"),
                "motivo_ajuste": e.get("motivo_ajuste", ""),
                "resultado_manual": bool(e.get("resultado_manual") is True),
                "resultado_fallback": bool(e.get("resultado_fallback") is True),
                "fonte_resultado": e.get("fonte_resultado", "ESPN"),
                "origem_resultado": e.get("origem_resultado", ""),
                "motivo_fallback": e.get("motivo_fallback", ""),
                "motivo_resultado_manual": e.get("motivo_resultado_manual", ""),
            }
            for e in eventos
        ],
    }

    # Validações de formato que o front espera.
    if proximos and not all(j.get("mandante") and j.get("visitante") and j.get("data_iso") for j in jogos_json["jogos"]):
        raise RuntimeError("jogos.json inválido: jogo sem mandante/visitante/data.")
    if finalizados and not all(r.get("placar_mandante") is not None and r.get("placar_visitante") is not None for r in resultados_json["resultados"]):
        raise RuntimeError("resultados.json inválido: resultado finalizado sem placar.")

    return jogos_json, resultados_json, eventos_json


def diagnosticar_sincronia_tabela_resultados(
    tabela_payload: dict[str, Any], resultados_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reconstrói a classificação pelos resultados e compara com o standings.

    A ESPN atualiza os endpoints de classificação e scoreboard de forma
    independente. Durante alguns minutos, um deles pode incorporar uma partida
    antes do outro. O snapshot só pode ser publicado quando os dois descrevem
    exatamente o mesmo estado esportivo.
    """
    tabela = tabela_payload.get("tabela") or []
    resultados = resultados_payload.get("resultados") or []
    oficiais = {str(item.get("time") or ""): item for item in tabela}
    if set(oficiais) != set(CANONICOS):
        return [{"clube": "*", "campo": "clubes", "reconstruido": len(oficiais), "oficial": len(CANONICOS)}]

    acumulado = {
        clube: {"jogos": 0, "pontos": 0, "vitorias": 0, "empates": 0,
                "derrotas": 0, "gp": 0, "gc": 0}
        for clube in CANONICOS
    }
    anomalias: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in resultados:
        event_id = str(item.get("event_id") or "").strip()
        if event_id:
            if event_id in ids:
                anomalias.append({
                    "clube": "*",
                    "campo": "event_id_duplicado",
                    "reconstruido": event_id,
                    "oficial": "único",
                })
                continue
            ids.add(event_id)
        mandante_bruto = item.get("mandante")
        visitante_bruto = item.get("visitante")
        mandante_nome = mandante_bruto.get("nome") if isinstance(mandante_bruto, dict) else mandante_bruto
        visitante_nome = visitante_bruto.get("nome") if isinstance(visitante_bruto, dict) else visitante_bruto
        mandante = para_canonico(mandante_nome, item.get("mandante_nome"))
        visitante = para_canonico(visitante_nome, item.get("visitante_nome"))
        try:
            gols_mandante = int(item.get("placar_mandante"))
            gols_visitante = int(item.get("placar_visitante"))
        except (TypeError, ValueError):
            anomalias.append({
                "clube": mandante or visitante or "*",
                "campo": "placar",
                "reconstruido": "inválido",
                "oficial": "inteiro",
            })
            continue
        if mandante not in acumulado or visitante not in acumulado or mandante == visitante:
            anomalias.append({
                "clube": mandante or visitante or "*",
                "campo": "confronto",
                "reconstruido": f"{mandante} x {visitante}",
                "oficial": "clubes canônicos distintos",
            })
            continue

        casa = acumulado[mandante]
        fora = acumulado[visitante]
        casa["jogos"] += 1
        fora["jogos"] += 1
        casa["gp"] += gols_mandante
        casa["gc"] += gols_visitante
        fora["gp"] += gols_visitante
        fora["gc"] += gols_mandante
        if gols_mandante > gols_visitante:
            casa["pontos"] += 3
            casa["vitorias"] += 1
            fora["derrotas"] += 1
        elif gols_mandante < gols_visitante:
            fora["pontos"] += 3
            fora["vitorias"] += 1
            casa["derrotas"] += 1
        else:
            casa["pontos"] += 1
            fora["pontos"] += 1
            casa["empates"] += 1
            fora["empates"] += 1

    discrepancias = list(anomalias)
    for clube in CANONICOS:
        oficial = oficiais[clube]
        for campo in ("jogos", "pontos", "vitorias", "empates", "derrotas", "gp", "gc"):
            reconstruido = int(acumulado[clube][campo])
            valor_oficial = int(oficial.get(campo) or 0)
            if reconstruido != valor_oficial:
                discrepancias.append({
                    "clube": clube,
                    "campo": campo,
                    "reconstruido": reconstruido,
                    "oficial": valor_oficial,
                })
    return discrepancias


def resumir_discrepancias(discrepancias: list[dict[str, Any]], limite: int = 8) -> str:
    amostra = "; ".join(
        f"{item['clube']} {item['campo']}={item['reconstruido']}/{item['oficial']}"
        for item in discrepancias[:limite]
    )
    restantes = len(discrepancias) - limite
    return amostra + (f"; e mais {restantes}" if restantes > 0 else "")


def snapshot_local_sincronizado() -> tuple[bool, str]:
    caminhos = {
        "tabela": Path("tabela.json"),
        "jogos": Path("jogos.json"),
        "resultados": Path("resultados.json"),
        "eventos": Path("espn_eventos.json"),
    }
    faltantes = [str(path) for path in caminhos.values() if not path.exists()]
    if faltantes:
        return False, "arquivos anteriores ausentes: " + ", ".join(faltantes)
    try:
        payloads = {
            nome: json.loads(path.read_text(encoding="utf-8"))
            for nome, path in caminhos.items()
        }
        tabela = payloads["tabela"]
        jogos = payloads["jogos"]
        resultados = payloads["resultados"]
        eventos = payloads["eventos"]

        for nome, payload in payloads.items():
            if not isinstance(payload, dict):
                raise RuntimeError(f"{caminhos[nome]} não contém objeto JSON")
            if payload.get("fonte") != "ESPN":
                raise RuntimeError(f"{caminhos[nome]} não declara fonte ESPN")

        validar_contra_ranking(tabela)
        colecoes = {
            "jogos": jogos.get("jogos"),
            "resultados": resultados.get("resultados"),
            "eventos": eventos.get("eventos"),
        }
        for nome, itens in colecoes.items():
            if not isinstance(itens, list):
                raise RuntimeError(f"{caminhos[nome]} não contém lista válida")
            ids = [str(item.get("event_id") or "").strip() for item in itens]
            if any(not event_id for event_id in ids):
                raise RuntimeError(f"{caminhos[nome]} contém event_id ausente")
            if len(ids) != len(set(ids)):
                raise RuntimeError(f"{caminhos[nome]} contém event_id duplicado")

        if int(jogos.get("total_jogos") or 0) != len(colecoes["jogos"]):
            raise RuntimeError("jogos.json possui total_jogos divergente")
        if int(resultados.get("total_resultados") or 0) != len(colecoes["resultados"]):
            raise RuntimeError("resultados.json possui total_resultados divergente")
        if int(eventos.get("total") or 0) != len(colecoes["eventos"]):
            raise RuntimeError("espn_eventos.json possui total divergente")

        ids_eventos = {str(item.get("event_id")) for item in colecoes["eventos"]}
        ids_jogos = {str(item.get("event_id")) for item in colecoes["jogos"]}
        ids_resultados = {str(item.get("event_id")) for item in colecoes["resultados"]}
        if not ids_jogos.issubset(ids_eventos):
            raise RuntimeError("jogos.json contém partidas ausentes de espn_eventos.json")
        if not ids_resultados.issubset(ids_eventos):
            raise RuntimeError("resultados.json contém partidas ausentes de espn_eventos.json")
        if ids_jogos & ids_resultados:
            raise RuntimeError("uma mesma partida aparece em jogos.json e resultados.json")

        discrepancias = diagnosticar_sincronia_tabela_resultados(tabela, resultados)
    except Exception as exc:  # noqa: BLE001
        return False, f"snapshot anterior inválido: {type(exc).__name__}: {exc}"
    if discrepancias:
        return False, "snapshot anterior fora de sincronia: " + resumir_discrepancias(discrepancias)
    return True, "snapshot anterior íntegro nos quatro artefatos ESPN"



def avaliar_eventos_normalizados(
    eventos: list[dict[str, Any]],
    tabela: dict[str, Any],
    anteriores: dict[str, dict[str, Any]],
    snapshot_anterior_em: datetime | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    jogos, resultados, eventos_json = gerar_jogos_resultados_eventos(
        eventos,
        anteriores,
        snapshot_anterior_em,
        eventos_ja_normalizados=True,
        aplicar_manuais=False,
    )
    discrepancias = diagnosticar_sincronia_tabela_resultados(tabela, resultados)
    return jogos, resultados, eventos_json, discrepancias


def tentar_fallback_transacional(
    eventos: list[dict[str, Any]],
    tabela: dict[str, Any],
    anteriores: dict[str, dict[str, Any]],
    snapshot_anterior_em: datetime | None,
    discrepancias_atuais: list[dict[str, Any]],
    nome: str,
    aplicador: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], int]:
    """Só aceita o fallback quando ele reduz a divergência ou fecha a tabela."""
    candidato = copy.deepcopy(eventos)
    aplicados = int(aplicador(candidato, discrepancias_atuais) or 0)
    if not aplicados:
        jogos, resultados, eventos_json, discrepancias = avaliar_eventos_normalizados(
            eventos, tabela, anteriores, snapshot_anterior_em
        )
        return eventos, jogos, resultados, eventos_json, discrepancias, 0

    jogos, resultados, eventos_json, novas = avaliar_eventos_normalizados(
        candidato, tabela, anteriores, snapshot_anterior_em
    )
    if len(novas) < len(discrepancias_atuais):
        print(
            f"Fallback {nome} aceito: divergências {len(discrepancias_atuais)} -> {len(novas)}."
        )
        return candidato, jogos, resultados, eventos_json, novas, aplicados

    print(
        f"::warning::Fallback {nome} rejeitado pela auditoria: divergências "
        f"{len(discrepancias_atuais)} -> {len(novas)}; estado anterior preservado."
    )
    jogos, resultados, eventos_json, discrepancias = avaliar_eventos_normalizados(
        eventos, tabela, anteriores, snapshot_anterior_em
    )
    return eventos, jogos, resultados, eventos_json, discrepancias, 0

def escrever_outputs_github(
    *,
    sincronizado: bool,
    motivo: str,
    tentativas: int,
    status: str | None = None,
    fallbacks: list[dict[str, Any]] | None = None,
) -> None:
    caminho = os.environ.get("GITHUB_OUTPUT")
    if not caminho:
        return
    texto = " ".join(str(motivo).splitlines())
    fallbacks = fallbacks or []
    status_final = status or ("ok" if sincronizado else "preservado")
    fallbacks_json = json.dumps(fallbacks, ensure_ascii=False, separators=(",", ":"))
    with open(caminho, "a", encoding="utf-8") as output:
        output.write(f"sincronizado={str(sincronizado).lower()}\n")
        output.write(f"status={status_final}\n")
        output.write(f"tentativas={tentativas}\n")
        output.write(f"motivo={texto}\n")
        output.write(f"fallbacks={fallbacks_json}\n")


def erro_transitorio_de_fonte(exc: Exception) -> bool:
    texto = str(exc).lower()
    sinais = (
        "falha ao buscar json",
        "indisponível",
        "não retornou eventos",
        "temporariamente",
        "timed out",
        "timeout",
        "temporary failure",
        "http error 429",
        "http error 500",
        "http error 502",
        "http error 503",
        "http error 504",
        "connection reset",
    )
    return any(sinal in texto for sinal in sinais)


def validar_contra_ranking(tabela_payload: dict[str, Any]) -> None:
    tabela = tabela_payload.get("tabela") or []
    if len(tabela) != 20:
        raise RuntimeError(f"tabela.json teria {len(tabela)} times; esperado 20.")
    nomes = [t.get("time") for t in tabela]
    if sorted(nomes) != sorted(CANONICOS):
        raise RuntimeError("tabela.json não preserva exatamente os 20 nomes canônicos do Ranking.")
    obrig = {"pos", "time", "pontos", "jogos", "vitorias", "empates", "derrotas", "gp", "gc", "sg", "aproveitamento"}
    for linha in tabela:
        faltando = obrig - set(linha)
        if faltando:
            raise RuntimeError(f"Linha de tabela sem campos obrigatórios {faltando}: {linha}")


def selftest_execucao_6() -> None:
    global ARQ_RESULTADOS_MANUAIS
    import tempfile

    original = ARQ_RESULTADOS_MANUAIS
    with tempfile.TemporaryDirectory() as tmp:
        ARQ_RESULTADOS_MANUAIS = Path(tmp) / "resultados-manuais.json"
        ARQ_RESULTADOS_MANUAIS.write_text(json.dumps({
            "jogos": {
                "x1": {
                    "ativo": True,
                    "event_id": "x1",
                    "rodada": 4,
                    "mandante": "Bahia",
                    "visitante": "Chapecoense",
                    "data_iso": "2026-07-17T19:30",
                    "placar_mandante": 2,
                    "placar_visitante": 0,
                    "status": "Encerrado",
                }
            }
        }), encoding="utf-8")
        dt = datetime(2026, 7, 17, 19, 30, tzinfo=FUSO_BRASILIA)
        evento = {
            "event_id": "x1", "rodada": 4, "data_dt": dt, "data_iso": "2026-07-17T19:30",
            "mandante_nome": "Bahia", "visitante_nome": "Chapecoense",
            "mandante": info_time("Bahia"), "visitante": info_time("Chapecoense"),
            "estado": "pre", "concluido": False, "status": "Agendado",
            "placar_mandante": None, "placar_visitante": None, "_sort": dt.timestamp(),
        }
        eventos = [evento]
        assert aplicar_resultados_manuais(eventos) == 1
        assert evento["estado"] == "post" and evento["concluido"] is True
        assert (evento["placar_mandante"], evento["placar_visitante"]) == (2, 0)
        assert evento_realmente_finalizado(evento, datetime(2026, 7, 18, 0, 0, tzinfo=FUSO_BRASILIA))

        evento_oficial = dict(evento)
        evento_oficial["resultado_manual"] = False
        evento_oficial["origem_resultado"] = ""
        assert aplicar_resultados_manuais([evento_oficial]) == 0

        evento_divergente = dict(evento_oficial)
        evento_divergente["placar_mandante"] = 1
        try:
            aplicar_resultados_manuais([evento_divergente])
        except RuntimeError as exc:
            assert "diverge da ESPN" in str(exc)
        else:
            raise AssertionError("divergência entre ESPN e manual não foi bloqueada")
    ARQ_RESULTADOS_MANUAIS = original

    # Regressão do empate Botafogo 0 x 0 Vitória: a ESPN publicou state=post
    # e placar final, mas manteve completed=false/displayClock="0'".
    agora_teste = datetime(2026, 7, 23, 21, 22, tzinfo=FUSO_BRASILIA)
    empate_post = {
        "event_id": "sync-zero",
        "rodada": 4,
        "data_iso": "2026-07-23T19:30",
        "data_dt": datetime(2026, 7, 23, 19, 30, tzinfo=FUSO_BRASILIA),
        "mandante": info_time("Botafogo"),
        "visitante": info_time("Vitória"),
        "placar_mandante": 0,
        "placar_visitante": 0,
        "estado": "post",
        "concluido": False,
        "status": "0'",
    }
    assert evento_realmente_finalizado(empate_post, agora_teste)
    assert payload_jogo(empate_post)["status"] == "Encerrado"
    empate_pre = dict(empate_post, estado="pre")
    assert not evento_realmente_finalizado(empate_pre, agora_teste)

    tabela_teste = {
        "tabela": [
            {"time": clube, "jogos": 0, "pontos": 0, "vitorias": 0, "empates": 0,
             "derrotas": 0, "gp": 0, "gc": 0}
            for clube in CANONICOS
        ]
    }
    resultados_teste = {
        "resultados": [{
            "event_id": "sync-1",
            "mandante": {"nome": "Botafogo"},
            "visitante": {"nome": "Vitória"},
            "placar_mandante": 0,
            "placar_visitante": 0,
        }]
    }
    por_time = {item["time"]: item for item in tabela_teste["tabela"]}
    for clube in ("Botafogo", "Vitória"):
        por_time[clube].update({"jogos": 1, "pontos": 1, "empates": 1})
    assert diagnosticar_sincronia_tabela_resultados(tabela_teste, resultados_teste) == []
    por_time["Botafogo"]["jogos"] = 2
    divergencias = diagnosticar_sincronia_tabela_resultados(tabela_teste, resultados_teste)
    assert any(item["clube"] == "Botafogo" and item["campo"] == "jogos" for item in divergencias)

    # Uma fonte auxiliar comum não pode trocar resultado ESPN finalizado; a CBF,
    # como autoridade oficial, pode oferecê-lo à auditoria transacional. A troca
    # só será efetivada posteriormente se reduzir as divergências da tabela.
    final_espn = {
        "event_id": "sync-final",
        "mandante_nome": "Botafogo",
        "visitante_nome": "Vitória",
        "data_dt": agora_teste - timedelta(hours=4),
        "_sort": (agora_teste - timedelta(hours=4)).timestamp(),
        "placar_mandante": 1,
        "placar_visitante": 0,
        "estado": "post",
        "concluido": True,
        "status": "Encerrado",
    }
    divergencias_times = [{"clube": "Botafogo", "campo": "pontos"}, {"clube": "Vitória", "campo": "pontos"}]
    assert _eventos_candidatos_fallback([final_espn], divergencias_times) == []
    assert _eventos_candidatos_fallback(
        [final_espn], divergencias_times, permitir_finalizados_espn=True
    ) == [final_espn]
    print("Selftest Execução 6 e sincronização cruzada OK")


def main() -> None:
    anteriores, snapshot_anterior_em = carregar_snapshot_eventos_anterior()
    ultima_falha = ""

    for tentativa in range(1, MAX_TENTATIVAS_SINCRONIA + 1):
        print(f"== COLETA SINCRONIZADA {tentativa}/{MAX_TENTATIVAS_SINCRONIA} ==")
        try:
            tabela = gerar_tabela()
            validar_contra_ranking(tabela)
            eventos_brutos = buscar_eventos_scoreboard()
            eventos_normalizados = normalizar_eventos_scoreboard(eventos_brutos)
            aplicar_transmissoes_manuais(eventos_normalizados)
            if not eventos_normalizados:
                raise RuntimeError("Nenhum evento ESPN foi normalizado; mantendo snapshot anterior.")

            jogos, resultados, eventos_json, discrepancias = avaliar_eventos_normalizados(
                eventos_normalizados, tabela, anteriores, snapshot_anterior_em
            )

            if discrepancias:
                print(
                    "::warning::Scoreboard principal divergente da tabela: "
                    + resumir_discrepancias(discrepancias)
                )

                # 1) A própria ESPN continua prioritária: tenta o summary individual.
                eventos_normalizados, jogos, resultados, eventos_json, discrepancias, _ = tentar_fallback_transacional(
                    eventos_normalizados,
                    tabela,
                    anteriores,
                    snapshot_anterior_em,
                    discrepancias,
                    "ESPN summary",
                    aplicar_resumos_alternativos_espn,
                )

            if discrepancias:
                # 2) Autoridade esportiva oficial: resultado/tabela da CBF.
                eventos_normalizados, jogos, resultados, eventos_json, discrepancias, _ = tentar_fallback_transacional(
                    eventos_normalizados,
                    tabela,
                    anteriores,
                    snapshot_anterior_em,
                    discrepancias,
                    "CBF",
                    aplicar_resultados_cbf,
                )

            if discrepancias:
                # 3) API auxiliar opcional, só quando key + league id estiverem configurados.
                eventos_normalizados, jogos, resultados, eventos_json, discrepancias, _ = tentar_fallback_transacional(
                    eventos_normalizados,
                    tabela,
                    anteriores,
                    snapshot_anterior_em,
                    discrepancias,
                    "API-Football",
                    aplicar_resultados_api_football,
                )

            if discrepancias:
                # 4) Última trava: override manual explícito, versionado e auditável.
                eventos_normalizados, jogos, resultados, eventos_json, discrepancias, _ = tentar_fallback_transacional(
                    eventos_normalizados,
                    tabela,
                    anteriores,
                    snapshot_anterior_em,
                    discrepancias,
                    "override manual",
                    lambda itens, _disc: aplicar_resultados_manuais(itens),
                )

            if not discrepancias:
                fallbacks = listar_fallbacks_eventos(eventos_normalizados)
                gravar_json_atomico("tabela.json", tabela)
                gravar_json_atomico("jogos.json", jogos)
                gravar_json_atomico("resultados.json", resultados)
                gravar_json_atomico("espn_eventos.json", eventos_json)

                fontes = sorted({item.get("fonte") for item in fallbacks if item.get("fonte")})
                if fallbacks:
                    motivo = (
                        "snapshot auditado e publicado; ESPN permaneceu principal e "
                        "foram usadas fontes complementares: " + ", ".join(fontes)
                    )
                    status = "aviso"
                else:
                    motivo = "standings e scoreboard ESPN descrevem o mesmo estado esportivo"
                    status = "ok"

                escrever_outputs_github(
                    sincronizado=True,
                    motivo=motivo,
                    tentativas=tentativa,
                    status=status,
                    fallbacks=fallbacks,
                )
                print("== ARQUIVOS GERADOS ==")
                print(f"  tabela.json        {len(tabela['tabela'])} times, fonte principal ESPN")
                print(f"  jogos.json         {len(jogos['jogos'])} próximos jogos")
                print(f"  resultados.json    {len(resultados['resultados'])} resultados")
                print(f"  espn_eventos.json  {len(eventos_json['eventos'])} eventos")
                if fallbacks:
                    for item in fallbacks:
                        print(
                            "  FALLBACK: "
                            f"{item.get('jogo')} {item.get('placar')} — {item.get('fonte')}"
                        )
                print("Concluído com auditoria resultados x tabela aprovada.")
                return

            ultima_falha = (
                "fontes ainda fora de sincronia após a cadeia ESPN -> CBF -> "
                "API-Football opcional -> override manual: "
                + resumir_discrepancias(discrepancias)
            )
            print(f"::warning::{ultima_falha}")
        except Exception as exc:  # noqa: BLE001
            if not erro_transitorio_de_fonte(exc):
                print(f"ERRO FATAL: {type(exc).__name__}: {exc}")
                escrever_outputs_github(
                    sincronizado=False,
                    motivo=str(exc),
                    tentativas=tentativa,
                    status="erro",
                )
                sys.exit(1)
            ultima_falha = f"fonte temporariamente indisponível: {type(exc).__name__}: {exc}"
            print(f"::warning::{ultima_falha}")

        if tentativa < MAX_TENTATIVAS_SINCRONIA:
            espera = ESPERA_SINCRONIA_SEGUNDOS * tentativa
            print(f"Aguardando {espera}s antes de repetir a coleta completa...")
            time.sleep(espera)

    anterior_ok, diagnostico_anterior = snapshot_local_sincronizado()
    if anterior_ok:
        motivo = f"{ultima_falha}. {diagnostico_anterior}; nenhum arquivo foi sobrescrito"
        escrever_outputs_github(
            sincronizado=False,
            motivo=motivo,
            tentativas=MAX_TENTATIVAS_SINCRONIA,
            status="preservado",
        )
        print(f"::warning::{motivo}")
        print("Coleta encerrada com segurança: último snapshot íntegro preservado.")
        return

    motivo = f"{ultima_falha}. Não foi possível preservar dados: {diagnostico_anterior}"
    escrever_outputs_github(
        sincronizado=False,
        motivo=motivo,
        tentativas=MAX_TENTATIVAS_SINCRONIA,
        status="erro",
    )
    print(f"ERRO FATAL: {motivo}")
    sys.exit(1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest_execucao_6()
    else:
        main()

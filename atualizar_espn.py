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
  3. Tabela e resultados só são gravados quando descrevem exatamente o mesmo
     estado esportivo. Se o standings estiver provisoriamente contaminado por
     jogos ao vivo, a classificação é avançada de forma transacional a partir
     do último snapshot íntegro, aplicando somente novos resultados finais
     confirmados pela ESPN. Qualquer alteração retroativa continua bloqueada.
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
    buscar_agenda_cbf,
    buscar_tabela_detalhada_cbf,
    fetch_api_football_fixtures,
    localizar_agenda_cbf,
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

# O scoreboard passa a ser consultado de forma incremental. O snapshot local
# consolidado é a fonte do histórico; cada execução atualiza apenas uma janela
# móvel capaz de cobrir correções recentes, partidas ao vivo e agenda futura.
ESPN_JANELA_PASSADO_DIAS = max(14, int(os.environ.get("ESPN_JANELA_PASSADO_DIAS", "45")))
ESPN_JANELA_FUTURO_DIAS = max(30, int(os.environ.get("ESPN_JANELA_FUTURO_DIAS", "75")))
ESPN_BLOCO_COMPLETO_DIAS = max(28, min(120, int(os.environ.get("ESPN_BLOCO_COMPLETO_DIAS", "112"))))
ESPN_VARREDURA_COMPLETA_INTERVALO_DIAS = max(0, int(os.environ.get("ESPN_VARREDURA_COMPLETA_INTERVALO_DIAS", "7")))
ESPN_HORA_VARREDURA_COMPLETA_BRT = max(0, min(23, int(os.environ.get("ESPN_HORA_VARREDURA_COMPLETA_BRT", "3"))))
URL_RESUMO_EVENTO = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary"
ARQ_AJUSTES_CALENDARIO = Path("dados-br/ajustes-calendario.json")
ARQ_CALENDARIO_CANONICO = Path("dados-br/calendario-completo.json")
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


def _env_bool(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return str(valor).strip().lower() in {"1", "true", "yes", "sim", "on"}


def fetch_json(
    url: str,
    timeout: int = 25,
    tentativas: int = 3,
    *,
    cache_bust: bool = False,
) -> dict[str, Any]:
    """Busca JSON ESPN com transporte resistente a bloqueios de runner.

    O site irmão já instalava ``curl-cffi`` no GitHub Actions, mas este coletor
    continuava usando apenas ``urllib``. Em runners compartilhados a ESPN passou
    a responder 403 ao urllib, deixando o snapshot congelado mesmo enquanto o
    navegador conseguia ler o placar ao vivo.

    A lógica agora é a mesma usada no Fórmula do Gol: tenta primeiro curl-cffi
    com fingerprint real de Chrome e, de forma independente, mantém urllib como
    fallback. O parâmetro ``cache_bust`` continua aceito por compatibilidade; o
    cliente Chrome usa uma URL fresca em toda tentativa para não reaproveitar
    uma resposta 403 intermediária do edge da ESPN.
    """
    ultimo: Exception | None = None
    tentativas = max(1, int(tentativas))
    for i in range(1, tentativas + 1):
        sep = "&" if "?" in url else "?"
        # O caminho curl usa sempre uma URL fresca, como no Fórmula do Gol.
        curl_url = f"{url}{sep}_={int(time.time())}"
        urllib_url = curl_url if cache_bust else url
        erros: list[str] = []

        try:
            from curl_cffi import requests as curl_requests  # type: ignore

            response = curl_requests.get(
                curl_url,
                impersonate="chrome",
                timeout=timeout + 8 * (i - 1),
                headers={
                    "Accept": HEADERS["Accept"],
                    "Accept-Language": HEADERS["Accept-Language"],
                    "Cache-Control": HEADERS["Cache-Control"],
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"resposta JSON não é objeto: {type(payload).__name__}")
            return payload
        except ImportError as exc:
            erros.append(f"curl_cffi=indisponível: {exc}")
        except Exception as exc:  # noqa: BLE001
            erros.append(f"curl_cffi={type(exc).__name__}: {exc}")
            ultimo = exc

        try:
            req = urllib.request.Request(urllib_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout + 10 * (i - 1)) as r:
                charset = r.headers.get_content_charset() or "utf-8"
                bruto = r.read().decode(charset, errors="replace")
                payload = json.loads(bruto)
                if not isinstance(payload, dict):
                    raise ValueError(f"resposta JSON não é objeto: {type(payload).__name__}")
                return payload
        except Exception as exc:  # noqa: BLE001
            erros.append(f"urllib={type(exc).__name__}: {exc}")
            ultimo = RuntimeError(" | ".join(erros))
            print(f"  tentativa {i}/{tentativas} falhou: {ultimo}")
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
def limites_temporada() -> tuple[datetime, datetime]:
    return (
        datetime(TEMPORADA, 1, 1, tzinfo=timezone.utc),
        datetime(TEMPORADA, 12, 31, 23, 59, tzinfo=timezone.utc),
    )


def periodo_incremental(agora_utc: datetime | None = None) -> tuple[datetime, datetime]:
    inicio_temporada, fim_temporada = limites_temporada()
    agora = agora_utc or datetime.now(timezone.utc)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)
    agora = agora.astimezone(timezone.utc)
    inicio = max(inicio_temporada, agora - timedelta(days=ESPN_JANELA_PASSADO_DIAS))
    fim = min(fim_temporada, agora + timedelta(days=ESPN_JANELA_FUTURO_DIAS))
    return inicio, fim


def datas_url(inicio: datetime, fim: datetime) -> str:
    return f"{inicio.strftime('%Y%m%d')}-{fim.strftime('%Y%m%d')}"


def carregar_payload_eventos_anterior() -> dict[str, Any]:
    caminho = Path("espn_eventos.json")
    if not caminho.exists():
        return {}
    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ultima_varredura_completa(payload_anterior: dict[str, Any]) -> datetime | None:
    coleta = payload_anterior.get("coleta") or {}
    valor = coleta.get("ultima_varredura_completa_em") if isinstance(coleta, dict) else None
    # Snapshots produzidos pela versão antiga eram, por definição, varreduras
    # desde janeiro. Assim a primeira execução após o upgrade não força nova
    # coleta completa e já entra no modo incremental.
    return parse_iso_brt(valor or payload_anterior.get("atualizado_em"))


def decidir_modo_scoreboard(
    payload_anterior: dict[str, Any],
    agora: datetime | None = None,
) -> tuple[str, str]:
    if _env_bool("ESPN_COLETA_COMPLETA"):
        return "completa", "solicitada explicitamente"
    eventos_anteriores = payload_anterior.get("eventos") or []
    if not eventos_anteriores:
        return "completa", "snapshot histórico inexistente"
    intervalo = ESPN_VARREDURA_COMPLETA_INTERVALO_DIAS
    if intervalo <= 0:
        return "incremental", "varredura completa automática desativada"
    agora_brasilia = (agora or agora_brt()).astimezone(FUSO_BRASILIA)
    ultima = _ultima_varredura_completa(payload_anterior)
    vencida = ultima is None or agora_brasilia - ultima >= timedelta(days=intervalo)
    if vencida and agora_brasilia.hour == ESPN_HORA_VARREDURA_COMPLETA_BRT:
        return "completa", f"manutenção periódica após {intervalo} dias"
    return "incremental", "janela móvel operacional"


def _buscar_eventos_periodo(
    inicio: datetime,
    fim: datetime,
    *,
    bloco_dias: int,
) -> list[dict[str, Any]]:
    eventos_por_id: dict[str, dict[str, Any]] = {}
    cursor = inicio
    chamadas = 0
    while cursor <= fim:
        proximo = min(cursor + timedelta(days=max(1, bloco_dias) - 1), fim)
        url = f"{URL_SCOREBOARD}?dates={datas_url(cursor, proximo)}&limit=200"
        print(f"Fonte: {url}")
        # Uma tentativa por URL. A repetição sincronizada externa já possui
        # backoff longo e evita tempestade de chamadas quando o IP recebe 403.
        data = fetch_json(url, timeout=30, tentativas=1)
        chamadas += 1
        eventos = data.get("events") or []
        if not isinstance(eventos, list):
            raise RuntimeError(f"scoreboard inválido em {datas_url(cursor, proximo)}: campo events não é lista")
        for ev in eventos:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("id") or "")
            if eid:
                eventos_por_id[eid] = ev
        cursor = proximo + timedelta(days=1)
    print(f"Chamadas ao scoreboard: {chamadas}; eventos brutos recebidos: {len(eventos_por_id)}")
    if not eventos_por_id:
        raise RuntimeError("A ESPN não retornou eventos para a janela consultada; mantendo JSONs anteriores.")
    return list(eventos_por_id.values())


def buscar_eventos_scoreboard() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    print("== EVENTOS/JOGOS/RESULTADOS (ESPN scoreboard incremental) ==")
    payload_anterior = carregar_payload_eventos_anterior()
    agora_utc = datetime.now(timezone.utc)
    modo, motivo = decidir_modo_scoreboard(payload_anterior, agora_brt())
    inicio_temporada, fim_temporada = limites_temporada()
    inicio_incremental, fim_incremental = periodo_incremental(agora_utc)
    ultima_completa = _ultima_varredura_completa(payload_anterior)

    modo_executado = modo
    if modo == "completa":
        print(f"Modo solicitado: COMPLETO ({motivo}).")
        try:
            eventos = _buscar_eventos_periodo(
                inicio_temporada, fim_temporada, bloco_dias=ESPN_BLOCO_COMPLETO_DIAS
            )
            ultima_completa = agora_brt()
            inicio_usado, fim_usado = inicio_temporada, fim_temporada
        except Exception as exc:  # noqa: BLE001
            if not (payload_anterior.get("eventos") or []):
                raise
            print(
                "::warning::Varredura completa indisponível; retomando a atualização "
                f"incremental sem perder o histórico: {type(exc).__name__}: {exc}"
            )
            modo_executado = "incremental-fallback"
            eventos = _buscar_eventos_periodo(
                inicio_incremental, fim_incremental,
                bloco_dias=(fim_incremental - inicio_incremental).days + 1,
            )
            inicio_usado, fim_usado = inicio_incremental, fim_incremental
    else:
        print(f"Modo: INCREMENTAL ({motivo}).")
        eventos = _buscar_eventos_periodo(
            inicio_incremental, fim_incremental,
            bloco_dias=(fim_incremental - inicio_incremental).days + 1,
        )
        inicio_usado, fim_usado = inicio_incremental, fim_incremental

    coleta = {
        "modo": modo_executado,
        "janela_inicio": inicio_usado.strftime("%Y-%m-%d"),
        "janela_fim": fim_usado.strftime("%Y-%m-%d"),
        "eventos_recebidos": len(eventos),
        "ultima_varredura_completa_em": (
            ultima_completa.replace(microsecond=0).isoformat() if ultima_completa else ""
        ),
    }
    return eventos, coleta


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
    # HOTFIX_REAGENDADOS_20260902
    # "adiado" é estado operacional atual, não histórico eterno.
    ajustes = carregar_ajustes_calendario()
    if not ajustes:
        return

    aplicados = 0
    obsoletos = 0
    for ajuste in ajustes:
        event_id = str(ajuste.get("event_id") or "").strip()
        mand = para_canonico(ajuste.get("mandante"))
        vis = para_canonico(ajuste.get("visitante"))
        alvo = None
        for e in eventos:
            bate_id = bool(event_id and str(e.get("event_id") or "") == event_id)
            bate_jogo = bool(
                mand and vis
                and e.get("mandante_nome") == mand
                and e.get("visitante_nome") == vis
            )
            if bate_id or bate_jogo:
                alvo = e
                break

        if alvo is None:
            print(
                "Aviso: ajuste de calendário não encontrou evento: "
                f"{event_id or (mand + ' x ' + vis if mand and vis else '?')}"
            )
            continue

        fonte_finalizada = bool(
            alvo.get("concluido") is True
            or str(alvo.get("estado") or "").lower() == "post"
        )

        rodada = ajuste.get("rodada")
        if rodada not in (None, ""):
            alvo["rodada"] = int(rodada)

        for campo in ("estadio", "transmissao"):
            if campo in ajuste and ajuste[campo]:
                alvo[campo] = ajuste[campo]

        fonte_tem_kickoff_ativo = bool(
            isinstance(alvo.get("data_dt"), datetime)
            and alvo.get("data_definir") is not True
            and alvo.get("adiado") is not True
            and not fonte_finalizada
        )

        ajuste_operacional_aplicado = False

        if fonte_finalizada:
            # Fonte finalizada é soberana: não volta a ser "adiada".
            pass

        elif ajuste.get("data_definir") is True and fonte_tem_kickoff_ativo:
            # TBA manual antigo perde para kickoff novo e ativo da fonte.
            obsoletos += 1
            motivo_antigo = str(ajuste.get("motivo") or "").strip()
            if str(alvo.get("motivo_ajuste") or "").strip() == motivo_antigo:
                alvo["motivo_ajuste"] = ""
            alvo["ajuste_calendario"] = False
            print(
                "::notice::Ajuste manual TBA obsoleto ignorado; "
                f"fonte atual já confirmou {alvo.get('mandante_nome')} x "
                f"{alvo.get('visitante_nome')} em {alvo.get('data_iso')}."
            )
            continue

        elif ajuste.get("data_definir") is True:
            alvo["adiado"] = True
            alvo["data_definir"] = True
            alvo["data_iso"] = None
            alvo["data_dt"] = None
            alvo["_sort"] = float("inf")
            ajuste_operacional_aplicado = True

        elif ajuste.get("data_iso"):
            dt = _parse_data_manual_brt(ajuste.get("data_iso"))
            if not dt:
                raise RuntimeError(
                    f"Data manual inválida no ajuste {event_id}: {ajuste.get('data_iso')}"
                )
            alvo["adiado"] = False
            alvo["data_definir"] = False
            alvo["data_dt"] = dt
            alvo["data_iso"] = dt.strftime("%Y-%m-%dT%H:%M")
            alvo["_sort"] = dt.timestamp()
            ajuste_operacional_aplicado = True

        elif ajuste.get("adiado") is True:
            alvo["adiado"] = True
            ajuste_operacional_aplicado = True

        if not ajuste_operacional_aplicado:
            continue

        alvo["ajuste_calendario"] = True
        alvo["motivo_ajuste"] = str(ajuste.get("motivo") or "").strip()

        inicio_ajustado = alvo.get("data_dt")
        estado_manual_ainda_valido = (
            not isinstance(inicio_ajustado, datetime)
            or agora_brt() < inicio_ajustado - timedelta(minutes=15)
        )
        if estado_manual_ainda_valido:
            for campo in (
                "estado",
                "status",
                "placar_mandante",
                "placar_visitante",
                "concluido",
            ):
                if campo in ajuste:
                    alvo[campo] = ajuste[campo]

        aplicados += 1

    print(
        f"Ajustes de calendário aplicados: {aplicados}/{len(ajustes)}"
        + (f"; TBA obsoleto(s) ignorado(s): {obsoletos}" if obsoletos else "")
    )

def _status_interrompido(st: dict[str, Any], status_publico: str = "") -> bool:
    texto = " ".join(
        str(valor or "")
        for valor in (
            status_publico,
            st.get("name"),
            st.get("description"),
            st.get("detail"),
            st.get("shortDetail"),
        )
    ).lower()
    return bool(re.search(r"postpon|adiad|suspend|cancel", texto))


def _estado_scoreboard_seguro(
    estado_fonte: str,
    concluido: bool,
    dt_brt: datetime,
    st: dict[str, Any],
    status_publico: str,
    agora: datetime,
) -> tuple[str, bool]:
    """Normaliza sinais contraditórios da ESPN sem perder finais reais.

    Um ``state=post`` com ``completed=false`` só vira pós-jogo quando já
    transcorreram ao menos 90 minutos desde o início e não existe sinal de
    adiamento, suspensão ou cancelamento. Esta é a mesma regra usada com
    sucesso pelo coletor do Fórmula do Gol.
    """
    estado = str(estado_fonte or ("post" if concluido else "pre")).lower()
    interrompido = _status_interrompido(st, status_publico)
    if interrompido:
        return "pre", True
    if concluido:
        return "post", False
    if estado == "post" and dt_brt > agora - timedelta(minutes=90):
        return "pre", False
    return estado, False


def carregar_calendario_canonico_por_mando() -> dict[tuple[str, str], dict[str, Any]]:
    """Lê a matriz estrutural de 380 jogos indexada pelo mando."""
    try:
        payload = json.loads(ARQ_CALENDARIO_CANONICO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    jogos = payload.get("jogos") or payload.get("partidas") or []
    if not isinstance(jogos, list) or len(jogos) != 380:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in jogos:
        if not isinstance(raw, dict):
            continue
        home = para_canonico(raw.get("mandante"))
        away = para_canonico(raw.get("visitante"))
        rodada = int(raw.get("rodada") or 0)
        if home and away and home != away and 1 <= rodada <= 38:
            item = dict(raw)
            item["mandante"] = home
            item["visitante"] = away
            out[(home, away)] = item
    return out if len(out) == 380 else {}


def carregar_rodadas_canonicas_por_mando() -> dict[tuple[str, str], int]:
    """Corrige metadados ``week`` da ESPN pela estrutura real da competição."""
    return {
        key: int(item.get("rodada") or 0)
        for key, item in carregar_calendario_canonico_por_mando().items()
    }


def aplicar_rodadas_canonicas(eventos: list[dict[str, Any]]) -> int:
    mapa = carregar_rodadas_canonicas_por_mando()
    if not mapa:
        return 0
    alterados = 0
    for evento in eventos:
        home = str(evento.get("mandante_nome") or "")
        away = str(evento.get("visitante_nome") or "")
        rodada = mapa.get((home, away))
        if not rodada:
            continue
        anterior = int(evento.get("rodada") or 0)
        if anterior == rodada:
            continue
        if anterior:
            evento["rodada_corrigida_de"] = anterior
        evento["rodada"] = rodada
        motivo = str(evento.get("motivo_ajuste") or "").strip()
        nota = "rodada reconciliada pela matriz canônica de 380 jogos"
        evento["motivo_ajuste"] = f"{motivo}; {nota}".strip("; ") if motivo else nota
        alterados += 1
    return alterados


def complementar_eventos_futuros_cbf(eventos: list[dict[str, Any]], rows: list[Any]) -> int:
    """Restaura jogo futuro omitido pela ESPN somente quando CBF + matriz + ID conhecido concordam."""
    if not rows:
        return 0
    canon = carregar_calendario_canonico_por_mando()
    if not canon:
        return 0
    existentes = {(str(e.get("mandante_nome") or ""), str(e.get("visitante_nome") or "")) for e in eventos}
    agora = agora_brt()
    adicionados = 0
    for oficial in rows:
        matchup = (oficial.mandante, oficial.visitante)
        if matchup in existentes:
            continue
        base = canon.get(matchup)
        if not base:
            continue
        event_id = str(base.get("event_id") or "").strip()
        if not event_id:
            continue
        dt = parse_iso_brt(oficial.data_iso)
        if not dt or dt < agora - timedelta(hours=6):
            continue
        anterior = str(base.get("data_iso") or "")
        eventos.append({
            "event_id": event_id, "rodada": int(base.get("rodada") or 0),
            "data_dt": dt, "data_iso": dt.strftime("%Y-%m-%dT%H:%M"),
            "mandante_nome": oficial.mandante, "visitante_nome": oficial.visitante,
            "mandante": info_time(oficial.mandante), "visitante": info_time(oficial.visitante),
            "estadio": str(base.get("estadio") or ""), "transmissao": "",
            "status": "Pré-jogo", "estado": "pre", "concluido": False, "adiado": False,
            "data_definir": False, "placar_mandante": None, "placar_visitante": None,
            "_sort": dt.timestamp(), "fonte_evento": "CBF oficial + calendário canônico",
            "fonte_calendario": "CBF oficial — agenda de credenciamento",
            "origem_calendario": oficial.origem,
            "data_espn_original": anterior if anterior and anterior != oficial.data_iso else "",
        })
        existentes.add(matchup)
        adicionados += 1
    eventos.sort(key=lambda e: float(e.get("_sort") or 0))
    return adicionados



def aplicar_agenda_oficial_cbf(eventos: list[dict[str, Any]], rows: list[Any]) -> int:
    # HOTFIX_REAGENDADOS_20260902
    # Uma nova data oficial reativa operacionalmente o jogo.
    if not rows:
        return 0

    agora = agora_brt()
    alterados = 0

    for evento in eventos:
        estado_atual = str(evento.get("estado") or "").lower()
        if evento.get("concluido") is True or estado_atual == "post":
            continue

        home = str(evento.get("mandante_nome") or "")
        away = str(evento.get("visitante_nome") or "")
        oficial = localizar_agenda_cbf(rows, mandante=home, visitante=away)
        if not oficial:
            continue

        dt = parse_iso_brt(oficial.data_iso)
        if not dt or dt < agora - timedelta(hours=6):
            continue

        anterior = str(evento.get("data_iso") or "")
        novo = dt.strftime("%Y-%m-%dT%H:%M")
        estava_interrompido = bool(
            evento.get("adiado") is True
            or evento.get("data_definir") is True
            or _status_interrompido({}, str(evento.get("status") or ""))
        )

        mudou = bool(
            anterior != novo
            or evento.get("adiado") is True
            or evento.get("data_definir") is True
        )

        if anterior != novo and not str(evento.get("data_espn_original") or "").strip():
            evento["data_espn_original"] = anterior

        evento["data_iso"] = novo
        evento["data_dt"] = dt
        evento["_sort"] = dt.timestamp()
        evento["data_definir"] = False
        evento["adiado"] = False

        # Não rebaixa uma partida efetivamente ao vivo para pré-jogo.
        if estado_atual != "in":
            evento["estado"] = "pre"
            evento["concluido"] = False
            if estava_interrompido:
                evento["status"] = "Pré-jogo"
                mudou = True

        evento["fonte_calendario"] = "CBF oficial — agenda de credenciamento"
        evento["origem_calendario"] = oficial.origem

        if mudou:
            alterados += 1

    eventos.sort(key=lambda e: float(e.get("_sort") or 0))
    return alterados

def marcar_kickoffs_provisorios_espn(eventos: list[dict[str, Any]]) -> int:
    """Marca lotes futuros incompletos no mesmo timestamp como data a definir."""
    por_rodada: dict[int, list[dict[str, Any]]] = {}
    for evento in eventos:
        rodada = int(evento.get("rodada") or 0)
        if not (1 <= rodada <= 38):
            continue
        if evento.get("concluido") is True or str(evento.get("estado") or "").lower() == "post":
            continue
        if "CBF oficial" in str(evento.get("fonte_calendario") or ""):
            continue
        data_iso = str(evento.get("data_iso") or "").strip()
        if not data_iso or evento.get("data_definir") is True:
            continue
        por_rodada.setdefault(rodada, []).append(evento)
    alterados = 0
    for rodada, itens in por_rodada.items():
        datas = {str(e.get("data_iso") or "").strip() for e in itens}
        if not (4 <= len(itens) < 10 and len(datas) == 1):
            continue
        timestamp = next(iter(datas))
        for evento in itens:
            evento["data_definir"] = True
            evento.setdefault("data_fonte_anterior", evento.get("data_iso"))
            motivo = str(evento.get("motivo_ajuste") or "").strip()
            nota = f"kickoff ESPN provisório ({len(itens)} jogos da R{rodada} em {timestamp})"
            if nota not in motivo:
                evento["motivo_ajuste"] = f"{motivo}; {nota}".strip("; ") if motivo else nota
            alterados += 1
    return alterados


def normalizar_eventos_scoreboard(
    eventos: list[dict[str, Any]], *, finalizar: bool = True
) -> list[dict[str, Any]]:
    legadas = carregar_rodadas_legadas()
    normalizados: list[dict[str, Any]] = []
    nao_mapeados: list[str] = []
    agora = agora_brt()

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
        concluido = bool(st.get("completed") is True)
        status_publico = status_evento(ev).get("displayClock") or st.get("shortDetail") or st.get("detail") or ""
        estado, interrompido = _estado_scoreboard_seguro(
            str(st.get("state") or "pre"),
            concluido,
            dt_brt,
            st,
            status_publico,
            agora,
        )

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
            "status": status_publico,
            "estado": estado,
            "concluido": concluido,
            "adiado": interrompido,
            "placar_mandante": placar_competidor(casa),
            "placar_visitante": placar_competidor(fora),
            "data_definir": False,
            "_sort": dt_brt.timestamp(),
        })

    if nao_mapeados:
        print("Aviso: eventos ESPN com clubes fora do de-para foram ignorados:")
        for n in sorted(set(nao_mapeados)):
            print(f"  - {n}")

    normalizados.sort(key=lambda e: e["_sort"])
    if finalizar:
        return finalizar_eventos_normalizados(normalizados)
    return normalizados


def finalizar_eventos_normalizados(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eventos.sort(key=lambda e: float(e.get("_sort") or 0))
    inferir_rodadas_faltantes(eventos)
    corrigidas = aplicar_rodadas_canonicas(eventos)
    if corrigidas:
        print(f"Rodadas reconciliadas pela matriz canônica: {corrigidas}")
    aplicar_ajustes_calendario(eventos)
    return sanear_eventos_por_rodada(eventos)


def _evento_snapshot_para_normalizado(item: dict[str, Any]) -> dict[str, Any] | None:
    mandante = para_canonico(item.get("mandante"))
    visitante = para_canonico(item.get("visitante"))
    if not mandante or not visitante:
        return None
    dt = _parse_data_manual_brt(item.get("data_iso"))
    data_definir = bool(item.get("data_definir") is True)
    if dt is None and not data_definir:
        return None
    evento = {
        "event_id": str(item.get("event_id") or ""),
        "rodada": int(item.get("rodada") or 0),
        "data_dt": dt,
        "data_iso": dt.strftime("%Y-%m-%dT%H:%M") if dt else None,
        "mandante_nome": mandante,
        "visitante_nome": visitante,
        "mandante": info_time(mandante),
        "visitante": info_time(visitante),
        "estadio": str(item.get("estadio") or ""),
        "transmissao": str(item.get("transmissao") or ""),
        "status": str(item.get("status") or ""),
        "estado": str(item.get("estado") or "pre"),
        "concluido": bool(item.get("concluido") is True),
        "adiado": bool(item.get("adiado") is True),
        "placar_mandante": item.get("placar_mandante"),
        "placar_visitante": item.get("placar_visitante"),
        "data_definir": data_definir,
        "_sort": dt.timestamp() if dt else float("inf"),
    }
    for campo in (
        "finalizado_em", "rodada_corrigida_de", "motivo_ajuste",
        "fonte_calendario", "origem_calendario", "data_espn_original", "data_fonte_anterior", "fonte_evento",
        "resultado_manual", "resultado_fallback", "fonte_resultado",
        "origem_resultado", "motivo_fallback", "motivo_resultado_manual",
    ):
        if campo in item:
            evento[campo] = item.get(campo)
    if data_definir or item.get("motivo_ajuste"):
        evento["ajuste_calendario"] = True
    return evento


def _chave_confronto(evento: dict[str, Any]) -> tuple[str, str] | None:
    mandante = str(evento.get("mandante_nome") or "").strip()
    visitante = str(evento.get("visitante_nome") or "").strip()
    return (mandante, visitante) if mandante and visitante else None


def mesclar_eventos_incrementais(
    eventos_atualizados: list[dict[str, Any]],
    payload_anterior: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Consolida a janela nova sobre o histórico sem apagar partidas antigas.

    O confronto mandante–visitante é a identidade esportiva estável de cada jogo
    no turno/returno. Ele também elimina duplicidade quando a ESPN troca o
    ``event_id`` de uma partida reagendada. Campos editoriais vazios da resposta
    nova (estádio/transmissão) herdam o valor íntegro anterior.
    """
    payload = payload_anterior if payload_anterior is not None else carregar_payload_eventos_anterior()
    anteriores: list[dict[str, Any]] = []
    for item in payload.get("eventos") or []:
        if isinstance(item, dict):
            convertido = _evento_snapshot_para_normalizado(item)
            if convertido:
                anteriores.append(convertido)

    consolidados: dict[tuple[str, str] | tuple[str, str, str], dict[str, Any]] = {}
    chave_por_id: dict[str, tuple[str, str] | tuple[str, str, str]] = {}

    def registrar(evento: dict[str, Any], *, novo: bool) -> None:
        confronto = _chave_confronto(evento)
        event_id = str(evento.get("event_id") or "")
        chave: tuple[str, str] | tuple[str, str, str]
        if confronto:
            chave = confronto
        else:
            chave = ("event_id", event_id, "")

        anterior = consolidados.get(chave)
        if anterior is None and event_id and event_id in chave_por_id:
            chave_antiga = chave_por_id[event_id]
            anterior = consolidados.pop(chave_antiga, None)
        if novo and anterior:
            if not evento.get("rodada") and anterior.get("rodada"):
                evento["rodada"] = anterior["rodada"]
            for campo in ("estadio", "transmissao"):
                if not evento.get(campo) and anterior.get(campo):
                    evento[campo] = anterior[campo]
        consolidados[chave] = evento
        if event_id:
            chave_por_id[event_id] = chave

    for evento in anteriores:
        registrar(evento, novo=False)
    for evento in eventos_atualizados:
        registrar(evento, novo=True)

    mesclados = finalizar_eventos_normalizados(list(consolidados.values()))
    stats = {
        "eventos_historicos": len(anteriores),
        "eventos_atualizados": len(eventos_atualizados),
        "eventos_consolidados": len(mesclados),
    }
    if anteriores and len(mesclados) < len(anteriores):
        print(
            "Aviso: saneamento consolidado reduziu o snapshot de "
            f"{len(anteriores)} para {len(mesclados)} eventos; validações transacionais continuam ativas."
        )
    return mesclados, stats


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



def _event_ids_forcados_summary() -> set[str]:
    """IDs que o orquestrador confirmou como FINAL e quer reconciliar já.

    O valor chega pelo FAST CORE como lista separada por vírgula/espaço. IDs
    desconhecidos são ignorados; o coletor nunca inventa confronto nem placar.
    """
    raw = str(os.environ.get("ESPN_FORCE_SUMMARY_EVENT_IDS") or "").strip()
    if not raw:
        return set()
    return {token for token in re.findall(r"\d+", raw) if token}


def _candidatos_summary_proativo(
    eventos: list[dict[str, Any]],
    *,
    agora: datetime | None = None,
    janela_horas: int = 12,
    limite: int = 12,
) -> list[dict[str, Any]]:
    """Seleciona jogos recentes ainda não finalizados para confirmação individual.

    O scoreboard agregado da ESPN pode ficar congelado/defasado mesmo quando o
    endpoint individual ``summary?event=...`` já publicou o FINAL. Antes desta
    rotina, o summary só era consultado quando standings x resultados divergiam;
    se AMBOS estivessem igualmente atrasados, nada disparava o fallback.

    IDs explicitamente enviados pelo orquestrador têm prioridade e não dependem
    da janela temporal. Para execução manual, jogos iniciados há pelo menos 75
    minutos e no máximo ``janela_horas`` também são verificados.
    """
    agora = agora or agora_brt()
    forcados = _event_ids_forcados_summary()
    candidatos: list[tuple[int, float, dict[str, Any]]] = []
    for evento in eventos:
        event_id = str(evento.get("event_id") or "").strip()
        if not event_id:
            continue
        if evento_realmente_finalizado(evento, agora):
            continue
        if evento.get("data_definir") is True:
            continue
        inicio = evento.get("data_dt")
        forçado = event_id in forcados
        recente = bool(
            isinstance(inicio, datetime)
            and agora - timedelta(hours=max(1, janela_horas)) <= inicio <= agora - timedelta(minutes=75)
        )
        if not (forçado or recente):
            continue
        # Forçados primeiro; dentro do grupo, o kickoff mais recente primeiro.
        sort_ts = float(inicio.timestamp()) if isinstance(inicio, datetime) else 0.0
        candidatos.append((0 if forçado else 1, -sort_ts, evento))
    candidatos.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidatos[: max(1, int(limite))]]


def aplicar_resumos_proativos_espn(
    eventos: list[dict[str, Any]],
    *,
    agora: datetime | None = None,
) -> int:
    """Confirma FINAL pelo endpoint individual ESPN sem depender de divergência.

    Esta é a via crítica do FAST CORE. Só promove um evento quando o summary
    individual confirma ``post/completed`` e o confronto (mandante/visitante)
    coincide com o snapshot canônico. Falha do summary não interrompe a coleta;
    o scoreboard/CBF continuam disponíveis como caminhos normais.
    """
    agora = agora or agora_brt()
    aplicados = 0
    candidatos = _candidatos_summary_proativo(eventos, agora=agora)
    if not candidatos:
        return 0
    for alvo in candidatos:
        event_id = str(alvo.get("event_id") or "").strip()
        try:
            payload = fetch_json(
                f"{URL_RESUMO_EVENTO}?event={urllib.parse.quote(event_id)}",
                timeout=20,
                tentativas=1,
                cache_bust=True,
            )
            bruto = _evento_bruto_do_summary(payload, event_id)
            if not bruto:
                continue
            normalizados = normalizar_eventos_scoreboard([bruto], finalizar=False)
            if not normalizados:
                continue
            resumo = normalizados[0]
            if not evento_realmente_finalizado(resumo, agora):
                continue
            if resumo.get("placar_mandante") is None or resumo.get("placar_visitante") is None:
                continue
            if (
                resumo.get("mandante_nome") != alvo.get("mandante_nome")
                or resumo.get("visitante_nome") != alvo.get("visitante_nome")
            ):
                print(
                    f"::warning::Summary ESPN {event_id} ignorado: confronto divergente "
                    f"({resumo.get('mandante_nome')} x {resumo.get('visitante_nome')})."
                )
                continue
            antes = (
                alvo.get("placar_mandante"), alvo.get("placar_visitante"),
                alvo.get("estado"), alvo.get("concluido"),
            )
            _aplicar_placar_complementar(
                alvo,
                placar_mandante=int(resumo["placar_mandante"]),
                placar_visitante=int(resumo["placar_visitante"]),
                fonte="ESPN summary",
                origem=f"{URL_RESUMO_EVENTO}?event={event_id}",
                motivo=(
                    "FINAL confirmado proativamente no summary individual da ESPN; "
                    "não depende da atualização do scoreboard agregado."
                ),
                status=str(resumo.get("status") or "Encerrado"),
            )
            depois = (
                alvo.get("placar_mandante"), alvo.get("placar_visitante"),
                alvo.get("estado"), alvo.get("concluido"),
            )
            if antes != depois:
                aplicados += 1
                print(
                    f"FINAL proativo ESPN: {alvo.get('mandante_nome')} "
                    f"{alvo.get('placar_mandante')} x {alvo.get('placar_visitante')} "
                    f"{alvo.get('visitante_nome')} (event_id={event_id})"
                )
        except Exception as exc:  # noqa: BLE001
            print(
                f"::warning::Summary ESPN proativo indisponível para {event_id}: "
                f"{type(exc).__name__}: {exc}"
            )
    if aplicados:
        print(f"Resultados recuperados proativamente pelo summary ESPN: {aplicados}")
    return aplicados


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
    payload = carregar_payload_eventos_anterior()
    eventos = {
        str(item.get("event_id") or ""): item
        for item in (payload.get("eventos") or [])
        if isinstance(item, dict) and item.get("event_id")
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
        if not evento_realmente_finalizado(e, agora):
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
    futuro. Por isso a data também precisa estar no passado com margem de
    segurança.

    ``adiado=True`` registra também partidas que foram reagendadas e depois
    disputadas. Ele não pode, sozinho, anular um resultado final. Adiamentos
    ainda ativos já chegam normalizados com ``estado=pre`` e continuam fora do
    resultados.json pela checagem de estado abaixo.
    """
    if (
        e.get("placar_mandante") is None
        or e.get("placar_visitante") is None
    ):
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
                "fonte_calendario": e.get("fonte_calendario", ""),
                "origem_calendario": e.get("origem_calendario", ""),
                "data_espn_original": e.get("data_espn_original", ""),
                "data_fonte_anterior": e.get("data_fonte_anterior", ""),
                "fonte_evento": e.get("fonte_evento", ""),
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


def _resultado_por_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    itens = payload.get("resultados")
    if not isinstance(itens, list):
        return None
    saida: dict[str, dict[str, Any]] = {}
    for item in itens:
        event_id = str(item.get("event_id") or "").strip()
        if not event_id or event_id in saida:
            return None
        saida[event_id] = item
    return saida


def _assinatura_resultado(item: dict[str, Any]) -> tuple[Any, ...]:
    mandante_bruto = item.get("mandante")
    visitante_bruto = item.get("visitante")
    mandante_nome = mandante_bruto.get("nome") if isinstance(mandante_bruto, dict) else mandante_bruto
    visitante_nome = visitante_bruto.get("nome") if isinstance(visitante_bruto, dict) else visitante_bruto
    return (
        para_canonico(mandante_nome, item.get("mandante_nome")),
        para_canonico(visitante_nome, item.get("visitante_nome")),
        int(item.get("placar_mandante")),
        int(item.get("placar_visitante")),
    )


def reconstruir_tabela_incremental(
    tabela_anterior: dict[str, Any],
    resultados_anteriores: dict[str, Any],
    resultados_atuais: dict[str, Any],
) -> tuple[dict[str, Any] | None, int, str]:
    """Avança uma tabela íntegra aplicando apenas resultados finais novos.

    Essa rota existe para a janela em que o standings da ESPN já incorpora
    placares ao vivo, enquanto o scoreboard distingue corretamente partidas
    encerradas das que ainda estão em andamento. O histórico anterior precisa
    permanecer integralmente presente e imutável; remoção ou alteração de
    resultado bloqueia a reconstrução.
    """
    if diagnosticar_sincronia_tabela_resultados(tabela_anterior, resultados_anteriores):
        return None, 0, "snapshot anterior não fecha com seus próprios resultados"

    anteriores = _resultado_por_id(resultados_anteriores)
    atuais = _resultado_por_id(resultados_atuais)
    if anteriores is None or atuais is None:
        return None, 0, "coleção de resultados inválida ou com event_id duplicado"

    ids_anteriores = set(anteriores)
    ids_atuais = set(atuais)
    if not ids_anteriores.issubset(ids_atuais):
        return None, 0, "a coleta atual removeu resultados já publicados"

    for event_id in ids_anteriores:
        try:
            assinatura_anterior = _assinatura_resultado(anteriores[event_id])
            assinatura_atual = _assinatura_resultado(atuais[event_id])
        except (TypeError, ValueError):
            return None, 0, f"placar inválido no resultado histórico {event_id}"
        if assinatura_anterior != assinatura_atual:
            return None, 0, f"resultado histórico {event_id} foi alterado"

    novos_ids = ids_atuais - ids_anteriores
    if not novos_ids:
        return None, 0, "nenhum resultado final novo para aplicar"

    linhas_anteriores = tabela_anterior.get("tabela")
    if not isinstance(linhas_anteriores, list):
        return None, 0, "tabela anterior inválida"
    linhas = {str(item.get("time") or ""): copy.deepcopy(item) for item in linhas_anteriores}
    if set(linhas) != set(CANONICOS):
        return None, 0, "tabela anterior não contém os 20 clubes canônicos"

    for event_id in sorted(novos_ids, key=lambda chave: str(atuais[chave].get("data_iso") or "")):
        item = atuais[event_id]
        try:
            mandante, visitante, gols_mandante, gols_visitante = _assinatura_resultado(item)
        except (TypeError, ValueError):
            return None, 0, f"placar inválido no novo resultado {event_id}"
        if mandante not in linhas or visitante not in linhas or mandante == visitante:
            return None, 0, f"confronto inválido no novo resultado {event_id}"

        casa = linhas[mandante]
        fora = linhas[visitante]
        casa["jogos"] = int(casa.get("jogos") or 0) + 1
        fora["jogos"] = int(fora.get("jogos") or 0) + 1
        casa["gp"] = int(casa.get("gp") or 0) + gols_mandante
        casa["gc"] = int(casa.get("gc") or 0) + gols_visitante
        fora["gp"] = int(fora.get("gp") or 0) + gols_visitante
        fora["gc"] = int(fora.get("gc") or 0) + gols_mandante
        if gols_mandante > gols_visitante:
            casa["pontos"] = int(casa.get("pontos") or 0) + 3
            casa["vitorias"] = int(casa.get("vitorias") or 0) + 1
            fora["derrotas"] = int(fora.get("derrotas") or 0) + 1
        elif gols_mandante < gols_visitante:
            fora["pontos"] = int(fora.get("pontos") or 0) + 3
            fora["vitorias"] = int(fora.get("vitorias") or 0) + 1
            casa["derrotas"] = int(casa.get("derrotas") or 0) + 1
        else:
            casa["pontos"] = int(casa.get("pontos") or 0) + 1
            fora["pontos"] = int(fora.get("pontos") or 0) + 1
            casa["empates"] = int(casa.get("empates") or 0) + 1
            fora["empates"] = int(fora.get("empates") or 0) + 1

    posicao_anterior = {
        str(item.get("time") or ""): int(item.get("pos") or 999)
        for item in linhas_anteriores
    }
    ordenadas = list(linhas.values())
    for linha in ordenadas:
        linha["sg"] = int(linha.get("gp") or 0) - int(linha.get("gc") or 0)
        jogos = int(linha.get("jogos") or 0)
        pontos = int(linha.get("pontos") or 0)
        linha["aproveitamento"] = int(round(100.0 * pontos / (3 * jogos))) if jogos else 0
        linha.pop("pos", None)
    ordenadas.sort(key=lambda linha: (
        -int(linha.get("pontos") or 0),
        -int(linha.get("vitorias") or 0),
        -int(linha.get("sg") or 0),
        -int(linha.get("gp") or 0),
        posicao_anterior.get(str(linha.get("time") or ""), 999),
        str(linha.get("time") or ""),
    ))
    tabela = [{"pos": pos, **linha} for pos, linha in enumerate(ordenadas, 1)]
    candidato = {
        "atualizado_em": resultados_atuais.get("atualizado_em") or iso_agora_brt(),
        "fonte": "ESPN",
        "metodo_classificacao": "snapshot ESPN anterior + novos resultados finais ESPN",
        "standings_provisorio_ignorado": True,
        "resultados_finais_aplicados": len(novos_ids),
        "tabela": tabela,
    }
    discrepancias = diagnosticar_sincronia_tabela_resultados(candidato, resultados_atuais)
    if discrepancias:
        return None, 0, "classificação incremental não passou na auditoria: " + resumir_discrepancias(discrepancias)
    return candidato, len(novos_ids), ""


def tentar_tabela_transacional(resultados_atuais: dict[str, Any]) -> tuple[dict[str, Any] | None, int, str]:
    try:
        tabela_anterior = json.loads(Path("tabela.json").read_text(encoding="utf-8"))
        resultados_anteriores = json.loads(Path("resultados.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, 0, f"não foi possível carregar o snapshot anterior: {type(exc).__name__}: {exc}"
    return reconstruir_tabela_incremental(tabela_anterior, resultados_anteriores, resultados_atuais)


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
                    "adiado": True,
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
        assert evento["adiado"] is True
        assert (evento["placar_mandante"], evento["placar_visitante"]) == (2, 0)
        fim_teste = datetime(2026, 7, 18, 0, 0, tzinfo=FUSO_BRASILIA)
        assert evento_realmente_finalizado(evento, fim_teste)
        aplicar_finalizados_em(eventos, {}, None, fim_teste)
        assert evento.get("finalizado_em")

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
        "adiado": True,
    }
    assert evento_realmente_finalizado(empate_post, agora_teste)
    assert payload_jogo(empate_post)["status"] == "Encerrado"
    empate_pre = dict(empate_post, estado="pre")
    assert not evento_realmente_finalizado(empate_pre, agora_teste)
    assert _estado_scoreboard_seguro(
        "post",
        False,
        agora_teste - timedelta(minutes=20),
        {},
        "0'",
        agora_teste,
    ) == ("pre", False)
    assert _estado_scoreboard_seguro(
        "post",
        False,
        agora_teste - timedelta(minutes=112),
        {},
        "0'",
        agora_teste,
    ) == ("post", False)
    assert _estado_scoreboard_seguro(
        "post",
        False,
        agora_teste - timedelta(hours=3),
        {"description": "Postponed"},
        "Adiado",
        agora_teste,
    ) == ("pre", True)
    adiado_ativo = dict(
        empate_post,
        estado="pre",
        concluido=False,
        status="Adiado",
        finalizado_em="2026-07-23T21:00:00-03:00",
    )
    assert not evento_realmente_finalizado(adiado_ativo, agora_teste)
    aplicar_finalizados_em([adiado_ativo], {}, None, agora_teste)
    assert "finalizado_em" not in adiado_ativo

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

    # Regressão de 29/07/2026: quatro jogos terminaram enquanto o standings já
    # calculava partidas ainda ao vivo. Somente os resultados finais devem
    # avançar o snapshot anterior; nenhuma parcial ao vivo entra na tabela.
    tabela_base = {
        "fonte": "ESPN",
        "tabela": [
            {
                "pos": indice,
                "time": clube,
                "jogos": 0,
                "pontos": 0,
                "vitorias": 0,
                "empates": 0,
                "derrotas": 0,
                "gp": 0,
                "gc": 0,
                "sg": 0,
                "aproveitamento": 0,
            }
            for indice, clube in enumerate(CANONICOS, 1)
        ],
    }
    resultados_base = {"fonte": "ESPN", "resultados": []}
    resultados_finais = {
        "fonte": "ESPN",
        "atualizado_em": "2026-07-29T22:05:00-03:00",
        "resultados": [
            {
                "event_id": "401841170",
                "data_iso": "2026-07-29T19:30",
                "mandante": {"nome": "Mirassol"},
                "visitante": {"nome": "Remo"},
                "placar_mandante": 2,
                "placar_visitante": 1,
            },
            {
                "event_id": "401841171",
                "data_iso": "2026-07-29T19:30",
                "mandante": {"nome": "Internacional"},
                "visitante": {"nome": "Flamengo"},
                "placar_mandante": 1,
                "placar_visitante": 1,
            },
            {
                "event_id": "401841177",
                "data_iso": "2026-07-29T21:30",
                "mandante": {"nome": "Fluminense"},
                "visitante": {"nome": "Bahia"},
                "placar_mandante": 0,
                "placar_visitante": 0,
            },
            {
                "event_id": "401841172",
                "data_iso": "2026-07-29T21:30",
                "mandante": {"nome": "Vitória"},
                "visitante": {"nome": "Palmeiras"},
                "placar_mandante": 0,
                "placar_visitante": 4,
            },
        ],
    }
    tabela_incremental, aplicados, erro_incremental = reconstruir_tabela_incremental(
        tabela_base, resultados_base, resultados_finais
    )
    assert not erro_incremental and aplicados == 4 and tabela_incremental
    assert diagnosticar_sincronia_tabela_resultados(tabela_incremental, resultados_finais) == []
    incremental_por_time = {item["time"]: item for item in tabela_incremental["tabela"]}
    assert incremental_por_time["Mirassol"]["pontos"] == 3
    assert incremental_por_time["Remo"]["derrotas"] == 1
    assert incremental_por_time["Internacional"]["empates"] == 1
    assert incremental_por_time["Flamengo"]["pontos"] == 1
    assert incremental_por_time["Fluminense"]["empates"] == 1
    assert incremental_por_time["Bahia"]["pontos"] == 1
    assert incremental_por_time["Vitória"]["derrotas"] == 1
    assert incremental_por_time["Palmeiras"]["pontos"] == 3

    resultados_historicos = copy.deepcopy(resultados_finais)
    resultado_alterado = copy.deepcopy(resultados_finais)
    resultado_alterado["resultados"][0]["placar_mandante"] = 3
    bloqueada, _, motivo_bloqueio = reconstruir_tabela_incremental(
        tabela_incremental, resultados_historicos, resultado_alterado
    )
    assert bloqueada is None and "foi alterado" in motivo_bloqueio

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

    # Regressões da coleta incremental: uma execução operacional consulta uma
    # única janela, preserva o histórico e substitui uma partida reagendada
    # mesmo quando a ESPN troca o event_id.
    agora_utc = datetime(2026, 8, 5, 17, 22, tzinfo=timezone.utc)
    inicio_inc, fim_inc = periodo_incremental(agora_utc)
    assert inicio_inc.strftime("%Y-%m-%d") == "2026-06-21"
    assert fim_inc.strftime("%Y-%m-%d") == "2026-10-19"

    payload_incremental = {
        "atualizado_em": "2026-08-04T02:59:52-03:00",
        "eventos": [
            {
                "event_id": "historico-1", "rodada": 1,
                "data_iso": "2026-01-28T19:00",
                "mandante": "Atlético-MG", "visitante": "Palmeiras",
                "estadio": "Arena MRV", "transmissao": "",
                "status": "Encerrado", "estado": "post", "concluido": True,
                "placar_mandante": 2, "placar_visitante": 2,
                "adiado": False, "data_definir": False,
            },
            {
                "event_id": "agenda-antiga", "rodada": 22,
                "data_iso": "2026-08-10T20:00",
                "mandante": "Flamengo", "visitante": "Bahia",
                "estadio": "Maracanã", "transmissao": "Premiere",
                "status": "Agendado", "estado": "pre", "concluido": False,
                "placar_mandante": None, "placar_visitante": None,
                "adiado": False, "data_definir": False,
            },
        ],
    }
    data_nova = datetime(2026, 8, 11, 21, 30, tzinfo=FUSO_BRASILIA)
    evento_novo = {
        "event_id": "agenda-nova", "rodada": 0,
        "data_dt": data_nova, "data_iso": "2026-08-11T21:30",
        "mandante_nome": "Flamengo", "visitante_nome": "Bahia",
        "mandante": info_time("Flamengo"), "visitante": info_time("Bahia"),
        "estadio": "", "transmissao": "", "status": "Agendado",
        "estado": "pre", "concluido": False, "adiado": False,
        "placar_mandante": None, "placar_visitante": None,
        "data_definir": False, "_sort": data_nova.timestamp(),
    }
    consolidados, stats_incrementais = mesclar_eventos_incrementais(
        [evento_novo], payload_incremental
    )
    assert stats_incrementais == {
        "eventos_historicos": 2, "eventos_atualizados": 1, "eventos_consolidados": 2
    }
    ids_consolidados = {item.get("event_id") for item in consolidados}
    assert ids_consolidados == {"historico-1", "agenda-nova"}
    atualizado = next(item for item in consolidados if item.get("event_id") == "agenda-nova")
    rodada_canonica_teste = carregar_rodadas_canonicas_por_mando().get(("Flamengo", "Bahia"), 22)
    assert atualizado["rodada"] == rodada_canonica_teste
    if rodada_canonica_teste != 22:
        assert atualizado.get("rodada_corrigida_de") == 22
    assert atualizado["estadio"] == "Maracanã"
    assert atualizado["transmissao"] == "Premiere"

    env_completa = os.environ.pop("ESPN_COLETA_COMPLETA", None)
    try:
        modo, _ = decidir_modo_scoreboard(
            payload_incremental, datetime(2026, 8, 5, 14, 0, tzinfo=FUSO_BRASILIA)
        )
        assert modo == "incremental"
        payload_vencido = copy.deepcopy(payload_incremental)
        payload_vencido["coleta"] = {
            "ultima_varredura_completa_em": "2026-07-20T03:00:00-03:00"
        }
        modo, _ = decidir_modo_scoreboard(
            payload_vencido, datetime(2026, 8, 5, 3, 10, tzinfo=FUSO_BRASILIA)
        )
        assert modo == "completa"
        os.environ["ESPN_COLETA_COMPLETA"] = "true"
        assert decidir_modo_scoreboard(payload_incremental)[0] == "completa"
    finally:
        if env_completa is None:
            os.environ.pop("ESPN_COLETA_COMPLETA", None)
        else:
            os.environ["ESPN_COLETA_COMPLETA"] = env_completa

    # Kickoffs provisórios: lote futuro incompleto no mesmo timestamp não pode
    # virar horário confirmado. Rodada completa e jogo confirmado pela CBF não
    # são rebaixados.
    provis = []
    for i in range(7):
        dtp = datetime(2026, 9, 5, 15, 0, tzinfo=FUSO_BRASILIA)
        provis.append({
            "event_id": f"prov-{i}", "rodada": 26, "data_iso": "2026-09-05T15:00",
            "data_dt": dtp, "_sort": dtp.timestamp(), "mandante_nome": f"M{i}",
            "visitante_nome": f"V{i}", "estado": "pre", "concluido": False,
            "data_definir": False, "fonte_calendario": "ESPN",
        })
    assert marcar_kickoffs_provisorios_espn(provis) == 7
    assert all(x.get("data_definir") is True for x in provis)
    confirm = copy.deepcopy(provis[:1])
    confirm[0]["data_definir"] = False
    confirm[0]["fonte_calendario"] = "CBF oficial — agenda de credenciamento"
    assert marcar_kickoffs_provisorios_espn(confirm) == 0
    assert confirm[0]["data_definir"] is False


    # HOTFIX_REAGENDADOS_20260902 — regressões permanentes.
    # 1) TBA manual antigo não pode apagar kickoff novo/ativo da ESPN.
    ajustes_original = globals()["carregar_ajustes_calendario"]
    try:
        futuro_ativo = agora_brt() + timedelta(days=2)
        globals()["carregar_ajustes_calendario"] = lambda: [{
            "event_id": "id-antigo",
            "rodada": 4,
            "mandante": "Flamengo",
            "visitante": "Mirassol",
            "data_definir": True,
            "estado": "pre",
            "concluido": False,
            "status": "Data a definir",
            "motivo": "TBA antigo de teste",
        }]
        reagendado_espn = [{
            "event_id": "id-novo",
            "rodada": 4,
            "mandante_nome": "Flamengo",
            "visitante_nome": "Mirassol",
            "data_dt": futuro_ativo,
            "data_iso": futuro_ativo.strftime("%Y-%m-%dT%H:%M"),
            "_sort": futuro_ativo.timestamp(),
            "estado": "pre",
            "concluido": False,
            "adiado": False,
            "data_definir": False,
            "status": "0'",
        }]
        aplicar_ajustes_calendario(reagendado_espn)
        assert reagendado_espn[0]["data_iso"] == futuro_ativo.strftime("%Y-%m-%dT%H:%M")
        assert reagendado_espn[0]["adiado"] is False
        assert reagendado_espn[0]["data_definir"] is False
        assert reagendado_espn[0]["status"] == "0'"
    finally:
        globals()["carregar_ajustes_calendario"] = ajustes_original

    # 2) CBF com nova data limpa o estado operacional de adiamento,
    # inclusive se a data já tiver sido gravada numa execução anterior.
    localizar_original = globals()["localizar_agenda_cbf"]
    try:
        class _AgendaTesteReagendado:
            mandante = "Botafogo"
            visitante = "Grêmio"
            data_iso = (agora_brt() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
            origem = "https://credencial.cbf.com.br/teste-reagendado"

        agenda_teste = _AgendaTesteReagendado()
        globals()["localizar_agenda_cbf"] = (
            lambda rows, mandante, visitante:
            rows[0]
            if rows and mandante == rows[0].mandante and visitante == rows[0].visitante
            else None
        )
        antigo = agora_brt() - timedelta(days=20)
        evento_reagendado = [{
            "event_id": "reagendado-r21",
            "rodada": 21,
            "mandante_nome": "Botafogo",
            "visitante_nome": "Grêmio",
            "data_dt": antigo,
            "data_iso": antigo.strftime("%Y-%m-%dT%H:%M"),
            "_sort": antigo.timestamp(),
            "estado": "pre",
            "concluido": False,
            "adiado": True,
            "data_definir": False,
            "status": "Postponed",
        }]
        assert aplicar_agenda_oficial_cbf(evento_reagendado, [agenda_teste]) == 1
        assert evento_reagendado[0]["data_iso"] == agenda_teste.data_iso
        assert evento_reagendado[0]["adiado"] is False
        assert evento_reagendado[0]["data_definir"] is False
        assert evento_reagendado[0]["estado"] == "pre"
        assert evento_reagendado[0]["status"] == "Pré-jogo"
        assert evento_reagendado[0]["fonte_calendario"].startswith("CBF oficial")
    finally:
        globals()["localizar_agenda_cbf"] = localizar_original

    # Proveniência da CBF precisa sobreviver ao espn_eventos.json; sem isso a
    # execução seguinte perderia a informação de que o kickoff foi confirmado.
    prov_event = {
        **evento_novo,
        "event_id": "prov-cbf",
        "fonte_calendario": "CBF oficial — agenda de credenciamento",
        "origem_calendario": "https://credencial.cbf.com.br/teste",
        "data_espn_original": "2026-08-11T20:00",
    }
    _, _, prov_json = gerar_jogos_resultados_eventos(
        [prov_event], eventos_ja_normalizados=True, aplicar_manuais=False
    )
    prov_out = prov_json["eventos"][0]
    assert prov_out["fonte_calendario"].startswith("CBF oficial")
    assert prov_out["data_espn_original"] == "2026-08-11T20:00"

    fetch_original = globals()["fetch_json"]
    chamadas_teste: list[str] = []
    try:
        def _fetch_teste(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            chamadas_teste.append(url)
            return {"events": [{"id": "inc-1"}, {"id": "inc-1"}, {"id": "inc-2"}]}
        globals()["fetch_json"] = _fetch_teste
        recebidos = _buscar_eventos_periodo(
            inicio_inc, fim_inc, bloco_dias=(fim_inc - inicio_inc).days + 1
        )
        assert len(chamadas_teste) == 1
        assert "_=" not in chamadas_teste[0]
        assert {item["id"] for item in recebidos} == {"inc-1", "inc-2"}
    finally:
        globals()["fetch_json"] = fetch_original

    # FAST CORE 1.1.2: summary proativo independe de divergência standings.
    fetch_original = globals()["fetch_json"]
    env_force_original = os.environ.get("ESPN_FORCE_SUMMARY_EVENT_IDS")
    try:
        now_summary = datetime(2026, 9, 6, 14, 0, tzinfo=FUSO_BRASILIA)
        kickoff_summary = now_summary - timedelta(hours=3)
        alvo_summary = {
            "event_id": "401841219",
            "rodada": 26,
            "data_dt": kickoff_summary,
            "data_iso": kickoff_summary.strftime("%Y-%m-%dT%H:%M"),
            "_sort": kickoff_summary.timestamp(),
            "mandante_nome": "Coritiba",
            "visitante_nome": "Mirassol",
            "mandante": info_time("Coritiba"),
            "visitante": info_time("Mirassol"),
            "estadio": "Couto Pereira",
            "transmissao": "",
            "status": "0'",
            "estado": "pre",
            "concluido": False,
            "adiado": False,
            "placar_mandante": 0,
            "placar_visitante": 0,
            "data_definir": False,
        }
        def _fetch_summary_teste(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            assert "summary?event=401841219" in url
            return {
                "header": {
                    "id": "401841219",
                    "competitions": [{
                        "date": "2026-09-06T14:00Z",
                        "status": {
                            "type": {
                                "completed": True,
                                "state": "post",
                                "displayClock": "90'+6'",
                                "shortDetail": "Final",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "1",
                                "team": {
                                    "displayName": "Coritiba",
                                    "shortDisplayName": "Coritiba",
                                    "abbreviation": "CFC",
                                },
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {
                                    "displayName": "Mirassol",
                                    "shortDisplayName": "Mirassol",
                                    "abbreviation": "MIR",
                                },
                            },
                        ],
                    }],
                }
            }
        globals()["fetch_json"] = _fetch_summary_teste
        os.environ["ESPN_FORCE_SUMMARY_EVENT_IDS"] = "401841219"
        assert aplicar_resumos_proativos_espn([alvo_summary], agora=now_summary) == 1
        assert alvo_summary["estado"] == "post"
        assert alvo_summary["concluido"] is True
        assert alvo_summary["placar_mandante"] == 1
        assert alvo_summary["placar_visitante"] == 0
        assert alvo_summary["fonte_resultado"] == "ESPN summary"
    finally:
        globals()["fetch_json"] = fetch_original
        if env_force_original is None:
            os.environ.pop("ESPN_FORCE_SUMMARY_EVENT_IDS", None)
        else:
            os.environ["ESPN_FORCE_SUMMARY_EVENT_IDS"] = env_force_original

    print("Selftest Execução 6, sincronização cruzada e coleta incremental OK")


def main() -> None:
    anteriores, snapshot_anterior_em = carregar_snapshot_eventos_anterior()
    ultima_falha = ""

    for tentativa in range(1, MAX_TENTATIVAS_SINCRONIA + 1):
        print(f"== COLETA SINCRONIZADA {tentativa}/{MAX_TENTATIVAS_SINCRONIA} ==")
        try:
            classificacao_transacional = False
            resultados_transacionais = 0
            tabela = gerar_tabela()
            validar_contra_ranking(tabela)
            eventos_brutos, coleta_scoreboard = buscar_eventos_scoreboard()
            eventos_atualizados = normalizar_eventos_scoreboard(eventos_brutos, finalizar=False)
            eventos_normalizados, estatisticas_mesclagem = mesclar_eventos_incrementais(
                eventos_atualizados
            )
            coleta_scoreboard.update(estatisticas_mesclagem)

            # A ESPN continua principal, mas a CBF confirma kickoffs futuros e
            # recupera omissões sem inventar jogos/IDs. Falha da CBF nunca
            # impede a atualização esportiva principal.
            try:
                agenda_cbf = buscar_agenda_cbf(resolver=para_canonico)
            except Exception as exc:  # noqa: BLE001
                agenda_cbf = []
                print(f"::warning::Agenda CBF indisponível para reconciliação de horários: {type(exc).__name__}: {exc}")
            if agenda_cbf:
                horarios_cbf = aplicar_agenda_oficial_cbf(eventos_normalizados, agenda_cbf)
                adicionados_cbf = complementar_eventos_futuros_cbf(eventos_normalizados, agenda_cbf)
                if horarios_cbf or adicionados_cbf:
                    eventos_normalizados = finalizar_eventos_normalizados(eventos_normalizados)
                coleta_scoreboard["horarios_reconciliados_cbf"] = horarios_cbf
                coleta_scoreboard["jogos_restaurados_cbf"] = adicionados_cbf
                print(f"Agenda CBF: {horarios_cbf} horário(s) reconciliado(s), {adicionados_cbf} jogo(s) restaurado(s).")
            else:
                coleta_scoreboard["horarios_reconciliados_cbf"] = 0
                coleta_scoreboard["jogos_restaurados_cbf"] = 0

            provisoria = marcar_kickoffs_provisorios_espn(eventos_normalizados)
            coleta_scoreboard["kickoffs_provisorios_suprimidos"] = provisoria
            if provisoria:
                print(f"Kickoffs provisórios suprimidos: {provisoria}")

            aplicar_transmissoes_manuais(eventos_normalizados)
            # FAST CORE: confirma por event_id jogos recentes/forçados ANTES da
            # auditoria standings x resultados. Assim um scoreboard agregado
            # congelado não consegue mais esconder um FINAL já disponível no
            # summary individual da ESPN.
            summary_proativos = aplicar_resumos_proativos_espn(eventos_normalizados)
            coleta_scoreboard["resultados_summary_proativos"] = summary_proativos
            if summary_proativos:
                eventos_normalizados = finalizar_eventos_normalizados(eventos_normalizados)
            print(
                "Snapshot consolidado: "
                f"{estatisticas_mesclagem['eventos_historicos']} históricos + "
                f"{estatisticas_mesclagem['eventos_atualizados']} recebidos -> "
                f"{estatisticas_mesclagem['eventos_consolidados']} eventos únicos."
            )
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
                # O standings da ESPN inclui placares provisórios de partidas ao
                # vivo. Se o scoreboard já confirmou novos jogos encerrados,
                # avançamos SOMENTE esses resultados sobre o último snapshot
                # íntegro. O método rejeita remoção ou alteração histórica.
                tabela_candidata, aplicados, motivo_transacional = tentar_tabela_transacional(resultados)
                if tabela_candidata is not None:
                    tabela = tabela_candidata
                    discrepancias = diagnosticar_sincronia_tabela_resultados(tabela, resultados)
                    classificacao_transacional = not discrepancias
                    resultados_transacionais = aplicados if classificacao_transacional else 0
                    if classificacao_transacional:
                        print(
                            "Classificação transacional aceita: "
                            f"{aplicados} novo(s) resultado(s) final(is) ESPN aplicado(s); "
                            "placares de jogos ainda ao vivo foram ignorados."
                        )
                else:
                    print(f"::warning::Classificação transacional não aplicada: {motivo_transacional}.")

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
                eventos_json["coleta"] = coleta_scoreboard
                gravar_json_atomico("tabela.json", tabela)
                gravar_json_atomico("jogos.json", jogos)
                gravar_json_atomico("resultados.json", resultados)
                gravar_json_atomico("espn_eventos.json", eventos_json)

                fontes = sorted({item.get("fonte") for item in fallbacks if item.get("fonte")})
                if fallbacks or classificacao_transacional:
                    complementos = []
                    if fallbacks:
                        complementos.append("fontes complementares: " + ", ".join(fontes))
                    if classificacao_transacional:
                        complementos.append(
                            f"classificação avançada com {resultados_transacionais} "
                            "resultado(s) final(is) ESPN, sem incorporar jogos ao vivo"
                        )
                    motivo = (
                        "snapshot auditado e publicado; ESPN permaneceu principal; "
                        + "; ".join(complementos)
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscar_detalhes_jogos_brasileirao.py

Busca incrementalmente o summary da ESPN para jogos finalizados do Brasileirão e gera:
  - dados-br/jogos-detalhes.json
  - dados-br/auditoria-jogos-detalhes.json

O front usa o JSON para exibir o botão recolhível "📊 Estatísticas do jogo"
na aba Resultados. A rotina é conservadora: não inventa estatística, preserva
estatísticas boas de execuções anteriores quando a ESPN oscila e nunca toca no
módulo copa2026/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary?event={event_id}"
FUSO_BRASILIA = timezone(timedelta(hours=-3))
ROOT = Path(__file__).resolve().parents[1]
RESULTADOS = ROOT / "resultados.json"
SAIDA = ROOT / "dados-br" / "jogos-detalhes.json"
AUDITORIA = ROOT / "dados-br" / "auditoria-jogos-detalhes.json"
PUBLICOS_COMPLEMENTARES = ROOT / "dados-br" / "publicos-complementares.json"
RESULTADOS_MANUAIS = ROOT / "dados-br" / "resultados-manuais.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

# Métricas que interessam para uma leitura simples no card do jogo. A ESPN muda
# nomes e formatos entre competições; por isso aceitamos variações.
METRIC_RULES = [
    {"keys": ["expected goals", "expectedgoals", "xg"], "label": "xG", "order": 1},
    {"keys": ["possession pct", "possession percent", "possession percentage", "possessionpct", "possession"], "label": "Posse", "order": 2, "percent": True},
    {"keys": ["total shots", "totalshots", "shots total", "shots"], "label": "Finalizações", "order": 3},
    {"keys": ["shots on goal", "shots on target", "shotsongoal", "shotsontarget"], "label": "Chutes no gol", "order": 4},
    {"keys": ["shots off target", "shotsofftarget"], "label": "Chutes para fora", "order": 5},
    {"keys": ["blocked shots", "blockedshots"], "label": "Chutes bloqueados", "order": 6},
    {"keys": ["shot pct", "shot percent", "shot percentage", "shotpct", "shooting percentage"], "label": "Aproveitamento dos chutes", "order": 7, "percent01": True, "note": "chutes no gol ÷ finalizações"},
    {"keys": ["big chances created", "bigchancescreated"], "label": "Grandes chances", "order": 8},
    {"keys": ["big chances missed", "bigchancesmissed"], "label": "Chances perdidas", "order": 9},
    {"keys": ["corner kicks", "cornerkicks", "won corners", "woncorners", "corners"], "label": "Escanteios", "order": 10},
    {"keys": ["fouls committed", "foulscommitted", "fouls"], "label": "Faltas", "order": 11},
    {"keys": ["yellow cards", "yellowcards"], "label": "Amarelos", "order": 12},
    {"keys": ["red cards", "redcards"], "label": "Vermelhos", "order": 13},
    {"keys": ["offsides", "offside"], "label": "Impedimentos", "order": 14},
    {"keys": ["saves", "goalkeeper saves"], "label": "Defesas", "order": 15},
    {"keys": ["accurate passes", "accuratepasses", "completed passes"], "label": "Passes certos", "order": 16},
    {"keys": ["pass pct", "pass percent", "pass percentage", "pass accuracy", "passpct", "passaccuracy"], "label": "Precisão de passe", "order": 17, "percent01": True},
    {"keys": ["total passes", "totalpasses", "passes", "pass attempts", "passattempts"], "label": "Passes", "order": 18},
    {"keys": ["duels won", "duelswon", "total duels won", "totalduelswon"], "label": "Duelos vencidos", "order": 19},
    {"keys": ["tackles won", "tackleswon", "successful tackles", "successfultackles", "tackles"], "label": "Desarmes", "order": 20},
    {"keys": ["interceptions", "interception"], "label": "Interceptações", "order": 21},
    {"keys": ["accurate crosses", "accuratecrosses", "crosses", "cross attempts", "crossattempts"], "label": "Cruzamentos", "order": 22},
    {"keys": ["clearances", "clearance"], "label": "Cortes", "order": 23},
]


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def iso_agora_brt() -> str:
    return agora_brt().isoformat()


def normalizar(valor: Any) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(valor or ""))
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def compacto(valor: Any) -> str:
    return normalizar(valor).replace(" ", "")


def rule_of(nome: Any) -> dict[str, Any] | None:
    k = normalizar(nome)
    kc = compacto(nome)
    if not k:
        return None

    for regra in METRIC_RULES:
        if k == normalizar(regra["label"]) or kc == compacto(regra["label"]):
            return regra

    for regra in METRIC_RULES:
        for chave in regra["keys"]:
            if k == normalizar(chave) or kc == compacto(chave):
                return regra

    # Parcial controlado: evita tratar "shots on goal" como "Finalizações".
    for regra in METRIC_RULES:
        if regra["label"] == "Finalizações":
            continue
        if normalizar(regra["label"]) in k or compacto(regra["label"]) in kc:
            return regra
        for chave in regra["keys"]:
            nk, nck = normalizar(chave), compacto(chave)
            if nk and (nk in k or nck in kc):
                return regra
    return None


def stat_name(item: dict[str, Any]) -> str:
    return str(
        item.get("displayName")
        or item.get("shortDisplayName")
        or item.get("name")
        or item.get("label")
        or item.get("abbreviation")
        or ""
    )


def stat_val(item: dict[str, Any]) -> str:
    valor = item.get("displayValue")
    if valor is None:
        valor = item.get("value")
    return "" if valor is None else str(valor)


def numero(valor: Any) -> float | None:
    m = re.search(r"-?\d+(?:[\.,]\d+)?", str(valor or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def fmt_value(regra: dict[str, Any], bruto: Any) -> str:
    if bruto is None:
        return ""
    s = str(bruto).strip()
    if s == "":
        return ""
    n = numero(s)
    if (regra.get("percent") or regra.get("percent01")) and "%" not in s and n is not None:
        if regra.get("percent01") and 0 <= n <= 1:
            return f"{round(n * 100)}%"
        return f"{round(n, 1):g}%"
    return s


def team_nome(team_box: dict[str, Any]) -> str:
    t = team_box.get("team") or {}
    return str(t.get("displayName") or t.get("shortDisplayName") or t.get("name") or t.get("abbreviation") or "")


def team_id(team_box: dict[str, Any]) -> str:
    t = team_box.get("team") or {}
    return str(t.get("id") or t.get("uid") or t.get("abbreviation") or team_nome(team_box) or "")


def home_away_from_competitors(summary: dict[str, Any]) -> tuple[str, str]:
    comp = (((summary.get("header") or {}).get("competitions") or [{}])[0])
    home = away = ""
    for c in comp.get("competitors") or []:
        t = c.get("team") or {}
        tid = str(t.get("id") or t.get("uid") or t.get("abbreviation") or t.get("displayName") or "")
        if c.get("homeAway") == "home":
            home = tid
        elif c.get("homeAway") == "away":
            away = tid
    return home, away


def ordenar_times_boxscore(summary: dict[str, Any], jogo: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    teams = (((summary or {}).get("boxscore") or {}).get("teams") or [])
    if len(teams) < 2:
        return None, None

    home_by_flag = next((t for t in teams if str(t.get("homeAway") or "").lower() == "home"), None)
    away_by_flag = next((t for t in teams if str(t.get("homeAway") or "").lower() == "away"), None)
    if home_by_flag and away_by_flag:
        return home_by_flag, away_by_flag

    home_id, away_id = home_away_from_competitors(summary)
    if home_id or away_id:
        home = next((t for t in teams if team_id(t) == home_id), None)
        away = next((t for t in teams if team_id(t) == away_id), None)
        if home and away:
            return home, away

    mandante = normalizar((jogo.get("mandante") or {}).get("nome"))
    visitante = normalizar((jogo.get("visitante") or {}).get("nome"))
    if mandante or visitante:
        home = next((t for t in teams if mandante and mandante in normalizar(team_nome(t))), None)
        away = next((t for t in teams if visitante and visitante in normalizar(team_nome(t))), None)
        if home and away and home is not away:
            return home, away

    # A ESPN geralmente já entrega na ordem mandante/visitante.
    return teams[0], teams[1]


def estatisticas_do_time(team_box: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not team_box:
        return []
    return list(team_box.get("statistics") or team_box.get("stats") or [])


def parse_summary(summary: dict[str, Any], jogo: dict[str, Any]) -> list[dict[str, Any]]:
    home, away = ordenar_times_boxscore(summary, jogo)
    stats_home = estatisticas_do_time(home)
    stats_away = estatisticas_do_time(away)
    if not stats_home or not stats_away:
        return []

    away_por_label: dict[str, tuple[dict[str, Any], str]] = {}
    for s in stats_away:
        regra = rule_of(stat_name(s))
        if regra:
            away_por_label[regra["label"]] = (regra, stat_val(s))

    by_label: dict[str, dict[str, Any]] = {}
    for s in stats_home:
        regra = rule_of(stat_name(s))
        if not regra:
            continue
        label = regra["label"]
        par_away = away_por_label.get(label)
        item = {
            "nome": label,
            "home": fmt_value(regra, stat_val(s)),
            "away": fmt_value(regra, par_away[1] if par_away else ""),
        }
        if regra.get("note"):
            item["note"] = regra["note"]
        if item["home"] == "" and item["away"] == "":
            continue
        anterior = by_label.get(label)
        if anterior is None or regra["order"] < anterior.get("_order", 999):
            item["_order"] = regra["order"]
            by_label[label] = item

    saida = sorted(by_label.values(), key=lambda x: x.get("_order", 999))
    for item in saida:
        item.pop("_order", None)
    return saida



def _walk(no: Any):
    if isinstance(no, dict):
        yield no
        for v in no.values():
            yield from _walk(v)
    elif isinstance(no, list):
        for v in no:
            yield from _walk(v)


def _first_text(no: Any, *keys: str) -> str:
    if not isinstance(no, dict):
        return ""
    for key in keys:
        v = no.get(key)
        if isinstance(v, dict):
            text = _first_text(v, "displayName", "fullName", "name", "shortDisplayName", "text")
            if text:
                return text
        elif v not in (None, ""):
            return str(v).strip()
    return ""


def _attendance_number(value: Any) -> int | None:
    """Converte público sem confundir separador de milhar com decimal."""
    if isinstance(value, dict):
        for key in ("value", "displayValue", "formattedValue", "text", "shortText", "name"):
            found = _attendance_number(value.get(key))
            if found is not None:
                return found
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(round(float(value)))
        return n if 100 <= n <= 250000 else None
    raw = str(value or "").strip()
    if not raw:
        return None
    # Público é inteiro. "43,210", "43.210" e "43 210" devem virar 43210.
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    return n if 100 <= n <= 250000 else None


def parse_publico(summary: dict[str, Any]) -> int | None:
    candidatos: list[int] = []
    nomes = {"attendance", "crowd", "publico", "spectators", "attendancevalue"}
    for no in _walk(summary):
        for key, value in no.items():
            nk = compacto(key)
            if nk not in nomes and not any(token in nk for token in ("attendance", "spectator", "publico")):
                continue
            n = _attendance_number(value)
            if n is not None:
                candidatos.append(n)
    return max(candidatos) if candidatos else None




def carregar_publicos_complementares() -> dict[str, dict[str, Any]]:
    payload = carregar_json(PUBLICOS_COMPLEMENTARES, {})
    jogos = payload.get("jogos") if isinstance(payload, dict) else {}
    return jogos if isinstance(jogos, dict) else {}


def publico_complementar(event_id: str, mapa: dict[str, dict[str, Any]]) -> tuple[int | None, str, str]:
    item = mapa.get(str(event_id)) if isinstance(mapa, dict) else None
    if not isinstance(item, dict):
        return None, "", ""
    valor = _attendance_number(item.get("publico"))
    return valor, str(item.get("fonte") or ""), str(item.get("tipo") or "presente")


def parse_estadio(summary: dict[str, Any], jogo: dict[str, Any]) -> str:
    paths = [
        ((summary.get("gameInfo") or {}).get("venue") or {}),
        ((((summary.get("header") or {}).get("competitions") or [{}])[0]).get("venue") or {}),
    ]
    for venue in paths:
        text = _first_text(venue, "fullName", "displayName", "name", "shortName")
        if text:
            return text
    return str(jogo.get("estadio") or "").strip()


def parse_arbitro(summary: dict[str, Any]) -> str:
    officials = (summary.get("gameInfo") or {}).get("officials") or []
    if not isinstance(officials, list):
        officials = []
    preferidos: list[str] = []
    outros: list[str] = []
    for item in officials:
        if not isinstance(item, dict):
            continue
        nome = _first_text(item, "displayName", "fullName", "name")
        if not nome and isinstance(item.get("official"), dict):
            nome = _first_text(item["official"], "displayName", "fullName", "name")
        if not nome:
            continue
        papel = normalizar(" ".join(str(item.get(k) or "") for k in ("position", "type", "role", "order")))
        if "referee" in papel or "arbitro" in papel:
            preferidos.append(nome)
        else:
            outros.append(nome)
    return (preferidos or outros or [""])[0]


def limpar_nome_jogador(nome: Any) -> str:
    s = str(nome or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+(?:with a|with the)\s+(?:cross|pass|headed pass|header|shot|through ball).*?$", "", s, flags=re.I)
    s = re.sub(r"\s+(?:following|after)\s+.*?$", "", s, flags=re.I)
    s = re.sub(r"\s+(?:right|left)-?footed.*?$", "", s, flags=re.I)
    s = re.sub(r"\s+(?:assisted by|from the centre|from outside).*?$", "", s, flags=re.I)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip(" -.,;")
    return s


def _bool_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = normalizar(value)
    if text in {"true", "yes", "sim", "1"}:
        return True
    if text in {"false", "no", "nao", "0"}:
        return False
    return None


def _athlete_record(entry: dict[str, Any]) -> tuple[str, str]:
    candidates: list[dict[str, Any]] = []
    for key in ("athlete", "player", "participant", "person"):
        value = entry.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(entry)
    for athlete in candidates:
        name = _first_text(
            athlete, "displayName", "fullName", "shortName", "name", "shortDisplayName"
        )
        name = limpar_nome_jogador(name)
        if not name:
            continue
        athlete_id = str(
            athlete.get("id")
            or athlete.get("athleteId")
            or athlete.get("uid")
            or entry.get("athleteId")
            or ""
        ).strip()
        return name, athlete_id
    return "", ""


def _minutes_from_entry(entry: dict[str, Any]) -> int | None:
    direct_keys = ("minutes", "minutesPlayed", "minsPlayed", "timePlayed")
    for key in direct_keys:
        value = entry.get(key)
        if isinstance(value, dict):
            value = value.get("value") if value.get("value") is not None else value.get("displayValue")
        n = numero(value)
        if n is not None:
            return max(0, int(round(n)))

    for node in _walk(entry.get("statistics") or entry.get("stats") or []):
        label = normalizar(" ".join(str(node.get(k) or "") for k in (
            "name", "displayName", "shortDisplayName", "label", "abbreviation"
        )))
        if label not in {"minutes", "minutes played", "mins", "min"}:
            continue
        value = node.get("value") if node.get("value") is not None else node.get("displayValue")
        n = numero(value)
        if n is not None:
            return max(0, int(round(n)))
    return None


def _confirmed_appearance(entry: dict[str, Any]) -> tuple[bool, bool, bool, int | None]:
    did_not_play = next((
        _bool_flag(entry.get(key))
        for key in ("didNotPlay", "did_not_play", "dnp")
        if entry.get(key) is not None
    ), None)
    if did_not_play is True:
        return False, False, False, _minutes_from_entry(entry)

    starter = any(_bool_flag(entry.get(key)) is True for key in ("starter", "starting", "isStarter"))
    subbed_in = any(_bool_flag(entry.get(key)) is True for key in ("subbedIn", "subbed_in", "entered"))
    if entry.get("subbedInFor") not in (None, "", False, []):
        subbed_in = True
    explicitly_played = any(
        _bool_flag(entry.get(key)) is True
        for key in ("played", "appeared", "participated", "hasPlayed")
    )
    minutes = _minutes_from_entry(entry)
    played = starter or subbed_in or explicitly_played or (minutes is not None and minutes > 0)
    return played, starter, subbed_in, minutes


def _game_team_names(jogo: dict[str, Any]) -> tuple[str, str]:
    return (
        str((jogo.get("mandante") or {}).get("nome") or "").strip(),
        str((jogo.get("visitante") or {}).get("nome") or "").strip(),
    )


def _canonical_game_team(raw: Any, jogo: dict[str, Any], side_hint: str = "", index: int = -1) -> str:
    home, away = _game_team_names(jogo)
    side = normalizar(side_hint)
    if side in {"home", "mandante", "casa"}:
        return home
    if side in {"away", "visitante", "fora"}:
        return away

    raw_name = _first_text(raw, "displayName", "shortDisplayName", "name", "location", "abbreviation") if isinstance(raw, dict) else str(raw or "")
    nraw = normalizar(raw_name)
    nhome, naway = normalizar(home), normalizar(away)
    if nraw and nhome and (nraw == nhome or nraw in nhome or nhome in nraw):
        return home
    if nraw and naway and (nraw == naway or nraw in naway or naway in nraw):
        return away
    if index == 0:
        return home
    if index == 1:
        return away
    return raw_name.strip()


def _roster_lists(summary: dict[str, Any]) -> list[tuple[dict[str, Any], int]]:
    out: list[tuple[dict[str, Any], int]] = []
    seen: set[int] = set()
    containers = [
        summary.get("rosters"),
        summary.get("lineups"),
        summary.get("lineUps"),
        (summary.get("boxscore") or {}).get("rosters"),
        (summary.get("boxscore") or {}).get("lineups"),
    ]
    for container in containers:
        if isinstance(container, list):
            for index, block in enumerate(container):
                if isinstance(block, dict) and id(block) not in seen:
                    seen.add(id(block))
                    out.append((block, index))
        elif isinstance(container, dict):
            for index, key in enumerate(("home", "away")):
                value = container.get(key)
                if isinstance(value, dict):
                    block = value
                elif isinstance(value, list):
                    block = {"homeAway": key, "roster": value}
                else:
                    continue
                if id(block) not in seen:
                    seen.add(id(block))
                    out.append((block, index))
    return out


def parse_jogadores(summary: dict[str, Any], jogo: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai apenas atletas com participação confirmada na partida.

    A ESPN marca titulares e jogadores que entraram em campo no bloco
    ``rosters``. Reservas que não atuaram não entram na contagem.
    """
    dedup: dict[str, dict[str, Any]] = {}
    for block, index in _roster_lists(summary):
        raw_team = block.get("team") or block.get("club") or block.get("competitor") or {}
        side_hint = str(block.get("homeAway") or block.get("side") or "")
        team = _canonical_game_team(raw_team, jogo, side_hint, index)
        team_id_value = ""
        if isinstance(raw_team, dict):
            team_id_value = str(raw_team.get("id") or raw_team.get("uid") or "").strip()

        entries: list[Any] = []
        for key in ("roster", "athletes", "players", "lineup"):
            value = block.get(key)
            if isinstance(value, list):
                entries.extend(value)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            played, starter, subbed_in, minutes = _confirmed_appearance(entry)
            if not played:
                continue
            name, athlete_id = _athlete_record(entry)
            if not name or not team:
                continue
            key = athlete_id or f"{normalizar(name)}|{normalizar(team)}"
            previous = dedup.get(key) or {}
            record = {
                "athlete_id": athlete_id or str(previous.get("athlete_id") or ""),
                "nome": name,
                "time": team,
                "team_id": team_id_value or str(previous.get("team_id") or ""),
                "titular": bool(starter or previous.get("titular")),
                "entrou": bool(subbed_in or previous.get("entrou")),
            }
            best_minutes = max(
                [x for x in (minutes, previous.get("minutos")) if isinstance(x, int)],
                default=None,
            )
            if best_minutes is not None:
                record["minutos"] = best_minutes
            dedup[key] = record

    players = list(dedup.values())
    players.sort(key=lambda x: (normalizar(x.get("time")), not bool(x.get("titular")), normalizar(x.get("nome"))))
    return players


def escolher_jogadores(
    novos: list[dict[str, Any]], anteriores: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    """Preserva a escalação anterior se a resposta nova vier truncada."""
    novos_validos = [x for x in novos if isinstance(x, dict) and x.get("nome") and x.get("time")]
    anteriores_validos = [x for x in anteriores if isinstance(x, dict) and x.get("nome") and x.get("time")]
    if anteriores_validos and len(novos_validos) < len(anteriores_validos):
        return anteriores_validos, True
    return novos_validos, False


_EVENT_KEYS = {
    "scoringplays": 100,
    "keyevents": 90,
    "incidents": 80,
    "matchevents": 75,
    "plays": 50,
    "commentary": 40,
    "details": 30,
}


def _event_nodes(summary: dict[str, Any]) -> list[tuple[dict[str, Any], str, int]]:
    """Retorna eventos com origem/prioridade e evita percorrer a mesma lista duas vezes."""
    out: list[tuple[dict[str, Any], str, int]] = []
    seen_lists: set[int] = set()
    seen_items: set[tuple[int, str]] = set()

    def walk(no: Any) -> None:
        if isinstance(no, dict):
            for key, value in no.items():
                nk = compacto(key)
                if isinstance(value, list) and nk in _EVENT_KEYS and id(value) not in seen_lists:
                    seen_lists.add(id(value))
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        marker = (id(item), nk)
                        if marker in seen_items:
                            continue
                        seen_items.add(marker)
                        out.append((item, nk, _EVENT_KEYS[nk]))
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(no, list):
            for item in no:
                walk(item)

    walk(summary)
    out.sort(key=lambda x: -x[2])
    return out


def _event_text(ev: dict[str, Any]) -> str:
    tipo = ev.get("type")
    parts: list[str] = []
    if isinstance(tipo, dict):
        parts.extend(str(tipo.get(k) or "") for k in ("text", "name", "displayName", "description", "id"))
    elif tipo:
        parts.append(str(tipo))
    parts.extend(str(ev.get(k) or "") for k in ("text", "description", "descricao", "shortText", "headline", "eventType", "playType"))
    # A mesma frase aparece em vários campos da ESPN; remova repetições exatas.
    unique: list[str] = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        if part and part not in unique:
            unique.append(part)
    return " ".join(unique).strip()


def _event_type_text(ev: dict[str, Any]) -> str:
    tipo = ev.get("type")
    parts: list[str] = []
    if isinstance(tipo, dict):
        parts.extend(str(tipo.get(k) or "") for k in ("text", "name", "displayName", "description", "id"))
    elif tipo:
        parts.append(str(tipo))
    parts.extend(str(ev.get(k) or "") for k in ("eventType", "playType"))
    return " ".join(parts)


def _event_minute(ev: dict[str, Any]) -> str:
    for key in ("clock", "time", "displayClock", "timeDisplayValue", "minute", "minuto"):
        v = ev.get(key)
        if isinstance(v, dict):
            text = _first_text(v, "displayValue", "displayClock", "value", "text")
            if text:
                return text
        elif v not in (None, ""):
            return str(v)
    return ""


def _minute_key(value: Any) -> str:
    """Normaliza minuto inclusive quando chega como objeto/string de objeto."""
    if isinstance(value, dict):
        value = _first_text(value, "displayValue", "displayClock", "text", "value")
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Algumas execuções antigas serializaram o objeto do relógio dentro de uma
    # string. Aproveite apenas o displayValue; nunca use o objeto como equipe.
    m = re.search(r"displayValue['\"\s:]+([^,}\]]+)", raw, flags=re.I)
    if m:
        raw = m.group(1).strip(" '\"")
    nums = re.findall(r"\d+", raw)
    if not nums:
        return normalizar(raw)
    return f"{int(nums[0])}+{int(nums[1]) if len(nums) > 1 else 0}"


def _athletes_event(ev: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key in ("athletes", "athletesInvolved", "participants", "players"):
        for item in ev.get(key) or []:
            if not isinstance(item, dict):
                continue
            base = item.get("athlete") if isinstance(item.get("athlete"), dict) else item
            nome = limpar_nome_jogador(_first_text(base, "displayName", "fullName", "name", "shortName"))
            papel = normalizar(" ".join(str(item.get(k) or "") for k in ("type", "role", "position")))
            if nome:
                out.append((nome, papel))
    for key in ("athlete", "player", "scorer"):
        if isinstance(ev.get(key), dict):
            nome = limpar_nome_jogador(_first_text(ev[key], "displayName", "fullName", "name", "shortName"))
            if nome and not any(normalizar(n) == normalizar(nome) for n, _ in out):
                out.append((nome, "scorer" if key == "scorer" else ""))
    # Compatibilidade com o JSON local já normalizado.
    if ev.get("jogador"):
        nome = limpar_nome_jogador(ev.get("jogador"))
        if nome and not any(normalizar(n) == normalizar(nome) for n, _ in out):
            out.append((nome, "scorer"))
    for nome in ev.get("assistencias") or []:
        nome = limpar_nome_jogador(nome)
        if nome and not any(normalizar(n) == normalizar(nome) for n, _ in out):
            out.append((nome, "assist"))
    return out


def _team_alias(value: Any) -> str:
    n = normalizar(value)
    replacements = {
        "atletico mineiro": "atletico mg",
        "clube atletico mineiro": "atletico mg",
        "athletico paranaense": "athletico pr",
        "club athletico paranaense": "athletico pr",
        "red bull bragantino": "bragantino",
        "rb bragantino": "bragantino",
        "gremio porto alegrense": "gremio",
        "sport club internacional": "internacional",
        "sao paulo fc": "sao paulo",
        "vasco": "vasco da gama",
    }
    return replacements.get(n, n)


def _canonical_team(raw: Any, jogo: dict[str, Any] | None) -> str:
    text = str(raw or "").strip()
    if not jogo:
        return text
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    n = _team_alias(text)
    for candidate in (home, away):
        nc = _team_alias(candidate)
        if n and (n == nc or n in nc or nc in n):
            return candidate
    # Comparação por palavra distintiva para nomes longos.
    stop = {"clube", "club", "esporte", "sport", "futebol", "football", "fc", "ec", "sc", "da", "do", "de"}
    tokens = set(n.split()) - stop
    best = ""
    best_score = 0
    for candidate in (home, away):
        ctokens = set(_team_alias(candidate).split()) - stop
        score = len(tokens & ctokens)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score else text


def _event_team(ev: dict[str, Any], jogo: dict[str, Any] | None) -> str:
    """Extrai somente uma equipe válida do evento.

    A ESPN usa ``time`` também para o relógio do lance. O código antigo fazia
    ``str(ev['time'])`` como fallback de equipe, o que gerava textos como
    ``{'value': 1237.0, 'displayValue': "21'"}`` e impedia a deduplicação.
    """
    raw: Any = ""
    for key in ("team", "competitor", "club"):
        value = ev.get(key)
        if isinstance(value, dict):
            raw = _first_text(value, "displayName", "shortDisplayName", "fullName", "name", "abbreviation")
        elif value not in (None, ""):
            raw = value
        if raw:
            break

    # Compatibilidade com registros legados em português: aceite ``time``
    # somente quando for texto e corresponder de fato a um dos dois clubes.
    if not raw and isinstance(ev.get("time"), str):
        raw = ev.get("time")

    text = str(raw or "").strip()
    if not text or text.startswith(("{", "[")) or "displayvalue" in text.lower():
        return ""
    canonical = _canonical_team(text, jogo)
    if not jogo:
        return canonical
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    return canonical if canonical in (home, away) else ""


def _extract_goal_actor(text: str) -> tuple[str, str]:
    # ESPN: "Goal! Time A 0, Time B 1. Jogador (Time B) ..."
    m = re.search(r"(?:goal|gol)!.*?\.\s*([^().]+?)\s*\(([^)]+)\)", text, flags=re.I)
    if not m:
        return "", ""
    return limpar_nome_jogador(m.group(1)), m.group(2).strip()


def _extract_card_actor(text: str) -> tuple[str, str]:
    patterns = [
        r"([^().]+?)\s*\(([^)]+)\)\s+is shown (?:the|a) (?:second )?(?:yellow|red) card",
        r"second yellow card to\s+([^().]+?)\s*\(([^)]+)\)",
        r"(?:var decision:\s*)?red card(?:\s+to)?\s+([^().]+?)\s*\(([^)]+)\)",
        r"yellow card(?:\s+to)?\s+([^().]+?)\s*\(([^)]+)\)",
        r"cart[aã]o (?:amarelo|vermelho).*?para\s+([^().]+?)\s*\(([^)]+)\)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return limpar_nome_jogador(m.group(1)), m.group(2).strip()
    return "", ""


def _extract_assists(text: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"assist(?:ed|ência|encia)?\s+(?:by|de|por)\s+([^.;()]+)", text, flags=re.I):
        nome = limpar_nome_jogador(m.group(1))
        if nome and normalizar(nome) not in {normalizar(x) for x in out}:
            out.append(nome)
    return out


def _is_goal_event(ev: dict[str, Any], text: str) -> bool:
    ntype = normalizar(_event_type_text(ev))
    ntext = normalizar(text)
    reject = (
        "attempt saved", "shot saved", "save made", "shots on goal", "shots on target",
        "centre of the goal", "center of the goal", "expected goals", "goal difference",
        "goals for", "goalkeeper", "missed", "blocked",
    )
    if any(x in ntext for x in reject) and not re.search(r"\b(?:goal|gol)!", text, flags=re.I):
        return False
    explicit_type = bool(re.search(r"\b(?:own goal|penalty goal|goal|gol)\b", ntype)) and not any(
        x in ntype for x in ("attempt", "save", "shot", "miss")
    )
    explicit_text = bool(re.search(r"\b(?:goal|gol)!", text, flags=re.I))
    own_goal_text = bool(re.search(r"(?:^|\s)own goal by\s+", text, flags=re.I))
    return explicit_type or explicit_text or own_goal_text


def _card_type(ev: dict[str, Any], text: str) -> str:
    n = normalizar(_event_type_text(ev) + " " + text)
    if "no red card" in n or "sem cartao vermelho" in n:
        return ""
    if "red card" in n or "cartao vermelho" in n:
        return "vermelho"
    if "yellow card" in n or "cartao amarelo" in n:
        return "amarelo"
    return ""


def _minute_sort(value: Any) -> tuple[int, int, str]:
    nums = [int(x) for x in re.findall(r"\d+", str(value or ""))]
    return (nums[0] if nums else 999, nums[1] if len(nums) > 1 else 0, str(value or ""))


def _metric_int(stats: list[dict[str, Any]] | None, label: str, side: str) -> int | None:
    for item in stats or []:
        if normalizar(item.get("nome")) == normalizar(label):
            n = numero(item.get(side))
            return int(round(n)) if n is not None else None
    return None


def _event_quality(item: dict[str, Any]) -> int:
    return int(item.get("_prioridade") or 0) + (20 if item.get("jogador") else 0) + (10 if item.get("time") else 0) + (3 if item.get("assistencias") else 0)


def _event_narrative_signature(item: dict[str, Any], kind: str) -> str:
    text = str(item.get("descricao") or "")
    lower = text.lower()
    if kind == "gol":
        indexes = [i for marker in ("goal!", "gol!", "own goal by") if (i := lower.find(marker)) >= 0]
        if indexes:
            return normalizar(text[min(indexes):])
    else:
        # A frase após o clube entre parênteses é idêntica nas duplicatas,
        # mesmo quando a ESPN alterna apelido e nome completo do atleta.
        m = re.search(r"\([^)]+\)\s+is shown\s+(?:the|a)\s+(?:second\s+)?(?:yellow|red)\s+card[^.]*", text, flags=re.I)
        if m:
            return normalizar(m.group(0))
    return normalizar(text)


def _dedupe_events(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        player = normalizar(item.get("jogador"))
        narrative = _event_narrative_signature(item, kind)
        # O mesmo lance pode vir em keyEvents e commentary. A equipe de uma das
        # cópias pode estar ausente/malformada; por isso jogador+minuto+tipo é a
        # identidade principal. Sem jogador, use a narrativa do lance.
        key = "|".join([
            kind,
            normalizar(item.get("tipo")),
            _minute_key(item.get("minuto")),
            player or narrative,
        ])
        previous = best.get(key)
        if previous is None or _event_quality(item) > _event_quality(previous):
            best[key] = item

    # ESPN costuma repetir o mesmo lance em keyEvents/scoringPlays e commentary.
    # Quando o nome exibido varia (apelido x nome completo), a descrição narrativa
    # ainda é a mesma. Nessa situação, considere minuto+time+tipo+texto equivalente.
    merged: list[dict[str, Any]] = []
    for item in sorted(best.values(), key=lambda x: (-_event_quality(x), _minute_sort(x.get("minuto")))):
        ndesc = _event_narrative_signature(item, kind)
        duplicate_index = None
        for idx, previous in enumerate(merged):
            if _minute_key(previous.get("minuto")) != _minute_key(item.get("minuto")):
                continue
            if normalizar(previous.get("tipo")) != normalizar(item.get("tipo")):
                continue
            pplayer = normalizar(previous.get("jogador"))
            iplayer = normalizar(item.get("jogador"))
            if pplayer and iplayer and pplayer == iplayer:
                duplicate_index = idx
                break
            pdesc = _event_narrative_signature(previous, kind)
            # Use a frase do lance, não apenas o nome, para não unir cartões distintos
            # aplicados ao mesmo time no mesmo minuto.
            if ndesc and pdesc and (ndesc in pdesc or pdesc in ndesc):
                duplicate_index = idx
                break
        if duplicate_index is None:
            merged.append(item)
        elif _event_quality(item) > _event_quality(merged[duplicate_index]):
            merged[duplicate_index] = item

    merged.sort(key=lambda x: _minute_sort(x.get("minuto")))
    return merged

def _limit_by_score(gols: list[dict[str, Any]], jogo: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not jogo:
        return gols
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    expected = {
        home: int(jogo.get("placar_mandante") or 0),
        away: int(jogo.get("placar_visitante") or 0),
    }
    selected: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for team in (home, away):
        candidates = [g for g in gols if _canonical_team(g.get("time"), jogo) == team]
        candidates.sort(key=lambda x: (-_event_quality(x), _minute_sort(x.get("minuto"))))
        selected.extend(candidates[: expected[team]])
    unknown = [g for g in gols if _canonical_team(g.get("time"), jogo) not in (home, away)]
    remaining = sum(expected.values()) - len(selected)
    if remaining > 0:
        unknown.sort(key=lambda x: (-_event_quality(x), _minute_sort(x.get("minuto"))))
        selected.extend(unknown[:remaining])
    selected.sort(key=lambda x: _minute_sort(x.get("minuto")))
    return selected


def _limit_cards(cartoes: list[dict[str, Any]], jogo: dict[str, Any] | None, stats: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not jogo or not stats:
        return cartoes
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    side_of = {home: "home", away: "away"}
    selected: list[dict[str, Any]] = []
    accounted: set[int] = set()
    expected_by_type: dict[str, list[int | None]] = {"amarelo": [], "vermelho": []}
    for team in (home, away):
        for tipo, label in (("amarelo", "Amarelos"), ("vermelho", "Vermelhos")):
            expected = _metric_int(stats, label, side_of[team])
            expected_by_type[tipo].append(expected)
            candidates = [
                (idx, c) for idx, c in enumerate(cartoes)
                if c.get("tipo") == tipo and _canonical_team(c.get("time"), jogo) == team
            ]
            candidates.sort(key=lambda pair: (-_event_quality(pair[1]), _minute_sort(pair[1].get("minuto"))))
            take = len(candidates) if expected is None else max(0, expected)
            for idx, item in candidates[:take]:
                selected.append(item)
                accounted.add(idx)
    # Eventos sem equipe só podem completar uma lacuna real do boxscore. Se os
    # totais conhecidos já foram preenchidos, trata-se de cópia redundante e é
    # descartada. Isso impede a duplicação provocada pelo campo ``time``-relógio.
    for tipo in ("amarelo", "vermelho"):
        pending = [
            (idx, item) for idx, item in enumerate(cartoes)
            if idx not in accounted and item.get("tipo") == tipo
        ]
        pending.sort(key=lambda pair: (-_event_quality(pair[1]), _minute_sort(pair[1].get("minuto"))))
        expected_values = expected_by_type[tipo]
        if all(v is not None for v in expected_values):
            expected_total = sum(int(v or 0) for v in expected_values)
            already = sum(1 for item in selected if item.get("tipo") == tipo)
            take = max(0, expected_total - already)
            pending = pending[:take]
        for idx, item in pending:
            selected.append(item)
            accounted.add(idx)
    selected.sort(key=lambda x: _minute_sort(x.get("minuto")))
    return selected


def validar_eventos(jogo: dict[str, Any], stats: list[dict[str, Any]], gols: list[dict[str, Any]], cartoes: list[dict[str, Any]]) -> dict[str, Any]:
    """Valida incompatibilidades sem confundir ficha incompleta com dado corrompido.

    A ESPN pode publicar o placar final antes de completar a equipe/autoria dos
    gols e cartões. Nessa janela, o registro fica ``pendente_detalhes`` e será
    reconsultado na próxima execução. Só excesso, duplicidade ou impossibilidade
    de conciliar os eventos com placar/boxscore é inconsistente e bloqueante.
    """
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    valid_teams = {home, away}

    expected_goals = {
        home: int(jogo.get("placar_mandante") or 0),
        away: int(jogo.get("placar_visitante") or 0),
    }
    found_goals = {
        team: sum(1 for g in gols if _canonical_team(g.get("time"), jogo) == team)
        for team in (home, away)
    }
    unknown_goals = [g for g in gols if _canonical_team(g.get("time"), jogo) not in valid_teams]
    seen_goals: set[tuple[str, str, str]] = set()
    duplicate_goals = 0
    for goal in gols:
        signature = (
            _minute_key(goal.get("minuto")),
            normalizar(goal.get("jogador")) or _event_narrative_signature(goal, "gol"),
            normalizar(_canonical_team(goal.get("time"), jogo)),
        )
        if signature in seen_goals:
            duplicate_goals += 1
        seen_goals.add(signature)

    goals_no_excess = all(found_goals[team] <= expected_goals[team] for team in (home, away))
    goals_deficit = sum(max(0, expected_goals[team] - found_goals[team]) for team in (home, away))
    unknown_goals_fit_deficit = len(unknown_goals) <= goals_deficit
    goals_within_total = len(gols) <= sum(expected_goals.values())
    goals_compatible = (
        goals_no_excess
        and unknown_goals_fit_deficit
        and goals_within_total
        and duplicate_goals == 0
    )
    goals_complete = found_goals == expected_goals and not unknown_goals

    expected_cards: dict[str, dict[str, int | None]] = {}
    found_cards: dict[str, dict[str, int]] = {}
    for team, side in ((home, "home"), (away, "away")):
        expected_cards[team] = {
            "amarelo": _metric_int(stats, "Amarelos", side),
            "vermelho": _metric_int(stats, "Vermelhos", side),
        }
        found_cards[team] = {
            tipo: sum(
                1
                for c in cartoes
                if c.get("tipo") == tipo and _canonical_team(c.get("time"), jogo) == team
            )
            for tipo in ("amarelo", "vermelho")
        }

    cards_complete = all(
        exp is None or found_cards[team][tipo] == exp
        for team in (home, away)
        for tipo, exp in expected_cards[team].items()
    )
    cards_no_excess = all(
        exp is None or found_cards[team][tipo] <= exp
        for team in (home, away)
        for tipo, exp in expected_cards[team].items()
    )
    unknown_cards = [c for c in cartoes if _canonical_team(c.get("time"), jogo) not in valid_teams]
    seen_cards: set[tuple[str, str, str]] = set()
    duplicate_cards = 0
    for card in cartoes:
        signature = (
            normalizar(card.get("tipo")),
            _minute_key(card.get("minuto")),
            normalizar(card.get("jogador")) or _event_narrative_signature(card, "cartao"),
        )
        if signature in seen_cards:
            duplicate_cards += 1
        seen_cards.add(signature)

    unknown_cards_by_type = {
        tipo: sum(1 for c in unknown_cards if c.get("tipo") == tipo)
        for tipo in ("amarelo", "vermelho")
    }
    cards_assignment_possible = True
    for tipo in ("amarelo", "vermelho"):
        expected_values = [expected_cards[team][tipo] for team in (home, away)]
        if all(value is not None for value in expected_values):
            deficit = sum(
                max(0, int(expected_cards[team][tipo] or 0) - found_cards[team][tipo])
                for team in (home, away)
            )
            if unknown_cards_by_type[tipo] > deficit:
                cards_assignment_possible = False
                break

    cards_compatible = cards_no_excess and cards_assignment_possible and duplicate_cards == 0
    # Ausência de cartões nominais é tolerada; evento existente sem equipe fica
    # pendente até a ESPN completar a atribuição.
    cards_pending_attribution = bool(unknown_cards) and cards_compatible
    cards_ok = cards_compatible

    pending_details = (
        goals_compatible
        and cards_compatible
        and (not goals_complete or cards_pending_attribution)
    )
    validation_ok = goals_complete and cards_ok and not cards_pending_attribution

    pending_reasons: list[str] = []
    if not goals_complete and goals_compatible:
        pending_reasons.append(
            f"ficha de gols incompleta: {sum(found_goals.values())}/{sum(expected_goals.values())} atribuídos"
        )
        if unknown_goals:
            pending_reasons.append(f"{len(unknown_goals)} gol(s) ainda sem equipe")
    if cards_pending_attribution:
        pending_reasons.append(f"{len(unknown_cards)} cartão(ões) ainda sem equipe")

    return {
        "gols_esperados": expected_goals,
        "gols_extraidos": found_goals,
        "gols_completos": goals_complete,
        "gols_sem_excesso": goals_no_excess,
        "gols_time_desconhecido": len(unknown_goals),
        "gols_duplicados": duplicate_goals,
        "gols_compativeis": goals_compatible,
        "gols_ok": goals_complete,
        "cartoes_esperados": expected_cards,
        "cartoes_extraidos": found_cards,
        "cartoes_completos": cards_complete,
        "cartoes_sem_excesso": cards_no_excess,
        "cartoes_time_desconhecido": len(unknown_cards),
        "cartoes_duplicados": duplicate_cards,
        "cartoes_compativeis": cards_compatible,
        "cartoes_ok": cards_ok,
        "ok": validation_ok,
        "pendente_detalhes": pending_details,
        "tipo_pendencia": "ficha_espn_incompleta" if pending_details else "",
        "motivo": "; ".join(pending_reasons),
    }


def validacao_resultado_manual_pendente(jogo: dict[str, Any], motivo: str) -> dict[str, Any]:
    """Representa um placar final confirmado sem inventar autores de gols/cartões.

    O resultado manual só existe para reconciliar um evento que a fonte principal
    manteve em estado incorreto. Enquanto o summary da ESPN não disponibiliza os
    eventos, o jogo permanece contabilizado como resultado final, mas seus
    detalhes são explicitamente marcados como pendentes — nunca como validados.
    """
    home = str((jogo.get("mandante") or {}).get("nome") or jogo.get("mandante") or "")
    away = str((jogo.get("visitante") or {}).get("nome") or jogo.get("visitante") or "")
    return {
        "gols_esperados": {
            home: int(jogo.get("placar_mandante") or 0),
            away: int(jogo.get("placar_visitante") or 0),
        },
        "gols_extraidos": {home: 0, away: 0},
        "gols_completos": False,
        "gols_sem_excesso": True,
        "gols_time_desconhecido": 0,
        "gols_duplicados": 0,
        "gols_compativeis": True,
        "gols_ok": False,
        "cartoes_esperados": {},
        "cartoes_extraidos": {},
        "cartoes_completos": False,
        "cartoes_sem_excesso": True,
        "cartoes_time_desconhecido": 0,
        "cartoes_duplicados": 0,
        "cartoes_compativeis": True,
        "cartoes_ok": True,
        "ok": False,
        "resultado_confirmado": True,
        "pendente_detalhes": True,
        "tipo_pendencia": "resultado_manual_sem_ficha",
        "motivo": motivo[:300],
    }


def _ajustar_validacao_manual_sem_eventos(
    jogo: dict[str, Any],
    validacao: dict[str, Any],
    gols: list[dict[str, Any]],
    cartoes: list[dict[str, Any]],
    motivo: str,
) -> dict[str, Any]:
    """Converte somente ausência total de eventos de um resultado manual em pendência.

    Eventos parciais ou contraditórios continuam sendo inconsistência crítica.
    """
    if jogo.get("resultado_manual") is not True or validacao.get("ok"):
        return validacao
    if gols or cartoes:
        return validacao
    return validacao_resultado_manual_pendente(jogo, motivo)


def parse_eventos(
    summary: dict[str, Any],
    jogo: dict[str, Any] | None = None,
    stats: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gols_raw: list[dict[str, Any]] = []
    cartoes_raw: list[dict[str, Any]] = []
    for ev, _source, prioridade in _event_nodes(summary):
        text = _event_text(ev)
        if not text:
            continue
        athletes = _athletes_event(ev)
        player = next((n for n, role in athletes if "assist" not in role), "")
        assists = [n for n, role in athletes if "assist" in role]
        team = _event_team(ev, jogo)
        minuto = _event_minute(ev)

        if _is_goal_event(ev, text):
            p_text, t_text = _extract_goal_actor(text)
            player = player or p_text
            team = team or t_text
            if not assists:
                assists = _extract_assists(text)
            team = _event_team({"team": team or t_text}, jogo)
            gols_raw.append({
                "minuto": minuto,
                "jogador": limpar_nome_jogador(player),
                "time": team,
                "assistencias": [limpar_nome_jogador(x) for x in assists if limpar_nome_jogador(x)],
                "descricao": text,
                "_prioridade": prioridade,
            })

        card = _card_type(ev, text)
        if card:
            p_text, t_text = _extract_card_actor(text)
            card_player = player or p_text
            card_team = _event_team({"team": team or t_text}, jogo)
            cartoes_raw.append({
                "tipo": card,
                "minuto": minuto,
                "jogador": limpar_nome_jogador(card_player),
                "time": card_team,
                "descricao": text,
                "_prioridade": prioridade,
            })

    gols = _dedupe_events(gols_raw, "gol")
    cartoes = _dedupe_events(cartoes_raw, "cartao")
    gols = _limit_by_score(gols, jogo)
    cartoes = _limit_cards(cartoes, jogo, stats)
    for item in gols + cartoes:
        item.pop("_prioridade", None)
    return gols, cartoes


def _pseudo_summary_from_record(record: dict[str, Any]) -> dict[str, Any]:
    goals: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for raw in record.get("gols") or []:
        desc = str(raw.get("descricao") or "")
        ev: dict[str, Any] = {
            "text": desc,
            "clock": {"displayValue": raw.get("minuto") or ""},
            "team": {"displayName": raw.get("time") or ""},
            "jogador": raw.get("jogador") or "",
            "assistencias": raw.get("assistencias") or [],
        }
        if re.search(r"\b(?:goal|gol)!|^\s*(?:own goal|goal|gol)\b", desc, flags=re.I) and "attempt saved" not in desc.lower():
            ev["type"] = {"text": "Own Goal" if re.search(r"^\s*own goal", desc, flags=re.I) else "Goal"}
        goals.append(ev)
    for raw in record.get("cartoes") or []:
        cards.append({
            "text": raw.get("descricao") or "",
            "clock": {"displayValue": raw.get("minuto") or ""},
            "team": {"displayName": raw.get("time") or ""},
            "jogador": raw.get("jogador") or "",
        })
    return {"scoringPlays": goals, "keyEvents": cards}


def sanitizar_registro_local(jogo: dict[str, Any], record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stats = list(record.get("stats") or record.get("estatisticas") or [])
    summary = _pseudo_summary_from_record(record)
    gols, cartoes = parse_eventos(summary, jogo, stats)
    return gols, cartoes, validar_eventos(jogo, stats, gols, cartoes)

def fetch_json(url: str, timeout: int = 20, tentativas: int = 2) -> dict[str, Any]:
    ultimo: Exception | None = None
    for i in range(1, tentativas + 1):
        try:
            sep = "&" if "?" in url else "?"
            req = urllib.request.Request(f"{url}{sep}_={int(time.time())}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout + 6 * (i - 1)) as r:
                charset = r.headers.get_content_charset() or "utf-8"
                return json.loads(r.read().decode(charset, errors="replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            ultimo = exc
            if i < tentativas:
                time.sleep(1.5 * i)
    raise RuntimeError(f"falha ao buscar {url}: {type(ultimo).__name__}: {ultimo}")


def carregar_json(path: Path, padrao: Any) -> Any:
    if not path.exists():
        return padrao
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def carregar_event_ids_detalhes() -> dict[str, str]:
    """Mapeia o ID canônico do jogo para o ID ESPN que contém os detalhes.

    A ESPN pode criar um novo evento quando uma partida é adiada. O site
    preserva o ID canônico no calendário/resultados, mas consulta o novo ID
    apenas para boxscore, gols, cartões, público, estádio e arbitragem.
    """
    payload = carregar_json(RESULTADOS_MANUAIS, {})
    jogos = payload.get("jogos") if isinstance(payload, dict) else {}
    if not isinstance(jogos, dict):
        return {}
    mapa: dict[str, str] = {}
    for chave, item in jogos.items():
        if not isinstance(item, dict) or item.get("ativo") is False:
            continue
        canonico = str(item.get("event_id") or chave or "").strip()
        detalhes = str(item.get("event_id_detalhes") or "").strip()
        if canonico.isdigit() and detalhes.isdigit() and canonico != detalhes:
            mapa[canonico] = detalhes
    return mapa


def gravar_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def jogo_finalizado(jogo: dict[str, Any]) -> bool:
    if not jogo.get("event_id"):
        return False
    if jogo.get("placar_mandante") is None or jogo.get("placar_visitante") is None:
        return False
    estado = str(jogo.get("estado") or "").lower()
    if estado == "pre":
        return False
    return True


def _data_jogo(jogo: dict[str, Any]) -> datetime | None:
    raw = str(jogo.get("data_iso") or "").strip()
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=FUSO_BRASILIA) if value.tzinfo is None else value.astimezone(FUSO_BRASILIA)


def registro_pode_usar_cache(
    jogo: dict[str, Any],
    antigo: dict[str, Any] | None,
    event_id_fonte: str,
    refresh_hours: float,
    *,
    agora: datetime | None = None,
) -> bool:
    """Evita baixar novamente summaries finais já íntegros e estabilizados.

    Jogos recentes continuam sendo consultados por uma janela curta porque a
    ESPN pode completar público, cartões e escalações depois do apito final.
    Correção de placar, troca do ID-fonte, falta de estatísticas ou auditoria
    incompleta invalidam o cache imediatamente.
    """
    if not isinstance(antigo, dict):
        return False
    if str(antigo.get("event_id_fonte_detalhes") or antigo.get("event_id") or "") != str(event_id_fonte):
        return False
    if antigo.get("placar_mandante") != jogo.get("placar_mandante") or antigo.get("placar_visitante") != jogo.get("placar_visitante"):
        return False
    if str(antigo.get("mandante") or "") != str((jogo.get("mandante") or {}).get("nome") or ""):
        return False
    if str(antigo.get("visitante") or "") != str((jogo.get("visitante") or {}).get("nome") or ""):
        return False
    if not list(antigo.get("stats") or antigo.get("estatisticas") or []):
        return False
    validation = antigo.get("validacao_eventos") or {}
    if validation.get("ok") is not True or validation.get("pendente_detalhes") is True:
        return False
    played_at = _data_jogo(jogo)
    now = agora or datetime.now(FUSO_BRASILIA)
    if refresh_hours > 0 and played_at is not None and now - played_at < timedelta(hours=refresh_hours):
        return False
    return True


def montar_registro(
    event_id: str,
    jogo: dict[str, Any],
    stats: list[dict[str, Any]],
    *,
    publico: int | None = None,
    estadio: str = "",
    arbitro: str = "",
    gols: list[dict[str, Any]] | None = None,
    cartoes: list[dict[str, Any]] | None = None,
    jogadores: list[dict[str, Any]] | None = None,
    jogadores_preservados: bool = False,
    preservado: bool = False,
    validacao: dict[str, Any] | None = None,
    publico_fonte: str = "",
    publico_tipo: str = "",
    event_id_fonte_detalhes: str = "",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_id_fonte_detalhes": str(event_id_fonte_detalhes or event_id),
        "rodada": int(jogo.get("rodada") or 0),
        "data_iso": jogo.get("data_iso") or "",
        "mandante": (jogo.get("mandante") or {}).get("nome") or "",
        "visitante": (jogo.get("visitante") or {}).get("nome") or "",
        "placar_mandante": jogo.get("placar_mandante"),
        "placar_visitante": jogo.get("placar_visitante"),
        "estadio": estadio or str(jogo.get("estadio") or ""),
        "publico": publico,
        "publico_tipo": publico_tipo or ("presente" if publico not in (None, "") else ""),
        "publico_fonte": publico_fonte,
        "arbitro": arbitro,
        "stats": stats,
        "estatisticas": stats,
        "gols": gols or [],
        "cartoes": cartoes or [],
        "jogadores": jogadores or [],
        "jogadores_preservados_de_execucao_anterior": bool(jogadores_preservados),
        "validacao_eventos": validacao or validar_eventos(jogo, stats, gols or [], cartoes or []),
        "fonte": "ESPN summary" if not jogo.get("resultado_manual") else "Resultado confirmado; detalhes ESPN",
        "resultado_manual": bool(jogo.get("resultado_manual") is True),
        "origem_resultado": str(jogo.get("origem_resultado") or ""),
        "motivo_resultado_manual": str(jogo.get("motivo_resultado_manual") or ""),
        "preservado_de_execucao_anterior": bool(preservado),
        "atualizado_em": iso_agora_brt(),
    }



def self_test() -> None:
    summary = {
        "gameInfo": {
            "attendance": {"displayValue": "43,210"},
            "venue": {"fullName": "Estádio Teste"},
            "officials": [{"displayName": "Árbitro Teste", "position": {"displayName": "Referee"}}],
        },
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1"}},
            {"homeAway": "away", "team": {"id": "2"}},
        ]}]},
        "boxscore": {"teams": [
            {"homeAway": "home", "team": {"id": "1", "displayName": "Flamengo"}, "statistics": [
                {"name": "possessionPct", "displayValue": "60%"},
                {"name": "totalShots", "displayValue": "10"},
                {"name": "yellowCards", "displayValue": "0"},
                {"name": "redCards", "displayValue": "0"},
                {"name": "totalPasses", "displayValue": "500"},
                {"name": "tacklesWon", "displayValue": "18"},
                {"name": "interceptions", "displayValue": "11"},
                {"name": "crosses", "displayValue": "22"},
            ]},
            {"homeAway": "away", "team": {"id": "2", "displayName": "Palmeiras"}, "statistics": [
                {"name": "possessionPct", "displayValue": "40%"},
                {"name": "totalShots", "displayValue": "7"},
                {"name": "yellowCards", "displayValue": "1"},
                {"name": "redCards", "displayValue": "0"},
                {"name": "totalPasses", "displayValue": "410"},
                {"name": "tacklesWon", "displayValue": "20"},
                {"name": "interceptions", "displayValue": "9"},
                {"name": "crosses", "displayValue": "15"},
            ]},
        ]},
        "rosters": [
            {"homeAway": "home", "team": {"id": "1", "displayName": "Flamengo"}, "roster": [
                {"starter": True, "subbedIn": False, "athlete": {"id": "10", "displayName": "Pedro"}},
                {"starter": False, "subbedIn": True, "athlete": {"id": "11", "displayName": "Samuel Lino"}},
                {"starter": False, "subbedIn": False, "athlete": {"id": "12", "displayName": "Reserva sem entrar"}},
            ]},
            {"homeAway": "away", "team": {"id": "2", "displayName": "Palmeiras"}, "roster": [
                {"starter": True, "subbedIn": False, "athlete": {"id": "20", "displayName": "Jogador X"}},
                {"starter": False, "subbedIn": False, "didNotPlay": True, "athlete": {"id": "21", "displayName": "Reserva visitante"}},
            ]},
        ],
        "scoringPlays": [{
            "type": {"text": "Goal"}, "clock": {"displayValue": "23'"},
            "athletes": [
                {"athlete": {"displayName": "Pedro"}, "role": "scorer"},
                {"athlete": {"displayName": "Samuel Lino"}, "role": "assist"},
            ],
            "team": {"displayName": "Flamengo"},
            "text": "Goal! Flamengo 1, Palmeiras 0. Pedro (Flamengo). Assisted by Samuel Lino with a cross.",
        }],
        "plays": [
            {"clock": {"displayValue": "23'"}, "text": "Goal! Flamengo 1, Palmeiras 0. Pedro (Flamengo). Assisted by Samuel Lino with a cross."},
            {"clock": {"displayValue": "44'"}, "text": "Attempt saved. Jogador Y shot is saved in the centre of the goal."},
        ],
        "keyEvents": [{
            "type": {"text": "Yellow Card"}, "clock": {"displayValue": "31'"},
            "athletes": [{"athlete": {"displayName": "Jogador X"}}],
            "team": {"displayName": "Palmeiras"},
            "text": "Jogador X (Palmeiras) is shown the yellow card.",
        }],
        "commentary": [{
            # ``time`` aqui é o relógio, não a equipe. Esta forma reproduz o
            # payload que causava cartões duplicados no site.
            "time": {"value": 1860.0, "displayValue": "31'"},
            "text": "Jogador X (Palmeiras) is shown the yellow card.",
        }],
    }
    jogo = {
        "mandante": {"nome": "Flamengo"}, "visitante": {"nome": "Palmeiras"},
        "placar_mandante": 1, "placar_visitante": 0, "estadio": "",
    }
    assert parse_publico(summary) == 43210
    assert parse_estadio(summary, jogo) == "Estádio Teste"
    assert parse_arbitro(summary) == "Árbitro Teste"
    stats = parse_summary(summary, jogo)
    assert any(x["nome"] == "Posse" and x["home"] == "60%" and x["away"] == "40%" for x in stats)
    assert any(x["nome"] == "Passes" and x["home"] == "500" and x["away"] == "410" for x in stats)
    assert any(x["nome"] == "Desarmes" and x["home"] == "18" and x["away"] == "20" for x in stats)
    assert any(x["nome"] == "Interceptações" and x["home"] == "11" and x["away"] == "9" for x in stats)
    assert any(x["nome"] == "Cruzamentos" and x["home"] == "22" and x["away"] == "15" for x in stats)
    jogadores = parse_jogadores(summary, jogo)
    assert {(x["nome"], x["time"]) for x in jogadores} == {
        ("Pedro", "Flamengo"), ("Samuel Lino", "Flamengo"), ("Jogador X", "Palmeiras")
    }, jogadores
    assert next(x for x in jogadores if x["nome"] == "Pedro")["titular"] is True
    assert next(x for x in jogadores if x["nome"] == "Samuel Lino")["entrou"] is True
    escolhidos, preservou = escolher_jogadores(
        jogadores[:1], jogadores
    )
    assert preservou is True and len(escolhidos) == len(jogadores)
    gols, cartoes = parse_eventos(summary, jogo, stats)
    assert len(gols) == 1, gols
    assert gols[0]["jogador"] == "Pedro"
    assert gols[0]["assistencias"] == ["Samuel Lino"]
    assert len(cartoes) == 1, cartoes
    assert cartoes[0]["jogador"] == "Jogador X"
    assert cartoes[0]["time"] == "Palmeiras"
    assert _extract_card_actor("Second yellow card to Fulano (Palmeiras) for a bad foul.") == ("Fulano", "Palmeiras")
    assert _extract_card_actor("VAR Decision: Red Card Sicrano (Flamengo).") == ("Sicrano", "Flamengo")
    validation = validar_eventos(jogo, stats, gols, cartoes)
    assert validation["ok"], validation
    manual = {**jogo, "resultado_manual": True}
    pendente = _ajustar_validacao_manual_sem_eventos(
        manual, validar_eventos(manual, [], [], []), [], [], "teste offline"
    )
    assert pendente.get("pendente_detalhes") is True and pendente.get("ok") is False, pendente
    assert _ajustar_validacao_manual_sem_eventos(
        manual, validar_eventos(manual, [], gols, []), gols, [], "não deve mascarar evento parcial"
    ).get("pendente_detalhes") is not True
    cache_game = {
        "data_iso": "2026-07-01T20:00:00-03:00",
        "mandante": {"nome": "Flamengo"}, "visitante": {"nome": "Palmeiras"},
        "placar_mandante": 1, "placar_visitante": 0,
    }
    cache_record = {
        "event_id": "123", "event_id_fonte_detalhes": "123",
        "mandante": "Flamengo", "visitante": "Palmeiras",
        "placar_mandante": 1, "placar_visitante": 0,
        "stats": [{"nome": "Posse", "home": "60%", "away": "40%"}],
        "validacao_eventos": {"ok": True},
    }
    test_now = datetime(2026, 7, 4, 20, 0, tzinfo=FUSO_BRASILIA)
    assert registro_pode_usar_cache(cache_game, cache_record, "123", 48, agora=test_now)
    assert not registro_pode_usar_cache({**cache_game, "placar_mandante": 2}, cache_record, "123", 48, agora=test_now)
    assert not registro_pode_usar_cache(cache_game, cache_record, "999", 48, agora=test_now)
    assert not registro_pode_usar_cache(cache_game, {**cache_record, "stats": []}, "123", 48, agora=test_now)
    mapa_ids = carregar_event_ids_detalhes()
    if RESULTADOS_MANUAIS.exists():
        assert mapa_ids.get("401840998") == "401879459", mapa_ids
    print("SELF-TEST OK: público, escalações, eventos, deduplicação, ID alternativo e fallback manual sem inventar detalhes.")


def _build_payload(jogos_saida: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total_com = sum(1 for j in jogos_saida.values() if j.get("stats"))
    return {
        "_comentario": "Gerado por scripts/buscar_detalhes_jogos_brasileirao.py. Gols e cartões são deduplicados e validados contra placar/boxscore.",
        "gerado_em": iso_agora_brt(),
        "fonte": "ESPN summary",
        "total_jogos": len(jogos_saida),
        "total_com_estatisticas": total_com,
        "total_com_publico": sum(1 for j in jogos_saida.values() if j.get("publico") not in (None, "")),
        "total_com_eventos": sum(1 for j in jogos_saida.values() if j.get("gols") or j.get("cartoes")),
        "total_com_jogadores": sum(1 for j in jogos_saida.values() if j.get("jogadores")),
        "total_eventos_validados": sum(1 for j in jogos_saida.values() if (j.get("validacao_eventos") or {}).get("ok")),
        "total_eventos_pendentes_detalhes": sum(
            1 for j in jogos_saida.values() if (j.get("validacao_eventos") or {}).get("pendente_detalhes") is True
        ),
        "jogos": jogos_saida,
    }


def _build_audit(
    base_resultados: dict[str, Any], resultados: list[dict[str, Any]], jogos_saida: dict[str, dict[str, Any]],
    *, buscados: int, preservados: int, falhas: list[dict[str, Any]], sem_estatisticas: list[dict[str, Any]], modo: str,
) -> dict[str, Any]:
    pendentes_detalhes = [
        {"event_id": eid, "jogo": f"{j.get('mandante')} x {j.get('visitante')}", "validacao": j.get("validacao_eventos")}
        for eid, j in jogos_saida.items()
        if (j.get("validacao_eventos") or {}).get("pendente_detalhes") is True
    ]
    inconsistencias = [
        {"event_id": eid, "jogo": f"{j.get('mandante')} x {j.get('visitante')}", "validacao": j.get("validacao_eventos")}
        for eid, j in jogos_saida.items()
        if not (j.get("validacao_eventos") or {}).get("ok")
        and not (j.get("validacao_eventos") or {}).get("pendente_detalhes")
    ]
    return {
        "gerado_em": iso_agora_brt(), "fonte": "ESPN summary", "modo": modo,
        "total_resultados_lidos": len(base_resultados.get("resultados") or []),
        "total_processados": len(resultados), "total_buscados_na_espn": buscados,
        "total_com_estatisticas": sum(1 for j in jogos_saida.values() if j.get("stats")),
        "total_com_publico": sum(1 for j in jogos_saida.values() if j.get("publico") not in (None, "")),
        "total_sem_publico": sum(1 for j in jogos_saida.values() if j.get("publico") in (None, "")),
        "total_com_eventos": sum(1 for j in jogos_saida.values() if j.get("gols") or j.get("cartoes")),
        "total_eventos_validados": sum(1 for j in jogos_saida.values() if (j.get("validacao_eventos") or {}).get("ok")),
        "total_eventos_pendentes_detalhes": len(pendentes_detalhes),
        "eventos_pendentes_detalhes": pendentes_detalhes,
        "total_inconsistencias_eventos": len(inconsistencias),
        "inconsistencias_eventos": inconsistencias,
        "total_sem_estatisticas": len(sem_estatisticas),
        "total_preservados_de_execucao_anterior": preservados,
        "total_falhas": len(falhas), "sem_estatisticas": sem_estatisticas, "falhas": falhas,
        "total_com_jogadores": sum(1 for j in jogos_saida.values() if j.get("jogadores")),
        "jogos_sem_escalacoes": [
            {"event_id": eid, "jogo": f"{j.get('mandante')} x {j.get('visitante')}"}
            for eid, j in jogos_saida.items() if not j.get("jogadores")
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca estatísticas por jogo do Brasileirão na ESPN.")
    parser.add_argument("--dry-run", action="store_true", help="Só valida entradas, sem rede e sem gravar arquivos.")
    parser.add_argument("--self-test", action="store_true", help="Executa testes internos do parser sem usar rede.")
    parser.add_argument("--reparar-local", action="store_true", help="Sanitiza o JSON atual sem acessar a rede.")
    parser.add_argument("--max-jogos", type=int, default=0, help="Limite opcional de jogos processados nesta execução.")
    parser.add_argument("--sleep", type=float, default=0.08, help="Pausa entre chamadas ESPN.")
    parser.add_argument(
        "--refresh-hours", type=float, default=48.0,
        help="Reconsulta jogos íntegros somente durante esta janela após o início; use 0 para cache imediato.",
    )
    parser.add_argument("--force-refresh", action="store_true", help="Ignora o cache incremental e reconsulta todos os jogos.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    base_resultados = carregar_json(RESULTADOS, {})
    resultados = [j for j in (base_resultados.get("resultados") or []) if jogo_finalizado(j)]
    if args.max_jogos and args.max_jogos > 0:
        resultados = resultados[: args.max_jogos]
    if args.dry_run:
        print(f"DRY-RUN OK: {len(resultados)} jogo(s) finalizado(s) elegível(is) em resultados.json")
        return

    anterior = carregar_json(SAIDA, {})
    jogos_anteriores = anterior.get("jogos") if isinstance(anterior, dict) else {}
    if not isinstance(jogos_anteriores, dict):
        jogos_anteriores = {}

    publicos_complementares = carregar_publicos_complementares()
    event_ids_detalhes = carregar_event_ids_detalhes()

    jogos_saida: dict[str, dict[str, Any]] = {}
    falhas: list[dict[str, Any]] = []
    sem_estatisticas: list[dict[str, Any]] = []
    preservados = 0
    buscados = 0

    for i, jogo in enumerate(resultados, 1):
        event_id = str(jogo.get("event_id") or "")
        if not event_id:
            continue
        event_id_fonte = event_ids_detalhes.get(event_id, event_id)
        sufixo_fonte = f" · detalhes ESPN {event_id_fonte}" if event_id_fonte != event_id else ""
        label = f"R{jogo.get('rodada')} · {(jogo.get('mandante') or {}).get('nome')} x {(jogo.get('visitante') or {}).get('nome')} · {event_id}{sufixo_fonte}"
        antigo = jogos_anteriores.get(event_id) if isinstance(jogos_anteriores, dict) else None

        if not args.force_refresh and registro_pode_usar_cache(jogo, antigo, event_id_fonte, args.refresh_hours):
            cached = dict(antigo)
            manual_publico, manual_fonte, manual_tipo = publico_complementar(event_id, publicos_complementares)
            if cached.get("publico") in (None, "", 0, "0") and manual_publico is not None:
                cached.update(publico=manual_publico, publico_fonte=manual_fonte, publico_tipo=manual_tipo)
            jogos_saida[event_id] = cached
            preservados += 1
            print(f"[{i:03d}/{len(resultados):03d}] CACHE {label}: summary final íntegro preservado")
            continue

        if args.reparar_local:
            stats = list((antigo or {}).get("stats") or (antigo or {}).get("estatisticas") or [])
            gols, cartoes, validacao = sanitizar_registro_local(jogo, antigo or {})
            jogadores = list((antigo or {}).get("jogadores") or [])
            validacao = _ajustar_validacao_manual_sem_eventos(
                jogo, validacao, gols, cartoes, "Summary ESPN ainda não disponível; resultado manual preservado."
            )
            manual_publico, manual_fonte, manual_tipo = publico_complementar(event_id, publicos_complementares)
            valor_publico = (antigo or {}).get("publico")
            fonte_publico = str((antigo or {}).get("publico_fonte") or "")
            tipo_publico = str((antigo or {}).get("publico_tipo") or "")
            if valor_publico in (None, "", 0, "0") and manual_publico is not None:
                valor_publico, fonte_publico, tipo_publico = manual_publico, manual_fonte, manual_tipo
            jogos_saida[event_id] = montar_registro(
                event_id, jogo, stats, publico=valor_publico,
                estadio=str((antigo or {}).get("estadio") or jogo.get("estadio") or ""),
                arbitro=str((antigo or {}).get("arbitro") or ""), gols=gols, cartoes=cartoes, jogadores=jogadores,
                preservado=True, validacao=validacao, publico_fonte=fonte_publico, publico_tipo=tipo_publico,
                event_id_fonte_detalhes=event_id_fonte,
            )
            print(f"[{i:03d}/{len(resultados):03d}] LOCAL {label}: gols={len(gols)} · cartões={len(cartoes)} · ok={validacao['ok']}")
            continue

        try:
            summary = fetch_json(BASE_SUMMARY.format(event_id=event_id_fonte))
            stats = parse_summary(summary, jogo)
            publico = parse_publico(summary)
            publico_fonte = "ESPN summary" if publico is not None else ""
            publico_tipo = "presente" if publico is not None else ""
            if publico is None:
                publico, publico_fonte, publico_tipo = publico_complementar(event_id, publicos_complementares)
            estadio = parse_estadio(summary, jogo)
            arbitro = parse_arbitro(summary)
            jogadores_novos = parse_jogadores(summary, jogo)
            jogadores, jogadores_preservados = escolher_jogadores(
                jogadores_novos, list((antigo or {}).get("jogadores") or [])
            )
            gols, cartoes = parse_eventos(summary, jogo, stats)
            validacao = validar_eventos(jogo, stats, gols, cartoes)
            validacao = _ajustar_validacao_manual_sem_eventos(
                jogo, validacao, gols, cartoes, "Summary ESPN respondeu sem eventos compatíveis com o placar confirmado."
            )
            buscados += 1
        except Exception as exc:  # noqa: BLE001
            stats = list((antigo or {}).get("stats") or (antigo or {}).get("estatisticas") or [])
            if antigo:
                gols, cartoes, validacao = sanitizar_registro_local(jogo, antigo)
                jogadores = list((antigo or {}).get("jogadores") or [])
                validacao = _ajustar_validacao_manual_sem_eventos(
                    jogo, validacao, gols, cartoes, f"Falha ao atualizar summary ESPN: {exc}"
                )
                preservados += 1
                manual_publico, manual_fonte, manual_tipo = publico_complementar(event_id, publicos_complementares)
                valor_publico = (antigo or {}).get("publico")
                fonte_publico = str((antigo or {}).get("publico_fonte") or "")
                tipo_publico = str((antigo or {}).get("publico_tipo") or "")
                if valor_publico in (None, "", 0, "0") and manual_publico is not None:
                    valor_publico, fonte_publico, tipo_publico = manual_publico, manual_fonte, manual_tipo
                jogos_saida[event_id] = montar_registro(
                    event_id, jogo, stats, publico=valor_publico,
                    estadio=str((antigo or {}).get("estadio") or jogo.get("estadio") or ""),
                    arbitro=str((antigo or {}).get("arbitro") or ""), gols=gols, cartoes=cartoes, jogadores=jogadores,
                    preservado=True, validacao=validacao, publico_fonte=fonte_publico, publico_tipo=tipo_publico,
                    event_id_fonte_detalhes=event_id_fonte,
                )
            else:
                if jogo.get("resultado_manual") is True:
                    sem_estatisticas.append({"event_id": event_id, "jogo": label, "motivo": "detalhes ESPN pendentes"})
                    validacao = validacao_resultado_manual_pendente(
                        jogo, f"Falha ao buscar summary ESPN: {exc}"
                    )
                    jogos_saida[event_id] = montar_registro(
                        event_id, jogo, [], validacao=validacao, event_id_fonte_detalhes=event_id_fonte
                    )
                else:
                    falhas.append({"event_id": event_id, "jogo": label, "erro": str(exc)[:300]})
                    jogos_saida[event_id] = montar_registro(
                        event_id, jogo, [], validacao=validar_eventos(jogo, [], [], []),
                        event_id_fonte_detalhes=event_id_fonte,
                    )
            print(f"[WARN] {label}: {exc}")
            time.sleep(max(0.0, args.sleep))
            continue

        if not stats:
            sem_estatisticas.append({"event_id": event_id, "jogo": label})
        jogos_saida[event_id] = montar_registro(
            event_id, jogo, stats, publico=publico, estadio=estadio, arbitro=arbitro,
            gols=gols, cartoes=cartoes, jogadores=jogadores, jogadores_preservados=jogadores_preservados,
            validacao=validacao, publico_fonte=publico_fonte, publico_tipo=publico_tipo,
            event_id_fonte_detalhes=event_id_fonte,
        )
        print(
            f"[{i:03d}/{len(resultados):03d}] {label}: {len(stats)} estatística(s) · "
            f"público={publico if publico is not None else 'n/d'} · jogadores={len(jogadores)}"
            f"{' (preservados)' if jogadores_preservados else ''} · gols={len(gols)} · cartões={len(cartoes)} · ok={validacao['ok']}"
        )
        time.sleep(max(0.0, args.sleep))

    payload = _build_payload(jogos_saida)
    auditoria = _build_audit(
        base_resultados, resultados, jogos_saida, buscados=buscados, preservados=preservados,
        falhas=falhas, sem_estatisticas=sem_estatisticas, modo="reparo-local" if args.reparar_local else "rede",
    )
    gravar_json(SAIDA, payload)
    gravar_json(AUDITORIA, auditoria)
    print(
        f"OK: {len(jogos_saida)} jogos em {SAIDA.relative_to(ROOT)}; "
        f"{payload['total_com_estatisticas']} com estatísticas e {payload['total_com_jogadores']} com escalações."
    )
    print(
        f"OK: {auditoria['total_eventos_validados']} jogos com eventos integralmente validados; "
        f"{auditoria['total_eventos_pendentes_detalhes']} com detalhes pendentes; "
        f"{auditoria['total_inconsistencias_eventos']} inconsistência(s)."
    )
    print(f"OK: auditoria em {AUDITORIA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscar_lideres_jogadores_espn.py

Busca os rankings oficiais de gols e assistências da temporada do Brasileirão
nas fontes JSON que alimentam as páginas de estatísticas da ESPN.

Saídas:
  - dados-br/lideres-jogadores.json
  - dados-br/auditoria-lideres-jogadores.json

Princípios:
  * não usa summary de partida para reconstruir a classificação da temporada;
  * tenta múltiplas rotas ESPN e múltiplos formatos de resposta;
  * preserva o último snapshot válido se a ESPN oscilar;
  * rejeita nomes contaminados por texto de narração;
  * nunca publica lista vazia ou regressão catastrófica.

Somente biblioteca padrão.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from collections import defaultdict
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atualizar_espn import ESCUDOS_TIMES, FUSO_BRASILIA, HEADERS, para_canonico  # type: ignore

TEMPORADA = int(os.environ.get("BRASILEIRAO_TEMPORADA", "2026"))
SAIDA = ROOT / "dados-br" / "lideres-jogadores.json"
AUDITORIA = ROOT / "dados-br" / "auditoria-lideres-jogadores.json"

SUSPICIOUS_NAME_TOKENS = (
    " with a ", " with the ", " cross", " right foot", " left foot", " header",
    " assisted by", " from the ", " shot", " penalty", " own goal", " attempt",
    " goal!", " substitution", " yellow card", " red card",
)

STAT_ALIASES = {
    "gols": {"goals", "goal", "gols", "gol", "total goals", "goals scored"},
    "assistencias": {"assists", "assist", "assistencias", "assistência", "assists total"},
    "jogos": {"appearances", "games played", "games", "matches", "jogos", "partidas", "apps"},
}


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def iso_agora_brt() -> str:
    return agora_brt().isoformat()


def norm(v: Any) -> str:
    s = unicodedata.normalize("NFD", str(v or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[\.,]\d+)?", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def int_num(v: Any) -> int | None:
    n = num(v)
    return None if n is None else int(round(n))


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def candidate_urls(stat: str) -> list[str]:
    sort_key = "goals" if stat == "gols" else "assists"
    q = urllib.parse.urlencode({
        "region": "br",
        "lang": "pt",
        "contentorigin": "espn",
        "isqualified": "true",
        "limit": "200",
        "sort": f"{sort_key}:desc",
        "season": str(TEMPORADA),
    })
    q_en = urllib.parse.urlencode({
        "region": "us",
        "lang": "en",
        "contentorigin": "espn",
        "isqualified": "true",
        "limit": "200",
        "sort": f"{sort_key}:desc",
        "season": str(TEMPORADA),
    })
    category = "goals" if stat == "gols" else "assists"
    common_q = urllib.parse.urlencode({
        "region": "br",
        "lang": "pt",
        "contentorigin": "espn",
        "isqualified": "true",
        "season": str(TEMPORADA),
        "limit": "200",
        "category": category,
        "sort": f"{sort_key}:desc",
    })
    # A ordem privilegia os endpoints Core API de líderes, que são mais
    # estáveis para futebol do que a antiga rota fittwo/athletes.
    return [
        f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/bra.1/seasons/{TEMPORADA}/leaders?limit=200",
        "https://sports.core.api.espn.com/v2/sports/soccer/leagues/bra.1/leaders?limit=200",
        f"https://sports.core.api.espn.com/v3/sports/soccer/bra.1/leaders?season={TEMPORADA}&limit=200",
        f"https://site.web.api.espn.com/apis/common/v3/sports/soccer/bra.1/statistics/byathlete?{common_q}",
        f"https://site.web.api.espn.com/apis/fittwo/v3/sports/soccer/bra.1/athletes?{q}",
        f"https://site.web.api.espn.com/apis/fittwo/v3/sports/soccer/bra.1/athletes?{q_en}",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/athletes?season={TEMPORADA}&limit=200&sort={urllib.parse.quote(sort_key + ':desc')}",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/leaders?season={TEMPORADA}&limit=200",
        f"https://site.web.api.espn.com/apis/v2/sports/soccer/bra.1/leaders?region=br&lang=pt&season={TEMPORADA}&limit=200",
        f"https://www.espn.com.br/futebol/estatisticas/_/liga/bra.1/temporada/{TEMPORADA}?xhr=1",
        f"https://www.espn.com/soccer/stats/_/league/bra.1/season/{TEMPORADA}?xhr=1",
    ]


def fetch_document(url: str, timeout: int = 30, attempts: int = 2) -> tuple[Any, str]:
    last: Exception | None = None
    headers = dict(HEADERS)
    headers.update({
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Referer": "https://www.espn.com.br/",
    })
    for attempt in range(1, attempts + 1):
        try:
            sep = "&" if "?" in url else "?"
            req = urllib.request.Request(f"{url}{sep}_={int(time.time())}", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout + 8 * (attempt - 1)) as resp:
                raw = resp.read()
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                if "json" in ctype or text.lstrip().startswith(("{", "[")):
                    return json.loads(text), ctype
                embedded = extract_embedded_json(text)
                if embedded:
                    return embedded, ctype or "text/html"
                raise ValueError("HTML sem JSON incorporado utilizável")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")



def _espn_ref_permitida(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "espn.com" or host.endswith(".espn.com")


def resolver_refs_espn(
    node: Any,
    cache: dict[str, Any] | None = None,
    limite: list[int] | None = None,
    profundidade: int = 0,
    chave_pai: str = "",
) -> Any:
    """Resolve apenas as referências necessárias do Core API da ESPN.

    As respostas de líderes normalmente trazem as categorias em ``items`` e
    os nomes de atleta/equipe por ``$ref``. Estatísticas secundárias também
    podem vir referenciadas; elas não são hidratadas para evitar dezenas de
    chamadas desnecessárias.
    """
    if cache is None:
        cache = {}
    if limite is None:
        limite = [0]
    if profundidade > 8:
        return node

    if isinstance(node, dict):
        ref = str(node.get("$ref") or "").strip()
        pode_resolver = (
            chave_pai in {"items", "leaders", "athlete", "player", "team", "club", "currentTeam"}
            or profundidade <= 2
        )
        if (
            ref
            and pode_resolver
            and _espn_ref_permitida(ref)
            and set(node).issubset({"$ref", "uid", "id"})
        ):
            if ref in cache:
                return cache[ref]
            if limite[0] >= 80:
                return node
            limite[0] += 1
            try:
                payload, _ = fetch_document(ref, timeout=12, attempts=1)
                cache[ref] = payload
                return resolver_refs_espn(payload, cache, limite, profundidade + 1, chave_pai)
            except Exception as exc:  # noqa: BLE001
                cache[ref] = {"$ref": ref, "_erro_ref": str(exc)[:180]}
                return cache[ref]

        return {
            key: resolver_refs_espn(value, cache, limite, profundidade + 1, key)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [resolver_refs_espn(v, cache, limite, profundidade + 1, chave_pai) for v in node]
    return node


def extract_embedded_json(text: str) -> dict[str, Any] | list[Any] | None:
    patterns = [
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        r'window\.__espn(?:fitt)?__\s*=\s*(\{.*?\})\s*;</script>',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            blob = html.unescape(match.group(1)).strip()
            try:
                data = json.loads(blob)
                if isinstance(data, (dict, list)):
                    return data
            except Exception:
                continue
    return None


def dict_name(d: dict[str, Any]) -> str:
    return str(
        d.get("displayName") or d.get("fullName") or d.get("shortDisplayName")
        or d.get("name") or d.get("shortName") or ""
    ).strip()


def athlete_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key in ("athlete", "player", "person", "participant", "competitor"):
        if isinstance(item.get(key), dict):
            candidates.append(item[key])
    candidates.append(item)
    for a in candidates:
        name = dict_name(a)
        if not name:
            continue
        aid = str(a.get("id") or a.get("athleteId") or a.get("uid") or item.get("athleteId") or "").strip()
        return {"nome": name, "athlete_id": aid, "raw": a}
    return None


def team_from_item(item: dict[str, Any], athlete_raw: dict[str, Any] | None = None) -> tuple[str, str]:
    candidates: list[Any] = []
    for source in (item, athlete_raw or {}):
        for key in ("team", "club", "currentTeam", "teamInfo"):
            if isinstance(source.get(key), dict):
                candidates.append(source[key])
        for key in ("teamName", "clubName", "teamAbbreviation", "teamId"):
            if source.get(key):
                candidates.append(source.get(key))
    for t in candidates:
        if isinstance(t, dict):
            canon = para_canonico(
                t.get("displayName"), t.get("shortDisplayName"), t.get("name"),
                t.get("location"), t.get("abbreviation"), t.get("slug"), t.get("id"),
            )
            espn_id = str(t.get("id") or t.get("uid") or "").strip()
        else:
            canon = para_canonico(t)
            espn_id = str(t or "").strip() if str(t or "").isdigit() else ""
        if canon:
            return canon, espn_id
    return "", ""


def name_matches_stat(value: Any, stat: str) -> bool:
    n = norm(value)
    return any(n == norm(alias) or norm(alias) in n for alias in STAT_ALIASES[stat])


def stat_from_node(node: Any, stat: str) -> int | None:
    aliases = STAT_ALIASES[stat]
    if isinstance(node, dict):
        # Campos diretos.
        for key, value in node.items():
            nk = norm(key)
            if any(nk == norm(a) or norm(a) in nk for a in aliases):
                if isinstance(value, dict):
                    for vk in ("value", "displayValue", "total", "count"):
                        v = int_num(value.get(vk))
                        if v is not None:
                            return v
                else:
                    v = int_num(value)
                    if v is not None:
                        return v
        # Nós de estatística nome/valor.
        label = " ".join(str(node.get(k) or "") for k in (
            "name", "displayName", "shortDisplayName", "abbreviation", "label", "type", "description"
        ))
        if name_matches_stat(label, stat):
            for key in ("value", "displayValue", "total", "count", "stat"):
                v = int_num(node.get(key))
                if v is not None:
                    return v
        # Recursão limitada às áreas estatísticas.
        for key in ("statistics", "stats", "splits", "categories", "values", "totals", "seasonTotals"):
            if key in node:
                v = stat_from_node(node[key], stat)
                if v is not None:
                    return v
    elif isinstance(node, list):
        for item in node:
            v = stat_from_node(item, stat)
            if v is not None:
                return v
    return None


def item_value(item: dict[str, Any], stat: str, category_hint: str = "") -> int | None:
    value = stat_from_node(item, stat)
    if value is not None:
        return value
    if name_matches_stat(category_hint, stat):
        for key in ("value", "displayValue", "total", "count", "stat"):
            v = int_num(item.get(key))
            if v is not None:
                return v
    return None


def walk_candidates(node: Any, stat: str, category_hint: str = "", order_counter: list[int] | None = None) -> Iterable[tuple[dict[str, Any], str, int]]:
    if order_counter is None:
        order_counter = [0]
    if isinstance(node, dict):
        local_hint = category_hint
        label = " ".join(str(node.get(k) or "") for k in (
            "name", "displayName", "shortDisplayName", "label", "description", "type"
        ))
        if name_matches_stat(label, stat):
            local_hint = label
        athlete = athlete_from_item(node)
        if athlete:
            value = item_value(node, stat, local_hint)
            if value is not None:
                order_counter[0] += 1
                yield node, local_hint, order_counter[0]
        for key, value in node.items():
            child_hint = local_hint
            if name_matches_stat(key, stat):
                child_hint = key
            yield from walk_candidates(value, stat, child_hint, order_counter)
    elif isinstance(node, list):
        for item in node:
            yield from walk_candidates(item, stat, category_hint, order_counter)


def suspicious_name(name: str) -> bool:
    n = f" {norm(name)} "
    return len(name.strip()) < 2 or any(norm(tok) in n for tok in SUSPICIOUS_NAME_TOKENS)


def extract_ranking(payload: Any, stat: str) -> list[dict[str, Any]]:
    field = "gols" if stat == "gols" else "assistencias"
    dedup: dict[str, dict[str, Any]] = {}
    for item, hint, order in walk_candidates(payload, stat):
        athlete = athlete_from_item(item)
        if not athlete:
            continue
        name = athlete["nome"].strip()
        if suspicious_name(name):
            continue
        value = item_value(item, stat, hint)
        if value is None or value < 0:
            continue
        team, team_id = team_from_item(item, athlete.get("raw"))
        if not team:
            # Não publica jogador sem clube reconhecido no Brasileirão.
            continue
        games = stat_from_node(item, "jogos")
        key = athlete.get("athlete_id") or f"{norm(name)}|{norm(team)}"
        record = {
            "posicao_fonte": order,
            "athlete_id": athlete.get("athlete_id", ""),
            "nome": name,
            "time": team,
            "team_id": team_id,
            "escudo": (ESCUDOS_TIMES.get(team) or {}).get("escudo", ""),
            "jogos": games,
            field: int(value),
        }
        if games and games > 0:
            record["media_por_jogo"] = round(float(value) / games, 3)
        old = dedup.get(key)
        if old is None or int(record[field]) > int(old[field]):
            dedup[key] = record
    ranking = list(dedup.values())
    ranking.sort(key=lambda x: (-int(x[field]), int(x.get("posicao_fonte") or 9999), norm(x["nome"])))
    for pos, item in enumerate(ranking, 1):
        item["posicao"] = pos
        item.pop("posicao_fonte", None)
    return ranking


def validate_ranking(ranking: list[dict[str, Any]], stat: str, previous: list[dict[str, Any]] | None = None) -> list[str]:
    field = "gols" if stat == "gols" else "assistencias"
    errors: list[str] = []
    min_len = 5
    if len(ranking) < min_len:
        errors.append(f"{stat}: apenas {len(ranking)} jogador(es); mínimo {min_len}")
    if ranking:
        top = int(ranking[0].get(field) or 0)
        if top <= 0:
            errors.append(f"{stat}: líder com valor não positivo")
        values = [int(x.get(field) or 0) for x in ranking]
        if values != sorted(values, reverse=True):
            errors.append(f"{stat}: ranking fora de ordem")
        if len({(norm(x.get('nome')), norm(x.get('time'))) for x in ranking}) != len(ranking):
            errors.append(f"{stat}: jogadores duplicados")
        for item in ranking[:20]:
            if suspicious_name(str(item.get("nome") or "")):
                errors.append(f"{stat}: nome suspeito: {item.get('nome')}")
            if not item.get("time"):
                errors.append(f"{stat}: jogador sem clube: {item.get('nome')}")
    if previous:
        old_top = int((previous[0] or {}).get(field) or 0) if previous else 0
        new_top = int((ranking[0] or {}).get(field) or 0) if ranking else 0
        if old_top >= 5 and new_top < max(3, int(old_top * 0.60)):
            errors.append(f"{stat}: regressão catastrófica do líder ({old_top} -> {new_top})")
        if len(previous) >= 10 and len(ranking) < max(5, len(previous) // 2):
            errors.append(f"{stat}: lista caiu de {len(previous)} para {len(ranking)}")
    return errors


def load_previous() -> dict[str, Any]:
    data = read_json(SAIDA, {})
    return data if isinstance(data, dict) else {}


def collect_one(stat: str, fixture: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    attempts_log: list[dict[str, Any]] = []
    if fixture:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        ranking = extract_ranking(payload, stat)
        return ranking, [{"url": str(fixture), "status": "fixture", "itens": len(ranking)}], str(fixture)

    best: list[dict[str, Any]] = []
    best_url = ""
    field = "gols" if stat == "gols" else "assistencias"
    target = 50 if stat == "gols" else 30
    for url in candidate_urls(stat):
        try:
            payload, ctype = fetch_document(url, timeout=14, attempts=1)
            refs_resolvidas = [0]
            payload_hidratado = resolver_refs_espn(payload, cache={}, limite=refs_resolvidas)
            ranking = extract_ranking(payload_hidratado, stat)
            attempts_log.append({
                "url": url,
                "status": "ok",
                "content_type": ctype,
                "itens_extraidos": len(ranking),
                "refs_espn_resolvidas": refs_resolvidas[0],
            })
            current_score = (len(ranking), sum(int(x.get(field) or 0) for x in ranking))
            best_score = (len(best), sum(int(x.get(field) or 0) for x in best))
            if current_score > best_score:
                best, best_url = ranking, url
            # Não aceita mais uma lista de apenas cinco como suficiente. Uma
            # fonte realmente extensa encerra a busca; caso contrário, compara
            # todas as rotas e conserva a melhor resposta.
            if len(best) >= target:
                break
        except Exception as exc:  # noqa: BLE001
            attempts_log.append({"url": url, "status": "erro", "erro": str(exc)[:300]})
    return best, attempts_log, best_url


def _name_compatible(a: Any, b: Any) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.88


def _details_payload() -> dict[str, Any]:
    data = read_json(ROOT / "dados-br" / "jogos-detalhes.json", {})
    return data if isinstance(data, dict) else {}


def aggregate_from_details(stat: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reconstrói a lista completa a partir de eventos de jogos já validados."""
    data = _details_payload()
    games = data.get("jogos") or {}
    if not isinstance(games, dict):
        games = {}
    field = "gols" if stat == "gols" else "assistencias"
    counts: dict[tuple[str, str], int] = defaultdict(int)
    display: dict[tuple[str, str], tuple[str, str]] = {}
    match_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    ignored_own_goals = 0
    invalid_games = 0

    for event_id, game in games.items():
        if not isinstance(game, dict):
            continue
        if not (game.get("validacao_eventos") or {}).get("gols_ok", True):
            invalid_games += 1
            continue
        for goal in game.get("gols") or []:
            if not isinstance(goal, dict):
                continue
            description = str(goal.get("descricao") or "")
            team = para_canonico(goal.get("time")) or str(goal.get("time") or "").strip()
            if not team:
                continue
            if stat == "gols":
                if "own goal" in description.lower() or "gol contra" in norm(description):
                    ignored_own_goals += 1
                    continue
                names = [str(goal.get("jogador") or "").strip()]
            else:
                names = [str(x or "").strip() for x in goal.get("assistencias") or []]
            for name in names:
                if not name or suspicious_name(name):
                    continue
                key = (norm(name), norm(team))
                counts[key] += 1
                display.setdefault(key, (name, team))
                match_ids[key].add(str(event_id))

    ranking: list[dict[str, Any]] = []
    for key, value in counts.items():
        name, team = display[key]
        ranking.append({
            "athlete_id": "",
            "nome": name,
            "time": team,
            "team_id": "",
            "escudo": (ESCUDOS_TIMES.get(team) or {}).get("escudo", ""),
            "jogos": 0,
            field: int(value),
            "jogos_com_participacao": len(match_ids[key]),
            "origem_complementar": "eventos validados das partidas",
        })
    ranking.sort(key=lambda x: (-int(x[field]), norm(x["nome"]), norm(x["time"])))
    for pos, item in enumerate(ranking, 1):
        item["posicao"] = pos
    audit = {
        "jogos_lidos": len(games),
        "jogos_invalidos_ignorados": invalid_games,
        "jogadores": len(ranking),
        "total_eventos_contabilizados": sum(counts.values()),
        "gols_contra_ignorados": ignored_own_goals if stat == "gols" else 0,
    }
    return ranking, audit


def merge_local_as_primary(
    local: list[dict[str, Any]], official: list[dict[str, Any]], stat: str
) -> list[dict[str, Any]]:
    """Reconstrução dos eventos das partidas é a FONTE PRIMÁRIA dos contadores.

    O ranking oficial da ESPN entra apenas como enriquecedor de metadados
    (athlete_id, team_id, escudo e jogos disputados). Assim, se a ESPN vier
    com dados congelados/desatualizados (comportamento observado a partir de
    julho/2026), a lista publicada continua correta porque reflete todos os
    gols e assistências validados jogo a jogo.

    Compatível com a saída anterior — mesmas chaves (posicao, nome, time,
    escudo, jogos, gols/assistencias, media_por_jogo) esperadas pelo frontend.
    """
    field = "gols" if stat == "gols" else "assistencias"
    used_official: set[int] = set()
    merged: list[dict[str, Any]] = []

    for local_row in local:
        team = para_canonico(local_row.get("time")) or str(local_row.get("time") or "")
        row = dict(local_row)
        row["time"] = team
        row["escudo"] = row.get("escudo") or (ESCUDOS_TIMES.get(team) or {}).get("escudo", "")

        # Procura correspondente na lista oficial (mesmo time + nome compatível)
        # para enriquecer metadados; NÃO usa o valor do contador da oficial.
        candidates = [
            (idx, off) for idx, off in enumerate(official)
            if idx not in used_official
            and norm(para_canonico(off.get("time")) or off.get("time")) == norm(team)
            and _name_compatible(off.get("nome"), row.get("nome"))
        ]
        if candidates:
            idx, off = candidates[0]
            used_official.add(idx)
            # Enriquecimento seletivo: só sobrescreve campos vazios do local.
            if off.get("athlete_id"):
                row["athlete_id"] = off.get("athlete_id")
            if off.get("team_id"):
                row["team_id"] = off.get("team_id")
            if not row.get("escudo") and off.get("escudo"):
                row["escudo"] = off.get("escudo")
            # jogos disputados: oficial costuma ter esse total; só usa se >0.
            off_jogos = int(off.get("jogos") or 0)
            if off_jogos > 0:
                row["jogos"] = off_jogos
            row["origem_complementar"] = "eventos das partidas · metadados enriquecidos pela ESPN"
        else:
            row["origem_complementar"] = "eventos das partidas"

        merged.append(row)

    # Deduplicação defensiva por (nome_normalizado, time_normalizado)
    dedup: list[dict[str, Any]] = []
    for row in sorted(merged, key=lambda x: (-int(x.get(field) or 0), norm(x.get("nome")), norm(x.get("time")))):
        duplicate = next(
            (x for x in dedup
             if norm(x.get("time")) == norm(row.get("time"))
             and _name_compatible(x.get("nome"), row.get("nome"))),
            None,
        )
        if duplicate is None:
            dedup.append(row)
        elif int(row.get(field) or 0) > int(duplicate.get(field) or 0):
            duplicate.update(row)

    dedup.sort(key=lambda x: (-int(x.get(field) or 0), norm(x.get("nome")), norm(x.get("time"))))
    for pos, item in enumerate(dedup, 1):
        item["posicao"] = pos
        games = int(item.get("jogos") or 0)
        participation_games = int(item.get("jogos_com_participacao") or 0)
        if games <= 0 and participation_games > 0:
            item["jogos"] = participation_games
            games = participation_games
            item["origem_jogos"] = "mínimo validado pelos eventos das partidas (fallback)"
        if games > 0:
            item["media_por_jogo"] = round(int(item.get(field) or 0) / games, 3)
        else:
            item.pop("media_por_jogo", None)
    return dedup


def merge_official_and_local(
    official: list[dict[str, Any]], local: list[dict[str, Any]], stat: str
) -> list[dict[str, Any]]:
    field = "gols" if stat == "gols" else "assistencias"
    used_local: set[int] = set()
    merged: list[dict[str, Any]] = []

    for off in official:
        team = para_canonico(off.get("time")) or str(off.get("time") or "")
        candidates = [
            (idx, row) for idx, row in enumerate(local)
            if idx not in used_local
            and norm(para_canonico(row.get("time")) or row.get("time")) == norm(team)
            and _name_compatible(off.get("nome"), row.get("nome"))
        ]
        candidates.sort(key=lambda pair: (
            0 if norm(pair[1].get("nome")) == norm(off.get("nome")) else 1,
            -int(pair[1].get(field) or 0),
        ))
        row = dict(off)
        if candidates:
            idx, local_row = candidates[0]
            used_local.add(idx)
            # O ranking oficial define nome canônico/quantidade; os eventos
            # garantem que o jogador continue na lista completa.
            row["jogos_com_participacao"] = local_row.get("jogos_com_participacao", 0)
            row["origem_complementar"] = "ranking ESPN conferido nos eventos"
        row["time"] = team
        row["escudo"] = row.get("escudo") or (ESCUDOS_TIMES.get(team) or {}).get("escudo", "")
        merged.append(row)

    for idx, row in enumerate(local):
        if idx in used_local:
            continue
        merged.append(dict(row))

    # Deduplicação defensiva após aliases oficiais/local.
    dedup: list[dict[str, Any]] = []
    for row in sorted(merged, key=lambda x: (-int(x.get(field) or 0), norm(x.get("nome")), norm(x.get("time")))):
        duplicate = next((x for x in dedup if norm(x.get("time")) == norm(row.get("time")) and _name_compatible(x.get("nome"), row.get("nome"))), None)
        if duplicate is None:
            dedup.append(row)
        elif int(row.get(field) or 0) > int(duplicate.get(field) or 0):
            duplicate.update(row)

    dedup.sort(key=lambda x: (-int(x.get(field) or 0), norm(x.get("nome")), norm(x.get("time"))))
    for pos, item in enumerate(dedup, 1):
        item["posicao"] = pos
        games = int(item.get("jogos") or 0)
        participation_games = int(item.get("jogos_com_participacao") or 0)
        if games <= 0 and participation_games > 0:
            item["jogos"] = participation_games
            games = participation_games
            item["origem_jogos"] = "mínimo validado pelos eventos das partidas (fallback)"
        if games > 0:
            item["media_por_jogo"] = round(int(item.get(field) or 0) / games, 3)
        else:
            item.pop("media_por_jogo", None)
    return dedup


def validate_completeness(ranking: list[dict[str, Any]], stat: str, local_audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    games = int(local_audit.get("jogos_lidos") or 0)
    min_len = 5
    if games >= 50:
        min_len = 40 if stat == "gols" else 20
    elif games >= 15:
        min_len = 15 if stat == "gols" else 8
    if len(ranking) < min_len:
        errors.append(f"{stat}: lista completa tem apenas {len(ranking)} nomes; esperado ao menos {min_len} para {games} jogos")
    if stat == "gols":
        local_total = int(local_audit.get("total_eventos_contabilizados") or 0)
        merged_total = sum(int(x.get("gols") or 0) for x in ranking)
        # O total oficial pode variar por aliases, mas não pode sofrer truncamento maciço.
        if local_total and merged_total < int(local_total * 0.90):
            errors.append(f"gols: cobertura insuficiente ({merged_total}/{local_total})")
    return errors

def self_test() -> None:
    fixture = {
        "categories": [
            {
                "name": "goals",
                "leaders": [
                    {"value": 11, "athlete": {"id": "1", "displayName": "Kevin Viveros"}, "team": {"displayName": "Athletico Paranaense"}, "statistics": [{"name": "appearances", "value": 17}]},
                    {"value": 10, "athlete": {"id": "2", "displayName": "Pedro"}, "team": {"displayName": "Flamengo"}, "statistics": [{"name": "appearances", "value": 17}]},
                    {"value": 9, "athlete": {"id": "3", "displayName": "Carlos Vinícius"}, "team": {"displayName": "Grêmio"}},
                    {"value": 9, "athlete": {"id": "4", "displayName": "John Kennedy"}, "team": {"displayName": "Fluminense"}},
                    {"value": 8, "athlete": {"id": "5", "displayName": "Breno"}, "team": {"displayName": "Coritiba"}},
                ],
            },
            {
                "name": "assists",
                "leaders": [
                    {"value": 8, "athlete": {"id": "6", "displayName": "Jogador A"}, "team": {"displayName": "Palmeiras"}},
                    {"value": 7, "athlete": {"id": "7", "displayName": "Jogador B"}, "team": {"displayName": "Bahia"}},
                    {"value": 6, "athlete": {"id": "8", "displayName": "Jogador C"}, "team": {"displayName": "Santos"}},
                    {"value": 5, "athlete": {"id": "9", "displayName": "Jogador D"}, "team": {"displayName": "Cruzeiro"}},
                    {"value": 4, "athlete": {"id": "10", "displayName": "Jogador E"}, "team": {"displayName": "Botafogo"}},
                ],
            },
        ]
    }
    goals = extract_ranking(fixture, "gols")
    assists = extract_ranking(fixture, "assistencias")
    assert [x["gols"] for x in goals[:5]] == [11, 10, 9, 9, 8]
    assert goals[0]["time"] == "Athletico-PR"
    assert goals[0]["jogos"] == 17
    assert [x["assistencias"] for x in assists[:5]] == [8, 7, 6, 5, 4]
    assert not validate_ranking(goals, "gols")
    assert not validate_ranking(assists, "assistencias")
    contaminated = {
        "categories": [{"name": "assists", "leaders": [
            {"value": 5, "athlete": {"displayName": "Renan Lodi with a cross"}, "team": {"displayName": "Atlético Mineiro"}}
        ]}]
    }
    assert not extract_ranking(contaminated, "assistencias")
    print("SELF-TEST OK: parser de líderes, aliases, jogos e bloqueio de nomes contaminados.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca e completa artilharia e assistências da ESPN.")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--fixture-gols", type=Path)
    parser.add_argument("--fixture-assistencias", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconstruir-local", action="store_true", help="Completa os rankings usando o snapshot atual e eventos locais, sem rede.")
    parser.add_argument(
        "--nao-falhar-sem-snapshot", action="store_true",
        help="Grava a auditoria e encerra com código 0 quando ainda não houver base válida.",
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    previous = load_previous()
    prev_goals = list(previous.get("artilharia") or [])
    prev_assists = list(previous.get("assistencias") or [])

    if args.reconstruir_local:
        collected_goals, log_goals, source_goals = prev_goals, [{"status": "snapshot-local", "itens": len(prev_goals)}], "snapshot anterior"
        collected_assists, log_assists, source_assists = prev_assists, [{"status": "snapshot-local", "itens": len(prev_assists)}], "snapshot anterior"
    else:
        collected_goals, log_goals, source_goals = collect_one("gols", args.fixture_gols)
        collected_assists, log_assists, source_assists = collect_one("assistencias", args.fixture_assistencias)

    errors_new_goals = validate_ranking(collected_goals, "gols", prev_goals) if collected_goals else ["gols: nenhuma lista oficial coletada"]
    errors_new_assists = validate_ranking(collected_assists, "assistencias", prev_assists) if collected_assists else ["assistencias: nenhuma lista oficial coletada"]
    official_goals = collected_goals if not errors_new_goals else prev_goals
    official_assists = collected_assists if not errors_new_assists else prev_assists
    used_previous = {
        "artilharia": official_goals is prev_goals or args.reconstruir_local,
        "assistencias": official_assists is prev_assists or args.reconstruir_local,
    }

    local_goals, local_audit_goals = aggregate_from_details("gols")
    local_assists, local_audit_assists = aggregate_from_details("assistencias")
    # A lista LOCAL (reconstruída dos eventos das partidas) é a fonte primária
    # dos contadores. A ESPN entra apenas como enriquecedor de metadados.
    goals = merge_local_as_primary(local_goals, official_goals, "gols")
    assists = merge_local_as_primary(local_assists, official_assists, "assistencias")

    final_errors = (
        validate_ranking(goals, "gols") + validate_ranking(assists, "assistencias")
        + validate_completeness(goals, "gols", local_audit_goals)
        + validate_completeness(assists, "assistencias", local_audit_assists)
    )
    status = "valido" if not final_errors else "invalido"
    completeness = {
        "artilharia": {**local_audit_goals, "jogadores_publicados": len(goals)},
        "assistencias": {**local_audit_assists, "jogadores_publicados": len(assists)},
    }

    audit = {
        "gerado_em": iso_agora_brt(), "temporada": TEMPORADA, "status": status,
        "resumo": {
            "artilheiros": len(goals), "assistentes": len(assists),
            "lider_gols": goals[0] if goals else None,
            "lider_assistencias": assists[0] if assists else None,
            "preservado_de_execucao_anterior": used_previous,
            "completude": completeness,
        },
        "fonte_aceita": {"artilharia": source_goals, "assistencias": source_assists},
        "tentativas": {"artilharia": log_goals, "assistencias": log_assists},
        "erros_nova_coleta": {"artilharia": errors_new_goals, "assistencias": errors_new_assists},
        "erros_finais": final_errors,
        "nomes_suspeitos": [x.get("nome") for x in goals + assists if suspicious_name(str(x.get("nome") or ""))],
    }

    if args.dry_run:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        if final_errors:
            raise SystemExit(2)
        return

    write_json_atomic(AUDITORIA, audit)
    if final_errors:
        if args.nao_falhar_sem_snapshot:
            print("AVISO: coleta de líderes ainda inválida; auditoria gravada.")
            print(" | ".join(final_errors))
            return
        raise RuntimeError("Coleta de líderes inválida: " + " | ".join(final_errors))

    payload = {
        "atualizado_em": iso_agora_brt(), "temporada": TEMPORADA,
        "fonte": "Eventos das partidas (ESPN summary) · metadados enriquecidos pelo ranking oficial da ESPN",
        "metodologia": "Reconstrói artilharia e assistências contando cada gol e assistência validados jogo a jogo (fonte primária). O ranking oficial da ESPN é consultado apenas para enriquecer identificadores, escudo e jogos disputados; nunca sobrescreve o contador reconstruído.",
        "status": "valido", "preservado_de_execucao_anterior": used_previous,
        "fonte_aceita": {"artilharia": source_goals, "assistencias": source_assists},
        "completude": completeness,
        "artilharia": goals, "assistencias": assists,
    }
    write_json_atomic(SAIDA, payload)
    print(f"OK: {len(goals)} artilheiros e {len(assists)} assistentes em {SAIDA.relative_to(ROOT)}")
    print(f"OK: auditoria em {AUDITORIA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

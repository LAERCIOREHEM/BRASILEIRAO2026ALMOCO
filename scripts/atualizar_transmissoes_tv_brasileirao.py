#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consolida transmissões oficiais do Brasileirão Série A.

Fontes automáticas, independentes e auditáveis:
1. CBF — tabela detalhada oficial (autoridade para grade de transmissão);
2. GE Agenda — dados estruturados/JavaScript embutido e texto renderizável;
3. GE — guias editoriais recentes de rodada/"onde assistir";
4. ESPN — scoreboard e summary individual como complemento;
5. transmissoes.json — correção editorial manual de última instância.

Princípios:
- nenhuma resposta vazia apaga informação válida já publicada;
- canais só são publicados quando pertencem à lista oficial permitida;
- cada jogo guarda evidências e fontes de onde os canais vieram;
- a saída só muda quando há mudança semântica real;
- o arquivo de auditoria registra cobertura, falhas e jogos críticos sem canal.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atualizar_espn import para_canonico  # noqa: E402
from fontes_brasileirao import CBFPartida, buscar_tabela_detalhada_cbf, localizar_partida_cbf  # noqa: E402

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/summary"
GE_AGENDA = "https://ge.globo.com/agenda/"
GE_BRASILEIRAO = "https://ge.globo.com/futebol/brasileirao-serie-a/"

AGENDA = ROOT / "jogos.json"
OUTPUT = ROOT / "dados-br" / "transmissoes-tv.json"
AUDIT_OUTPUT = ROOT / "dados-br" / "auditoria-transmissoes-tv.json"
CONFIG_PATH = ROOT / "dados-br" / "config-transmissoes-tv.json"
MANUAL = ROOT / "transmissoes.json"

PROVIDERS: list[tuple[str, tuple[str, ...]]] = [
    ("Premiere", ("premiere", "premiere clubes")),
    ("SporTV", ("sportv", "sport tv", "sportv 1", "sportv 2", "sportv 3")),
    ("Disney+ / ESPN", ("disney+", "disney plus", "espn", "espn brasil")),
    ("Prime Video", ("prime video", "amazon prime", "amazon prime video")),
    ("Globo", ("tv globo", "rede globo", "globo")),
    ("Record", ("record", "record tv", "recordtv")),
    ("GE TV", ("ge tv", "getv", "ge-tv")),
    ("CazéTV", ("cazetv", "caze tv", "cazé tv", "youtube cazetv", "youtube / caze tv")),
]
ALLOWED_CHANNELS = {label for label, _ in PROVIDERS}

DEFAULT_CONFIG: dict[str, Any] = {
    "janela_passado_dias": 2,
    "janela_futuro_dias": 35,
    "janela_critica_horas": 72,
    "janela_aviso_dias": 14,
    "preservar_apos_jogo_horas": 6,
    "ge_agenda_url": GE_AGENDA,
    "ge_brasileirao_url": GE_BRASILEIRAO,
    "ge_max_artigos": 12,
    "ge_paginas_feed": 2,
    "timeout_segundos": 30,
    "tentativas_rede": 3,
    "habilitar_ge_agenda": True,
    "habilitar_ge_artigos": True,
    "habilitar_espn_summary": True,
}

TEAM_ALIASES = {
    "athletico": "athletico pr", "athletico paranaense": "athletico pr", "atletico pr": "athletico pr",
    "atletico mineiro": "atletico mg", "clube atletico mineiro": "atletico mg",
    "red bull bragantino": "bragantino", "rb bragantino": "bragantino",
    "vasco": "vasco da gama", "cr vasco da gama": "vasco da gama", "vasco da gama saf": "vasco da gama",
    "ec bahia": "bahia", "ec vitoria": "vitoria", "sao paulo fc": "sao paulo",
    "gremio fbpa": "gremio", "sc internacional": "internacional", "clube do remo": "remo",
    "santos fc": "santos", "coritiba saf": "coritiba", "red bull bragantino saf": "bragantino",
}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("&", " e ")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def team_key(value: Any) -> str:
    key = norm(value)
    return TEAM_ALIASES.get(key, key)


def parse_dt(value: Any) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        obj = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if obj.tzinfo is None:
        obj = obj.replace(tzinfo=TZ)
    return obj.astimezone(TZ)


def iso_now(now: dt.datetime) -> str:
    return now.astimezone(TZ).replace(microsecond=0).isoformat()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(fallback)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON inválido em {path}: {exc}") from exc


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def semantic_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: semantic_payload(v)
            for k, v in value.items()
            if k not in {"atualizado_em", "consultado_em", "duracao_ms"}
        }
    if isinstance(value, list):
        return [semantic_payload(v) for v in value]
    return value


def canonical_closed_channel(value: Any) -> Optional[str]:
    wanted = norm(value)
    if not wanted:
        return None
    for label, aliases in PROVIDERS:
        for candidate in (label, *aliases):
            c = norm(candidate)
            if wanted == c or re.search(r"(?:^|\s)" + re.escape(c) + r"(?:\s|$)", wanted):
                return label
    return None


def extract_channels(value: Any) -> list[str]:
    """Extrai canais preservando a ordem em que aparecem na fonte.

    URLs são removidas antes da detecção para impedir falsos positivos como
    ``ge.globo.com`` sendo interpretado como transmissão da TV Globo.
    """
    texts: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            texts.append(html.unescape(node))
            return
        if isinstance(node, Mapping):
            for key, item in node.items():
                key_n = norm(key)
                if key_n in {
                    "name", "shortname", "displayname", "network", "callletters", "names",
                    "broadcast", "broadcasts", "geobroadcasts", "media", "channel", "channels",
                    "transmissao", "transmission", "where to watch", "wheretowatch", "onde assistir",
                    "ondeassistir", "tv", "streaming", "watch", "watchproviders",
                }:
                    walk(item)
                elif isinstance(item, (Mapping, list, tuple)):
                    walk(item)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)
            return
        texts.append(str(node))

    walk(value)
    ordered: list[tuple[int, int, str]] = []
    offset = 0
    for text in texts:
        cleaned = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.I)
        hay = norm(cleaned)
        for provider_index, (label, aliases) in enumerate(PROVIDERS):
            best_position: Optional[int] = None
            for alias in (label, *aliases):
                match = re.search(r"(?:^|\s)" + re.escape(norm(alias)) + r"(?:\s|$)", hay)
                if match and (best_position is None or match.start() < best_position):
                    best_position = match.start()
            if best_position is not None:
                ordered.append((offset + best_position, provider_index, label))
        offset += len(hay) + 1

    out: list[str] = []
    for _, _, label in sorted(ordered):
        if label not in out:
            out.append(label)
    return out


def game_team_name(game: Mapping[str, Any], side: str) -> str:
    value = game.get(side)
    if isinstance(value, Mapping):
        return str(value.get("nome") or value.get("displayName") or value.get("name") or "")
    return str(value or "")


def agenda_games(agenda: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = agenda.get("jogos") or []
    return [dict(item) for item in values if isinstance(item, Mapping)]


def in_collection_window(game: Mapping[str, Any], now: dt.datetime, cfg: Mapping[str, Any]) -> bool:
    kickoff = parse_dt(game.get("data_iso"))
    if not kickoff:
        return True
    start = now - dt.timedelta(days=int(cfg.get("janela_passado_dias") or 2))
    end = now + dt.timedelta(days=int(cfg.get("janela_futuro_dias") or 35))
    return start <= kickoff <= end


def match_game(
    games: Sequence[Mapping[str, Any]],
    *,
    event_id: str = "",
    home: str = "",
    away: str = "",
    rodada: int = 0,
    data_iso: str = "",
) -> Optional[Mapping[str, Any]]:
    eid = str(event_id or "").strip()
    if eid:
        for game in games:
            if str(game.get("event_id") or game.get("id") or "") == eid:
                return game
    hk, ak = team_key(home), team_key(away)
    target_dt = parse_dt(data_iso)
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for game in games:
        if hk and team_key(game_team_name(game, "mandante")) != hk:
            continue
        if ak and team_key(game_team_name(game, "visitante")) != ak:
            continue
        if rodada and int(game.get("rodada") or 0) != rodada:
            continue
        game_dt = parse_dt(game.get("data_iso"))
        distance = 0.0
        if target_dt and game_dt:
            distance = abs((game_dt - target_dt).total_seconds())
            if distance > 48 * 3600:
                continue
        candidates.append((distance, game))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


@dataclass
class Evidence:
    source: str
    channels: list[str]
    reference: str = ""
    captured_at: str = ""
    authority: int = 0
    detail: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "fonte": self.source,
            "canais": self.channels,
            "referencia": self.reference,
            "capturado_em": self.captured_at,
            "autoridade": self.authority,
            "detalhe": self.detail,
        }


class _ScriptAndLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._in_script = False
        self._script: list[str] = []
        self._anchor_href = ""
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_map = dict(attrs)
        if tag.lower() == "script":
            self._in_script = True
            self._script = []
        elif tag.lower() == "a":
            self._anchor_href = str(attrs_map.get("href") or "")
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.scripts.append("".join(self._script))
            self._in_script = False
            self._script = []
        elif tag.lower() == "a" and self._anchor_href:
            self.links.append((self._anchor_href, " ".join(self._anchor_text)))
            self._anchor_href = ""
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script.append(data)
        else:
            self.text_parts.append(data)
            if self._anchor_href:
                self._anchor_text.append(data)

    def visible_text(self) -> str:
        return re.sub(r"\s+", " ", html.unescape(" ".join(self.text_parts))).strip()


def fetch_text(url: str, *, timeout: int, attempts: int) -> str:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        cache_url = url + ("&" if "?" in url else "?") + f"_={int(time.time())}"
        attempt_errors: list[str] = []

        # GE usa proteção CDN que responde melhor ao fingerprint do Chrome.
        # Uma falha no cliente impersonado não impede o fallback por urllib.
        try:
            from curl_cffi import requests as curl_requests  # type: ignore

            response = curl_requests.get(
                cache_url,
                impersonate="chrome",
                timeout=timeout + attempt * 5,
                headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
            )
            response.raise_for_status()
            return response.text
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            attempt_errors.append(f"curl_cffi={type(exc).__name__}: {exc}")

        try:
            request = urllib.request.Request(
                cache_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout + attempt * 5) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001
            attempt_errors.append(f"urllib={type(exc).__name__}: {exc}")

        errors.append(f"tentativa {attempt}: " + " | ".join(attempt_errors))
        if attempt < attempts:
            time.sleep(min(8, attempt * 2))
    raise RuntimeError(f"falha ao buscar {url}: " + " | ".join(errors))


def fetch_json(url: str, *, timeout: int, attempts: int) -> dict[str, Any]:
    raw = fetch_text(url, timeout=timeout, attempts=attempts)
    return json.loads(raw)


def balanced_json_fragments(script: str) -> Iterator[str]:
    """Extrai apenas objetos de topo plausíveis, com custo rigidamente limitado.

    Procurar a partir de toda chave interna de um bundle JavaScript torna o
    processamento quadrático. Aqui são considerados somente o início do script
    e estruturas logo após atribuições/separadores, suficientes para os estados
    serializados usados por páginas editoriais.
    """
    starts: list[int] = []
    stripped_offset = len(script) - len(script.lstrip())
    if script.lstrip().startswith(("{", "[")):
        starts.append(stripped_offset)
    for match in re.finditer(r"(?:=|:|\()\s*([\[{])", script):
        starts.append(match.start(1))
        if len(starts) >= 80:
            break
    seen_starts: set[int] = set()
    for start in starts:
        if start in seen_starts:
            continue
        seen_starts.add(start)
        stack: list[str] = []
        quote = ""
        escaped = False
        for idx in range(start, min(len(script), start + 600_000)):
            ch = script[idx]
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = ""
                continue
            if ch in {'"', "'"}:
                quote = ch
                continue
            if ch in "[{":
                stack.append(ch)
            elif ch in "]}":
                if not stack:
                    break
                opening = stack.pop()
                if (opening, ch) not in {("[", "]"), ("{", "}")}:
                    break
                if not stack:
                    fragment = script[start:idx + 1]
                    if len(fragment) >= 20:
                        yield fragment
                    break


def json_candidates_from_html(page: str) -> list[Any]:
    parser = _ScriptAndLinkParser()
    parser.feed(page)
    parser.close()
    out: list[Any] = []
    seen: set[str] = set()
    for script in parser.scripts:
        stripped = script.strip()
        direct = [stripped] if stripped.startswith(("{", "[")) else []
        for fragment in direct + list(balanced_json_fragments(script)):
            # Converte apenas JSON real. Objetos JavaScript com funções são ignorados.
            try:
                obj = json.loads(fragment)
            except Exception:
                continue
            marker = json.dumps(obj, sort_keys=True, ensure_ascii=False)[:2000]
            if marker not in seen:
                out.append(obj)
                seen.add(marker)
            if len(out) >= 100:
                return out
    return out


def flatten_text(node: Any, *, max_chars: int = 20000) -> str:
    values: list[str] = []
    used = 0

    def add(text: str) -> None:
        nonlocal used
        if used >= max_chars:
            return
        piece = text[: max_chars - used]
        values.append(piece)
        used += len(piece)

    def walk(value: Any) -> None:
        if used >= max_chars or value is None:
            return
        if isinstance(value, str):
            add(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, (int, float)):
            add(str(value))

    walk(node)
    return " ".join(values)


def strings_for_team(value: str) -> list[str]:
    key = team_key(value)
    out = {key, norm(value)}
    for alias, canonical in TEAM_ALIASES.items():
        if canonical == key:
            out.add(alias)
    # Palavras muito curtas geram falsos positivos em JSON minificado.
    return sorted((item for item in out if len(item) >= 4), key=len, reverse=True)


def text_contains_game(text: str, home: str, away: str) -> bool:
    n = norm(text)
    return any(alias in n for alias in strings_for_team(home)) and any(alias in n for alias in strings_for_team(away))


def channels_near_game(raw_text: str, home: str, away: str, *, radius: int = 1400) -> list[str]:
    """Procura canais em uma janela curta ao redor do par de clubes mais próximo."""
    text = html.unescape(raw_text).replace("\\u002F", "/").replace("\\u0026", "&")
    ntext = norm(text)
    home_aliases = strings_for_team(home)
    away_aliases = strings_for_team(away)
    positions_h = [ntext.find(a) for a in home_aliases if ntext.find(a) >= 0]
    positions_a = [ntext.find(a) for a in away_aliases if ntext.find(a) >= 0]
    if not positions_h or not positions_a:
        return []
    best: Optional[tuple[int, int, int]] = None
    for hp in positions_h:
        for ap in positions_a:
            distance = abs(hp - ap)
            if best is None or distance < best[0]:
                best = (distance, hp, ap)
    if not best or best[0] > radius:
        return []
    _, hp, ap = best
    start = max(0, min(hp, ap) - 300)
    end = min(len(ntext), max(hp, ap) + 850)
    return extract_channels(ntext[start:end])


def iter_json_nodes(node: Any) -> Iterator[Any]:
    """Percorre primeiro os nós menores para isolar um único evento do GE."""
    if isinstance(node, Mapping):
        for value in node.values():
            if isinstance(value, (Mapping, list, tuple)):
                yield from iter_json_nodes(value)
        yield node
    elif isinstance(node, (list, tuple)):
        for value in node:
            if isinstance(value, (Mapping, list, tuple)):
                yield from iter_json_nodes(value)
        yield node


def structured_channels_for_game(json_blobs: Sequence[Any], home: str, away: str) -> list[str]:
    """Seleciona o menor objeto JSON que contém os dois clubes e um provedor."""
    matches: list[tuple[int, list[str]]] = []
    for blob in json_blobs:
        for node in iter_json_nodes(blob):
            text = flatten_text(node, max_chars=8000)
            if not text_contains_game(text, home, away):
                continue
            channels = extract_channels(node)
            if channels:
                matches.append((len(norm(text)), channels))
    if not matches:
        return []
    shortest = min(size for size, _ in matches)
    out: list[str] = []
    # Empates de tamanho podem representar campos complementares do mesmo evento.
    for size, channels in matches:
        if size > shortest + 2:
            continue
        for channel in channels:
            if channel not in out:
                out.append(channel)
    return out


def ge_entries_from_page(
    page: str,
    games: Sequence[Mapping[str, Any]],
    *,
    source_name: str,
    reference: str,
    captured_at: str,
    authority: int,
) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    parser = _ScriptAndLinkParser()
    parser.feed(page)
    parser.close()
    searchable = "\n".join(parser.scripts) + "\n" + parser.visible_text()
    json_blobs = json_candidates_from_html(page)

    for game in games:
        event_id = str(game.get("event_id") or game.get("id") or "")
        if not event_id:
            continue
        home = game_team_name(game, "mandante")
        away = game_team_name(game, "visitante")
        channels = structured_channels_for_game(json_blobs, home, away)
        # Conteúdo editorial sem JSON estruturado continua coberto por uma janela
        # curta em torno do confronto. Não misturamos essa leitura quando um nó
        # estruturado já foi localizado.
        if not channels:
            channels = channels_near_game(searchable, home, away)
        if channels:
            out.setdefault(event_id, []).append(Evidence(
                source=source_name,
                channels=channels,
                reference=reference,
                captured_at=captured_at,
                authority=authority,
                detail="clubes e provedores identificados no mesmo bloco de conteúdo",
            ))
    return out


def article_links_from_page(page: str, base_url: str, limit: int) -> list[str]:
    parser = _ScriptAndLinkParser()
    parser.feed(page)
    parser.close()
    candidates: list[str] = []
    for href, anchor in parser.links:
        absolute = urllib.parse.urljoin(base_url, href)
        if not absolute.startswith("https://ge.globo.com/") or not absolute.endswith(".ghtml"):
            continue
        label = norm(anchor + " " + absolute)
        if any(term in label for term in (
            "onde assistir", "transmissao", "transmissoes", "jogos da rodada", "brasileirao 2026 veja",
        )) and absolute not in candidates:
            candidates.append(absolute)
    # Também reconhece links embutidos em JSON/minificação.
    for url in re.findall(r"https?:\\?/\\?/ge\.globo\.com/[^\"'<> ]+?\.ghtml", page):
        cleaned = url.replace("\\/", "/")
        label = norm(cleaned)
        if any(term in label for term in ("onde assistir", "transmiss", "rodada")) and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates[:limit]


def merge_evidence(target: dict[str, list[Evidence]], source: Mapping[str, Sequence[Evidence]]) -> None:
    for event_id, evidences in source.items():
        bucket = target.setdefault(str(event_id), [])
        fingerprints = {(e.source, tuple(e.channels), e.reference) for e in bucket}
        for evidence in evidences:
            fp = (evidence.source, tuple(evidence.channels), evidence.reference)
            if fp not in fingerprints:
                bucket.append(evidence)
                fingerprints.add(fp)


def espn_broadcasts(event: Mapping[str, Any]) -> list[str]:
    comp = ((event.get("competitions") or [{}])[0]) or {}
    return extract_channels({
        "competition": {k: comp.get(k) for k in ("broadcasts", "geoBroadcasts", "media")},
        "event": {k: event.get(k) for k in ("broadcasts", "geoBroadcasts", "media")},
    })


def espn_scoreboard_entries(
    scoreboard: Mapping[str, Any],
    games: Sequence[Mapping[str, Any]],
    captured_at: str,
) -> tuple[dict[str, list[Evidence]], set[str]]:
    out: dict[str, list[Evidence]] = {}
    present: set[str] = set()
    for event in scoreboard.get("events") or []:
        event_id = str(event.get("id") or "")
        game = match_game(games, event_id=event_id)
        if not game:
            continue
        present.add(str(game.get("event_id") or game.get("id") or event_id))
        channels = espn_broadcasts(event)
        if channels:
            out.setdefault(event_id, []).append(Evidence(
                source="ESPN scoreboard",
                channels=channels,
                reference=ESPN_SCOREBOARD,
                captured_at=captured_at,
                authority=50,
            ))
    return out, present


def espn_summary_entries(
    games: Sequence[Mapping[str, Any]],
    event_ids: Iterable[str],
    *,
    timeout: int,
    attempts: int,
    captured_at: str,
    errors: list[str],
) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    ids = sorted(set(str(x) for x in event_ids if x))

    def fetch_one(event_id: str) -> tuple[str, str, list[str], str]:
        url = ESPN_SUMMARY + "?" + urllib.parse.urlencode({"event": event_id})
        try:
            summary = fetch_json(url, timeout=timeout, attempts=attempts)
            return event_id, url, extract_channels(summary), ""
        except Exception as exc:  # noqa: BLE001
            return event_id, url, [], f"{type(exc).__name__}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(ids)))) as executor:
        for event_id, url, channels, error in executor.map(fetch_one, ids):
            if error:
                errors.append(f"ESPN summary {event_id}: {error}")
            elif channels:
                out.setdefault(event_id, []).append(Evidence(
                    source="ESPN summary",
                    channels=channels,
                    reference=url,
                    captured_at=captured_at,
                    authority=55,
                ))
    return out


def cbf_evidence(
    games: Sequence[Mapping[str, Any]], rows: Iterable[CBFPartida], captured_at: str
) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    rows_list = list(rows)
    for game in games:
        event_id = str(game.get("event_id") or game.get("id") or "")
        if not event_id:
            continue
        home = para_canonico(game_team_name(game, "mandante"))
        away = para_canonico(game_team_name(game, "visitante"))
        if not home or not away:
            continue
        row = localizar_partida_cbf(
            rows_list,
            mandante=home,
            visitante=away,
            rodada=int(game.get("rodada") or 0),
            data_iso=str(game.get("data_iso") or ""),
        )
        channels = extract_channels(row.transmissao if row else "")
        if row and channels:
            out.setdefault(event_id, []).append(Evidence(
                source="CBF oficial — tabela detalhada",
                channels=channels,
                reference=row.origem,
                captured_at=captured_at,
                authority=100,
                detail=f"ref. {row.referencia}" if row.referencia else "",
            ))
    return out


def manual_evidence(manual: Mapping[str, Any], games: Sequence[Mapping[str, Any]], captured_at: str) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    for raw in manual.get("transmissoes") or []:
        if not isinstance(raw, Mapping):
            continue
        channels = extract_channels(raw.get("canais") or raw.get("transmissao"))
        if not channels:
            continue
        game = match_game(
            games,
            event_id=str(raw.get("event_id") or ""),
            home=str(raw.get("mandante") or ""),
            away=str(raw.get("visitante") or ""),
            rodada=int(raw.get("rodada") or 0),
            data_iso=str(raw.get("data_iso") or ""),
        )
        if not game:
            continue
        event_id = str(game.get("event_id") or game.get("id") or "")
        out.setdefault(event_id, []).append(Evidence(
            source="override editorial — transmissoes.json",
            channels=channels,
            reference=str(raw.get("fonte") or "transmissoes.json"),
            captured_at=captured_at,
            authority=1000,
        ))
    return out


def existing_evidence(existing: Mapping[str, Any], games: Sequence[Mapping[str, Any]], captured_at: str) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = {}
    for event_id, item in (existing.get("jogos") or {}).items():
        if not isinstance(item, Mapping):
            continue
        channels = extract_channels(item.get("canais"))
        if not channels:
            continue
        game = match_game(games, event_id=str(event_id))
        if not game:
            continue
        out.setdefault(str(event_id), []).append(Evidence(
            source="snapshot anterior preservado",
            channels=channels,
            reference="dados-br/transmissoes-tv.json",
            captured_at=captured_at,
            authority=10,
            detail="usado somente quando nenhuma fonte automática respondeu com dado válido",
        ))
    return out


def consolidate_game(
    game: Mapping[str, Any],
    evidences: Sequence[Evidence],
    *,
    automatic_sources_responded: bool,
) -> Optional[dict[str, Any]]:
    event_id = str(game.get("event_id") or game.get("id") or "")
    if not event_id:
        return None
    manual = [e for e in evidences if e.authority >= 1000]
    current = [e for e in evidences if e.source != "snapshot anterior preservado"]
    previous = [e for e in evidences if e.source == "snapshot anterior preservado"]

    selected: list[Evidence]
    preservation = False
    if manual:
        selected = manual
    elif current:
        selected = current
    elif previous and not automatic_sources_responded:
        selected = previous
        preservation = True
    elif previous:
        # Uma coleta válida sem informação de canal não apaga silenciosamente um
        # anúncio já confirmado. O histórico fica preservado e sinalizado.
        selected = previous
        preservation = True
    else:
        return None

    channels: list[str] = []
    for evidence in sorted(selected, key=lambda e: e.authority, reverse=True):
        for channel in evidence.channels:
            if channel in ALLOWED_CHANNELS and channel not in channels:
                channels.append(channel)
    if not channels:
        return None

    source_names = [e.source for e in selected]
    return {
        "event_id": event_id,
        "rodada": int(game.get("rodada") or 0),
        "mandante": game_team_name(game, "mandante"),
        "visitante": game_team_name(game, "visitante"),
        "data_iso": game.get("data_iso") or "",
        "tipo": "tv_ou_streaming_oficial",
        "canais": channels,
        "origem": " + ".join(dict.fromkeys(source_names)),
        "confianca": "manual" if manual else ("preservado" if preservation else "confirmado"),
        "fontes": [e.public() for e in sorted(selected, key=lambda e: e.authority, reverse=True)],
    }


def collect(
    *,
    agenda: Mapping[str, Any],
    existing: Mapping[str, Any],
    manual: Mapping[str, Any],
    cfg: Mapping[str, Any],
    now: dt.datetime,
    source_payloads: Optional[Mapping[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    all_games = agenda_games(agenda)
    games = [g for g in all_games if in_collection_window(g, now, cfg)]
    captured_at = iso_now(now)
    timeout = int(cfg.get("timeout_segundos") or 30)
    attempts = int(cfg.get("tentativas_rede") or 3)

    evidence_by_game: dict[str, list[Evidence]] = {}
    source_status: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    payloads = dict(source_payloads or {})

    # CBF
    try:
        started = time.monotonic()
        rows = payloads.get("cbf_rows")
        if rows is None:
            rows = buscar_tabela_detalhada_cbf(resolver=para_canonico)
        rows = list(rows)
        merge_evidence(evidence_by_game, cbf_evidence(games, rows, captured_at))
        source_status["cbf"] = {
            "ok": True, "registros": len(rows), "duracao_ms": round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        source_status["cbf"] = {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
        errors.append("CBF: " + source_status["cbf"]["erro"])

    # GE Agenda
    if cfg.get("habilitar_ge_agenda", True):
        try:
            started = time.monotonic()
            page = payloads.get("ge_agenda_html")
            if page is None:
                page = fetch_text(str(cfg.get("ge_agenda_url") or GE_AGENDA), timeout=timeout, attempts=attempts)
            found = ge_entries_from_page(
                page, games, source_name="GE Agenda", reference=str(cfg.get("ge_agenda_url") or GE_AGENDA),
                captured_at=captured_at, authority=80,
            )
            merge_evidence(evidence_by_game, found)
            source_status["ge_agenda"] = {
                "ok": True, "jogos_com_canal": len(found), "duracao_ms": round((time.monotonic() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001
            source_status["ge_agenda"] = {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
            errors.append("GE Agenda: " + source_status["ge_agenda"]["erro"])

    # GE guias editoriais recentes
    article_urls: list[str] = []
    if cfg.get("habilitar_ge_artigos", True):
        try:
            started = time.monotonic()
            pages = payloads.get("ge_index_pages")
            if pages is None:
                pages = []
                base = str(cfg.get("ge_brasileirao_url") or GE_BRASILEIRAO)
                pages.append(fetch_text(base, timeout=timeout, attempts=attempts))
                for page_no in range(1, int(cfg.get("ge_paginas_feed") or 2) + 1):
                    feed_url = urllib.parse.urljoin(base, f"index/feed/pagina-{page_no}.ghtml")
                    try:
                        pages.append(fetch_text(feed_url, timeout=timeout, attempts=max(1, attempts - 1)))
                    except Exception:
                        continue
            for page in pages:
                for url in article_links_from_page(page, str(cfg.get("ge_brasileirao_url") or GE_BRASILEIRAO), int(cfg.get("ge_max_artigos") or 12)):
                    if url not in article_urls:
                        article_urls.append(url)
            article_pages = payloads.get("ge_article_pages") or {}
            found_all: dict[str, list[Evidence]] = {}
            selected_urls = article_urls[: int(cfg.get("ge_max_artigos") or 12)]

            def fetch_article(url: str) -> tuple[str, Optional[str], str]:
                try:
                    page = article_pages.get(url) if isinstance(article_pages, Mapping) else None
                    if page is None:
                        page = fetch_text(url, timeout=timeout, attempts=max(1, attempts - 1))
                    return url, page, ""
                except Exception as exc:  # noqa: BLE001
                    return url, None, f"{type(exc).__name__}: {exc}"

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(selected_urls)))) as executor:
                for url, page, error in executor.map(fetch_article, selected_urls):
                    if error or page is None:
                        errors.append(f"GE artigo {url}: {error}")
                        continue
                    found = ge_entries_from_page(
                        page, games, source_name="GE guia editorial", reference=url,
                        captured_at=captured_at, authority=85,
                    )
                    merge_evidence(found_all, found)
            merge_evidence(evidence_by_game, found_all)
            source_status["ge_artigos"] = {
                "ok": True, "artigos_consultados": len(selected_urls),
                "jogos_com_canal": len(found_all), "duracao_ms": round((time.monotonic() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001
            source_status["ge_artigos"] = {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
            errors.append("GE artigos: " + source_status["ge_artigos"]["erro"])

    # ESPN scoreboard e summaries dos jogos ainda sem informação.
    try:
        started = time.monotonic()
        scoreboard = payloads.get("espn_scoreboard")
        if scoreboard is None:
            dates = f"{(now.date() - dt.timedelta(days=2)):%Y%m%d}-{(now.date() + dt.timedelta(days=int(cfg.get('janela_futuro_dias') or 35))):%Y%m%d}"
            scoreboard = fetch_json(
                ESPN_SCOREBOARD + "?" + urllib.parse.urlencode({"dates": dates, "limit": 300}),
                timeout=timeout, attempts=attempts,
            )
        espn_found, present_ids = espn_scoreboard_entries(scoreboard, games, captured_at)
        merge_evidence(evidence_by_game, espn_found)
        missing_ids = [
            str(g.get("event_id") or g.get("id") or "") for g in games
            if str(g.get("event_id") or g.get("id") or "") and not evidence_by_game.get(str(g.get("event_id") or g.get("id") or ""))
        ]
        summary_found: dict[str, list[Evidence]] = {}
        if cfg.get("habilitar_espn_summary", True):
            if "espn_summaries" in payloads:
                for event_id, summary in (payloads.get("espn_summaries") or {}).items():
                    channels = extract_channels(summary)
                    if channels:
                        summary_found.setdefault(str(event_id), []).append(Evidence(
                            source="ESPN summary", channels=channels,
                            reference=ESPN_SUMMARY + "?event=" + str(event_id), captured_at=captured_at, authority=55,
                        ))
            else:
                summary_found = espn_summary_entries(
                    games, missing_ids, timeout=timeout, attempts=max(1, attempts - 1), captured_at=captured_at, errors=errors,
                )
            merge_evidence(evidence_by_game, summary_found)
        source_status["espn"] = {
            "ok": True, "eventos_na_janela": len(present_ids), "scoreboard_com_canal": len(espn_found),
            "summary_com_canal": len(summary_found), "duracao_ms": round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        source_status["espn"] = {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
        errors.append("ESPN: " + source_status["espn"]["erro"])

    # Override manual e snapshot anterior entram por último, com políticas próprias.
    merge_evidence(evidence_by_game, manual_evidence(manual, games, captured_at))
    merge_evidence(evidence_by_game, existing_evidence(existing, games, captured_at))

    any_automatic_ok = any(source_status.get(name, {}).get("ok") for name in ("cbf", "ge_agenda", "ge_artigos", "espn"))
    generated: dict[str, Any] = {}
    for game in games:
        event_id = str(game.get("event_id") or game.get("id") or "")
        entry = consolidate_game(game, evidence_by_game.get(event_id, []), automatic_sources_responded=any_automatic_ok)
        if entry:
            generated[event_id] = entry

    generated = dict(sorted(generated.items(), key=lambda kv: str(kv[1].get("data_iso") or "")))
    payload = {
        "descricao": "Transmissões oficiais por TV ou streaming do Brasileirão Série A.",
        "politica": {
            "fontes": ["CBF oficial", "GE Agenda", "GE guias editoriais", "ESPN", "override manual"],
            "regra_preservacao": "resposta vazia ou falha de uma fonte nunca apaga transmissão válida já publicada",
            "regra_publicacao": "somente canais oficiais da lista permitida; evidências ficam registradas por jogo",
            "youtube_exato": "links exatos de GE TV/CazéTV permanecem em dados-br/transmissoes-aovivo.json",
        },
        "jogos": generated,
        "atualizado_em": captured_at,
    }

    critical_hours = int(cfg.get("janela_critica_horas") or 72)
    warning_days = int(cfg.get("janela_aviso_dias") or 14)
    missing: list[dict[str, Any]] = []
    for game in games:
        event_id = str(game.get("event_id") or game.get("id") or "")
        kickoff = parse_dt(game.get("data_iso"))
        if event_id in generated or not kickoff or kickoff < now - dt.timedelta(hours=6):
            continue
        hours = (kickoff - now).total_seconds() / 3600
        if hours <= warning_days * 24:
            missing.append({
                "event_id": event_id,
                "rodada": int(game.get("rodada") or 0),
                "jogo": f"{game_team_name(game, 'mandante')} x {game_team_name(game, 'visitante')}",
                "data_iso": game.get("data_iso") or "",
                "faltam_horas": round(hours, 1),
                "nivel": "critico" if hours <= critical_hours else "aviso",
            })

    preserved = [
        {"event_id": event_id, "jogo": f"{item.get('mandante')} x {item.get('visitante')}", "canais": item.get("canais")}
        for event_id, item in generated.items() if item.get("confianca") == "preservado"
    ]
    audit = {
        "descricao": "Auditoria da consolidação de transmissões do Brasileirão.",
        "resumo": {
            "jogos_na_janela": len(games),
            "jogos_com_transmissao": len(generated),
            "jogos_sem_transmissao_14d": len(missing),
            "jogos_criticos_sem_transmissao_72h": sum(1 for item in missing if item["nivel"] == "critico"),
            "registros_preservados": len(preserved),
            "fontes_com_falha": sum(1 for item in source_status.values() if not item.get("ok")),
        },
        "fontes": source_status,
        "sem_transmissao": missing,
        "preservados": preserved,
        "erros": errors,
        "artigos_ge_descobertos": article_urls,
        "atualizado_em": captured_at,
    }
    return payload, audit


def selftest() -> None:
    now = dt.datetime(2026, 7, 24, 10, 0, tzinfo=TZ)
    agenda = {
        "jogos": [
            {"event_id": "1", "rodada": 20, "mandante": "Santos", "visitante": "Chapecoense", "data_iso": "2026-07-25T18:30:00-03:00"},
            {"event_id": "2", "rodada": 20, "mandante": "Vasco da Gama", "visitante": "Mirassol", "data_iso": "2026-07-25T20:30:00-03:00"},
            {"event_id": "3", "rodada": 21, "mandante": "Flamengo", "visitante": "São Paulo", "data_iso": "2026-07-29T21:30:00-03:00"},
        ]
    }
    cbf = [
        CBFPartida("193", 20, "Santos", "Chapecoense", "2026-07-25T18:30", None, None, "Premiere, Sportv", "https://cbf.test"),
        CBFPartida("192", 20, "Vasco da Gama", "Mirassol", "2026-07-25T20:30", None, None, "Premiere, Record, YouTube / Cazé TV", "https://cbf.test"),
    ]
    ge_html = '''
    <html><script type="application/json">{"events":[
      {"homeTeam":{"name":"Santos"},"awayTeam":{"name":"Chapecoense"},"whereToWatch":["Premiere","SporTV"]},
      {"homeTeam":{"name":"Vasco da Gama"},"awayTeam":{"name":"Mirassol"},"ondeAssistir":"Record e CazéTV"}
    ]}</script></html>
    '''
    espn = {"events": [{"id": "1", "competitions": [{"geoBroadcasts": [{"media": {"shortName": "Premiere"}}]}]}]}
    manual = {"transmissoes": [{"event_id": "3", "mandante": "Flamengo", "visitante": "São Paulo", "transmissao": "Globo / Premiere", "fonte": "teste manual"}]}
    payload, audit = collect(
        agenda=agenda,
        existing={"jogos": {}},
        manual=manual,
        cfg={**DEFAULT_CONFIG, "habilitar_ge_artigos": False},
        now=now,
        source_payloads={"cbf_rows": cbf, "ge_agenda_html": ge_html, "espn_scoreboard": espn, "espn_summaries": {}},
    )
    assert payload["jogos"]["1"]["canais"] == ["Premiere", "SporTV"]
    assert payload["jogos"]["2"]["canais"] == ["Premiere", "Record", "CazéTV"]
    assert payload["jogos"]["3"]["canais"] == ["Globo", "Premiere"]
    assert payload["jogos"]["3"]["confianca"] == "manual"
    assert audit["resumo"]["jogos_criticos_sem_transmissao_72h"] == 0

    # Resposta vazia não pode apagar snapshot anterior.
    previous = {
        "jogos": {
            "1": {"event_id": "1", "mandante": "Santos", "visitante": "Chapecoense", "data_iso": "2026-07-25T18:30:00-03:00", "canais": ["Premiere"]}
        }
    }
    preserved_payload, preserved_audit = collect(
        agenda={"jogos": [agenda["jogos"][0]]}, existing=previous, manual={"transmissoes": []},
        cfg={**DEFAULT_CONFIG, "habilitar_ge_agenda": False, "habilitar_ge_artigos": False, "habilitar_espn_summary": False},
        now=now, source_payloads={"cbf_rows": [], "espn_scoreboard": {"events": []}},
    )
    assert preserved_payload["jogos"]["1"]["canais"] == ["Premiere"]
    assert preserved_payload["jogos"]["1"]["confianca"] == "preservado"
    assert preserved_audit["resumo"]["registros_preservados"] == 1

    # Parser de links editoriais.
    article_index = '<a href="/futebol/brasileirao-serie-a/noticia/2026/07/24/brasileirao-veja-onde-assistir-aos-jogos-da-20a-rodada.ghtml">Onde assistir aos jogos da rodada</a>'
    links = article_links_from_page(article_index, GE_BRASILEIRAO, 5)
    assert len(links) == 1 and links[0].endswith(".ghtml")
    assert extract_channels("Premiere, SporTV, Record e YouTube / Cazé TV") == ["Premiere", "SporTV", "Record", "CazéTV"]
    assert extract_channels("Leia em https://ge.globo.com/futebol/ e assista no Premiere") == ["Premiere"]
    parsed_blobs = json_candidates_from_html(ge_html)
    assert structured_channels_for_game(parsed_blobs, "Santos", "Chapecoense") == ["Premiere", "SporTV"]
    assert structured_channels_for_game(parsed_blobs, "Vasco da Gama", "Mirassol") == ["Record", "CazéTV"]
    print("SELFTEST OK: CBF, GE, ESPN, manual, preservação, auditoria e links editoriais")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0

    cfg = {**DEFAULT_CONFIG, **load_json(CONFIG_PATH, {})}
    now = dt.datetime.now(TZ)
    agenda = load_json(AGENDA, {"jogos": []})
    existing = load_json(OUTPUT, {"jogos": {}})
    old_audit = load_json(AUDIT_OUTPUT, {})
    manual = load_json(MANUAL, {"transmissoes": []})
    payload, audit = collect(agenda=agenda, existing=existing, manual=manual, cfg=cfg, now=now)

    if args.dry_run:
        print(json.dumps({"transmissoes": payload, "auditoria": audit}, ensure_ascii=False, indent=2))
        return 0

    changed_output = semantic_payload(existing) != semantic_payload(payload)
    changed_audit = semantic_payload(old_audit) != semantic_payload(audit)
    if changed_output:
        atomic_write_json(OUTPUT, payload)
    if changed_audit:
        atomic_write_json(AUDIT_OUTPUT, audit)
    print(
        f"Transmissões TV: {len(payload['jogos'])} jogo(s); "
        f"alterado={str(changed_output).lower()}; auditoria_alterada={str(changed_audit).lower()}; "
        f"críticos_sem_canal={audit['resumo']['jogos_criticos_sem_transmissao_72h']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

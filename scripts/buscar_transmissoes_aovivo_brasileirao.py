#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Localiza transmissões oficiais do Brasileirão nos canais GE TV e CazéTV.

Regras principais:
- Escopo exclusivo do módulo Brasileirão.
- Só aceita vídeos pertencentes aos channelIds oficiais configurados.
- Só considera transmissões `upcoming` ou `live`.
- Faz varredura barata da playlist de uploads em toda execução útil.
- Faz scraping da página /@canal/streams (custo zero de quota) em toda
  execução para capturar lives agendadas não presentes nos uploads recentes.
- Liga o vídeo ao jogo somente quando clubes + horário dão confiança alta.
- CazéTV tem prioridade sobre GE TV; exibe sempre um único link.
- Links manuais têm prioridade absoluta e nunca são sobrescritos.

Usa apenas biblioteca padrão do Python. Requer YOUTUBE_API_KEY para
validar os video_ids encontrados via scraping (videos.list = 1 unidade).
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

YT_API = "https://www.googleapis.com/youtube/v3"
TZ = ZoneInfo("America/Sao_Paulo")
UTC = dt.timezone.utc

ENDPOINT_COST = {
    "channels": 1,
    "playlistItems": 1,
    "videos": 1,
    "search": 100,  # nunca usado — mantido apenas para documentação
}


def now_brt() -> dt.datetime:
    return dt.datetime.now(TZ).replace(microsecond=0)


def iso_brt(value: dt.datetime) -> str:
    return value.astimezone(TZ).replace(microsecond=0).isoformat()


def parse_datetime(value: Any, default_tz: dt.tzinfo = TZ) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=default_tz)
        return parsed.astimezone(TZ)
    except ValueError:
        return None


def load_json(path: Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return copy.deepcopy(fallback)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON inválido em {path}: {exc}") from exc


def semantic_payload(data: Any) -> Any:
    """Remove apenas timestamp editorial para evitar commits sem mudança real."""
    if isinstance(data, dict):
        return {k: semantic_payload(v) for k, v in data.items() if k != "atualizado_em"}
    if isinstance(data, list):
        return [semantic_payload(v) for v in data]
    return data


def save_if_changed(path: Path, payload: Dict[str, Any], current_time: dt.datetime, dry_run: bool = False) -> bool:
    old = load_json(path, {})
    if semantic_payload(old) == semantic_payload(payload):
        return False
    payload = copy.deepcopy(payload)
    payload["atualizado_em"] = iso_brt(current_time)
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    temp.replace(path)
    return True


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("&", " e ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def whole_term(text_norm: str, term: str) -> bool:
    t = norm(term)
    return bool(t and re.search(r"(?:^|\s)" + re.escape(t) + r"(?:\s|$)", text_norm))


def chunked(values: Sequence[str], size: int = 50) -> Iterable[List[str]]:
    for idx in range(0, len(values), size):
        yield list(values[idx: idx + size])


def video_id_from_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    try:
        parsed = urllib.parse.urlparse(text if "://" in text else "https://" + text)
        host = parsed.netloc.lower().split(":")[0]
        if host in {"youtu.be", "www.youtu.be"}:
            candidate = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com"):
            if parsed.path.startswith("/shorts/") or parsed.path.startswith("/live/") or parsed.path.startswith("/embed/"):
                candidate = parsed.path.strip("/").split("/")[1]
            else:
                candidate = (urllib.parse.parse_qs(parsed.query).get("v") or [""])[0]
        else:
            return ""
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else ""
    except Exception:
        return ""


def youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass
class Game:
    event_id: str
    rodada: int
    kickoff: dt.datetime
    mandante: str
    visitante: str
    estado: str
    estadio: str = ""

    @property
    def key(self) -> str:
        return self.event_id or f"{norm(self.mandante)}-{norm(self.visitante)}-{self.kickoff.isoformat()}"


@dataclass
class Candidate:
    video_id: str
    channel_key: str
    channel_id: str
    channel_title: str
    title: str
    description: str
    status: str
    scheduled_start: Optional[dt.datetime]
    actual_start: Optional[dt.datetime]
    actual_end: Optional[dt.datetime]
    thumbnail: str = ""
    source: str = ""
    score: float = 0.0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    rejected_reason: str = ""

    def public(self, channel_name: str) -> Dict[str, Any]:
        return {
            "fonte": self.channel_key,
            "nome": channel_name,
            "video_id": self.video_id,
            "url": youtube_url(self.video_id),
            "status": self.status,
            "inicio_programado": iso_brt(self.scheduled_start) if self.scheduled_start else "",
            "inicio_real": iso_brt(self.actual_start) if self.actual_start else "",
            "titulo": self.title,
            "canal": self.channel_title,
            "channel_id": self.channel_id,
            "thumbnail": self.thumbnail,
            "confianca": round(self.confidence, 4),
            "motivos": self.reasons,
            "origem_busca": self.source,
        }


class YouTubeClient:
    def __init__(self, api_key: str, timeout: int = 25, sleep: float = 0.03) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.sleep = sleep
        self.requests: Dict[str, int] = {}
        self.quota_estimated = 0

    def get(self, resource: str, **params: Any) -> Dict[str, Any]:
        clean = {k: v for k, v in params.items() if v not in (None, "", [], ())}
        clean["key"] = self.api_key
        url = f"{YT_API}/{resource}?" + urllib.parse.urlencode(clean, doseq=True)
        request = urllib.request.Request(url, headers={"User-Agent": "brasileirao-transmissoes-aovivo/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"YouTube API HTTP {exc.code} em {resource}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Falha de rede na YouTube API em {resource}: {exc}") from exc
        self.requests[resource] = self.requests.get(resource, 0) + 1
        self.quota_estimated += ENDPOINT_COST.get(resource, 1)
        if self.sleep:
            time.sleep(self.sleep)
        return json.loads(raw)


def team_name(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("nome") or obj.get("displayName") or obj.get("name") or "").strip()
    return str(obj or "").strip()


def load_games(path: Path) -> List[Game]:
    data = load_json(path, {})
    games: List[Game] = []
    for item in data.get("jogos") or []:
        kickoff = parse_datetime(item.get("data_iso"))
        if not kickoff or item.get("data_definir") is True:
            continue
        home = team_name(item.get("mandante"))
        away = team_name(item.get("visitante"))
        if not home or not away:
            continue
        games.append(Game(
            event_id=str(item.get("event_id") or ""),
            rodada=int(item.get("rodada") or 0),
            kickoff=kickoff,
            mandante=home,
            visitante=away,
            estado=str(item.get("estado") or "pre").lower(),
            estadio=str(item.get("estadio") or ""),
        ))
    return sorted(games, key=lambda g: (g.kickoff, g.rodada, g.mandante, g.visitante))


def aliases_for(team: str, aliases: Mapping[str, Any]) -> List[str]:
    values = [team] + list(aliases.get(team) or [])
    out: List[str] = []
    seen = set()
    for value in values:
        n = norm(value)
        if n and n not in seen:
            out.append(n)
            seen.add(n)
    return out


def team_present(text_norm: str, team: str, aliases: Mapping[str, Any]) -> bool:
    return any(whole_term(text_norm, alias) for alias in aliases_for(team, aliases))


def candidate_status(item: Mapping[str, Any]) -> str:
    snippet = item.get("snippet") or {}
    live = str(snippet.get("liveBroadcastContent") or "").lower()
    details = item.get("liveStreamingDetails") or {}
    if details.get("actualEndTime"):
        return "completed"
    if live == "live" or details.get("actualStartTime"):
        return "live"
    if live == "upcoming" or details.get("scheduledStartTime"):
        return "upcoming"
    return "none"


def candidate_from_video(item: Mapping[str, Any], channel_key: str, source: str) -> Optional[Candidate]:
    vid = str(item.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        return None
    snippet = item.get("snippet") or {}
    live = item.get("liveStreamingDetails") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        if isinstance(thumbs.get(key), dict) and thumbs[key].get("url"):
            thumb = str(thumbs[key]["url"])
            break
    return Candidate(
        video_id=vid,
        channel_key=channel_key,
        channel_id=str(snippet.get("channelId") or ""),
        channel_title=str(snippet.get("channelTitle") or ""),
        title=str(snippet.get("title") or ""),
        description=str(snippet.get("description") or ""),
        status=candidate_status(item),
        scheduled_start=parse_datetime(live.get("scheduledStartTime"), UTC),
        actual_start=parse_datetime(live.get("actualStartTime"), UTC),
        actual_end=parse_datetime(live.get("actualEndTime"), UTC),
        thumbnail=thumb,
        source=source,
    )


def evaluate_candidate(candidate: Candidate, game: Game, config: Mapping[str, Any], aliases: Mapping[str, Any]) -> Candidate:
    evaluated = copy.deepcopy(candidate)
    title_n = norm(candidate.title)
    desc_n = norm(candidate.description)
    combined_n = (title_n + " " + desc_n).strip()
    banned = [norm(x) for x in config.get("palavras_rejeitadas") or []]
    for term in banned:
        if term and whole_term(combined_n, term):
            evaluated.rejected_reason = f"conteúdo rejeitado: {term}"
            return evaluated
    if candidate.status not in {"upcoming", "live"}:
        evaluated.rejected_reason = "vídeo não está como transmissão futura ou ao vivo"
        return evaluated

    home_title = team_present(title_n, game.mandante, aliases)
    away_title = team_present(title_n, game.visitante, aliases)
    home_desc = team_present(desc_n, game.mandante, aliases)
    away_desc = team_present(desc_n, game.visitante, aliases)

    score = 0.0
    reasons: List[str] = []
    if home_title and away_title:
        score += 60
        reasons.append("os dois clubes aparecem no título")
    elif (home_title and away_desc) or (away_title and home_desc):
        score += 42
        reasons.append("um clube aparece no título e o outro na descrição")
    elif home_desc and away_desc:
        score += 26
        reasons.append("os dois clubes aparecem somente na descrição")
    else:
        evaluated.rejected_reason = "não identifica com segurança os dois clubes"
        return evaluated

    competition_terms = [norm(x) for x in config.get("termos_competicao") or []]
    if any(term and whole_term(combined_n, term) for term in competition_terms):
        score += 8
        reasons.append("identifica Brasileirão/competição")
    if whole_term(combined_n, "ao vivo") or candidate.status == "live":
        score += 7
        reasons.append("identifica transmissão ao vivo")
    if candidate.status == "live":
        score += 5
        reasons.append("transmissão já está ao vivo")

    reference_start = candidate.scheduled_start or candidate.actual_start
    if reference_start:
        delta_minutes = abs((reference_start - game.kickoff).total_seconds()) / 60
        max_delta = float(config.get("tolerancia_horario_minutos") or 180)
        if delta_minutes > max_delta:
            evaluated.rejected_reason = f"horário incompatível ({delta_minutes:.0f} min de diferença)"
            return evaluated
        score += max(4.0, 20.0 * (1.0 - delta_minutes / max_delta))
        reasons.append(f"horário compatível ({delta_minutes:.0f} min de diferença)")
    elif candidate.status == "live" and home_title and away_title:
        score += 8
        reasons.append("já está ao vivo e identifica os dois clubes")
    else:
        evaluated.rejected_reason = "sem horário programado suficiente para validar o confronto"
        return evaluated

    confidence = min(0.999, score / 100.0)
    threshold = float(config.get("confianca_minima") or 0.72)
    if confidence < threshold:
        evaluated.rejected_reason = f"confiança insuficiente ({confidence:.2%})"
        evaluated.score = score
        evaluated.confidence = confidence
        evaluated.reasons = reasons
        return evaluated

    evaluated.score = score
    evaluated.confidence = confidence
    evaluated.reasons = reasons
    return evaluated


def resolve_channels(client: YouTubeClient, config: Mapping[str, Any], errors: List[str]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for channel in config.get("canais") or []:
        key = str(channel.get("chave") or "").strip()
        if not key:
            continue
        configured_id = str(channel.get("channel_id") or "").strip()
        handle = str(channel.get("handle") or "").strip()
        item: Optional[Dict[str, Any]] = None
        try:
            if configured_id:
                data = client.get("channels", part="id,snippet,contentDetails", id=configured_id, maxResults=1)
                items = data.get("items") or []
                item = items[0] if items else None
            if not item and handle:
                data = client.get("channels", part="id,snippet,contentDetails", forHandle=handle, maxResults=1)
                items = data.get("items") or []
                item = items[0] if items else None
        except Exception as exc:
            errors.append(f"Falha ao resolver canal {key}: {exc}")
        if not item:
            errors.append(f"Canal {key} não foi resolvido por channel_id nem handle")
            continue
        snippet = item.get("snippet") or {}
        playlists = (item.get("contentDetails") or {}).get("relatedPlaylists") or {}
        result[key] = {
            "chave": key,
            "nome": str(channel.get("nome") or snippet.get("title") or key),
            "channel_id": str(item.get("id") or configured_id),
            "channel_title": str(snippet.get("title") or channel.get("nome") or key),
            "uploads_playlist": str(playlists.get("uploads") or ""),
            "handle": handle,
            "prioridade": str(channel.get("prioridade") or ""),
            "streams_url": str(channel.get("streams_url") or ""),
        }
    return result


def fetch_video_details(client: YouTubeClient, ids: Iterable[str]) -> List[Dict[str, Any]]:
    unique = sorted({str(x) for x in ids if re.fullmatch(r"[A-Za-z0-9_-]{11}", str(x or ""))})
    out: List[Dict[str, Any]] = []
    for group in chunked(unique, 50):
        data = client.get("videos", part="snippet,status,liveStreamingDetails", id=",".join(group), maxResults=50)
        out.extend(data.get("items") or [])
    return out


def extract_video_ids_from_streams_html(page: str) -> List[str]:
    """Extrai videoIds da aba /streams sem executar JavaScript.

    O YouTube repete o mesmo ID em vários blocos; a ordem de primeira aparição
    é preservada e somente IDs sintaticamente válidos são retornados.
    """
    decoded = page.replace("\\u0026", "&").replace("\\u003d", "=").replace("\\/", "/")
    patterns = (
        r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
        r'(?:watch\?v=|/live/)([A-Za-z0-9_-]{11})',
    )
    out: List[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, decoded):
            video_id = match.group(1)
            if video_id not in seen:
                seen.add(video_id)
                out.append(video_id)
    return out


def fetch_streams_page(url: str, timeout: int = 25) -> str:
    """Busca a aba oficial de streams com fingerprint de navegador quando disponível."""
    try:
        from curl_cffi import requests as curl_requests  # type: ignore
        response = curl_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
        )
        response.raise_for_status()
        return response.text
    except ImportError:
        pass
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def scan_streams_page(
    client: YouTubeClient,
    channel: Mapping[str, str],
    max_items: int,
    errors: List[str],
) -> List[Candidate]:
    """Captura lives agendadas diretamente da aba oficial /streams.

    Essa camada costuma enxergar transmissões futuras antes da playlist de
    uploads e usa somente videos.list para validação, com custo baixo de quota.
    """
    url = str(channel.get("streams_url") or "").strip()
    if not url:
        return []
    try:
        page = fetch_streams_page(url)
        ids = extract_video_ids_from_streams_html(page)[:max_items]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Falha ao ler /streams de {channel.get('nome')}: {exc}")
        return []
    if not ids:
        return []
    try:
        details = fetch_video_details(client, ids)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Falha ao validar /streams de {channel.get('nome')}: {exc}")
        return []
    out: List[Candidate] = []
    for item in details:
        cand = candidate_from_video(item, str(channel.get("chave")), "streams-page")
        if cand and cand.channel_id == channel.get("channel_id") and cand.status in {"upcoming", "live"}:
            out.append(cand)
    return out


def scan_uploads(client: YouTubeClient, channel: Mapping[str, str], max_items: int, errors: List[str]) -> List[Candidate]:
    playlist = channel.get("uploads_playlist") or ""
    if not playlist:
        errors.append(f"Canal {channel.get('nome')} sem playlist de uploads")
        return []
    ids: List[str] = []
    token = ""
    while len(ids) < max_items:
        try:
            data = client.get("playlistItems", part="contentDetails", playlistId=playlist, maxResults=min(50, max_items - len(ids)), pageToken=token)
        except Exception as exc:
            errors.append(f"Falha ao varrer uploads de {channel.get('nome')}: {exc}")
            break
        for item in data.get("items") or []:
            vid = str((item.get("contentDetails") or {}).get("videoId") or "")
            if vid:
                ids.append(vid)
        token = str(data.get("nextPageToken") or "")
        if not token:
            break
    try:
        details = fetch_video_details(client, ids)
    except Exception as exc:
        errors.append(f"Falha ao detalhar uploads de {channel.get('nome')}: {exc}")
        return []
    out: List[Candidate] = []
    for item in details:
        cand = candidate_from_video(item, str(channel.get("chave")), "uploads")
        if cand and cand.channel_id == channel.get("channel_id") and cand.status in {"upcoming", "live"}:
            out.append(cand)
    return out





def load_existing_video_ids(output: Mapping[str, Any], manual: Mapping[str, Any]) -> List[str]:
    ids: List[str] = []
    for container in (output, manual):
        games = container.get("jogos") if isinstance(container, dict) else None
        if isinstance(games, dict):
            entries = games.values()
        elif isinstance(games, list):
            entries = games
        else:
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key in ("principal", "alternativa"):
                link = entry.get(key)
                if isinstance(link, dict):
                    vid = str(link.get("video_id") or video_id_from_url(link.get("url")))
                    if vid:
                        ids.append(vid)
            alternatives = entry.get("alternativas") or []
            if isinstance(alternatives, list):
                for link in alternatives:
                    if isinstance(link, dict):
                        vid = str(link.get("video_id") or video_id_from_url(link.get("url")))
                        if vid:
                            ids.append(vid)
            for key in ("cazetv", "getv", "url"):
                vid = video_id_from_url(entry.get(key))
                if vid:
                    ids.append(vid)
    return ids


def manual_links_for_game(manual: Mapping[str, Any], game: Game, channels: Mapping[str, Mapping[str, str]]) -> Dict[str, Dict[str, Any]]:
    games = manual.get("jogos") if isinstance(manual, dict) else {}
    entry: Optional[Mapping[str, Any]] = None
    if isinstance(games, dict):
        raw = games.get(game.event_id)
        if isinstance(raw, dict):
            entry = raw
        if entry is None:
            for value in games.values():
                if not isinstance(value, dict):
                    continue
                if norm(value.get("mandante")) == norm(game.mandante) and norm(value.get("visitante")) == norm(game.visitante):
                    entry = value
                    break
    elif isinstance(games, list):
        for value in games:
            if not isinstance(value, dict):
                continue
            if str(value.get("event_id") or "") == game.event_id:
                entry = value
                break
    if not entry or entry.get("ativo") is False:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    candidates: List[Tuple[str, Any]] = []
    for key in ("cazetv", "getv"):
        if entry.get(key):
            candidates.append((key, entry.get(key)))
    principal = entry.get("principal")
    if isinstance(principal, dict):
        candidates.append((str(principal.get("fonte") or ""), principal))
    for alt in entry.get("alternativas") or []:
        if isinstance(alt, dict):
            candidates.append((str(alt.get("fonte") or ""), alt))
    if entry.get("url"):
        candidates.append((str(entry.get("fonte") or ""), entry.get("url")))

    by_id = {str(c.get("channel_id")): key for key, c in channels.items()}
    for source_key, raw in candidates:
        if isinstance(raw, dict):
            url = raw.get("url") or raw.get("video_id")
            source_key = source_key or str(raw.get("fonte") or "")
            title = str(raw.get("titulo") or "Inserido manualmente")
        else:
            url = raw
            title = "Inserido manualmente"
        vid = video_id_from_url(url)
        if not vid:
            continue
        if source_key not in channels:
            source_key = by_id.get(str(entry.get("channel_id") or ""), source_key)
        if source_key not in channels:
            continue
        channel = channels[source_key]
        result[source_key] = {
            "fonte": source_key,
            "nome": channel.get("nome") or source_key,
            "video_id": vid,
            "url": youtube_url(vid),
            "status": str(entry.get("status") or "upcoming"),
            "inicio_programado": iso_brt(game.kickoff),
            "inicio_real": "",
            "titulo": title,
            "canal": channel.get("channel_title") or channel.get("nome") or source_key,
            "channel_id": channel.get("channel_id") or "",
            "thumbnail": "",
            "confianca": 1.0,
            "motivos": ["link manual com prioridade absoluta"],
            "origem_busca": "manual",
        }
    return result


def choose_links(links: Mapping[str, Dict[str, Any]], priority: Sequence[str]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    ordered: List[Dict[str, Any]] = []
    for key in priority:
        if key in links:
            ordered.append(links[key])
    for key, value in links.items():
        if key not in priority:
            ordered.append(value)
    # Retorna APENAS o principal (link único — CazéTV tem prioridade sobre GE TV)
    return (ordered[0] if ordered else None, [])


def existing_links_for_game(existing: Mapping[str, Any], game: Game) -> Dict[str, Dict[str, Any]]:
    games = existing.get("jogos") if isinstance(existing, dict) else {}
    if not isinstance(games, dict):
        return {}
    entry = games.get(game.event_id)
    if not isinstance(entry, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for link in [entry.get("principal")] + list(entry.get("alternativas") or []):
        if isinstance(link, dict) and link.get("fonte") and link.get("video_id"):
            out[str(link["fonte"])] = copy.deepcopy(link)
    return out


def match_candidates_to_games(
    games: Sequence[Game],
    candidates: Sequence[Candidate],
    channels: Mapping[str, Mapping[str, str]],
    config: Mapping[str, Any],
    aliases: Mapping[str, Any],
) -> Tuple[Dict[str, Dict[str, Candidate]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    matched: Dict[str, Dict[str, Candidate]] = {g.event_id: {} for g in games}
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for candidate in candidates:
        channel = channels.get(candidate.channel_key)
        if not channel or candidate.channel_id != channel.get("channel_id"):
            rejected.append({
                "video_id": candidate.video_id,
                "url": youtube_url(candidate.video_id),
                "canal": candidate.channel_title,
                "titulo": candidate.title,
                "motivo": "channelId não corresponde ao canal oficial configurado",
            })
            continue
        best_game: Optional[Game] = None
        best_eval: Optional[Candidate] = None
        for game in games:
            evaluated = evaluate_candidate(candidate, game, config, aliases)
            if evaluated.rejected_reason:
                continue
            if best_eval is None or evaluated.score > best_eval.score:
                best_eval = evaluated
                best_game = game
        if best_game is None or best_eval is None:
            nearest = min(games, key=lambda g: abs((g.kickoff - (candidate.scheduled_start or candidate.actual_start or g.kickoff)).total_seconds()), default=None)
            reason = "não corresponde com segurança a nenhum jogo dentro da janela"
            if nearest:
                reason = evaluate_candidate(candidate, nearest, config, aliases).rejected_reason or reason
            rejected.append({
                "video_id": candidate.video_id,
                "url": youtube_url(candidate.video_id),
                "fonte": candidate.channel_key,
                "canal": candidate.channel_title,
                "titulo": candidate.title,
                "status": candidate.status,
                "inicio_programado": iso_brt(candidate.scheduled_start) if candidate.scheduled_start else "",
                "motivo": reason,
            })
            continue
        current = matched[best_game.event_id].get(candidate.channel_key)
        if current is None or best_eval.score > current.score:
            matched[best_game.event_id][candidate.channel_key] = best_eval
        accepted.append({
            "event_id": best_game.event_id,
            "jogo": f"{best_game.mandante} x {best_game.visitante}",
            "fonte": candidate.channel_key,
            "video_id": candidate.video_id,
            "url": youtube_url(candidate.video_id),
            "titulo": candidate.title,
            "status": candidate.status,
            "confianca": round(best_eval.confidence, 4),
            "motivos": best_eval.reasons,
        })
    return matched, accepted, rejected


def build_outputs(
    root: Path,
    current_time: dt.datetime,
    args: argparse.Namespace,
    client: Optional[YouTubeClient],
) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    config = load_json(root / "dados-br/config-transmissoes-aovivo.json", {})
    getv_config = load_json(root / "dados-br/getv-config.json", {})
    aliases = getv_config.get("aliases_clubes") or {}
    existing = load_json(root / "dados-br/transmissoes-aovivo.json", {"jogos": {}})
    manual = load_json(root / "dados-br/transmissoes-aovivo-manual.json", {"jogos": {}})
    games = load_games(root / "jogos.json")

    before_minutes = int(config.get("janela_antes_horas", 24) * 60)
    after_minutes = int(config.get("janela_depois_inicio_minutos", 90))
    targets = [
        game for game in games
        if game.estado != "post"
        and -after_minutes <= (game.kickoff - current_time).total_seconds() / 60 <= before_minutes
    ]
    if args.event_id:
        targets = [game for game in games if game.event_id == args.event_id]

    output_base = {
        "fonte": "YouTube oficial — CazéTV e GE TV",
        "politica": {
            "prioridade": ["cazetv", "getv"],
            "regra": "Somente canais oficiais configurados; CazéTV tem prioridade sobre GE TV; link único.",
            "janela": f"de {config.get('janela_antes_horas', 24)}h antes até {after_minutes} min após o início",
            "manual": "dados-br/transmissoes-aovivo-manual.json tem prioridade absoluta",
        },
        "jogos": {},
    }

    if not targets:
        keep_past = int(config.get("manter_apos_inicio_horas", 3) * 60)
        game_by_id = {g.event_id: g for g in games}
        for event_id, entry in (existing.get("jogos") or {}).items():
            game = game_by_id.get(event_id)
            if game and (game.kickoff - current_time).total_seconds() / 60 >= -keep_past:
                output_base["jogos"][event_id] = entry
        audit = {
            "fonte": output_base["fonte"],
            "resumo": {
                "jogos_na_janela": 0,
                "busca_streams_executada": False,
                "transmissoes_publicadas": len(output_base["jogos"]),
                "sem_transmissao": 0,
                "erros": 0,
            },
            "jogos_analisados": [],
            "aceitos": [],
            "rejeitados": [],
            "sem_transmissao": [],
            "erros": [],
            "quota_estimada_youtube": {"unidades": 0, "requisicoes": {}},
        }
        return output_base, audit, False

    if client is None:
        raise RuntimeError("YOUTUBE_API_KEY não configurada para jogo dentro da janela de busca")

    errors: List[str] = []
    channels = resolve_channels(client, config, errors)
    missing_channels = [str(ch.get("chave")) for ch in config.get("canais") or [] if str(ch.get("chave")) not in channels]
    if missing_channels:
        errors.append("Canais oficiais não resolvidos: " + ", ".join(missing_channels))

    candidates: List[Candidate] = []

    # 1) Aba /streams oficial: costuma publicar a live futura antes de ela
    #    aparecer com destaque na playlist de uploads.
    for channel in channels.values():
        candidates.extend(scan_streams_page(
            client, channel, int(config.get("streams_max_itens") or 120), errors
        ))

    # 2) Playlist de uploads via API. Mantida como fonte independente e
    #    redundante para quando o HTML do YouTube muda ou sofre bloqueio.
    for channel in channels.values():
        candidates.extend(scan_uploads(client, channel, int(config.get("uploads_max_itens") or 500), errors))

    # 3) Revalida links já existentes/manuais para manter status atualizado
    existing_ids = load_existing_video_ids(existing, manual)
    if existing_ids:
        try:
            details = fetch_video_details(client, existing_ids)
            id_to_channel_key = {c.get("channel_id"): key for key, c in channels.items()}
            for item in details:
                channel_id = str((item.get("snippet") or {}).get("channelId") or "")
                key = str(id_to_channel_key.get(channel_id) or "")
                if key:
                    cand = candidate_from_video(item, key, "validação-direta")
                    if cand and cand.status in {"upcoming", "live"}:
                        candidates.append(cand)
        except Exception as exc:
            errors.append(f"Falha ao revalidar links existentes: {exc}")

    # Deduplica: /streams > uploads > validação-direta.
    source_rank = {"streams-page": 3, "uploads": 2, "validação-direta": 1}
    unique: Dict[str, Candidate] = {}
    for cand in candidates:
        old = unique.get(cand.video_id)
        if old is None or source_rank.get(cand.source, 0) > source_rank.get(old.source, 0):
            unique[cand.video_id] = cand
    candidates = list(unique.values())

    matched, accepted, rejected = match_candidates_to_games(targets, candidates, channels, config, aliases)
    priority = list(config.get("prioridade") or ["cazetv", "getv"])

    published: Dict[str, Any] = {}
    no_stream: List[Dict[str, Any]] = []
    game_reports: List[Dict[str, Any]] = []
    for game in targets:
        manual_links = manual_links_for_game(manual, game, channels)
        automatic_links: Dict[str, Dict[str, Any]] = {}
        for source_key, cand in matched.get(game.event_id, {}).items():
            automatic_links[source_key] = cand.public(str(channels[source_key].get("nome") or source_key))

        existing_links = existing_links_for_game(existing, game)
        valid_candidate_ids = {c.video_id for c in candidates if c.status in {"upcoming", "live"}}
        for source_key, link in existing_links.items():
            if str(link.get("video_id")) in valid_candidate_ids and source_key not in automatic_links:
                automatic_links[source_key] = link

        links = automatic_links
        origin = "automático"
        if manual_links:
            links = {**automatic_links, **manual_links}
            origin = "manual"
        principal, alternatives = choose_links(links, priority)
        entry = {
            "event_id": game.event_id,
            "rodada": game.rodada,
            "mandante": game.mandante,
            "visitante": game.visitante,
            "data_iso": iso_brt(game.kickoff),
            "estadio": game.estadio,
            "origem": origin,
            "principal": principal,
            "alternativas": alternatives,
        }
        if principal:
            published[game.event_id] = entry
        else:
            no_stream.append({
                "event_id": game.event_id,
                "rodada": game.rodada,
                "jogo": f"{game.mandante} x {game.visitante}",
                "data_iso": iso_brt(game.kickoff),
                "motivo": "nenhuma transmissão oficial validada em CazéTV ou GE TV",
            })
        game_reports.append({
            "event_id": game.event_id,
            "rodada": game.rodada,
            "jogo": f"{game.mandante} x {game.visitante}",
            "data_iso": iso_brt(game.kickoff),
            "principal": principal.get("nome") if principal else "",
            "fontes_encontradas": [principal.get("nome")] if principal else [],
            "manual": bool(manual_links),
        })

    output_base["jogos"] = dict(sorted(published.items(), key=lambda kv: kv[1].get("data_iso", "")))
    audit = {
        "fonte": output_base["fonte"],
        "politica": output_base["politica"],
        "resumo": {
            "jogos_na_janela": len(targets),
            "busca_streams_executada": True,
            "candidatos_oficiais_encontrados": len(candidates),
            "transmissoes_publicadas": len(published),
            "sem_transmissao": len(no_stream),
            "erros": len(errors),
        },
        "canais_resolvidos": channels,
        "jogos_analisados": game_reports,
        "aceitos": accepted,
        "rejeitados": rejected,
        "sem_transmissao": no_stream,
        "erros": errors,
        "quota_estimada_youtube": {
            "unidades": client.quota_estimated,
            "requisicoes": client.requests,
            "observacao": "search.list não é usado. A aba /streams custa apenas videos.list; a playlist de uploads mantém redundância. A execução típica permanece muito abaixo da cota diária gratuita do YouTube Data API.",
        },
    }
    return output_base, audit, True


def selftest() -> None:
    aliases = {
        "Botafogo": ["botafogo-rj"],
        "Santos": ["santos fc"],
        "Bragantino": ["red bull bragantino", "rb bragantino"],
        "Athletico-PR": ["athletico paranaense"],
    }
    config = {
        "palavras_rejeitadas": ["melhores momentos", "pre jogo", "pós jogo", "react", "radio"],
        "termos_competicao": ["brasileirao", "brasileirão"],
        "tolerancia_horario_minutos": 180,
        "confianca_minima": 0.72,
    }
    game = Game("1", 19, dt.datetime(2026, 7, 16, 19, 30, tzinfo=TZ), "Botafogo", "Santos", "pre")
    caze = Candidate("AAAAAAAAAAA", "cazetv", "UC1", "CazéTV", "BOTAFOGO X SANTOS | BRASILEIRÃO 2026 | AO VIVO", "", "upcoming", dt.datetime(2026, 7, 16, 18, 30, tzinfo=TZ), None, None)
    ev = evaluate_candidate(caze, game, config, aliases)
    assert not ev.rejected_reason and ev.confidence >= 0.72, ev

    wrong = Candidate("BBBBBBBBBBB", "getv", "UC2", "ge tv", "BOTAFOGO X SANTOS | MELHORES MOMENTOS", "", "upcoming", game.kickoff, None, None)
    assert evaluate_candidate(wrong, game, config, aliases).rejected_reason

    far = Candidate("CCCCCCCCCCC", "getv", "UC2", "ge tv", "BOTAFOGO X SANTOS | AO VIVO", "", "upcoming", game.kickoff + dt.timedelta(hours=6), None, None)
    assert "horário incompatível" in evaluate_candidate(far, game, config, aliases).rejected_reason

    alias_game = Game("2", 20, game.kickoff, "Bragantino", "Athletico-PR", "pre")
    alias_cand = Candidate("DDDDDDDDDDD", "getv", "UC2", "ge tv", "RB BRAGANTINO X ATHLETICO PARANAENSE AO VIVO", "Brasileirão", "live", None, game.kickoff, None)
    assert not evaluate_candidate(alias_cand, alias_game, config, aliases).rejected_reason

    # Prioridade: CazéTV vence GE TV; link único (alternativas vazio)
    principal, alternatives = choose_links({"getv": {"fonte": "getv"}, "cazetv": {"fonte": "cazetv"}}, ["cazetv", "getv"])
    assert principal and principal["fonte"] == "cazetv"
    assert alternatives == [], f"alternativas devem ser vazias, got {alternatives}"

    assert video_id_from_url("https://www.youtube.com/watch?v=54apQSJpf0A") == "54apQSJpf0A"
    assert video_id_from_url("https://youtu.be/54apQSJpf0A?t=2") == "54apQSJpf0A"

    # Teste scraping: extrai IDs de HTML simulado
    html_fake = '''
    {"videoId":"Cih-UxYNCSs"}
    {"videoId":"BBBBBBBBBBB"}
    watch?v=CCCCCCCCCCC
    '''
    ids_found = extract_video_ids_from_streams_html(html_fake)
    assert "Cih-UxYNCSs" in ids_found, f"ID da live Cazé não encontrado: {ids_found}"
    assert len(ids_found) == 3

    print("SELFTEST OK: vínculo, rejeições, aliases, prioridade CazéTV, link único, /streams e uploads")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Raiz do repositório")
    parser.add_argument("--dry-run", action="store_true", help="Analisa sem gravar arquivos")
    parser.add_argument("--offline", action="store_true", help="Não acessa YouTube; útil apenas para validar janela/JSONs")
    parser.add_argument("--no-search", action="store_true", help="Legado: sem efeito (search.list não é mais usado)")
    parser.add_argument("--force-search", action="store_true", help="Legado: sem efeito (search.list não é mais usado)")
    parser.add_argument("--event-id", default="", help="Limita a um event_id")
    parser.add_argument("--now", default="", help="Horário ISO para testes")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.selftest:
        selftest()
        return 0

    root = Path(args.root).resolve()
    current_time = parse_datetime(args.now) if args.now else now_brt()
    if current_time is None:
        raise RuntimeError("--now inválido")

    for rel in ("jogos.json", "dados-br/config-transmissoes-aovivo.json", "dados-br/transmissoes-aovivo-manual.json"):
        if not (root / rel).exists():
            raise RuntimeError(f"Arquivo obrigatório ausente: {rel}")
        load_json(root / rel, {})

    api_key = str(os.environ.get("YOUTUBE_API_KEY") or "").strip()
    client: Optional[YouTubeClient] = None
    if not args.offline and api_key:
        client = YouTubeClient(api_key)

    output, audit, streams_ran = build_outputs(root, current_time, args, client)
    output_changed = save_if_changed(root / "dados-br/transmissoes-aovivo.json", output, current_time, args.dry_run)
    audit_changed = save_if_changed(root / "dados-br/auditoria-transmissoes-aovivo.json", audit, current_time, args.dry_run)

    print(json.dumps({
        "agora": iso_brt(current_time),
        "dry_run": args.dry_run,
        "offline": args.offline,
        "output_changed": output_changed,
        "audit_changed": audit_changed,
        "resumo": audit.get("resumo", {}),
        "quota_estimada_youtube": audit.get("quota_estimada_youtube", {}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)

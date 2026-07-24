#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fontes complementares e auditáveis do Brasileirão.

A ESPN permanece a fonte primária do projeto. Este módulo só é consultado
quando a auditoria detecta divergência entre scoreboard e standings ou quando
a grade de transmissão ainda não foi preenchida pela ESPN.

Ordem operacional dos resultados:
1. ESPN (tratada por atualizar_espn.py);
2. tabela detalhada oficial da CBF;
3. API-Football, somente quando a chave e a liga forem configuradas;
4. override manual versionado (tratado por atualizar_espn.py).

Somente biblioteca padrão.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Mapping, Optional

FUSO_BRASILIA = timezone(timedelta(hours=-3))
CBF_TABELA_DETALHADA_URL = os.environ.get(
    "CBF_TABELA_DETALHADA_URL",
    "https://www.cbf.com.br/futebol-brasileiro/tabelas/campeonato-brasileiro/serie-a/2026?documento=Tabela+Detalhada",
)
CBF_TABELA_DETALHADA_URLS = tuple(dict.fromkeys(filter(None, (
    CBF_TABELA_DETALHADA_URL,
    "https://cbf-hml.cbf.com.br/futebol-brasileiro/tabelas/campeonato-brasileiro/serie-a/2026?documento=Tabela+Detalhada",
))))
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


@dataclass(frozen=True)
class CBFPartida:
    referencia: str
    rodada: int
    mandante: str
    visitante: str
    data_iso: str
    placar_mandante: Optional[int]
    placar_visitante: Optional[int]
    transmissao: str
    origem: str = CBF_TABELA_DETALHADA_URL

    def public(self) -> dict[str, Any]:
        return asdict(self)


def normalizar_texto(valor: Any) -> str:
    texto = unicodedata.normalize("NFD", str(valor or ""))
    texto = "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")
    texto = texto.lower().replace("&", " e ")
    texto = re.sub(r"[^a-z0-9+:/.' -]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def fetch_text(url: str, *, timeout: int = 30, tentativas: int = 2) -> str:
    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            separador = "&" if "?" in url else "?"
            req = urllib.request.Request(
                f"{url}{separador}_={int(time.time())}", headers=HEADERS_HTML
            )
            with urllib.request.urlopen(req, timeout=timeout + (tentativa - 1) * 10) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            if tentativa < tentativas:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"falha ao buscar página oficial: {url} :: {ultimo}")


class _TabelaHTMLParser(HTMLParser):
    """Extrai linhas/células sem depender das classes CSS da página da CBF."""

    BREAK_TAGS = {"br", "p", "div", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._fallback: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._flush_row()
            self._row = []
        elif tag in {"td", "th"}:
            self._flush_cell()
            self._cell = []
        elif tag == "img":
            attrs_map = dict(attrs)
            alt = attrs_map.get("alt") or ""
            if alt:
                self._append(alt)
        elif tag in self.BREAK_TAGS:
            self._append(" \n ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"}:
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag in self.BREAK_TAGS:
            self._append(" \n ")

    def handle_data(self, data: str) -> None:
        self._append(data)

    def close(self) -> None:
        super().close()
        self._flush_cell()
        self._flush_row()

    def _append(self, value: str) -> None:
        target = self._cell if self._cell is not None else self._fallback
        target.append(value)

    @staticmethod
    def _clean(parts: Iterable[str]) -> str:
        text = html.unescape(" ".join(parts)).replace("\xa0", " ")
        text = re.sub(r"\s*\n\s*", " | ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"(?:\s*\|\s*)+", " | ", text)
        return text.strip(" |")

    def _flush_cell(self) -> None:
        if self._cell is None:
            return
        cleaned = self._clean(self._cell)
        if self._row is None:
            self._row = []
        self._row.append(cleaned)
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row is not None:
            cells = [cell for cell in self._row if cell]
            if cells:
                self.rows.append(cells)
        self._row = None

    def fallback_text(self) -> str:
        return self._clean(self._fallback)


def _find_teams(text: str, resolver: Callable[[Any], Optional[str]]) -> list[tuple[int, str]]:
    """Localiza clubes em ordem de aparição usando janelas de palavras."""
    normalized = normalizar_texto(text)
    tokens = normalized.split()
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for start in range(len(tokens)):
        # Nomes de clubes no Brasil cabem com folga em até seis palavras.
        for size in range(6, 0, -1):
            end = start + size
            if end > len(tokens):
                continue
            candidate = " ".join(tokens[start:end])
            club = resolver(candidate)
            if club and club not in seen:
                found.append((start, club))
                seen.add(club)
                break
    found.sort(key=lambda item: item[0])
    return found


def _parse_datetime_brt(text: str) -> Optional[datetime]:
    match = re.search(
        r"\b(\d{2})/(\d{2})/(\d{4})\b.*?\b(?:às|as)\s*(\d{1,2})[h:]?(\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    day, month, year, hour, minute = map(int, match.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=FUSO_BRASILIA)
    except ValueError:
        return None


def _parse_score(text: str) -> tuple[Optional[int], Optional[int]]:
    # Evita capturar o "x" sem números usado em partidas futuras.
    match = re.search(
        r"(?<!\d)(\d{1,2})\s*(?:\([^)]*\)\s*)?[xX×]\s*(?:\([^)]*\)\s*)?(\d{1,2})(?!\d)",
        text,
    )
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _parse_transmission(cells: list[str], row_text: str) -> str:
    candidates = [cell for cell in cells if "transmiss" in normalizar_texto(cell)]
    source = candidates[-1] if candidates else row_text
    match = re.search(r"transmiss[aã]o\s*:\s*(.+?)(?:\s*\|\s*|$)", source, flags=re.IGNORECASE)
    value = (match.group(1) if match else "").strip(" .|-")
    if normalizar_texto(value) in {"", "nao definido", "a definir"}:
        return ""
    return value


def parse_cbf_tabela_detalhada(
    html_text: str,
    *,
    resolver: Callable[[Any], Optional[str]],
    origem: str = CBF_TABELA_DETALHADA_URL,
) -> list[CBFPartida]:
    parser = _TabelaHTMLParser()
    parser.feed(html_text)
    parser.close()

    rows = parser.rows
    # Proteção para mudanças de markup: o buscador da CBF também pode devolver
    # os registros sem <tr>. Neste caso, separa pelo marcador "Ref:".
    if not rows:
        raw = parser.fallback_text()
        rows = [[chunk] for chunk in re.split(r"(?=\bRef:\s*\d+)", raw) if "Rodada:" in chunk]

    out: list[CBFPartida] = []
    seen: set[tuple[int, str, str, str]] = set()
    for cells in rows:
        row_text = " | ".join(cells)
        if "rodada" not in normalizar_texto(row_text) or "ref" not in normalizar_texto(row_text):
            continue
        round_match = re.search(r"Rodada\s*:\s*(\d+)", row_text, flags=re.IGNORECASE)
        ref_match = re.search(r"Ref\s*:\s*(\d+)", row_text, flags=re.IGNORECASE)
        kickoff = _parse_datetime_brt(row_text)
        teams = _find_teams(row_text, resolver)
        if not round_match or not kickoff or len(teams) < 2:
            continue
        # Escolhe os dois primeiros clubes distintos. Títulos/cabeçalhos não têm
        # data e rodada juntos, então não entram aqui.
        home, away = teams[0][1], teams[1][1]
        if home == away:
            continue
        home_score, away_score = _parse_score(row_text)
        item = CBFPartida(
            referencia=ref_match.group(1) if ref_match else "",
            rodada=int(round_match.group(1)),
            mandante=home,
            visitante=away,
            data_iso=kickoff.strftime("%Y-%m-%dT%H:%M"),
            placar_mandante=home_score,
            placar_visitante=away_score,
            transmissao=_parse_transmission(cells, row_text),
            origem=origem,
        )
        key = (item.rodada, item.mandante, item.visitante, item.data_iso)
        if key not in seen:
            out.append(item)
            seen.add(key)
    out.sort(key=lambda x: (x.data_iso, x.rodada, x.mandante, x.visitante))
    return out


def buscar_tabela_detalhada_cbf(
    *, resolver: Callable[[Any], Optional[str]], url: str = ""
) -> list[CBFPartida]:
    """Busca a tabela oficial, tentando os hosts públicos conhecidos da CBF.

    O domínio principal é priorizado. O host alternativo é mantido porque a
    própria CBF o utiliza em alguns links de impressão/tabela detalhada. Um
    endereço explícito em ``CBF_TABELA_DETALHADA_URL`` continua soberano.
    """
    urls = (url,) if url else CBF_TABELA_DETALHADA_URLS
    errors: list[str] = []
    for candidate in urls:
        try:
            page = fetch_text(candidate)
            rows = parse_cbf_tabela_detalhada(page, resolver=resolver, origem=candidate)
            if rows:
                return rows
            errors.append(f"{candidate}: página carregada sem partidas reconhecíveis")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
    raise RuntimeError("nenhuma tabela detalhada oficial da CBF pôde ser lida :: " + " | ".join(errors))


def _parse_iso_brt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASILIA)
    return dt.astimezone(FUSO_BRASILIA)


def localizar_partida_cbf(
    rows: Iterable[CBFPartida],
    *,
    mandante: str,
    visitante: str,
    rodada: int = 0,
    data_iso: str = "",
    tolerancia_horas: int = 36,
) -> Optional[CBFPartida]:
    target_dt = _parse_iso_brt(data_iso)
    candidates: list[tuple[float, CBFPartida]] = []
    for row in rows:
        if row.mandante != mandante or row.visitante != visitante:
            continue
        if rodada and row.rodada != rodada:
            continue
        row_dt = _parse_iso_brt(row.data_iso)
        distance = 0.0
        if target_dt and row_dt:
            distance = abs((row_dt - target_dt).total_seconds())
            if distance > tolerancia_horas * 3600:
                continue
        candidates.append((distance, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def fetch_api_football_fixtures(
    *,
    api_key: str,
    league_id: str,
    season: int,
    match_date: date,
    timeout: int = 25,
) -> list[dict[str, Any]]:
    if not api_key or not league_id:
        return []
    query = urllib.parse.urlencode({
        "league": league_id,
        "season": season,
        "date": match_date.isoformat(),
        "timezone": "America/Sao_Paulo",
    })
    req = urllib.request.Request(
        f"{API_FOOTBALL_BASE}/fixtures?{query}",
        headers={
            "x-apisports-key": api_key,
            "Accept": "application/json",
            "User-Agent": "Brasileirao2026Almoco/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API-Football HTTP {exc.code}: {body[:400]}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"falha na API-Football: {exc}") from exc
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"API-Football devolveu erros: {errors}")
    return [dict(item) for item in (payload.get("response") or []) if isinstance(item, Mapping)]


def localizar_fixture_api_football(
    fixtures: Iterable[Mapping[str, Any]],
    *,
    mandante: str,
    visitante: str,
    resolver: Callable[[Any], Optional[str]],
) -> Optional[dict[str, Any]]:
    final_statuses = {"FT", "AET", "PEN"}
    matches: list[dict[str, Any]] = []
    for raw in fixtures:
        teams = raw.get("teams") or {}
        home = resolver((teams.get("home") or {}).get("name"))
        away = resolver((teams.get("away") or {}).get("name"))
        status = str(((raw.get("fixture") or {}).get("status") or {}).get("short") or "").upper()
        goals = raw.get("goals") or {}
        if home != mandante or away != visitante or status not in final_statuses:
            continue
        if goals.get("home") is None or goals.get("away") is None:
            continue
        matches.append({
            "fixture_id": str(((raw.get("fixture") or {}).get("id") or "")),
            "placar_mandante": int(goals["home"]),
            "placar_visitante": int(goals["away"]),
            "status": status,
            "origem": "API-Football",
        })
    return matches[0] if len(matches) == 1 else None


def _selftest() -> None:
    aliases = {
        "botafogo": "Botafogo",
        "vitoria": "Vitória",
        "vitoria ba": "Vitória",
        "vasco da gama": "Vasco da Gama",
        "vasco da gama saf": "Vasco da Gama",
        "mirassol": "Mirassol",
        "bahia": "Bahia",
        "corinthians": "Corinthians",
    }

    def resolver(value: Any) -> Optional[str]:
        n = normalizar_texto(value).replace(" saf", "")
        return aliases.get(n)

    sample = """
    <table><tbody>
      <tr><td>Ref: 032<br>Rodada: 4</td><td><span>0</span> x <span>0</span></td>
          <td><img alt="Botafogo">Botafogo <img alt="Vitória-BA">Vitória</td>
          <td>Data: 23/07/2026 - quinta-feira às 19h30</td>
          <td>Transmissão: Cazé TV</td></tr>
      <tr><td>Ref: 192<br>Rodada: 20</td><td> x </td>
          <td>Vasco da Gama SAF Mirassol</td>
          <td>Data: 25/07/2026 - sábado às 20h30</td>
          <td>Transmissão: Premiere, Record, YouTube / Cazé TV</td></tr>
    </tbody></table>
    """
    rows = parse_cbf_tabela_detalhada(sample, resolver=resolver, origem="teste")
    assert len(rows) == 2, rows
    first = localizar_partida_cbf(
        rows, mandante="Botafogo", visitante="Vitória", rodada=4, data_iso="2026-07-23T19:30"
    )
    assert first and (first.placar_mandante, first.placar_visitante) == (0, 0)
    second = localizar_partida_cbf(
        rows, mandante="Vasco da Gama", visitante="Mirassol", rodada=20, data_iso="2026-07-25T20:30"
    )
    assert second and second.transmissao == "Premiere, Record, YouTube / Cazé TV"
    assert second.placar_mandante is None and second.placar_visitante is None
    print("Selftest fontes complementares do Brasileirão OK")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        _selftest()
    else:
        raise SystemExit("Use --selftest; este módulo é importado pelos coletores.")

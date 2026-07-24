#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza transmissões oficiais de TV/streaming do Brasileirão.

- Lê a agenda local em jogos.json.
- Usa a ESPN como fonte principal e a tabela detalhada da CBF para completar
  canais que ainda não aparecem no scoreboard.
- Extrai provedores oficiais conhecidos de TV e streaming (Premiere, SporTV,
  Disney+/ESPN, Prime Video, Globo, Record, GE TV e CazéTV).
- Preserva os cadastros manuais e mantém GE TV/CazéTV também na grade de
  "onde assistir"; quando o vídeo exato é localizado,
  dados-br/transmissoes-aovivo.json continua tendo prioridade visual.
- Não cria links de terceiros; a página usa apenas destinos oficiais já
  definidos no JavaScript.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
API = "https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atualizar_espn import para_canonico  # noqa: E402
from fontes_brasileirao import (  # noqa: E402
    CBFPartida,
    buscar_tabela_detalhada_cbf,
    localizar_partida_cbf,
)

AGENDA = ROOT / "jogos.json"
OUTPUT = ROOT / "dados-br" / "transmissoes-tv.json"
MANUAL = ROOT / "transmissoes.json"

PROVIDERS = [
    ("Premiere", ("premiere",)),
    ("SporTV", ("sportv", "sport tv")),
    ("Disney+ / ESPN", ("disney+", "disney plus", "espn")),
    ("Prime Video", ("prime video", "amazon prime", "amazon prime video")),
    ("Globo", ("tv globo", "globo")),
    ("Record", ("record", "record tv", "recordtv")),
    ("GE TV", ("ge tv", "getv")),
    ("CazéTV", ("cazetv", "caze tv")),
]
ALLOWED_CHANNELS = {label for label, _aliases in PROVIDERS}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_closed_channel(value: Any) -> Optional[str]:
    """Retorna o nome canônico de um canal/plataforma oficial aceito pelo site."""
    wanted = norm(value)
    if not wanted:
        return None
    for label, aliases in PROVIDERS:
        candidates = (label, *aliases)
        if any(norm(candidate) == wanted for candidate in candidates):
            return label
    return None


def sanitize_closed_channels(values: Any) -> List[str]:
    """Normaliza e remove duplicatas dos canais oficiais aceitos."""
    if isinstance(values, str):
        values = re.split(r"\s*(?:/|,|;|\be\b)\s*", values, flags=re.IGNORECASE)
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for raw in values:
        label = canonical_closed_channel(raw)
        if label and label not in out:
            out.append(label)
    return out


def sanitize_manual_entry(item: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Preserva o cadastro manual e normaliza todos os provedores oficiais."""
    cleaned = copy.deepcopy(dict(item))
    cleaned["canais"] = sanitize_closed_channels(cleaned.get("canais"))
    if not cleaned["canais"]:
        return None
    return cleaned


TEAM_ALIASES = {
    "athletico": "athletico pr", "athletico paranaense": "athletico pr", "atletico pr": "athletico pr",
    "atletico mineiro": "atletico mg", "clube atletico mineiro": "atletico mg",
    "red bull bragantino": "bragantino", "rb bragantino": "bragantino",
    "vasco": "vasco da gama", "cr vasco da gama": "vasco da gama",
    "ec bahia": "bahia", "ec vitoria": "vitoria", "sao paulo fc": "sao paulo",
    "gremio fbpa": "gremio", "sc internacional": "internacional", "clube do remo": "remo",
}


def team_key(value: Any) -> str:
    key = norm(value)
    return TEAM_ALIASES.get(key, key)


def manual_entries(manual: Mapping[str, Any], agenda: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Converte transmissoes.json em registros duráveis ligados à agenda atual.

    O arquivo manual é a fonte editorial oficial das rodadas publicadas. Ele
    prevalece sobre a ESPN, que frequentemente divulga os canais muito tarde.
    """
    jogos = agenda.get("jogos") or []
    if not isinstance(jogos, list):
        jogos = []
    out: Dict[str, Dict[str, Any]] = {}
    for raw in manual.get("transmissoes") or []:
        if not isinstance(raw, Mapping):
            continue
        canais = sanitize_closed_channels(raw.get("canais") or raw.get("transmissao"))
        if not canais:
            continue
        mand = team_key(raw.get("mandante"))
        vist = team_key(raw.get("visitante"))
        rodada = int(raw.get("rodada") or 0)
        event_id = str(raw.get("event_id") or "").strip()
        jogo = None
        for cand in jogos:
            cand_id = str(cand.get("event_id") or cand.get("id") or "")
            if event_id and cand_id == event_id:
                jogo = cand
                break
            if mand and vist and team_key((cand.get("mandante") or {}).get("nome") if isinstance(cand.get("mandante"), Mapping) else cand.get("mandante")) == mand and team_key((cand.get("visitante") or {}).get("nome") if isinstance(cand.get("visitante"), Mapping) else cand.get("visitante")) == vist:
                if not rodada or int(cand.get("rodada") or 0) == rodada:
                    jogo = cand
                    break
        if not jogo:
            continue
        event_id = str(jogo.get("event_id") or jogo.get("id") or "")
        if not event_id:
            continue
        nome_m = (jogo.get("mandante") or {}).get("nome") if isinstance(jogo.get("mandante"), Mapping) else jogo.get("mandante")
        nome_v = (jogo.get("visitante") or {}).get("nome") if isinstance(jogo.get("visitante"), Mapping) else jogo.get("visitante")
        out[event_id] = {
            "event_id": event_id,
            "rodada": int(jogo.get("rodada") or rodada or 0),
            "mandante": nome_m or raw.get("mandante") or "",
            "visitante": nome_v or raw.get("visitante") or "",
            "data_iso": jogo.get("data_iso") or raw.get("data_iso") or "",
            "tipo": "tv_ou_streaming_oficial",
            "canais": canais,
            "origem": "manual confirmado — transmissoes.json",
            "fonte_editorial": raw.get("fonte") or "programação oficial publicada",
        }
    return out


def parse_dt(value: Any) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        obj = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=TZ)
        return obj.astimezone(TZ)
    except ValueError:
        return None


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(fallback)


def broadcasts(event: Mapping[str, Any]) -> List[str]:
    comp = ((event.get("competitions") or [{}])[0]) or {}
    values: List[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, Mapping):
            return
        names = node.get("names")
        if isinstance(names, list):
            values.extend(str(x) for x in names if x)
        for key in ("name", "shortName", "displayName", "network", "callLetters"):
            if node.get(key):
                values.append(str(node[key]))
        if node.get("media"):
            walk(node["media"])

    # A ESPN costuma usar broadcasts em alguns jogos e geoBroadcasts em outros.
    # O parser anterior ignorava geoBroadcasts, por isso muitos canais próximos
    # nunca entravam no JSON mesmo após o workflow rodar.
    for source in (
        comp.get("broadcasts"), comp.get("geoBroadcasts"),
        event.get("broadcasts"), event.get("geoBroadcasts")
    ):
        walk(source)

    out: List[str] = []
    for raw in values:
        n = norm(raw)
        for label, aliases in PROVIDERS:
            if any(norm(alias) in n for alias in aliases) and label not in out:
                out.append(label)
    return out


def fetch_scoreboard(start: dt.date, end: dt.date) -> Dict[str, Any]:
    dates = f"{start:%Y%m%d}-{end:%Y%m%d}"
    url = API + "?" + urllib.parse.urlencode({"dates": dates, "limit": 200})
    req = urllib.request.Request(url, headers={"User-Agent": "brasileirao-tv-discovery/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def auto_entries(agenda: Mapping[str, Any], scoreboard: Mapping[str, Any]) -> Dict[str, Any]:
    local = {str(j.get("event_id") or ""): j for j in (agenda.get("jogos") or []) if j.get("event_id")}
    out: Dict[str, Any] = {}
    for event in scoreboard.get("events") or []:
        event_id = str(event.get("id") or "")
        channels = broadcasts(event)
        if not event_id or not channels:
            continue
        item = local.get(event_id, {})
        comp = ((event.get("competitions") or [{}])[0]) or {}
        competitors = comp.get("competitors") or []
        home = next((x for x in competitors if x.get("homeAway") == "home"), competitors[0] if competitors else {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
        home_name = ((home.get("team") or {}).get("displayName") or item.get("mandante") or "")
        away_name = ((away.get("team") or {}).get("displayName") or item.get("visitante") or "")
        kickoff = event.get("date") or comp.get("date") or item.get("data_iso") or ""
        out[event_id] = {
            "event_id": event_id,
            "rodada": int(item.get("rodada") or 0),
            "mandante": home_name,
            "visitante": away_name,
            "data_iso": kickoff,
            "tipo": "assinatura",
            "canais": channels,
            "origem": "ESPN automático",
        }
    return out



def cbf_entries(agenda: Mapping[str, Any], rows: Iterable[CBFPartida]) -> Dict[str, Dict[str, Any]]:
    """Relaciona a tabela detalhada oficial da CBF à agenda ESPN local."""
    out: Dict[str, Dict[str, Any]] = {}
    rows_list = list(rows)
    for game in agenda.get("jogos") or []:
        event_id = str(game.get("event_id") or game.get("id") or "").strip()
        if not event_id:
            continue
        home = (game.get("mandante") or {}).get("nome") if isinstance(game.get("mandante"), Mapping) else game.get("mandante")
        away = (game.get("visitante") or {}).get("nome") if isinstance(game.get("visitante"), Mapping) else game.get("visitante")
        home = para_canonico(home)
        away = para_canonico(away)
        if not home or not away:
            continue
        row = localizar_partida_cbf(
            rows_list,
            mandante=home,
            visitante=away,
            rodada=int(game.get("rodada") or 0),
            data_iso=str(game.get("data_iso") or ""),
        )
        if not row or not row.transmissao:
            continue
        channels = sanitize_closed_channels(row.transmissao)
        if not channels:
            continue
        out[event_id] = {
            "event_id": event_id,
            "rodada": int(game.get("rodada") or row.rodada or 0),
            "mandante": home,
            "visitante": away,
            "data_iso": game.get("data_iso") or row.data_iso,
            "tipo": "tv_ou_streaming_oficial",
            "canais": channels,
            "origem": "CBF oficial — tabela detalhada",
            "fonte_editorial": row.origem,
            "referencia_cbf": row.referencia,
        }
    return out


def merge_cbf(generated: Dict[str, Dict[str, Any]], official: Mapping[str, Dict[str, Any]]) -> None:
    """Complementa a ESPN sem removê-la como fonte principal."""
    for event_id, cbf_item in official.items():
        existing = generated.get(event_id)
        if not existing:
            generated[event_id] = copy.deepcopy(cbf_item)
            continue
        merged = sanitize_closed_channels(list(existing.get("canais") or []) + list(cbf_item.get("canais") or []))
        if merged != list(existing.get("canais") or []):
            existing["canais"] = merged
            existing["origem"] = "ESPN automático + CBF oficial"
            existing["fonte_editorial_cbf"] = cbf_item.get("fonte_editorial")
            existing["referencia_cbf"] = cbf_item.get("referencia_cbf")

def build(
    existing: Mapping[str, Any],
    agenda: Mapping[str, Any],
    scoreboard: Mapping[str, Any],
    now: dt.datetime,
    manual: Optional[Mapping[str, Any]] = None,
    cbf_rows: Optional[Iterable[CBFPartida]] = None,
) -> Dict[str, Any]:
    generated = auto_entries(agenda, scoreboard)
    merge_cbf(generated, cbf_entries(agenda, cbf_rows or []))
    # Preserva cadastros manuais já publicados, inclusive entre execuções em que
    # a ESPN ainda não informou os canais.
    for event_id, item in (existing.get("jogos") or {}).items():
        if str(item.get("origem") or "").lower().startswith("manual"):
            cleaned = sanitize_manual_entry(item)
            if cleaned is not None:
                generated[str(event_id)] = cleaned
    # transmissoes.json é o cadastro editorial durável e tem prioridade final.
    generated.update(manual_entries(manual or {}, agenda))
    return {
        "descricao": "Transmissões oficiais por TV ou streaming, inclusive GE TV e CazéTV quando publicadas na programação.",
        "politica": {
            "origem": "ESPN automática; CBF oficial complementa canais ausentes; transmissoes.json é a última correção editorial; o vídeo exato do YouTube é mantido separadamente",
            "limite_links": 3,
            "regra": "Somente páginas oficiais dos serviços; alguns acessos podem exigir assinatura e login.",
        },
        "jogos": generated,
        "atualizado_em": now.astimezone(TZ).replace(microsecond=0).isoformat(),
    }


def selftest() -> None:
    agenda = {"jogos": [{"event_id": "1", "rodada": 19, "mandante": "Vitória", "visitante": "Vasco", "data_iso": "2026-07-16T19:30:00-03:00"}]}
    score = {"events": [{"id": "1", "date": "2026-07-16T22:30:00Z", "competitions": [{"geoBroadcasts": [{"media": {"shortName": "Premiere"}}, {"media": {"shortName": "SporTV"}}], "competitors": [{"homeAway": "home", "team": {"displayName": "Vitória"}}, {"homeAway": "away", "team": {"displayName": "Vasco da Gama"}}]}]}]}
    existing = {
        "jogos": {
            "2": {
                "event_id": "2",
                "origem": "manual confirmado",
                "canais": ["GE TV", "Amazon Prime Video", "Prime Video"],
            },
            "3": {
                "event_id": "3",
                "origem": "manual confirmado — YouTube",
                "canais": ["CazéTV"],
            },
        }
    }
    manual = {"transmissoes": [{"rodada": 19, "mandante": "Vitória", "visitante": "Vasco da Gama", "transmissao": "Record / Premiere"}]}
    cbf = [CBFPartida(
        referencia="001",
        rodada=19,
        mandante="Vitória",
        visitante="Vasco da Gama",
        data_iso="2026-07-16T19:30:00-03:00",
        placar_mandante=None,
        placar_visitante=None,
        transmissao="Globo / Premiere",
        origem="CBF teste",
    )]
    result = build(existing, agenda, score, dt.datetime(2026, 7, 16, 20, 0, tzinfo=TZ), manual, cbf)
    # A correção editorial final é intencionalmente soberana sobre ESPN/CBF.
    assert result["jogos"]["1"]["canais"] == ["Record", "Premiere"]
    assert result["jogos"]["1"]["origem"].startswith("manual confirmado")
    assert result["jogos"]["2"]["canais"] == ["GE TV", "Prime Video"]
    assert result["jogos"]["3"]["canais"] == ["CazéTV"]
    assert all(
        set(item.get("canais") or []).issubset(ALLOWED_CHANNELS)
        for item in result["jogos"].values()
    )
    cbf_only = build({"jogos": {}}, agenda, {"events": []}, dt.datetime(2026, 7, 16, 20, 0, tzinfo=TZ), {"transmissoes": []}, cbf)
    assert cbf_only["jogos"]["1"]["canais"] == ["Globo", "Premiere"]
    assert cbf_only["jogos"]["1"]["origem"].startswith("CBF oficial")
    print("Selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    now = dt.datetime.now(TZ)
    agenda = load_json(AGENDA, {"jogos": []})
    existing = load_json(OUTPUT, {"jogos": {}})
    manual = load_json(MANUAL, {"transmissoes": []})
    score = fetch_scoreboard(now.date() - dt.timedelta(days=1), now.date() + dt.timedelta(days=21))
    try:
        cbf_rows = buscar_tabela_detalhada_cbf(resolver=para_canonico)
        print(f"Tabela detalhada da CBF reconhecida: {len(cbf_rows)} partida(s)")
    except Exception as exc:  # noqa: BLE001
        cbf_rows = []
        print(f"::warning::Transmissões CBF indisponíveis; ESPN/manual preservados: {type(exc).__name__}: {exc}")
    payload = build(existing, agenda, score, now, manual, cbf_rows)
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    comparavel_novo = {k: v for k, v in payload.items() if k != "atualizado_em"}
    comparavel_antigo = {k: v for k, v in existing.items() if k != "atualizado_em"}
    if comparavel_novo == comparavel_antigo:
        print(f"Transmissões sem mudança: {len(payload['jogos'])} jogo(s); arquivo preservado.")
        return 0
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Transmissões TV atualizadas: {len(payload['jogos'])} jogo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

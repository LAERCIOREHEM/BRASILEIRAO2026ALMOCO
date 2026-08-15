#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busca playlists/vídeos de melhores momentos da GE TV e cruza com jogos do Brasileirão.

Execução 1: somente coleta e gera JSONs. Não altera layout do site.

Requisitos:
- Secret/variável YOUTUBE_API_KEY com chave da YouTube Data API v3.
- Usa apenas biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
BRT = dt.timezone(dt.timedelta(hours=-3), name="BRT")


def agora_iso() -> str:
    return dt.datetime.now(BRT).replace(microsecond=0).isoformat()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON inválido em {path}: {exc}") from exc


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def norm(txt: Any) -> str:
    s = str(txt or "").lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"&", " e ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def contem_termo(texto_norm: str, termo: str) -> bool:
    t = norm(termo)
    if not t:
        return False
    return bool(re.search(r"(?:^|\s)" + re.escape(t) + r"(?:\s|$)", texto_norm))


def rodada_do_texto(txt: str) -> Optional[int]:
    n = norm(txt)
    patterns = [
        r"(\d{1,2})\s*(?:a|o|ª|º)?\s*rodada",
        r"rodada\s*(\d{1,2})",
        r"r\s*(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, n)
        if m:
            try:
                r = int(m.group(1))
                if 1 <= r <= 38:
                    return r
            except ValueError:
                pass
    return None


def playlist_id_from_url_or_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "youtube.com" in value or "youtu.be" in value:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        return (qs.get("list") or [""])[0]
    return value


class YouTubeClient:
    def __init__(self, api_key: str, sleep: float = 0.05, timeout: int = 20) -> None:
        self.api_key = api_key
        self.sleep = sleep
        self.timeout = timeout
        self.requests = 0

    def get(self, resource: str, **params: Any) -> Dict[str, Any]:
        params = {k: v for k, v in params.items() if v not in (None, "", [])}
        params["key"] = self.api_key
        url = f"{YOUTUBE_API}/{resource}?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": "brasileirao-getv-bot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"YouTube API HTTP {exc.code} em {resource}: {body[:800]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Falha de rede na YouTube API em {resource}: {exc}") from exc
        self.requests += 1
        if self.sleep:
            time.sleep(self.sleep)
        return json.loads(payload)


def resolver_channel_id(client: YouTubeClient, config: Dict[str, Any]) -> str:
    canal = (config.get("channel_id") or "").strip()
    if canal:
        return canal

    # Primeiro usa playlist semente: playlists.list(id=...) retorna o channelId da playlist oficial.
    for seed in config.get("playlists_semente", []):
        pid = playlist_id_from_url_or_id(seed)
        if not pid:
            continue
        data = client.get("playlists", part="snippet", id=pid, maxResults=1)
        items = data.get("items") or []
        if items:
            channel_id = items[0].get("snippet", {}).get("channelId")
            if channel_id:
                return channel_id

    # Fallback barato: channels.list(forHandle=@getv)
    for handle in config.get("handles_candidatos", []):
        h = str(handle or "").strip()
        if not h:
            continue
        data = client.get("channels", part="id,snippet", forHandle=h, maxResults=1)
        items = data.get("items") or []
        if items:
            return items[0].get("id") or ""

    raise RuntimeError("Não foi possível identificar o channel_id da GE TV. Informe channel_id ou playlist semente em dados-br/getv-config.json.")


def listar_playlists_canal(client: YouTubeClient, channel_id: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    token: Optional[str] = None
    pages = 0
    while True:
        pages += 1
        data = client.get("playlists", part="snippet,contentDetails", channelId=channel_id, maxResults=50, pageToken=token)
        out.extend(data.get("items") or [])
        token = data.get("nextPageToken")
        if not token or pages >= max_pages:
            break
    return out


def playlist_eh_brasileirao(pl: Dict[str, Any], config: Dict[str, Any]) -> bool:
    sn = pl.get("snippet", {})
    titulo = norm(sn.get("title", ""))
    if "rodada" not in titulo:
        return False
    patterns = [norm(p) for p in config.get("padroes_titulo_playlist", [])]
    return any(p and p in titulo for p in patterns)


def playlist_publica(pl: Dict[str, Any]) -> Dict[str, Any]:
    sn = pl.get("snippet", {})
    cd = pl.get("contentDetails", {})
    titulo = sn.get("title", "")
    return {
        "playlist_id": pl.get("id"),
        "titulo": titulo,
        "rodada": rodada_do_texto(titulo),
        "published_at": sn.get("publishedAt"),
        "item_count": cd.get("itemCount"),
        "url": f"https://www.youtube.com/playlist?list={pl.get('id')}",
    }


def listar_videos_playlist(client: YouTubeClient, playlist_id: str, max_pages: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    token: Optional[str] = None
    pages = 0
    while True:
        pages += 1
        data = client.get("playlistItems", part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=token)
        out.extend(data.get("items") or [])
        token = data.get("nextPageToken")
        if not token or pages >= max_pages:
            break
    return out


def video_publico(item: Dict[str, Any], playlist_id: str, rodada: Optional[int]) -> Dict[str, Any]:
    sn = item.get("snippet", {})
    cd = item.get("contentDetails", {})
    vid = cd.get("videoId") or sn.get("resourceId", {}).get("videoId")
    thumbs = sn.get("thumbnails") or {}
    thumb = (thumbs.get("maxres") or thumbs.get("standard") or thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    return {
        "video_id": vid,
        "titulo": sn.get("title", ""),
        "descricao": sn.get("description", ""),
        "published_at": cd.get("videoPublishedAt") or sn.get("publishedAt"),
        "thumbnail": thumb,
        "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        "playlist_id": playlist_id,
        "rodada_playlist": rodada,
    }


@dataclass
class Jogo:
    chave: str
    event_id: str
    rodada: int
    mandante: str
    visitante: str
    data_iso: str = ""
    placar_mandante: Any = None
    placar_visitante: Any = None
    estado: str = ""
    concluido: bool = False


def nome_time(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("nome") or obj.get("name") or obj.get("displayName") or "")
    return str(obj or "")


def carregar_jogos(root: Path) -> List[Jogo]:
    # A ordem é deliberada: calendário primeiro, snapshot ESPN depois e
    # resultados por último. Assim, um registro finalizado nunca é
    # sobrescrito por uma cópia pré-jogo do mesmo event_id.
    fontes = [
        (root / "jogos.json", "jogos"),
        (root / "espn_eventos.json", "eventos"),
        (root / "resultados.json", "resultados"),
    ]
    por_chave: Dict[str, Jogo] = {}
    for path, key in fontes:
        data = load_json(path, {})
        arr = data.get(key) or []
        for x in arr:
            try:
                rodada = int(x.get("rodada") or 0)
            except Exception:
                rodada = 0
            mand = nome_time(x.get("mandante"))
            vist = nome_time(x.get("visitante"))
            if not rodada or not mand or not vist:
                continue
            event_id = str(x.get("event_id") or x.get("id") or "")
            chave = event_id or f"rodada-{rodada}-{norm(mand)}-{norm(vist)}"
            por_chave[chave] = Jogo(
                chave=chave,
                event_id=event_id,
                rodada=rodada,
                mandante=mand,
                visitante=vist,
                data_iso=str(x.get("data_iso") or ""),
                placar_mandante=x.get("placar_mandante"),
                placar_visitante=x.get("placar_visitante"),
                estado=str(x.get("estado") or ""),
                concluido=bool(x.get("concluido") is True or str(x.get("estado") or "").lower() == "post"),
            )
    return sorted(por_chave.values(), key=lambda j: (j.rodada, j.data_iso, j.mandante, j.visitante))


def aliases_para(clube: str, config: Dict[str, Any]) -> List[str]:
    aliases = [clube]
    aliases += (config.get("aliases_clubes") or {}).get(clube, [])
    # Remove vazios/duplicados preservando ordem.
    out: List[str] = []
    seen = set()
    for a in aliases:
        n = norm(a)
        if n and n not in seen:
            out.append(a)
            seen.add(n)
    return out


def time_no_titulo(titulo_norm: str, clube: str, config: Dict[str, Any]) -> bool:
    return any(contem_termo(titulo_norm, a) for a in aliases_para(clube, config))


def video_tem_melhores_momentos(video: Dict[str, Any]) -> bool:
    titulo = norm(video.get("titulo"))
    # Aceita playlists da GE TV com títulos abreviados, mas evita vídeos de bastidores genéricos.
    bons = ["melhores momentos", "compacto", "gols", "brasileirao", "brasileirão"]
    ruins = ["ao vivo", "podcast", "shorts", "coletiva", "entrevista", "treino", "bastidores"]
    if any(r in titulo for r in ruins):
        return False
    return any(norm(b) in titulo for b in bons) or bool(re.search(r"\b\d+\s*x\s*\d+\b", titulo))


def pontuar_match(jogo: Jogo, video: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, List[str]]:
    titulo = norm(video.get("titulo"))
    rodada_playlist = video.get("rodada_playlist")
    rodada_titulo = rodada_do_texto(video.get("titulo") or "")
    motivos: List[str] = []
    score = 0.0

    if rodada_playlist is not None:
        if rodada_playlist != jogo.rodada:
            return 0.0, ["rodada da playlist diferente"]
        score += 0.32
        motivos.append("rodada da playlist confere")
    elif rodada_titulo == jogo.rodada:
        score += 0.22
        motivos.append("rodada no título confere")

    mand = time_no_titulo(titulo, jogo.mandante, config)
    vist = time_no_titulo(titulo, jogo.visitante, config)
    if mand:
        score += 0.28
        motivos.append("mandante no título")
    if vist:
        score += 0.28
        motivos.append("visitante no título")
    if mand and vist:
        score += 0.10
        motivos.append("dois clubes no título")

    if video_tem_melhores_momentos(video):
        score += 0.06
        motivos.append("título compatível com melhores momentos")

    # Placar no título aumenta confiança se bater com o resultado local.
    placares = re.findall(r"(\d+)\s*x\s*(\d+)", titulo)
    if placares and jogo.placar_mandante is not None and jogo.placar_visitante is not None:
        pm, pv = str(jogo.placar_mandante), str(jogo.placar_visitante)
        if any(a == pm and b == pv for a, b in placares):
            score += 0.08
            motivos.append("placar confere")

    return min(score, 1.0), motivos


def escolher_videos(jogos: List[Jogo], videos: List[Dict[str, Any]], config: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    min_conf = float(config.get("min_confianca_publicar") or 0.86)
    vinculados: Dict[str, Dict[str, Any]] = {}
    duvidosos: List[Dict[str, Any]] = []
    sem_video: List[Dict[str, Any]] = []

    jogos_por_rodada: Dict[int, List[Jogo]] = {}
    for j in jogos:
        jogos_por_rodada.setdefault(j.rodada, []).append(j)

    for jogo in jogos:
        candidatos: List[Tuple[float, Dict[str, Any], List[str]]] = []
        for video in videos:
            # Nunca publica entrevista/bastidores/podcast só porque os dois
            # clubes aparecem no título e a playlist é da rodada correta.
            if not video_tem_melhores_momentos(video):
                continue
            # Se a playlist tem rodada, restringe fortemente.
            rp = video.get("rodada_playlist")
            if rp is not None and rp != jogo.rodada:
                continue
            score, motivos = pontuar_match(jogo, video, config)
            if score > 0:
                candidatos.append((score, video, motivos))
        candidatos.sort(key=lambda t: t[0], reverse=True)
        if not candidatos:
            sem_video.append({"event_id": jogo.event_id, "rodada": jogo.rodada, "mandante": jogo.mandante, "visitante": jogo.visitante})
            continue
        score, video, motivos = candidatos[0]
        registro = {
            "event_id": jogo.event_id,
            "chave": jogo.chave,
            "rodada": jogo.rodada,
            "mandante": jogo.mandante,
            "visitante": jogo.visitante,
            "placar_mandante": jogo.placar_mandante,
            "placar_visitante": jogo.placar_visitante,
            "video_id": video.get("video_id"),
            "titulo": video.get("titulo"),
            "url": video.get("url"),
            "thumbnail": video.get("thumbnail"),
            "playlist_id": video.get("playlist_id"),
            "published_at": video.get("published_at"),
            "fonte": "GE TV / YouTube",
            "confianca": round(score, 3),
            "motivos": motivos,
        }
        if score >= min_conf:
            vinculados[jogo.chave] = registro
        else:
            duvidosos.append(registro)
            sem_video.append({"event_id": jogo.event_id, "rodada": jogo.rodada, "mandante": jogo.mandante, "visitante": jogo.visitante})
    return vinculados, duvidosos, sem_video


def _ultima_rodada_disputada(jogos: List[Jogo]) -> Optional[int]:
    """Retorna a maior rodada com jogo em andamento (in) ou encerrado (post).
    É a "rodada corrente" real — não a última rodada só agendada no calendário.
    Retorna None quando nenhum jogo se enquadrar (início da temporada)."""
    rodadas = [j.rodada for j in jogos if j.estado in ("post", "in") and j.rodada > 0]
    return max(rodadas) if rodadas else None


def rodadas_alvo(args: argparse.Namespace, jogos: List[Jogo], config: Dict[str, Any]) -> Tuple[int, int]:
    if args.rodada_inicio and args.rodada_fim:
        return int(args.rodada_inicio), int(args.rodada_fim)

    ultima_disputada = _ultima_rodada_disputada(jogos)

    if args.modo == "backfill":
        rb = config.get("rodadas_backfill") or {}
        inicio_cfg = args.rodada_inicio or rb.get("inicio") or 1
        # Fim dinâmico: cobre até a rodada atualmente disputada. Se nada foi
        # disputado ainda (raro), usa o valor de config; se este também não
        # existir, cai em 1 para não estourar range.
        fim_cfg = args.rodada_fim or ultima_disputada or rb.get("fim") or 1
        return int(inicio_cfg), int(fim_cfg)

    # incremental: as N rodadas mais recentes que já foram disputadas.
    # Fallback: se nenhuma rodada foi disputada, usa a última do calendário
    # (comportamento antigo) para não zerar a janela.
    if ultima_disputada is None:
        max_rodada = max([j.rodada for j in jogos], default=1)
    else:
        max_rodada = ultima_disputada
    recentes = int((config.get("incremental") or {}).get("rodadas_recentes") or 4)
    return max(1, max_rodada - recentes + 1), max_rodada


def self_test() -> int:
    config = {
        "min_confianca_publicar": 0.86,
        "aliases_clubes": {
            "Atlético-MG": ["Atletico MG", "Galo"],
            "Grêmio": ["Gremio"],
        },
    }
    jogo = Jogo(
        chave="401-test", event_id="401-test", rodada=23,
        mandante="Atlético-MG", visitante="Grêmio",
        placar_mandante=1, placar_visitante=0, estado="post", concluido=True,
    )
    assert rodada_do_texto("Brasileirão | 23ª rodada") == 23
    assert rodada_do_texto("R23 - melhores momentos") == 23

    bom = {
        "video_id": "ok",
        "titulo": "Atlético-MG 1 x 0 Grêmio | melhores momentos | Brasileirão | 23ª rodada",
        "url": "https://www.youtube.com/watch?v=ok",
        "thumbnail": "https://i.ytimg.com/vi/ok/hqdefault.jpg",
        "playlist_id": "PL-R23",
        "rodada_playlist": 23,
        "published_at": "2026-08-16T21:00:00Z",
    }
    score, motivos = pontuar_match(jogo, bom, config)
    assert score >= 0.86, (score, motivos)
    assert "mandante no título" in motivos and "visitante no título" in motivos
    assert "placar confere" in motivos

    rodada_errada = dict(bom, video_id="wrong-round", rodada_playlist=22)
    score_errado, _ = pontuar_match(jogo, rodada_errada, config)
    assert score_errado == 0.0

    bastidores = dict(bom, video_id="backstage", titulo="Bastidores Atlético-MG x Grêmio", rodada_playlist=23)
    assert video_tem_melhores_momentos(bastidores) is False

    um_time = dict(bom, video_id="one-team", titulo="Atlético-MG | melhores momentos | Brasileirão", rodada_playlist=23)
    score_um, _ = pontuar_match(jogo, um_time, config)
    assert score_um < 0.86

    vinculados, duvidosos, sem_video = escolher_videos([jogo], [rodada_errada, um_time, bom], config)
    assert list(vinculados) == [jogo.chave]
    assert vinculados[jogo.chave]["video_id"] == "ok"
    assert not duvidosos and not sem_video

    vinculados2, _, sem_video2 = escolher_videos([jogo], [rodada_errada, bastidores], config)
    assert not vinculados2 and len(sem_video2) == 1

    # A janela incremental acompanha a última rodada realmente disputada, não
    # a maior rodada apenas agendada no calendário.
    agendado = Jogo("future", "future", 38, "Bahia", "Vitória", estado="pre", concluido=False)
    args = argparse.Namespace(rodada_inicio=None, rodada_fim=None, modo="incremental")
    ini, fim = rodadas_alvo(args, [jogo, agendado], {"incremental": {"rodadas_recentes": 4}})
    assert (ini, fim) == (20, 23)

    print("SELFTEST OK: rodada, clubes, placar, rejeição de falsos positivos e janela incremental de melhores momentos")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca melhores momentos da GE TV no YouTube e vincula aos jogos do Brasileirão.")
    ap.add_argument("--root", default=".", help="raiz do repositório")
    ap.add_argument("--modo", choices=["backfill", "incremental"], default="incremental")
    ap.add_argument("--rodada-inicio", type=int, default=None)
    ap.add_argument("--rodada-fim", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="valida estrutura sem chamar YouTube API")
    ap.add_argument("--self-test", action="store_true", help="executa testes offline e termina")
    ap.add_argument("--sleep", type=float, default=0.05)
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    config_path = root / "dados-br" / "getv-config.json"
    config = load_json(config_path, {})
    jogos_all = carregar_jogos(root)
    resultados_publicados = load_json(root / "resultados.json", {"resultados": []}).get("resultados") or []
    ids_resultados = {
        str(j.get("event_id") or j.get("id") or "").strip()
        for j in resultados_publicados
        if str(j.get("event_id") or j.get("id") or "").strip()
    }
    chaves_resultados = {
        f"rodada-{int(j.get('rodada') or 0)}-{norm(nome_time(j.get('mandante'))).replace(' ', '-')}-{norm(nome_time(j.get('visitante'))).replace(' ', '-')}"
        for j in resultados_publicados
        if int(j.get("rodada") or 0) > 0 and nome_time(j.get("mandante")) and nome_time(j.get("visitante"))
    }

    def consta_em_resultados(jogo: Jogo) -> bool:
        if jogo.event_id and jogo.event_id in ids_resultados:
            return True
        chave = f"rodada-{jogo.rodada}-{norm(jogo.mandante).replace(' ', '-')}-{norm(jogo.visitante).replace(' ', '-')}"
        return chave in chaves_resultados

    jogos_publicados = [j for j in jogos_all if consta_em_resultados(j)]
    ri, rf = rodadas_alvo(args, jogos_all, config)
    jogos = [j for j in jogos_publicados if ri <= j.rodada <= rf]
    if not jogos:
        raise SystemExit(f"Nenhum jogo publicado em resultados.json encontrado para rodadas {ri}-{rf}.")

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if args.dry_run:
        print(f"DRY RUN OK: {len(jogos)} jogos nas rodadas {ri}-{rf}; config em {config_path}.")
        return 0
    if not api_key:
        raise SystemExit("Secret/variável YOUTUBE_API_KEY não encontrada. Crie o secret no GitHub antes de rodar o workflow.")

    client = YouTubeClient(api_key, sleep=args.sleep)
    channel_id = resolver_channel_id(client, config)
    playlists_raw = listar_playlists_canal(client, channel_id)
    playlists = [playlist_publica(pl) for pl in playlists_raw if playlist_eh_brasileirao(pl, config)]

    # Garante playlist semente mesmo se o filtro do canal não a encontrar/paginar.
    ids = {p.get("playlist_id") for p in playlists}
    for seed in config.get("playlists_semente", []):
        pid = playlist_id_from_url_or_id(seed)
        if pid and pid not in ids:
            data = client.get("playlists", part="snippet,contentDetails", id=pid, maxResults=1)
            for pl in data.get("items") or []:
                pub = playlist_publica(pl)
                playlists.append(pub)
                ids.add(pub.get("playlist_id"))

    playlists = [p for p in playlists if p.get("rodada") is not None and ri <= int(p["rodada"]) <= rf]
    playlists.sort(key=lambda p: (p.get("rodada") or 999, p.get("titulo") or ""))

    if args.modo == "incremental":
        max_pl = int((config.get("incremental") or {}).get("max_playlists_por_execucao") or 10)
        # Prioriza as rodadas mais recentes.
        playlists = sorted(playlists, key=lambda p: p.get("rodada") or 0, reverse=True)[:max_pl]
        playlists = sorted(playlists, key=lambda p: p.get("rodada") or 0)

    videos: List[Dict[str, Any]] = []
    for pl in playlists:
        pid = pl.get("playlist_id")
        rodada = pl.get("rodada")
        if not pid:
            continue
        for item in listar_videos_playlist(client, pid):
            v = video_publico(item, pid, rodada)
            if v.get("video_id"):
                videos.append(v)

    vinculados, duvidosos, sem_video = escolher_videos(jogos, videos, config)
    prev = load_json(root / "dados-br" / "melhores-momentos.json", {"jogos": {}})
    prev_playlists = load_json(root / "dados-br" / "getv-playlists.json", {"playlists": []})

    # Saneia vínculos antigos: melhores momentos só podem existir para jogos
    # efetivamente encerrados. Isso remove automaticamente qualquer vídeo
    # associado a partida futura, adiada ou ainda em andamento.
    finais_all = jogos_publicados
    ids_finais = {j.event_id for j in finais_all if j.event_id}
    chaves_finais = {j.chave for j in finais_all if j.chave}
    merged_jogos = {}
    for key, registro in dict(prev.get("jogos") or {}).items():
        event_id = str((registro or {}).get("event_id") or "")
        chave = str((registro or {}).get("chave") or key or "")
        if (event_id and event_id in ids_finais) or chave in chaves_finais:
            merged_jogos[str(key)] = registro
    merged_jogos.update(vinculados)

    saida = {
        "atualizado_em": agora_iso(),
        "fonte": "GE TV / YouTube",
        "modo_ultima_execucao": args.modo,
        "rodadas_processadas": {"inicio": ri, "fim": rf},
        "total_vinculados": len(merged_jogos),
        "jogos": dict(sorted(merged_jogos.items(), key=lambda kv: (kv[1].get("rodada") or 999, kv[1].get("mandante") or ""))),
    }
    playlists_json = {
        "atualizado_em": agora_iso(),
        "fonte": "GE TV / YouTube",
        "channel_id": channel_id,
        "total_playlists": len(playlists),
        "playlists": playlists,
    }
    auditoria = {
        "atualizado_em": agora_iso(),
        "fonte": "GE TV / YouTube",
        "modo": args.modo,
        "rodadas_processadas": {"inicio": ri, "fim": rf},
        "youtube_requests": client.requests,
        "resumo": {
            "playlists_encontradas": len(playlists),
            "videos_lidos": len(videos),
            "jogos_processados": len(jogos),
            "jogos_vinculados_nesta_execucao": len(vinculados),
            "jogos_vinculados_total": len(merged_jogos),
            "candidatos_duvidosos": len(duvidosos),
            "jogos_sem_video": len(sem_video),
        },
        "playlists": playlists,
        "candidatos_duvidosos": duvidosos[:200],
        "jogos_sem_video": sem_video[:300],
    }

    # Evita commits inúteis a cada 30 minutos: só reescreve os JSONs quando
    # aparecer vínculo novo/alterado ou mudança real na lista de playlists.
    prev_jogos = prev.get("jogos") or {}
    prev_pl_sem_data = [{k: v for k, v in p.items() if k != "published_at"} for p in (prev_playlists.get("playlists") or [])]
    new_pl_sem_data = [{k: v for k, v in p.items() if k != "published_at"} for p in playlists]
    houve_mudanca = (prev_jogos != merged_jogos) or (prev_pl_sem_data != new_pl_sem_data)

    if houve_mudanca or not (root / "dados-br" / "auditoria-melhores-momentos.json").exists():
        save_json(root / "dados-br" / "melhores-momentos.json", saida)
        save_json(root / "dados-br" / "getv-playlists.json", playlists_json)
        save_json(root / "dados-br" / "auditoria-melhores-momentos.json", auditoria)
    else:
        print("Sem vídeos/playlists novos. JSONs preservados para evitar commit vazio.")

    print("Busca GE TV concluída")
    print(f"Modo: {args.modo} | Rodadas: {ri}-{rf}")
    print(f"Playlists: {len(playlists)} | vídeos: {len(videos)} | vinculados nesta execução: {len(vinculados)} | total: {len(merged_jogos)}")
    print(f"Duvidosos: {len(duvidosos)} | sem vídeo: {len(sem_video)} | YouTube requests: {client.requests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

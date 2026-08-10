#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atualizar_publicos_brasileirao.py

Complementa automaticamente o público presente dos jogos finalizados do
Brasileirão quando a ESPN não informa o campo.

Fonte documental automática principal: artigos por rodada do ge/Gato Mestre.
A descoberta usa primeiro o sitemap diário do ge, portanto NÃO depende de adivinhar
o slug/título da matéria; a URL histórica previsível fica apenas como fallback.
A rotina é conservadora:
  * usa somente "Público presente"/"Público total"; nunca transforma pagantes
    em público presente;
  * não sobrescreve um complemento existente com valor diferente;
  * preserva o último JSON válido quando a fonte externa oscila;
  * propaga o mesmo valor para IDs duplicados que representam a mesma partida;
  * gera auditoria dos jogos ainda sem público e de eventuais conflitos.

Saídas:
  - dados-br/publicos-complementares.json
  - dados-br/auditoria-publicos.json
  - dados-br/jogos-detalhes.json (somente campos de público já existentes no índice)
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
RESULTADOS = ROOT / "resultados.json"
DETALHES = ROOT / "dados-br" / "jogos-detalhes.json"
SAIDA = ROOT / "dados-br" / "publicos-complementares.json"
AUDITORIA = ROOT / "dados-br" / "auditoria-publicos.json"
FUSO_BRASILIA = timezone(timedelta(hours=-3))
GE_SITEMAP_TEMPLATE = "https://ge.globo.com/sitemap/ge/{ano:04d}/{mes:02d}/{dia:02d}_{parte}.xml"
GE_TEMPLATE = (
    "https://ge.globo.com/gato-mestre/noticia/{ano:04d}/{mes:02d}/{dia:02d}/"
    "veja-os-publicos-da-{rodada}a-rodada-do-campeonato-brasileiro.ghtml"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def agora_brt() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def iso_agora_brt() -> str:
    return agora_brt().isoformat()


def carregar_json(path: Path, padrao: Any) -> Any:
    if not path.exists():
        return padrao
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def salvar_json_atomico(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalizar(valor: Any) -> str:
    s = unicodedata.normalize("NFD", str(valor or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.lower().replace("&", " e ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


ALIASES = {
    "atletico mg": "atletico mg",
    "atletico mineiro": "atletico mg",
    "clube atletico mineiro": "atletico mg",
    "athletico pr": "athletico pr",
    "athletico paranaense": "athletico pr",
    "club athletico paranaense": "athletico pr",
    "bragantino": "bragantino",
    "rb bragantino": "bragantino",
    "red bull bragantino": "bragantino",
    "vasco": "vasco da gama",
    "vasco da gama": "vasco da gama",
    "cr vasco da gama": "vasco da gama",
    "remo": "remo",
    "clube do remo": "remo",
}


def time_canonico(valor: Any) -> str:
    n = normalizar(valor)
    return ALIASES.get(n, n)


def numero_publico(valor: Any) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        n = int(round(float(valor)))
        return n if 100 <= n <= 250000 else None
    raw = str(valor or "").strip()
    if not raw or "nao divulgado" in normalizar(raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    return n if 100 <= n <= 250000 else None


def jogo_finalizado(jogo: dict[str, Any]) -> bool:
    return str(jogo.get("estado") or "").lower() == "post" and jogo.get("placar_mandante") is not None and jogo.get("placar_visitante") is not None


def data_jogo(jogo: dict[str, Any]) -> date | None:
    raw = str(jogo.get("data_iso") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def assinatura_jogo(jogo: dict[str, Any]) -> tuple[str, str, str, int, int] | None:
    d = data_jogo(jogo)
    if d is None:
        return None
    try:
        placar_casa = int(jogo.get("placar_mandante"))
        placar_fora = int(jogo.get("placar_visitante"))
    except (TypeError, ValueError):
        return None
    casa = time_canonico((jogo.get("mandante") or {}).get("nome"))
    fora = time_canonico((jogo.get("visitante") or {}).get("nome"))
    if not casa or not fora:
        return None
    return d.isoformat(), casa, fora, placar_casa, placar_fora


def _strings_de_json(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings_de_json(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings_de_json(value)


def html_para_linhas(conteudo: str) -> list[str]:
    """Extrai texto do HTML e também de blocos JSON embutidos do artigo."""
    textos: list[str] = []

    # Estratégia 1: texto visível em headings/parágrafos/listas.
    visivel = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", "\n", conteudo)
    visivel = re.sub(r"(?i)<br\s*/?>", "\n", visivel)
    visivel = re.sub(r"(?i)</?(?:p|h[1-6]|li|div|section|article|tr|td|th)\b[^>]*>", "\n", visivel)
    visivel = re.sub(r"(?s)<[^>]+>", " ", visivel)
    textos.append(html_lib.unescape(visivel))

    # Estratégia 2: Globo costuma replicar conteúdo em JSON/JSON-LD.
    for match in re.finditer(r"(?is)<script\b[^>]*>(.*?)</script>", conteudo):
        bruto = html_lib.unescape(match.group(1).strip())
        if not bruto:
            continue
        candidatos = [bruto]
        if bruto.startswith("<!--") and bruto.endswith("-->"):
            candidatos.append(bruto[4:-3].strip())
        for candidato in candidatos:
            try:
                objeto = json.loads(candidato)
            except Exception:
                continue
            textos.extend(_strings_de_json(objeto))
            break

    linhas: list[str] = []
    vistos: set[str] = set()
    for texto in textos:
        texto = texto.replace("\\u00d7", "×").replace("\\u00ba", "º")
        # Strings extraídas de JSON/JS podem conter quebras ainda escapadas.
        texto = texto.replace("\\r\\n", "\n").replace("\\n", "\n")
        texto = texto.replace("\r", "\n")
        for linha in texto.split("\n"):
            linha = re.sub(r"\s+", " ", html_lib.unescape(linha)).strip(" \t-•")
            if not linha:
                continue
            chave = linha.casefold()
            if chave in vistos:
                continue
            vistos.add(chave)
            linhas.append(linha)
    return linhas


RE_JOGO = re.compile(
    r"^(?P<casa>.+?)\s+(?P<gc>\d{1,2})\s*[x×]\s*(?P<gf>\d{1,2})\s+(?P<fora>.+?)(?:\s*\([^)]*\))?$",
    flags=re.IGNORECASE,
)
RE_PUBLICO_PRESENTE = re.compile(r"^P[uú]blico\s+(?:presente|total)\s*:\s*(.+)$", flags=re.IGNORECASE)


def parse_artigo_ge(conteudo: str) -> list[dict[str, Any]]:
    linhas = html_para_linhas(conteudo)
    jogos: list[dict[str, Any]] = []
    for i, linha in enumerate(linhas):
        m = RE_JOGO.match(linha)
        if not m:
            continue
        # Evita confundir títulos/frases longas com uma ficha de jogo.
        casa = re.sub(r"\s+", " ", m.group("casa")).strip()
        fora = re.sub(r"\s+", " ", m.group("fora")).strip()
        if len(casa) > 45 or len(fora) > 45:
            continue
        publico: int | None = None
        tipo = ""
        for prox in linhas[i + 1 : i + 12]:
            # Ao encontrar outra partida, encerra o bloco atual.
            if RE_JOGO.match(prox):
                break
            pm = RE_PUBLICO_PRESENTE.match(prox)
            if pm:
                publico = numero_publico(pm.group(1))
                tipo = "presente" if publico is not None else "nao_divulgado"
                break
        jogos.append({
            "mandante": casa,
            "visitante": fora,
            "placar_mandante": int(m.group("gc")),
            "placar_visitante": int(m.group("gf")),
            "publico": publico,
            "tipo": tipo,
        })
    # Remove repetições causadas por conteúdo duplicado no HTML/JSON.
    unicos: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for item in jogos:
        chave = (
            time_canonico(item["mandante"]),
            time_canonico(item["visitante"]),
            int(item["placar_mandante"]),
            int(item["placar_visitante"]),
        )
        anterior = unicos.get(chave)
        if anterior is None or (anterior.get("publico") is None and item.get("publico") is not None):
            unicos[chave] = item
    return list(unicos.values())


def buscar_html(url: str, timeout: int = 22, tentativas: int = 2) -> str:
    erros: list[str] = []
    try:
        from curl_cffi import requests as curl_requests  # type: ignore
    except Exception:
        curl_requests = None

    for tentativa in range(1, max(1, tentativas) + 1):
        if curl_requests is not None:
            try:
                resp = curl_requests.get(url, headers=HEADERS, timeout=timeout, impersonate="chrome", allow_redirects=True)
                if int(resp.status_code) == 404:
                    raise FileNotFoundError("HTTP 404")
                resp.raise_for_status()
                texto = str(resp.text or "")
                if len(texto) < 500:
                    raise RuntimeError(f"HTML muito curto ({len(texto)} bytes)")
                return texto
            except FileNotFoundError:
                raise
            except Exception as exc:
                erros.append(f"curl-cffi tentativa {tentativa}: {exc}")

        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = int(getattr(resp, "status", 200) or 200)
                if status == 404:
                    raise FileNotFoundError("HTTP 404")
                bruto = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                texto = bruto.decode(charset, errors="replace")
                if len(texto) < 500:
                    raise RuntimeError(f"HTML muito curto ({len(texto)} bytes)")
                return texto
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError("HTTP 404") from exc
            erros.append(f"urllib tentativa {tentativa}: HTTP {exc.code}")
        except Exception as exc:
            erros.append(f"urllib tentativa {tentativa}: {exc}")

        if tentativa < tentativas:
            time.sleep(min(1.5, 0.35 * tentativa))
    raise RuntimeError("; ".join(erros[-4:]) or "falha desconhecida ao buscar HTML")


def url_ge(rodada: int, d: date) -> str:
    return GE_TEMPLATE.format(ano=d.year, mes=d.month, dia=d.day, rodada=int(rodada))


def variantes_url_ge(url: str) -> list[str]:
    """Retorna URL canônica + AMP do ge para contornar diferenças de cache/publicação."""
    raw = str(url or "").strip()
    if not raw or "ge.globo.com/" not in raw:
        return [raw] if raw else []
    if "ge.globo.com/google/amp/" in raw:
        normal = raw.replace("ge.globo.com/google/amp/", "ge.globo.com/", 1)
        return list(dict.fromkeys([normal, raw]))
    amp = raw.replace("ge.globo.com/", "ge.globo.com/google/amp/", 1)
    return list(dict.fromkeys([raw, amp]))



def extrair_urls_sitemap(conteudo: str) -> list[str]:
    """Extrai <loc> de sitemap XML tolerando namespace e XML parcialmente escapado."""
    raw = str(conteudo or "").strip()
    if not raw:
        return []
    urls: list[str] = []
    try:
        root = ET.fromstring(raw)
        for node in root.iter():
            if str(node.tag).split("}")[-1].lower() != "loc":
                continue
            url = html_lib.unescape(str(node.text or "").strip())
            if url.startswith("https://"):
                urls.append(url)
    except ET.ParseError:
        for match in re.finditer(r"(?is)<loc>\s*(.*?)\s*</loc>", raw):
            url = html_lib.unescape(re.sub(r"\s+", "", match.group(1)))
            if url.startswith("https://"):
                urls.append(url)
    return list(dict.fromkeys(urls))


def pontuar_url_publico_ge(url: str, rodada: int) -> int:
    texto = normalizar(urllib.parse.unquote(str(url or "")))
    score = 0
    if "ge globo com gato mestre noticia" in texto:
        score += 8
    if "publico" in texto or "publicos" in texto:
        score += 10
    if "brasileirao" in texto or "campeonato brasileiro" in texto:
        score += 5
    if f"{int(rodada)}a rodada" in texto or f"{int(rodada)} rodada" in texto:
        score += 12
    if "veja a lista" in texto or "veja os publicos" in texto:
        score += 3
    return score


def descobrir_urls_ge_por_sitemap(
    rodada: int,
    datas: list[date],
    *,
    max_datas: int = 8,
    max_partes: int = 2,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Descobre matérias candidatas sem depender do slug editorial do ge."""
    candidatos: dict[str, int] = {}
    auditoria: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []
    datas_unicas = list(dict.fromkeys(datas))[: max(1, int(max_datas))]
    for d in datas_unicas:
        for parte in range(1, max(1, int(max_partes)) + 1):
            sitemap = GE_SITEMAP_TEMPLATE.format(ano=d.year, mes=d.month, dia=d.day, parte=parte)
            try:
                conteudo = buscar_html(sitemap, timeout=18, tentativas=1)
            except FileNotFoundError:
                # _2.xml, por exemplo, normalmente nem existe; isso não é erro operacional.
                continue
            except Exception as exc:
                erros.append({"rodada": rodada, "url": sitemap, "erro": str(exc)[:500], "tipo": "sitemap"})
                continue
            urls = extrair_urls_sitemap(conteudo)
            aceitas = 0
            for url in urls:
                score = pontuar_url_publico_ge(url, rodada)
                if score < 18:
                    continue
                candidatos[url] = max(candidatos.get(url, 0), score)
                aceitas += 1
            auditoria.append({"rodada": rodada, "url": sitemap, "urls": len(urls), "candidatas": aceitas, "tipo": "sitemap"})
    ordenadas = [url for url, _ in sorted(candidatos.items(), key=lambda item: (-item[1], item[0]))]
    return ordenadas[:20], auditoria, erros


def _chave_item_artigo(item: dict[str, Any]) -> tuple[str, str, int, int] | None:
    try:
        gc = int(item.get("placar_mandante"))
        gf = int(item.get("placar_visitante"))
    except (TypeError, ValueError):
        return None
    casa = time_canonico(item.get("mandante"))
    fora = time_canonico(item.get("visitante"))
    if not casa or not fora:
        return None
    return casa, fora, gc, gf


def mesclar_itens_artigos(fontes_parseadas: list[tuple[str, list[dict[str, Any]]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mescla HTML normal/AMP, preferindo versão que efetivamente publicou o público.

    Se duas variantes trouxerem números diferentes para a mesma partida, o valor é
    bloqueado e o conflito vai para a auditoria; não escolhemos um número no escuro.
    """
    merged: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    conflitos: list[dict[str, Any]] = []
    bloqueadas: set[tuple[str, str, int, int]] = set()
    for fonte_url, itens in fontes_parseadas:
        for bruto in itens:
            chave = _chave_item_artigo(bruto)
            if chave is None or chave in bloqueadas:
                continue
            item = dict(bruto)
            item["_fonte_url"] = fonte_url
            anterior = merged.get(chave)
            if anterior is None:
                merged[chave] = item
                continue
            velho = numero_publico(anterior.get("publico"))
            novo = numero_publico(item.get("publico"))
            if velho is None and novo is not None:
                merged[chave] = item
            elif velho is not None and novo is not None and velho != novo:
                conflitos.append({
                    "tipo": "divergencia_variantes_ge",
                    "partida": list(chave),
                    "valor_1": velho,
                    "fonte_1": anterior.get("_fonte_url"),
                    "valor_2": novo,
                    "fonte_2": fonte_url,
                })
                merged.pop(chave, None)
                bloqueadas.add(chave)
    return list(merged.values()), conflitos


def datas_candidatas(jogos_rodada: list[dict[str, Any]]) -> list[date]:
    datas = sorted({d for jogo in jogos_rodada if (d := data_jogo(jogo)) is not None})
    candidatos: list[date] = []
    # A matéria costuma sair no dia do último jogo da rodada. Incluímos pequena
    # margem para publicação/atualização no dia seguinte e jogos remarcados.
    for d in reversed(datas):
        for offset in (0, 1, 2):
            x = d + timedelta(days=offset)
            if x not in candidatos:
                candidatos.append(x)
    return candidatos[:24]


def _match_artigo_resultado(item: dict[str, Any], jogo: dict[str, Any]) -> bool:
    try:
        if int(item.get("placar_mandante")) != int(jogo.get("placar_mandante")):
            return False
        if int(item.get("placar_visitante")) != int(jogo.get("placar_visitante")):
            return False
    except (TypeError, ValueError):
        return False
    return (
        time_canonico(item.get("mandante")) == time_canonico((jogo.get("mandante") or {}).get("nome"))
        and time_canonico(item.get("visitante")) == time_canonico((jogo.get("visitante") or {}).get("nome"))
    )


def complemento_valido(item: Any) -> int | None:
    if not isinstance(item, dict):
        return None
    return numero_publico(item.get("publico"))


def _fonte_rodada_existente(payload: dict[str, Any], rodada: int) -> str:
    fontes = payload.get("fontes_rodadas") or {}
    if isinstance(fontes, dict):
        item = fontes.get(str(rodada))
        if isinstance(item, dict) and item.get("url"):
            return str(item.get("url"))
        if isinstance(item, str):
            return item
    jogos = payload.get("jogos") or {}
    if isinstance(jogos, dict):
        for item in jogos.values():
            if not isinstance(item, dict):
                continue
            fonte = str(item.get("fonte") or "")
            if f"publicos-da-{rodada}a-rodada" in fonte:
                return fonte
    return ""


def _registrar_complemento(
    mapa: dict[str, dict[str, Any]],
    event_id: str,
    publico: int,
    fonte: str,
    *,
    tipo: str = "presente",
    origem: str = "ge/Gato Mestre",
) -> tuple[bool, dict[str, Any] | None]:
    atual = mapa.get(event_id)
    valor_atual = complemento_valido(atual)
    if valor_atual is not None:
        if valor_atual == publico:
            return False, None
        return False, {
            "event_id": event_id,
            "existente": valor_atual,
            "novo": publico,
            "fonte_existente": str((atual or {}).get("fonte") or ""),
            "fonte_nova": fonte,
        }
    mapa[event_id] = {
        "publico": int(publico),
        "tipo": tipo,
        "fonte": fonte,
        "origem": origem,
    }
    return True, None


def propagar_duplicados(
    resultados: list[dict[str, Any]],
    mapa: dict[str, dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    por_assinatura: dict[tuple[str, str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    por_id = {str(j.get("event_id") or ""): j for j in resultados}
    for jogo in resultados:
        sig = assinatura_jogo(jogo)
        if sig:
            por_assinatura[sig].append(jogo)

    alteracoes = 0
    conflitos: list[dict[str, Any]] = []
    for sig, jogos in por_assinatura.items():
        if len(jogos) < 2:
            continue
        conhecidos: list[tuple[int, str, str, str]] = []
        for jogo in jogos:
            eid = str(jogo.get("event_id") or "")
            item = mapa.get(eid)
            valor = complemento_valido(item)
            if valor is not None:
                conhecidos.append((valor, str((item or {}).get("fonte") or ""), str((item or {}).get("tipo") or "presente"), str((item or {}).get("origem") or "complemento documental")))
        if not conhecidos:
            continue
        valores = {x[0] for x in conhecidos}
        if len(valores) > 1:
            conflitos.append({"assinatura": list(sig), "event_ids": [str(j.get("event_id") or "") for j in jogos], "valores": sorted(valores)})
            continue
        publico, fonte, tipo, origem = conhecidos[0]
        for jogo in jogos:
            eid = str(jogo.get("event_id") or "")
            mudou, conflito = _registrar_complemento(mapa, eid, publico, fonte, tipo=tipo, origem=origem)
            alteracoes += int(mudou)
            if conflito:
                conflitos.append(conflito)
    return alteracoes, conflitos


def executar_coleta(
    resultados: list[dict[str, Any]],
    detalhes: dict[str, Any],
    payload: dict[str, Any],
    *,
    sem_rede: bool = False,
    max_rodadas: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    jogos_mapa = payload.get("jogos") if isinstance(payload.get("jogos"), dict) else {}
    mapa: dict[str, dict[str, Any]] = {str(k): dict(v) for k, v in jogos_mapa.items() if isinstance(v, dict)}
    fontes_rodadas = payload.get("fontes_rodadas") if isinstance(payload.get("fontes_rodadas"), dict) else {}
    fontes_rodadas = {str(k): v for k, v in fontes_rodadas.items()}

    detalhes_jogos = detalhes.get("jogos") if isinstance(detalhes, dict) else {}
    if not isinstance(detalhes_jogos, dict):
        detalhes_jogos = {}

    finalizados = [j for j in resultados if jogo_finalizado(j) and j.get("event_id")]

    def tem_publico(jogo: dict[str, Any]) -> bool:
        eid = str(jogo.get("event_id") or "")
        return numero_publico((detalhes_jogos.get(eid) or {}).get("publico")) is not None or complemento_valido(mapa.get(eid)) is not None

    pendentes = [j for j in finalizados if not tem_publico(j)]
    rodadas_pendentes = sorted({int(j.get("rodada") or 0) for j in pendentes if int(j.get("rodada") or 0) > 0}, reverse=True)
    if max_rodadas > 0:
        rodadas_pendentes = rodadas_pendentes[:max_rodadas]

    inseridos = 0
    conflitos: list[dict[str, Any]] = []
    erros_fontes: list[dict[str, Any]] = []
    fontes_consultadas: list[dict[str, Any]] = []

    if not sem_rede:
        por_rodada: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for jogo in finalizados:
            r = int(jogo.get("rodada") or 0)
            if r > 0:
                por_rodada[r].append(jogo)

        for rodada in rodadas_pendentes:
            jogos_rodada = por_rodada.get(rodada, [])
            fonte_existente = _fonte_rodada_existente(payload, rodada)
            datas = datas_candidatas(jogos_rodada)
            descobertas, audit_sitemap, erros_sitemap = descobrir_urls_ge_por_sitemap(rodada, datas)
            fontes_consultadas.extend(audit_sitemap)
            erros_fontes.extend(erros_sitemap)

            urls_base: list[str] = []
            if fonte_existente:
                urls_base.append(fonte_existente)
            # Primeiro URLs realmente publicadas no sitemap; só depois mantemos o
            # padrão histórico como fallback. Assim títulos novos não quebram a coleta.
            urls_base.extend(descobertas)
            urls_base.extend(url_ge(rodada, d) for d in datas)
            # Dedup preservando ordem. Cada URL de artigo do ge é consultada também
            # em AMP para contornar defasagem de cache entre representações.
            urls_base = list(dict.fromkeys(urls_base))
            artigo_itens: list[dict[str, Any]] = []
            url_encontrada = ""
            for url_base in urls_base:
                fontes_parseadas: list[tuple[str, list[dict[str, Any]]]] = []
                for url in variantes_url_ge(url_base):
                    try:
                        conteudo = buscar_html(url)
                    except FileNotFoundError:
                        continue
                    except Exception as exc:
                        erros_fontes.append({"rodada": rodada, "url": url, "erro": str(exc)[:500]})
                        continue
                    parsed = parse_artigo_ge(conteudo)
                    fontes_consultadas.append({"rodada": rodada, "url": url, "itens": len(parsed)})
                    if parsed:
                        fontes_parseadas.append((url, parsed))
                if fontes_parseadas:
                    artigo_itens, conflitos_variantes = mesclar_itens_artigos(fontes_parseadas)
                    conflitos.extend(conflitos_variantes)
                    if artigo_itens:
                        url_encontrada = url_base
                        break
            if not artigo_itens:
                continue

            fonte_atual = fontes_rodadas.get(str(rodada))
            if not isinstance(fonte_atual, dict) or fonte_atual.get("url") != url_encontrada:
                fontes_rodadas[str(rodada)] = {
                    "url": url_encontrada,
                    "fonte": "ge/Gato Mestre",
                }
            for jogo in jogos_rodada:
                eid = str(jogo.get("event_id") or "")
                if complemento_valido(mapa.get(eid)) is not None:
                    continue
                item = next((x for x in artigo_itens if _match_artigo_resultado(x, jogo)), None)
                if not item:
                    continue
                publico = numero_publico(item.get("publico"))
                if publico is None:
                    continue
                fonte_item = str(item.get("_fonte_url") or url_encontrada)
                mudou, conflito = _registrar_complemento(mapa, eid, publico, fonte_item)
                inseridos += int(mudou)
                if conflito:
                    conflitos.append(conflito)

    propagados, conflitos_dup = propagar_duplicados(finalizados, mapa)
    inseridos += propagados
    conflitos.extend(conflitos_dup)

    comentario = (
        "Complemento de público presente para jogos em que a ESPN não trouxe o campo. "
        "Coleta automática prioritária no ge/Gato Mestre; fontes documentais avulsas "
        "podem ser mantidas para jogos remarcados ou ainda ausentes na matéria da rodada."
    )
    houve_mudanca_payload = (
        payload.get("_comentario") != comentario
        or payload.get("fontes_rodadas") != fontes_rodadas
        or payload.get("jogos") != mapa
    )
    saida = dict(payload)
    saida.update({
        "_comentario": comentario,
        "atualizado_em": iso_agora_brt() if houve_mudanca_payload else payload.get("atualizado_em"),
        "fontes_rodadas": fontes_rodadas,
        "jogos": mapa,
    })

    # Cobertura final considerando detalhe ESPN + complemento documental.
    sem_publico: list[dict[str, Any]] = []
    fontes = Counter()
    for jogo in finalizados:
        eid = str(jogo.get("event_id") or "")
        d = detalhes_jogos.get(eid) or {}
        publico_detalhe = numero_publico(d.get("publico"))
        comp = mapa.get(eid) or {}
        publico_comp = complemento_valido(comp)
        if publico_detalhe is not None:
            fonte = str(d.get("publico_fonte") or "ESPN")
            fontes[fonte] += 1
        elif publico_comp is not None:
            fonte = str(comp.get("origem") or comp.get("fonte") or "complemento documental")
            fontes[fonte] += 1
        else:
            sem_publico.append({
                "event_id": eid,
                "rodada": int(jogo.get("rodada") or 0),
                "data_iso": str(jogo.get("data_iso") or ""),
                "mandante": str((jogo.get("mandante") or {}).get("nome") or ""),
                "visitante": str((jogo.get("visitante") or {}).get("nome") or ""),
                "placar": f"{jogo.get('placar_mandante')} x {jogo.get('placar_visitante')}",
            })

    # Há casos em que a ESPN troca o event_id de um jogo remarcado. O repositório
    # preserva os dois registros para rastreabilidade, mas a cobertura editorial
    # também precisa informar o número de partidas físicas únicas.
    grupos_fisicos: dict[tuple[str, str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for jogo in finalizados:
        sig = assinatura_jogo(jogo)
        if sig:
            grupos_fisicos[sig].append(jogo)
    partidas_fisicas_sem_publico: list[dict[str, Any]] = []
    for sig, grupo in grupos_fisicos.items():
        tem = False
        for jogo in grupo:
            eid = str(jogo.get("event_id") or "")
            d = detalhes_jogos.get(eid) or {}
            if numero_publico(d.get("publico")) is not None or complemento_valido(mapa.get(eid)) is not None:
                tem = True
                break
        if not tem:
            jogo = grupo[0]
            partidas_fisicas_sem_publico.append({
                "event_ids": [str(x.get("event_id") or "") for x in grupo],
                "rodada": int(jogo.get("rodada") or 0),
                "data_iso": str(jogo.get("data_iso") or ""),
                "mandante": str((jogo.get("mandante") or {}).get("nome") or ""),
                "visitante": str((jogo.get("visitante") or {}).get("nome") or ""),
                "placar": f"{jogo.get('placar_mandante')} x {jogo.get('placar_visitante')}",
            })

    audit = {
        "gerado_em": iso_agora_brt(),
        "fonte_automatica": "ge/Gato Mestre (público presente/total; nunca pagantes como substituto)",
        "total_jogos_finalizados": len(finalizados),
        "total_com_publico_ou_complemento": len(finalizados) - len(sem_publico),
        "total_sem_publico": len(sem_publico),
        "sem_publico": sem_publico,
        "total_partidas_fisicas": len(grupos_fisicos),
        "total_partidas_fisicas_com_publico": len(grupos_fisicos) - len(partidas_fisicas_sem_publico),
        "total_partidas_fisicas_sem_publico": len(partidas_fisicas_sem_publico),
        "partidas_fisicas_sem_publico": partidas_fisicas_sem_publico,
        "rodadas_pendentes_no_inicio": rodadas_pendentes,
        "novos_complementos": inseridos,
        "fontes_consultadas": fontes_consultadas,
        "erros_fontes": erros_fontes,
        "conflitos": conflitos,
        "fontes_em_uso": dict(sorted(fontes.items())),
    }
    return saida, audit



def propagar_publicos_para_detalhes(
    detalhes: dict[str, Any],
    complementos: dict[str, Any],
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    """Atualiza somente público/fonte/tipo em jogos-detalhes, sem reconsultar ESPN.

    Regra conservadora: nunca substitui um público já informado por número
    diferente. Divergências são auditadas para revisão manual.
    """
    saida = dict(detalhes) if isinstance(detalhes, dict) else {}
    jogos_antigos = saida.get("jogos") if isinstance(saida.get("jogos"), dict) else {}
    jogos = {str(k): dict(v) for k, v in jogos_antigos.items() if isinstance(v, dict)}
    mapa = complementos.get("jogos") if isinstance(complementos, dict) else {}
    if not isinstance(mapa, dict):
        mapa = {}
    alteracoes = 0
    conflitos: list[dict[str, Any]] = []
    for event_id, comp in mapa.items():
        if not isinstance(comp, dict) or str(event_id) not in jogos:
            continue
        publico = numero_publico(comp.get("publico"))
        if publico is None:
            continue
        row = jogos[str(event_id)]
        atual = numero_publico(row.get("publico"))
        if atual is not None:
            if atual != publico:
                conflitos.append({
                    "event_id": str(event_id),
                    "publico_detalhes": atual,
                    "publico_complementar": publico,
                    "fonte_detalhes": str(row.get("publico_fonte") or ""),
                    "fonte_complementar": str(comp.get("fonte") or ""),
                })
            continue
        row["publico"] = publico
        row["publico_fonte"] = str(comp.get("fonte") or comp.get("origem") or "complemento documental")
        row["publico_tipo"] = str(comp.get("tipo") or "presente")
        alteracoes += 1

    if alteracoes:
        saida["jogos"] = jogos
        saida["total_com_publico"] = sum(1 for row in jogos.values() if numero_publico(row.get("publico")) is not None)
        # Não reescrevemos contadores de estatísticas/eventos: esta operação só
        # propaga público. O timestamp sinaliza ao front que o JSON mudou.
        saida["gerado_em"] = iso_agora_brt()
    return saida, alteracoes, conflitos


def self_test() -> None:
    fixture = r'''<!doctype html><html><body>
      <h2>Botafogo 2 x 1 Santos (Nilton Santos)</h2>
      <p>Público pagante: 13.632</p><p>Público presente: 15.585</p><p>Renda: R$ 457.870</p>
      <h2>Internacional 1 x 2 Cruzeiro (Beira-Rio)</h2>
      <p>Público pagante: 10.685</p><p>Público presente: não divulgado</p>
      <h2>Vasco 1 × 1 Mirassol (São Januário)</h2>
      <p>Público pagante: 9.983</p><p>Público total: 10.649</p>
      <script type="application/ld+json">{"articleBody":"Grêmio 1 x 1 Fluminense (Arena do Grêmio)\\nPúblico pagante: 23.728\\nPúblico presente: 23.993"}</script>
    </body></html>'''
    parsed = parse_artigo_ge(fixture)
    idx = {(time_canonico(x["mandante"]), time_canonico(x["visitante"])): x for x in parsed}
    assert idx[("botafogo", "santos")]["publico"] == 15585
    assert idx[("internacional", "cruzeiro")]["publico"] is None, "não pode usar pagantes quando o presente não foi divulgado"
    assert idx[("vasco da gama", "mirassol")]["publico"] == 10649
    assert idx[("gremio", "fluminense")]["publico"] == 23993
    assert numero_publico("70.791") == 70791
    assert numero_publico("70,791") == 70791
    assert numero_publico("não divulgado") is None
    assert time_canonico("Atlético Mineiro") == time_canonico("Atlético-MG")
    assert time_canonico("Vasco") == time_canonico("Vasco da Gama")
    assert time_canonico("RB Bragantino") == time_canonico("Bragantino")

    resultados = [
        {
            "event_id": "a", "rodada": 4, "data_iso": "2026-07-23T19:30", "estado": "post",
            "mandante": {"nome": "Botafogo"}, "visitante": {"nome": "Vitória"},
            "placar_mandante": 0, "placar_visitante": 0,
        },
        {
            "event_id": "b", "rodada": 0, "data_iso": "2026-07-23T19:30", "estado": "post",
            "mandante": {"nome": "Botafogo"}, "visitante": {"nome": "Vitória"},
            "placar_mandante": 0, "placar_visitante": 0,
        },
    ]
    mapa = {"a": {"publico": 16772, "tipo": "presente", "fonte": "teste"}}
    n, conflitos = propagar_duplicados(resultados, mapa)
    assert n == 1 and not conflitos and mapa["b"]["publico"] == 16772

    mapa_conflito = {"x": {"publico": 12345, "fonte": "antiga"}}
    mudou, conflito = _registrar_complemento(mapa_conflito, "x", 54321, "nova")
    assert not mudou and conflito and mapa_conflito["x"]["publico"] == 12345

    normal = "https://ge.globo.com/gato-mestre/noticia/2026/07/23/exemplo.ghtml"
    amp = "https://ge.globo.com/google/amp/gato-mestre/noticia/2026/07/23/exemplo.ghtml"
    assert variantes_url_ge(normal) == [normal, amp]
    assert variantes_url_ge(amp) == [normal, amp]
    base = {"mandante": "Internacional", "visitante": "Cruzeiro", "placar_mandante": 1, "placar_visitante": 2}
    itens, conflitos_merge = mesclar_itens_artigos([
        (normal, [{**base, "publico": None}]),
        (amp, [{**base, "publico": 12266}]),
    ])
    assert not conflitos_merge and len(itens) == 1 and itens[0]["publico"] == 12266 and itens[0]["_fonte_url"] == amp
    itens_conf, conflitos_merge = mesclar_itens_artigos([
        (normal, [{**base, "publico": 12000}]),
        (amp, [{**base, "publico": 12266}]),
    ])
    assert not itens_conf and len(conflitos_merge) == 1

    detalhes_fixture = {
        "gerado_em": "antes",
        "total_com_publico": 0,
        "jogos": {
            "x": {"event_id": "x", "publico": None},
            "y": {"event_id": "y", "publico": 12000, "publico_fonte": "ESPN"},
        },
    }
    comp_fixture = {"jogos": {
        "x": {"publico": 15000, "tipo": "presente", "fonte": "ge"},
        "y": {"publico": 13000, "tipo": "presente", "fonte": "ge"},
    }}
    detalhes_novos, n_prop, conf_prop = propagar_publicos_para_detalhes(detalhes_fixture, comp_fixture)
    assert n_prop == 1 and detalhes_novos["jogos"]["x"]["publico"] == 15000
    assert detalhes_novos["jogos"]["y"]["publico"] == 12000 and len(conf_prop) == 1

    sitemap_fixture = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ge.globo.com/gato-mestre/noticia/2026/08/09/flamengo-x-vitoria-tem-o-maior-publico-da-22a-rodada-do-brasileirao-veja-a-lista.ghtml</loc></url>
      <url><loc>https://ge.globo.com/futebol/noticia/2026/08/09/outra-materia.ghtml</loc></url>
    </urlset>"""
    sm = extrair_urls_sitemap(sitemap_fixture)
    assert len(sm) == 2
    assert pontuar_url_publico_ge(sm[0], 22) >= 30
    assert pontuar_url_publico_ge(sm[1], 22) < 18

    print("SELF-TEST OK: parser GE, sitemap dinâmico, normal+AMP, público presente/total, bloqueio de pagantes, aliases, duplicados e conflitos.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Atualiza público presente complementar do Brasileirão.")
    parser.add_argument("--self-test", action="store_true", help="Executa testes internos sem rede.")
    parser.add_argument("--dry-run", action="store_true", help="Executa coleta/auditoria sem gravar arquivos.")
    parser.add_argument("--sem-rede", action="store_true", help="Somente consolida/propaga os complementos já gravados.")
    parser.add_argument("--max-rodadas", type=int, default=0, help="Limita rodadas consultadas na rede (0 = todas pendentes).")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    resultados_payload = carregar_json(RESULTADOS, {})
    resultados = resultados_payload.get("resultados") if isinstance(resultados_payload, dict) else []
    if not isinstance(resultados, list):
        raise RuntimeError("resultados.json inválido: campo resultados não é lista")
    detalhes = carregar_json(DETALHES, {})
    payload = carregar_json(SAIDA, {"jogos": {}})
    if not isinstance(payload, dict):
        payload = {"jogos": {}}

    saida, audit = executar_coleta(
        [x for x in resultados if isinstance(x, dict)],
        detalhes if isinstance(detalhes, dict) else {},
        payload,
        sem_rede=bool(args.sem_rede),
        max_rodadas=max(0, int(args.max_rodadas or 0)),
    )

    if args.dry_run:
        print(json.dumps({
            "novos_complementos": audit["novos_complementos"],
            "total_sem_publico": audit["total_sem_publico"],
            "rodadas_pendentes": audit["rodadas_pendentes_no_inicio"],
            "conflitos": len(audit["conflitos"]),
            "erros_fontes": len(audit["erros_fontes"]),
        }, ensure_ascii=False))
        return

    salvar_json_atomico(SAIDA, saida)

    detalhes_atualizados, propagados_detalhes, conflitos_detalhes = propagar_publicos_para_detalhes(
        detalhes if isinstance(detalhes, dict) else {}, saida
    )
    if propagados_detalhes:
        salvar_json_atomico(DETALHES, detalhes_atualizados)
    audit["propagados_para_jogos_detalhes"] = propagados_detalhes
    audit["conflitos_jogos_detalhes"] = conflitos_detalhes

    audit_anterior = carregar_json(AUDITORIA, {})
    if isinstance(audit_anterior, dict):
        atual_cmp = {k: v for k, v in audit.items() if k != "gerado_em"}
        anterior_cmp = {k: v for k, v in audit_anterior.items() if k != "gerado_em"}
        if atual_cmp == anterior_cmp and audit_anterior.get("gerado_em"):
            audit["gerado_em"] = audit_anterior["gerado_em"]
    salvar_json_atomico(AUDITORIA, audit)
    print(
        "OK: públicos complementares atualizados · "
        f"novos={audit['novos_complementos']} · propagados_detalhes={propagados_detalhes} · "
        f"cobertura={audit['total_com_publico_ou_complemento']}/{audit['total_jogos_finalizados']} · "
        f"sem público={audit['total_sem_publico']} · conflitos={len(audit['conflitos']) + len(conflitos_detalhes)}"
    )
    if audit["erros_fontes"]:
        print(f"AVISO: {len(audit['erros_fontes'])} falha(s) de fonte externa; snapshot anterior preservado.", file=sys.stderr)


if __name__ == "__main__":
    main()

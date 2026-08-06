#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Otimizador de imagens do site (execucao local, uma unica vez ou quando entrarem
imagens novas).

Motivo: o artefato publicado no GitHub Pages estava com ~191 MB porque diversas
imagens estao em resolucao de impressao (ex.: 3200x4000 px, 2 MB cada) para
serem exibidas em cards de poucas centenas de pixels. Artefato grande faz o
passo `actions/deploy-pages` estourar o tempo limite ("deployment_queued" ate
"Timeout reached, aborting!").

O script reduz a maior dimensao para MAX_LADO px e recomprime PNG/JPG/WebP
mantendo o MESMO nome de arquivo, sem alterar HTML/CSS/JS.

Uso:
    python scripts/otimizar_imagens.py --dry-run     # so relatorio, nao grava
    python scripts/otimizar_imagens.py               # aplica
    python scripts/otimizar_imagens.py --max-lado 900 --pastas img copa2026/img

Requer: pip install pillow
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("ERRO: Pillow nao instalado. Rode: pip install pillow")
    sys.exit(1)

Image.MAX_IMAGE_PIXELS = None

EXTENSOES = {".png", ".jpg", ".jpeg", ".webp"}
PASTAS_PADRAO = ["img", "copa2026/img", "dados-br"]
MAX_LADO_PADRAO = 1200
QUALIDADE_JPG = 82
GANHO_MINIMO = 0.03  # so grava se economizar pelo menos 3%


def humano(n: int) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.1f} {unidade}" if unidade != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def otimizar(caminho: Path, max_lado: int, dry_run: bool) -> tuple[int, int]:
    original = caminho.stat().st_size
    try:
        img = Image.open(caminho)
        img.load()
    except Exception as exc:
        print(f"  ! ignorado ({exc}): {caminho}")
        return original, original

    formato = (img.format or "").upper()
    largura, altura = img.size

    if max(largura, altura) > max_lado:
        escala = max_lado / float(max(largura, altura))
        novo = (max(1, round(largura * escala)), max(1, round(altura * escala)))
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img = img.resize(novo, Image.LANCZOS)

    destino_tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    try:
        if formato == "PNG":
            trabalho = img
            if trabalho.mode not in ("RGBA", "RGB", "P"):
                trabalho = trabalho.convert("RGBA")
            if trabalho.mode in ("RGBA", "RGB"):
                trabalho = trabalho.quantize(
                    colors=256, method=Image.Quantize.FASTOCTREE
                )
            trabalho.save(destino_tmp, format="PNG", optimize=True)
        elif formato in ("JPEG", "MPO"):
            img.convert("RGB").save(
                destino_tmp,
                format="JPEG",
                quality=QUALIDADE_JPG,
                optimize=True,
                progressive=True,
            )
        elif formato == "WEBP":
            img.save(destino_tmp, format="WEBP", quality=QUALIDADE_JPG, method=6)
        else:
            return original, original
    except Exception as exc:
        print(f"  ! falha ao recomprimir ({exc}): {caminho}")
        if destino_tmp.exists():
            destino_tmp.unlink()
        return original, original
    finally:
        img.close()

    final = destino_tmp.stat().st_size
    if final >= original * (1 - GANHO_MINIMO):
        destino_tmp.unlink()
        return original, original

    if dry_run:
        destino_tmp.unlink()
    else:
        destino_tmp.replace(caminho)
    return original, final


def main() -> int:
    parser = argparse.ArgumentParser(description="Otimiza imagens do site.")
    parser.add_argument("--max-lado", type=int, default=MAX_LADO_PADRAO)
    parser.add_argument("--pastas", nargs="*", default=PASTAS_PADRAO)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raiz", default=".")
    args = parser.parse_args()

    raiz = Path(args.raiz).resolve()
    arquivos: list[Path] = []
    for pasta in args.pastas:
        base = raiz / pasta
        if not base.exists():
            print(f"AVISO: pasta inexistente, ignorada: {pasta}")
            continue
        arquivos.extend(
            p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSOES
        )

    if not arquivos:
        print("Nenhuma imagem encontrada.")
        return 0

    antes_total = 0
    depois_total = 0
    alterados = 0
    for caminho in sorted(arquivos):
        antes, depois = otimizar(caminho, args.max_lado, args.dry_run)
        antes_total += antes
        depois_total += depois
        if depois < antes:
            alterados += 1
            print(
                f"  {humano(antes):>9} -> {humano(depois):>9}  "
                f"{caminho.relative_to(raiz)}"
            )

    economia = antes_total - depois_total
    pct = (economia / antes_total * 100) if antes_total else 0
    print("-" * 72)
    print(f"Imagens analisadas : {len(arquivos)}")
    print(f"Imagens otimizadas : {alterados}")
    print(f"Antes              : {humano(antes_total)}")
    print(f"Depois             : {humano(depois_total)}")
    print(f"Economia           : {humano(economia)} ({pct:.1f}%)")
    if args.dry_run:
        print("\n(dry-run: nenhum arquivo foi gravado)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

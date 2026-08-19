#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera auditoria local da cobertura de estatísticas da aba Resultados."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

BRT = dt.timezone(dt.timedelta(hours=-3))

def agora_iso() -> str:
    return dt.datetime.now(BRT).replace(microsecond=0).isoformat()

def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def nome_time(obj: Any) -> str:
    return str(obj.get("nome") or "") if isinstance(obj, dict) else str(obj or "")

def stats_do_jogo(jogo: Dict[str, Any], detalhes: Dict[str, Any]) -> List[Dict[str, Any]]:
    jogos = detalhes.get("jogos") or {}
    event_id = str(jogo.get("event_id") or jogo.get("id") or "").strip()
    det = jogos.get(event_id) if isinstance(jogos, dict) and event_id else None
    if not isinstance(det, dict):
        return []
    stats = det.get("stats") or det.get("estatisticas") or []
    if not isinstance(stats, list):
        return []
    return [s for s in stats if isinstance(s, dict) and (s.get("home") not in (None, "") or s.get("away") not in (None, ""))]

def jogo_resumido(j: Dict[str, Any], motivo: str = "") -> Dict[str, Any]:
    item = {
        "event_id": str(j.get("event_id") or j.get("id") or ""),
        "rodada": j.get("rodada"),
        "mandante": nome_time(j.get("mandante")),
        "visitante": nome_time(j.get("visitante")),
        "placar_mandante": j.get("placar_mandante"),
        "placar_visitante": j.get("placar_visitante"),
        "data_iso": j.get("data_iso"),
    }
    if motivo:
        item["motivo"] = motivo
    return item

def main() -> int:
    ap = argparse.ArgumentParser(description="Gera auditoria de cobertura de estatísticas na aba Resultados.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--saida", default="dados-br/auditoria-cobertura-resultados.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    resultados = load_json(root / "resultados.json", {"resultados": []})
    detalhes = load_json(root / "dados-br" / "jogos-detalhes.json", {"jogos": {}})
    jogos = resultados.get("resultados") or []
    if not isinstance(jogos, list): jogos = []
    com_stats, sem_stats = [], []
    por_rodada: Dict[str, Dict[str, int]] = {}
    for j in jogos:
        r = str(j.get("rodada") or "?")
        por_rodada.setdefault(r, {"jogos": 0, "com_estatisticas": 0, "sem_estatisticas": 0})
        por_rodada[r]["jogos"] += 1
        stats = stats_do_jogo(j, detalhes)
        if stats:
            item = jogo_resumido(j); item["estatisticas"] = len(stats); com_stats.append(item); por_rodada[r]["com_estatisticas"] += 1
        else:
            sem_stats.append(jogo_resumido(j, "sem estatísticas ESPN summary")); por_rodada[r]["sem_estatisticas"] += 1
    total=len(jogos)
    saida={
        "atualizado_em": agora_iso(),
        "fonte": "auditoria local do site",
        "resumo": {
            "jogos_resultados": total,
            "jogos_com_estatisticas": len(com_stats),
            "jogos_sem_estatisticas": len(sem_stats),
            "percentual_estatisticas": round((len(com_stats)/total*100),1) if total else 0,
        },
        "por_rodada": dict(sorted(por_rodada.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 999)),
        "jogos_sem_estatisticas": sorted(sem_stats, key=lambda x:(x.get("rodada") or 999, x.get("mandante") or "")),
    }
    if args.dry_run:
        print(json.dumps(saida["resumo"],ensure_ascii=False,indent=2)); return 0
    save_json(root/args.saida,saida)
    print("Auditoria de cobertura gerada:",args.saida)
    print(json.dumps(saida["resumo"],ensure_ascii=False,indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

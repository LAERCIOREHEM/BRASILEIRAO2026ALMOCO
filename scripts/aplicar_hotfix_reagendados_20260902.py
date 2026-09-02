#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# HOTFIX_REAGENDADOS_20260902
#
# Aplica sobre a versão ATUAL do repositório:
# - TBA manual antigo não sobrescreve kickoff novo/ativo;
# - data oficial da CBF reativa operacionalmente jogo antes adiado;
# - Ao Vivo não herda adiado=true histórico quando ESPN atual está normal;
# - remove override obsoleto Flamengo x Mirassol R4;
# - adiciona regressões permanentes ao selftest;
# - força cache-bust do br-aovivo.js.

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "atualizar_espn.py"
JS = ROOT / "js" / "br-aovivo.js"
HTML = ROOT / "aovivo.html"
AJUSTES = ROOT / "dados-br" / "ajustes-calendario.json"

MARCADOR = "HOTFIX_REAGENDADOS_20260902"


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"ERRO: arquivo esperado não existe: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def replace_function(text: str, name: str, next_name: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^def {re.escape(name)}\(.*?(?=^def {re.escape(next_name)}\()"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"ERRO: esperava exatamente 1 função {name} antes de {next_name}; achei {len(matches)}."
        )
    return text[:matches[0].start()] + replacement.rstrip() + "\n\n" + text[matches[0].end():]


NEW_APLICAR_AJUSTES = r'''
def aplicar_ajustes_calendario(eventos: list[dict[str, Any]]) -> None:
    # HOTFIX_REAGENDADOS_20260902
    # "adiado" é estado operacional atual, não histórico eterno.
    ajustes = carregar_ajustes_calendario()
    if not ajustes:
        return

    aplicados = 0
    obsoletos = 0
    for ajuste in ajustes:
        event_id = str(ajuste.get("event_id") or "").strip()
        mand = para_canonico(ajuste.get("mandante"))
        vis = para_canonico(ajuste.get("visitante"))
        alvo = None
        for e in eventos:
            bate_id = bool(event_id and str(e.get("event_id") or "") == event_id)
            bate_jogo = bool(
                mand and vis
                and e.get("mandante_nome") == mand
                and e.get("visitante_nome") == vis
            )
            if bate_id or bate_jogo:
                alvo = e
                break

        if alvo is None:
            print(
                "Aviso: ajuste de calendário não encontrou evento: "
                f"{event_id or (mand + ' x ' + vis if mand and vis else '?')}"
            )
            continue

        fonte_finalizada = bool(
            alvo.get("concluido") is True
            or str(alvo.get("estado") or "").lower() == "post"
        )

        rodada = ajuste.get("rodada")
        if rodada not in (None, ""):
            alvo["rodada"] = int(rodada)

        for campo in ("estadio", "transmissao"):
            if campo in ajuste and ajuste[campo]:
                alvo[campo] = ajuste[campo]

        fonte_tem_kickoff_ativo = bool(
            isinstance(alvo.get("data_dt"), datetime)
            and alvo.get("data_definir") is not True
            and alvo.get("adiado") is not True
            and not fonte_finalizada
        )

        ajuste_operacional_aplicado = False

        if fonte_finalizada:
            # Fonte finalizada é soberana: não volta a ser "adiada".
            pass

        elif ajuste.get("data_definir") is True and fonte_tem_kickoff_ativo:
            # TBA manual antigo perde para kickoff novo e ativo da fonte.
            obsoletos += 1
            motivo_antigo = str(ajuste.get("motivo") or "").strip()
            if str(alvo.get("motivo_ajuste") or "").strip() == motivo_antigo:
                alvo["motivo_ajuste"] = ""
            alvo["ajuste_calendario"] = False
            print(
                "::notice::Ajuste manual TBA obsoleto ignorado; "
                f"fonte atual já confirmou {alvo.get('mandante_nome')} x "
                f"{alvo.get('visitante_nome')} em {alvo.get('data_iso')}."
            )
            continue

        elif ajuste.get("data_definir") is True:
            alvo["adiado"] = True
            alvo["data_definir"] = True
            alvo["data_iso"] = None
            alvo["data_dt"] = None
            alvo["_sort"] = float("inf")
            ajuste_operacional_aplicado = True

        elif ajuste.get("data_iso"):
            dt = _parse_data_manual_brt(ajuste.get("data_iso"))
            if not dt:
                raise RuntimeError(
                    f"Data manual inválida no ajuste {event_id}: {ajuste.get('data_iso')}"
                )
            alvo["adiado"] = False
            alvo["data_definir"] = False
            alvo["data_dt"] = dt
            alvo["data_iso"] = dt.strftime("%Y-%m-%dT%H:%M")
            alvo["_sort"] = dt.timestamp()
            ajuste_operacional_aplicado = True

        elif ajuste.get("adiado") is True:
            alvo["adiado"] = True
            ajuste_operacional_aplicado = True

        if not ajuste_operacional_aplicado:
            continue

        alvo["ajuste_calendario"] = True
        alvo["motivo_ajuste"] = str(ajuste.get("motivo") or "").strip()

        inicio_ajustado = alvo.get("data_dt")
        estado_manual_ainda_valido = (
            not isinstance(inicio_ajustado, datetime)
            or agora_brt() < inicio_ajustado - timedelta(minutes=15)
        )
        if estado_manual_ainda_valido:
            for campo in (
                "estado",
                "status",
                "placar_mandante",
                "placar_visitante",
                "concluido",
            ):
                if campo in ajuste:
                    alvo[campo] = ajuste[campo]

        aplicados += 1

    print(
        f"Ajustes de calendário aplicados: {aplicados}/{len(ajustes)}"
        + (f"; TBA obsoleto(s) ignorado(s): {obsoletos}" if obsoletos else "")
    )
'''

NEW_CBF = r'''
def aplicar_agenda_oficial_cbf(eventos: list[dict[str, Any]], rows: list[Any]) -> int:
    # HOTFIX_REAGENDADOS_20260902
    # Uma nova data oficial reativa operacionalmente o jogo.
    if not rows:
        return 0

    agora = agora_brt()
    alterados = 0

    for evento in eventos:
        estado_atual = str(evento.get("estado") or "").lower()
        if evento.get("concluido") is True or estado_atual == "post":
            continue

        home = str(evento.get("mandante_nome") or "")
        away = str(evento.get("visitante_nome") or "")
        oficial = localizar_agenda_cbf(rows, mandante=home, visitante=away)
        if not oficial:
            continue

        dt = parse_iso_brt(oficial.data_iso)
        if not dt or dt < agora - timedelta(hours=6):
            continue

        anterior = str(evento.get("data_iso") or "")
        novo = dt.strftime("%Y-%m-%dT%H:%M")
        estava_interrompido = bool(
            evento.get("adiado") is True
            or evento.get("data_definir") is True
            or _status_interrompido({}, str(evento.get("status") or ""))
        )

        mudou = bool(
            anterior != novo
            or evento.get("adiado") is True
            or evento.get("data_definir") is True
        )

        if anterior != novo and not str(evento.get("data_espn_original") or "").strip():
            evento["data_espn_original"] = anterior

        evento["data_iso"] = novo
        evento["data_dt"] = dt
        evento["_sort"] = dt.timestamp()
        evento["data_definir"] = False
        evento["adiado"] = False

        # Não rebaixa uma partida efetivamente ao vivo para pré-jogo.
        if estado_atual != "in":
            evento["estado"] = "pre"
            evento["concluido"] = False
            if estava_interrompido:
                evento["status"] = "Pré-jogo"
                mudou = True

        evento["fonte_calendario"] = "CBF oficial — agenda de credenciamento"
        evento["origem_calendario"] = oficial.origem

        if mudou:
            alterados += 1

    eventos.sort(key=lambda e: float(e.get("_sort") or 0))
    return alterados
'''

REGRESSION_BLOCK = r'''
    # HOTFIX_REAGENDADOS_20260902 — regressões permanentes.
    # 1) TBA manual antigo não pode apagar kickoff novo/ativo da ESPN.
    ajustes_original = globals()["carregar_ajustes_calendario"]
    try:
        futuro_ativo = agora_brt() + timedelta(days=2)
        globals()["carregar_ajustes_calendario"] = lambda: [{
            "event_id": "id-antigo",
            "rodada": 4,
            "mandante": "Flamengo",
            "visitante": "Mirassol",
            "data_definir": True,
            "estado": "pre",
            "concluido": False,
            "status": "Data a definir",
            "motivo": "TBA antigo de teste",
        }]
        reagendado_espn = [{
            "event_id": "id-novo",
            "rodada": 4,
            "mandante_nome": "Flamengo",
            "visitante_nome": "Mirassol",
            "data_dt": futuro_ativo,
            "data_iso": futuro_ativo.strftime("%Y-%m-%dT%H:%M"),
            "_sort": futuro_ativo.timestamp(),
            "estado": "pre",
            "concluido": False,
            "adiado": False,
            "data_definir": False,
            "status": "0'",
        }]
        aplicar_ajustes_calendario(reagendado_espn)
        assert reagendado_espn[0]["data_iso"] == futuro_ativo.strftime("%Y-%m-%dT%H:%M")
        assert reagendado_espn[0]["adiado"] is False
        assert reagendado_espn[0]["data_definir"] is False
        assert reagendado_espn[0]["status"] == "0'"
    finally:
        globals()["carregar_ajustes_calendario"] = ajustes_original

    # 2) CBF com nova data limpa o estado operacional de adiamento,
    # inclusive se a data já tiver sido gravada numa execução anterior.
    localizar_original = globals()["localizar_agenda_cbf"]
    try:
        class _AgendaTesteReagendado:
            mandante = "Botafogo"
            visitante = "Grêmio"
            data_iso = (agora_brt() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
            origem = "https://credencial.cbf.com.br/teste-reagendado"

        agenda_teste = _AgendaTesteReagendado()
        globals()["localizar_agenda_cbf"] = (
            lambda rows, mandante, visitante:
            rows[0]
            if rows and mandante == rows[0].mandante and visitante == rows[0].visitante
            else None
        )
        antigo = agora_brt() - timedelta(days=20)
        evento_reagendado = [{
            "event_id": "reagendado-r21",
            "rodada": 21,
            "mandante_nome": "Botafogo",
            "visitante_nome": "Grêmio",
            "data_dt": antigo,
            "data_iso": antigo.strftime("%Y-%m-%dT%H:%M"),
            "_sort": antigo.timestamp(),
            "estado": "pre",
            "concluido": False,
            "adiado": True,
            "data_definir": False,
            "status": "Postponed",
        }]
        assert aplicar_agenda_oficial_cbf(evento_reagendado, [agenda_teste]) == 1
        assert evento_reagendado[0]["data_iso"] == agenda_teste.data_iso
        assert evento_reagendado[0]["adiado"] is False
        assert evento_reagendado[0]["data_definir"] is False
        assert evento_reagendado[0]["estado"] == "pre"
        assert evento_reagendado[0]["status"] == "Pré-jogo"
        assert evento_reagendado[0]["fonte_calendario"].startswith("CBF oficial")
    finally:
        globals()["localizar_agenda_cbf"] = localizar_original

'''


def patch_python() -> None:
    text = read(PY)
    text = replace_function(
        text, "aplicar_ajustes_calendario", "_status_interrompido", NEW_APLICAR_AJUSTES
    )
    text = replace_function(
        text, "aplicar_agenda_oficial_cbf", "marcar_kickoffs_provisorios_espn", NEW_CBF
    )

    selftest_pos = text.find("def selftest_execucao_6")
    if selftest_pos < 0:
        raise SystemExit("ERRO: selftest_execucao_6 não encontrado.")
    if MARCADOR not in text[selftest_pos:]:
        anchor = "    # Proveniência da CBF precisa sobreviver ao espn_eventos.json; sem isso a\n"
        if anchor not in text:
            raise SystemExit("ERRO: âncora do selftest não encontrada em atualizar_espn.py.")
        text = text.replace(anchor, REGRESSION_BLOCK + anchor, 1)

    write(PY, text)


def patch_js() -> None:
    text = read(JS)
    old = "      adiado: loc.adiado || game.adiado,\n"
    new = (
        "      // HOTFIX_REAGENDADOS_20260902: snapshot historicamente adiado não\\n"
        "      // contamina um evento ESPN atual que já voltou a ter kickoff ativo.\\n"
        "      adiado: game.adiado === true || (!game.date && loc.adiado === true),\\n"
    ).replace("\\n", "\n")
    if MARCADOR not in text:
        if old not in text:
            raise SystemExit("ERRO: merge do campo adiado não encontrado em js/br-aovivo.js.")
        text = text.replace(old, new, 1)
    write(JS, text)


def patch_html() -> None:
    text = read(HTML)
    pattern = re.compile(r'<script src="js/br-aovivo\.js\?v=[^"]+"></script>')
    replacement = '<script src="js/br-aovivo.js?v=20260902-reagendados-v1"></script>'
    text2, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(
            f"ERRO: referência única a br-aovivo.js não encontrada em aovivo.html (count={count})."
        )
    write(HTML, text2)


def patch_ajustes() -> None:
    raw = json.loads(read(AJUSTES))
    ajustes = raw.get("ajustes")
    if not isinstance(ajustes, list):
        raise SystemExit("ERRO: ajustes-calendario.json não contém lista 'ajustes'.")

    antes = len(ajustes)
    novos = []
    removidos = 0
    for item in ajustes:
        if (
            isinstance(item, dict)
            and str(item.get("mandante") or "").strip() == "Flamengo"
            and str(item.get("visitante") or "").strip() == "Mirassol"
            and int(item.get("rodada") or 0) == 4
            and item.get("data_definir") is True
        ):
            removidos += 1
            continue
        novos.append(item)

    raw["ajustes"] = novos
    brt = timezone(timedelta(hours=-3))
    raw["atualizado_em"] = datetime.now(brt).replace(microsecond=0).isoformat()
    write(AJUSTES, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    print(
        f"ajustes-calendario.json: {antes} -> {len(novos)} ajustes; "
        f"TBA Flamengo x Mirassol removido(s): {removidos}"
    )


def validate_static() -> None:
    py = read(PY)
    js = read(JS)
    html = read(HTML)
    ajustes = json.loads(read(AJUSTES))

    for needle in (
        "TBA manual antigo não pode apagar kickoff novo/ativo da ESPN",
        'evento["adiado"] = False',
        'evento["data_definir"] = False',
        "TBA obsoleto(s) ignorado(s)",
    ):
        if needle not in py:
            raise SystemExit(f"ERRO: validação estática falhou; ausente: {needle}")

    if "adiado: game.adiado === true || (!game.date && loc.adiado === true)" not in js:
        raise SystemExit("ERRO: correção JS de adiado não aplicada.")
    if "20260902-reagendados-v1" not in html:
        raise SystemExit("ERRO: cache-bust do Ao Vivo não aplicado.")

    for item in ajustes.get("ajustes") or []:
        if (
            str(item.get("mandante") or "") == "Flamengo"
            and str(item.get("visitante") or "") == "Mirassol"
            and item.get("data_definir") is True
        ):
            raise SystemExit("ERRO: override TBA Flamengo x Mirassol ainda existe.")


def main() -> None:
    patch_python()
    patch_js()
    patch_html()
    patch_ajustes()
    validate_static()
    print("HOTFIX_REAGENDADOS_20260902 aplicado com sucesso.")


if __name__ == "__main__":
    main()

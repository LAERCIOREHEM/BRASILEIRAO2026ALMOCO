#!/usr/bin/env python3
"""
Script que busca a tabela do Brasileirão e salva em tabela.json.

Roda no GitHub Actions, sem CORS e sem proxy.
Fluxo:
1. Tenta buscar a tabela no Terra.
2. Se falhar, tenta buscar no GloboEsporte.
3. Normaliza os nomes dos clubes.
4. Gera tabela.json com horário de Brasília e metadados de atualização.

Observação importante:
O horário salvo em "atualizado_em" é o horário real em que o GitHub Actions
executou este script. O cron agenda para :07 e :37, mas o GitHub pode atrasar
alguns minutos a execução.
"""

import json
import sys
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser


# ============================================================================
# CONFIGURAÇÕES GERAIS
# ============================================================================

FUSO_BRASILIA = timezone(timedelta(hours=-3))
URL_TERRA = "https://www.terra.com.br/esportes/futebol/brasileiro-serie-a/tabela/"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================================
# UTILITÁRIOS DE DATA/HORA
# ============================================================================

def agora_brasilia():
    return datetime.now(FUSO_BRASILIA)


def calcular_proxima_prevista(dt=None):
    """
    Calcula a próxima atualização prevista nos minutos :07 ou :37.
    Isso é apenas informativo para o site.
    """
    if dt is None:
        dt = agora_brasilia()

    minuto = dt.minute

    if minuto < 7:
        proxima = dt.replace(minute=7, second=0, microsecond=0)
    elif minuto < 37:
        proxima = dt.replace(minute=37, second=0, microsecond=0)
    else:
        proxima = dt.replace(hour=dt.hour + 1, minute=7, second=0, microsecond=0)

    return proxima


# ============================================================================
# FETCH COM ANTI-CACHE
# ============================================================================

def fetch(url, timeout=20):
    """
    Baixa o conteúdo de uma URL com headers de navegador e parâmetro anti-cache.
    """
    separador = "&" if "?" in url else "?"
    url_anticache = f"{url}{separador}_={int(datetime.now().timestamp())}"

    req = urllib.request.Request(url_anticache, headers=HEADERS)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# ============================================================================
# FONTE 1: TERRA
# ============================================================================

class TerraParser(HTMLParser):
    """
    Parser simples para extrair tabelas HTML do Terra.
    """

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False

        self.current_table = []
        self.current_row = []
        self.current_cell = ""
        self.tables = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.current_table = []

        elif tag == "tbody" and self.in_table:
            self.in_tbody = True

        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []

        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
            cell = limpar_texto(self.current_cell)
            self.current_row.append(cell)

        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = []

        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False

        elif tag == "table" and self.in_table:
            self.in_table = False
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def limpar_texto(txt):
    """
    Remove excesso de espaços, quebras, símbolos soltos e lixo visual.
    """
    if txt is None:
        return ""

    txt = re.sub(r"\s+", " ", txt)
    txt = txt.replace("»", "").replace("«", "").replace(">", "")
    return txt.strip()


def extrair_inteiros(linha):
    """
    Extrai inteiros de uma linha da tabela.
    """
    nums = []

    for item in linha:
        item_limpo = limpar_texto(item)

        # Captura apenas células que sejam números inteiros puros, inclusive negativos.
        if re.fullmatch(r"-?\d+", item_limpo):
            nums.append(int(item_limpo))

    return nums


def extrair_nome_time(linha):
    """
    Tenta identificar o nome do time na linha do Terra.

    A estrutura mais comum é:
    posição | escudo | nome | tendência | P | J | V | E | D | GP | GC | SG | %

    Porém, como o Terra pode mudar pequenos detalhes, esta função tenta achar
    o primeiro texto plausível que não seja número nem símbolo visual.
    """
    candidatos = []

    for item in linha:
        item = limpar_texto(item)

        if not item:
            continue

        if re.fullmatch(r"-?\d+", item):
            continue

        if item in {"-", "+", "=", "▲", "▼"}:
            continue

        # Evita textos muito curtos que sejam apenas tendência ou lixo.
        if len(item) < 3:
            continue

        candidatos.append(item)

    if not candidatos:
        return ""

    # Em geral o nome do time é o primeiro texto plausível.
    return candidatos[0]


def buscar_terra():
    """
    Busca a tabela no Terra.
    Retorna lista de dicts.
    """
    html = fetch(URL_TERRA)

    parser = TerraParser()
    parser.feed(html)

    if not parser.tables:
        raise Exception("Nenhuma tabela HTML encontrada no Terra")

    # Preferir tabela com exatamente 20 linhas.
    tabela_certa = None

    for tabela in parser.tables:
        if len(tabela) == 20:
            tabela_certa = tabela
            break

    # Se não achou exatamente 20, pega a maior tabela com pelo menos 20 linhas.
    if tabela_certa is None:
        tabelas_validas = [t for t in parser.tables if len(t) >= 20]
        if not tabelas_validas:
            raise Exception(
                f"Formato inesperado no Terra. Tabelas encontradas: "
                f"{[len(t) for t in parser.tables]}"
            )
        tabela_certa = max(tabelas_validas, key=len)[:20]

    resultado = []

    for linha in tabela_certa:
        if len(linha) < 10:
            continue

        try:
            pos = int(limpar_texto(linha[0]))
        except Exception:
            continue

        nome = extrair_nome_time(linha)
        if not nome:
            continue

        nums = extrair_inteiros(linha)

        # Esperado, no mínimo:
        # pos, P, J, V, E, D, GP, GC, SG, %
        # Alguns layouts podem repetir ou ocultar valores.
        if len(nums) < 10:
            raise Exception(
                f"Linha com poucos números no Terra: {linha} | nums={nums}"
            )

        # A primeira posição costuma ser a colocação.
        # Os últimos 9 números devem ser:
        # P, J, V, E, D, GP, GC, SG, %
        relevantes = nums[-9:]
        pontos, jogos, vitorias, empates, derrotas, gp, gc, sg, aproveitamento = relevantes

        resultado.append({
            "pos": pos,
            "time": normalizar_nome(nome),
            "pontos": pontos,
            "jogos": jogos,
            "vitorias": vitorias,
            "empates": empates,
            "derrotas": derrotas,
            "gp": gp,
            "gc": gc,
            "sg": sg,
            "aproveitamento": aproveitamento,
        })

    validar_tabela(resultado, "Terra")

    resultado.sort(key=lambda x: x["pos"])
    return resultado


# ============================================================================
# FONTE 2: GLOBOESPORTE
# ============================================================================

def buscar_globoesporte():
    """
    Backup via API do GloboEsporte.

    Atenção:
    Essa URL pode mudar conforme o campeonato/temporada.
    Mantida apenas como backup.
    """
    ano = agora_brasilia().year

    url = (
        "https://api.globoesporte.globo.com/tabela/"
        "d1a37fa4-e948-43a6-ba53-ab24ab3a45b1/"
        f"fase/fase-unica-campeonato-brasileiro-{ano}/classificacao/"
    )

    raw = fetch(url)
    data = json.loads(raw)

    if not isinstance(data, list):
        raise Exception(f"Formato inesperado da API GE: {type(data).__name__}")

    resultado = []

    for item in data:
        clube = item.get("equipe") or item.get("clube") or {}
        nome = clube.get("nome_popular") or clube.get("nome") or ""

        pos = item.get("ordem") or item.get("posicao")

        resultado.append({
            "pos": int(pos or 0),
            "time": normalizar_nome(nome),
            "pontos": int(item.get("pontos") or 0),
            "jogos": int(item.get("jogos") or 0),
            "vitorias": int(item.get("vitorias") or 0),
            "empates": int(item.get("empates") or 0),
            "derrotas": int(item.get("derrotas") or 0),
            "gp": int(item.get("gols_pro") or 0),
            "gc": int(item.get("gols_contra") or 0),
            "sg": int(item.get("saldo_gols") or 0),
            "aproveitamento": int(float(item.get("aproveitamento") or 0)),
        })

    validar_tabela(resultado, "GloboEsporte")

    resultado.sort(key=lambda x: x["pos"])
    return resultado


# ============================================================================
# NORMALIZAÇÃO DE NOMES
# ============================================================================

NORMALIZACAO_NOMES = {
    "Atlético Mineiro": "Atlético-MG",
    "Atletico Mineiro": "Atlético-MG",
    "Atlético-MG": "Atlético-MG",
    "Atletico-MG": "Atlético-MG",
    "CAM": "Atlético-MG",

    "Athletico Paranaense": "Athletico-PR",
    "Atlético Paranaense": "Athletico-PR",
    "Athletico-PR": "Athletico-PR",
    "CAP": "Athletico-PR",

    "Red Bull Bragantino": "Bragantino",
    "RB Bragantino": "Bragantino",
    "Bragantino": "Bragantino",

    "Vasco": "Vasco da Gama",
    "Vasco da Gama": "Vasco da Gama",

    "São Paulo": "São Paulo",
    "Sao Paulo": "São Paulo",

    "Grêmio": "Grêmio",
    "Gremio": "Grêmio",

    "Vitória": "Vitória",
    "Vitoria": "Vitória",

    "Ceará": "Ceará",
    "Ceara": "Ceará",

    "Goiás": "Goiás",
    "Goias": "Goiás",

    "Cuiabá": "Cuiabá",
    "Cuiaba": "Cuiabá",

    "Sport Recife": "Sport",
    "Sport": "Sport",
}


def normalizar_nome(nome):
    nome = limpar_texto(nome)
    return NORMALIZACAO_NOMES.get(nome, nome)


# ============================================================================
# VALIDAÇÃO
# ============================================================================

def validar_tabela(tabela, fonte):
    """
    Valida se a tabela extraída parece consistente.
    """
    if not isinstance(tabela, list):
        raise Exception(f"{fonte}: tabela não é lista")

    if len(tabela) != 20:
        raise Exception(f"{fonte}: esperava 20 times, obtive {len(tabela)}")

    posicoes = sorted([int(t["pos"]) for t in tabela])

    if posicoes != list(range(1, 21)):
        raise Exception(f"{fonte}: posições inválidas: {posicoes}")

    nomes = [t["time"] for t in tabela]

    if len(set(nomes)) != 20:
        raise Exception(f"{fonte}: há times duplicados ou nomes vazios: {nomes}")

    for t in tabela:
        campos_obrigatorios = [
            "pos", "time", "pontos", "jogos", "vitorias", "empates",
            "derrotas", "gp", "gc", "sg", "aproveitamento"
        ]

        for campo in campos_obrigatorios:
            if campo not in t:
                raise Exception(f"{fonte}: campo ausente '{campo}' em {t}")

        if not t["time"]:
            raise Exception(f"{fonte}: time vazio em {t}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    inicio = agora_brasilia()

    print("=" * 70)
    print("Atualização da tabela do Brasileirão")
    print("=" * 70)
    print(f"Início em Brasília: {inicio.strftime('%d/%m/%Y %H:%M:%S BRT')}")
    print(f"Início ISO: {inicio.isoformat()}")
    print()

    fontes = [
        ("Terra", buscar_terra),
        ("GloboEsporte", buscar_globoesporte),
    ]

    erros = []
    tabela = None
    fonte_usada = None

    for nome_fonte, funcao in fontes:
        try:
            print(f"Tentando fonte: {nome_fonte}")
            tabela = funcao()
            fonte_usada = nome_fonte
            print(f"Sucesso via {nome_fonte}: {len(tabela)} times")
            print()
            break

        except Exception as e:
            erro = f"{nome_fonte}: {type(e).__name__}: {e}"
            print(f"Falha em {erro}")
            print()
            erros.append(erro)

    if tabela is None:
        print("ERRO: todas as fontes falharam.")
        print()
        for erro in erros:
            print(f"- {erro}")
        sys.exit(1)

    fim = agora_brasilia()
    proxima = calcular_proxima_prevista(fim)

    output = {
        "atualizado_em": fim.isoformat(),
        "atualizado_em_br": fim.strftime("%d/%m/%Y %H:%M BRT"),
        "executado_em": fim.isoformat(),
        "proxima_atualizacao_prevista": proxima.isoformat(),
        "proxima_atualizacao_prevista_br": proxima.strftime("%d/%m/%Y %H:%M BRT"),
        "fonte": fonte_usada,
        "total_times": len(tabela),
        "tabela": tabela,
    }

    with open("tabela.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("tabela.json salvo com sucesso")
    print("=" * 70)
    print(f"Atualizado em: {output['atualizado_em_br']}")
    print(f"Próxima prevista: {output['proxima_atualizacao_prevista_br']}")
    print(f"Fonte usada: {fonte_usada}")
    print(f"Times: {len(tabela)}")
    print()

    print("Top 5:")
    for t in tabela[:5]:
        print(
            f"{t['pos']:>2}º {t['time']:<18} "
            f"{t['pontos']:>2} pts | J: {t['jogos']:>2} | "
            f"V: {t['vitorias']:>2} | SG: {t['sg']:>3}"
        )

    print()
    print("Concluído.")


if __name__ == "__main__":
    main()

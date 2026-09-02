# PATCH — Jogos adiados/reagendados automáticos — 02/09/2026

## Aplicação no GitHub
Suba somente estes dois arquivos, preservando os caminhos:

- `.github/workflows/HOTFIX_REAGENDADOS_20260902.yml`
- `scripts/aplicar_hotfix_reagendados_20260902.py`

Depois:
**Actions → HOTFIX · jogos reagendados automáticos → Run workflow**

O workflow altera os arquivos atuais de produção, valida tudo, remove os dois
arquivos temporários, faz commit/push e dispara automaticamente
`Atualizar Brasileirao (ESPN)` com coleta completa.

## Produção alterada
- `atualizar_espn.py`
- `js/br-aovivo.js`
- `aovivo.html`
- `dados-br/ajustes-calendario.json`

## Regra estrutural nova
- Um TBA manual antigo não pode apagar uma data nova válida da ESPN/CBF.
- Quando a CBF publica nova data, `adiado=true` e `data_definir=true` deixam de
  representar o estado atual do jogo.
- Um jogo pode ter sido historicamente reagendado sem continuar operacionalmente adiado.
- O Ao Vivo não herda mais `adiado=true` velho se a ESPN atual já apresenta
  kickoff normal.
- O override obsoleto Flamengo x Mirassol da R4 é removido.
- Regressões permanentes entram no selftest.

## Supabase
Nenhuma alteração no Supabase é necessária.

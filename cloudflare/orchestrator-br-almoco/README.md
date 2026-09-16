# Orchestrator BR Almoço 2.0.0 — Agenda/Event Driven

O Cloudflare continua com Cron a cada minuto, mas o **GitHub não é mais um cron**.
O Worker decide por evidência esportiva e mantém o sistema em `SLEEP` quando nada
pode ter mudado.

## Objetivo da 2.0

Eliminar a tempestade de `Atualizar Brasileirao (ESPN)` causada por idade de
snapshot, fonte preservada ou jogos adiados/TBA. Idade, sozinha, nunca mais gera
workflow pesado.

## Estados operacionais

- `sleep`: nenhum evento esportivo próximo; GitHub pesado fica zerado.
- `calendar_watch`: há adiado/TBA; Cloudflare audita ESPN de forma barata.
- `source_degraded`: último snapshot foi preservado; Cloudflare testa recuperação
  sem gastar Action.
- `pre_game`: T-6h até T-60min; agenda é confirmada em intervalos moderados.
- `near_game`: última hora; probes baratos ficam mais frequentes.
- `game_window`: jogo começou, mas ainda não chegou à janela provável de FINAL.
- `final_watch`: T+88min em diante; FINAL é acompanhado agressivamente.

## Quando o GitHub pode acordar

`Atualizar Brasileirao (ESPN)` só é elegível quando existir pelo menos um sinal
objetivo:

1. FINAL confirmado e ainda ausente em `resultados.json`;
2. safety trigger temporal de FINAL;
3. mudança real de data/horário detectada no `event_id` ESPN;
4. fonte anteriormente preservada voltou a responder ao probe Cloudflare;
5. auditoria geral crítica com fonte disponível;
6. AF realmente divergente dos resultados.

O snapshot estar velho **não é sinal**.

## Agenda inteligente

Fora de jogo, o Worker consulta `summary?event=<id>` apenas em janelas de agenda.
Ele compara o kickoff remoto com `calendario-completo.json`. Jogos adiados/TBA e
partidas dos próximos 14 dias são auditados sem disparar GitHub. Só uma mudança
objetiva cria um sinal `MAIN`.

A CBF continua integrada no coletor Python oficial. Quando um `MAIN` realmente é
necessário, `atualizar_espn.py` faz a reconciliação ESPN → CBF já existente.

## Anti-loop por assinatura

Mudança de agenda e recuperação de fonte ganham uma assinatura persistente. O
mesmo sinal não pode gerar workflows em sequência. Recuperação de fonte usa
backoff de 6 horas; um FINAL novo continua tendo prioridade e pode disparar
imediatamente.

## Coleta automática incremental

FINAL, MAIN e MAIN_AF agora chamam:

```text
coleta_completa=false
```

A varredura completa continua disponível para manutenção/manual, mas deixou de
ser custo obrigatório de cada evento.

## ESPN adaptativa

O coletor inicia o scoreboard em blocos de 14 dias. Se a ESPN responder erro a
um range, divide automaticamente a faixa até consulta diária:

```text
14 dias → 7 → 3/4 → 1 dia
```

Isso cobre a mudança observada em 16/09/2026, quando uma faixa extensa passou a
retornar HTTP 400. Se até a consulta diária falhar, o mecanismo transacional já
existente preserva o último snapshot íntegro.

## FINAL

A lógica rápida permanece independente do slow path:

```text
T+88 → scoreboard ESPN por dia
      → summary por event_id como fallback
      → FINAL → Atualizar Brasileirão incremental

T+110 sem convergência
      → safety trigger
      → Atualizar Brasileirão incremental + event_ids
```

AO VIVO, públicos, melhores momentos, elencos e fair play continuam fora do
escopo do orquestrador.

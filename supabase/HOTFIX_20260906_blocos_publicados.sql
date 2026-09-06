-- HOTFIX 2026-09-06 — blocos 3 rodadas / configs já publicadas
--
-- Corrige a incompatibilidade entre:
--   * Execução 18: trigger exige que br_config_rodadas acompanhe a janela atual do bloco;
--   * Execução 21: RPC preserva abre_em/fecha_em de rodadas já publicada/apurada.
--
-- Resultado anterior: br_pipeline_sincronizar_blocos_v1 abortava com P0001
-- "A janela da rodada 21 é controlada pelo bloco 21–23...".
--
-- Este hotfix NÃO altera palpites, resultados, ranking ou composição dos blocos.
-- Apenas permite que uma rodada histórica já publicada/apurada preserve sua
-- janela original, mantendo a validação de temporada/rodada/bloco.

create or replace function public.br_validar_config_rodada_bloco_v1()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_bloco public.br_blocos_apostas%rowtype;
begin
  if new.bloco_id is null then
    return new;
  end if;

  select b.* into v_bloco
  from public.br_blocos_apostas b
  where b.id = new.bloco_id;

  if v_bloco.id is null then
    raise exception 'Bloco de apostas inexistente.';
  end if;

  if new.temporada <> v_bloco.temporada
     or new.rodada < v_bloco.rodada_inicio
     or new.rodada > v_bloco.rodada_fim then
    raise exception 'A rodada % não pertence ao bloco %–%.', new.rodada, v_bloco.rodada_inicio, v_bloco.rodada_fim;
  end if;

  -- Rodadas já publicadas/apuradas são histórico imutável. A RPC nova preserva
  -- intencionalmente a janela original delas, mesmo se o bloco tiver sido
  -- recalculado depois.
  if new.status in ('publicada','apurada') then
    return new;
  end if;

  if v_bloco.abre_em is null or v_bloco.fecha_em is null then
    raise exception 'O bloco %–% ainda não possui janela configurada.', v_bloco.rodada_inicio, v_bloco.rodada_fim;
  end if;

  if new.abre_em is distinct from v_bloco.abre_em
     or new.fecha_em is distinct from v_bloco.fecha_em then
    raise exception 'A janela da rodada % é controlada pelo bloco %–%. Atualize o bloco, não a rodada isolada.',
      new.rodada, v_bloco.rodada_inicio, v_bloco.rodada_fim;
  end if;

  return new;
end;
$$;

-- Smoke-check estrutural: a trigger deve continuar vinculada à função corrigida.
do $$
begin
  if not exists (
    select 1
    from pg_trigger t
    join pg_proc p on p.oid = t.tgfoid
    where t.tgrelid = 'public.br_config_rodadas'::regclass
      and t.tgname = 'br_config_rodadas_validar_bloco_v1'
      and p.proname = 'br_validar_config_rodada_bloco_v1'
      and not t.tgisinternal
  ) then
    raise exception 'Trigger br_config_rodadas_validar_bloco_v1 não encontrada após hotfix.';
  end if;
end;
$$;

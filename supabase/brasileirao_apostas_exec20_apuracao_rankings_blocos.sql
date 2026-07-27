-- ============================================================================
-- Supabase — Bolão Brasileirão 2026
-- Execução 4: apuração parcial, rankings e finalização automática
--
-- Pré-requisitos:
--   supabase/brasileirao_apostas_exec18_blocos_3_rodadas.sql
--   supabase/brasileirao_apostas_exec19_apostas_blocos_30_partidas.sql
--
-- Esta migração é idempotente e:
-- 1) preserva os palpites, comprovantes e o fluxo legado da Rodada 20;
-- 2) publica automaticamente as rodadas vinculadas a bloco no fechamento;
-- 3) registra progresso de apuração por rodada e por bloco;
-- 4) permite ao pipeline marcar uma rodada como apurada somente quando todos
--    os resultados auditados estiverem presentes;
-- 5) mantém uma trilha técnica de cada execução do pipeline;
-- 6) cria RPCs v2/v3 sem remover as versões anteriores.
-- ============================================================================

begin;

create schema if not exists extensions;
create extension if not exists pgcrypto;

-- --------------------------------------------------------------------------
-- 1. Estado materializado da apuração
-- --------------------------------------------------------------------------

alter table public.br_config_rodadas
  add column if not exists jogos_apurados int not null default 0,
  add column if not exists apuracao_concluida boolean not null default false,
  add column if not exists apurado_em timestamptz,
  add column if not exists apuracao_atualizada_em timestamptz;

alter table public.br_blocos_apostas
  add column if not exists jogos_apurados int not null default 0,
  add column if not exists apuracao_concluida boolean not null default false,
  add column if not exists apurado_em timestamptz,
  add column if not exists apuracao_atualizada_em timestamptz;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'br_config_rodadas_jogos_apurados_chk'
      and conrelid = 'public.br_config_rodadas'::regclass
  ) then
    alter table public.br_config_rodadas
      add constraint br_config_rodadas_jogos_apurados_chk
      check (jogos_apurados between 0 and 10);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'br_blocos_apostas_jogos_apurados_chk'
      and conrelid = 'public.br_blocos_apostas'::regclass
  ) then
    alter table public.br_blocos_apostas
      add constraint br_blocos_apostas_jogos_apurados_chk
      check (jogos_apurados between 0 and 30);
  end if;
end;
$$;

create table if not exists public.br_apuracao_execucoes (
  id uuid primary key default gen_random_uuid(),
  temporada int not null,
  payload_hash text not null,
  rodadas_atualizadas int not null default 0,
  blocos_atualizados int not null default 0,
  resumo jsonb not null default '{}'::jsonb,
  criado_em timestamptz not null default now(),
  constraint br_apuracao_execucoes_hash_chk check (length(payload_hash) between 32 and 128)
);

create index if not exists br_apuracao_execucoes_temporada_idx
  on public.br_apuracao_execucoes (temporada, criado_em desc);

alter table public.br_apuracao_execucoes enable row level security;

-- --------------------------------------------------------------------------
-- 2. Publicação automática dos blocos no exato fechamento
-- --------------------------------------------------------------------------

-- A publicação automática vale apenas para rodadas vinculadas aos blocos.
-- A Rodada 20 continua obedecendo sua configuração antiga.
update public.br_config_rodadas
set publica_em = fecha_em,
    atualizado_em = now()
where bloco_id is not null
  and publica_em is null
  and fecha_em is not null;

create or replace function public.br_definir_publicacao_automatica_bloco_v1()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.bloco_id is not null and new.fecha_em is not null and new.publica_em is null then
    new.publica_em := new.fecha_em;
  end if;
  return new;
end;
$$;

drop trigger if exists br_config_rodadas_publicacao_automatica_bloco_v1
  on public.br_config_rodadas;
create trigger br_config_rodadas_publicacao_automatica_bloco_v1
before insert or update of bloco_id, fecha_em, publica_em
on public.br_config_rodadas
for each row execute function public.br_definir_publicacao_automatica_bloco_v1();

-- --------------------------------------------------------------------------
-- 3. Sincronização segura pelo workflow
-- --------------------------------------------------------------------------

create or replace function public.br_pipeline_sincronizar_apuracao_v1(
  p_temporada int,
  p_payload_hash text,
  p_rodadas jsonb,
  p_blocos jsonb,
  p_resumo jsonb default '{}'::jsonb
)
returns table (
  rodadas_atualizadas int,
  blocos_atualizados int,
  rodadas_concluidas int,
  blocos_concluidos int,
  registrado_em timestamptz
)
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_item jsonb;
  v_rodada int;
  v_inicio int;
  v_fim int;
  v_apurados int;
  v_total int;
  v_concluida boolean;
  v_publicada boolean;
  v_rodadas_atualizadas int := 0;
  v_blocos_atualizados int := 0;
  v_rodadas_concluidas int := 0;
  v_blocos_concluidos int := 0;
  v_agora timestamptz := now();
begin
  if p_temporada is null or p_temporada < 2020 then
    raise exception 'Temporada inválida.';
  end if;
  if nullif(trim(coalesce(p_payload_hash, '')), '') is null then
    raise exception 'Hash da apuração obrigatório.';
  end if;
  if jsonb_typeof(p_rodadas) <> 'array' or jsonb_typeof(p_blocos) <> 'array' then
    raise exception 'Resumo de rodadas/blocos inválido.';
  end if;

  for v_item in select * from jsonb_array_elements(p_rodadas)
  loop
    begin
      v_rodada := (v_item->>'rodada')::int;
      v_apurados := greatest(0, least(10, coalesce((v_item->>'jogos_apurados')::int, 0)));
      v_total := greatest(0, least(10, coalesce((v_item->>'total_jogos')::int, 0)));
      v_concluida := coalesce((v_item->>'concluida')::boolean, false)
                     and v_total = 10 and v_apurados = 10;
      v_publicada := coalesce((v_item->>'publicada')::boolean, false);
    exception when others then
      raise exception 'Resumo inválido de rodada: %', v_item;
    end;

    if v_rodada between 1 and 38 then
      update public.br_config_rodadas c
      set jogos_apurados = v_apurados,
          apuracao_concluida = v_concluida,
          apuracao_atualizada_em = v_agora,
          apurado_em = case
            when v_concluida then coalesce(c.apurado_em, v_agora)
            else null
          end,
          status = case
            when v_concluida and v_publicada then 'apurada'
            when v_publicada and c.status not in ('apurada','bloqueada') then 'publicada'
            else c.status
          end,
          atualizado_em = now()
      where c.temporada = p_temporada
        and c.rodada = v_rodada;

      if found then
        v_rodadas_atualizadas := v_rodadas_atualizadas + 1;
        if v_concluida then v_rodadas_concluidas := v_rodadas_concluidas + 1; end if;
      end if;
    end if;
  end loop;

  for v_item in select * from jsonb_array_elements(p_blocos)
  loop
    begin
      v_inicio := (v_item->>'rodada_inicio')::int;
      v_fim := (v_item->>'rodada_fim')::int;
      v_apurados := greatest(0, least(30, coalesce((v_item->>'jogos_apurados')::int, 0)));
      v_concluida := coalesce((v_item->>'concluido')::boolean, false)
                     and v_apurados = 30;
    exception when others then
      raise exception 'Resumo inválido de bloco: %', v_item;
    end;

    update public.br_blocos_apostas b
    set jogos_apurados = v_apurados,
        apuracao_concluida = v_concluida,
        apuracao_atualizada_em = v_agora,
        apurado_em = case
          when v_concluida then coalesce(b.apurado_em, v_agora)
          else null
        end,
        atualizado_em = now()
    where b.temporada = p_temporada
      and b.rodada_inicio = v_inicio
      and b.rodada_fim = v_fim;

    if found then
      v_blocos_atualizados := v_blocos_atualizados + 1;
      if v_concluida then v_blocos_concluidos := v_blocos_concluidos + 1; end if;
    end if;
  end loop;

  insert into public.br_apuracao_execucoes
    (temporada, payload_hash, rodadas_atualizadas, blocos_atualizados, resumo)
  values
    (p_temporada, p_payload_hash, v_rodadas_atualizadas,
     v_blocos_atualizados, coalesce(p_resumo, '{}'::jsonb));

  return query select v_rodadas_atualizadas, v_blocos_atualizados,
    v_rodadas_concluidas, v_blocos_concluidos, v_agora;
end;
$$;

revoke all on function public.br_pipeline_sincronizar_apuracao_v1(int,text,jsonb,jsonb,jsonb) from public;
revoke all on function public.br_pipeline_sincronizar_apuracao_v1(int,text,jsonb,jsonb,jsonb) from anon;
revoke all on function public.br_pipeline_sincronizar_apuracao_v1(int,text,jsonb,jsonb,jsonb) from authenticated;
grant execute on function public.br_pipeline_sincronizar_apuracao_v1(int,text,jsonb,jsonb,jsonb) to service_role;

-- --------------------------------------------------------------------------
-- 4. RPCs de leitura versionadas
-- --------------------------------------------------------------------------

create or replace function public.br_listar_config_rodadas_v3(
  p_temporada int default 2026
)
returns table (
  temporada int,
  rodada int,
  abre_em timestamptz,
  fecha_em timestamptz,
  publica_em timestamptz,
  status text,
  observacao text,
  total_jogos int,
  jogos_apurados int,
  apuracao_concluida boolean,
  apurado_em timestamptz,
  apuracao_atualizada_em timestamptz,
  atualizado_em timestamptz,
  bloco_id uuid,
  bloco_nome text,
  bloco_rodada_inicio int,
  bloco_rodada_fim int,
  bloco_primeiro_jogo_em timestamptz,
  bloco_versao bigint
)
language sql
security definer
set search_path = public
as $$
  select
    c.temporada, c.rodada, c.abre_em, c.fecha_em,
    coalesce(c.publica_em, case when c.bloco_id is not null then c.fecha_em end),
    c.status, c.observacao, c.total_jogos, c.jogos_apurados,
    c.apuracao_concluida, c.apurado_em, c.apuracao_atualizada_em,
    c.atualizado_em, c.bloco_id, b.nome, b.rodada_inicio, b.rodada_fim,
    b.primeiro_jogo_em, b.versao
  from public.br_config_rodadas c
  left join public.br_blocos_apostas b on b.id = c.bloco_id
  where c.temporada = p_temporada
  order by c.rodada;
$$;

revoke all on function public.br_listar_config_rodadas_v3(int) from public;
grant execute on function public.br_listar_config_rodadas_v3(int) to anon;

create or replace function public.br_admin_listar_blocos_apostas_v2(
  p_admin_id uuid,
  p_token text,
  p_temporada int default 2026
)
returns table (
  bloco_id uuid,
  temporada int,
  rodada_inicio int,
  rodada_fim int,
  nome text,
  primeiro_jogo_em timestamptz,
  fechamento_recomendado_em timestamptz,
  abre_em timestamptz,
  fecha_em timestamptz,
  status text,
  observacao text,
  versao bigint,
  rodadas_configuradas int,
  total_palpites bigint,
  fechamento_conforme_recomendacao boolean,
  jogos_apurados int,
  apuracao_concluida boolean,
  apurado_em timestamptz,
  apuracao_atualizada_em timestamptz,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.br_validar_sessao(p_admin_id, p_token, true) then
    raise exception 'Acesso admin inválido.';
  end if;

  return query
  select
    b.id, b.temporada, b.rodada_inicio, b.rodada_fim, b.nome,
    b.primeiro_jogo_em,
    public.br_recomendar_fechamento_bloco_v1(b.primeiro_jogo_em),
    b.abre_em, b.fecha_em, b.status, b.observacao, b.versao,
    (select count(*)::int from public.br_config_rodadas c where c.bloco_id = b.id),
    (select count(*)::bigint from public.br_palpites p
      where p.bloco_id = b.id or (
        p.bloco_id is null and p.temporada = b.temporada
        and p.rodada between b.rodada_inicio and b.rodada_fim
      )),
    case when b.primeiro_jogo_em is null or b.fecha_em is null then false
      else b.fecha_em = public.br_recomendar_fechamento_bloco_v1(b.primeiro_jogo_em)
    end,
    b.jogos_apurados, b.apuracao_concluida, b.apurado_em,
    b.apuracao_atualizada_em, b.atualizado_em
  from public.br_blocos_apostas b
  where b.temporada = p_temporada
  order by b.rodada_inicio;
end;
$$;

revoke all on function public.br_admin_listar_blocos_apostas_v2(uuid,text,int) from public;
grant execute on function public.br_admin_listar_blocos_apostas_v2(uuid,text,int) to anon;

commit;

-- Validações sugeridas:
-- 1) A Rodada 20 continua sem bloco e não teve palpites alterados.
-- select rodada, bloco_id, count(*) from public.br_palpites
-- where temporada = 2026 and rodada = 20 group by rodada, bloco_id;
--
-- 2) Rodadas de bloco passam a publicar automaticamente no fechamento.
-- select rodada, fecha_em, publica_em from public.br_config_rodadas
-- where temporada = 2026 and bloco_id is not null order by rodada;
--
-- 3) O workflow registrará cada sincronização em br_apuracao_execucoes.

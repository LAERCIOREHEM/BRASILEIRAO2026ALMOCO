-- ============================================================================
-- Supabase — Bolão Brasileirão 2026
-- Execução 3: apostas progressivas dos blocos de 30 partidas
--
-- Pré-requisito: executar antes
--   supabase/brasileirao_apostas_exec18_blocos_3_rodadas.sql
--
-- Esta migração:
-- 1) preserva integralmente a Rodada 20 e as RPCs antigas por rodada;
-- 2) cria comprovante único por bloco, calculado sobre TODOS os palpites
--    persistidos do participante no bloco;
-- 3) permite salvamento progressivo (1 a 30 partidas, sem apagar as omitidas);
-- 4) oferece consulta dos próprios palpites, progresso e palpites públicos por
--    bloco/rodada, respeitando publicação e ligas;
-- 5) é idempotente e não realiza backfill destrutivo.
-- ============================================================================

begin;

create schema if not exists extensions;
create extension if not exists pgcrypto;

-- Hash específico do conjunto do bloco. O hash_fechamento legado permanece
-- disponível para a Rodada 20 e para integrações antigas.
alter table public.br_palpites
  add column if not exists hash_bloco text;

create table if not exists public.br_comprovantes_blocos (
  id uuid primary key default gen_random_uuid(),
  temporada int not null default 2026,
  bloco_id uuid not null references public.br_blocos_apostas(id) on delete restrict,
  participante_id uuid not null references public.br_participantes(id) on delete cascade,
  total_palpites int not null default 0,
  total_jogos int not null default 30,
  hash_bloco text not null,
  payload_hash text not null,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint br_comprovantes_blocos_total_chk check (
    total_palpites between 0 and 30 and total_jogos = 30
  ),
  constraint br_comprovantes_blocos_unico unique (temporada, bloco_id, participante_id)
);

create index if not exists br_comprovantes_blocos_participante_idx
  on public.br_comprovantes_blocos (participante_id, temporada, atualizado_em desc);

alter table public.br_comprovantes_blocos enable row level security;

drop trigger if exists br_comprovantes_blocos_set_atualizado_em on public.br_comprovantes_blocos;
create trigger br_comprovantes_blocos_set_atualizado_em
before update on public.br_comprovantes_blocos
for each row execute function public.br_set_atualizado_em();

-- --------------------------------------------------------------------------
-- Salvar progressivamente um bloco. Itens não enviados NÃO são apagados.
-- O hash final é recalculado sobre o conjunto completo persistido.
-- --------------------------------------------------------------------------
create or replace function public.br_salvar_palpites_bloco_v1(
  p_participante_id uuid,
  p_token text,
  p_temporada int,
  p_bloco_id uuid,
  p_palpites jsonb
)
returns table (
  bloco_id uuid,
  rodada_inicio int,
  rodada_fim int,
  total_palpites int,
  total_jogos int,
  faltantes int,
  completo boolean,
  hash_bloco text,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_part public.br_participantes%rowtype;
  v_bloco public.br_blocos_apostas%rowtype;
  v_item jsonb;
  v_rodada int;
  v_event_id text;
  v_pm int;
  v_pv int;
  v_payload_hash text;
  v_hash text;
  v_total int;
  v_antigo jsonb;
  v_agora timestamptz := now();
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;

  select p.* into v_part
  from public.br_participantes p
  where p.id = p_participante_id and p.ativo = true;
  if v_part.id is null then
    raise exception 'Participante inválido.';
  end if;

  select b.* into v_bloco
  from public.br_blocos_apostas b
  where b.id = p_bloco_id and b.temporada = p_temporada
  for update;
  if v_bloco.id is null then
    raise exception 'Bloco de apostas não encontrado.';
  end if;

  if v_bloco.abre_em is null or v_bloco.fecha_em is null then
    raise exception 'O bloco ainda não possui janela configurada.';
  end if;
  if v_bloco.status not in ('programada','aberta') then
    raise exception 'Bloco fora da janela de apostas.';
  end if;
  if v_agora < v_bloco.abre_em or v_agora >= v_bloco.fecha_em then
    raise exception 'Bloco fora da janela de apostas.';
  end if;

  if jsonb_typeof(p_palpites) <> 'array' then
    raise exception 'Payload inválido.';
  end if;
  if jsonb_array_length(p_palpites) < 1 or jsonb_array_length(p_palpites) > 30 then
    raise exception 'Envie entre 1 e 30 palpites por salvamento.';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(p_palpites) x
    group by x->>'event_id'
    having count(*) > 1
  ) then
    raise exception 'O envio contém jogo duplicado.';
  end if;

  v_payload_hash := encode(digest(
    p_temporada::text || '|' || p_bloco_id::text || '|' ||
    p_participante_id::text || '|' || p_palpites::text,
    'sha256'
  ), 'hex');

  for v_item in select * from jsonb_array_elements(p_palpites)
  loop
    v_event_id := trim(coalesce(v_item->>'event_id', ''));
    if v_event_id = '' then raise exception 'Jogo sem event_id.'; end if;

    begin
      v_rodada := (v_item->>'rodada')::int;
      v_pm := (v_item->>'placar_mandante')::int;
      v_pv := (v_item->>'placar_visitante')::int;
    exception when others then
      raise exception 'Rodada ou placar inválido no jogo %.', v_event_id;
    end;

    if v_rodada < v_bloco.rodada_inicio or v_rodada > v_bloco.rodada_fim then
      raise exception 'A rodada % não pertence ao bloco %–%.',
        v_rodada, v_bloco.rodada_inicio, v_bloco.rodada_fim;
    end if;
    if v_pm < 0 or v_pv < 0 or v_pm > 30 or v_pv > 30 then
      raise exception 'Placar inválido no jogo %.', v_event_id;
    end if;

    select to_jsonb(p.*) into v_antigo
    from public.br_palpites p
    where p.temporada = p_temporada
      and p.rodada = v_rodada
      and p.event_id = v_event_id
      and p.participante_id = p_participante_id;

    insert into public.br_palpites (
      temporada, rodada, event_id, jogo_chave, bloco_id, participante_id,
      membro, mandante, visitante, placar_mandante, placar_visitante,
      kickoff, fecha_em, origem, hash_fechamento, hash_bloco, versao
    ) values (
      p_temporada, v_rodada, v_event_id, v_item->>'jogo_chave', v_bloco.id,
      p_participante_id, v_part.nome, v_item->>'mandante', v_item->>'visitante',
      v_pm, v_pv, nullif(v_item->>'kickoff','')::timestamptz,
      v_bloco.fecha_em, 'site-logado-bloco-v1', v_payload_hash, null, 3
    )
    on conflict (temporada, rodada, event_id, participante_id)
      where participante_id is not null
    do update set
      jogo_chave = excluded.jogo_chave,
      bloco_id = excluded.bloco_id,
      membro = excluded.membro,
      mandante = excluded.mandante,
      visitante = excluded.visitante,
      placar_mandante = excluded.placar_mandante,
      placar_visitante = excluded.placar_visitante,
      kickoff = excluded.kickoff,
      fecha_em = excluded.fecha_em,
      origem = excluded.origem,
      hash_fechamento = excluded.hash_fechamento,
      versao = excluded.versao;

    insert into public.br_palpites_auditoria
      (temporada, rodada, event_id, participante_id, membro, acao,
       antes, depois, hash_fechamento)
    values
      (p_temporada, v_rodada, v_event_id, p_participante_id, v_part.nome,
       case when v_antigo is null then 'insert_bloco' else 'update_bloco' end,
       v_antigo, v_item, v_payload_hash);
  end loop;

  -- Limites estruturais: no máximo 10 jogos por rodada e 30 por bloco.
  if exists (
    select 1
    from public.br_palpites p
    where p.participante_id = p_participante_id
      and p.temporada = p_temporada
      and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    group by p.rodada
    having count(*) > 10
  ) then
    raise exception 'Há mais de 10 palpites em uma rodada do bloco.';
  end if;

  select count(*)::int into v_total
  from public.br_palpites p
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim;
  if v_total > 30 then
    raise exception 'O bloco possui mais de 30 palpites.';
  end if;

  select encode(digest(
    p_temporada::text || '|' || v_bloco.rodada_inicio::text || '-' ||
    v_bloco.rodada_fim::text || '|' || p_participante_id::text || '|' ||
    coalesce(string_agg(
      p.rodada::text || '|' || p.event_id || '|' ||
      p.placar_mandante::text || '|' || p.placar_visitante::text,
      E'\n' order by p.rodada, p.kickoff nulls last, p.event_id
    ), ''),
    'sha256'
  ), 'hex') into v_hash
  from public.br_palpites p
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim;

  update public.br_palpites p
  set bloco_id = v_bloco.id,
      hash_bloco = v_hash,
      hash_fechamento = v_hash,
      fecha_em = v_bloco.fecha_em,
      versao = greatest(coalesce(p.versao, 2), 3)
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    and (p.bloco_id is distinct from v_bloco.id
      or p.hash_bloco is distinct from v_hash
      or p.hash_fechamento is distinct from v_hash
      or p.fecha_em is distinct from v_bloco.fecha_em
      or p.versao < 3);

  insert into public.br_comprovantes_blocos
    (temporada, bloco_id, participante_id, total_palpites, total_jogos,
     hash_bloco, payload_hash)
  values
    (p_temporada, v_bloco.id, p_participante_id, v_total, 30,
     v_hash, v_payload_hash)
  on conflict (temporada, bloco_id, participante_id)
  do update set
    total_palpites = excluded.total_palpites,
    total_jogos = 30,
    hash_bloco = excluded.hash_bloco,
    payload_hash = excluded.payload_hash,
    atualizado_em = now();

  return query
  select v_bloco.id, v_bloco.rodada_inicio, v_bloco.rodada_fim,
         v_total, 30, 30 - v_total, v_total = 30, v_hash, now();
end;
$$;

revoke all on function public.br_salvar_palpites_bloco_v1(uuid,text,int,uuid,jsonb) from public;
grant execute on function public.br_salvar_palpites_bloco_v1(uuid,text,int,uuid,jsonb) to anon;

-- --------------------------------------------------------------------------
-- Próprios palpites do bloco.
-- --------------------------------------------------------------------------
create or replace function public.br_listar_meus_palpites_bloco_v1(
  p_participante_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_temporada int default 2026
)
returns table (
  id uuid, temporada int, bloco_id uuid, rodada int, event_id text,
  jogo_chave text, membro text, mandante text, visitante text,
  placar_mandante int, placar_visitante int, kickoff timestamptz,
  fecha_em timestamptz, hash_bloco text, criado_em timestamptz,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_bloco public.br_blocos_apostas%rowtype;
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;

  select b.* into v_bloco
  from public.br_blocos_apostas b
  where b.id = p_bloco_id and b.temporada = p_temporada;
  if v_bloco.id is null then raise exception 'Bloco não encontrado.'; end if;

  return query
  select p.id, p.temporada, v_bloco.id, p.rodada, p.event_id,
         p.jogo_chave, p.membro, p.mandante, p.visitante,
         p.placar_mandante, p.placar_visitante, p.kickoff,
         p.fecha_em, coalesce(p.hash_bloco, cb.hash_bloco),
         p.criado_em, p.atualizado_em
  from public.br_palpites p
  left join public.br_comprovantes_blocos cb
    on cb.temporada = p.temporada
   and cb.bloco_id = v_bloco.id
   and cb.participante_id = p.participante_id
  where p.temporada = p_temporada
    and p.participante_id = p_participante_id
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
  order by p.rodada, p.kickoff nulls last, p.mandante;
end;
$$;

revoke all on function public.br_listar_meus_palpites_bloco_v1(uuid,text,uuid,int) from public;
grant execute on function public.br_listar_meus_palpites_bloco_v1(uuid,text,uuid,int) to anon;

create or replace function public.br_listar_comprovante_bloco_v1(
  p_participante_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_temporada int default 2026
)
returns table (
  comprovante_id uuid, bloco_id uuid, nome text,
  rodada_inicio int, rodada_fim int, total_palpites int,
  total_jogos int, faltantes int, completo boolean,
  hash_bloco text, criado_em timestamptz, atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;

  return query
  select cb.id, b.id, b.nome, b.rodada_inicio, b.rodada_fim,
         cb.total_palpites, cb.total_jogos,
         greatest(cb.total_jogos - cb.total_palpites, 0),
         cb.total_palpites = cb.total_jogos,
         cb.hash_bloco, cb.criado_em, cb.atualizado_em
  from public.br_comprovantes_blocos cb
  join public.br_blocos_apostas b on b.id = cb.bloco_id
  where cb.temporada = p_temporada
    and cb.bloco_id = p_bloco_id
    and cb.participante_id = p_participante_id;
end;
$$;

revoke all on function public.br_listar_comprovante_bloco_v1(uuid,text,uuid,int) from public;
grant execute on function public.br_listar_comprovante_bloco_v1(uuid,text,uuid,int) to anon;

create or replace function public.br_progresso_bloco_v1(
  p_participante_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_temporada int default 2026
)
returns table (
  bloco_id uuid, rodada_inicio int, rodada_fim int,
  total_palpites int, total_jogos int, faltantes int,
  percentual numeric, completo boolean, hash_bloco text,
  atualizado_em timestamptz, progresso_rodadas jsonb
)
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_bloco public.br_blocos_apostas%rowtype;
  v_total int;
  v_hash text;
  v_atualizado timestamptz;
  v_por_rodada jsonb;
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;

  select b.* into v_bloco from public.br_blocos_apostas b
  where b.id = p_bloco_id and b.temporada = p_temporada;
  if v_bloco.id is null then raise exception 'Bloco não encontrado.'; end if;

  select count(*)::int, max(p.atualizado_em)
    into v_total, v_atualizado
  from public.br_palpites p
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim;

  select cb.hash_bloco, cb.atualizado_em
    into v_hash, v_atualizado
  from public.br_comprovantes_blocos cb
  where cb.temporada = p_temporada
    and cb.bloco_id = p_bloco_id
    and cb.participante_id = p_participante_id;

  -- SELECT INTO sem linha atribui nulos. Se ainda não há comprovante, conserva
  -- o instante da última gravação individual calculado acima.
  if not found then
    select max(p.atualizado_em) into v_atualizado
    from public.br_palpites p
    where p.participante_id = p_participante_id
      and p.temporada = p_temporada
      and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim;
  end if;

  select jsonb_agg(jsonb_build_object(
           'rodada', gs.r,
           'salvos', coalesce(x.total, 0),
           'total', 10,
           'faltantes', 10 - coalesce(x.total, 0)
         ) order by gs.r)
    into v_por_rodada
  from generate_series(v_bloco.rodada_inicio, v_bloco.rodada_fim) gs(r)
  left join (
    select p.rodada, count(*)::int total
    from public.br_palpites p
    where p.participante_id = p_participante_id
      and p.temporada = p_temporada
      and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    group by p.rodada
  ) x on x.rodada = gs.r;

  return query select v_bloco.id, v_bloco.rodada_inicio, v_bloco.rodada_fim,
    coalesce(v_total, 0), 30, 30 - coalesce(v_total, 0),
    round((coalesce(v_total, 0)::numeric / 30::numeric) * 100, 1),
    coalesce(v_total, 0) = 30, v_hash, v_atualizado,
    coalesce(v_por_rodada, '[]'::jsonb);
end;
$$;

revoke all on function public.br_progresso_bloco_v1(uuid,text,uuid,int) from public;
grant execute on function public.br_progresso_bloco_v1(uuid,text,uuid,int) to anon;

-- --------------------------------------------------------------------------
-- Palpites públicos do bloco. Cada rodada só é retornada quando sua própria
-- configuração já estiver publicada/apurada ou tiver alcançado publica_em.
-- p_liga_id nulo representa a visão geral; com liga, exige associação ativa.
-- --------------------------------------------------------------------------
create or replace function public.br_listar_palpites_publicos_bloco_v1(
  p_participante_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_liga_id uuid default null,
  p_temporada int default 2026
)
returns table (
  participante_id uuid, membro text, rodada int, event_id text,
  mandante text, visitante text, placar_mandante int,
  placar_visitante int, hash_bloco text, criado_em timestamptz,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_bloco public.br_blocos_apostas%rowtype;
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;
  if p_liga_id is not null
     and not public.br_pode_ver_liga(p_participante_id, p_liga_id) then
    raise exception 'Você não tem acesso a esta liga.';
  end if;

  select b.* into v_bloco from public.br_blocos_apostas b
  where b.id = p_bloco_id and b.temporada = p_temporada;
  if v_bloco.id is null then raise exception 'Bloco não encontrado.'; end if;

  return query
  select p.participante_id, p.membro, p.rodada, p.event_id,
         p.mandante, p.visitante, p.placar_mandante,
         p.placar_visitante, coalesce(p.hash_bloco, cb.hash_bloco),
         p.criado_em, p.atualizado_em
  from public.br_palpites p
  join public.br_participantes bp
    on bp.id = p.participante_id and bp.ativo = true
  join public.br_config_rodadas c
    on c.temporada = p.temporada and c.rodada = p.rodada
   and (c.status in ('publicada','apurada')
        or (c.publica_em is not null and now() >= c.publica_em))
  left join public.br_comprovantes_blocos cb
    on cb.temporada = p.temporada
   and cb.bloco_id = v_bloco.id
   and cb.participante_id = p.participante_id
  left join public.br_liga_participantes lp
    on lp.participante_id = p.participante_id
   and lp.liga_id = p_liga_id
   and lp.ativo = true
  where p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    and (p_liga_id is null or lp.id is not null)
  order by p.rodada, p.membro, p.kickoff nulls last, p.mandante;
end;
$$;

revoke all on function public.br_listar_palpites_publicos_bloco_v1(uuid,text,uuid,uuid,int) from public;
grant execute on function public.br_listar_palpites_publicos_bloco_v1(uuid,text,uuid,uuid,int) to anon;

commit;

-- Validações sugeridas:
-- 1) Rodada 20 continua sem bloco e sem hash_bloco obrigatório.
-- select rodada, bloco_id, count(*) from public.br_palpites
-- where temporada = 2026 and rodada = 20 group by rodada, bloco_id;
--
-- 2) A tabela de comprovantes inicia vazia e recebe uma linha por participante/bloco.
-- select * from public.br_comprovantes_blocos order by atualizado_em desc;

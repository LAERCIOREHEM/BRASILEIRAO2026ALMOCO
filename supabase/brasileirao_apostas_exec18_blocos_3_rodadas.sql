-- ============================================================================
-- Supabase — Bolão Brasileirão 2026
-- Execução 2 (infraestrutura): blocos de três rodadas
--
-- Objetivos desta migração:
-- 1) preservar integralmente a Rodada 20 e todos os dados já gravados;
-- 2) criar os blocos 21–23, 24–26, 27–29, 30–32, 33–35 e 36–38;
-- 3) permitir uma única janela de apostas por bloco;
-- 4) recomendar o fechamento exatamente 1 hora antes do primeiro jogo;
-- 5) usar versionamento otimista e trilha de auditoria para impedir alterações
--    silenciosas;
-- 6) manter compatibilidade com as RPCs e a interface da Execução 1.
--
-- Como aplicar:
-- Supabase Dashboard > SQL Editor > New query > cole o arquivo inteiro > Run.
-- O script é idempotente: pode ser executado novamente sem recriar blocos nem
-- sobrescrever configurações já salvas.
-- ============================================================================

begin;

create extension if not exists pgcrypto;

-- --------------------------------------------------------------------------
-- 1. Estrutura dos blocos
-- --------------------------------------------------------------------------

create table if not exists public.br_blocos_apostas (
  id uuid primary key default gen_random_uuid(),
  temporada int not null default 2026,
  rodada_inicio int not null,
  rodada_fim int not null,
  nome text not null,
  primeiro_jogo_em timestamptz,
  abre_em timestamptz,
  fecha_em timestamptz,
  status text not null default 'futura',
  observacao text,
  versao bigint not null default 1,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint br_blocos_apostas_intervalo_chk check (
    rodada_inicio between 21 and 36
    and rodada_fim between 23 and 38
    and rodada_fim = rodada_inicio + 2
  ),
  constraint br_blocos_apostas_status_chk check (
    status in ('futura','programada','aberta','fechada','bloqueada')
  ),
  constraint br_blocos_apostas_datas_chk check (
    (abre_em is null or fecha_em is null or abre_em < fecha_em)
    and (primeiro_jogo_em is null or fecha_em is null or fecha_em < primeiro_jogo_em)
  ),
  constraint br_blocos_apostas_versao_chk check (versao >= 1),
  constraint br_blocos_apostas_unico unique (temporada, rodada_inicio, rodada_fim)
);

create index if not exists br_blocos_apostas_temporada_idx
  on public.br_blocos_apostas (temporada, rodada_inicio);

create table if not exists public.br_blocos_apostas_auditoria (
  id uuid primary key default gen_random_uuid(),
  bloco_id uuid not null references public.br_blocos_apostas(id) on delete restrict,
  temporada int not null,
  rodada_inicio int not null,
  rodada_fim int not null,
  admin_id uuid references public.br_participantes(id) on delete set null,
  acao text not null,
  versao_anterior bigint,
  versao_nova bigint not null,
  antes jsonb,
  depois jsonb not null,
  justificativa text,
  criado_em timestamptz not null default now()
);

create index if not exists br_blocos_apostas_auditoria_bloco_idx
  on public.br_blocos_apostas_auditoria (bloco_id, criado_em desc);

alter table public.br_blocos_apostas enable row level security;
alter table public.br_blocos_apostas_auditoria enable row level security;

-- Não são criadas policies de escrita direta. A aplicação usa somente RPCs
-- SECURITY DEFINER com validação da sessão administrativa.

-- --------------------------------------------------------------------------
-- 2. Vínculo opcional com configurações e palpites existentes
-- --------------------------------------------------------------------------

alter table public.br_config_rodadas
  add column if not exists bloco_id uuid;

alter table public.br_palpites
  add column if not exists bloco_id uuid;

create index if not exists br_config_rodadas_bloco_idx
  on public.br_config_rodadas (bloco_id);

create index if not exists br_palpites_bloco_idx
  on public.br_palpites (bloco_id);

-- Adiciona as FKs apenas quando ainda não existirem. Assim, a reexecução não
-- duplica constraints e não toca em registros antigos.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'br_config_rodadas_bloco_fk'
      and conrelid = 'public.br_config_rodadas'::regclass
  ) then
    alter table public.br_config_rodadas
      add constraint br_config_rodadas_bloco_fk
      foreign key (bloco_id) references public.br_blocos_apostas(id) on delete restrict;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'br_palpites_bloco_fk'
      and conrelid = 'public.br_palpites'::regclass
  ) then
    alter table public.br_palpites
      add constraint br_palpites_bloco_fk
      foreign key (bloco_id) references public.br_blocos_apostas(id) on delete restrict;
  end if;
end;
$$;

-- --------------------------------------------------------------------------
-- 3. Seeds fixos dos seis blocos. ON CONFLICT DO NOTHING é intencional:
--    nenhuma configuração administrativa já existente será sobrescrita.
-- --------------------------------------------------------------------------

insert into public.br_blocos_apostas
  (temporada, rodada_inicio, rodada_fim, nome, status, observacao)
values
  (2026, 21, 23, 'Bloco 21–23', 'futura', 'Primeiro bloco de três rodadas após a Rodada 20.'),
  (2026, 24, 26, 'Bloco 24–26', 'futura', null),
  (2026, 27, 29, 'Bloco 27–29', 'futura', null),
  (2026, 30, 32, 'Bloco 30–32', 'futura', null),
  (2026, 33, 35, 'Bloco 33–35', 'futura', null),
  (2026, 36, 38, 'Bloco 36–38', 'futura', null)
on conflict (temporada, rodada_inicio, rodada_fim) do nothing;

-- --------------------------------------------------------------------------
-- 4. Funções auxiliares e travas de consistência
-- --------------------------------------------------------------------------

create or replace function public.br_recomendar_fechamento_bloco_v1(
  p_primeiro_jogo_em timestamptz
)
returns timestamptz
language sql
immutable
as $$
  select case
    when p_primeiro_jogo_em is null then null
    else p_primeiro_jogo_em - interval '1 hour'
  end;
$$;

-- Configurações vinculadas a um bloco não podem receber datas divergentes por
-- uma RPC antiga ou por uma edição isolada. A Rodada 20, sem bloco_id, não é
-- atingida por esta trigger.
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

  -- HOTFIX 2026-09-06: linhas já publicadas/apuradas são histórico imutável.
  -- A Execução 21 preserva intencionalmente abre_em/fecha_em desses registros;
  -- portanto a trigger não pode exigir que acompanhem uma janela do bloco que
  -- tenha sido recalculada posteriormente. O vínculo temporada/rodada/bloco
  -- continua sendo validado acima.
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

drop trigger if exists br_config_rodadas_validar_bloco_v1 on public.br_config_rodadas;
create trigger br_config_rodadas_validar_bloco_v1
before insert or update of temporada, rodada, abre_em, fecha_em, bloco_id
on public.br_config_rodadas
for each row execute function public.br_validar_config_rodada_bloco_v1();

-- O vínculo em br_palpites é opcional para compatibilidade, mas passa a ser
-- preenchido automaticamente quando a configuração da rodada já pertence a
-- um bloco. Palpites da Rodada 20 continuam com bloco_id nulo.
create or replace function public.br_vincular_palpite_bloco_v1()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_bloco_id uuid;
  v_bloco public.br_blocos_apostas%rowtype;
begin
  if new.rodada <= 20 then
    new.bloco_id := null;
    return new;
  end if;

  if new.bloco_id is null then
    select c.bloco_id into v_bloco_id
    from public.br_config_rodadas c
    where c.temporada = new.temporada
      and c.rodada = new.rodada;
    new.bloco_id := v_bloco_id;
  end if;

  if new.bloco_id is not null then
    select b.* into v_bloco
    from public.br_blocos_apostas b
    where b.id = new.bloco_id;

    if v_bloco.id is null
       or new.temporada <> v_bloco.temporada
       or new.rodada < v_bloco.rodada_inicio
       or new.rodada > v_bloco.rodada_fim then
      raise exception 'Vínculo de bloco incompatível com a rodada %.', new.rodada;
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists br_palpites_vincular_bloco_v1 on public.br_palpites;
create trigger br_palpites_vincular_bloco_v1
before insert or update of temporada, rodada, bloco_id
on public.br_palpites
for each row execute function public.br_vincular_palpite_bloco_v1();

-- Não há backfill físico dos palpites já existentes. O vínculo é opcional e
-- será preenchido nos novos INSERTs/alterações de chave; registros anteriores
-- continuam íntegros, inclusive em seus horários de atualização e hashes.

-- --------------------------------------------------------------------------
-- 5. RPCs versionadas
-- --------------------------------------------------------------------------

-- Lista administrativa dos blocos, incluindo recomendação, divergência,
-- quantidade de rodadas materializadas e total de palpites vinculados.
create or replace function public.br_admin_listar_blocos_apostas_v1(
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
    b.id,
    b.temporada,
    b.rodada_inicio,
    b.rodada_fim,
    b.nome,
    b.primeiro_jogo_em,
    public.br_recomendar_fechamento_bloco_v1(b.primeiro_jogo_em),
    b.abre_em,
    b.fecha_em,
    b.status,
    b.observacao,
    b.versao,
    (
      select count(*)::int
      from public.br_config_rodadas c
      where c.bloco_id = b.id
    ),
    (
      select count(*)::bigint
      from public.br_palpites p
      where p.bloco_id = b.id
         or (
           p.bloco_id is null
           and p.temporada = b.temporada
           and p.rodada between b.rodada_inicio and b.rodada_fim
         )
    ),
    case
      when b.primeiro_jogo_em is null or b.fecha_em is null then false
      else b.fecha_em = public.br_recomendar_fechamento_bloco_v1(b.primeiro_jogo_em)
    end,
    b.atualizado_em
  from public.br_blocos_apostas b
  where b.temporada = p_temporada
  order by b.rodada_inicio;
end;
$$;

revoke all on function public.br_admin_listar_blocos_apostas_v1(uuid,text,int) from public;
grant execute on function public.br_admin_listar_blocos_apostas_v1(uuid,text,int) to anon;

-- Versão pública futura da configuração. A RPC antiga é preservada e continua
-- sendo usada pela Execução 1; esta v2 já expõe os metadados necessários para
-- a interface de blocos da Execução 3.
create or replace function public.br_listar_config_rodadas_v2(
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
    c.temporada,
    c.rodada,
    c.abre_em,
    c.fecha_em,
    c.publica_em,
    c.status,
    c.observacao,
    c.total_jogos,
    c.atualizado_em,
    c.bloco_id,
    b.nome,
    b.rodada_inicio,
    b.rodada_fim,
    b.primeiro_jogo_em,
    b.versao
  from public.br_config_rodadas c
  left join public.br_blocos_apostas b on b.id = c.bloco_id
  where c.temporada = p_temporada
  order by c.rodada;
$$;

revoke all on function public.br_listar_config_rodadas_v2(int) from public;
grant execute on function public.br_listar_config_rodadas_v2(int) to anon;

-- Salva o bloco inteiro com optimistic locking. O fechamento é calculado
-- automaticamente quando p_fecha_em vier nulo. Um fechamento diferente de
-- primeiro_jogo_em - 1h exige confirmação explícita e justificativa.
create or replace function public.br_admin_salvar_bloco_apostas_v1(
  p_admin_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_versao_esperada bigint,
  p_primeiro_jogo_em timestamptz,
  p_abre_em timestamptz,
  p_fecha_em timestamptz,
  p_status text,
  p_observacao text,
  p_confirmar_alteracao_sensivel boolean default false,
  p_confirmar_fechamento_diferente boolean default false
)
returns table (
  bloco_id uuid,
  versao bigint,
  fecha_em timestamptz,
  fechamento_recomendado_em timestamptz,
  fechamento_conforme_recomendacao boolean,
  total_palpites bigint,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_antes public.br_blocos_apostas%rowtype;
  v_depois public.br_blocos_apostas%rowtype;
  v_primeiro_jogo_em timestamptz;
  v_abre_em timestamptz;
  v_fecha timestamptz;
  v_recomendado timestamptz;
  v_total_palpites bigint;
  v_alteracao_sensivel boolean;
  v_reabertura boolean;
  v_status_config text;
  v_justificativa text;
begin
  if not public.br_validar_sessao(p_admin_id, p_token, true) then
    raise exception 'Acesso admin inválido.';
  end if;

  select b.* into v_antes
  from public.br_blocos_apostas b
  where b.id = p_bloco_id
  for update;

  if v_antes.id is null then
    raise exception 'Bloco de apostas não encontrado.';
  end if;

  if p_versao_esperada is null or p_versao_esperada <> v_antes.versao then
    raise exception 'O bloco foi alterado em outra sessão. Recarregue o painel antes de salvar.';
  end if;

  if coalesce(p_status, '') not in ('futura','programada','aberta','fechada','bloqueada') then
    raise exception 'Status de bloco inválido.';
  end if;

  -- Campos omitidos preservam a configuração atual. Isso torna a RPC segura
  -- para atualizações parciais e impede que um bloco já materializado fique com
  -- datas nulas enquanto as três rodadas continuam vinculadas à janela anterior.
  v_primeiro_jogo_em := coalesce(p_primeiro_jogo_em, v_antes.primeiro_jogo_em);
  v_abre_em := coalesce(p_abre_em, v_antes.abre_em);
  v_recomendado := public.br_recomendar_fechamento_bloco_v1(v_primeiro_jogo_em);

  if p_fecha_em is not null then
    v_fecha := p_fecha_em;
  elsif p_primeiro_jogo_em is not null
        and p_primeiro_jogo_em is distinct from v_antes.primeiro_jogo_em then
    v_fecha := v_recomendado;
  else
    v_fecha := coalesce(v_antes.fecha_em, v_recomendado);
  end if;

  v_justificativa := nullif(trim(coalesce(p_observacao, '')), '');

  if (v_abre_em is not null or v_fecha is not null) and v_primeiro_jogo_em is null then
    raise exception 'Informe o primeiro jogo antes de configurar a janela do bloco.';
  end if;
  if v_abre_em is not null and v_fecha is not null and v_abre_em >= v_fecha then
    raise exception 'A abertura deve ser anterior ao fechamento.';
  end if;
  if v_primeiro_jogo_em is not null and v_fecha is not null and v_fecha >= v_primeiro_jogo_em then
    raise exception 'O fechamento deve ocorrer antes do primeiro jogo.';
  end if;

  if p_status <> 'futura' then
    if v_primeiro_jogo_em is null then
      raise exception 'Informe o primeiro jogo do bloco.';
    end if;
    if v_abre_em is null then
      raise exception 'Informe a abertura do bloco.';
    end if;
    if v_fecha is null then
      raise exception 'Não foi possível calcular o fechamento do bloco.';
    end if;
  end if;

  if v_fecha is not null
     and v_recomendado is not null
     and v_fecha is distinct from v_recomendado
     and not coalesce(p_confirmar_fechamento_diferente, false) then
    raise exception 'O fechamento recomendado é exatamente 1 hora antes do primeiro jogo. Confirme explicitamente para usar outro horário.';
  end if;

  if v_fecha is not null
     and v_recomendado is not null
     and v_fecha is distinct from v_recomendado
     and v_justificativa is null then
    raise exception 'Informe uma justificativa para usar fechamento diferente da recomendação.';
  end if;

  select count(*)::bigint into v_total_palpites
  from public.br_palpites p
  where p.bloco_id = v_antes.id
     or (
       p.bloco_id is null
       and p.temporada = v_antes.temporada
       and p.rodada between v_antes.rodada_inicio and v_antes.rodada_fim
     );

  v_alteracao_sensivel :=
    v_antes.primeiro_jogo_em is distinct from v_primeiro_jogo_em
    or v_antes.abre_em is distinct from v_abre_em
    or v_antes.fecha_em is distinct from v_fecha
    or v_antes.status is distinct from p_status;

  v_reabertura :=
    v_antes.status in ('fechada','bloqueada')
    and p_status in ('programada','aberta');

  if (v_total_palpites > 0 and v_alteracao_sensivel) or v_reabertura then
    if not coalesce(p_confirmar_alteracao_sensivel, false) then
      raise exception 'Alteração sensível bloqueada. Confirme a operação e registre a justificativa.';
    end if;
    if v_justificativa is null then
      raise exception 'A justificativa é obrigatória para alteração sensível.';
    end if;
  end if;

  update public.br_blocos_apostas b
  set primeiro_jogo_em = v_primeiro_jogo_em,
      abre_em = v_abre_em,
      fecha_em = v_fecha,
      status = p_status,
      observacao = p_observacao,
      versao = b.versao + 1,
      atualizado_em = now()
  where b.id = v_antes.id
    and b.versao = p_versao_esperada
  returning b.* into v_depois;

  if v_depois.id is null then
    raise exception 'Conflito de versão ao salvar o bloco. Recarregue o painel.';
  end if;

  -- Só materializa br_config_rodadas quando existe uma janela completa.
  -- A Rodada 20 não entra no generate_series e permanece intocada.
  if v_depois.abre_em is not null and v_depois.fecha_em is not null then
    v_status_config := case v_depois.status
      when 'futura' then 'futura'
      when 'programada' then 'programada'
      when 'aberta' then 'aberta'
      when 'fechada' then 'fechada'
      when 'bloqueada' then 'bloqueada'
      else 'programada'
    end;

    insert into public.br_config_rodadas
      (temporada, rodada, abre_em, fecha_em, publica_em, status, observacao, bloco_id, atualizado_em)
    select
      v_depois.temporada,
      gs.rodada,
      v_depois.abre_em,
      v_depois.fecha_em,
      null,
      v_status_config,
      concat('Janela herdada do ', v_depois.nome,
             case when nullif(trim(coalesce(v_depois.observacao, '')), '') is null
                  then '' else ' · ' || trim(v_depois.observacao) end),
      v_depois.id,
      now()
    from generate_series(v_depois.rodada_inicio, v_depois.rodada_fim) as gs(rodada)
    on conflict (temporada, rodada)
    do update set
      abre_em = excluded.abre_em,
      fecha_em = excluded.fecha_em,
      status = case
        when public.br_config_rodadas.status in ('publicada','apurada')
          then public.br_config_rodadas.status
        else excluded.status
      end,
      observacao = case
        when nullif(trim(coalesce(public.br_config_rodadas.observacao, '')), '') is null
          then excluded.observacao
        else public.br_config_rodadas.observacao
      end,
      bloco_id = excluded.bloco_id,
      atualizado_em = now();
  end if;

  -- Palpites preexistentes permanecem sem alteração física. As consultas e
  -- proteções do bloco também consideram registros legados pelo intervalo de
  -- rodadas, mesmo quando bloco_id continua nulo.

  insert into public.br_blocos_apostas_auditoria
    (bloco_id, temporada, rodada_inicio, rodada_fim, admin_id, acao,
     versao_anterior, versao_nova, antes, depois, justificativa)
  values
    (v_depois.id, v_depois.temporada, v_depois.rodada_inicio, v_depois.rodada_fim,
     p_admin_id,
     case when v_antes.abre_em is null and v_depois.abre_em is not null then 'configuracao_inicial' else 'atualizacao' end,
     v_antes.versao, v_depois.versao, to_jsonb(v_antes), to_jsonb(v_depois), v_justificativa);

  return query
  select
    v_depois.id,
    v_depois.versao,
    v_depois.fecha_em,
    public.br_recomendar_fechamento_bloco_v1(v_depois.primeiro_jogo_em),
    case
      when v_depois.primeiro_jogo_em is null or v_depois.fecha_em is null then false
      else v_depois.fecha_em = public.br_recomendar_fechamento_bloco_v1(v_depois.primeiro_jogo_em)
    end,
    v_total_palpites,
    v_depois.atualizado_em;
end;
$$;

revoke all on function public.br_admin_salvar_bloco_apostas_v1(uuid,text,uuid,bigint,timestamptz,timestamptz,timestamptz,text,text,boolean,boolean) from public;
grant execute on function public.br_admin_salvar_bloco_apostas_v1(uuid,text,uuid,bigint,timestamptz,timestamptz,timestamptz,text,text,boolean,boolean) to anon;

create or replace function public.br_admin_historico_blocos_apostas_v1(
  p_admin_id uuid,
  p_token text,
  p_bloco_id uuid,
  p_limite int default 50
)
returns table (
  auditoria_id uuid,
  criado_em timestamptz,
  acao text,
  versao_anterior bigint,
  versao_nova bigint,
  justificativa text,
  admin_id uuid,
  antes jsonb,
  depois jsonb
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
    a.id,
    a.criado_em,
    a.acao,
    a.versao_anterior,
    a.versao_nova,
    a.justificativa,
    a.admin_id,
    a.antes,
    a.depois
  from public.br_blocos_apostas_auditoria a
  where a.bloco_id = p_bloco_id
  order by a.criado_em desc
  limit greatest(1, least(coalesce(p_limite, 50), 200));
end;
$$;

revoke all on function public.br_admin_historico_blocos_apostas_v1(uuid,text,uuid,int) from public;
grant execute on function public.br_admin_historico_blocos_apostas_v1(uuid,text,uuid,int) to anon;

commit;

-- --------------------------------------------------------------------------
-- Validações sugeridas após executar o arquivo
-- --------------------------------------------------------------------------
-- 1) A Rodada 20 deve continuar sem bloco:
-- select temporada, rodada, bloco_id, abre_em, fecha_em, status
-- from public.br_config_rodadas
-- where temporada = 2026 and rodada = 20;
--
-- 2) Devem existir exatamente seis blocos:
-- select temporada, rodada_inicio, rodada_fim, nome, status, versao
-- from public.br_blocos_apostas
-- where temporada = 2026
-- order by rodada_inicio;
--
-- 3) Nenhum dado de palpite da Rodada 20 deve ter sido alterado:
-- select count(*) as palpites_r20, count(bloco_id) as palpites_r20_com_bloco
-- from public.br_palpites
-- where temporada = 2026 and rodada = 20;

-- ============================================================================
-- Desafios na Mesa — registro recreativo privado do Almoço de Sexta
--
-- Execute uma vez no SQL Editor do mesmo projeto Supabase usado pelo bolão.
-- Pré-requisito: estruturas e funções de autenticação da Execução 10 ou superior.
-- O script é idempotente e pode ser executado novamente com segurança.
-- ============================================================================

create extension if not exists pgcrypto;

create table if not exists public.br_desafios_mesa (
  id uuid primary key default gen_random_uuid(),
  titulo text not null,
  participante_a_id uuid not null references public.br_participantes(id) on delete restrict,
  participante_b_id uuid not null references public.br_participantes(id) on delete restrict,
  descricao text not null,
  criterio_resultado text not null,
  compromisso_simbolico text not null,
  prazo date not null,
  alerta_em timestamptz not null,
  alerta_enviado_em timestamptz,
  status text not null default 'em_andamento',
  vencedor_id uuid references public.br_participantes(id) on delete restrict,
  perdedor_id uuid references public.br_participantes(id) on delete restrict,
  cumprido boolean not null default false,
  data_cumprimento date,
  observacoes text,
  criado_por uuid not null references public.br_participantes(id) on delete restrict,
  atualizado_por uuid not null references public.br_participantes(id) on delete restrict,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint br_desafios_participantes_diferentes check (participante_a_id <> participante_b_id),
  constraint br_desafios_status_valido check (status in ('em_andamento', 'aguardando_resultado', 'encerrado', 'cumprido', 'cancelado')),
  constraint br_desafios_resultado_par check ((vencedor_id is null) = (perdedor_id is null)),
  constraint br_desafios_resultado_diferente check (vencedor_id is null or vencedor_id <> perdedor_id),
  constraint br_desafios_cumprimento_coerente check (
    (cumprido = false and data_cumprimento is null and status <> 'cumprido')
    or (cumprido = true and data_cumprimento is not null and status = 'cumprido')
  )
);

create index if not exists br_desafios_status_prazo_idx on public.br_desafios_mesa(status, prazo);
create index if not exists br_desafios_alerta_idx on public.br_desafios_mesa(alerta_em) where alerta_enviado_em is null;
create index if not exists br_desafios_participante_a_idx on public.br_desafios_mesa(participante_a_id);
create index if not exists br_desafios_participante_b_idx on public.br_desafios_mesa(participante_b_id);

create table if not exists public.br_desafios_mesa_auditoria (
  id uuid primary key default gen_random_uuid(),
  desafio_id uuid references public.br_desafios_mesa(id) on delete set null,
  acao text not null check (acao in ('criado', 'alterado', 'cancelado', 'alerta_enviado')),
  antes jsonb,
  depois jsonb,
  admin_id uuid references public.br_participantes(id) on delete set null,
  criado_em timestamptz not null default now()
);

create index if not exists br_desafios_auditoria_desafio_idx on public.br_desafios_mesa_auditoria(desafio_id, criado_em desc);

create or replace function public.br_desafios_set_atualizado_em()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

drop trigger if exists br_desafios_set_atualizado_em on public.br_desafios_mesa;
create trigger br_desafios_set_atualizado_em
before update on public.br_desafios_mesa
for each row execute function public.br_desafios_set_atualizado_em();

-- As tabelas nunca são expostas diretamente. Toda leitura/escrita passa pelas
-- RPCs abaixo, que validam a sessão e o perfil do usuário.
alter table public.br_desafios_mesa enable row level security;
alter table public.br_desafios_mesa_auditoria enable row level security;
revoke all on table public.br_desafios_mesa from anon, authenticated;
revoke all on table public.br_desafios_mesa_auditoria from anon, authenticated;

create or replace function public.br_desafio_texto_permitido(p_texto text)
returns boolean
language sql
immutable
set search_path = public
as $$
  select
    coalesce(p_texto, '') !~* '(^|[^[:alnum:]_])(dinheiro|pix|reais?|apostas?|bets?|cassino|vinhos?|champagne|champanhe|espumantes?|cervejas?|whisky|whiskey|vodka|cachaça|cachaca|gins?|rum|licores?)([^[:alnum:]_]|$)'
    and coalesce(p_texto, '') !~* 'r\s*\$'
    and coalesce(p_texto, '') !~* 'jogos?\s+de\s+azar'
    and coalesce(p_texto, '') !~* 'bebidas?\s+alco[oó]licas?';
$$;

drop function if exists public.br_desafios_listar(uuid, text);
create function public.br_desafios_listar(p_participante_id uuid, p_token text)
returns table (
  id uuid,
  titulo text,
  participante_a_id uuid,
  participante_a_nome text,
  participante_b_id uuid,
  participante_b_nome text,
  descricao text,
  criterio_resultado text,
  compromisso_simbolico text,
  prazo date,
  alerta_em timestamptz,
  alerta_enviado_em timestamptz,
  status text,
  vencedor_id uuid,
  vencedor_nome text,
  perdedor_id uuid,
  perdedor_nome text,
  cumprido boolean,
  data_cumprimento date,
  observacoes text,
  criado_em timestamptz,
  atualizado_em timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida ou expirada.';
  end if;

  return query
  select
    d.id,
    d.titulo,
    d.participante_a_id,
    pa.nome,
    d.participante_b_id,
    pb.nome,
    d.descricao,
    d.criterio_resultado,
    d.compromisso_simbolico,
    d.prazo,
    d.alerta_em,
    d.alerta_enviado_em,
    d.status,
    d.vencedor_id,
    pv.nome,
    d.perdedor_id,
    pp.nome,
    d.cumprido,
    d.data_cumprimento,
    d.observacoes,
    d.criado_em,
    d.atualizado_em
  from public.br_desafios_mesa d
  join public.br_participantes pa on pa.id = d.participante_a_id
  join public.br_participantes pb on pb.id = d.participante_b_id
  left join public.br_participantes pv on pv.id = d.vencedor_id
  left join public.br_participantes pp on pp.id = d.perdedor_id
  order by
    case d.status
      when 'em_andamento' then 1
      when 'aguardando_resultado' then 2
      when 'encerrado' then 3
      when 'cumprido' then 4
      else 5
    end,
    d.prazo asc,
    d.criado_em desc;
end;
$$;

revoke all on function public.br_desafios_listar(uuid, text) from public;
grant execute on function public.br_desafios_listar(uuid, text) to anon;

drop function if exists public.br_desafios_admin_participantes(uuid, text);
create function public.br_desafios_admin_participantes(p_admin_id uuid, p_token text)
returns table (participante_id uuid, nome text, ativo boolean)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.br_validar_sessao(p_admin_id, p_token, true) then
    raise exception 'Acesso administrativo inválido.';
  end if;
  return query
  select p.id, p.nome, p.ativo
  from public.br_participantes p
  where p.ativo = true
  order by p.nome;
end;
$$;

revoke all on function public.br_desafios_admin_participantes(uuid, text) from public;
grant execute on function public.br_desafios_admin_participantes(uuid, text) to anon;

drop function if exists public.br_desafios_admin_salvar(
  uuid, text, uuid, text, uuid, uuid, text, text, text, date, timestamptz,
  text, uuid, uuid, boolean, date, text
);
create function public.br_desafios_admin_salvar(
  p_admin_id uuid,
  p_token text,
  p_desafio_id uuid,
  p_titulo text,
  p_participante_a_id uuid,
  p_participante_b_id uuid,
  p_descricao text,
  p_criterio_resultado text,
  p_compromisso_simbolico text,
  p_prazo date,
  p_alerta_em timestamptz,
  p_status text,
  p_vencedor_id uuid,
  p_perdedor_id uuid,
  p_cumprido boolean,
  p_data_cumprimento date,
  p_observacoes text
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
  v_antes jsonb;
  v_depois jsonb;
  v_alerta_anterior timestamptz;
begin
  if not public.br_validar_sessao(p_admin_id, p_token, true) then
    raise exception 'Acesso administrativo inválido.';
  end if;

  p_titulo := btrim(coalesce(p_titulo, ''));
  p_descricao := btrim(coalesce(p_descricao, ''));
  p_criterio_resultado := btrim(coalesce(p_criterio_resultado, ''));
  p_compromisso_simbolico := btrim(coalesce(p_compromisso_simbolico, ''));
  p_observacoes := nullif(btrim(coalesce(p_observacoes, '')), '');
  p_status := btrim(coalesce(p_status, ''));

  if length(p_titulo) not between 3 and 100 then raise exception 'Título deve ter entre 3 e 100 caracteres.'; end if;
  if length(p_descricao) not between 5 and 600 then raise exception 'Descrição deve ter entre 5 e 600 caracteres.'; end if;
  if length(p_criterio_resultado) not between 5 and 500 then raise exception 'Critério deve ter entre 5 e 500 caracteres.'; end if;
  if length(p_compromisso_simbolico) not between 2 and 160 then raise exception 'Compromisso simbólico deve ter entre 2 e 160 caracteres.'; end if;
  if length(coalesce(p_observacoes, '')) > 600 then raise exception 'Observações excedem 600 caracteres.'; end if;
  if p_participante_a_id is null or p_participante_b_id is null or p_participante_a_id = p_participante_b_id then
    raise exception 'Selecione dois participantes diferentes.';
  end if;
  if not exists (select 1 from public.br_participantes where id = p_participante_a_id and ativo = true)
     or not exists (select 1 from public.br_participantes where id = p_participante_b_id and ativo = true) then
    raise exception 'Participante inexistente ou inativo.';
  end if;
  if p_prazo is null or p_alerta_em is null then raise exception 'Prazo e alerta são obrigatórios.'; end if;
  if p_alerta_em >= ((p_prazo + 1)::timestamp at time zone 'America/Sao_Paulo') then
    raise exception 'O alerta deve ocorrer até a data-limite.';
  end if;
  if p_status not in ('em_andamento', 'aguardando_resultado', 'encerrado', 'cumprido') then
    raise exception 'Situação inválida.';
  end if;
  if not public.br_desafio_texto_permitido(p_titulo || ' ' || p_descricao || ' ' || p_criterio_resultado || ' ' || p_compromisso_simbolico || ' ' || coalesce(p_observacoes, '')) then
    raise exception 'Use somente compromissos simbólicos, sem dinheiro, itens restritos ou jogos de azar.';
  end if;
  if (p_vencedor_id is null) <> (p_perdedor_id is null) then raise exception 'Defina vencedor e responsável juntos.'; end if;
  if p_vencedor_id is not null then
    if p_vencedor_id = p_perdedor_id then raise exception 'O resultado precisa indicar pessoas diferentes.'; end if;
    if p_vencedor_id not in (p_participante_a_id, p_participante_b_id)
       or p_perdedor_id not in (p_participante_a_id, p_participante_b_id) then
      raise exception 'O resultado deve usar os dois participantes do desafio.';
    end if;
  end if;
  if p_status in ('encerrado', 'cumprido') and (p_vencedor_id is null or p_perdedor_id is null) then
    raise exception 'Defina o resultado antes de encerrar.';
  end if;
  if p_status = 'cumprido' and (coalesce(p_cumprido, false) = false or p_data_cumprimento is null) then
    raise exception 'Confirme o cumprimento e informe a data.';
  end if;
  if p_status <> 'cumprido' and (coalesce(p_cumprido, false) = true or p_data_cumprimento is not null) then
    raise exception 'A data de cumprimento exige a situação Cumprido.';
  end if;

  if p_desafio_id is null then
    insert into public.br_desafios_mesa (
      titulo, participante_a_id, participante_b_id, descricao, criterio_resultado,
      compromisso_simbolico, prazo, alerta_em, status, vencedor_id, perdedor_id,
      cumprido, data_cumprimento, observacoes, criado_por, atualizado_por
    ) values (
      p_titulo, p_participante_a_id, p_participante_b_id, p_descricao, p_criterio_resultado,
      p_compromisso_simbolico, p_prazo, p_alerta_em, p_status, p_vencedor_id, p_perdedor_id,
      coalesce(p_cumprido, false), p_data_cumprimento, p_observacoes, p_admin_id, p_admin_id
    ) returning id, to_jsonb(br_desafios_mesa) into v_id, v_depois;

    insert into public.br_desafios_mesa_auditoria(desafio_id, acao, depois, admin_id)
    values (v_id, 'criado', v_depois, p_admin_id);
  else
    select to_jsonb(d), d.alerta_em into v_antes, v_alerta_anterior
    from public.br_desafios_mesa d where d.id = p_desafio_id for update;
    if v_antes is null then raise exception 'Desafio não encontrado.'; end if;
    if v_antes->>'status' = 'cancelado' then raise exception 'Um desafio cancelado não pode ser alterado.'; end if;

    update public.br_desafios_mesa d set
      titulo = p_titulo,
      participante_a_id = p_participante_a_id,
      participante_b_id = p_participante_b_id,
      descricao = p_descricao,
      criterio_resultado = p_criterio_resultado,
      compromisso_simbolico = p_compromisso_simbolico,
      prazo = p_prazo,
      alerta_em = p_alerta_em,
      alerta_enviado_em = case when v_alerta_anterior is distinct from p_alerta_em then null else d.alerta_enviado_em end,
      status = p_status,
      vencedor_id = p_vencedor_id,
      perdedor_id = p_perdedor_id,
      cumprido = coalesce(p_cumprido, false),
      data_cumprimento = p_data_cumprimento,
      observacoes = p_observacoes,
      atualizado_por = p_admin_id
    where d.id = p_desafio_id
    returning d.id, to_jsonb(d) into v_id, v_depois;

    insert into public.br_desafios_mesa_auditoria(desafio_id, acao, antes, depois, admin_id)
    values (v_id, 'alterado', v_antes, v_depois, p_admin_id);
  end if;

  return v_id;
end;
$$;

revoke all on function public.br_desafios_admin_salvar(
  uuid, text, uuid, text, uuid, uuid, text, text, text, date, timestamptz,
  text, uuid, uuid, boolean, date, text
) from public;
grant execute on function public.br_desafios_admin_salvar(
  uuid, text, uuid, text, uuid, uuid, text, text, text, date, timestamptz,
  text, uuid, uuid, boolean, date, text
) to anon;

drop function if exists public.br_desafios_admin_cancelar(uuid, text, uuid);
create function public.br_desafios_admin_cancelar(p_admin_id uuid, p_token text, p_desafio_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_antes jsonb;
  v_depois jsonb;
begin
  if not public.br_validar_sessao(p_admin_id, p_token, true) then
    raise exception 'Acesso administrativo inválido.';
  end if;
  select to_jsonb(d) into v_antes from public.br_desafios_mesa d where d.id = p_desafio_id for update;
  if v_antes is null then raise exception 'Desafio não encontrado.'; end if;
  if v_antes->>'status' = 'cancelado' then return true; end if;

  update public.br_desafios_mesa d set
    status = 'cancelado',
    cumprido = false,
    data_cumprimento = null,
    atualizado_por = p_admin_id
  where d.id = p_desafio_id
  returning to_jsonb(d) into v_depois;

  insert into public.br_desafios_mesa_auditoria(desafio_id, acao, antes, depois, admin_id)
  values (p_desafio_id, 'cancelado', v_antes, v_depois, p_admin_id);
  return true;
end;
$$;

revoke all on function public.br_desafios_admin_cancelar(uuid, text, uuid) from public;
grant execute on function public.br_desafios_admin_cancelar(uuid, text, uuid) to anon;

-- Funções exclusivas do workflow de alertas. Elas não são concedidas ao site.
drop function if exists public.br_desafios_alertas_pendentes(timestamptz);
create function public.br_desafios_alertas_pendentes(p_agora timestamptz)
returns table (
  id uuid,
  titulo text,
  participante_a_nome text,
  participante_b_nome text,
  descricao text,
  criterio_resultado text,
  compromisso_simbolico text,
  prazo date,
  alerta_em timestamptz
)
language sql
security definer
set search_path = public
as $$
  select d.id, d.titulo, pa.nome, pb.nome, d.descricao, d.criterio_resultado,
         d.compromisso_simbolico, d.prazo, d.alerta_em
  from public.br_desafios_mesa d
  join public.br_participantes pa on pa.id = d.participante_a_id
  join public.br_participantes pb on pb.id = d.participante_b_id
  where d.status in ('em_andamento', 'aguardando_resultado', 'encerrado')
    and d.alerta_em <= coalesce(p_agora, now())
    and d.alerta_enviado_em is null
  order by d.alerta_em, d.prazo, d.titulo;
$$;

revoke all on function public.br_desafios_alertas_pendentes(timestamptz) from public, anon, authenticated;
grant execute on function public.br_desafios_alertas_pendentes(timestamptz) to service_role;

drop function if exists public.br_desafios_marcar_alertas_enviados(uuid[], timestamptz);
create function public.br_desafios_marcar_alertas_enviados(p_ids uuid[], p_enviado_em timestamptz)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_total integer;
  v_id uuid;
begin
  update public.br_desafios_mesa
  set alerta_enviado_em = coalesce(p_enviado_em, now())
  where id = any(coalesce(p_ids, array[]::uuid[]))
    and alerta_enviado_em is null;
  get diagnostics v_total = row_count;

  foreach v_id in array coalesce(p_ids, array[]::uuid[]) loop
    insert into public.br_desafios_mesa_auditoria(desafio_id, acao, depois, admin_id)
    select d.id, 'alerta_enviado', to_jsonb(d), null
    from public.br_desafios_mesa d where d.id = v_id;
  end loop;
  return v_total;
end;
$$;

revoke all on function public.br_desafios_marcar_alertas_enviados(uuid[], timestamptz) from public, anon, authenticated;
grant execute on function public.br_desafios_marcar_alertas_enviados(uuid[], timestamptz) to service_role;

-- Verificação rápida após executar:
-- select to_regclass('public.br_desafios_mesa') as tabela,
--        has_function_privilege('anon', 'public.br_desafios_listar(uuid,text)', 'execute') as leitura_rpc,
--        has_table_privilege('anon', 'public.br_desafios_mesa', 'select') as leitura_direta;

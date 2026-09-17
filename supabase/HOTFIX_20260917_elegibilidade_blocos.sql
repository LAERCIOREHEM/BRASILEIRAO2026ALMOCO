-- ============================================================================
-- HOTFIX 2026-09-17 — elegibilidade imutável por bloco
--
-- Regras:
--   1) o fechamento HISTÓRICO que vale para elegibilidade congela no primeiro palpite;
--   2) 30/30 dentro da janela => elegível;
--   3) incompleto => não aparece em ranking/palpites públicos;
--   4) exceção histórica só existe quando explicitamente marcada no banco;
--   5) MEC fica elegível no bloco 21–23 com os 25 palpites já registrados;
--   6) prazo histórico do bloco 21–23 = 29/07/2026 21:30 UTC (18:30 BRT),
--      separado do fecha_em operacional exigido pelo calendário atual;
--   7) Carlinhos e Armínio permanecem elegíveis: auditoria comprova conclusão/
--      edição em 29/07, antes do fechamento histórico.
--
-- Idempotente. Aplicar no Supabase SQL Editor antes de reexecutar a apuração.
-- ============================================================================

begin;

-- --------------------------------------------------------------------------
-- 1. Metadados imutáveis de fechamento/elegibilidade
-- --------------------------------------------------------------------------

alter table public.br_blocos_apostas
  add column if not exists fecha_em_congelado timestamptz;
alter table public.br_blocos_apostas
  add column if not exists fechamento_congelado_em timestamptz;

alter table public.br_comprovantes_blocos
  add column if not exists elegivel boolean;
alter table public.br_comprovantes_blocos
  add column if not exists elegibilidade_motivo text;
alter table public.br_comprovantes_blocos
  add column if not exists concluido_em timestamptz;
alter table public.br_comprovantes_blocos
  add column if not exists fecha_em_congelado timestamptz;
alter table public.br_comprovantes_blocos
  add column if not exists excecao_administrativa boolean not null default false;
alter table public.br_comprovantes_blocos
  add column if not exists ultima_edicao_usuario_em timestamptz;

-- Regra estrutural: incompleto só pode ser elegível mediante exceção explícita.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'br_comprovantes_blocos_elegibilidade_chk'
      and conrelid = 'public.br_comprovantes_blocos'::regclass
  ) then
    alter table public.br_comprovantes_blocos
      add constraint br_comprovantes_blocos_elegibilidade_chk check (
        coalesce(elegivel, false) = false
        or total_palpites = total_jogos
        or excecao_administrativa = true
      );
  end if;
end $$;

-- --------------------------------------------------------------------------
-- 2. Corrige o fato histórico do bloco 21–23
-- --------------------------------------------------------------------------

-- O deadline HISTÓRICO que estava gravado nos próprios palpites de julho era
-- 21:30 UTC. Ele NÃO pode ser escrito em br_blocos_apostas.fecha_em porque
-- fecha_em é operacional e possui a constraint fecha_em < primeiro_jogo_em.
-- No estado atual do calendário o primeiro_jogo_em do 21–23 é 18:00 UTC e o
-- fecha_em operacional é 17:00 UTC; ambos permanecem intactos.
update public.br_blocos_apostas
set fecha_em_congelado = timestamptz '2026-07-29 21:30:00+00',
    fechamento_congelado_em = coalesce(fechamento_congelado_em, timestamptz '2026-07-29 13:15:35+00')
where temporada = 2026
  and rodada_inicio = 21
  and rodada_fim = 23;

-- Nos palpites realmente criados antes do fechamento histórico, preserva o
-- deadline que valia quando foram aceitos. Registros criados depois do prazo
-- não são "regularizados" por este hotfix.
update public.br_palpites p
set fecha_em = timestamptz '2026-07-29 21:30:00+00'
where p.temporada = 2026
  and p.rodada between 21 and 23
  and p.criado_em < timestamptz '2026-07-29 21:30:00+00'
  and p.fecha_em is distinct from timestamptz '2026-07-29 21:30:00+00';

-- Para demais blocos que já receberam qualquer palpite, congela o deadline
-- atualmente válido. A partir daqui ele não será mais recalculado.
update public.br_blocos_apostas b
set fecha_em_congelado = b.fecha_em,
    fechamento_congelado_em = coalesce(b.fechamento_congelado_em, now())
where b.temporada = 2026
  and b.fecha_em is not null
  and b.fecha_em_congelado is null
  and exists (
    select 1 from public.br_palpites p
    where p.temporada = b.temporada
      and p.rodada between b.rodada_inicio and b.rodada_fim
  );

-- --------------------------------------------------------------------------
-- 3. Backfill dos comprovantes existentes
-- --------------------------------------------------------------------------

-- Backfill conservador: 30/30 só é elegível quando as 30 linhas atuais
-- remontam a instante anterior ao deadline congelado. Isso evita transformar
-- em participante válido alguém completado tecnicamente/depois da janela.
-- As exceções históricas comprovadas do bloco 21–23 são fixadas logo abaixo.
update public.br_comprovantes_blocos cb
set elegivel = (
      cb.total_palpites = cb.total_jogos
      and not exists (
        select 1
        from public.br_palpites p
        where p.temporada = cb.temporada
          and p.participante_id = cb.participante_id
          and p.rodada between b.rodada_inicio and b.rodada_fim
          and (p.criado_em is null
               or p.criado_em >= coalesce(cb.fecha_em_congelado, b.fecha_em_congelado, b.fecha_em))
      )
    ),
    elegibilidade_motivo = case
      when cb.total_palpites <> cb.total_jogos
        then format('incompleto: %s/%s', cb.total_palpites, cb.total_jogos)
      when exists (
        select 1
        from public.br_palpites p
        where p.temporada = cb.temporada
          and p.participante_id = cb.participante_id
          and p.rodada between b.rodada_inicio and b.rodada_fim
          and (p.criado_em is null
               or p.criado_em >= coalesce(cb.fecha_em_congelado, b.fecha_em_congelado, b.fecha_em))
      ) then '30/30, mas há registro criado após o fechamento histórico'
      else 'backfill histórico: 30/30 anterior ao fechamento congelado'
    end,
    fecha_em_congelado = coalesce(cb.fecha_em_congelado, b.fecha_em_congelado, b.fecha_em)
from public.br_blocos_apostas b
where b.id = cb.bloco_id
  and cb.temporada = 2026
  and cb.excecao_administrativa = false;

-- Recupera, apenas para auditoria, a última edição registrada até o deadline
-- congelado. Eventos técnicos posteriores não alteram a elegibilidade.
with ultimas as (
  select
    cb.id as comprovante_id,
    max(a.criado_em) as ultima_edicao
  from public.br_comprovantes_blocos cb
  join public.br_blocos_apostas b on b.id = cb.bloco_id
  join public.br_palpites_auditoria a
    on a.temporada = cb.temporada
   and a.participante_id = cb.participante_id
   and a.rodada between b.rodada_inicio and b.rodada_fim
  where cb.temporada = 2026
    and a.acao in ('insert','update','insert_bloco','update_bloco','insert_bloco_uid','update_bloco_uid')
    and a.criado_em <= coalesce(cb.fecha_em_congelado, b.fecha_em_congelado, b.fecha_em)
  group by cb.id
)
update public.br_comprovantes_blocos cb
set ultima_edicao_usuario_em = u.ultima_edicao
from ultimas u
where u.comprovante_id = cb.id;

-- Evidência forense específica obtida da trilha imutável de 29/07/2026.
update public.br_comprovantes_blocos cb
set elegivel = true,
    elegibilidade_motivo = '30/30 concluídos dentro da janela histórica de 29/07/2026 18:30 BRT',
    concluido_em = timestamptz '2026-07-29 20:37:54.343159+00',
    ultima_edicao_usuario_em = timestamptz '2026-07-29 20:50:36.703273+00',
    fecha_em_congelado = timestamptz '2026-07-29 21:30:00+00'
from public.br_blocos_apostas b
where cb.bloco_id = b.id
  and cb.temporada = 2026
  and b.rodada_inicio = 21 and b.rodada_fim = 23
  and cb.participante_id = uuid '5e60a5dc-cb5d-4124-8770-06ebaeb5040b'; -- Armínio

update public.br_comprovantes_blocos cb
set elegivel = true,
    elegibilidade_motivo = '30/30 concluídos dentro da janela histórica de 29/07/2026 18:30 BRT',
    concluido_em = timestamptz '2026-07-29 13:20:27.495127+00',
    ultima_edicao_usuario_em = timestamptz '2026-07-29 13:20:27.495127+00',
    fecha_em_congelado = timestamptz '2026-07-29 21:30:00+00'
from public.br_blocos_apostas b
where cb.bloco_id = b.id
  and cb.temporada = 2026
  and b.rodada_inicio = 21 and b.rodada_fim = 23
  and cb.participante_id = uuid 'bda2b93f-dda9-4eec-8fe7-1558e82dd993'; -- Carlinhos

-- Decisão administrativa solicitada em 17/09/2026: MEC permanece neste bloco
-- com os 25 palpites efetivamente registrados. A exceção é isolada neste bloco.
update public.br_comprovantes_blocos cb
set elegivel = true,
    excecao_administrativa = true,
    elegibilidade_motivo = 'exceção histórica 21–23: manter os 25 palpites originalmente registrados; sem inclusão retroativa',
    fecha_em_congelado = timestamptz '2026-07-29 21:30:00+00'
from public.br_blocos_apostas b
where cb.bloco_id = b.id
  and cb.temporada = 2026
  and b.rodada_inicio = 21 and b.rodada_fim = 23
  and cb.participante_id = uuid '7ee44713-7900-44cb-a902-71bd66dd64ba'; -- MEC

-- --------------------------------------------------------------------------
-- 4. O deadline congelado não pode ser reescrito pelo pipeline
-- --------------------------------------------------------------------------

create or replace function public.br_preservar_fechamento_congelado_v1()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  -- Congela somente o fato histórico. O fecha_em operacional precisa continuar
  -- livre para obedecer ao calendário e à constraint fecha_em < primeiro_jogo_em.
  if old.fecha_em_congelado is not null then
    new.fecha_em_congelado := old.fecha_em_congelado;
  end if;
  if old.fechamento_congelado_em is not null then
    new.fechamento_congelado_em := old.fechamento_congelado_em;
  end if;
  return new;
end;
$$;

drop trigger if exists br_blocos_preservar_fechamento_congelado_v1
  on public.br_blocos_apostas;
create trigger br_blocos_preservar_fechamento_congelado_v1
before update of fecha_em_congelado, fechamento_congelado_em
on public.br_blocos_apostas
for each row execute function public.br_preservar_fechamento_congelado_v1();

-- --------------------------------------------------------------------------
-- 5. Sincronização do pipeline: separa prazo operacional de prazo histórico
-- --------------------------------------------------------------------------

create or replace function public.br_pipeline_sincronizar_blocos_v1(
  p_temporada int,
  p_agora timestamptz,
  p_abertura_antecedencia_dias int,
  p_fechamento_antecedencia_minutos int,
  p_blocos jsonb,
  p_origem text default 'pipeline-exec21'
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_item jsonb;
  v_bloco public.br_blocos_apostas%rowtype;
  v_antes jsonb;
  v_inicio int;
  v_fim int;
  v_total_canonicos int;
  v_primeiro timestamptz;
  v_abre_calculado timestamptz;
  v_fecha_calculado timestamptz;
  v_abre_novo timestamptz;
  v_fecha_novo timestamptz;
  v_primeiro_novo timestamptz;
  v_status_novo text;
  v_palpites bigint;
  v_abriu_agora boolean;
  v_alterou boolean;
  v_result jsonb := '[]'::jsonb;
  v_status_config text;
  v_agora timestamptz := coalesce(p_agora, now());
begin
  if p_temporada is null or p_temporada < 2020 then raise exception 'Temporada inválida.'; end if;
  if p_abertura_antecedencia_dias < 1 or p_abertura_antecedencia_dias > 30 then raise exception 'Antecedência de abertura inválida.'; end if;
  if p_fechamento_antecedencia_minutos < 1 or p_fechamento_antecedencia_minutos > 1440 then raise exception 'Antecedência de fechamento inválida.'; end if;
  if jsonb_typeof(p_blocos) <> 'array' then raise exception 'Payload de blocos inválido.'; end if;

  for v_item in select * from jsonb_array_elements(p_blocos)
  loop
    v_inicio := coalesce((v_item->>'rodada_inicio')::int, 0);
    v_fim := coalesce((v_item->>'rodada_fim')::int, 0);
    v_total_canonicos := coalesce((v_item->>'total_canonicos')::int, 0);
    v_primeiro := nullif(v_item->>'primeiro_jogo_em','')::timestamptz;

    if v_fim <> v_inicio + 2 or v_inicio not in (21,24,27,30,33,36) then
      raise exception 'Intervalo de bloco inválido: %–%.', v_inicio, v_fim;
    end if;

    select b.* into v_bloco
    from public.br_blocos_apostas b
    where b.temporada = p_temporada
      and b.rodada_inicio = v_inicio
      and b.rodada_fim = v_fim
    for update;
    if v_bloco.id is null then raise exception 'Bloco %–% inexistente.', v_inicio, v_fim; end if;

    select count(*)::bigint into v_palpites
    from public.br_palpites p
    where p.temporada = p_temporada
      and p.rodada between v_inicio and v_fim;

    v_antes := to_jsonb(v_bloco);
    v_abriu_agora := false;
    v_alterou := false;

    -- Sem os 30 confrontos canônicos ou sem nenhum kickoff confiável, nunca
    -- inventa janela. Configuração anterior válida é preservada.
    if v_total_canonicos = 30 and v_primeiro is not null then
      v_abre_calculado := v_primeiro - make_interval(days => p_abertura_antecedencia_dias);
      v_fecha_calculado := v_primeiro - make_interval(mins => p_fechamento_antecedencia_minutos);

      if v_palpites = 0 then
        -- Antes do primeiro palpite a janela acompanha livremente o calendário.
        v_primeiro_novo := v_primeiro;
        v_abre_novo := v_abre_calculado;
        v_fecha_novo := v_fecha_calculado;
      else
        -- Depois do primeiro palpite, o prazo HISTÓRICO de elegibilidade vive
        -- em fecha_em_congelado. Já fecha_em continua sendo o deadline
        -- OPERACIONAL e precisa respeitar br_blocos_apostas_datas_chk.
        -- Reagendamento nunca pode reabrir/estender a janela: apenas preservar
        -- ou antecipar primeiro jogo, abertura e fechamento operacionais.
        v_primeiro_novo := case
          when v_bloco.primeiro_jogo_em is null then v_primeiro
          else least(v_bloco.primeiro_jogo_em, v_primeiro)
        end;
        v_abre_novo := case
          when v_bloco.abre_em is null then v_abre_calculado
          else least(v_bloco.abre_em, v_abre_calculado)
        end;
        v_fecha_novo := case
          when v_bloco.fecha_em is null then v_fecha_calculado
          else least(v_bloco.fecha_em, v_fecha_calculado)
        end;
      end if;

      if v_bloco.status in ('fechada','bloqueada') then
        v_status_novo := v_bloco.status; -- reabertura automática proibida
      elsif v_agora < v_abre_novo then
        v_status_novo := 'programada';
      elsif v_agora < v_fecha_novo then
        v_status_novo := 'aberta';
      else
        v_status_novo := 'fechada';
      end if;

      v_abriu_agora := v_status_novo = 'aberta' and v_bloco.status <> 'aberta';

      update public.br_blocos_apostas b
      set primeiro_jogo_em = v_primeiro_novo,
          abre_em = v_abre_novo,
          fecha_em = v_fecha_novo,
          status = v_status_novo,
          sincronizado_em = v_agora,
          sincronizacao_origem = nullif(trim(coalesce(p_origem,'')), ''),
          politica_automatica_versao = 1,
          versao = case when
            b.primeiro_jogo_em is distinct from v_primeiro_novo
            or b.abre_em is distinct from v_abre_novo
            or b.fecha_em is distinct from v_fecha_novo
            or b.status is distinct from v_status_novo
            then b.versao + 1 else b.versao end,
          atualizado_em = case when
            b.primeiro_jogo_em is distinct from v_primeiro_novo
            or b.abre_em is distinct from v_abre_novo
            or b.fecha_em is distinct from v_fecha_novo
            or b.status is distinct from v_status_novo
            then now() else b.atualizado_em end
      where b.id = v_bloco.id
      returning b.* into v_bloco;

      -- `sincronizado_em` muda em toda execução e não deve gerar auditoria/versão falsa.
      v_alterou := v_bloco.versao <> coalesce((v_antes->>'versao')::bigint, v_bloco.versao);

      -- Metadados do jogo podem ser reconciliados, mas o deadline histórico
      -- gravado em palpites já aceitos não é reescrito por reagendamento.
      update public.br_palpites p
      set fecha_em = coalesce(p.fecha_em, v_bloco.fecha_em_congelado, v_bloco.fecha_em)
      where p.temporada = p_temporada
        and p.rodada between v_inicio and v_fim
        and p.fecha_em is null
        and coalesce(v_bloco.fecha_em_congelado, v_bloco.fecha_em) is not null;

      -- Materializa as três rodadas. Publicação continua automática no fecha_em.
      v_status_config := case v_bloco.status
        when 'programada' then 'programada'
        when 'aberta' then 'aberta'
        when 'fechada' then 'fechada'
        when 'bloqueada' then 'bloqueada'
        else 'futura'
      end;

      insert into public.br_config_rodadas
        (temporada, rodada, abre_em, fecha_em, publica_em, status, observacao, bloco_id, atualizado_em)
      select
        p_temporada, gs.rodada, v_bloco.abre_em, v_bloco.fecha_em, v_bloco.fecha_em,
        v_status_config,
        concat('Janela automática do ', v_bloco.nome, ' · Execução 21'),
        v_bloco.id, now()
      from generate_series(v_inicio, v_fim) as gs(rodada)
      on conflict (temporada, rodada)
      do update set
        abre_em = case
          when public.br_config_rodadas.status in ('publicada','apurada') then public.br_config_rodadas.abre_em
          else excluded.abre_em end,
        fecha_em = case
          when public.br_config_rodadas.status in ('publicada','apurada') then public.br_config_rodadas.fecha_em
          else excluded.fecha_em end,
        publica_em = case
          when public.br_config_rodadas.status in ('publicada','apurada') then public.br_config_rodadas.publica_em
          else excluded.publica_em end,
        status = case
          when public.br_config_rodadas.status in ('publicada','apurada') then public.br_config_rodadas.status
          else excluded.status end,
        bloco_id = excluded.bloco_id,
        atualizado_em = now();

      if v_alterou then
        insert into public.br_blocos_apostas_auditoria
          (bloco_id, temporada, rodada_inicio, rodada_fim, admin_id, acao,
           versao_anterior, versao_nova, antes, depois, justificativa)
        values
          (v_bloco.id, p_temporada, v_inicio, v_fim, null,
           case when v_abriu_agora then 'abertura_automatica_exec21'
                when v_bloco.status = 'fechada' then 'fechamento_automatico_exec21'
                else 'sincronizacao_automatica_exec21' end,
           coalesce((v_antes->>'versao')::bigint, v_bloco.versao), v_bloco.versao,
           v_antes, to_jsonb(v_bloco),
           'Sincronização automática pela matriz canônica; fecha_em é operacional e fecha_em_congelado preserva a elegibilidade histórica.');
      end if;
    else
      update public.br_blocos_apostas b
      set sincronizado_em = v_agora,
          sincronizacao_origem = nullif(trim(coalesce(p_origem,'')), '')
      where b.id = v_bloco.id
      returning b.* into v_bloco;
    end if;

    v_result := v_result || jsonb_build_array(jsonb_build_object(
      'bloco_id', v_bloco.id,
      'rodada_inicio', v_inicio,
      'rodada_fim', v_fim,
      'nome', v_bloco.nome,
      'total_canonicos', v_total_canonicos,
      'primeiro_jogo_em', v_bloco.primeiro_jogo_em,
      'abre_em', v_bloco.abre_em,
      'fecha_em', v_bloco.fecha_em,
      'status', v_bloco.status,
      'total_palpites', v_palpites,
      'jogos_apurados', coalesce(v_bloco.jogos_apurados,0),
      'apuracao_concluida', coalesce(v_bloco.apuracao_concluida,false),
      'abriu_agora', v_abriu_agora,
      'email_abertura_pendente', v_bloco.status = 'aberta' and v_bloco.abertura_email_enviado_em is null,
      'abertura_email_enviado_em', v_bloco.abertura_email_enviado_em,
      'abertura_email_ultima_tentativa_em', v_bloco.abertura_email_ultima_tentativa_em,
      'alterou', v_alterou
    ));
  end loop;

  return jsonb_build_object('temporada', p_temporada, 'agora', v_agora, 'blocos', v_result);
end;
$$;

revoke all on function public.br_pipeline_sincronizar_blocos_v1(int,timestamptz,int,int,jsonb,text) from public;
revoke all on function public.br_pipeline_sincronizar_blocos_v1(int,timestamptz,int,int,jsonb,text) from anon;
revoke all on function public.br_pipeline_sincronizar_blocos_v1(int,timestamptz,int,int,jsonb,text) from authenticated;
grant execute on function public.br_pipeline_sincronizar_blocos_v1(int,timestamptz,int,int,jsonb,text) to service_role;

-- --------------------------------------------------------------------------
-- 6. Salvamento v1: progressivo durante a janela; elegibilidade só em 30/30
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
  v_jogo_uid text;
  v_pm int;
  v_pv int;
  v_payload_hash text;
  v_hash text;
  v_total int;
  v_antigo jsonb;
  v_deadline timestamptz; -- deadline operacional para aceitar nova gravação
  v_deadline_historico timestamptz; -- fato congelado para elegibilidade/auditoria
  v_agora timestamptz := now();
begin
  if not public.br_validar_sessao(p_participante_id, p_token, false) then
    raise exception 'Sessão inválida.';
  end if;

  select p.* into v_part
  from public.br_participantes p
  where p.id = p_participante_id and p.ativo = true;
  if v_part.id is null then raise exception 'Participante inválido.'; end if;

  select b.* into v_bloco
  from public.br_blocos_apostas b
  where b.id = p_bloco_id and b.temporada = p_temporada
  for update;
  if v_bloco.id is null then raise exception 'Bloco de apostas não encontrado.'; end if;

  -- A primeira gravação congela o fechamento que estava valendo para todos.
  -- Reagendamentos posteriores da CBF/ESPN não podem mudar retroativamente
  -- a regra de elegibilidade do participante.
  if v_bloco.fecha_em_congelado is null and v_bloco.fecha_em is not null then
    update public.br_blocos_apostas
    set fecha_em_congelado = fecha_em,
        fechamento_congelado_em = coalesce(fechamento_congelado_em, v_agora)
    where id = v_bloco.id
    returning * into v_bloco;
  end if;
  v_deadline_historico := coalesce(v_bloco.fecha_em_congelado, v_bloco.fecha_em);
  -- Nunca aceita nova gravação depois do deadline operacional atual, mesmo que
  -- o histórico congelado seja posterior por causa de um reagendamento antigo.
  v_deadline := case
    when v_bloco.fecha_em is not null and v_deadline_historico is not null
      then least(v_bloco.fecha_em, v_deadline_historico)
    else coalesce(v_bloco.fecha_em, v_deadline_historico)
  end;

  if v_bloco.abre_em is null or v_deadline is null then
    raise exception 'O bloco ainda não possui janela configurada.';
  end if;
  if v_bloco.status not in ('programada','aberta') then
    raise exception 'Bloco fora da janela de apostas.';
  end if;
  if v_agora < v_bloco.abre_em or v_agora >= v_deadline then
    raise exception 'Bloco fora da janela de apostas.';
  end if;

  if jsonb_typeof(p_palpites) <> 'array' then raise exception 'Payload inválido.'; end if;
  if jsonb_array_length(p_palpites) < 1 or jsonb_array_length(p_palpites) > 30 then
    raise exception 'Envie entre 1 e 30 palpites por salvamento.';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(p_palpites) x
    group by coalesce(nullif(x->>'jogo_uid',''), x->>'event_id')
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
    begin
      v_rodada := (v_item->>'rodada')::int;
      v_pm := (v_item->>'placar_mandante')::int;
      v_pv := (v_item->>'placar_visitante')::int;
    exception when others then
      raise exception 'Rodada ou placar inválido no jogo %.', coalesce(nullif(v_event_id,''), '?');
    end;

    if v_rodada < v_bloco.rodada_inicio or v_rodada > v_bloco.rodada_fim then
      raise exception 'A rodada % não pertence ao bloco %–%.', v_rodada, v_bloco.rodada_inicio, v_bloco.rodada_fim;
    end if;
    if v_pm < 0 or v_pv < 0 or v_pm > 30 or v_pv > 30 then
      raise exception 'Placar inválido no jogo %.', coalesce(nullif(v_event_id,''), '?');
    end if;

    v_jogo_uid := nullif(trim(coalesce(v_item->>'jogo_uid', '')), '');
    if v_jogo_uid is null then
      v_jogo_uid := public.br_jogo_uid_v1(
        p_temporada, v_rodada, v_item->>'mandante', v_item->>'visitante'
      );
    end if;
    if v_jogo_uid <> public.br_jogo_uid_v1(
      p_temporada, v_rodada, v_item->>'mandante', v_item->>'visitante'
    ) then
      raise exception 'jogo_uid incompatível com rodada/mandante/visitante.';
    end if;
    if v_event_id = '' then
      -- event_id pode ainda não existir para jogo futuro; o UID canônico é a
      -- identidade real. Um alias sintético, estável, evita campo NOT NULL vazio.
      v_event_id := 'canon:' || encode(digest(v_jogo_uid, 'sha256'), 'hex');
    end if;

    select to_jsonb(p.*) into v_antigo
    from public.br_palpites p
    where p.temporada = p_temporada
      and p.jogo_uid = v_jogo_uid
      and p.participante_id = p_participante_id;

    insert into public.br_palpites (
      temporada, rodada, event_id, jogo_chave, jogo_uid, bloco_id, participante_id,
      membro, mandante, visitante, placar_mandante, placar_visitante,
      kickoff, fecha_em, palpite_atualizado_em, origem, hash_fechamento, hash_bloco, versao
    ) values (
      p_temporada, v_rodada, v_event_id, v_item->>'jogo_chave', v_jogo_uid, v_bloco.id,
      p_participante_id, v_part.nome, v_item->>'mandante', v_item->>'visitante',
      v_pm, v_pv, nullif(v_item->>'kickoff','')::timestamptz,
      v_deadline, v_agora, 'site-logado-bloco-v2', v_payload_hash, null, 4
    )
    on conflict (temporada, jogo_uid, participante_id)
      where participante_id is not null and jogo_uid is not null
    do update set
      rodada = excluded.rodada,
      event_id = excluded.event_id,
      jogo_chave = excluded.jogo_chave,
      bloco_id = excluded.bloco_id,
      membro = excluded.membro,
      mandante = excluded.mandante,
      visitante = excluded.visitante,
      placar_mandante = excluded.placar_mandante,
      placar_visitante = excluded.placar_visitante,
      kickoff = excluded.kickoff,
      fecha_em = excluded.fecha_em,
      palpite_atualizado_em = v_agora,
      origem = excluded.origem,
      hash_fechamento = excluded.hash_fechamento,
      versao = excluded.versao;

    insert into public.br_palpites_auditoria
      (temporada, rodada, event_id, participante_id, membro, acao,
       antes, depois, hash_fechamento)
    values
      (p_temporada, v_rodada, v_event_id, p_participante_id, v_part.nome,
       case when v_antigo is null then 'insert_bloco_uid' else 'update_bloco_uid' end,
       v_antigo, v_item || jsonb_build_object('jogo_uid', v_jogo_uid), v_payload_hash);
  end loop;

  if exists (
    select 1
    from public.br_palpites p
    where p.participante_id = p_participante_id
      and p.temporada = p_temporada
      and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    group by p.rodada
    having count(distinct p.jogo_uid) > 10
  ) then
    raise exception 'Há mais de 10 palpites canônicos em uma rodada do bloco.';
  end if;

  select count(distinct p.jogo_uid)::int into v_total
  from public.br_palpites p
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim;
  if v_total > 30 then raise exception 'O bloco possui mais de 30 palpites canônicos.'; end if;

  select encode(digest(
    p_temporada::text || '|' || v_bloco.rodada_inicio::text || '-' ||
    v_bloco.rodada_fim::text || '|' || p_participante_id::text || '|' ||
    coalesce(string_agg(
      p.rodada::text || '|' || coalesce(p.jogo_uid, p.event_id) || '|' ||
      p.placar_mandante::text || '|' || p.placar_visitante::text,
      E'\n' order by p.rodada, coalesce(p.jogo_uid, p.event_id)
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
      fecha_em = v_deadline,
      versao = greatest(coalesce(p.versao, 2), 4)
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    and (p.bloco_id is distinct from v_bloco.id
      or p.hash_bloco is distinct from v_hash
      or p.hash_fechamento is distinct from v_hash
      or p.fecha_em is distinct from v_deadline
      or p.versao < 4);

  insert into public.br_comprovantes_blocos
    (temporada, bloco_id, participante_id, total_palpites, total_jogos,
     hash_bloco, payload_hash, elegivel, elegibilidade_motivo,
     concluido_em, fecha_em_congelado, excecao_administrativa,
     ultima_edicao_usuario_em)
  values
    (p_temporada, v_bloco.id, p_participante_id, v_total, 30,
     v_hash, v_payload_hash, v_total = 30,
     case when v_total = 30 then '30/30 concluídos dentro da janela congelada'
          else format('incompleto: %s/30', v_total) end,
     case when v_total = 30 then v_agora else null end,
     v_deadline_historico, false, v_agora)
  on conflict on constraint br_comprovantes_blocos_unico
  do update set
    total_palpites = excluded.total_palpites,
    total_jogos = 30,
    hash_bloco = excluded.hash_bloco,
    payload_hash = excluded.payload_hash,
    elegivel = case
      when public.br_comprovantes_blocos.excecao_administrativa then true
      else excluded.elegivel
    end,
    elegibilidade_motivo = case
      when public.br_comprovantes_blocos.excecao_administrativa
        then public.br_comprovantes_blocos.elegibilidade_motivo
      else excluded.elegibilidade_motivo
    end,
    concluido_em = case
      when public.br_comprovantes_blocos.excecao_administrativa
        then public.br_comprovantes_blocos.concluido_em
      else coalesce(public.br_comprovantes_blocos.concluido_em, excluded.concluido_em)
    end,
    fecha_em_congelado = coalesce(public.br_comprovantes_blocos.fecha_em_congelado, excluded.fecha_em_congelado),
    ultima_edicao_usuario_em = excluded.ultima_edicao_usuario_em,
    atualizado_em = now();

  return query
  select v_bloco.id, v_bloco.rodada_inicio, v_bloco.rodada_fim,
         v_total, 30, 30 - v_total, v_total = 30, v_hash, now();
end;
$$;

revoke all on function public.br_salvar_palpites_bloco_v1(uuid,text,int,uuid,jsonb) from public;
grant execute on function public.br_salvar_palpites_bloco_v1(uuid,text,int,uuid,jsonb) to anon;

-- --------------------------------------------------------------------------
-- 7. Palpites públicos: só participantes elegíveis (inclui exceção MEC)
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
         p.criado_em, coalesce(p.palpite_atualizado_em, p.atualizado_em)
  from public.br_palpites p
  join public.br_participantes bp
    on bp.id = p.participante_id and bp.ativo = true
  join public.br_config_rodadas c
    on c.temporada = p.temporada and c.rodada = p.rodada
   and (c.status in ('publicada','apurada')
        or (c.publica_em is not null and now() >= c.publica_em))
  join public.br_comprovantes_blocos cb
    on cb.temporada = p.temporada
   and cb.bloco_id = v_bloco.id
   and cb.participante_id = p.participante_id
   and cb.elegivel is true
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

-- --------------------------------------------------------------------------
-- Validação pós-migração (somente leitura)
-- --------------------------------------------------------------------------
-- Esperado no bloco 21–23:
--   br_blocos_apostas.fecha_em             = deadline OPERACIONAL válido
--   br_blocos_apostas.fecha_em_congelado   = 2026-07-29 21:30:00+00
--   fecha_em < primeiro_jogo_em             = true (constraint preservada)
--   Carlinhos: elegivel=true, 30/30
--   Armínio:   elegivel=true, 30/30
--   MEC:       elegivel=true, 25/30, excecao_administrativa=true
--
-- select rodada_inicio, rodada_fim, primeiro_jogo_em, fecha_em,
--        fecha_em_congelado, (fecha_em < primeiro_jogo_em) as datas_validas
-- from public.br_blocos_apostas
-- where temporada = 2026 and rodada_inicio = 21 and rodada_fim = 23;
--
-- select bp.nome, cb.total_palpites, cb.total_jogos, cb.elegivel,
--        cb.excecao_administrativa, cb.concluido_em, cb.ultima_edicao_usuario_em,
--        cb.fecha_em_congelado, cb.elegibilidade_motivo
-- from public.br_comprovantes_blocos cb
-- join public.br_participantes bp on bp.id = cb.participante_id
-- join public.br_blocos_apostas b on b.id = cb.bloco_id
-- where cb.temporada = 2026 and b.rodada_inicio = 21 and b.rodada_fim = 23
-- order by bp.nome;

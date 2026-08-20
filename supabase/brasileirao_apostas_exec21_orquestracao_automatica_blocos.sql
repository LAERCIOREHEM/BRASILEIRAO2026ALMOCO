-- ============================================================================
-- Supabase — Bolão Brasileirão 2026
-- Execução 21: orquestração automática e independente dos blocos 21–38
--
-- Regras centrais:
-- * cada bloco de três rodadas mantém exatamente 30 jogos canônicos;
-- * apostas e apuração possuem relógios independentes;
-- * o bloco seguinte pode abrir mesmo com o anterior ainda em apuração;
-- * abre automaticamente 7 dias antes do primeiro kickoff confiável do bloco;
-- * fecha 1 hora antes do primeiro kickoff confiável entre TODOS os 30 jogos;
-- * depois do primeiro palpite, o pipeline pode ENCURTAR o prazo se houver
--   antecipação, mas nunca o estende automaticamente;
-- * bloco fechado/bloqueado nunca é reaberto automaticamente;
-- * jogo adiado continua na rodada/bloco original;
-- * jogo_uid canônico desacopla o palpite do event_id externo da ESPN;
-- * e-mail de abertura é deduplicado por bloco.
--
-- Pré-requisitos: Execuções 18, 19 e 20 já aplicadas neste mesmo projeto.
-- Aplicação: Supabase Dashboard > SQL Editor > executar este arquivo inteiro.
-- Idempotente: pode ser reaplicado.
-- ============================================================================

begin;

create extension if not exists pgcrypto;

-- --------------------------------------------------------------------------
-- 1. Identidade canônica do jogo, resistente a troca de event_id/data
-- --------------------------------------------------------------------------

create or replace function public.br_jogo_uid_v1(
  p_temporada int,
  p_rodada int,
  p_mandante text,
  p_visitante text
)
returns text
language sql
immutable
as $$
  select concat(
    coalesce(p_temporada, 0)::text, '|',
    coalesce(p_rodada, 0)::text, '|',
    lower(trim(coalesce(p_mandante, ''))), '|',
    lower(trim(coalesce(p_visitante, '')))
  );
$$;

alter table public.br_palpites
  add column if not exists jogo_uid text;

-- `atualizado_em` possui trigger global e também muda quando o PIPELINE apenas
-- ajusta metadados (deadline/hash). Por isso guardamos separadamente o instante
-- da última edição efetiva feita pelo participante. Essa coluna é a autoridade
-- para validar se um palpite foi gravado dentro do prazo.
alter table public.br_palpites
  add column if not exists palpite_atualizado_em timestamptz;

update public.br_palpites
set jogo_uid = public.br_jogo_uid_v1(temporada, rodada, mandante, visitante)
where nullif(trim(coalesce(jogo_uid, '')), '') is null;

update public.br_palpites
set palpite_atualizado_em = coalesce(atualizado_em, criado_em)
where palpite_atualizado_em is null;

-- Caso histórico extremamente defensivo: se dois event_ids externos diferentes
-- já tiverem criado duas linhas para o MESMO jogo/participante, preserva a linha
-- mais recente e registra a deduplicação antes de remover a mais antiga.
with ranked as (
  select p.*,
         row_number() over (
           partition by p.temporada, p.jogo_uid, p.participante_id
           order by p.palpite_atualizado_em desc nulls last, p.atualizado_em desc nulls last, p.criado_em desc nulls last, p.id desc
         ) as rn
  from public.br_palpites p
  where p.participante_id is not null
    and nullif(trim(coalesce(p.jogo_uid, '')), '') is not null
), dup as (
  select * from ranked where rn > 1
)
insert into public.br_palpites_auditoria
  (temporada, rodada, event_id, participante_id, membro, acao, antes, depois, hash_fechamento)
select temporada, rodada, event_id, participante_id, membro,
       'dedupe_jogo_uid_exec21', to_jsonb(dup), null, hash_fechamento
from dup;

with ranked as (
  select p.id,
         row_number() over (
           partition by p.temporada, p.jogo_uid, p.participante_id
           order by p.palpite_atualizado_em desc nulls last, p.atualizado_em desc nulls last, p.criado_em desc nulls last, p.id desc
         ) as rn
  from public.br_palpites p
  where p.participante_id is not null
    and nullif(trim(coalesce(p.jogo_uid, '')), '') is not null
)
delete from public.br_palpites p
using ranked r
where p.id = r.id and r.rn > 1;

create unique index if not exists br_palpites_jogo_uid_participante_idx
  on public.br_palpites (temporada, jogo_uid, participante_id)
  where participante_id is not null and jogo_uid is not null;

create index if not exists br_palpites_jogo_uid_idx
  on public.br_palpites (temporada, jogo_uid);

-- --------------------------------------------------------------------------
-- 2. Metadados da automação e deduplicação do e-mail de abertura
-- --------------------------------------------------------------------------

alter table public.br_blocos_apostas
  add column if not exists sincronizado_em timestamptz;
alter table public.br_blocos_apostas
  add column if not exists sincronizacao_origem text;
alter table public.br_blocos_apostas
  add column if not exists abertura_email_enviado_em timestamptz;
alter table public.br_blocos_apostas
  add column if not exists abertura_email_ultima_tentativa_em timestamptz;
alter table public.br_blocos_apostas
  add column if not exists politica_automatica_versao int not null default 1;

-- --------------------------------------------------------------------------
-- 3. Substitui o salvamento do bloco: jogo_uid é a chave lógica; event_id vira
--    alias externo atualizável. A assinatura pública da RPC permanece igual.
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

  if v_bloco.abre_em is null or v_bloco.fecha_em is null then
    raise exception 'O bloco ainda não possui janela configurada.';
  end if;
  if v_bloco.status not in ('programada','aberta') then
    raise exception 'Bloco fora da janela de apostas.';
  end if;
  if v_agora < v_bloco.abre_em or v_agora >= v_bloco.fecha_em then
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
      v_bloco.fecha_em, v_agora, 'site-logado-bloco-v2', v_payload_hash, null, 4
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
      fecha_em = v_bloco.fecha_em,
      versao = greatest(coalesce(p.versao, 2), 4)
  where p.participante_id = p_participante_id
    and p.temporada = p_temporada
    and p.rodada between v_bloco.rodada_inicio and v_bloco.rodada_fim
    and (p.bloco_id is distinct from v_bloco.id
      or p.hash_bloco is distinct from v_hash
      or p.hash_fechamento is distinct from v_hash
      or p.fecha_em is distinct from v_bloco.fecha_em
      or p.versao < 4);

  insert into public.br_comprovantes_blocos
    (temporada, bloco_id, participante_id, total_palpites, total_jogos, hash_bloco, payload_hash)
  values
    (p_temporada, v_bloco.id, p_participante_id, v_total, 30, v_hash, v_payload_hash)
  on conflict on constraint br_comprovantes_blocos_unico
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

-- As RPCs públicas mantêm a mesma assinatura, mas exibem como `atualizado_em`
-- a última edição feita pelo participante, e não uma atualização técnica do
-- pipeline em deadline/hash. Assim o comprovante visual não muda de horário
-- quando o sistema apenas reconcilia o calendário.
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
         p.criado_em, coalesce(p.palpite_atualizado_em, p.atualizado_em)
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

-- --------------------------------------------------------------------------
-- 4. RPC do pipeline: sincroniza os seis blocos sem depender da conclusão do
--    bloco anterior. Nenhuma decisão esportiva é tomada no banco: o Python
--    fornece somente os 30 confrontos e o primeiro kickoff confiável.
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
        -- Depois do primeiro palpite, uma antecipação pode reduzir o prazo para
        -- proteger a equidade; adiamento nunca concede tempo adicional.
        v_primeiro_novo := case
          when v_bloco.primeiro_jogo_em is null then v_primeiro
          else least(v_bloco.primeiro_jogo_em, v_primeiro)
        end;
        v_abre_novo := coalesce(v_bloco.abre_em, v_abre_calculado);
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

      -- Se o calendário antecipou o primeiro jogo depois de já existirem palpites,
      -- o deadline gravado em cada palpite também precisa ser encurtado. Nunca
      -- estende o prazo de um palpite já existente.
      update public.br_palpites p
      set fecha_em = case
            when p.fecha_em is null then v_bloco.fecha_em
            else least(p.fecha_em, v_bloco.fecha_em)
          end
      where p.temporada = p_temporada
        and p.rodada between v_inicio and v_fim
        and v_bloco.fecha_em is not null
        and (p.fecha_em is null or p.fecha_em > v_bloco.fecha_em);

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
           'Sincronização automática pela matriz canônica; prazo nunca é estendido após o primeiro palpite.');
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

create or replace function public.br_pipeline_marcar_email_abertura_v1(
  p_temporada int,
  p_bloco_id uuid,
  p_enviado_em timestamptz default now()
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_rows integer := 0;
begin
  update public.br_blocos_apostas
  set abertura_email_enviado_em = coalesce(abertura_email_enviado_em, p_enviado_em),
      abertura_email_ultima_tentativa_em = p_enviado_em
  where id = p_bloco_id
    and temporada = p_temporada
    and status = 'aberta'
    and abertura_email_enviado_em is null;
  get diagnostics v_rows = row_count;
  return v_rows > 0;
end;
$$;

revoke all on function public.br_pipeline_marcar_email_abertura_v1(int,uuid,timestamptz) from public;
revoke all on function public.br_pipeline_marcar_email_abertura_v1(int,uuid,timestamptz) from anon;
revoke all on function public.br_pipeline_marcar_email_abertura_v1(int,uuid,timestamptz) from authenticated;
grant execute on function public.br_pipeline_marcar_email_abertura_v1(int,uuid,timestamptz) to service_role;

create or replace function public.br_pipeline_marcar_tentativa_email_abertura_v1(
  p_temporada int,
  p_bloco_id uuid,
  p_tentativa_em timestamptz default now()
)
returns void
language sql
security definer
set search_path = public
as $$
  update public.br_blocos_apostas
  set abertura_email_ultima_tentativa_em = p_tentativa_em
  where id = p_bloco_id and temporada = p_temporada;
$$;

revoke all on function public.br_pipeline_marcar_tentativa_email_abertura_v1(int,uuid,timestamptz) from public;
revoke all on function public.br_pipeline_marcar_tentativa_email_abertura_v1(int,uuid,timestamptz) from anon;
revoke all on function public.br_pipeline_marcar_tentativa_email_abertura_v1(int,uuid,timestamptz) from authenticated;
grant execute on function public.br_pipeline_marcar_tentativa_email_abertura_v1(int,uuid,timestamptz) to service_role;

-- --------------------------------------------------------------------------
-- 5. Leitura pública v4: acrescenta estado do bloco sem quebrar consumidores.
-- --------------------------------------------------------------------------

create or replace function public.br_listar_config_rodadas_v4(
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
  bloco_versao bigint,
  bloco_status text,
  bloco_jogos_apurados int,
  bloco_apuracao_concluida boolean,
  bloco_sincronizado_em timestamptz
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
    b.primeiro_jogo_em, b.versao, b.status, b.jogos_apurados,
    b.apuracao_concluida, b.sincronizado_em
  from public.br_config_rodadas c
  left join public.br_blocos_apostas b on b.id = c.bloco_id
  where c.temporada = p_temporada
  order by c.rodada;
$$;

revoke all on function public.br_listar_config_rodadas_v4(int) from public;
grant execute on function public.br_listar_config_rodadas_v4(int) to anon;

commit;

-- Verificações sugeridas após aplicar:
-- select rodada_inicio, rodada_fim, status, abre_em, fecha_em, jogos_apurados,
--        apuracao_concluida, abertura_email_enviado_em
-- from public.br_blocos_apostas where temporada=2026 order by rodada_inicio;
--
-- select temporada, rodada, count(distinct jogo_uid)
-- from public.br_palpites where temporada=2026 group by temporada, rodada order by rodada;

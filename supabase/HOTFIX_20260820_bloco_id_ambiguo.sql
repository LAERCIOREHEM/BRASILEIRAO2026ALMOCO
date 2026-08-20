-- HOTFIX 2026-08-20 — Bolão Brasileirão 2026
-- Corrige: ERROR column reference "bloco_id" is ambiguous
-- Causa: o nome da coluna de retorno `bloco_id` colidia com `bloco_id` no
-- alvo de ON CONFLICT da tabela br_comprovantes_blocos.
--
-- Efeito: substitui somente a RPC br_salvar_palpites_bloco_v1.
-- Não apaga palpites, participantes, ligas, blocos ou comprovantes.
-- Pode ser executado no Supabase > SQL Editor > New query > Run.

begin;

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

commit;

-- Verificação não destrutiva: deve retornar 1 linha com o constraint usado pelo hotfix.
select conname, pg_get_constraintdef(oid) as definicao
from pg_constraint
where conrelid = 'public.br_comprovantes_blocos'::regclass
  and conname = 'br_comprovantes_blocos_unico';

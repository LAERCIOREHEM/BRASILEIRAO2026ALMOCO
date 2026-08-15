-- ============================================================================
-- Supabase — Bolão Brasileirão 2026
-- Execução 22: ranking simples por bloco + e-mail único de conclusão
--
-- Complementa a Execução 21 sem alterar palpites, pontuação ou deadlines.
-- * R20 continua histórico e independente;
-- * blocos 21–23 ... 36–38 continuam independentes;
-- * o pipeline pode avisar uma única vez quando um bloco chegar a 30/30;
-- * deduplicação e retentativa do e-mail ficam persistidas no banco.
--
-- Pré-requisito: Execução 21 aplicada.
-- Aplicação: Supabase Dashboard > SQL Editor > executar este arquivo inteiro.
-- Idempotente: pode ser reaplicado.
-- ============================================================================

begin;

alter table public.br_blocos_apostas
  add column if not exists conclusao_email_enviado_em timestamptz;

alter table public.br_blocos_apostas
  add column if not exists conclusao_email_ultima_tentativa_em timestamptz;

-- Leitura exclusiva do pipeline. Retorna todos os blocos para que o script
-- consiga tanto descobrir pendências quanto auditar a deduplicação.
create or replace function public.br_pipeline_status_emails_conclusao_v1(
  p_temporada int default 2026
)
returns table (
  bloco_id uuid,
  rodada_inicio int,
  rodada_fim int,
  apuracao_concluida boolean,
  apurado_em timestamptz,
  conclusao_email_enviado_em timestamptz,
  conclusao_email_ultima_tentativa_em timestamptz,
  email_conclusao_pendente boolean
)
language sql
security definer
set search_path = public
as $$
  select
    b.id,
    b.rodada_inicio,
    b.rodada_fim,
    coalesce(b.apuracao_concluida, false),
    b.apurado_em,
    b.conclusao_email_enviado_em,
    b.conclusao_email_ultima_tentativa_em,
    coalesce(b.apuracao_concluida, false)
      and b.conclusao_email_enviado_em is null
  from public.br_blocos_apostas b
  where b.temporada = p_temporada
  order by b.rodada_inicio;
$$;

revoke all on function public.br_pipeline_status_emails_conclusao_v1(int) from public;
revoke all on function public.br_pipeline_status_emails_conclusao_v1(int) from anon;
revoke all on function public.br_pipeline_status_emails_conclusao_v1(int) from authenticated;
grant execute on function public.br_pipeline_status_emails_conclusao_v1(int) to service_role;

create or replace function public.br_pipeline_marcar_tentativa_email_conclusao_v1(
  p_temporada int,
  p_bloco_id uuid,
  p_tentativa_em timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_tentativa_em is null then
    raise exception 'Instante da tentativa obrigatório.';
  end if;

  update public.br_blocos_apostas b
  set conclusao_email_ultima_tentativa_em = p_tentativa_em,
      atualizado_em = now()
  where b.temporada = p_temporada
    and b.id = p_bloco_id
    and coalesce(b.apuracao_concluida, false) = true
    and b.conclusao_email_enviado_em is null;

  return found;
end;
$$;

revoke all on function public.br_pipeline_marcar_tentativa_email_conclusao_v1(int,uuid,timestamptz) from public;
revoke all on function public.br_pipeline_marcar_tentativa_email_conclusao_v1(int,uuid,timestamptz) from anon;
revoke all on function public.br_pipeline_marcar_tentativa_email_conclusao_v1(int,uuid,timestamptz) from authenticated;
grant execute on function public.br_pipeline_marcar_tentativa_email_conclusao_v1(int,uuid,timestamptz) to service_role;

create or replace function public.br_pipeline_marcar_email_conclusao_v1(
  p_temporada int,
  p_bloco_id uuid,
  p_enviado_em timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$;
begin
  if p_enviado_em is null then
    raise exception 'Instante do envio obrigatório.';
  end if;

  update public.br_blocos_apostas b
  set conclusao_email_enviado_em = coalesce(b.conclusao_email_enviado_em, p_enviado_em),
      conclusao_email_ultima_tentativa_em = p_enviado_em,
      atualizado_em = now()
  where b.temporada = p_temporada
    and b.id = p_bloco_id
    and coalesce(b.apuracao_concluida, false) = true
    and b.conclusao_email_enviado_em is null;

  return found;
end;
$$;

revoke all on function public.br_pipeline_marcar_email_conclusao_v1(int,uuid,timestamptz) from public;
revoke all on function public.br_pipeline_marcar_email_conclusao_v1(int,uuid,timestamptz) from anon;
revoke all on function public.br_pipeline_marcar_email_conclusao_v1(int,uuid,timestamptz) from authenticated;
grant execute on function public.br_pipeline_marcar_email_conclusao_v1(int,uuid,timestamptz) to service_role;

commit;

-- Validações úteis após aplicar:
-- select rodada_inicio, rodada_fim, apuracao_concluida,
--        conclusao_email_enviado_em, conclusao_email_ultima_tentativa_em
-- from public.br_blocos_apostas
-- where temporada = 2026
-- order by rodada_inicio;

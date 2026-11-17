-- Milhão: planos, uso do Filtrão e fotos de perfil.
-- Rodar uma vez no SQL Editor do Supabase. Pode rodar de novo sem estragar nada.

-- 1) Assinatura de cada pessoa. Quem usa o site só LÊ a própria linha;
--    quem escreve é o servidor (função "assinatura", com a chave secreta), quando o Mercado Pago avisa.
create table if not exists public.assinaturas (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  plano         text not null default 'gratis' check (plano in ('gratis', 'ouro')),
  status        text not null default 'inativa',      -- ativa, pendente, pausada, cancelada, inativa
  valido_ate    timestamptz,                           -- até quando o Ouro vale (fim do período pago)
  mp_assinatura text,                                  -- id da assinatura no Mercado Pago
  atualizado_em timestamptz not null default now()
);
alter table public.assinaturas enable row level security;
drop policy if exists "le a propria assinatura" on public.assinaturas;
create policy "le a propria assinatura" on public.assinaturas for select to authenticated using (auth.uid() = user_id);

-- 2) Perguntas ao Filtrão por dia (o plano grátis tem um limite diário)
create table if not exists public.uso_filtrao (
  user_id   uuid not null references auth.users(id) on delete cascade,
  dia       date not null,
  perguntas int  not null default 0,
  primary key (user_id, dia)
);
alter table public.uso_filtrao enable row level security;   -- sem políticas: ninguém lê ou escreve direto

create or replace function public.usar_filtrao() returns int
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  if auth.uid() is null then return null; end if;
  insert into uso_filtrao (user_id, dia, perguntas)
  values (auth.uid(), (now() at time zone 'America/Sao_Paulo')::date, 1)
  on conflict (user_id, dia) do update set perguntas = uso_filtrao.perguntas + 1
  returning perguntas into n;
  return n;
end $$;
revoke all on function public.usar_filtrao() from public, anon;
grant execute on function public.usar_filtrao() to authenticated;

-- 3) Fotos de perfil: pasta pública "avatares", cada pessoa só mexe na própria pasta (o id dela)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('avatares', 'avatares', true, 1048576, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = true, file_size_limit = 1048576, allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp'];

drop policy if exists "foto: ve a propria" on storage.objects;
drop policy if exists "foto: envia a propria" on storage.objects;
drop policy if exists "foto: troca a propria" on storage.objects;
drop policy if exists "foto: apaga a propria" on storage.objects;
create policy "foto: ve a propria" on storage.objects for select to authenticated
  using (bucket_id = 'avatares' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "foto: envia a propria" on storage.objects for insert to authenticated
  with check (bucket_id = 'avatares' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "foto: troca a propria" on storage.objects for update to authenticated
  using (bucket_id = 'avatares' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "foto: apaga a propria" on storage.objects for delete to authenticated
  using (bucket_id = 'avatares' and (storage.foldername(name))[1] = auth.uid()::text);

-- 4) Pagamentos no Pix (30 dias de Ouro cada). Só o servidor lê e escreve.
--    Guarda o registro mesmo se a conta for excluída (a lei pede para manter registros de pagamento).
create table if not exists public.pagamentos_pix (
  id        text primary key,                                   -- número do pagamento no Mercado Pago
  user_id   uuid references auth.users(id) on delete set null,
  valor     numeric(10,2) not null,
  criado_em timestamptz not null default now()
);
alter table public.pagamentos_pix enable row level security;   -- sem políticas: ninguém lê pelo site

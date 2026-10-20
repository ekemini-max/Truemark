-- TrueMark database schema for Supabase (Postgres).
-- Paste this whole file into: Supabase dashboard -> SQL Editor -> New query -> Run.
-- It is safe to run more than once.
--
-- Security model: every table has row level security switched on with NO policies, and the
-- public roles (anon, authenticated) have no privileges. That means the publishable key can
-- read and write nothing. Only the TrueMark server, which holds the secret key, can touch data.

create table if not exists public.profiles (
  id               uuid primary key references auth.users (id) on delete cascade,
  email            text not null,
  full_name        text not null default '',
  institution_name text not null default '',
  role             text not null default 'issuer'  check (role in ('issuer', 'admin')),
  status           text not null default 'pending' check (status in ('pending', 'approved', 'suspended')),
  created_at       timestamptz not null default now(),
  approved_at      timestamptz,
  last_login_at    timestamptz
);
create index if not exists profiles_status_idx on public.profiles (status, created_at desc);

create table if not exists public.records (
  id               uuid primary key default gen_random_uuid(),
  code             text not null unique,
  issuer_id        uuid not null references public.profiles (id),
  institution_name text not null,
  student_name     text not null,
  course           text not null,
  grade            text not null,
  issued_on        date not null,
  salt             text not null,
  record_hash      text not null,
  status           text not null default 'pending' check (status in ('pending', 'active', 'revoked', 'failed')),
  tx_hash          text,
  block_number     bigint,
  chain_name       text,
  anchored_at      timestamptz,
  revoked_at       timestamptz,
  revoked_reason   text,
  anchor_error     text,
  created_at       timestamptz not null default now()
);
create index if not exists records_issuer_idx on public.records (issuer_id, created_at desc);
create index if not exists records_status_idx on public.records (status, created_at desc);

create table if not exists public.audit_log (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  actor_id    uuid,
  actor_email text not null,
  action      text not null,
  target      text not null default '',
  detail      text not null default ''
);
create index if not exists audit_log_created_idx on public.audit_log (created_at desc);

-- Only used when CHAIN_MODE=mock (the clearly-labelled simulation). Unused with a real blockchain.
create table if not exists public.mock_ledger (
  hash       text primary key,
  issuer_ref text not null,
  ts         bigint not null,
  revoked    boolean not null default false
);

-- Lock everything down.
alter table public.profiles    enable row level security;
alter table public.records     enable row level security;
alter table public.audit_log   enable row level security;
alter table public.mock_ledger enable row level security;

revoke all on public.profiles, public.records, public.audit_log, public.mock_ledger from anon, authenticated;

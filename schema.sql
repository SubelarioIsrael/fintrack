create table transactions (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    type text check (type in ('income','expense')) not null,
    amount numeric not null,
    category text not null,
    description text,
    created_at timestamp with time zone default now()
);

create table budgets (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    category text not null,
    monthly_limit numeric not null
);

create table goals (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    name text not null,
    target_amount numeric not null,
    current_amount numeric not null default 0,
    deadline date,
    created_at timestamp with time zone default now()
);

create table recurring (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    type text check (type in ('income','expense')) not null,
    amount numeric not null,
    category text not null,
    description text,
    frequency text check (frequency in ('weekly','monthly')) not null,
    last_run date
);
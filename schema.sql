create table transactions (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    type text check (type in ('income','expense')) not null,
    amount numeric not null,
    category text not null,
    description text,
    created_at timestamp default now()
);

create table budgets (
    id uuid primary key default gen_random_uuid(),
    user_id text not null,
    category text not null,
    monthly_limit numeric not null
);
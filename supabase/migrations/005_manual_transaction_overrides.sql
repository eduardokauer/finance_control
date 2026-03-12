alter table transactions
    add column if not exists manual_override boolean not null default false,
    add column if not exists manual_notes text,
    add column if not exists manual_updated_at timestamptz;

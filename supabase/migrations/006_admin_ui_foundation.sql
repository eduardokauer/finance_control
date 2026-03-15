alter table categories add column if not exists transaction_kind varchar(40);
alter table categories add column if not exists is_active boolean not null default true;
alter table categories add column if not exists created_at timestamptz default now();
alter table categories add column if not exists updated_at timestamptz default now();

update categories
set transaction_kind = case
  when name in ('SalÃ¡rio', 'Reembolsos', 'Outras Receitas') then 'income'
  when name in ('TransferÃªncias') then 'transfer'
  else 'expense'
end
where transaction_kind is null;

alter table categories alter column transaction_kind set not null;

alter table categorization_rules add column if not exists transaction_kind varchar(40);
alter table categorization_rules add column if not exists is_active boolean not null default true;
alter table categorization_rules add column if not exists created_at timestamptz default now();
alter table categorization_rules add column if not exists updated_at timestamptz default now();

update categorization_rules
set transaction_kind = case
  when category_name in ('SalÃ¡rio', 'Reembolsos', 'Outras Receitas') then 'income'
  when category_name in ('TransferÃªncias') then 'transfer'
  else 'expense'
end
where transaction_kind is null;

alter table categorization_rules alter column transaction_kind set not null;

alter table transactions add column if not exists categorization_rule_id bigint references categorization_rules(id);

create table if not exists transaction_audit_logs (
  id bigserial primary key,
  transaction_id bigint not null references transactions(id),
  origin varchar(40) not null,
  previous_category varchar(120),
  new_category varchar(120),
  previous_transaction_kind varchar(40),
  new_transaction_kind varchar(40),
  applied_rule_id bigint references categorization_rules(id),
  notes text,
  created_at timestamptz not null default now()
);

create index if not exists idx_transaction_audit_logs_transaction on transaction_audit_logs(transaction_id, created_at desc);

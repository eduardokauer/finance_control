create table if not exists source_files (
  id bigserial primary key,
  source_type varchar(40) not null,
  file_name varchar(255) not null,
  file_path text not null,
  reference_id varchar(255),
  file_hash varchar(64) not null unique,
  status varchar(40) not null,
  error_message text,
  created_at timestamptz default now()
);

create table if not exists raw_transactions (
  id bigserial primary key,
  source_file_id bigint not null references source_files(id),
  external_id varchar(255),
  raw_payload text not null,
  transaction_date date not null,
  amount numeric(14,2) not null,
  description_raw text not null,
  created_at timestamptz default now()
);

create table if not exists categories (
  id bigserial primary key,
  name varchar(120) not null unique
);

create table if not exists categorization_rules (
  id bigserial primary key,
  rule_type varchar(30) not null,
  pattern varchar(255) not null,
  category_name varchar(120) not null,
  priority int not null default 100
);

create table if not exists transactions (
  id bigserial primary key,
  source_file_id bigint not null references source_files(id),
  source_type varchar(40) not null,
  account_ref varchar(120),
  external_id varchar(255),
  canonical_hash varchar(64) not null unique,
  transaction_date date not null,
  competence_month varchar(7) not null,
  description_raw text not null,
  description_normalized text not null,
  amount numeric(14,2) not null,
  direction varchar(10) not null,
  transaction_kind varchar(40) not null,
  category varchar(120) not null,
  categorization_method varchar(40) not null,
  categorization_confidence numeric(5,2) not null,
  applied_rule varchar(255),
  is_card_bill_payment boolean not null default false,
  is_adjustment boolean not null default false,
  is_reconciled boolean not null default false,
  should_count_in_spending boolean not null default true
);
create unique index if not exists uq_transactions_external_not_null on transactions(source_type, external_id) where external_id is not null;

create table if not exists reconciliations (
  id bigserial primary key,
  source_file_id bigint not null references source_files(id),
  notes text
);

create table if not exists reconciliation_items (
  id bigserial primary key,
  reconciliation_id bigint not null references reconciliations(id),
  transaction_id bigint not null references transactions(id),
  role varchar(30) not null
);

create table if not exists analysis_runs (
  id bigserial primary key,
  period_start date not null,
  period_end date not null,
  trigger_source_file_id bigint references source_files(id),
  payload text not null,
  prompt text not null,
  html_output text not null,
  status varchar(30) not null,
  error_message text,
  created_at timestamptz default now()
);

create index if not exists idx_transactions_date on transactions(transaction_date);
create index if not exists idx_transactions_category on transactions(category);

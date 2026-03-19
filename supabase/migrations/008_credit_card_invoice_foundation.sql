create table if not exists credit_cards (
  id bigserial primary key,
  issuer varchar(40) not null,
  card_label varchar(120) not null,
  card_final varchar(4) not null,
  brand varchar(40),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_credit_cards_issuer_final unique (issuer, card_final)
);

create table if not exists credit_card_invoices (
  id bigserial primary key,
  source_file_id bigint not null references source_files(id),
  card_id bigint not null references credit_cards(id),
  issuer varchar(40) not null,
  card_final varchar(4) not null,
  billing_year integer not null,
  billing_month integer not null,
  due_date date not null,
  closing_date date,
  total_amount_brl numeric(14,2) not null,
  source_file_name varchar(255) not null,
  source_file_hash varchar(64) not null,
  notes text,
  import_status varchar(30) not null default 'imported',
  imported_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint uq_credit_card_invoices_card_period unique (card_id, billing_year, billing_month),
  constraint uq_credit_card_invoices_file_hash unique (source_file_hash)
);

create table if not exists credit_card_invoice_items (
  id bigserial primary key,
  invoice_id bigint not null references credit_card_invoices(id) on delete cascade,
  purchase_date date not null,
  description_raw text not null,
  description_normalized text,
  amount_brl numeric(14,2) not null,
  installment_current integer,
  installment_total integer,
  is_installment boolean not null default false,
  derived_note text,
  external_row_hash varchar(64) not null,
  created_at timestamptz not null default now(),
  constraint uq_credit_card_invoice_items_row_hash unique (invoice_id, external_row_hash)
);

create index if not exists idx_credit_card_invoices_card_period
  on credit_card_invoices(card_id, billing_year, billing_month);

create index if not exists idx_credit_card_invoice_items_invoice
  on credit_card_invoice_items(invoice_id, purchase_date);

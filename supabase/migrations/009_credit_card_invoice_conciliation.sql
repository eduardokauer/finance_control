create table if not exists credit_card_invoice_conciliations (
  id bigserial primary key,
  invoice_id bigint not null references credit_card_invoices(id) on delete cascade,
  status varchar(30) not null default 'pending_review',
  gross_amount_brl numeric(14,2) not null default 0,
  invoice_credit_total_brl numeric(14,2) not null default 0,
  bank_payment_total_brl numeric(14,2) not null default 0,
  conciliated_total_brl numeric(14,2) not null default 0,
  remaining_balance_brl numeric(14,2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_credit_card_invoice_conciliations_invoice unique (invoice_id)
);

create table if not exists credit_card_invoice_conciliation_items (
  id bigserial primary key,
  conciliation_id bigint not null references credit_card_invoice_conciliations(id) on delete cascade,
  item_type varchar(30) not null,
  amount_brl numeric(14,2) not null,
  bank_transaction_id bigint references transactions(id),
  invoice_item_id bigint references credit_card_invoice_items(id),
  notes text,
  created_at timestamptz not null default now(),
  constraint uq_credit_card_invoice_conciliation_items_bank_transaction unique (bank_transaction_id),
  constraint uq_credit_card_invoice_conciliation_items_invoice_item unique (invoice_item_id)
);

create index if not exists idx_credit_card_invoice_conciliations_invoice
  on credit_card_invoice_conciliations(invoice_id);

create index if not exists idx_credit_card_invoice_conciliation_items_conciliation
  on credit_card_invoice_conciliation_items(conciliation_id, item_type);

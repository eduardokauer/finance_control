alter table if exists categorization_rules
  add column if not exists source_scope varchar(30);

update categorization_rules
set source_scope = 'both'
where source_scope is null;

alter table if exists categorization_rules
  alter column source_scope set default 'both';

alter table if exists categorization_rules
  alter column source_scope set not null;

alter table if exists credit_card_invoice_items
  add column if not exists category varchar(120);

alter table if exists credit_card_invoice_items
  add column if not exists categorization_method varchar(40);

alter table if exists credit_card_invoice_items
  add column if not exists categorization_confidence numeric(5,2);

alter table if exists credit_card_invoice_items
  add column if not exists applied_rule varchar(255);

alter table if exists credit_card_invoice_items
  add column if not exists categorization_rule_id bigint references categorization_rules(id);

create index if not exists idx_credit_card_invoice_items_category
  on credit_card_invoice_items(category);

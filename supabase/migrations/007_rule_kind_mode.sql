do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_name = 'categorization_rules'
      and column_name = 'transaction_kind'
  ) and not exists (
    select 1
    from information_schema.columns
    where table_name = 'categorization_rules'
      and column_name = 'kind_mode'
  ) then
    alter table categorization_rules rename column transaction_kind to kind_mode;
  end if;
end $$;

alter table categorization_rules add column if not exists kind_mode varchar(20);

update categorization_rules
set kind_mode = case
  when kind_mode = 'transfer' then 'transfer'
  else 'flow'
end
where kind_mode is null or kind_mode not in ('flow', 'transfer');

alter table categorization_rules alter column kind_mode set default 'flow';
alter table categorization_rules alter column kind_mode set not null;

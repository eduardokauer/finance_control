insert into categorization_rules(rule_type, pattern, category_name, priority) values
('contains', 'itau black', 'Pagamento de Fatura', 1),
('contains', 'eletropaulo', 'Serviços da Casa', 1),
('contains', 'telefonica', 'Serviços da Casa', 1),
('contains', 'ipva', 'Impostos e Taxas', 1),
('contains', 'licenc', 'Impostos e Taxas', 1),
('contains', 'socialcondo', 'Moradia', 2),
('contains', 'guarida', 'Moradia', 2),
('contains', 'psicolo', 'Saúde', 2)
on conflict do nothing;

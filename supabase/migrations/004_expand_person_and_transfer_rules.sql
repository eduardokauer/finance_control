insert into categorization_rules(rule_type, pattern, category_name, priority) values
('contains', 'leticia', 'Moradia', 2),
('contains', 'ewerton', 'Moradia', 2),
('contains', 'faris', 'Saúde', 2),
('contains', 'luma', 'Saúde', 2),
('contains', 'm a dos', 'Saúde', 2),
('contains', 'pag tit banco', 'Transferências', 1),
('contains', 'pag tit int', 'Transferências', 1),
('contains', 'ted 102', 'Transferências', 1)
on conflict do nothing;

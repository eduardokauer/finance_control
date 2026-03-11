insert into categories(name) values
('Supermercado'),('Alimentação'),('Farmácia'),('Saúde'),('Transporte'),('Combustível'),('Pedágio/Estacionamento'),
('Compras'),('Casa'),('Pets'),('Educação'),('Lazer'),('Assinaturas'),('Beleza e Cuidados'),('Viagens'),('Moradia'),
('Serviços da Casa'),('Impostos e Taxas'),('Tarifas Bancárias'),('Seguros'),('Pagamento de Fatura'),('Transferências'),
('Ajustes e Estornos'),('IOF e Encargos'),('Parcelamentos'),('Salário'),('Reembolsos'),('Outras Receitas'),('Outros'),('Não Categorizado')
on conflict do nothing;

insert into categorization_rules(rule_type,pattern,category_name,priority) values
('contains','ifood','Alimentação',1),('contains','uber','Transporte',1),('contains','droga raia','Farmácia',1),
('contains','drogasil','Farmácia',1),('contains','netflix','Assinaturas',1),('contains','spotify','Assinaturas',1),
('contains','google one','Assinaturas',1),('contains','petlove','Pets',1),('contains','petz','Pets',1),
('contains','cobasi','Pets',1),('contains','mercado livre','Compras',1),('contains','amazon','Compras',1),
('contains','shopee','Compras',1),('contains','carrefour','Supermercado',1),('contains','extra','Supermercado',1),
('contains','pao de acucar','Supermercado',1),('contains','assai','Supermercado',1),('contains','shell','Combustível',1),
('contains','ipiranga','Combustível',1),('contains','posto','Combustível',1),('contains','sem parar','Pedágio/Estacionamento',1),
('contains','conectcar','Pedágio/Estacionamento',1),('contains','estapar','Pedágio/Estacionamento',1),
('contains','enel','Serviços da Casa',1),('contains','sabesp','Serviços da Casa',1),('contains','vivo fibra','Serviços da Casa',1),
('contains','seguro','Seguros',2),('contains','iof','IOF e Encargos',2),('contains','estorno','Ajustes e Estornos',1),
('contains','ajuste','Ajustes e Estornos',1),('contains','desconto na fatura','Ajustes e Estornos',1)
on conflict do nothing;

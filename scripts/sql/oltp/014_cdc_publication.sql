-- Publication dedicada para CDC (Debezium) da tabela de despesas (E2)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'inflow_despesas_pub') THEN
        CREATE PUBLICATION inflow_despesas_pub FOR TABLE oltp.despesas;
    END IF;
END $$;

-- REPLICA IDENTITY FULL garante que o Debezium receba a imagem "before"
-- completa em UPDATE/DELETE, não só a chave primária.
ALTER TABLE oltp.despesas REPLICA IDENTITY FULL;

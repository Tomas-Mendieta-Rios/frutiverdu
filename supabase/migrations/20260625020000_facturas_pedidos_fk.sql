-- Relacion logica facturas <-> pedidos_dux via nro_pedido
-- Solo indice (sin FK ni UNIQUE) para evitar problemas con nro_pedido vacio o duplicado

CREATE INDEX IF NOT EXISTS idx_pedidos_dux_nro_pedido ON pedidos_dux (nro_pedido);
CREATE INDEX IF NOT EXISTS idx_facturas_nro_pedido ON facturas (nro_pedido);

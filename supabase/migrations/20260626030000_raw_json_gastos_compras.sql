-- Agrega columna json JSONB a gastos y compras para guardar el raw completo de DUX.
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS json JSONB;
ALTER TABLE gastos_items ADD COLUMN IF NOT EXISTS json JSONB;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS json JSONB;
ALTER TABLE items_compra ADD COLUMN IF NOT EXISTS json JSONB;

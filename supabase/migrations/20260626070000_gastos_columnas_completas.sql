-- gastos: agregar rubro, sub_rubro, observaciones, condicion_pago, monto_pendiente; drop json
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS id_rubro BIGINT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS rubro_nombre TEXT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS id_sub_rubro BIGINT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS sub_rubro_nombre TEXT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS observaciones TEXT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS condicion_pago TEXT;
ALTER TABLE gastos ADD COLUMN IF NOT EXISTS monto_pendiente NUMERIC DEFAULT 0;
ALTER TABLE gastos DROP COLUMN IF EXISTS json;

-- gastos_items: agregar monto_total; drop json
ALTER TABLE gastos_items ADD COLUMN IF NOT EXISTS monto_total NUMERIC DEFAULT 0;
ALTER TABLE gastos_items DROP COLUMN IF EXISTS json;

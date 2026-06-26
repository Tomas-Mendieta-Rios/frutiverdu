ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS forma_pago TEXT;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS provincia TEXT;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS estado_recepcion TEXT;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS fecha_imputacion_contable TEXT;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS monto_pendiente NUMERIC DEFAULT 0;
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS monto_percepciones NUMERIC DEFAULT 0;

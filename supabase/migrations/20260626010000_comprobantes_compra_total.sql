-- Agrega total al comprobante de compra para no depender de cantidad * precio_uni
ALTER TABLE comprobantes_compra ADD COLUMN IF NOT EXISTS total NUMERIC DEFAULT 0;

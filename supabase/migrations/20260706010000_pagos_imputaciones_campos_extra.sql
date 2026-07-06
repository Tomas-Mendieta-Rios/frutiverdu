-- Agrega campos faltantes de ImputacionPagoDto a pagos_proveedores_imputaciones

ALTER TABLE pagos_proveedores_imputaciones
    ADD COLUMN IF NOT EXISTS id_comp_compra BIGINT,
    ADD COLUMN IF NOT EXISTS id_comp_gasto BIGINT,
    ADD COLUMN IF NOT EXISTS id_nota_credito_debito_compra BIGINT;

-- Índice para JOIN eficiente entre gastos_items.cod_item y gastos_catalogo.cod_producto
CREATE INDEX IF NOT EXISTS idx_gastos_catalogo_cod_producto
    ON gastos_catalogo(cod_producto);

-- View que resuelve el nombre del item desde el catálogo en la base de datos
CREATE OR REPLACE VIEW gastos_items_con_nombre AS
SELECT
    gi.*,
    gc.gasto      AS nombre_catalogo,
    gc.rubro      AS rubro_catalogo,
    gc.sub_rubro  AS sub_rubro_catalogo,
    gc.proveedor  AS proveedor_catalogo
FROM gastos_items gi
LEFT JOIN gastos_catalogo gc ON gi.cod_item::text = gc.cod_producto::text;

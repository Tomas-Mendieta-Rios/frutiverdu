-- Catálogo de items de gastos importados desde Excel
CREATE TABLE IF NOT EXISTS gastos_catalogo (
    id          BIGSERIAL PRIMARY KEY,
    cod_producto TEXT,
    gasto        TEXT NOT NULL,
    rubro        TEXT,
    sub_rubro    TEXT,
    proveedor    TEXT,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);

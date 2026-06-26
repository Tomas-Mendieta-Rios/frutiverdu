-- Reemplaza la tabla plana `compras` por un modelo header-detail normalizado.

DROP TABLE IF EXISTS compras;

CREATE TABLE IF NOT EXISTS comprobantes_compra (
    id BIGSERIAL PRIMARY KEY,
    nro_comprobante TEXT,
    fecha TEXT,
    proveedor_id TEXT,
    proveedor_nombre TEXT,
    condicion_pago TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS items_compra (
    id BIGSERIAL PRIMARY KEY,
    comprobante_id BIGINT REFERENCES comprobantes_compra(id) ON DELETE CASCADE,
    codigo_producto TEXT,
    producto_nombre TEXT,
    cantidad NUMERIC DEFAULT 0,
    precio NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

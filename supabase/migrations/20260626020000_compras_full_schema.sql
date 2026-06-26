-- Rediseño completo de compras siguiendo el patrón de gastos.
-- El id viene de DUX (id_compra), el total desde montos.total.

DROP TABLE IF EXISTS items_compra;
DROP TABLE IF EXISTS comprobantes_compra;

CREATE TABLE comprobantes_compra (
    id BIGINT PRIMARY KEY,
    id_empresa INT,
    id_sucursal INT,
    id_proveedor BIGINT,
    cuit TEXT,
    proveedor TEXT,
    nro_comprobante TEXT,
    tipo_comprobante TEXT,
    condicion_pago TEXT,
    estado TEXT DEFAULT 'EMITIDA',
    fecha TEXT,
    fecha_vencimiento TEXT,
    monto_exento NUMERIC DEFAULT 0,
    monto_gravado NUMERIC DEFAULT 0,
    monto_iva NUMERIC DEFAULT 0,
    monto_desc NUMERIC DEFAULT 0,
    total NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE items_compra (
    id BIGSERIAL PRIMARY KEY,
    comprobante_id BIGINT REFERENCES comprobantes_compra(id) ON DELETE CASCADE,
    cod_item TEXT,
    item TEXT,
    ctd NUMERIC DEFAULT 0,
    precio_uni NUMERIC DEFAULT 0,
    porc_desc NUMERIC DEFAULT 0,
    porc_iva NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

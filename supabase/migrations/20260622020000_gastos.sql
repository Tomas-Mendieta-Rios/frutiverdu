DROP TABLE IF EXISTS gastos_items;
DROP TABLE IF EXISTS gastos;

CREATE TABLE gastos (
    id BIGINT PRIMARY KEY,
    id_empresa INT,
    id_sucursal INT,
    id_proveedor BIGINT,
    cuit TEXT,
    proveedor TEXT,
    nro_comprobante TEXT,
    tipo_comprobante TEXT,
    gasto TEXT,
    estado TEXT DEFAULT 'EMITIDA',
    fecha TEXT,
    fecha_vencimiento TEXT,
    pago_pendiente BOOLEAN DEFAULT FALSE,
    monto_exento NUMERIC DEFAULT 0,
    monto_gravado NUMERIC DEFAULT 0,
    monto_iva NUMERIC DEFAULT 0,
    monto_desc NUMERIC DEFAULT 0,
    total NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE gastos_items (
    id BIGSERIAL PRIMARY KEY,
    gasto_id BIGINT REFERENCES gastos(id) ON DELETE CASCADE,
    cod_item TEXT,
    item TEXT,
    ctd NUMERIC DEFAULT 0,
    precio_uni NUMERIC DEFAULT 0,
    porc_desc NUMERIC DEFAULT 0,
    porc_iva NUMERIC DEFAULT 0,
    comentarios TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

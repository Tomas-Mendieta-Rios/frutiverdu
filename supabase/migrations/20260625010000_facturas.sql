-- Tablas para facturas DUX (comprobantes de venta)

CREATE TABLE IF NOT EXISTS facturas (
    factura_id TEXT PRIMARY KEY,
    tipo_comp TEXT,
    letra_comp TEXT,
    nro_comp TEXT,
    nro_pto_vta TEXT,
    fecha_comp TEXT,
    apellido_razon_soc TEXT,
    nombre TEXT,
    cuit TEXT,
    nro_pedido TEXT,
    monto_exento NUMERIC DEFAULT 0,
    monto_gravado NUMERIC DEFAULT 0,
    monto_iva NUMERIC DEFAULT 0,
    monto_desc NUMERIC DEFAULT 0,
    total NUMERIC DEFAULT 0,
    anulada TEXT DEFAULT 'N',
    nro_cae_cai TEXT,
    url_factura TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS facturas_items (
    id BIGSERIAL PRIMARY KEY,
    factura_id TEXT REFERENCES facturas(factura_id) ON DELETE CASCADE,
    cod_item TEXT,
    item TEXT,
    ctd NUMERIC DEFAULT 0,
    precio_uni NUMERIC DEFAULT 0,
    porc_desc NUMERIC DEFAULT 0,
    porc_iva NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

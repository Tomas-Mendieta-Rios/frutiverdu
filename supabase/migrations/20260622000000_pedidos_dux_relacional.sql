-- Migración: reemplazar pedidos_dux (JSON blob) por schema relacional
-- Fecha: 2026-06-22

DROP TABLE IF EXISTS pedidos_dux;

CREATE TABLE pedidos_dux (
    order_id TEXT PRIMARY KEY,
    nro_pedido TEXT,
    fecha TEXT,
    cliente TEXT,
    estado_facturacion TEXT,
    estado_remito TEXT,
    anulado TEXT DEFAULT 'N',
    lugar_entrega TEXT,
    monto_exento NUMERIC DEFAULT 0,
    monto_gravado NUMERIC DEFAULT 0,
    monto_iva NUMERIC DEFAULT 0,
    monto_descuento NUMERIC DEFAULT 0,
    total NUMERIC DEFAULT 0,
    condicion_pago TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE pedidos_dux_items (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT REFERENCES pedidos_dux(order_id) ON DELETE CASCADE,
    cod_item TEXT,
    item TEXT,
    ctd NUMERIC DEFAULT 0,
    precio_uni NUMERIC DEFAULT 0,
    porc_desc NUMERIC DEFAULT 0,
    porc_iva NUMERIC DEFAULT 0,
    comentarios TEXT,
    ctd_facturada NUMERIC DEFAULT 0,
    ctd_con_remito NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

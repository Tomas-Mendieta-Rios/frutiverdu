-- Migración: reemplazar pedidos_wix (JSON blob) por schema relacional
-- Fecha: 2026-06-22

DROP TABLE IF EXISTS pedidos_wix;

CREATE TABLE pedidos_wix (
    order_id TEXT PRIMARY KEY,
    number TEXT,
    status TEXT,
    created_date TEXT,
    billing_first_name TEXT,
    billing_last_name TEXT,
    billing_phone TEXT,
    billing_email TEXT,
    shipping_first_name TEXT,
    shipping_last_name TEXT,
    shipping_phone TEXT,
    shipping_address_line TEXT,
    shipping_address_line2 TEXT,
    shipping_city TEXT,
    shipping_subdivision TEXT,
    buyer_email TEXT,
    total_formatted TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE pedidos_wix_items (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT REFERENCES pedidos_wix(order_id) ON DELETE CASCADE,
    catalog_item_id TEXT,
    product_id TEXT,
    product_name_translated TEXT,
    product_name_original TEXT,
    quantity NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

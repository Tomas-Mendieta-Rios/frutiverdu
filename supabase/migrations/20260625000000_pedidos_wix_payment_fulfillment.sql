-- Agrega payment_status, fulfillment_status, buyer_note a pedidos_wix
-- y price_formatted, price_amount a pedidos_wix_items

ALTER TABLE pedidos_wix
    ADD COLUMN IF NOT EXISTS payment_status TEXT,
    ADD COLUMN IF NOT EXISTS fulfillment_status TEXT,
    ADD COLUMN IF NOT EXISTS buyer_note TEXT,
    ADD COLUMN IF NOT EXISTS updated_date TEXT;

ALTER TABLE pedidos_wix_items
    ADD COLUMN IF NOT EXISTS price_formatted TEXT,
    ADD COLUMN IF NOT EXISTS price_amount NUMERIC;

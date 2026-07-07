-- Cajas de cobro (MP Carlos, MP Frutiverdu, Efectivo, etc.)
CREATE TABLE IF NOT EXISTS cajas (
    id   SERIAL PRIMARY KEY,
    nombre TEXT UNIQUE NOT NULL,
    activa BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO cajas (nombre) VALUES
    ('MP CARLOS'),
    ('MP FRUTIVERDU'),
    ('EFECTIVO'),
    ('CAJA DE AHORRO'),
    ('CHEQUE')
ON CONFLICT (nombre) DO NOTHING;

ALTER TABLE pedidos_wix ADD COLUMN IF NOT EXISTS caja_id INT REFERENCES cajas(id);

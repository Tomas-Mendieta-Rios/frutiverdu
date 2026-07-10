CREATE TABLE IF NOT EXISTS cajas_ajustes (
    id          BIGSERIAL PRIMARY KEY,
    caja_id     INT REFERENCES cajas(id) ON DELETE CASCADE,
    fecha       DATE NOT NULL,
    monto       NUMERIC DEFAULT 0,
    nota        TEXT,
    tipo        TEXT NOT NULL DEFAULT 'ajuste',  -- 'inicial' | 'ajuste'
    afecta_balance BOOLEAN GENERATED ALWAYS AS (tipo = 'ajuste') STORED,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS aportes_socios (
    id          BIGSERIAL PRIMARY KEY,
    socio       TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'aporte',  -- 'aporte' | 'devolucion'
    fecha       DATE NOT NULL,
    monto       NUMERIC NOT NULL DEFAULT 0,
    concepto    TEXT,
    caja_id     INT REFERENCES cajas(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

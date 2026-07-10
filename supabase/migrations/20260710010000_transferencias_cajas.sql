CREATE TABLE IF NOT EXISTS transferencias_cajas (
    id          BIGSERIAL PRIMARY KEY,
    fecha       DATE NOT NULL,
    origen_id   INT REFERENCES cajas(id),
    destino_id  INT REFERENCES cajas(id),
    monto       NUMERIC DEFAULT 0,
    concepto    TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

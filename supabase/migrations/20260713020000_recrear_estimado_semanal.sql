CREATE TABLE IF NOT EXISTS estimado_semanal (
    id          BIGSERIAL PRIMARY KEY,
    dia_semana  TEXT,
    codigo      TEXT,
    producto    TEXT,
    unidad_medida TEXT,
    estimado    TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

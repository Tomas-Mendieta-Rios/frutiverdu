CREATE TABLE IF NOT EXISTS rubros (
    id BIGINT PRIMARY KEY,
    nombre TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subrubros (
    id BIGINT PRIMARY KEY,
    nombre TEXT,
    rubro_id BIGINT,
    rubro_nombre TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

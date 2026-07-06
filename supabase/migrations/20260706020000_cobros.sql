-- Cobros de clientes (desde DUX /v2/cobros)

CREATE TABLE IF NOT EXISTS cobros (
    id BIGINT PRIMARY KEY,
    id_empresa INT,
    id_sucursal INT,
    fecha TEXT,
    nro_comprobante TEXT,
    tipo_comprobante TEXT,
    monto NUMERIC DEFAULT 0,
    moneda TEXT,
    observaciones TEXT,
    id_cliente BIGINT,
    cliente TEXT,
    nombre_cliente TEXT,
    tipo_doc TEXT,
    nro_doc TEXT,
    id_personal BIGINT,
    personal TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cobros_cobranza (
    id BIGSERIAL PRIMARY KEY,
    cobro_id BIGINT REFERENCES cobros(id) ON DELETE CASCADE,
    tipo_valor TEXT,
    descripcion TEXT,
    referencia TEXT,
    monto NUMERIC DEFAULT 0,
    id_tarjeta BIGINT,
    id_plan_tarjeta BIGINT,
    id_terminal BIGINT,
    nro_cupon TEXT,
    nro_lote TEXT
);

CREATE TABLE IF NOT EXISTS cobros_imputaciones (
    id BIGSERIAL PRIMARY KEY,
    cobro_id BIGINT REFERENCES cobros(id) ON DELETE CASCADE,
    id_comp_venta BIGINT,
    id_nota_credito_debito_venta BIGINT,
    tipo_comp TEXT,
    nro_comprobante TEXT,
    monto_imputado NUMERIC DEFAULT 0
);

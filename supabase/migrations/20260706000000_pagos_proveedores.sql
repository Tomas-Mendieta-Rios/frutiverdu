-- Pagos a proveedores (desde DUX /v2/pagos-proveedores)

CREATE TABLE IF NOT EXISTS pagos_proveedores (
    id BIGINT PRIMARY KEY,
    id_empresa INT,
    id_sucursal INT,
    id_proveedor BIGINT,
    proveedor TEXT,
    fecha TEXT,
    nro_comprobante TEXT,
    forma_pago TEXT,
    monto NUMERIC DEFAULT 0,
    moneda TEXT,
    monto_aplicado NUMERIC DEFAULT 0,
    retencion NUMERIC DEFAULT 0,
    concepto TEXT,
    observaciones TEXT,
    id_caja BIGINT,
    caja TEXT,
    id_personal BIGINT,
    personal TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pagos_proveedores_lineas (
    id BIGSERIAL PRIMARY KEY,
    pago_id BIGINT REFERENCES pagos_proveedores(id) ON DELETE CASCADE,
    tipo_valor TEXT,
    descripcion TEXT,
    referencia TEXT,
    monto NUMERIC DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pagos_proveedores_imputaciones (
    id BIGSERIAL PRIMARY KEY,
    pago_id BIGINT REFERENCES pagos_proveedores(id) ON DELETE CASCADE,
    id_compra BIGINT,
    id_gasto BIGINT,
    tipo_comprobante TEXT,
    nro_comprobante TEXT,
    monto_imputado NUMERIC DEFAULT 0
);

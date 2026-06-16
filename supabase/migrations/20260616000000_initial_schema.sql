-- Initial schema for Frutiverdu Supabase migration
-- Created: 2026-06-16
-- This migration creates all tables needed for the inventory management system

-- Tabla: productos
CREATE TABLE IF NOT EXISTS productos (
    codigo TEXT PRIMARY KEY,
    producto TEXT,
    unidad_medida TEXT,
    descripcion TEXT,
    rubro TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: compuestos
CREATE TABLE IF NOT EXISTS compuestos (
    id BIGSERIAL PRIMARY KEY,
    codigo_origen TEXT,
    producto_origen TEXT,
    cantidad_origen TEXT,
    codigo_componente TEXT,
    producto_componente TEXT,
    cantidad_componente TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: stock_historico
CREATE TABLE IF NOT EXISTS stock_historico (
    id BIGSERIAL PRIMARY KEY,
    fecha TEXT,
    codigo TEXT,
    producto TEXT,
    unidad_medida TEXT,
    cantidad TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: estimado_historico
CREATE TABLE IF NOT EXISTS estimado_historico (
    id BIGSERIAL PRIMARY KEY,
    fecha TEXT,
    codigo TEXT,
    producto TEXT,
    unidad_medida TEXT,
    estimado TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: estimado_semanal
CREATE TABLE IF NOT EXISTS estimado_semanal (
    id BIGSERIAL PRIMARY KEY,
    dia_semana TEXT,
    codigo TEXT,
    producto TEXT,
    unidad_medida TEXT,
    estimado TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: wix_productos
CREATE TABLE IF NOT EXISTS wix_productos (
    wix_id TEXT PRIMARY KEY,
    producto TEXT,
    descripcion TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: mapping_wix_dux
CREATE TABLE IF NOT EXISTS mapping_wix_dux (
    id BIGSERIAL PRIMARY KEY,
    wix_id TEXT,
    wix_producto TEXT,
    dux_codigo TEXT,
    dux_producto TEXT,
    factor TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: packs_wix
CREATE TABLE IF NOT EXISTS packs_wix (
    id BIGSERIAL PRIMARY KEY,
    wix_id_pack TEXT,
    pack_nombre TEXT,
    dux_codigo TEXT,
    dux_producto TEXT,
    cantidad TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: selecciones_dux
CREATE TABLE IF NOT EXISTS selecciones_dux (
    order_id TEXT PRIMARY KEY,
    fecha_entrega TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: selecciones_wix
CREATE TABLE IF NOT EXISTS selecciones_wix (
    order_id TEXT PRIMARY KEY,
    fecha_entrega TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: stock_teorico_ultimo
CREATE TABLE IF NOT EXISTS stock_teorico_ultimo (
    codigo TEXT PRIMARY KEY,
    producto TEXT,
    stock_inicial TEXT,
    compras TEXT,
    pedidos TEXT,
    teorico TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: stock_teorico_detalle
CREATE TABLE IF NOT EXISTS stock_teorico_detalle (
    key TEXT PRIMARY KEY,
    value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: pedidos_dux
CREATE TABLE IF NOT EXISTS pedidos_dux (
    order_id TEXT PRIMARY KEY,
    fecha TEXT,
    json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: pedidos_wix
CREATE TABLE IF NOT EXISTS pedidos_wix (
    order_id TEXT PRIMARY KEY,
    fecha TEXT,
    json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: proveedores
CREATE TABLE IF NOT EXISTS proveedores (
    proveedor_id TEXT PRIMARY KEY,
    proveedor TEXT,
    nombre_fantasia TEXT,
    categoria_fiscal TEXT,
    tipo_documento TEXT,
    numero_documento TEXT,
    cuit_cuil TEXT,
    codigo TEXT,
    email TEXT,
    provincia TEXT,
    localidad TEXT,
    barrio TEXT,
    domicilio TEXT,
    telefono TEXT,
    celular TEXT,
    condicion_pago TEXT,
    fecha_creacion TEXT,
    persona_contacto TEXT,
    lugar_entrega TEXT,
    tipo_comprobante TEXT,
    habilitado TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: compras
CREATE TABLE IF NOT EXISTS compras (
    id BIGSERIAL PRIMARY KEY,
    fecha TEXT,
    proveedor_id TEXT,
    proveedor_nombre TEXT,
    codigo_producto TEXT,
    producto_nombre TEXT,
    cantidad TEXT,
    precio TEXT,
    condicion_pago TEXT,
    comprobante TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: mixes_dux
CREATE TABLE IF NOT EXISTS mixes_dux (
    id BIGSERIAL PRIMARY KEY,
    mix_base TEXT,
    componente_base TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla: config
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

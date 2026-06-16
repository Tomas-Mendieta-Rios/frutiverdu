"""Script para crear las tablas en Supabase basándose en el SCHEMA de gsheets_db.py

IMPORTANTE: Este script SOLO crea tablas en Supabase, NO TOCA Google Sheets.
"""

import streamlit as st
from supabase import create_client


def get_supabase_client():
    """Obtiene el cliente de Supabase desde secrets."""
    supabase_config = st.secrets.get("supabase", {})
    url = supabase_config.get("url")
    key = supabase_config.get("key")
    
    if not url or not key:
        st.error("❌ Credenciales de Supabase no configuradas")
        return None
    
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"❌ Error al crear cliente: {e}")
        return None


def generate_create_table_sql():
    """Genera SQL para crear todas las tablas basadas en el SCHEMA."""
    
    sql_statements = []
    
    # Tabla: productos
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS productos (
        codigo TEXT PRIMARY KEY,
        producto TEXT,
        unidad_medida TEXT,
        descripcion TEXT,
        rubro TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: compuestos
    sql_statements.append("""
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
    """)
    
    # Tabla: stock_historico
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS stock_historico (
        id BIGSERIAL PRIMARY KEY,
        fecha TEXT,
        codigo TEXT,
        producto TEXT,
        unidad_medida TEXT,
        cantidad TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: estimado_historico
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS estimado_historico (
        id BIGSERIAL PRIMARY KEY,
        fecha TEXT,
        codigo TEXT,
        producto TEXT,
        unidad_medida TEXT,
        estimado TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: estimado_semanal
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS estimado_semanal (
        id BIGSERIAL PRIMARY KEY,
        dia_semana TEXT,
        codigo TEXT,
        producto TEXT,
        unidad_medida TEXT,
        estimado TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: wix_productos
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS wix_productos (
        wix_id TEXT PRIMARY KEY,
        producto TEXT,
        descripcion TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: mapping_wix_dux
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS mapping_wix_dux (
        id BIGSERIAL PRIMARY KEY,
        wix_id TEXT,
        wix_producto TEXT,
        dux_codigo TEXT,
        dux_producto TEXT,
        factor TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: packs_wix
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS packs_wix (
        id BIGSERIAL PRIMARY KEY,
        wix_id_pack TEXT,
        pack_nombre TEXT,
        dux_codigo TEXT,
        dux_producto TEXT,
        cantidad TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: selecciones_dux
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS selecciones_dux (
        order_id TEXT PRIMARY KEY,
        fecha_entrega TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: selecciones_wix
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS selecciones_wix (
        order_id TEXT PRIMARY KEY,
        fecha_entrega TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: stock_teorico_ultimo
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS stock_teorico_ultimo (
        codigo TEXT PRIMARY KEY,
        producto TEXT,
        stock_inicial TEXT,
        compras TEXT,
        pedidos TEXT,
        teorico TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: stock_teorico_detalle
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS stock_teorico_detalle (
        key TEXT PRIMARY KEY,
        value TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: pedidos_dux
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS pedidos_dux (
        order_id TEXT PRIMARY KEY,
        fecha TEXT,
        json TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: pedidos_wix
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS pedidos_wix (
        order_id TEXT PRIMARY KEY,
        fecha TEXT,
        json TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: proveedores
    sql_statements.append("""
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
    """)
    
    # Tabla: compras
    sql_statements.append("""
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
    """)
    
    # Tabla: mixes_dux
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS mixes_dux (
        id BIGSERIAL PRIMARY KEY,
        mix_base TEXT,
        componente_base TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    # Tabla: config
    sql_statements.append("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    return sql_statements


def create_tables_in_supabase():
    """Crea todas las tablas en Supabase."""
    
    st.markdown("### 📊 Crear tablas en Supabase")
    
    if st.button("🚀 Crear todas las tablas", key="create_tables_btn"):
        client = get_supabase_client()
        if not client:
            st.stop()
        
        sql_statements = generate_create_table_sql()
        
        with st.spinner("Creando tablas..."):
            try:
                for sql in sql_statements:
                    # Ejecutar cada SQL usando el RPC o directamente
                    # Nota: Supabase Python no tiene un método directo para ejecutar SQL raw
                    # pero podemos usar un workaround: la API REST
                    result = client.postgrest.session.post(
                        f"{client.postgrest.url}/rpc/exec_sql",
                        json={"query": sql}
                    )
                
                st.success("✅ Todas las tablas fueron creadas exitosamente")
                st.balloons()
                
            except Exception as e:
                # Si no funciona con RPC, intentamos con una alternativa
                st.warning(f"⚠️ No se pudo ejecutar SQL directamente: {e}")
                st.info("""
                Las tablas deben crearse manualmente en Supabase SQL Editor:
                Ve a tu proyecto Supabase → SQL Editor → copia y pega el siguiente SQL:
                """)
                
                # Mostrar el SQL para que el usuario lo copie
                full_sql = "\n\n".join(sql_statements)
                st.code(full_sql, language="sql")
                st.write("📋 Copia el SQL de arriba y pégalo en Supabase SQL Editor")


if __name__ == "__main__":
    create_tables_in_supabase()

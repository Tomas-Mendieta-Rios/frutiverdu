"""Script para probar conexión a Supabase sin hacer cambios en la BD."""

import streamlit as st
import sys

st.set_page_config(page_title="Test Supabase Connection", layout="wide")
st.title("🧪 Test de conexión a Supabase")

try:
    import supabase
except ImportError:
    st.error("❌ supabase-py no está instalado. Ejecutá: pip install supabase")
    st.stop()

# Leer credenciales de secrets
supabase_config = st.secrets.get("supabase", {})
url = supabase_config.get("url")
key = supabase_config.get("key")

if not url or not key:
    st.error("❌ Credenciales de Supabase no configuradas en st.secrets['supabase']")
    st.info("Asegúrate de agregar en Streamlit Cloud → Settings → Secrets:")
    st.code("""[supabase]
url = "https://tu-proyecto.supabase.co"
key = "tu-api-key-aqui"
""")
    st.stop()

st.info(f"📍 Conectando a: `{url}`")

try:
    from supabase import create_client
    
    client = create_client(url, key)
    st.success("✅ Cliente de Supabase creado correctamente")
    
    # Intentar una query simple de prueba
    try:
        # Leer la tabla 'productos' si existe, sino cualquier tabla dummy
        result = client.table("public").select("1").limit(1).execute()
        st.success("✅ Conexión a la BD de Supabase funciona")
        st.write("Respuesta:", result)
    except Exception as e:
        if "does not exist" in str(e).lower():
            st.warning("⚠️ La tabla no existe aún (es normal), pero la conexión funciona")
        else:
            st.warning(f"⚠️ Query de prueba falló: {e}")
    
except Exception as e:
    st.error(f"❌ Error al conectar: {e}")
    st.write("Detalles:", str(e))

st.divider()
st.markdown("""
### Próximos pasos
1. Si ves ✅ la conexión funciona
2. Podemos crear las tablas en Supabase
3. Después migrar datos desde Google Sheets
""")

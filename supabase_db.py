"""Capa de acceso a Supabase como base de datos.
Expone la misma API pública que gsheets_db.py para que app.py no necesite cambios.
"""

import pandas as pd
import streamlit as st
from supabase import create_client, Client


# ---------------- CONEXIÓN ----------------

@st.cache_resource
def get_client() -> Client:
    cfg = st.secrets.get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("key")
    if not url or not key:
        raise RuntimeError("Credenciales de Supabase no configuradas en secrets.toml")
    return create_client(url, key)


def ultima_carga(clave):
    """Devuelve el updated_at más reciente de la tabla correspondiente, o None."""
    tabla_map = {
        "dux_productos": "productos",
        "compuestos": "compuestos",
        "pedidos_wix": "pedidos_wix",
        "pedidos_dux": "pedidos_dux",
    }
    tabla = tabla_map.get(clave, clave)
    try:
        client = get_client()
        resp = client.table(tabla).select("updated_at").order("updated_at", desc=True).limit(1).execute()
        if resp.data:
            return resp.data[0].get("updated_at")
    except Exception:
        pass
    return None


# ---------------- PRODUCTOS ----------------

def cargar_productos():
    client = get_client()
    resp = client.table("productos").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["codigo", "producto", "unidad_medida", "descripcion", "rubro"])
    df["codigo"] = df["codigo"].astype(str)
    if "rubro" not in df.columns:
        df["rubro"] = ""
    for col in ["created_at", "updated_at"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    return df


def guardar_productos(df):
    client = get_client()
    client.table("productos").delete().neq("codigo", "___never___").execute()
    if not df.empty:
        client.table("productos").insert(df.to_dict(orient="records")).execute()


# ---------------- COMPUESTOS ----------------

def cargar_compuestos():
    client = get_client()
    resp = client.table("compuestos").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return df
    for col in ["codigo_origen", "codigo_componente"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    for col in ["cantidad_origen", "cantidad_componente"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["id", "created_at", "updated_at"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    return df


def guardar_compuestos(df):
    client = get_client()
    client.table("compuestos").delete().neq("id", 0).execute()
    if not df.empty:
        client.table("compuestos").insert(df.to_dict(orient="records")).execute()

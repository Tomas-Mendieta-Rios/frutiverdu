"""Capa de acceso a Google Sheets como base de datos.

Tablas (cada una es una pestaña del Sheet):
  - productos                : codigo, producto, unidad_medida, descripcion
  - compuestos               : codigo_origen, producto_origen, cantidad_origen,
                               codigo_componente, producto_componente, cantidad_componente
  - stock_historico          : fecha, codigo, producto, unidad_medida, cantidad
  - estimado_historico       : fecha, codigo, producto, unidad_medida, estimado
  - wix_productos            : wix_id, producto, descripcion
  - mapping_wix_dux          : wix_id, wix_producto, dux_codigo, dux_producto, factor
  - packs_wix                : wix_id_pack, pack_nombre, dux_codigo, dux_producto, cantidad
  - selecciones_dux          : order_id, fecha_entrega
  - selecciones_wix          : order_id, fecha_entrega
"""

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCHEMA = {
    "productos": ["codigo", "producto", "unidad_medida", "descripcion"],
    "compuestos": [
        "codigo_origen",
        "producto_origen",
        "cantidad_origen",
        "codigo_componente",
        "producto_componente",
        "cantidad_componente",
    ],
    "stock_historico": ["fecha", "codigo", "producto", "unidad_medida", "cantidad"],
    "estimado_historico": [
        "fecha",
        "codigo",
        "producto",
        "unidad_medida",
        "estimado",
    ],
    "wix_productos": ["wix_id", "producto", "descripcion"],
    "mapping_wix_dux": [
        "wix_id",
        "wix_producto",
        "dux_codigo",
        "dux_producto",
        "factor",
    ],
    "packs_wix": [
        "wix_id_pack",
        "pack_nombre",
        "dux_codigo",
        "dux_producto",
        "cantidad",
    ],
    "selecciones_dux": ["order_id", "fecha_entrega"],
    "selecciones_wix": ["order_id", "fecha_entrega"],
}


@st.cache_resource
def _client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


@st.cache_resource
def _spreadsheet():
    return _client().open_by_key(st.secrets["gsheets"]["spreadsheet_id"])


def _get_ws(nombre):
    sheet = _spreadsheet()
    try:
        return sheet.worksheet(nombre)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=nombre, rows=1000, cols=20)
        ws.update(values=[SCHEMA[nombre]], range_name="A1")
        return ws


@st.cache_data(ttl=60)
def leer_tabla(nombre):
    ws = _get_ws(nombre)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(columns=SCHEMA[nombre])
    header, *rows = values
    if not rows:
        return pd.DataFrame(columns=header)
    df = pd.DataFrame(rows, columns=header)
    df = df.replace("", pd.NA)
    return df


def escribir_tabla(nombre, df):
    df = df.copy()
    cols = SCHEMA[nombre]
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[cols]
    df = df.astype(object).where(pd.notna(df), "")
    ws = _get_ws(nombre)
    ws.clear()
    valores = [cols] + df.values.tolist()
    ws.update(values=valores, range_name="A1", value_input_option="USER_ENTERED")
    leer_tabla.clear()


def fecha_modificacion(nombre):
    """Devuelve el timestamp YYYY-MM-DD HH:MM:SS de la última modificación
    de una pestaña del Sheet (vía Drive API). None si no se puede."""
    try:
        ws = _get_ws(nombre)
        sheet = _spreadsheet()
        info = sheet.fetch_sheet_metadata(params={"fields": "properties.modifiedTime"})
        ts = info.get("properties", {}).get("modifiedTime")
        if not ts:
            return None
        return pd.to_datetime(ts).tz_convert("America/Argentina/Buenos_Aires").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return None


# ---------------- PRODUCTOS ----------------

def cargar_productos():
    df = leer_tabla("productos")
    if not df.empty:
        df["codigo"] = df["codigo"].astype(str)
    return df


def guardar_productos(df):
    escribir_tabla("productos", df)


# ---------------- COMPUESTOS ----------------

def cargar_compuestos():
    df = leer_tabla("compuestos")
    if df.empty:
        return df
    for c in ["codigo_origen", "codigo_componente"]:
        if c in df.columns:
            df[c] = df[c].astype(str)
    for c in ["cantidad_origen", "cantidad_componente"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def guardar_compuestos(df):
    escribir_tabla("compuestos", df)


# ---------------- STOCK ----------------

def _normalizar_stock(df):
    if df.empty:
        return df
    df = df.copy()
    df["codigo"] = df["codigo"].astype(str)
    df["fecha"] = df["fecha"].astype(str)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    return df


def cargar_stock_completo():
    return _normalizar_stock(leer_tabla("stock_historico"))


def cargar_stock(fecha=None):
    """Devuelve stock para una fecha. Si fecha=None, devuelve la última fecha."""
    df = cargar_stock_completo()
    if df.empty:
        return pd.DataFrame(columns=["codigo", "producto", "unidad_medida", "cantidad"])
    if fecha is None:
        try:
            latest = pd.to_datetime(df["fecha"]).max()
            df = df[pd.to_datetime(df["fecha"]) == latest]
        except Exception:
            pass
    else:
        df = df[df["fecha"] == str(fecha)]
    return df.drop(columns=["fecha"], errors="ignore").reset_index(drop=True)


def guardar_stock(df_fecha, fecha):
    full = cargar_stock_completo()
    if not full.empty and "fecha" in full.columns:
        otros = full[full["fecha"] != str(fecha)]
    else:
        otros = pd.DataFrame(columns=SCHEMA["stock_historico"])
    nuevo = df_fecha.copy()
    nuevo["fecha"] = str(fecha)
    combinado = pd.concat(
        [otros, nuevo[SCHEMA["stock_historico"]]], ignore_index=True
    )
    escribir_tabla("stock_historico", combinado)


def fechas_stock():
    df = cargar_stock_completo()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- ESTIMADO ----------------

def _normalizar_estimado(df):
    if df.empty:
        return df
    df = df.copy()
    df["codigo"] = df["codigo"].astype(str)
    df["fecha"] = df["fecha"].astype(str)
    df["estimado"] = pd.to_numeric(df["estimado"], errors="coerce")
    return df


def cargar_estimado_completo():
    return _normalizar_estimado(leer_tabla("estimado_historico"))


def cargar_estimado(fecha=None):
    df = cargar_estimado_completo()
    if df.empty:
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "estimado"]
        )
    if fecha is None:
        try:
            latest = pd.to_datetime(df["fecha"]).max()
            df = df[pd.to_datetime(df["fecha"]) == latest]
        except Exception:
            pass
    else:
        df = df[df["fecha"] == str(fecha)]
    return df.drop(columns=["fecha"], errors="ignore").reset_index(drop=True)


def guardar_estimado(df_fecha, fecha):
    full = cargar_estimado_completo()
    if not full.empty and "fecha" in full.columns:
        otros = full[full["fecha"] != str(fecha)]
    else:
        otros = pd.DataFrame(columns=SCHEMA["estimado_historico"])
    nuevo = df_fecha.copy()
    nuevo["fecha"] = str(fecha)
    combinado = pd.concat(
        [otros, nuevo[SCHEMA["estimado_historico"]]], ignore_index=True
    )
    escribir_tabla("estimado_historico", combinado)


def fechas_estimado():
    df = cargar_estimado_completo()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- WIX PRODUCTOS ----------------

def cargar_wix_productos():
    df = leer_tabla("wix_productos")
    if not df.empty:
        df["wix_id"] = df["wix_id"].astype(str)
    return df


def guardar_wix_productos(df):
    escribir_tabla("wix_productos", df)


# ---------------- MAPPING WIX DUX ----------------

def cargar_mapping_wix_dux():
    df = leer_tabla("mapping_wix_dux")
    if df.empty:
        return df
    for c in ["wix_id", "dux_codigo"]:
        if c in df.columns:
            df[c] = df[c].astype(str)
    if "factor" in df.columns:
        df["factor"] = pd.to_numeric(df["factor"], errors="coerce").fillna(1.0)
    return df


def guardar_mapping_wix_dux(df):
    escribir_tabla("mapping_wix_dux", df)


# ---------------- PACKS WIX ----------------

def cargar_packs_wix():
    df = leer_tabla("packs_wix")
    if df.empty:
        return df
    for c in ["wix_id_pack", "dux_codigo"]:
        if c in df.columns:
            df[c] = df[c].astype(str)
    if "cantidad" in df.columns:
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    return df


def guardar_packs_wix(df):
    escribir_tabla("packs_wix", df)


# ---------------- SELECCIONES (DUX y WIX) ----------------

def cargar_selecciones(fuente):
    """fuente: 'dux' o 'wix'. Devuelve dict {order_id: fecha_entrega}."""
    nombre = f"selecciones_{fuente}"
    df = leer_tabla(nombre)
    if df.empty or "order_id" not in df.columns:
        return {}
    return dict(
        zip(df["order_id"].astype(str), df["fecha_entrega"].astype(str))
    )


def guardar_selecciones(fuente, selecciones):
    """fuente: 'dux' o 'wix'. selecciones: dict {order_id: fecha_entrega}."""
    nombre = f"selecciones_{fuente}"
    rows = [
        {"order_id": str(oid), "fecha_entrega": str(fent)}
        for oid, fent in selecciones.items()
        if fent
    ]
    df = pd.DataFrame(rows, columns=SCHEMA[nombre])
    escribir_tabla(nombre, df)

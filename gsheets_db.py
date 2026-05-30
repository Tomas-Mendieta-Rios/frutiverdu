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

import json as _json

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
    "estimado_semanal": [
        "dia_semana",
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
    "pedidos_dux": ["order_id", "fecha", "json"],
    "pedidos_wix": ["order_id", "fecha", "json"],
    "proveedores": [
        "proveedor_id",
        "proveedor",
        "nombre_fantasia",
        "categoria_fiscal",
        "tipo_documento",
        "numero_documento",
        "cuit_cuil",
        "codigo",
        "email",
        "provincia",
        "localidad",
        "barrio",
        "domicilio",
        "telefono",
        "celular",
        "condicion_pago",
        "fecha_creacion",
        "persona_contacto",
        "lugar_entrega",
        "tipo_comprobante",
        "habilitado",
    ],
    "compras": [
        "fecha",
        "proveedor_id",
        "proveedor_nombre",
        "codigo_producto",
        "producto_nombre",
        "cantidad",
        "precio",
        "condicion_pago",
    ],
    "config": ["key", "value"],
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


@st.cache_resource
def _get_ws(nombre):
    sheet = _spreadsheet()
    try:
        return sheet.worksheet(nombre)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=nombre, rows=1000, cols=20)
        ws.update(values=[SCHEMA[nombre]], range_name="A1")
        return ws


@st.cache_data(ttl=120)
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
    # Convertir TODO a string para preservar ceros a la izquierda en códigos
    df = df.astype(str).replace({"nan": "", "None": "", "<NA>": ""})
    ws = _get_ws(nombre)
    valores = [cols] + df.values.tolist()
    # IMPORTANTE: clear() PRIMERO y después update() — caso contrario, si la tabla
    # crecio mas alla del rango hardcodeado, quedan "filas fantasma" con datos viejos.
    # RAW para que Sheets no reinterprete tipos (preserva ceros a la izquierda en codigos).
    ws.clear()
    ws.update(values=valores, range_name="A1", value_input_option="RAW")
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


def _marcar_modificacion(clave):
    """Persiste timestamp 'YYYY-MM-DD HH:MM:SS' en config con key=ultima_carga_<clave>."""
    ts = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    try:
        guardar_config({f"ultima_carga_{clave}": ts})
    except Exception:
        pass


def ultima_carga(clave):
    """Devuelve el timestamp de la última carga registrada para esa clave, o None."""
    cfg = cargar_config()
    return cfg.get(f"ultima_carga_{clave}") or None


# ---------------- PRODUCTOS ----------------

def cargar_productos():
    df = leer_tabla("productos")
    if not df.empty:
        df["codigo"] = df["codigo"].astype(str)
    return df


def guardar_productos(df):
    escribir_tabla("productos", df)
    _marcar_modificacion("dux_productos")


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
    _marcar_modificacion("compuestos")


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
    _marcar_modificacion("stock")


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
    _marcar_modificacion("estimado")


def fechas_estimado():
    df = cargar_estimado_completo()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- ESTIMADO SEMANAL (por dia de la semana, fijo) ----------------

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def cargar_estimado_semanal(dia=None):
    """Si dia=None devuelve TODO el estimado semanal. Si dia='lunes' filtra."""
    df = leer_tabla("estimado_semanal")
    if df.empty:
        return df
    df["codigo"] = df["codigo"].astype(str)
    df["dia_semana"] = df["dia_semana"].astype(str)
    df["estimado"] = pd.to_numeric(df["estimado"], errors="coerce").fillna(0)
    if dia is not None:
        df = df[df["dia_semana"] == str(dia)].reset_index(drop=True)
    return df


def guardar_estimado_semanal_dia(df_dia, dia):
    """Reemplaza el estimado del dia indicado."""
    full = leer_tabla("estimado_semanal")
    if not full.empty and "dia_semana" in full.columns:
        otros = full[full["dia_semana"] != str(dia)]
    else:
        otros = pd.DataFrame(columns=SCHEMA["estimado_semanal"])
    nuevo = df_dia.copy()
    nuevo["dia_semana"] = str(dia)
    combinado = pd.concat(
        [otros, nuevo[SCHEMA["estimado_semanal"]]], ignore_index=True
    )
    escribir_tabla("estimado_semanal", combinado)
    _marcar_modificacion("estimado_semanal")


def dias_semana_con_estimado():
    df = leer_tabla("estimado_semanal")
    if df.empty:
        return []
    return sorted(df["dia_semana"].dropna().unique().tolist())


# ---------------- WIX PRODUCTOS ----------------

def cargar_wix_productos():
    df = leer_tabla("wix_productos")
    if not df.empty:
        df["wix_id"] = df["wix_id"].astype(str)
    return df


def guardar_wix_productos(df):
    escribir_tabla("wix_productos", df)
    _marcar_modificacion("wix_productos")


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
    _marcar_modificacion("mapping_wix_dux")


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
    _marcar_modificacion("packs")


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


# ---------------- PEDIDOS (DUX y WIX) ----------------

def _cargar_pedidos(fuente):
    """fuente: 'dux' o 'wix'. Devuelve lista de dicts (cada uno es un pedido)."""
    nombre = f"pedidos_{fuente}"
    df = leer_tabla(nombre)
    if df.empty or "json" not in df.columns:
        return []
    pedidos = []
    for raw in df["json"].astype(str):
        if not raw or raw == "<NA>":
            continue
        try:
            pedidos.append(_json.loads(raw))
        except Exception:
            continue
    return pedidos


def _guardar_pedidos(fuente, pedidos, fecha_field_candidates):
    """fuente: 'dux' o 'wix'. pedidos: lista de dicts. Persiste cada uno como fila."""
    nombre = f"pedidos_{fuente}"
    rows = []
    for p in pedidos:
        oid = str(p.get("id") or p.get("nro_pedido") or p.get("nroPedido") or "")
        fecha = ""
        for k in fecha_field_candidates:
            if p.get(k):
                fecha = str(p.get(k))
                break
        rows.append({
            "order_id": oid,
            "fecha": fecha,
            "json": _json.dumps(p, ensure_ascii=False),
        })
    df = pd.DataFrame(rows, columns=SCHEMA[nombre])
    escribir_tabla(nombre, df)
    _marcar_modificacion(f"pedidos_{fuente}")


def cargar_pedidos_dux():
    return _cargar_pedidos("dux")


def guardar_pedidos_dux(pedidos):
    _guardar_pedidos("dux", pedidos, ["fecha", "fecha_pedido", "fechaPedido"])


def cargar_pedidos_wix():
    return _cargar_pedidos("wix")


def guardar_pedidos_wix(pedidos):
    _guardar_pedidos("wix", pedidos, ["createdDate", "created_date"])


# ---------------- PROVEEDORES ----------------

def cargar_proveedores():
    df = leer_tabla("proveedores")
    if df.empty:
        return df
    # Migracion suave: schema viejo (razon_social, cuit) -> nuevo (proveedor, cuit_cuil)
    if "razon_social" in df.columns and "proveedor" not in df.columns:
        df = df.rename(columns={"razon_social": "proveedor"})
    if "cuit" in df.columns and "cuit_cuil" not in df.columns:
        df = df.rename(columns={"cuit": "cuit_cuil"})
    # Asegurar todas las columnas del schema (vacias si no existen)
    for c in SCHEMA["proveedores"]:
        if c not in df.columns:
            df[c] = ""
    df["proveedor_id"] = df["proveedor_id"].astype(str)
    return df


def guardar_proveedores(df):
    escribir_tabla("proveedores", df)
    _marcar_modificacion("proveedores")


# ---------------- COMPRAS ----------------

def cargar_compras():
    df = leer_tabla("compras")
    if df.empty:
        return df
    df["fecha"] = df["fecha"].astype(str)
    df["proveedor_id"] = df["proveedor_id"].astype(str)
    df["codigo_producto"] = df["codigo_producto"].astype(str)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["precio"] = pd.to_numeric(df["precio"], errors="coerce").fillna(0)
    return df


def guardar_compras_fecha(df_fecha, fecha):
    """Reemplaza las compras de una fecha. df_fecha debe tener las columnas del schema (sin fecha)."""
    full = cargar_compras()
    if not full.empty and "fecha" in full.columns:
        otros = full[full["fecha"] != str(fecha)]
    else:
        otros = pd.DataFrame(columns=SCHEMA["compras"])
    nuevo = df_fecha.copy()
    nuevo["fecha"] = str(fecha)
    combinado = pd.concat(
        [otros, nuevo[SCHEMA["compras"]]], ignore_index=True
    )
    escribir_tabla("compras", combinado)
    _marcar_modificacion("compras")


def fechas_compras():
    df = cargar_compras()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- CONFIG (key/value para preferencias) ----------------

def cargar_config():
    """Devuelve dict {key: value} con la configuración persistida."""
    df = leer_tabla("config")
    if df.empty or "key" not in df.columns:
        return {}
    return dict(zip(df["key"].astype(str), df["value"].astype(str)))


def guardar_config(updates):
    """Merge dict updates con la config existente y persiste a Sheets."""
    actual = cargar_config()
    actual.update({k: str(v) for k, v in updates.items() if v is not None})
    rows = [{"key": k, "value": v} for k, v in actual.items()]
    df = pd.DataFrame(rows, columns=SCHEMA["config"])
    escribir_tabla("config", df)

"""Capa de acceso a Supabase como base de datos.
Expone la misma API pública que gsheets_db.py para que app.py no necesite cambios.
"""

import json as _json
import pandas as pd
import streamlit as st
from supabase import create_client, Client

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


# ---------------- CONEXIÓN ----------------

@st.cache_resource
def get_client() -> Client:
    cfg = st.secrets.get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("key")
    if not url or not key:
        raise RuntimeError("Credenciales de Supabase no configuradas en secrets.toml")
    return create_client(url, key)


def _drop_meta(df):
    """Saca columnas internas de Supabase que no forman parte del schema."""
    for col in ["created_at", "updated_at"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    return df


def ultima_carga(clave):
    """Devuelve el updated_at más reciente de la tabla correspondiente, o None."""
    tabla_map = {
        "dux_productos": "productos",
        "compuestos": "compuestos",
        "pedidos_wix": "pedidos_wix",
        "pedidos_dux": "pedidos_dux",
        "stock": "stock_historico",
        "estimado": "estimado_historico",
        "estimado_semanal": "estimado_semanal",
        "compras": "compras",
        "proveedores": "proveedores",
        "wix_productos": "wix_productos",
        "mapping_wix_dux": "mapping_wix_dux",
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
    df = _drop_meta(df)
    df["codigo"] = df["codigo"].astype(str)
    if "rubro" not in df.columns:
        df["rubro"] = ""
    return df


def guardar_productos(df):
    client = get_client()
    client.table("productos").delete().neq("codigo", "___never___").execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("productos").insert(records).execute()


# ---------------- COMPUESTOS ----------------

def cargar_compuestos():
    client = get_client()
    resp = client.table("compuestos").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["codigo_origen", "producto_origen", "cantidad_origen", "codigo_componente", "producto_componente", "cantidad_componente"])
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    for col in ["codigo_origen", "codigo_componente"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    for col in ["cantidad_origen", "cantidad_componente"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def guardar_compuestos(df):
    client = get_client()
    client.table("compuestos").delete().gte("id", 1).execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("compuestos").insert(records).execute()


# ---------------- STOCK ----------------

def cargar_stock_completo():
    client = get_client()
    resp = client.table("stock_historico").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return df
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["codigo"] = df["codigo"].astype(str)
    df["fecha"] = df["fecha"].astype(str)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    return df


def cargar_stock(fecha=None):
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
    client = get_client()
    client.table("stock_historico").delete().eq("fecha", str(fecha)).execute()
    if not df_fecha.empty:
        nuevo = df_fecha.copy()
        nuevo["fecha"] = str(fecha)
        records = nuevo.where(pd.notnull(nuevo), None).to_dict(orient="records")
        client.table("stock_historico").insert(records).execute()


def fechas_stock():
    df = cargar_stock_completo()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- ESTIMADO ----------------

def cargar_estimado_completo():
    client = get_client()
    resp = client.table("estimado_historico").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return df
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["codigo"] = df["codigo"].astype(str)
    df["fecha"] = df["fecha"].astype(str)
    df["estimado"] = pd.to_numeric(df["estimado"], errors="coerce")
    return df


def cargar_estimado(fecha=None):
    df = cargar_estimado_completo()
    if df.empty:
        return pd.DataFrame(columns=["codigo", "producto", "unidad_medida", "estimado"])
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
    client = get_client()
    client.table("estimado_historico").delete().eq("fecha", str(fecha)).execute()
    if not df_fecha.empty:
        nuevo = df_fecha.copy()
        nuevo["fecha"] = str(fecha)
        records = nuevo.where(pd.notnull(nuevo), None).to_dict(orient="records")
        client.table("estimado_historico").insert(records).execute()


def fechas_estimado():
    df = cargar_estimado_completo()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- ESTIMADO SEMANAL ----------------

def cargar_estimado_semanal(dia=None):
    client = get_client()
    resp = client.table("estimado_semanal").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return df
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["codigo"] = df["codigo"].astype(str)
    df["dia_semana"] = df["dia_semana"].astype(str)
    df["estimado"] = pd.to_numeric(df["estimado"], errors="coerce").fillna(0)
    if dia is not None:
        df = df[df["dia_semana"] == str(dia)].reset_index(drop=True)
    return df


def guardar_estimado_semanal_dia(df_dia, dia):
    client = get_client()
    client.table("estimado_semanal").delete().eq("dia_semana", str(dia)).execute()
    if not df_dia.empty:
        nuevo = df_dia.copy()
        nuevo["dia_semana"] = str(dia)
        records = nuevo.where(pd.notnull(nuevo), None).to_dict(orient="records")
        client.table("estimado_semanal").insert(records).execute()


def dias_semana_con_estimado():
    client = get_client()
    resp = client.table("estimado_semanal").select("dia_semana").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return []
    return sorted(df["dia_semana"].dropna().unique().tolist())


# ---------------- WIX PRODUCTOS ----------------

def cargar_wix_productos():
    client = get_client()
    resp = client.table("wix_productos").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["wix_id", "producto", "descripcion"])
    df = _drop_meta(df)
    df["wix_id"] = df["wix_id"].astype(str)
    return df


def guardar_wix_productos(df):
    client = get_client()
    client.table("wix_productos").delete().neq("wix_id", "___never___").execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("wix_productos").insert(records).execute()


# ---------------- MAPPING WIX DUX ----------------

def cargar_mapping_wix_dux():
    client = get_client()
    resp = client.table("mapping_wix_dux").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["wix_id", "wix_producto", "dux_codigo", "dux_producto", "factor"])
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    for col in ["wix_id", "dux_codigo"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    if "factor" in df.columns:
        df["factor"] = pd.to_numeric(df["factor"], errors="coerce").fillna(1.0)
    return df


def guardar_mapping_wix_dux(df):
    client = get_client()
    client.table("mapping_wix_dux").delete().gte("id", 1).execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("mapping_wix_dux").insert(records).execute()


# ---------------- PACKS WIX ----------------

def cargar_packs_wix():
    client = get_client()
    resp = client.table("packs_wix").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["wix_id_pack", "pack_nombre", "dux_codigo", "dux_producto", "cantidad"])
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    for col in ["wix_id_pack", "dux_codigo"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    if "cantidad" in df.columns:
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    return df


def guardar_packs_wix(df):
    client = get_client()
    client.table("packs_wix").delete().gte("id", 1).execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("packs_wix").insert(records).execute()


# ---------------- SELECCIONES ----------------

def cargar_selecciones(fuente):
    """fuente: 'dux' o 'wix'. Devuelve dict {order_id: fecha_entrega}."""
    client = get_client()
    resp = client.table(f"selecciones_{fuente}").select("order_id,fecha_entrega").execute()
    if not resp.data:
        return {}
    return {str(r["order_id"]): str(r["fecha_entrega"]) for r in resp.data}


def guardar_selecciones(fuente, selecciones):
    """fuente: 'dux' o 'wix'. selecciones: dict {order_id: fecha_entrega}."""
    client = get_client()
    tabla = f"selecciones_{fuente}"
    client.table(tabla).delete().neq("order_id", "___never___").execute()
    rows = [
        {"order_id": str(oid), "fecha_entrega": str(fent)}
        for oid, fent in selecciones.items()
        if fent
    ]
    if rows:
        client.table(tabla).insert(rows).execute()


# ---------------- PEDIDOS ----------------

def _cargar_pedidos(fuente):
    client = get_client()
    resp = client.table(f"pedidos_{fuente}").select("json").execute()
    if not resp.data:
        return []
    pedidos = []
    for r in resp.data:
        raw = r.get("json") or ""
        if not raw:
            continue
        try:
            pedidos.append(_json.loads(raw))
        except Exception:
            continue
    return pedidos


def _guardar_pedidos(fuente, pedidos, fecha_field_candidates):
    """Merge por order_id: los existentes se actualizan, los nuevos se agregan."""
    client = get_client()
    tabla = f"pedidos_{fuente}"

    # Traer existentes
    resp = client.table(tabla).select("order_id,fecha,json").execute()
    merged = {}
    for r in (resp.data or []):
        oid = str(r.get("order_id") or "")
        if oid:
            merged[oid] = r

    # Mergear con los nuevos (gana la versión recibida)
    for p in pedidos:
        oid = str(p.get("id") or p.get("nro_pedido") or p.get("nroPedido") or "")
        if not oid:
            continue
        fecha = ""
        for k in fecha_field_candidates:
            if p.get(k):
                fecha = str(p.get(k))
                break
        merged[oid] = {
            "order_id": oid,
            "fecha": fecha,
            "json": _json.dumps(p, ensure_ascii=False),
        }

    if not merged:
        return 0

    # Upsert todo
    rows = list(merged.values())
    client.table(tabla).upsert(rows, on_conflict="order_id").execute()
    return 0


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
    client = get_client()
    resp = client.table("proveedores").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["proveedor_id", "proveedor", "cuit_cuil", "telefono", "email", "notas"])
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    if "razon_social" in df.columns and "proveedor" not in df.columns:
        df = df.rename(columns={"razon_social": "proveedor"})
    if "cuit" in df.columns and "cuit_cuil" not in df.columns:
        df = df.rename(columns={"cuit": "cuit_cuil"})
    df["proveedor_id"] = df["proveedor_id"].astype(str)
    return df


def guardar_proveedores(df):
    client = get_client()
    client.table("proveedores").delete().neq("proveedor_id", "___never___").execute()
    if not df.empty:
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        client.table("proveedores").insert(records).execute()


# ---------------- COMPRAS ----------------

def cargar_compras():
    client = get_client()
    resp = client.table("compras").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return df
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["fecha"] = df["fecha"].astype(str)
    df["proveedor_id"] = df["proveedor_id"].astype(str)
    df["codigo_producto"] = df["codigo_producto"].astype(str)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["precio"] = pd.to_numeric(df["precio"], errors="coerce").fillna(0)
    if "comprobante" not in df.columns:
        df["comprobante"] = ""
    df["comprobante"] = df["comprobante"].astype(str)
    return df


def _proximo_comprobante_id():
    cfg = cargar_config()
    try:
        n = int(cfg.get("next_comprobante_id", "1"))
    except (ValueError, TypeError):
        n = 1
    nuevo = f"APP-{n:05d}"
    guardar_config({"next_comprobante_id": str(n + 1)})
    return nuevo


def guardar_compras_fecha(df_fecha, fecha):
    client = get_client()

    # Traer comprobantes existentes para esta fecha
    resp = client.table("compras").select("proveedor_id,comprobante").eq("fecha", str(fecha)).execute()
    prov_a_compr = {}
    for r in (resp.data or []):
        pid = str(r.get("proveedor_id", ""))
        c = str(r.get("comprobante", "") or "")
        if pid and c and pid not in prov_a_compr:
            prov_a_compr[pid] = c

    # Asignar comprobante a cada línea
    df_fecha = df_fecha.copy()
    nuevos_compr = {}
    comprobantes = []
    for _, r in df_fecha.iterrows():
        pid = str(r.get("proveedor_id", "") or "")
        if not pid:
            comprobantes.append("")
        elif pid in prov_a_compr:
            comprobantes.append(prov_a_compr[pid])
        elif pid in nuevos_compr:
            comprobantes.append(nuevos_compr[pid])
        else:
            nuevo = _proximo_comprobante_id()
            nuevos_compr[pid] = nuevo
            comprobantes.append(nuevo)
    df_fecha["comprobante"] = comprobantes
    df_fecha["fecha"] = str(fecha)

    client.table("compras").delete().eq("fecha", str(fecha)).execute()
    records = df_fecha.where(pd.notnull(df_fecha), None).to_dict(orient="records")
    if records:
        client.table("compras").insert(records).execute()


def fechas_compras():
    df = cargar_compras()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


# ---------------- MIXES DUX ----------------

def cargar_mixes_dux():
    client = get_client()
    resp = client.table("mixes_dux").select("mix_base,componente_base").execute()
    if not resp.data:
        return {}
    out = {}
    for r in resp.data:
        mb = str(r.get("mix_base", "") or "").strip()
        cb = str(r.get("componente_base", "") or "").strip()
        if mb and cb:
            out.setdefault(mb, []).append(cb)
    return out


def guardar_mixes_dux(mixes_dict):
    client = get_client()
    client.table("mixes_dux").delete().gte("id", 1).execute()
    rows = []
    for mb, comps in mixes_dict.items():
        for cb in comps:
            rows.append({"mix_base": str(mb), "componente_base": str(cb)})
    if rows:
        client.table("mixes_dux").insert(rows).execute()


# ---------------- CONFIG ----------------

def cargar_config():
    client = get_client()
    resp = client.table("config").select("key,value").execute()
    if not resp.data:
        return {}
    return {str(r["key"]): str(r["value"]) for r in resp.data}


def guardar_config(updates):
    if not updates:
        return
    client = get_client()
    rows = [{"key": str(k), "value": str(v)} for k, v in updates.items() if v is not None]
    if rows:
        client.table("config").upsert(rows, on_conflict="key").execute()


# ---------------- STOCK TEORICO ----------------

def guardar_stock_teorico(rows, f0, fc, fp):
    client = get_client()
    filas = [
        {
            "codigo": str(r.get("Código", "") or ""),
            "producto": str(r.get("Producto", "") or ""),
            "stock_inicial": float(r.get("Stock inicial", 0) or 0),
            "compras": float(r.get("+ Compras", 0) or 0),
            "pedidos": float(r.get("− Pedidos", 0) or 0),
            "teorico": float(r.get("= Teórico", 0) or 0),
        }
        for r in rows
    ]
    client.table("stock_teorico_ultimo").delete().gte("id", 1).execute()
    if filas:
        client.table("stock_teorico_ultimo").insert(filas).execute()

    ts = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").strftime("%Y-%m-%d %H:%M:%S")
    guardar_config({
        "st_teorico_ultimo_f0": str(f0),
        "st_teorico_ultimo_fc": str(fc),
        "st_teorico_ultimo_fp": str(fp),
        "st_teorico_ultimo_ts": ts,
    })


def cargar_stock_teorico():
    client = get_client()
    resp = client.table("stock_teorico_ultimo").select("*").execute()
    cfg = cargar_config()
    rows = []
    for r in (resp.data or []):
        try:
            rows.append({
                "Código": str(r.get("codigo", "") or ""),
                "Producto": str(r.get("producto", "") or ""),
                "Stock inicial": float(r.get("stock_inicial", 0) or 0),
                "+ Compras": float(r.get("compras", 0) or 0),
                "− Pedidos": float(r.get("pedidos", 0) or 0),
                "= Teórico": float(r.get("teorico", 0) or 0),
            })
        except (ValueError, TypeError):
            continue

    def _parse_date(s):
        if not s:
            return None
        try:
            return pd.to_datetime(s).date()
        except Exception:
            return None

    return {
        "rows": rows,
        "f0": _parse_date(cfg.get("st_teorico_ultimo_f0")),
        "fc": _parse_date(cfg.get("st_teorico_ultimo_fc")),
        "fp": _parse_date(cfg.get("st_teorico_ultimo_fp")),
        "ts": cfg.get("st_teorico_ultimo_ts"),
    }


def guardar_stock_teorico_detalle(map_stock_ini, map_compras, compras_raw, dux_contados, wix_contados):
    def _safe(obj):
        try:
            return _json.dumps(obj, ensure_ascii=False)
        except Exception:
            return "{}" if isinstance(obj, dict) else "[]"

    guardar_config({
        "std_map_stock_ini": _safe(map_stock_ini),
        "std_map_compras": _safe(map_compras),
        "std_compras_raw": _safe(compras_raw),
        "std_dux_contados": _safe(dux_contados),
        "std_wix_contados": _safe(wix_contados),
    })


def cargar_stock_teorico_detalle():
    cfg = cargar_config()

    def _parse(key, default):
        v = cfg.get(key, "")
        if not v:
            return default
        try:
            return _json.loads(v)
        except Exception:
            return default

    return {
        "map_stock_ini": _parse("std_map_stock_ini", {}),
        "map_compras": _parse("std_map_compras", {}),
        "compras_raw": _parse("std_compras_raw", []),
        "dux_contados": _parse("std_dux_contados", []),
        "wix_contados": _parse("std_wix_contados", []),
    }

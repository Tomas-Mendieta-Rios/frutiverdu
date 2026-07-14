"""Capa de acceso a Supabase como base de datos.
Expone la misma API pública que gsheets_db.py para que app.py no necesite cambios.
"""

import json as _json
import pandas as pd
import streamlit as st
from supabase import create_client, Client

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

SCHEMA = {
    "productos": ["codigo", "producto", "unidad_medida", "descripcion", "rubro"],
    "compuestos": ["codigo_origen", "producto_origen", "cantidad_origen", "codigo_componente", "producto_componente", "cantidad_componente"],
    "stock_historico": ["fecha", "codigo", "producto", "unidad_medida", "cantidad"],
    "estimado_historico": ["fecha", "codigo", "producto", "unidad_medida", "estimado"],
    "estimado_semanal": ["dia_semana", "codigo", "producto", "unidad_medida", "estimado"],
    "wix_productos": ["wix_id", "producto", "descripcion"],
    "mapping_wix_dux": ["wix_id", "wix_producto", "dux_codigo", "dux_producto", "factor"],
    "packs_wix": ["wix_id_pack", "pack_nombre", "dux_codigo", "dux_producto", "cantidad"],
    "selecciones_dux": ["order_id", "fecha_entrega"],
    "selecciones_wix": ["order_id", "fecha_entrega"],
    "pedidos_dux": ["order_id", "fecha", "json"],
    "pedidos_wix": ["order_id", "fecha", "json"],
    "proveedores": ["proveedor_id", "proveedor", "nombre_fantasia", "categoria_fiscal", "tipo_documento", "numero_documento", "cuit_cuil", "codigo", "email", "provincia", "localidad", "barrio", "domicilio", "telefono", "celular", "condicion_pago", "fecha_creacion", "persona_contacto", "lugar_entrega", "tipo_comprobante", "habilitado"],
    "comprobantes_compra": ["nro_comprobante", "fecha", "proveedor_id", "proveedor_nombre", "condicion_pago"],
    "items_compra": ["comprobante_id", "codigo_producto", "producto_nombre", "cantidad", "precio"],
    "mixes_dux": ["mix_base", "componente_base"],
    "config": ["key", "value"],
}


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
        "gastos": "gastos",
        "dux_rubros": "rubros",
        "dux_subrubros": "subrubros",
    }
    tabla = tabla_map.get(clave, clave)
    client = get_client()
    for col in ("updated_at", "created_at"):
        try:
            resp = client.table(tabla).select(col).order(col, desc=True).limit(1).execute()
            if resp.data and resp.data[0].get(col):
                return resp.data[0][col]
        except Exception:
            continue
    return None


# ---------------- PRODUCTOS ----------------

def _productos_lookup():
    """Dict {codigo: nombre} para enriquecer items sin descripcion en DUX."""
    client = get_client()
    resp = client.table("productos").select("codigo, producto").execute()
    return {str(r.get("codigo", "")): str(r.get("producto") or "") for r in (resp.data or [])}


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


# ---------------- RUBROS / SUBRUBROS ----------------

def cargar_rubros():
    client = get_client()
    resp = client.table("rubros").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "nombre"])
    df = _drop_meta(df)
    return df


def guardar_rubros(registros):
    client = get_client()
    client.table("rubros").delete().neq("id", -1).execute()
    if registros:
        client.table("rubros").insert(registros).execute()


def cargar_subrubros():
    client = get_client()
    resp = client.table("subrubros").select("*").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "nombre", "rubro_id", "rubro_nombre"])
    df = _drop_meta(df)
    return df


def guardar_subrubros(registros):
    client = get_client()
    client.table("subrubros").delete().neq("id", -1).execute()
    if registros:
        client.table("subrubros").insert(registros).execute()


# ---------------- GASTOS CATÁLOGO ----------------

@st.cache_data(ttl=600)
def cargar_gastos_catalogo():
    client = get_client()
    resp = client.table("gastos_catalogo").select("*").order("rubro").order("sub_rubro").order("gasto").execute()
    df = pd.DataFrame(resp.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "cod_producto", "gasto", "rubro", "sub_rubro", "proveedor"])
    return _drop_meta(df)


def guardar_gastos_catalogo(registros):
    client = get_client()
    client.table("gastos_catalogo").delete().neq("id", -1).execute()
    if registros:
        client.table("gastos_catalogo").insert(registros).execute()
    st.cache_data.clear()


def eliminar_gastos_catalogo_item(item_id):
    client = get_client()
    client.table("gastos_catalogo").delete().eq("id", item_id).execute()
    st.cache_data.clear()


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

def _norm_fecha_iso(x):
    """Convierte cualquier formato de fecha a 'YYYY-MM-DD'. Devuelve None si inválido."""
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "None", "nan", "NaT"):
        return None
    # Fast path: ya es ISO (empieza con YYYY-)
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    # Slow path: puede ser DD/MM/YYYY (Sheets argentino) o MM/DD/YYYY
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _fetch_all(client, table, columns="*", filters=None, batch=1000):
    """Pagina sobre una tabla de Supabase y devuelve todos los registros."""
    rows = []
    offset = 0
    while True:
        q = client.table(table).select(columns).range(offset, offset + batch - 1)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        resp = q.execute()
        if not resp.data:
            break
        rows.extend(resp.data)
        if len(resp.data) < batch:
            break
        offset += batch
    return rows


def cargar_stock_completo():
    client = get_client()
    rows = _fetch_all(client, "stock_historico")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["codigo"] = df["codigo"].astype(str)
    df["fecha"] = df["fecha"].apply(_norm_fecha_iso)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    df = df[df["fecha"].notna()]
    return df


def cargar_stock(fecha=None):
    client = get_client()
    if fecha is None:
        # Sin fecha: devolver la fecha más reciente disponible
        fechas = fechas_stock()
        if not fechas:
            return pd.DataFrame(columns=["codigo", "producto", "unidad_medida", "cantidad"])
        fecha = fechas[0]
    f_str = _norm_fecha_iso(str(fecha)) or str(fecha)
    rows = _fetch_all(client, "stock_historico", filters={"fecha": f_str})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["codigo", "producto", "unidad_medida", "cantidad"])
    df = _drop_meta(df)
    if "id" in df.columns:
        df = df.drop(columns=["id"])
    df["codigo"] = df["codigo"].astype(str)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
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
    client = get_client()
    rows = _fetch_all(client, "stock_historico", columns="fecha")
    fechas = set()
    for row in rows:
        f = _norm_fecha_iso(row.get("fecha"))
        if f:
            fechas.add(f)
    return sorted(fechas, reverse=True)


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

# ---------------- PEDIDOS DUX ----------------

def cargar_pedidos_dux():
    client = get_client()
    resp_orders = client.table("pedidos_dux").select("*").limit(10000).execute()
    if not resp_orders.data:
        return []

    all_items = _fetch_all(client, "pedidos_dux_items")
    prods = _productos_lookup()
    items_por_order = {}
    for it in all_items:
        oid = str(it.get("order_id") or "")
        if oid:
            cod = str(it.get("cod_item") or "")
            items_por_order.setdefault(oid, []).append({
                "cod_item": it.get("cod_item"),
                "item": it.get("item") or prods.get(cod, ""),
                "ctd": it.get("ctd"),
                "precio_uni": it.get("precio_uni"),
                "porc_desc": it.get("porc_desc"),
                "porc_iva": it.get("porc_iva"),
                "comentarios": it.get("comentarios"),
                "ctd_facturada": it.get("ctd_facturada"),
                "ctd_con_remito": it.get("ctd_con_remito"),
            })

    pedidos = []
    for r in resp_orders.data:
        oid = str(r.get("order_id") or "")
        pedidos.append({
            "id": oid,
            "nro_pedido": r.get("nro_pedido"),
            "fecha": r.get("fecha"),
            "cliente": {"razon_social": r.get("cliente")},
            "estado_facturacion": r.get("estado_facturacion"),
            "estado_remito": r.get("estado_remito"),
            "anulado": r.get("anulado", "N"),
            "lugar_entrega": r.get("lugar_entrega"),
            "monto_exento": r.get("monto_exento"),
            "monto_gravado": r.get("monto_gravado"),
            "monto_iva": r.get("monto_iva"),
            "monto_descuento": r.get("monto_descuento"),
            "total": r.get("total"),
            "condicion_pago": r.get("condicion_pago"),
            "detalles": items_por_order.get(oid, []),
        })
    return pedidos


def guardar_pedidos_dux(pedidos):
    client = get_client()
    order_rows = []
    items_por_order = {}

    for p in pedidos:
        oid = str(p.get("id") or p.get("nro_pedido") or p.get("nroPedido") or "")
        if not oid:
            continue

        cliente = p.get("cliente")
        if isinstance(cliente, dict):
            cliente_str = (
                cliente.get("razon_social") or cliente.get("nombre") or
                cliente.get("razonSocial") or ""
            )
        else:
            cliente_str = str(cliente or "")

        order_rows.append({
            "order_id": oid,
            "nro_pedido": str(p.get("nro_pedido") or p.get("nroPedido") or ""),
            "fecha": str(p.get("fecha") or p.get("fecha_pedido") or p.get("fechaPedido") or ""),
            "cliente": cliente_str,
            "estado_facturacion": str(p.get("estado_facturacion") or ""),
            "estado_remito": str(p.get("estado_remito") or ""),
            "anulado": str(p.get("anulado") or "N"),
            "lugar_entrega": str(p.get("lugar_entrega") or ""),
            "monto_exento": _to_float(p.get("monto_exento")),
            "monto_gravado": _to_float(p.get("monto_gravado")),
            "monto_iva": _to_float(p.get("monto_iva")),
            "monto_descuento": _to_float(p.get("monto_descuento")),
            "total": _to_float(p.get("total")),
            "condicion_pago": str(p.get("condicion_pago") or ""),
        })

        detalles = []
        for f in ["detalles", "items", "productos", "lineas", "renglones", "detalle"]:
            v = p.get(f)
            if isinstance(v, list):
                detalles = v
                break

        items_por_order[oid] = [
            {
                "order_id": oid,
                "cod_item": str(it.get("cod_item") or it.get("codItem") or ""),
                "item": str(it.get("item") or it.get("descripcion") or ""),
                "ctd": _to_float(it.get("ctd") or it.get("cantidad")),
                "precio_uni": _to_float(it.get("precio_uni")),
                "porc_desc": _to_float(it.get("porc_desc")),
                "porc_iva": _to_float(it.get("porc_iva")),
                "comentarios": str(it.get("comentarios") or ""),
                "ctd_facturada": _to_float(it.get("ctd_facturada")),
                "ctd_con_remito": _to_float(it.get("ctd_con_remito")),
            }
            for it in detalles
        ]

    if not order_rows:
        return

    # Deduplicar por order_id antes del upsert: Postgres rechaza el batch si
    # el mismo order_id aparece dos veces (ON CONFLICT no puede afectar la misma
    # fila dos veces en una sola sentencia).
    dedup = {r["order_id"]: r for r in order_rows}
    order_rows = list(dedup.values())

    client.table("pedidos_dux").upsert(order_rows, on_conflict="order_id").execute()

    _oids = list(items_por_order.keys())
    client.table("pedidos_dux_items").delete().in_("order_id", _oids).execute()
    _all_items = [it for its in items_por_order.values() for it in its]
    if _all_items:
        client.table("pedidos_dux_items").insert(_all_items).execute()


def _to_float(v):
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


# ---------------- CAJAS ----------------

@st.cache_data(ttl=300)
def cargar_cajas():
    client = get_client()
    resp = client.table("cajas").select("*").order("id").execute()
    return resp.data or []


def guardar_cajas(cajas):
    client = get_client()
    ids_nuevos = {int(c["id"]) for c in cajas if c.get("id")}
    # Eliminar cajas que ya no están en la lista (nullear FK en pedidos_wix primero)
    existing = client.table("cajas").select("id").execute()
    ids_existentes = {r["id"] for r in (existing.data or [])}
    ids_a_borrar = ids_existentes - ids_nuevos
    for caja_id in ids_a_borrar:
        try:
            client.table("pedidos_wix").update({"caja_id": None}).eq("caja_id", caja_id).execute()
        except Exception:
            pass
        client.table("cajas").delete().eq("id", caja_id).execute()
    # Update / insert
    for c in cajas:
        caja_id = c.get("id")
        nombre = (c.get("nombre") or "").strip()
        activa = bool(c.get("activa", True))
        if not nombre:
            continue
        if caja_id:
            client.table("cajas").update({"nombre": nombre, "activa": activa}).eq("id", caja_id).execute()
        else:
            client.table("cajas").insert({"nombre": nombre, "activa": activa}).execute()
    cargar_cajas.clear()


@st.cache_data(ttl=120)
def cargar_ajustes_caja():
    client = get_client()
    resp = client.table("cajas_ajustes").select("*").order("fecha").execute()
    return resp.data or []


def guardar_ajuste_caja(caja_id, fecha, monto, nota="", tipo="ajuste"):
    client = get_client()
    if tipo == "inicial":
        # Solo puede haber uno por caja — reemplazar si existe
        existing = client.table("cajas_ajustes").select("id").eq("caja_id", caja_id).eq("tipo", "inicial").execute()
        if existing.data:
            client.table("cajas_ajustes").update({
                "fecha": str(fecha), "monto": float(monto), "nota": nota or "",
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            client.table("cajas_ajustes").insert({
                "caja_id": caja_id, "fecha": str(fecha),
                "monto": float(monto), "nota": nota or "", "tipo": "inicial",
            }).execute()
    else:
        client.table("cajas_ajustes").insert({
            "caja_id": caja_id, "fecha": str(fecha),
            "monto": float(monto), "nota": nota or "", "tipo": "ajuste",
        }).execute()
    cargar_ajustes_caja.clear()


def eliminar_ajuste_caja(ajuste_id):
    client = get_client()
    client.table("cajas_ajustes").delete().eq("id", ajuste_id).execute()
    cargar_ajustes_caja.clear()


def asignar_cajas_pedidos_wix(asignaciones):
    """asignaciones: dict {order_id: caja_id | None}"""
    client = get_client()
    for order_id, caja_id in asignaciones.items():
        client.table("pedidos_wix").update({"caja_id": caja_id}).eq("order_id", order_id).execute()
    cargar_pedidos_wix.clear()


def cargar_fechas_pago_wix():
    """Devuelve dict {order_id: fecha_pago}."""
    client = get_client()
    resp = client.table("fechas_pago_wix").select("order_id,fecha_pago").execute()
    return {r["order_id"]: r["fecha_pago"] for r in (resp.data or [])}


def guardar_fechas_pago_wix(fechas):
    """fechas: dict {order_id: fecha_pago_str | None}"""
    client = get_client()
    for order_id, fecha_pago in fechas.items():
        client.table("fechas_pago_wix").upsert(
            {"order_id": str(order_id), "fecha_pago": str(fecha_pago) if fecha_pago else None}
        ).execute()


# ---------------- PERCEPCIONES E IMPUESTOS ----------------

@st.cache_data(ttl=3600)
def cargar_percepciones_impuestos():
    client = get_client()
    resp = client.table("percepciones_impuestos").select("*").order("percepcion_impuesto").execute()
    return resp.data or []


def guardar_percepciones_impuestos(data):
    client = get_client()
    rows = [
        {
            "id_percepcion_impuesto":  p["id_percepcion_impuesto"],
            "percepcion_impuesto":     p.get("percepcion_impuesto"),
            "tipo_percepcion_impuesto": p.get("tipo_percepcion_impuesto"),
            "jurisdiccion":            p.get("jurisdiccion"),
            "descripcion":             p.get("descripcion"),
        }
        for p in data
    ]
    if rows:
        client.table("percepciones_impuestos").upsert(rows).execute()
    cargar_percepciones_impuestos.clear()


# ---------------- PEDIDOS WIX ----------------

@st.cache_data(ttl=600)
def cargar_pedidos_wix():
    client = get_client()
    resp_orders = client.table("pedidos_wix").select("*").limit(10000).execute()
    if not resp_orders.data:
        return []

    resp_items = client.table("pedidos_wix_items").select("*").execute()
    items_por_order = {}
    for it in (resp_items.data or []):
        oid = str(it.get("order_id") or "")
        if oid:
            items_por_order.setdefault(oid, []).append({
                "quantity": it.get("quantity"),
                "catalogReference": {"catalogItemId": it.get("catalog_item_id")},
                "productId": it.get("product_id"),
                "productName": {
                    "translated": it.get("product_name_translated"),
                    "original": it.get("product_name_original"),
                },
                "price": {
                    "formattedAmount": it.get("price_formatted"),
                    "amount": it.get("price_amount"),
                },
            })

    pedidos = []
    for r in resp_orders.data:
        oid = str(r.get("order_id") or "")
        buyer_email = r.get("buyer_email") or r.get("billing_email") or ""
        pedidos.append({
            "id": oid,
            "number": r.get("number"),
            "status": r.get("status"),
            "createdDate": r.get("created_date"),
            "lineItems": items_por_order.get(oid, []),
            "billingInfo": {
                "contactDetails": {
                    "firstName": r.get("billing_first_name"),
                    "lastName": r.get("billing_last_name"),
                    "phone": r.get("billing_phone"),
                    "email": r.get("billing_email"),
                },
            },
            "shippingInfo": {
                "logistics": {
                    "shippingDestination": {
                        "contactDetails": {
                            "firstName": r.get("shipping_first_name"),
                            "lastName": r.get("shipping_last_name"),
                            "phone": r.get("shipping_phone"),
                        },
                        "address": {
                            "addressLine": r.get("shipping_address_line"),
                            "addressLine2": r.get("shipping_address_line2"),
                            "city": r.get("shipping_city"),
                            "subdivision": r.get("shipping_subdivision"),
                        },
                    },
                },
            },
            "buyerInfo": {
                "email": buyer_email,
                "contactDetails": {"email": buyer_email},
            },
            "total_amount": float(r.get("total_amount") or 0),
            "priceSummary": {
                "total": {"formattedAmount": r.get("total_formatted")},
            },
            "paymentStatus": r.get("payment_status"),
            "fulfillmentStatus": r.get("fulfillment_status"),
            "buyerNote": r.get("buyer_note"),
            "updatedDate": r.get("updated_date"),
            "caja_id": r.get("caja_id"),
        })
    return pedidos


def guardar_pedidos_wix(pedidos):
    client = get_client()
    order_rows = []
    items_por_order = {}

    for p in pedidos:
        oid = str(p.get("id") or "")
        if not oid:
            continue

        bi = (p.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
        si_dest = (
            ((p.get("shippingInfo", {}) or {}).get("logistics", {}) or {})
            .get("shippingDestination", {}) or {}
        )
        si_cd = si_dest.get("contactDetails", {}) or {}
        si_addr = si_dest.get("address", {}) or {}
        bu = p.get("buyerInfo", {}) or {}
        buyer_email = (
            bu.get("email")
            or (bu.get("contactDetails", {}) or {}).get("email")
            or bi.get("email")
            or ""
        )
        _price_total = ((p.get("priceSummary", {}) or {}).get("total", {}) or {})
        total_formatted = str(_price_total.get("formattedAmount") or "")
        total_amount = _to_float(_price_total.get("amount"))

        order_rows.append({
            "order_id": oid,
            "number": str(p.get("number") or ""),
            "status": str(p.get("status") or ""),
            "created_date": str(p.get("createdDate") or p.get("created_date") or ""),
            "updated_date": str(p.get("updatedDate") or p.get("updated_date") or ""),
            "billing_first_name": str(bi.get("firstName") or ""),
            "billing_last_name": str(bi.get("lastName") or ""),
            "billing_phone": str(bi.get("phone") or ""),
            "billing_email": str(bi.get("email") or ""),
            "shipping_first_name": str(si_cd.get("firstName") or ""),
            "shipping_last_name": str(si_cd.get("lastName") or ""),
            "shipping_phone": str(si_cd.get("phone") or ""),
            "shipping_address_line": str(si_addr.get("addressLine") or ""),
            "shipping_address_line2": str(si_addr.get("addressLine2") or ""),
            "shipping_city": str(si_addr.get("city") or ""),
            "shipping_subdivision": str(si_addr.get("subdivision") or ""),
            "buyer_email": str(buyer_email),
            "total_formatted": total_formatted,
            "total_amount": total_amount,
            "payment_status": str(p.get("paymentStatus") or ""),
            "fulfillment_status": str(p.get("fulfillmentStatus") or ""),
            "buyer_note": str(p.get("buyerNote") or ""),
        })

        items_por_order[oid] = [
            {
                "order_id": oid,
                "catalog_item_id": str((li.get("catalogReference") or {}).get("catalogItemId") or li.get("productId") or ""),
                "product_id": str(li.get("productId") or ""),
                "product_name_translated": str((li.get("productName") or {}).get("translated") or ""),
                "product_name_original": str((li.get("productName") or {}).get("original") or ""),
                "quantity": _to_float(li.get("quantity")),
                "price_formatted": str((li.get("price") or {}).get("formattedAmount") or ""),
                "price_amount": _to_float((li.get("price") or {}).get("amount")),
            }
            for li in (p.get("lineItems") or [])
        ]

    if not order_rows:
        return

    dedup = {r["order_id"]: r for r in order_rows}
    order_rows = list(dedup.values())

    try:
        client.table("pedidos_wix").upsert(order_rows, on_conflict="order_id").execute()
    except Exception as _e:
        if "total_amount" in str(_e) and "PGRST204" in str(_e):
            for _r in order_rows:
                _r.pop("total_amount", None)
            client.table("pedidos_wix").upsert(order_rows, on_conflict="order_id").execute()
        else:
            raise

    _oids_wix = list(items_por_order.keys())
    client.table("pedidos_wix_items").delete().in_("order_id", _oids_wix).execute()
    _all_wix_items = [it for its in items_por_order.values() for it in its]
    if _all_wix_items:
        client.table("pedidos_wix_items").insert(_all_wix_items).execute()


# ---------------- FACTURAS ----------------

def guardar_facturas(facturas):
    client = get_client()
    rows = []
    items_por_factura = {}

    for f in facturas:
        fid = str(f.get("id") or "")
        if not fid:
            continue
        rows.append({
            "factura_id": fid,
            "tipo_comp": str(f.get("tipo_comp") or ""),
            "letra_comp": str(f.get("letra_comp") or ""),
            "nro_comp": str(f.get("nro_comp") or ""),
            "nro_pto_vta": str(f.get("nro_pto_vta") or ""),
            "fecha_comp": str(f.get("fecha_comp") or ""),
            "apellido_razon_soc": str(f.get("apellido_razon_soc") or ""),
            "nombre": str(f.get("nombre") or ""),
            "cuit": str(f.get("cuit") or ""),
            "nro_pedido": str(f.get("nro_pedido") or ""),
            "monto_exento": _to_float(f.get("monto_exento")),
            "monto_gravado": _to_float(f.get("monto_gravado")),
            "monto_iva": _to_float(f.get("monto_iva")),
            "monto_desc": _to_float(f.get("monto_desc")),
            "total": _to_float(f.get("total")),
            "anulada": str(f.get("anulada") or "N"),
            "con_cobro": bool(f.get("con_cobro", False)),
            "nro_cae_cai": str(f.get("nro_cae_cai") or ""),
            "url_factura": str(f.get("url_factura") or ""),
        })
        detalles = f.get("detalles") or f.get("detalles_json") or []
        items_por_factura[fid] = [
            {
                "factura_id": fid,
                "cod_item": str(it.get("cod_item") or ""),
                "item": str(it.get("item") or ""),
                "ctd": _to_float(it.get("ctd")),
                "precio_uni": _to_float(it.get("precio_uni")),
                "porc_desc": _to_float(it.get("porc_desc")),
                "porc_iva": _to_float(it.get("porc_iva")),
            }
            for it in detalles
        ]

    if not rows:
        return

    dedup = {r["factura_id"]: r for r in rows}
    rows = list(dedup.values())
    try:
        client.table("facturas").upsert(rows, on_conflict="factura_id").execute()
    except Exception as _e:
        if "con_cobro" in str(_e) and "PGRST204" in str(_e):
            for _r in rows:
                _r.pop("con_cobro", None)
            client.table("facturas").upsert(rows, on_conflict="factura_id").execute()
        else:
            raise

    _fids = list(items_por_factura.keys())
    client.table("facturas_items").delete().in_("factura_id", _fids).execute()
    _all_fitems = [it for its in items_por_factura.values() for it in its]
    if _all_fitems:
        client.table("facturas_items").insert(_all_fitems).execute()


@st.cache_data(ttl=600)
def cargar_facturas():
    client = get_client()
    resp = client.table("facturas").select("*").limit(10000).execute()
    if not resp.data:
        return []

    resp_items = client.table("facturas_items").select("*").execute()
    items_por_factura = {}
    for it in (resp_items.data or []):
        fid = str(it.get("factura_id") or "")
        if fid:
            items_por_factura.setdefault(fid, []).append({
                "cod_item": it.get("cod_item"),
                "item": it.get("item"),
                "ctd": it.get("ctd"),
                "precio_uni": it.get("precio_uni"),
                "porc_desc": it.get("porc_desc"),
                "porc_iva": it.get("porc_iva"),
            })

    facturas = []
    for r in resp.data:
        fid = str(r.get("factura_id") or "")
        facturas.append({
            "id": fid,
            "tipo_comp": r.get("tipo_comp"),
            "letra_comp": r.get("letra_comp"),
            "nro_comp": r.get("nro_comp"),
            "nro_pto_vta": r.get("nro_pto_vta"),
            "fecha_comp": r.get("fecha_comp"),
            "apellido_razon_soc": r.get("apellido_razon_soc"),
            "nombre": r.get("nombre"),
            "cuit": r.get("cuit"),
            "nro_pedido": r.get("nro_pedido"),
            "monto_exento": r.get("monto_exento"),
            "monto_gravado": r.get("monto_gravado"),
            "monto_iva": r.get("monto_iva"),
            "monto_desc": r.get("monto_desc"),
            "total": r.get("total"),
            "anulada": r.get("anulada"),
            "con_cobro": bool(r.get("con_cobro", False)),
            "nro_cae_cai": r.get("nro_cae_cai"),
            "url_factura": r.get("url_factura"),
            "detalles": items_por_factura.get(fid, []),
        })
    return facturas


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

@st.cache_data(ttl=600)
def cargar_compras():
    """DataFrame plano por ítem. Incluye comprobante_id y total_comprobante para el balance."""
    client = get_client()
    cols = (
        "comprobante_id, cod_item, item, ctd, precio_uni, porc_desc, porc_iva, "
        "comprobantes_compra(nro_comprobante, fecha, id_proveedor, proveedor, condicion_pago, total)"
    )
    rows = []
    offset = 0
    batch = 1000
    while True:
        resp = client.table("items_compra").select(cols).range(offset, offset + batch - 1).execute()
        if not resp.data:
            break
        rows.extend(resp.data)
        if len(resp.data) < batch:
            break
        offset += batch
    if not rows:
        return pd.DataFrame()
    prods = _productos_lookup()
    records = []
    for it in rows:
        cab = it.get("comprobantes_compra") or {}
        cod = str(it.get("cod_item") or "")
        records.append({
            "fecha": str(cab.get("fecha") or ""),
            "proveedor_id": str(cab.get("id_proveedor") or ""),
            "proveedor_nombre": str(cab.get("proveedor") or ""),
            "codigo_producto": cod,
            "producto_nombre": str(it.get("item") or "") or prods.get(cod, ""),
            "cantidad": _to_float(it.get("ctd")),
            "precio": _to_float(it.get("precio_uni")),
            "condicion_pago": str(cab.get("condicion_pago") or ""),
            "comprobante": str(cab.get("nro_comprobante") or ""),
            "comprobante_id": it.get("comprobante_id"),
            "total_comprobante": _to_float(cab.get("total")),
        })
    return pd.DataFrame(records)


@st.cache_data(ttl=600)
def cargar_comprobantes_compra():
    """Lista de comprobantes con su total DUX — para sumar en el balance sin pasar por ítems."""
    client = get_client()
    resp = client.table("comprobantes_compra").select(
        "id, nro_comprobante, fecha, proveedor, condicion_pago, total, estado, pago_pendiente"
    ).limit(10000).execute()
    return resp.data or []


def fechas_compras():
    df = cargar_compras()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


def guardar_compras_sync(compras):
    """Guarda compras sincronizadas desde DUX. Recibe lista de comprobantes raw de la API."""
    if not compras:
        return
    client = get_client()

    comp_rows = []
    items_por_comp = {}

    for c in compras:
        cid = c.get("id_compra") or c.get("id")
        if not cid:
            continue

        prov_obj = c.get("proveedor") or {}
        if isinstance(prov_obj, dict):
            proveedor = prov_obj.get("razon_social") or ""
            id_proveedor = prov_obj.get("id_proveedor")
        else:
            proveedor = str(prov_obj)
            id_proveedor = None

        montos = c.get("montos") or {}
        if not isinstance(montos, dict):
            montos = {}

        comp_rows.append({
            "id": int(cid),
            "id_empresa": c.get("id_empresa"),
            "id_sucursal": c.get("id_sucursal"),
            "id_proveedor": id_proveedor,
            "cuit": str(c.get("cuit") or ""),
            "proveedor": str(proveedor),
            "nro_comprobante": str(c.get("nro_comprobante") or ""),
            "tipo_comprobante": str(c.get("tipo_comprobante") or ""),
            "condicion_pago": str(c.get("condicion_pago") or ""),
            "estado": str(c.get("estado") or "EMITIDA"),
            "fecha": str(c.get("fecha") or ""),
            "fecha_vencimiento": str(c.get("fecha_vencimiento") or ""),
            "pago_pendiente": bool(c.get("pago_pendiente") or _to_float(montos.get("monto_pendiente")) > 0),
            "forma_pago": str(c.get("forma_pago") or ""),
            "provincia": str(c.get("provincia") or ""),
            "estado_recepcion": str(c.get("estado_recepcion") or ""),
            "fecha_imputacion_contable": str(c.get("fecha_imputacion_contable") or ""),
            "monto_exento": _to_float(montos.get("monto_exento")),
            "monto_gravado": _to_float(montos.get("monto_gravado")),
            "monto_iva": _to_float(montos.get("monto_iva")),
            "monto_desc": _to_float(montos.get("monto_descuento")),
            "monto_pendiente": _to_float(montos.get("monto_pendiente")),
            "monto_percepciones": _to_float(montos.get("monto_percepciones")),
            "total": _to_float(montos.get("total")),
            "json": c,
        })

        items_por_comp[int(cid)] = [
            {
                "comprobante_id": int(cid),
                "cod_item": str(it.get("cod_item") or ""),
                "item": str(it.get("item") or it.get("descripcion") or ""),
                "ctd": _to_float(it.get("ctd_recepcionada") or it.get("ctd") or it.get("cantidad")),
                "precio_uni": _to_float(it.get("precio_uni")),
                "porc_desc": _to_float(it.get("porc_desc")),
                "porc_iva": _to_float(it.get("porc_iva")),
                "json": it,
            }
            for it in (c.get("items", []) or [])
        ]

    if not comp_rows:
        return

    client.table("comprobantes_compra").upsert(comp_rows, on_conflict="id").execute()

    _cids = list(items_por_comp.keys())
    client.table("items_compra").delete().in_("comprobante_id", _cids).execute()
    _all_citems = [it for its in items_por_comp.values() for it in its]
    if _all_citems:
        client.table("items_compra").insert(_all_citems).execute()


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


# ---------------- GASTOS ----------------

@st.cache_data(ttl=600)
def cargar_gastos():
    client = get_client()
    resp_gastos = client.table("gastos").select("*").limit(10000).execute()
    if not resp_gastos.data:
        return []

    all_items_gasto = _fetch_all(client, "gastos_items_con_nombre")
    prods = _productos_lookup()
    items_por_gasto = {}
    for it in all_items_gasto:
        gid = it.get("gasto_id")
        if gid is not None:
            cod = str(it.get("cod_item") or "")
            items_por_gasto.setdefault(gid, []).append({
                "cod_item": it.get("cod_item"),
                "item": it.get("nombre_catalogo") or it.get("item") or prods.get(cod, ""),
                "ctd": it.get("ctd"),
                "precio_uni": it.get("precio_uni"),
                "porc_desc": it.get("porc_desc"),
                "porc_iva": it.get("porc_iva"),
                "comentarios": it.get("comentarios"),
            })

    gastos = []
    for r in resp_gastos.data:
        gid = r.get("id")
        gastos.append({
            **r,
            "detalles": items_por_gasto.get(gid, []),
        })
    return gastos


def guardar_gastos(gastos):
    client = get_client()
    gasto_rows = []
    items_por_gasto = {}

    for g in gastos:
        gid = g.get("id_compra") or g.get("id")
        if not gid:
            continue

        prov_obj = g.get("proveedor") or {}
        if isinstance(prov_obj, dict):
            proveedor = prov_obj.get("razon_social") or ""
            id_proveedor = prov_obj.get("id_proveedor")
        else:
            proveedor = str(prov_obj)
            id_proveedor = None

        montos = g.get("montos") or {}
        if not isinstance(montos, dict):
            montos = {}

        monto_pendiente_val = _to_float(montos.get("monto_pendiente"))
        pago_pendiente = monto_pendiente_val > 0

        rubro_obj = g.get("rubro") or {}
        sub_rubro_obj = g.get("sub_rubro") or {}

        gasto_rows.append({
            "id": int(gid),
            "id_empresa": g.get("id_empresa"),
            "id_sucursal": g.get("id_sucursal"),
            "id_proveedor": id_proveedor,
            "cuit": str(g.get("cuit") or ""),
            "proveedor": str(proveedor),
            "nro_comprobante": str(g.get("nro_comprobante") or ""),
            "tipo_comprobante": str(g.get("tipo_comprobante") or ""),
            "condicion_pago": str(g.get("condicion_pago") or ""),
            "gasto": str(g.get("gasto") or ""),
            "estado": str(g.get("estado") or "EMITIDA"),
            "fecha": str(g.get("fecha") or ""),
            "fecha_vencimiento": str(g.get("fecha_vencimiento") or ""),
            "observaciones": str(g.get("observaciones") or g.get("comentarios") or ""),
            "pago_pendiente": pago_pendiente,
            "monto_pendiente": monto_pendiente_val,
            "monto_exento": _to_float(montos.get("monto_exento")),
            "monto_gravado": _to_float(montos.get("monto_gravado")),
            "monto_iva": _to_float(montos.get("monto_iva")),
            "monto_desc": _to_float(montos.get("monto_descuento")),
            "total": _to_float(montos.get("total")),
            "id_rubro": rubro_obj.get("id_rubro") if isinstance(rubro_obj, dict) else None,
            "rubro_nombre": str(rubro_obj.get("rubro") or "") if isinstance(rubro_obj, dict) else "",
            "id_sub_rubro": sub_rubro_obj.get("id_sub_rubro") if isinstance(sub_rubro_obj, dict) else None,
            "sub_rubro_nombre": str(sub_rubro_obj.get("sub_rubro") or "") if isinstance(sub_rubro_obj, dict) else "",
        })

        detalles = []
        for f in ["items", "detalles", "productos", "lineas", "renglones", "detalle"]:
            v = g.get(f)
            if isinstance(v, list):
                detalles = v
                break

        items_por_gasto[int(gid)] = [
            {
                "gasto_id": int(gid),
                "cod_item": str(it.get("cod_item") or ""),
                "item": str(it.get("cod_item") or it.get("item") or it.get("descripcion") or ""),
                "ctd": _to_float(it.get("ctd") or it.get("cantidad")),
                "precio_uni": _to_float(it.get("precio_uni")),
                "porc_desc": _to_float(it.get("porc_desc")),
                "porc_iva": _to_float(it.get("porc_iva")),
                "comentarios": str(it.get("observaciones") or it.get("comentarios") or ""),
                "monto_total": _to_float(it.get("monto_total") or it.get("importe") or it.get("total")),
            }
            for it in detalles
        ]

    if not gasto_rows:
        return

    client.table("gastos").upsert(gasto_rows, on_conflict="id").execute()

    _gids = list(items_por_gasto.keys())
    client.table("gastos_items").delete().in_("gasto_id", _gids).execute()
    _all_gitems = [it for its in items_por_gasto.values() for it in its]
    if _all_gitems:
        client.table("gastos_items").insert(_all_gitems).execute()


@st.cache_data(ttl=600)
def cargar_pagos_proveedores():
    client = get_client()
    pago_rows = _fetch_all_rows(client, "pagos_proveedores")
    if not pago_rows:
        return []
    lin_rows = _fetch_all_rows(client, "pagos_proveedores_lineas")
    imp_rows = _fetch_all_rows(client, "pagos_proveedores_imputaciones")
    lin_by_id: dict = {}
    for row in lin_rows:
        lin_by_id.setdefault(int(row["pago_id"]), []).append(row)
    imp_by_id: dict = {}
    for row in imp_rows:
        imp_by_id.setdefault(int(row["pago_id"]), []).append(row)
    pagos = []
    for r in pago_rows:
        pid = int(r["id"])
        pagos.append({
            **r,
            "lineas_pago":  lin_by_id.get(pid, []),
            "imputaciones": imp_by_id.get(pid, []),
        })
    return pagos


def guardar_pagos_proveedores(pagos):
    client = get_client()
    pago_rows = []
    lineas_por_pago = {}
    imput_por_pago = {}

    for p in pagos:
        pid = p.get("id_pago")
        if not pid:
            continue

        prov_obj = p.get("proveedor") or {}
        proveedor    = prov_obj.get("razon_social", "") if isinstance(prov_obj, dict) else str(prov_obj)
        id_proveedor = prov_obj.get("id_proveedor")    if isinstance(prov_obj, dict) else None

        caja_obj = p.get("caja") or {}
        id_caja       = caja_obj.get("id_caja")        if isinstance(caja_obj, dict) else None
        caja_desc     = caja_obj.get("descripcion", "") if isinstance(caja_obj, dict) else ""

        personal_obj = p.get("personal") or {}
        id_personal   = personal_obj.get("id_personal") if isinstance(personal_obj, dict) else None
        personal_nom  = personal_obj.get("nombre", "")  if isinstance(personal_obj, dict) else ""

        pago_rows.append({
            "id":              int(pid),
            "id_empresa":      p.get("id_empresa"),
            "id_sucursal":     p.get("id_sucursal"),
            "id_proveedor":    id_proveedor,
            "proveedor":       str(proveedor),
            "fecha":           str(p.get("fecha") or ""),
            "nro_comprobante": str(p.get("nro_comprobante") or ""),
            "forma_pago":      str(p.get("forma_pago") or ""),
            "monto":           _to_float(p.get("monto")),
            "moneda":          str(p.get("moneda") or ""),
            "monto_aplicado":  _to_float(p.get("monto_aplicado")),
            "retencion":       _to_float(p.get("retencion")),
            "concepto":        str(p.get("concepto") or ""),
            "observaciones":   str(p.get("observaciones") or ""),
            "id_caja":         id_caja,
            "caja":            str(caja_desc),
            "id_personal":     id_personal,
            "personal":        str(personal_nom),
        })

        lineas_por_pago[int(pid)] = [
            {
                "pago_id":     int(pid),
                "tipo_valor":  str(l.get("tipo_valor") or ""),
                "descripcion": str(l.get("descripcion") or ""),
                "referencia":  str(l.get("referencia") or ""),
                "monto":       _to_float(l.get("monto")),
            }
            for l in (p.get("lineas_pago") or [])
        ]

        imput_por_pago[int(pid)] = [
            {
                "pago_id":                       int(pid),
                "id_compra":                     i.get("id_compra"),
                "id_gasto":                      i.get("id_gasto"),
                "id_comp_compra":                i.get("id_comp_compra"),
                "id_comp_gasto":                 i.get("id_comp_gasto"),
                "id_nota_credito_debito_compra":  i.get("id_nota_credito_debito_compra"),
                "tipo_comprobante":              str(i.get("tipo_comprobante") or ""),
                "nro_comprobante":               str(i.get("nro_comprobante") or ""),
                "monto_imputado":                _to_float(i.get("monto_imputado")),
            }
            for i in (p.get("imputaciones") or [])
        ]

    if not pago_rows:
        return

    client.table("pagos_proveedores").upsert(pago_rows, on_conflict="id").execute()

    _pids = list(lineas_por_pago.keys())
    client.table("pagos_proveedores_lineas").delete().in_("pago_id", _pids).execute()
    _all_lineas = [l for ls in lineas_por_pago.values() for l in ls]
    if _all_lineas:
        client.table("pagos_proveedores_lineas").insert(_all_lineas).execute()

    client.table("pagos_proveedores_imputaciones").delete().in_("pago_id", _pids).execute()
    _all_imput_p = [i for its in imput_por_pago.values() for i in its]
    if _all_imput_p:
        client.table("pagos_proveedores_imputaciones").insert(_all_imput_p).execute()


def _fetch_all_rows(client, table):
    """Trae todas las filas de una tabla paginando de a 1000 para evitar límites del API."""
    all_rows, offset, page = [], 0, 1000
    while True:
        resp = client.table(table).select("*").range(offset, offset + page - 1).execute()
        if not resp.data:
            break
        all_rows.extend(resp.data)
        if len(resp.data) < page:
            break
        offset += page
    return all_rows


@st.cache_data(ttl=600)
def cargar_cobros():
    client = get_client()
    cobro_rows = _fetch_all_rows(client, "cobros")
    if not cobro_rows:
        return []
    cob_rows = _fetch_all_rows(client, "cobros_cobranza")
    imp_rows = _fetch_all_rows(client, "cobros_imputaciones")
    cob_by_id: dict = {}
    for row in cob_rows:
        cob_by_id.setdefault(int(row["cobro_id"]), []).append(row)
    imp_by_id: dict = {}
    for row in imp_rows:
        imp_by_id.setdefault(int(row["cobro_id"]), []).append(row)
    cobros = []
    for r in cobro_rows:
        cid = int(r["id"])
        cobros.append({
            **r,
            "cobranza":     cob_by_id.get(cid, []),
            "imputaciones": imp_by_id.get(cid, []),
        })
    return cobros


def guardar_cobros(cobros):
    client = get_client()
    cobro_rows = []
    cobranza_por_cobro = {}
    imput_por_cobro = {}

    for c in cobros:
        cid = c.get("id_cobro")
        if not cid:
            continue

        cli_obj = c.get("cliente") or {}
        id_cliente            = cli_obj.get("id_cliente")          if isinstance(cli_obj, dict) else None
        apellido_razon_social = cli_obj.get("apellido_razon_social", "") if isinstance(cli_obj, dict) else str(cli_obj)
        nombre_cliente        = cli_obj.get("nombre", "")          if isinstance(cli_obj, dict) else ""
        tipo_doc              = cli_obj.get("tipo_doc", "")         if isinstance(cli_obj, dict) else ""
        nro_doc               = cli_obj.get("nro_doc", "")          if isinstance(cli_obj, dict) else ""

        per_obj = c.get("personal") or {}
        id_personal  = per_obj.get("id_personal") if isinstance(per_obj, dict) else None
        personal_nom = per_obj.get("nombre", "")  if isinstance(per_obj, dict) else ""

        cobro_rows.append({
            "id":                    int(cid),
            "id_empresa":            c.get("id_empresa"),
            "id_sucursal":           c.get("id_sucursal"),
            "fecha":                 str(c.get("fecha") or ""),
            "nro_comprobante":       str(c.get("nro_comprobante") or ""),
            "tipo_comprobante":      str(c.get("tipo_comprobante") or ""),
            "monto":                 _to_float(c.get("monto")),
            "moneda":                str(c.get("moneda") or ""),
            "observaciones":         str(c.get("observaciones") or ""),
            "id_cliente":            id_cliente,
            "cliente":               str(apellido_razon_social),
            "nombre_cliente":        str(nombre_cliente),
            "tipo_doc":              str(tipo_doc),
            "nro_doc":               str(nro_doc),
            "id_personal":           id_personal,
            "personal":              str(personal_nom),
        })

        cobranza_por_cobro[int(cid)] = [
            {
                "cobro_id":        int(cid),
                "tipo_valor":      str(l.get("tipo_valor") or ""),
                "descripcion":     str(l.get("descripcion") or ""),
                "referencia":      str(l.get("referencia") or ""),
                "monto":           _to_float(l.get("monto")),
                "id_tarjeta":      l.get("id_tarjeta"),
                "id_plan_tarjeta": l.get("id_plan_tarjeta"),
                "id_terminal":     l.get("id_terminal"),
                "nro_cupon":       str(l.get("nro_cupon") or ""),
                "nro_lote":        str(l.get("nro_lote") or ""),
            }
            for l in (c.get("cobranza") or [])
        ]

        imput_por_cobro[int(cid)] = [
            {
                "cobro_id":                      int(cid),
                "id_comp_venta":                 i.get("id_comp_venta"),
                "id_nota_credito_debito_venta":  i.get("id_nota_credito_debito_venta"),
                "tipo_comp":                     str(i.get("tipo_comp") or ""),
                "nro_comprobante":               str(i.get("nro_comprobante") or ""),
                "monto_imputado":                _to_float(i.get("monto_imputado")),
            }
            for i in (c.get("imputaciones") or [])
        ]

    if not cobro_rows:
        return

    client.table("cobros").upsert(cobro_rows, on_conflict="id").execute()

    # Solo actualizar cobranza para cobros que traen líneas — no borrar los que vienen vacíos
    _cids_con_cobranza = [cid for cid, lines in cobranza_por_cobro.items() if lines]
    if _cids_con_cobranza:
        client.table("cobros_cobranza").delete().in_("cobro_id", _cids_con_cobranza).execute()
        _all_cobranza = [l for cid in _cids_con_cobranza for l in cobranza_por_cobro[cid]]
        client.table("cobros_cobranza").insert(_all_cobranza).execute()

    _cids_cobro = list(cobranza_por_cobro.keys())
    client.table("cobros_imputaciones").delete().in_("cobro_id", _cids_cobro).execute()
    _all_imput_c = [i for its in imput_por_cobro.values() for i in its]
    if _all_imput_c:
        client.table("cobros_imputaciones").insert(_all_imput_c).execute()


@st.cache_data(ttl=600)
def cargar_ids_gastos():
    client = get_client()
    resp = client.table("gastos").select("id, gasto, nro_comprobante, gastos_items(cod_item)").execute()
    result = {}
    for r in (resp.data or []):
        items = r.get("gastos_items") or []
        cod_items = ", ".join(
            str(i.get("cod_item") or "").strip()
            for i in items if i.get("cod_item") and str(i.get("cod_item")).strip() not in ("", "None")
        )
        label = cod_items or r.get("gasto") or r.get("nro_comprobante") or str(r["id"])
        result[r["id"]] = {"label": label, "nro_comprobante": r.get("nro_comprobante") or ""}
    return result


@st.cache_data(ttl=300)
def cargar_transferencias():
    client = get_client()
    resp = client.table("transferencias_cajas").select(
        "*, origen:origen_id(nombre), destino:destino_id(nombre)"
    ).order("fecha", desc=True).execute()
    return resp.data or []


def guardar_transferencia(fecha, origen_id, destino_id, monto, concepto=""):
    client = get_client()
    client.table("transferencias_cajas").insert({
        "fecha":      str(fecha),
        "origen_id":  origen_id,
        "destino_id": destino_id,
        "monto":      float(monto),
        "concepto":   concepto or "",
    }).execute()
    st.cache_data.clear()


def eliminar_transferencia(transfer_id):
    client = get_client()
    client.table("transferencias_cajas").delete().eq("id", transfer_id).execute()
    st.cache_data.clear()


def cargar_compras_desde_gastos(fecha):
    """Lee compras del día desde gastos sincronizados en Supabase.
    Retorna el mismo formato que cargar_compras_dux_v2 para compatibilidad
    con el stock teórico: {"cantidades": {cod_item: qty}, "compras": [list]}
    """
    gastos = cargar_gastos()
    fecha_str = str(fecha)

    cantidades = {}
    compras_raw = []

    for g in gastos:
        if str(g.get("fecha") or "") != fecha_str:
            continue

        detalles = g.get("detalles") or []
        items_list = []
        for it in detalles:
            cod = str(it.get("cod_item") or "").strip()
            ctd = float(it.get("ctd") or 0)
            if cod:
                cantidades[cod] = cantidades.get(cod, 0.0) + ctd
            items_list.append({
                "cod_item": cod,
                "ctd_recepcionada": ctd,
            })

        compras_raw.append({
            "nro_comprobante": g.get("nro_comprobante") or "—",
            "proveedor": {"razon_social": g.get("proveedor") or ""},
            "items": items_list,
        })

    return {"cantidades": cantidades, "compras": compras_raw}

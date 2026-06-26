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

# ---------------- PEDIDOS DUX ----------------

def cargar_pedidos_dux():
    client = get_client()
    resp_orders = client.table("pedidos_dux").select("*").execute()
    if not resp_orders.data:
        return []

    resp_items = client.table("pedidos_dux_items").select("*").execute()
    items_por_order = {}
    for it in (resp_items.data or []):
        oid = str(it.get("order_id") or "")
        if oid:
            items_por_order.setdefault(oid, []).append({
                "cod_item": it.get("cod_item"),
                "item": it.get("item"),
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

    for oid, items in items_por_order.items():
        client.table("pedidos_dux_items").delete().eq("order_id", oid).execute()
        if items:
            client.table("pedidos_dux_items").insert(items).execute()


def _to_float(v):
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


# ---------------- PEDIDOS WIX ----------------

def cargar_pedidos_wix():
    client = get_client()
    resp_orders = client.table("pedidos_wix").select("*").execute()
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

    for oid, items in items_por_order.items():
        client.table("pedidos_wix_items").delete().eq("order_id", oid).execute()
        if items:
            client.table("pedidos_wix_items").insert(items).execute()


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

    for fid, items in items_por_factura.items():
        client.table("facturas_items").delete().eq("factura_id", fid).execute()
        if items:
            client.table("facturas_items").insert(items).execute()


def cargar_facturas():
    client = get_client()
    resp = client.table("facturas").select("*").order("fecha_comp", desc=True).execute()
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

def cargar_compras():
    """Devuelve un DataFrame plano con la misma estructura que antes para compatibilidad con app.py."""
    client = get_client()
    resp = client.table("items_compra").select(
        "codigo_producto, producto_nombre, cantidad, precio, "
        "comprobantes_compra(nro_comprobante, fecha, proveedor_id, proveedor_nombre, condicion_pago)"
    ).execute()
    rows = resp.data or []
    if not rows:
        return pd.DataFrame()
    records = []
    for it in rows:
        cab = it.get("comprobantes_compra") or {}
        records.append({
            "fecha": str(cab.get("fecha") or ""),
            "proveedor_id": str(cab.get("proveedor_id") or ""),
            "proveedor_nombre": str(cab.get("proveedor_nombre") or ""),
            "codigo_producto": str(it.get("codigo_producto") or ""),
            "producto_nombre": str(it.get("producto_nombre") or ""),
            "cantidad": float(it.get("cantidad") or 0),
            "precio": float(it.get("precio") or 0),
            "condicion_pago": str(cab.get("condicion_pago") or ""),
            "comprobante": str(cab.get("nro_comprobante") or ""),
        })
    return pd.DataFrame(records)


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
    """Guarda compras manuales para una fecha, agrupando por proveedor en comprobantes."""
    client = get_client()
    fecha_str = str(fecha)

    # Traer nro_comprobante existentes para esta fecha (para reusar si ya existe)
    resp = client.table("comprobantes_compra").select("id, proveedor_id, nro_comprobante").eq("fecha", fecha_str).execute()
    prov_a_id = {}
    for r in (resp.data or []):
        pid = str(r.get("proveedor_id") or "")
        if pid and pid not in prov_a_id:
            prov_a_id[pid] = r["id"]

    df_fecha = df_fecha.copy()
    df_fecha["fecha"] = fecha_str

    # Agrupar por proveedor_id
    por_proveedor = {}
    for _, row in df_fecha.iterrows():
        pid = str(row.get("proveedor_id") or "")
        por_proveedor.setdefault(pid, []).append(row)

    for pid, filas in por_proveedor.items():
        first = filas[0]
        if pid in prov_a_id:
            comp_id = prov_a_id[pid]
            # Eliminar items anteriores (el CASCADE no aplica aquí, borramos manualmente)
            client.table("items_compra").delete().eq("comprobante_id", comp_id).execute()
        else:
            nro = _proximo_comprobante_id()
            cab = {
                "nro_comprobante": nro,
                "fecha": fecha_str,
                "proveedor_id": pid,
                "proveedor_nombre": str(first.get("proveedor_nombre") or ""),
                "condicion_pago": str(first.get("condicion_pago") or ""),
            }
            ins = client.table("comprobantes_compra").insert(cab).execute()
            comp_id = ins.data[0]["id"]
            prov_a_id[pid] = comp_id

        items = [
            {
                "comprobante_id": comp_id,
                "codigo_producto": str(r.get("codigo_producto") or ""),
                "producto_nombre": str(r.get("producto_nombre") or ""),
                "cantidad": float(r.get("cantidad") or 0),
                "precio": float(r.get("precio") or 0),
            }
            for r in filas
        ]
        client.table("items_compra").insert(items).execute()


def fechas_compras():
    df = cargar_compras()
    if df.empty:
        return []
    return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)


def guardar_compras_sync(rows):
    """Guarda compras sincronizadas desde DUX, agrupando en comprobantes + items."""
    if not rows:
        return
    client = get_client()

    # Agrupar por (nro_comprobante, fecha, proveedor_id)
    por_comp: dict = {}
    for r in rows:
        key = (str(r.get("comprobante") or ""), str(r.get("fecha") or ""), str(r.get("proveedor_id") or ""))
        por_comp.setdefault(key, []).append(r)

    # Eliminar comprobantes existentes para las fechas afectadas y re-insertar
    fechas_afectadas = {k[1] for k in por_comp}
    for fecha in fechas_afectadas:
        resp = client.table("comprobantes_compra").select("id").eq("fecha", fecha).execute()
        ids = [r["id"] for r in (resp.data or [])]
        if ids:
            client.table("items_compra").delete().in_("comprobante_id", ids).execute()
            client.table("comprobantes_compra").delete().eq("fecha", fecha).execute()

    for (nro_comp, fecha, prov_id), filas in por_comp.items():
        first = filas[0]
        cab = {
            "nro_comprobante": nro_comp,
            "fecha": fecha,
            "proveedor_id": prov_id,
            "proveedor_nombre": str(first.get("proveedor_nombre") or ""),
            "condicion_pago": str(first.get("condicion_pago") or ""),
        }
        ins = client.table("comprobantes_compra").insert(cab).execute()
        comp_id = ins.data[0]["id"]
        items = [
            {
                "comprobante_id": comp_id,
                "codigo_producto": str(r.get("codigo_producto") or ""),
                "producto_nombre": str(r.get("producto_nombre") or ""),
                "cantidad": float(r.get("cantidad") or 0),
                "precio": float(r.get("precio") or 0),
            }
            for r in filas
        ]
        client.table("items_compra").insert(items).execute()


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

def cargar_gastos():
    client = get_client()
    resp_gastos = client.table("gastos").select("*").execute()
    if not resp_gastos.data:
        return []

    resp_items = client.table("gastos_items").select("*").execute()
    items_por_gasto = {}
    for it in (resp_items.data or []):
        gid = it.get("gasto_id")
        if gid is not None:
            items_por_gasto.setdefault(gid, []).append({
                "cod_item": it.get("cod_item"),
                "item": it.get("item"),
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

        pago_pendiente = _to_float(montos.get("monto_pendiente")) > 0

        gasto_rows.append({
            "id": int(gid),
            "id_empresa": g.get("id_empresa"),
            "id_sucursal": g.get("id_sucursal"),
            "id_proveedor": id_proveedor,
            "cuit": str(g.get("cuit") or ""),
            "proveedor": str(proveedor),
            "nro_comprobante": str(g.get("nro_comprobante") or ""),
            "tipo_comprobante": str(g.get("tipo_comprobante") or g.get("condicion_pago") or ""),
            "gasto": str(g.get("gasto") or ""),
            "estado": str(g.get("estado") or "EMITIDA"),
            "fecha": str(g.get("fecha") or ""),
            "fecha_vencimiento": str(g.get("fecha_vencimiento") or ""),
            "pago_pendiente": pago_pendiente,
            "monto_exento": _to_float(montos.get("monto_exento")),
            "monto_gravado": _to_float(montos.get("monto_gravado")),
            "monto_iva": _to_float(montos.get("monto_iva")),
            "monto_desc": _to_float(montos.get("monto_descuento")),
            "total": _to_float(montos.get("total")),
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
                "item": str(it.get("item") or it.get("descripcion") or ""),
                "ctd": _to_float(it.get("ctd") or it.get("cantidad")),
                "precio_uni": _to_float(it.get("precio_uni")),
                "porc_desc": _to_float(it.get("porc_desc")),
                "porc_iva": _to_float(it.get("porc_iva")),
                "comentarios": str(it.get("observaciones") or it.get("comentarios") or ""),
            }
            for it in detalles
        ]

    if not gasto_rows:
        return

    client.table("gastos").upsert(gasto_rows, on_conflict="id").execute()

    for gid, items in items_por_gasto.items():
        client.table("gastos_items").delete().eq("gasto_id", gid).execute()
        if items:
            client.table("gastos_items").insert(items).execute()


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

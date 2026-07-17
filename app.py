import hashlib
import io
import logging
import re
import time
import warnings
from datetime import date, timedelta, datetime, timezone

warnings.filterwarnings("ignore", message=".*use_container_width.*")
warnings.filterwarnings("ignore", message=".*label.*got an empty value.*")

# Silenciar deprecation warnings de Streamlit que inundan los logs
logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)
logging.getLogger("streamlit.elements.widgets.radio").setLevel(logging.ERROR)

import requests
import streamlit as st
import pandas as pd

import supabase_db as db

_AR = timezone(timedelta(hours=-3))

_DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

def _fmt_ts(ts):
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(str(ts)).astimezone(_AR)
        return f"{_DIAS[dt.weekday()]} {dt.strftime('%d/%m/%Y %H:%M')}"
    except Exception:
        return str(ts)

def _fmt_fecha(s):
    """Formatea string de fecha ISO a 'lun 06/07/2026'. Devuelve '—' si vacío."""
    if not s or str(s).strip() in ("", "None", "nan", "—"):
        return "—"
    try:
        d = pd.to_datetime(str(s)).date()
        return f"{_DIAS[d.weekday()]} {d.strftime('%d/%m/%Y')}"
    except Exception:
        return str(s)[:10] if s else "—"


DUX_RATE_LIMIT_SECONDS = 5.5


def _parse_num_es(v):
    """Parsea un numero aceptando coma o punto como decimal.
    Acepta '1,5' (AR), '1.5' (EN), '1.500,75' (AR con miles), 1500 (numerico)."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    # Si tiene tanto coma como punto, asumimos formato AR: punto=miles, coma=decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fmt_num_es(v):
    """Float -> string en formato AR (coma decimal, sin ceros sobrantes).
    Para mostrar en TextColumn editable."""
    try:
        n = float(v)
    except (ValueError, TypeError):
        return "0"
    if n == 0:
        return "0"
    return f"{n:.3f}".rstrip("0").rstrip(".").replace(".", ",")


_UNIDAD_PRIO = {
    "CAJA": 1, "BOLSA": 1, "RIESTRA": 1,
    "UNIDAD": 2, "CABEZA": 2, "ATADO": 2, "BANDEJA": 2,
    "CUBETA": 2, "MAPLE": 2, "PLANTA": 2,
    "KG": 3, "LITRO": 3, "KILO": 3,
}


def _prio_unidad(s):
    u = str(s).upper()
    for kw, p in _UNIDAD_PRIO.items():
        if kw in u:
            return p
    return 99



def cargar_compras_dux_v2(fecha_desde, fecha_hasta):
    """Lee las compras de DUX en un rango.
    Devuelve dict {
      'cantidades': {cod_item: cantidad_recepcionada_total},
      'compras': [lista de compras raw con sus items, proveedor, etc.]
    }
    Si la API falla, devuelve None (para distinguir de '0 compras')."""
    dux_cfg = st.secrets.get("dux", {})
    token = dux_cfg.get("token", "")
    base_url = dux_cfg.get(
        "base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services"
    )
    id_empresa = int(dux_cfg.get("id_empresa", 4245))

    if not token:
        return None

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
    }
    url = f"{base_url}/v2/compras"

    cantidades = {}
    compras_raw = []
    page_size = 50
    max_pages = 50

    for estado_filter in [None, "ANULADA"]:
        offset = 0
        for _ in range(max_pages):
            params = {
                "id_empresa": id_empresa,
                "fecha_desde": pd.to_datetime(fecha_desde).strftime("%Y-%m-%d"),
                "fecha_hasta": pd.to_datetime(fecha_hasta).strftime("%Y-%m-%d"),
                "incluir_detalle": "true",
                "limit": page_size,
                "offset": offset,
            }
            if estado_filter:
                params["estado"] = estado_filter
            try:
                r = requests.get(url, params=params, headers=headers, timeout=20)
                if r.status_code != 200:
                    break
                d = r.json()
            except Exception:
                break

            datos = d.get("datos", []) or []
            if not datos:
                break

            for compra in datos:
                # La API no devuelve el campo estado en el response,
                # lo inyectamos según el filtro usado
                if estado_filter:
                    compra["estado"] = estado_filter
                compras_raw.append(compra)
                for item in (compra.get("items", []) or []):
                    cod = str(item.get("cod_item", "") or "").strip()
                    if not cod:
                        continue
                    try:
                        ctd = float(item.get("ctd_recepcionada", 0) or 0)
                    except (ValueError, TypeError):
                        continue
                    cantidades[cod] = cantidades.get(cod, 0.0) + ctd

            offset += len(datos)
            time.sleep(2)

    return {"cantidades": cantidades, "compras": compras_raw}


# Dias de la semana (en castellano, sin acentos). Definicion unica reusada
# en Estimado y Total a comprar.
DIAS_SEMANA = db.DIAS_SEMANA
DIAS_DISPLAY = {
    "lunes": "Lunes", "martes": "Martes", "miercoles": "Miércoles",
    "jueves": "Jueves", "viernes": "Viernes", "sabado": "Sábado",
    "domingo": "Domingo",
}


def msg_error_http(fuente, status_code, body=""):
    """Devuelve un mensaje en castellano para mostrar a quien usa la app."""
    if status_code in (401, 403):
        return f"🔑 Las credenciales de {fuente} están vencidas o son inválidas. Avisale a Tomás."
    if status_code == 429:
        return f"⏳ {fuente} nos está limitando. Esperá 1 minuto y volvé a intentar."
    if status_code in (500, 502, 503, 504):
        return f"🔧 {fuente} está caído o lento. Probá en un rato."
    if status_code == 404:
        return f"❓ {fuente} no encontró lo que se pidió. Avisale a Tomás."
    detalle = (body or "")[:200].strip()
    return f"❌ Error de {fuente} (código {status_code}). {detalle}"


def msg_error_red(fuente, exc):
    nombre = type(exc).__name__
    if "Timeout" in nombre:
        return f"🌐 {fuente} no respondió a tiempo. Probá de nuevo en un rato."
    if "Connection" in nombre or "DNS" in nombre:
        return "🌐 No hay conexión a internet (o el servidor está caído). Probá de nuevo."
    return f"❌ Error de red con {fuente}: {exc}"


def msg_error_sheets(accion, exc):
    """accion = 'leer'/'guardar' + descripcion corta. Ej: 'leer pedidos DUX'."""
    txt = str(exc)
    if "429" in txt or "quota" in txt.lower() or "rate" in txt.lower():
        return "⏳ Google Sheets nos está limitando. Esperá 1 minuto y dale 🔄 Actualizar."
    if "403" in txt or "permission" in txt.lower():
        return "🔑 La planilla de Google no nos da permiso. Avisale a Tomás."
    if "404" in txt or "notfound" in txt.lower().replace(" ", ""):
        return "❓ No se encuentra la planilla. Avisale a Tomás."
    return f"❌ No se pudo {accion} en Google Sheets. Avisale a Tomás. ({txt[:150]})"




st.set_page_config(page_title="Frutiverdu - Compuestos", layout="wide")



EXCEPCIONES = {
    ("061", "062"),
    ("0256", "0205"),
    ("095", "094"),
    ("096", "097"),
}

st.title("Frutiverdu")

PRESENCIA_WINDOW = 600  # 10 min — considerado "activo" si dio señal en este lapso
HEARTBEAT_INTERVAL = 300  # 5 min — refrescamos nuestra presencia cada este lapso

if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None

if st.session_state["auth_user"] is None:
    st.title("🔒 Frutiverdu")
    with st.form("login_form"):
        _lu = st.text_input("Usuario")
        _lp = st.text_input("Contraseña", type="password")
        _lb = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
    if _lb:
        _users_cfg = st.secrets.get("users", {})
        _udata = _users_cfg.get(_lu.lower(), {})
        _stored = _udata.get("password_hash", "")
        _salt = st.secrets.get("auth", {}).get("salt", "frutiverdu")
        _input_hash = hashlib.sha256(f"{_salt}:{_lu.lower()}:{_lp}".encode()).hexdigest()
        if _stored and _input_hash == _stored:
            st.session_state["auth_user"] = _lu.lower()
            st.session_state["usuario_app"] = _lu.lower()
            st.session_state["_ultimo_heartbeat"] = 0
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
    st.stop()

if "usuario_app" not in st.session_state:
    st.session_state["auth_user"] = None
    st.rerun()
_usuario_actual = st.session_state["usuario_app"]
_ahora = int(time.time())

# Heartbeat: si pasaron >5 min desde el ultimo, refrescamos presencia
if _ahora - st.session_state.get("_ultimo_heartbeat", 0) > HEARTBEAT_INTERVAL:
    try:
        db.guardar_config({f"presencia_{_usuario_actual}": str(_ahora)})
        st.session_state["_ultimo_heartbeat"] = _ahora
    except Exception:
        pass

# Detectar otros usuarios activos en los ultimos 10 min.
# IMPORTANTE: usar st.empty() en vez de st.warning() condicional para que el
# árbol de widgets antes de st.tabs() sea siempre estable (mismo nro de slots).
_warning_otros_ph = st.empty()
try:
    _cfg_now = db.cargar_config()
    _otros_activos = []
    for _k_cfg, _v_cfg in _cfg_now.items():
        if not _k_cfg.startswith("presencia_"):
            continue
        _nombre = _k_cfg.replace("presencia_", "")
        if _nombre == _usuario_actual:
            continue
        try:
            _ts_otro = int(_v_cfg)
        except (ValueError, TypeError):
            continue
        if _ahora - _ts_otro < PRESENCIA_WINDOW:
            _otros_activos.append(_nombre)
    if _otros_activos:
        _warning_otros_ph.warning(
            f"⚠️ **{', '.join(_otros_activos)}** también está/n usando la app ahora. "
            "Tené cuidado con los cambios para no pisarse."
        )
except Exception:
    pass

_col_sesh, _col_logout = st.columns([8, 1])
with _col_sesh:
    st.caption(f"👤 Sesión: **{_usuario_actual}**")
with _col_logout:
    if st.button("Cerrar sesión", key="logout_top", use_container_width=True):
        st.session_state["auth_user"] = None
        st.session_state.pop("usuario_app", None)
        st.rerun()


def _slim_wix_order(o):
    """Devuelve una version reducida del pedido Wix con SOLO los campos que
    usa la app. Wix manda mucho metadata extra que puede exceder los 50k
    caracteres por celda de Google Sheets."""
    if not isinstance(o, dict):
        return o
    bi = (o.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
    si_logistics = ((o.get("shippingInfo", {}) or {}).get("logistics", {}) or {})
    si_dest = si_logistics.get("shippingDestination", {}) or {}
    bu = (o.get("buyerInfo", {}) or {}).get("contactDetails", {}) or {}
    return {
        "id": o.get("id"),
        "number": o.get("number"),
        "status": o.get("status"),
        "createdDate": o.get("createdDate"),
        "lineItems": [
            {
                "quantity": (li or {}).get("quantity"),
                "catalogReference": {
                    "catalogItemId": ((li or {}).get("catalogReference") or {}).get("catalogItemId"),
                },
                "productId": (li or {}).get("productId"),
                "productName": {
                    "translated": ((li or {}).get("productName") or {}).get("translated"),
                    "original": ((li or {}).get("productName") or {}).get("original"),
                },
                "price": (li or {}).get("price") or {},
            }
            for li in (o.get("lineItems") or [])
        ],
        "billingInfo": {
            "contactDetails": {
                "firstName": bi.get("firstName"),
                "lastName": bi.get("lastName"),
                "phone": bi.get("phone"),
                "email": bi.get("email"),
            },
        },
        "shippingInfo": {
            "logistics": {
                "shippingDestination": {
                    "contactDetails": {
                        "firstName": (si_dest.get("contactDetails") or {}).get("firstName"),
                        "lastName": (si_dest.get("contactDetails") or {}).get("lastName"),
                        "phone": (si_dest.get("contactDetails") or {}).get("phone"),
                    },
                    "address": si_dest.get("address") or {},
                },
            },
        },
        "buyerInfo": {
            "contactDetails": {
                "email": bu.get("email"),
            },
        },
        "priceSummary": {
            "total": {
                "formattedAmount": ((o.get("priceSummary", {}) or {}).get("total", {}) or {}).get("formattedAmount"),
            },
        },
        "paymentStatus": o.get("paymentStatus"),
        "fulfillmentStatus": o.get("fulfillmentStatus"),
        "buyerNote": o.get("buyerNote"),
        "updatedDate": o.get("updatedDate"),
    }


def _convertir_wix_orders_a_dux(orders_filtrados):
    """Convierte orders Wix (filtrados) en dict {dux_codigo: cantidad_total}
    usando mapping_wix_dux y packs_wix. Devuelve (resultado, sin_mapear)
    donde sin_mapear = {wix_id: {"nombre": str, "cantidad": float}}."""
    resultado = {}
    sin_mapear = {}

    df_m = db.cargar_mapping_wix_dux()
    mapping = {}
    if not df_m.empty:
        for _, r in df_m.iterrows():
            wid = str(r.get("wix_id", ""))
            dcod = str(r.get("dux_codigo", "") or "")
            try:
                factor = float(r.get("factor", 1.0))
            except (ValueError, TypeError):
                factor = 1.0
            if wid and dcod:
                mapping[wid] = (dcod, factor)

    df_p = db.cargar_packs_wix()
    packs = {}
    if not df_p.empty:
        for _, r in df_p.iterrows():
            pid = str(r.get("wix_id_pack", ""))
            dcod = str(r.get("dux_codigo", "") or "")
            try:
                cant = float(r.get("cantidad", 0))
            except (ValueError, TypeError):
                cant = 0.0
            if pid and dcod:
                packs.setdefault(pid, []).append((dcod, cant))

    for orden in orders_filtrados:
        for item in orden.get("lineItems", []):
            qty = item.get("quantity") or 0
            try:
                qty = float(qty)
            except (ValueError, TypeError):
                qty = 0.0
            cat_id = (
                (item.get("catalogReference") or {}).get("catalogItemId")
                or item.get("productId")
                or ""
            )
            cat_id = str(cat_id)

            if cat_id in packs:
                for dcod, cant in packs[cat_id]:
                    resultado[dcod] = resultado.get(dcod, 0.0) + cant * qty
            elif cat_id in mapping:
                dcod, factor = mapping[cat_id]
                resultado[dcod] = resultado.get(dcod, 0.0) + qty * factor
            else:
                nombre = (
                    (item.get("productName") or {}).get("translated")
                    or (item.get("productName") or {}).get("original")
                    or item.get("name")
                    or cat_id
                    or "(sin nombre)"
                )
                if cat_id not in sin_mapear:
                    sin_mapear[cat_id] = {"nombre": nombre, "cantidad": 0.0}
                sin_mapear[cat_id]["cantidad"] += qty

    return resultado, sin_mapear


@st.cache_data(ttl=120, show_spinner=False)
def _cargar_pedidos_dux_cached():
    return db.cargar_pedidos_dux()


def cargar_pedidos_dux_aggregated(productos_df, dia_estimado=None, fecha_compra=None):
    """Agrega pedidos DUX + Wix (filtrados por fecha_compra vía selecciones)
    + estimado semanal del dia indicado (default: ninguno).

    fecha_compra puede ser: None, un valor unico (str/date) o una lista/set
    de fechas (en cuyo caso se incluyen pedidos asignados a CUALQUIERA de ellas)."""
    cols = ["codigo", "producto", "unidad_medida", "cantidad", "estimado"]
    st.session_state["_wix_sin_mapear"] = {}
    st.session_state["_dux_contados"] = []
    st.session_state["_wix_contados"] = []
    all_orders = db.cargar_pedidos_dux()

    # Filtrar pedidos anulados (anulado="S") para que no cuenten en
    # ningun agregado (stock teorico, total a comprar, etc).
    all_orders = [
        o for o in all_orders
        if str(o.get("anulado", "N")).upper() != "S"
    ]

    selecciones_dux = db.cargar_selecciones("dux")

    if fecha_compra is not None:
        if isinstance(fecha_compra, (list, tuple, set)):
            fechas_str = {str(f) for f in fecha_compra if f}
        else:
            fechas_str = {str(fecha_compra)}
        all_orders = [
            o
            for o in all_orders
            if selecciones_dux.get(str(o.get("id") or o.get("nro_pedido") or "")) in fechas_str
        ]
        st.session_state["_dux_contados"] = all_orders

    items_planos = []
    for orden in all_orders:
        for item in extraer_items_dux(orden):
            items_planos.append(extraer_item_dux(item))

    df_items = (
        pd.DataFrame(items_planos)
        if items_planos
        else pd.DataFrame(columns=["codigo", "producto", "cantidad"])
    )

    if df_items.empty:
        df_agg = pd.DataFrame(columns=["codigo", "producto", "cantidad"])
    else:
        df_agg = df_items.groupby(["codigo", "producto"], as_index=False)[
            "cantidad"
        ].sum()

    # Sumar pedidos de Wix con fecha de entrega = fecha_compra
    if fecha_compra is not None:
        wix_orders = db.cargar_pedidos_wix()
        wix_orders = [
            o for o in wix_orders
            if str(o.get("status", "")).upper() != "CANCELED"
        ]
        try:
            wix_sel = db.cargar_selecciones("wix")
            wix_filtrados = [
                o for o in wix_orders if wix_sel.get(str(o.get("id"))) in fechas_str
            ]
            st.session_state["_wix_contados"] = wix_filtrados
            wix_dux_map, wix_sin_mapear = _convertir_wix_orders_a_dux(wix_filtrados)
            st.session_state["_wix_sin_mapear"] = wix_sin_mapear
            if wix_dux_map:
                map_prod_dux_x = dict(
                    zip(productos_df["codigo"].astype(str), productos_df["producto"])
                )
                wix_rows = [
                    {
                        "codigo": str(dcod),
                        "producto": map_prod_dux_x.get(str(dcod), ""),
                        "cantidad": cant,
                    }
                    for dcod, cant in wix_dux_map.items()
                ]
                df_wix_agg = pd.DataFrame(wix_rows)
                if df_agg.empty:
                    df_agg = df_wix_agg
                else:
                    df_agg = (
                        pd.concat([df_agg, df_wix_agg], ignore_index=True)
                        .groupby(["codigo", "producto"], as_index=False)[
                            "cantidad"
                        ].sum()
                    )
        except Exception:
            pass

    # Desglose de MIX: si un codigo aggreado corresponde a un MIX configurado,
    # se desglosa en sus componentes (en partes iguales) y el MIX se quita.
    # Si la tabla mixes_dux esta vacia o un MIX no esta configurado, no se hace nada.
    st.session_state["_mixes_sin_config"] = []
    try:
        mixes_dict = db.cargar_mixes_dux()
        if mixes_dict and not df_agg.empty:
            # Mapeo (base, unidad) -> codigo desde productos
            prod_temp_mix = productos_df.copy()
            partes_mix = (
                prod_temp_mix["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
            )
            prod_temp_mix["_base"] = partes_mix[0].str.strip()
            prod_temp_mix["_unidad"] = (
                partes_mix[1].fillna("").str.strip()
                if 1 in partes_mix.columns
                else ""
            )
            base_unit_to_cod = {
                (b, u): str(c)
                for c, b, u in zip(
                    prod_temp_mix["codigo"].astype(str),
                    prod_temp_mix["_base"],
                    prod_temp_mix["_unidad"],
                )
            }

            filas_nuevas = []
            indices_remover = []
            mixes_sin_config_visto = set()
            for idx, row in df_agg.iterrows():
                producto = str(row.get("producto", "") or "")
                partes_p = producto.rsplit(" - ", 1)
                base = partes_p[0].strip()
                unidad = partes_p[1].strip() if len(partes_p) > 1 else ""

                # Detectar si la base es un MIX (con o sin configuracion)
                es_mix = "MIX" in base.upper()

                if base in mixes_dict and mixes_dict[base]:
                    componentes = mixes_dict[base]
                    cantidad_total = float(row["cantidad"])
                    por_comp = cantidad_total / len(componentes)
                    for comp_base in componentes:
                        comp_codigo = base_unit_to_cod.get((comp_base, unidad))
                        if comp_codigo:
                            comp_producto = (
                                f"{comp_base} - {unidad}" if unidad else comp_base
                            )
                            filas_nuevas.append({
                                "codigo": comp_codigo,
                                "producto": comp_producto,
                                "cantidad": por_comp,
                            })
                    indices_remover.append(idx)
                elif es_mix:
                    # Es un MIX por nombre pero no esta en mixes_dict (o sin componentes)
                    if base not in mixes_sin_config_visto:
                        mixes_sin_config_visto.add(base)

            st.session_state["_mixes_sin_config"] = sorted(mixes_sin_config_visto)

            if indices_remover:
                df_agg = df_agg.drop(indices_remover).reset_index(drop=True)
            if filas_nuevas:
                df_nuevas = pd.DataFrame(filas_nuevas)
                df_agg = (
                    pd.concat([df_agg, df_nuevas], ignore_index=True)
                    .groupby(["codigo", "producto"], as_index=False)["cantidad"].sum()
                )
    except Exception:
        # Defensivo: si falla algo del desglose, seguimos con df_agg sin modificar
        pass

    if dia_estimado is None:
        df_est = pd.DataFrame(columns=["codigo", "estimado"])
    else:
        df_est = db.cargar_estimado_semanal(dia=dia_estimado)

    # Outer merge so items con solo estimado también aparecen
    if not df_est.empty:
        df_merge = df_agg.merge(
            df_est[["codigo", "estimado"]], on="codigo", how="outer"
        )
    else:
        df_merge = df_agg.copy()
        df_merge["estimado"] = 0.0

    df_merge["cantidad"] = df_merge["cantidad"].fillna(0).astype(float)
    df_merge["estimado"] = df_merge["estimado"].fillna(0).astype(float)

    map_prod = dict(zip(productos_df["codigo"].astype(str), productos_df["producto"]))
    map_unid = dict(zip(productos_df["codigo"].astype(str), productos_df["unidad_medida"]))
    df_merge["codigo"] = df_merge["codigo"].astype(str)
    df_merge["producto"] = df_merge.apply(
        lambda r: r.get("producto") if pd.notna(r.get("producto")) and r.get("producto")
        else map_prod.get(r["codigo"], ""),
        axis=1,
    )
    df_merge["unidad_medida"] = df_merge["codigo"].map(map_unid).fillna("")

    return df_merge[cols]


def _dux_get_first(d, claves):
    if not isinstance(d, dict):
        return None
    for k in claves:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def extraer_cliente_dux(orden):
    cliente_obj = orden.get("cliente")
    if isinstance(cliente_obj, dict):
        nombre = _dux_get_first(
            cliente_obj,
            ["razon_social", "nombre", "razonSocial", "nombre_completo"],
        )
        if nombre:
            return str(nombre)
    return str(
        _dux_get_first(
            orden,
            ["cliente", "razon_social", "razonSocial", "nombre_cliente",
             "apellido_razon_social"],
        )
        or "(sin cliente)"
    )


def extraer_items_dux(orden):
    for f in ["detalles", "items", "productos", "lineas", "renglones", "detalle"]:
        v = orden.get(f)
        if isinstance(v, list):
            return v
    return []


def extraer_item_dux(item):
    codigo = _dux_get_first(
        item,
        ["cod_item", "codItem", "codigo", "codigoItem",
         "codigoProducto", "cod_producto"],
    )
    descr = _dux_get_first(
        item,
        ["item", "descripcion", "producto", "detalle", "nombre"],
    )
    cant = _dux_get_first(
        item,
        [
            "cantidad", "cant", "qty", "quantity",
            "cantidad_pedida", "cantidadPedida",
            "cantidad_solicitada", "cantidadSolicitada",
            "cant_pedida", "cantPedida",
            "unidades", "ctd",
        ],
    )
    if cant is None:
        for k, v in item.items():
            if isinstance(k, str) and "cant" in k.lower() and isinstance(v, (int, float)):
                cant = v
                break
    try:
        cant = float(cant) if cant is not None else 0.0
    except (ValueError, TypeError):
        cant = 0.0
    return {
        "codigo": str(codigo) if codigo is not None else "",
        "producto": descr or "",
        "cantidad": cant,
    }


def _slim_dux_pedido(o):
    """Versión compacta de un pedido DUX con SOLO los campos que la UI usa
    al mostrar 'Pedidos contados'. Reduce ~10x el JSON para que entre en
    la celda de Sheets (49KB)."""
    if not isinstance(o, dict):
        return {}
    nro = _dux_get_first(o, ["nro_pedido", "nroPedido", "numero", "id"])
    cliente_txt = extraer_cliente_dux(o)
    items_slim = [extraer_item_dux(it) for it in extraer_items_dux(o)]
    return {
        # 'nro_pedido' es la primer clave que mira _dux_get_first al renderizar.
        "nro_pedido": nro,
        # extraer_cliente_dux lee orden.cliente.razon_social, asi que
        # preservamos esa forma para que el render no cambie.
        "cliente": {"razon_social": cliente_txt},
        # extraer_items_dux mira 'detalles' como primera opcion.
        "detalles": items_slim,
    }


def _slim_wix_pedido(o):
    """Versión compacta de un pedido Wix con SOLO los campos que la UI usa."""
    if not isinstance(o, dict):
        return {}
    bi = (o.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
    line_items_slim = []
    for li in (o.get("lineItems") or []):
        pn = li.get("productName") or {}
        line_items_slim.append({
            "productName": {
                "translated": pn.get("translated"),
                "original": pn.get("original"),
            },
            "quantity": li.get("quantity") or 0,
        })
    return {
        "number": o.get("number") or o.get("id", ""),
        "id": o.get("id", ""),
        "billingInfo": {
            "contactDetails": {
                "firstName": bi.get("firstName", "") or "",
                "lastName": bi.get("lastName", "") or "",
            }
        },
        "lineItems": line_items_slim,
    }


@st.cache_data(ttl=600)
def construir_grafo_conversion(compuestos_df):
    grafo = {}
    for _, row in compuestos_df.iterrows():
        c_orig = str(row["codigo_origen"])
        c_comp = str(row["codigo_componente"])
        q_orig = row.get("cantidad_origen")
        q_comp = row.get("cantidad_componente")
        if pd.isna(q_orig) or pd.isna(q_comp) or q_orig == 0 or q_comp == 0:
            continue
        grafo.setdefault(c_orig, {})[c_comp] = q_comp / q_orig
        grafo.setdefault(c_comp, {})[c_orig] = q_orig / q_comp
    return grafo


def convertir(grafo, desde, hasta):
    if desde == hasta:
        return 1.0
    visitados = {desde}
    cola = [(desde, 1.0)]
    while cola:
        actual, factor = cola.pop(0)
        for vecino, peso in grafo.get(actual, {}).items():
            if vecino in visitados:
                continue
            nuevo = factor * peso
            if vecino == hasta:
                return nuevo
            visitados.add(vecino)
            cola.append((vecino, nuevo))
    return None


def componentes_conectados(codigos, grafo):
    codigos = set(map(str, codigos))
    componentes = []
    visitados = set()
    for codigo in codigos:
        if codigo in visitados:
            continue
        comp = set()
        cola = [codigo]
        while cola:
            actual = cola.pop(0)
            if actual in comp:
                continue
            comp.add(actual)
            for vecino in grafo.get(actual, {}):
                if vecino in codigos and vecino not in comp:
                    cola.append(vecino)
        componentes.append(comp)
        visitados |= comp
    return componentes


UNIDAD_BASE_PRIORIDAD = [
    "KG",
    "UNIDAD",
    "ATADO",
    "CABEZA",
    "LITRO",
    "PLANTA",
    "MAPLE",
    "CUBETA",
    "BANDEJA",
    "BOLSA",
    "CAJA",
    "RIESTRA",
]

UNIDAD_SINGULAR = {
    "UNIDADES": "UNIDAD", "UNIDAD": "UNIDAD",
    "ATADOS": "ATADO", "ATADO": "ATADO",
    "CUBETAS": "CUBETA", "CUBETA": "CUBETA",
    "PLANTAS": "PLANTA", "PLANTA": "PLANTA",
    "CABEZAS": "CABEZA", "CABEZA": "CABEZA",
    "BANDEJAS": "BANDEJA", "BANDEJA": "BANDEJA",
    "BOLSAS": "BOLSA", "BOLSA": "BOLSA",
    "CAJAS": "CAJA", "CAJA": "CAJA",
    "MAPLES": "MAPLE", "MAPLE": "MAPLE",
    "RIESTRAS": "RIESTRA", "RIESTRA": "RIESTRA",
    "LITROS": "LITRO", "LITRO": "LITRO",
    "KG": "KG", "KILOS": "KG", "KILO": "KG",
}


def parsear_descripcion(desc):
    if not isinstance(desc, str) or not desc.strip():
        return (None, None)
    texto = desc.strip().upper()
    match = re.search(
        r"APROX\.?\s*([0-9]+(?:[.,/][0-9]+)?)\s*([A-ZÁÉÍÓÚÑ]+)",
        texto,
    )
    if not match:
        return (None, None)
    num_str = match.group(1).replace(",", ".")
    unit_raw = match.group(2)
    try:
        if "/" in num_str:
            n, d = num_str.split("/")
            cantidad = float(n) / float(d)
        else:
            cantidad = float(num_str)
    except (ValueError, ZeroDivisionError):
        return (None, None)
    if unit_raw in ("GRAMOS", "GRAMO", "GR", "GRS", "G"):
        return (cantidad / 1000.0, "KG")
    unit = UNIDAD_SINGULAR.get(unit_raw)
    if unit is None:
        return (None, None)
    return (cantidad, unit)


def completar_relaciones(compuestos_df, productos_df, excepciones=None):
    excepciones = excepciones or set()
    prio = {u: i for i, u in enumerate(UNIDAD_BASE_PRIORIDAD)}

    columnas = [
        "codigo_origen",
        "producto_origen",
        "cantidad_origen",
        "codigo_componente",
        "producto_componente",
        "cantidad_componente",
    ]

    if excepciones and not compuestos_df.empty:
        compuestos_df = compuestos_df[
            ~compuestos_df.apply(
                lambda r: (
                    str(r["codigo_origen"]),
                    str(r["codigo_componente"]),
                )
                in excepciones,
                axis=1,
            )
        ]

    df = productos_df.copy()
    partes = df["producto"].str.rsplit(" - ", n=1, expand=True)
    df["base"] = partes[0].str.strip()
    df["unidad"] = partes[1].fillna("").str.strip() if 1 in partes.columns else ""
    df["prio"] = df["unidad"].map(lambda u: prio.get(u, 99))
    if "descripcion" not in df.columns:
        df["descripcion"] = ""
    df["descripcion"] = df["descripcion"].fillna("")

    nuevas = []
    for _, grupo in df.groupby("base"):
        if len(grupo) < 2:
            continue
        grupo = grupo.sort_values(["prio", "codigo"])
        base_row = grupo.iloc[0]
        unidad_a_row = {r["unidad"]: r for _, r in grupo.iterrows()}

        for _, origen in grupo.iloc[1:].iterrows():
            cantidad_comp = float("nan")
            componente = base_row

            target_cant, target_unit = parsear_descripcion(origen["descripcion"])
            if (
                target_unit is not None
                and target_unit in unidad_a_row
                and unidad_a_row[target_unit]["codigo"] != origen["codigo"]
            ):
                componente = unidad_a_row[target_unit]
                cantidad_comp = target_cant

            par = (str(origen["codigo"]), str(componente["codigo"]))
            if par in excepciones:
                continue

            nuevas.append(
                {
                    "codigo_origen": origen["codigo"],
                    "producto_origen": origen["producto"],
                    "cantidad_origen": 1.0,
                    "codigo_componente": componente["codigo"],
                    "producto_componente": componente["producto"],
                    "cantidad_componente": cantidad_comp,
                }
            )

    generadas = pd.DataFrame(nuevas)

    if generadas.empty:
        return compuestos_df[columnas].sort_values("producto_origen").reset_index(drop=True)

    existentes = set(
        zip(
            compuestos_df["codigo_origen"].astype(str),
            compuestos_df["codigo_componente"].astype(str),
        )
    )
    generadas = generadas[
        ~generadas.apply(
            lambda r: (str(r["codigo_origen"]), str(r["codigo_componente"]))
            in existentes,
            axis=1,
        )
    ]

    merged = pd.concat([compuestos_df[columnas], generadas[columnas]], ignore_index=True)
    return merged.sort_values("producto_origen").reset_index(drop=True)


productos = db.cargar_productos()
compuestos_orig = db.cargar_compuestos()
# Si compuestos esta vacio (Sheet corrupto), no llamamos completar_relaciones
# (rompe por columnas faltantes). El usuario debera re-sincronizar.
# IMPORTANTE: usar st.empty() para que el árbol de widgets antes de st.tabs()
# sea siempre estable (mismo nro de slots). Un st.error() condicional sin
# st.stop() desplaza el índice del st.tabs() y rompe la selección de tabs.
_compuestos_error_ph = st.empty()
if compuestos_orig.empty or "codigo_origen" not in compuestos_orig.columns:
    _compuestos_error_ph.error(
        "⚠️ La tabla `compuestos` está vacía. "
        "Andá a la pestaña ⚙️ Relacionar productos y guardá las relaciones."
    )
    compuestos = pd.DataFrame(
        columns=[
            "codigo_origen", "producto_origen", "cantidad_origen",
            "codigo_componente", "producto_componente", "cantidad_componente",
        ]
    )
else:
    compuestos = completar_relaciones(compuestos_orig, productos, EXCEPCIONES)
    # NOTA: ya no guardamos automaticamente compuestos generados. Si hay relaciones
    # nuevas se computan en memoria para esta sesion pero NO se escriben a Sheets
    # (antes hacia un write en cada arranque -> gastaba quota).
    # Para persistir cambios al Sheet, ir a la pestania Relacionar productos y
    # apretar Guardar.

productos["label"] = productos["codigo"] + " - " + productos["producto"]

opciones = productos["label"].tolist()

map_label_a_producto = dict(zip(productos["label"], productos["producto"]))
map_label_a_codigo = dict(zip(productos["label"], productos["codigo"]))

compuestos["origen_label"] = (
    compuestos["codigo_origen"].astype(str)
    + " - "
    + compuestos["producto_origen"].astype(str)
)

compuestos["componente_label"] = (
    compuestos["codigo_componente"].astype(str)
    + " - "
    + compuestos["producto_componente"].astype(str)
)

map_label_a_unidad = dict(zip(productos["label"], productos["unidad_medida"]))

# Boton global para refrescar datos modificados por otros usuarios.
# Util cuando la app esta instalada como PWA en el celular y queda viva
# en background: sin esto, el usuario sigue viendo datos viejos hasta
# que cierre y abra la PWA.
st.markdown('<style>[data-testid="stButton"][data-key="btn_refresh_global"] button { font-size: 1.1rem; padding: 0.5rem 1.2rem; }</style>', unsafe_allow_html=True)
if st.button(
    "🔄  Recargar",
    key="btn_refresh_global",
):
    st.cache_data.clear()
    st.toast("Datos actualizados", icon="✅")
    st.rerun()

def _sync_gastos(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    _id_empresa = int(dux_cfg.get("id_empresa", 3455))
    _id_sucursal = int(dux_cfg.get("id_sucursal", 3))
    url_g = f"{_base_url}/v2/gastos"
    headers_g = {"accept": "application/json", "authorization": f"Bearer {_token}"}
    page_offset, page_size, all_gastos = 0, 50, []
    while True:
        params_g = {
            "id_empresa": _id_empresa, "id_sucursal": _id_sucursal,
            "fecha_desde": fecha_desde.strftime("%Y-%m-%d"),
            "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d"),
            "incluir_detalle": "true", "offset": page_offset, "limit": page_size,
        }
        try:
            r = requests.get(url_g, params=params_g, headers=headers_g, timeout=30)
        except requests.RequestException as e:
            return False, 0, msg_error_red("DUX (gastos)", e)
        if r.status_code != 200:
            return False, 0, msg_error_http("DUX (gastos)", r.status_code, r.text)
        try:
            d = r.json()
        except ValueError:
            return False, 0, "❌ DUX devolvió una respuesta inválida (gastos)."
        if isinstance(d, dict) and "error" in d:
            return False, 0, f"❌ DUX (gastos): {d['error'].get('mensaje', d['error'])}"
        page = d.get("datos", []) or [] if isinstance(d, dict) else (d if isinstance(d, list) else [])
        if not page:
            break
        all_gastos.extend(page)
        paging = d.get("paginacion", {}) or {} if isinstance(d, dict) else {}
        if not paging.get("hay_mas"):
            break
        page_offset += page_size
        time.sleep(DUX_RATE_LIMIT_SECONDS)
    db.guardar_gastos(all_gastos)
    return True, len(all_gastos), f"✅ {len(all_gastos)} gastos sincronizados."


def _sync_pagos_proveedores(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    _id_empresa = int(dux_cfg.get("id_empresa", 3455))
    _id_sucursal = int(dux_cfg.get("id_sucursal", 3))
    url = f"{_base_url}/v2/pagos-proveedores"
    headers = {"accept": "application/json", "authorization": f"Bearer {_token}"}
    page_offset, page_size, all_pagos = 0, 50, []
    while True:
        params = {
            "id_empresa": _id_empresa, "id_sucursal": _id_sucursal,
            "fecha_desde": fecha_desde.strftime("%Y-%m-%d"),
            "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d"),
            "estado": "emitido", "offset": page_offset, "limit": page_size,
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            return False, 0, msg_error_red("DUX (pagos proveedores)", e)
        if r.status_code != 200:
            return False, 0, msg_error_http("DUX (pagos proveedores)", r.status_code, r.text)
        try:
            d = r.json()
        except ValueError:
            return False, 0, "❌ DUX devolvió una respuesta inválida (pagos proveedores)."
        if isinstance(d, dict) and "error" in d:
            return False, 0, f"❌ DUX (pagos proveedores): {d['error'].get('mensaje', d['error'])}"
        page = d.get("datos", []) or [] if isinstance(d, dict) else (d if isinstance(d, list) else [])
        if not page:
            break
        all_pagos.extend(page)
        paging = d.get("paginacion", {}) or {} if isinstance(d, dict) else {}
        if not paging.get("hay_mas"):
            break
        page_offset += page_size
        time.sleep(DUX_RATE_LIMIT_SECONDS)
    db.guardar_pagos_proveedores(all_pagos)
    return True, len(all_pagos), f"✅ {len(all_pagos)} pagos a proveedores sincronizados."


def _sync_compras(fecha_desde, fecha_hasta):
    compras_res = cargar_compras_dux_v2(fecha_desde, fecha_hasta)
    if compras_res is None:
        return False, 0, msg_error_http("DUX (compras)", 401)
    compras_raw = compras_res.get("compras", [])
    # Deduplicar por id — la segunda pasada (ANULADA) tiene prioridad
    _seen = {}
    for c in compras_raw:
        _seen[c.get("id_compra")] = c
    compras_raw = list(_seen.values())
    n_items = sum(len(c.get("items", []) or []) for c in compras_raw)
    db.guardar_compras_sync(compras_raw)
    return True, len(compras_raw), f"✅ {len(compras_raw)} comprobantes sincronizados ({n_items} ítems)."


def _sync_pedidos_dux(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    _id_empresa = int(dux_cfg.get("id_empresa", 3455))
    _id_sucursal = int(dux_cfg.get("id_sucursal", 3))
    url_p = f"{_base_url}/pedidos"
    headers_p = {"accept": "application/json", "authorization": _token}
    page_offset, page_size, all_orders = 0, 50, []
    while True:
        params_p = {
            "idEmpresa": _id_empresa, "idSucursal": _id_sucursal,
            "fechaDesde": fecha_desde.strftime("%Y-%m-%d"),
            "fechaHasta": fecha_hasta.strftime("%Y-%m-%d"),
            "offset": page_offset, "limit": page_size,
        }
        try:
            r = requests.get(url_p, params=params_p, headers=headers_p, timeout=30)
        except requests.RequestException as e:
            return False, 0, msg_error_red("DUX (pedidos)", e)
        if r.status_code != 200:
            return False, 0, msg_error_http("DUX (pedidos)", r.status_code, r.text)
        try:
            d = r.json()
        except ValueError:
            return False, 0, "❌ DUX devolvió una respuesta inválida (pedidos)."
        if isinstance(d, dict) and "message" in d and "results" not in d:
            return False, 0, f"❌ DUX (pedidos): {d['message']}"
        if isinstance(d, dict) and "results" in d:
            page = d["results"]
        elif isinstance(d, list):
            page = d
        else:
            page = []
        if not page:
            break
        all_orders.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size
        time.sleep(DUX_RATE_LIMIT_SECONDS)
    db.guardar_pedidos_dux(all_orders)
    try:
        db.guardar_config({"dux_fecha_desde": str(fecha_desde), "dux_fecha_hasta": str(fecha_hasta)})
    except Exception:
        pass
    n = len(all_orders)
    return True, n, f"✅ {n} pedidos DUX sincronizados." if n else (True, 0, "No hay pedidos DUX en ese rango.")


def _sync_pedidos_wix(fecha_desde, fecha_hasta):
    wix_cfg = st.secrets.get("wix", {})
    wix_token_s = wix_cfg.get("api_key", "")
    wix_account_s = wix_cfg.get("account_id", "")
    wix_site_s = wix_cfg.get("site_id", "")
    url = "https://www.wixapis.com/ecom/v1/orders/search"
    headers = {
        "Authorization": wix_token_s, "wix-account-id": wix_account_s,
        "wix-site-id": wix_site_s, "Content-Type": "application/json",
    }
    _filter = {
        "$and": [
            {"createdDate": {"$gte": f"{fecha_desde}T00:00:00.000Z"}},
            {"createdDate": {"$lte": f"{fecha_hasta}T23:59:59.999Z"}},
        ]
    }
    all_orders = []
    cursor = None
    while True:
        paging = {"limit": 100}
        if cursor:
            paging["cursor"] = cursor
        body = {"search": {"filter": _filter, "cursorPaging": paging}}
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=30)
        except requests.RequestException as e:
            return False, 0, msg_error_red("Wix", e)
        if resp.status_code != 200:
            return False, 0, msg_error_http("Wix", resp.status_code, resp.text)
        try:
            data = resp.json()
        except ValueError:
            return False, 0, "❌ Wix devolvió una respuesta inválida."
        all_orders.extend(data.get("orders", []))
        meta = data.get("metadata") or data.get("pagingMetadata") or {}
        cursor = (meta.get("cursors") or {}).get("next") or meta.get("next")
        if not cursor or not data.get("orders"):
            break
    orders_slim = [_slim_wix_order(o) for o in all_orders]
    db.guardar_pedidos_wix(orders_slim)
    try:
        db.guardar_config({"wix_fecha_desde": str(fecha_desde), "wix_fecha_hasta": str(fecha_hasta)})
    except Exception:
        pass
    return True, len(all_orders), f"✅ {len(all_orders)} pedidos Wix sincronizados."


def _sync_facturas(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    _id_empresa = int(dux_cfg.get("id_empresa", 3455))
    _id_sucursal = int(dux_cfg.get("id_sucursal", 3))
    url_f = f"{_base_url}/facturas"
    headers_f = {"accept": "application/json", "authorization": _token}
    page_size = 50

    def _fetch_facturas(extra_params=None):
        results_all = []
        offset = 0
        while True:
            params_f = {
                "fechaDesde": fecha_desde.strftime("%Y-%m-%d"),
                "fechaHasta": fecha_hasta.strftime("%Y-%m-%d"),
                "idEmpresa": _id_empresa,
                "idSucursal": _id_sucursal,
                "offset": offset,
                "limit": page_size,
            }
            if extra_params:
                params_f.update(extra_params)
            try:
                r = requests.get(url_f, params=params_f, headers=headers_f, timeout=30)
            except requests.RequestException as e:
                return None, msg_error_red("DUX (facturas)", e)
            if r.status_code != 200:
                return None, msg_error_http("DUX (facturas)", r.status_code, r.text)
            try:
                d = r.json()
            except ValueError:
                return None, "❌ DUX devolvió una respuesta inválida (facturas)."
            if isinstance(d, dict) and "message" in d and "results" not in d:
                return None, f"❌ DUX (facturas): {d['message']}"
            results = d.get("results", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            if not results:
                break
            results_all.extend(results)
            total = (d.get("paging") or {}).get("total", 0) if isinstance(d, dict) else 0
            offset += page_size
            if offset >= total or len(results) < page_size:
                break
            time.sleep(DUX_RATE_LIMIT_SECONDS)
        return results_all, None

    # Todas las facturas vigentes
    all_facturas, err = _fetch_facturas({"anuladas": "false"})
    if err:
        return False, 0, err

    time.sleep(DUX_RATE_LIMIT_SECONDS)

    # IDs de facturas cobradas
    cobradas, err2 = _fetch_facturas({"anuladas": "false", "conCobro": "true"})
    _debug_cobro = f"conCobro=true → {len(cobradas or [])} resultados, err={err2}"
    if err2:
        cobradas = []
    cobradas_ids = {str(f.get("id") or "") for f in (cobradas or [])}

    # Facturas anuladas
    time.sleep(DUX_RATE_LIMIT_SECONDS)
    anuladas, _ = _fetch_facturas({"anuladas": "true"})
    all_facturas.extend(anuladas or [])

    # Marcar con_cobro
    for f in all_facturas:
        f["con_cobro"] = str(f.get("id") or "") in cobradas_ids

    db.guardar_facturas(all_facturas)
    n_cobr = sum(1 for f in all_facturas if f.get("con_cobro"))
    n_anul = len(anuladas or [])
    return True, len(all_facturas), f"✅ {len(all_facturas)} facturas — {n_cobr} cobradas, {n_anul} anuladas. [{_debug_cobro}]"


def _sync_cobros(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    _id_empresa = int(dux_cfg.get("id_empresa", 3455))
    _id_sucursal = int(dux_cfg.get("id_sucursal", 3))
    url = f"{_base_url}/v2/cobros"
    headers = {"accept": "application/json", "authorization": f"Bearer {_token}"}
    page_offset, page_size, all_cobros = 0, 50, []
    while True:
        params = {
            "id_empresa": _id_empresa, "id_sucursal": _id_sucursal,
            "fecha_desde": fecha_desde.strftime("%Y-%m-%d"),
            "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d"),
            "offset": page_offset, "limit": page_size,
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            return False, 0, msg_error_red("DUX (cobros)", e)
        if r.status_code != 200:
            return False, 0, msg_error_http("DUX (cobros)", r.status_code, r.text)
        try:
            d = r.json()
        except ValueError:
            return False, 0, "❌ DUX devolvió una respuesta inválida (cobros)."
        if isinstance(d, dict) and "error" in d:
            return False, 0, f"❌ DUX (cobros): {d['error'].get('mensaje', d['error'])}"
        page = d.get("datos", []) or [] if isinstance(d, dict) else (d if isinstance(d, list) else [])
        if not page:
            break
        all_cobros.extend(page)
        paging = d.get("paginacion", {}) or {} if isinstance(d, dict) else {}
        if not paging.get("hay_mas"):
            break
        page_offset += page_size
        time.sleep(DUX_RATE_LIMIT_SECONDS)
    db.guardar_cobros(all_cobros)
    return True, len(all_cobros), f"✅ {len(all_cobros)} cobros sincronizados."


def _sync_percepciones(fecha_desde, fecha_hasta):
    dux_cfg = st.secrets.get("dux", {})
    _token = dux_cfg.get("token", "")
    _base_url = dux_cfg.get("base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services")
    url = f"{_base_url}/percepcionesImpuestos"
    headers = {"accept": "application/json", "authorization": _token}
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        return False, 0, msg_error_red("DUX (percepciones)", e)
    if r.status_code != 200:
        return False, 0, msg_error_http("DUX (percepciones)", r.status_code, r.text)
    try:
        data = r.json()
    except ValueError:
        return False, 0, "❌ DUX devolvió una respuesta inválida (percepciones)."
    if not isinstance(data, list):
        return False, 0, "❌ Formato inesperado en respuesta de percepciones."
    db.guardar_percepciones_impuestos(data)
    return True, len(data), f"✅ {len(data)} percepciones sincronizadas."


# Datos de balance cargados aquí (fuera de cualquier tab) para que el árbol
# de widgets sea siempre consistente y no haya desincronización de tabs.
facturas_bal     = db.cargar_facturas()
pedidos_wix_bal  = db.cargar_pedidos_wix()
compras_bal      = db.cargar_compras()
comprobantes_bal = db.cargar_comprobantes_compra()
gastos_bal       = db.cargar_gastos()
cobros_bal       = db.cargar_cobros()
pagos_bal        = db.cargar_pagos_proveedores()

# ── AUTH ROLES ───────────────────────────────────────────────────────────────────────────
_USER_ROLES = {"tomas": "full", "claudia": "full", "carlos": "carlos"}

def _get_role(username):
    return _USER_ROLES.get((username or "").lower(), "restricted")

_logged_user = st.session_state["auth_user"]
_role = _get_role(_logged_user)


# Top-level tabs: agrupados por funcion. Sub-tabs adentro de cada grupo.
_ALL_TABS_DEF = [
    ("tab_comprar",               "🛒 Total a comprar", {"full", "carlos", "restricted"}),
    ("tab_egresos",               "💸 Egresos",         {"full"}),
    ("tab_ingresos",              "📈 Ingresos",        {"full"}),
    ("tab_grupo_pedidos",         "📋 Pedidos",         {"full", "carlos", "restricted"}),
    ("tab_grupo_diario",          "📦 Diario",          {"full", "carlos", "restricted"}),
    ("tab_tesoreria",             "🏦 Tesorería",       {"full", "carlos"}),
    ("tab_iva",                   "🧾 IVA",             {"full"}),
    ("tab_sync",                  "🔄 Sincronizar",     {"full", "carlos", "restricted"}),
    ("tab_grupo_config",          "⚙️ Configuración",   {"full", "carlos", "restricted"}),
    ("tab_grupo_config_avanzada", "🔧 Config. avanzada",{"full"}),
]

_visible_tabs = [(k, label) for k, label, roles in _ALL_TABS_DEF if _role in roles]
_tab_objects = st.tabs([label for _, label in _visible_tabs])
_tabs_dict = {k: obj for (k, _), obj in zip(_visible_tabs, _tab_objects)}

tab_comprar               = _tabs_dict.get("tab_comprar")
tab_egresos               = _tabs_dict.get("tab_egresos")
tab_ingresos              = _tabs_dict.get("tab_ingresos")
tab_grupo_pedidos         = _tabs_dict.get("tab_grupo_pedidos")
tab_grupo_diario          = _tabs_dict.get("tab_grupo_diario")
tab_tesoreria             = _tabs_dict.get("tab_tesoreria")
tab_iva                   = _tabs_dict.get("tab_iva")
tab_sync                  = _tabs_dict.get("tab_sync")
tab_grupo_config          = _tabs_dict.get("tab_grupo_config")
tab_grupo_config_avanzada = _tabs_dict.get("tab_grupo_config_avanzada")

# Sub-tab pre-init (in case parent tab is not visible for this role)
_sub_resumen = _sub_pendientes = tab_ing_cobros_wix = None
_stab_movimientos = _stab_transferencias = _stab_ajustes = _stab_saldo_ini = None
tab_eg_compras = tab_eg_gastos = tab_eg_pagos = None
tab_ing_facturas = tab_ing_cobros = None
tab_dux_productos = tab_dux_rubros = tab_wix_productos = None
tab_proveedores = tab_probar = tab_migracion = tab_cajas = tab_gastos_catalogo = tab_percepciones = None
tab_ing_cobros_wix = None

if tab_tesoreria:
    with tab_tesoreria:
        _sub_resumen, _sub_pendientes, tab_ing_cobros_wix, _stab_movimientos, _stab_transferencias, _stab_ajustes, _stab_saldo_ini = st.tabs([
            "📊 Resumen", "⏳ Pendientes y deudores", "💳 Cobros Wix", "📊 Movimientos", "↔️ Transferencias", "🔧 Ajustes", "💵 Saldo inicial",
        ])

# Tabs ocultas (definidas como None para que las referencias no rompan)
tab_grupo_analitica = None
tab_resumen_rango = None
tab_desglose_rango = None
tab_hist_precios = None
tab_detalle_compras = None

if tab_egresos:
    with tab_egresos:
        tab_eg_compras, tab_eg_gastos, tab_eg_pagos = st.tabs(["💰 Compras", "📄 Gastos", "💳 Pagos proveedores"])

if tab_ingresos:
    with tab_ingresos:
        tab_ing_facturas, tab_ing_cobros = st.tabs(["🧾 Facturas DUX", "💵 Cobros DUX"])

with tab_grupo_pedidos:
    tab_dux, tab_wix = st.tabs(["DUX", "Wix"])

with tab_grupo_diario:
    tab_stock, tab_estimado = st.tabs(["📦 Stock", "Estimado"])

if False:  # Analitica oculta — para volver: cambiar a 'with tab_grupo_analitica:'
    (
        tab_resumen_rango,
        tab_desglose_rango,
        tab_hist_precios,
        tab_detalle_compras,
    ) = st.tabs(
        [
            "Resumen por rango",
            "Desglose por unidad",
            "Histórico precios",
            "Detalle compras",
        ]
    )

def _fmt_monto(v):
    return f"$ {float(v or 0):,.0f}"

def _safe_date(val, default=date.min):
    if not val:
        return default
    try:
        _dt = pd.to_datetime(val)
        return _dt.date() if not pd.isna(_dt) else default
    except Exception:
        return default


def _caja_key(tipo_valor, descripcion):
    tv   = (tipo_valor or "").upper().strip()
    desc = (descripcion or "").upper().strip()
    if "CHEQUE" in tv or "CHEQUE" in desc:
        return "CHEQUE"
    if tv == "CUENTA":
        return desc or "CUENTA"
    return tv or "—"


def _calcular_saldos_actuales(cobros, pagos):
    """Devuelve {caja_key: saldo_actual} con fecha de corte por caja."""
    _cajas_list = db.cargar_cajas()
    _cajas_map  = {c["id"]: c["nombre"] for c in _cajas_list}
    _ajustes_todos = db.cargar_ajustes_caja()

    _inicial = {}
    _inicial_fecha = {}  # caja_name -> fecha de corte
    for _aj in _ajustes_todos:
        if _aj.get("tipo") == "inicial":
            _cn = _cajas_map.get(_aj["caja_id"], "")
            if _cn:
                _inicial[_cn] = float(_aj.get("monto") or 0)
                _inicial_fecha[_cn] = _safe_date(_aj.get("fecha"))

    _all_aj_sum = {}
    for _aj in _ajustes_todos:
        if _aj.get("tipo") != "ajuste":
            continue
        _cn = _cajas_map.get(_aj["caja_id"], "")
        if not _cn:
            continue
        _ajf = _safe_date(_aj.get("fecha"))
        if _ajf < _inicial_fecha.get(_cn, date.min):
            continue
        _all_aj_sum[_cn] = _all_aj_sum.get(_cn, 0.0) + float(_aj.get("monto") or 0)

    _hist = {}
    for _c in cobros:
        _cf = _safe_date(_c.get("fecha"))
        if _cf == date.min:
            continue
        for _cob in _c.get("cobranza", []):
            _ck = _caja_key(_cob.get("tipo_valor"), _cob.get("descripcion"))
            if _cf < _inicial_fecha.get(_ck, date.min):
                continue
            _h = _hist.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})
            _h["Entradas"] += float(_cob.get("monto") or 0)
    for _p in pagos:
        _pf = _safe_date(_p.get("fecha"))
        if _pf == date.min:
            continue
        for _lin in _p.get("lineas_pago", []):
            _ck = _caja_key(_lin.get("tipo_valor"), _lin.get("descripcion"))
            if _pf < _inicial_fecha.get(_ck, date.min):
                continue
            _h = _hist.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})
            _h["Salidas"] += float(_lin.get("monto") or 0)
    _transferencias = db.cargar_transferencias()
    for _tr in _transferencias:
        _trf = _safe_date(_tr.get("fecha"))
        if _trf == date.min:
            continue
        _horig = (_tr.get("origen")  or {}).get("nombre") or _cajas_map.get(_tr.get("origen_id"),  "—")
        _hdest = (_tr.get("destino") or {}).get("nombre") or _cajas_map.get(_tr.get("destino_id"), "—")
        _htm   = float(_tr.get("monto") or 0)
        if _trf >= _inicial_fecha.get(_horig, date.min):
            _hist.setdefault(_horig, {"Entradas": 0.0, "Salidas": 0.0})["Salidas"]  += _htm
        if _trf >= _inicial_fecha.get(_hdest, date.min):
            _hist.setdefault(_hdest, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += _htm

    # Solo devuelve cajas que tienen saldo inicial configurado
    _saldos = {}
    for _cn, _ini in _inicial.items():
        _h  = _hist.get(_cn, {"Entradas": 0.0, "Salidas": 0.0})
        _aj = _all_aj_sum.get(_cn, 0.0)
        _saldos[_cn] = _ini + _h["Entradas"] - _h["Salidas"] + _aj
    return _saldos


def _render_movimiento_caja(cobros, pagos):
    _hoy = date.today()

    # Fecha máxima = última fecha con datos reales (cobros, pagos, transferencias o ajustes)
    _fechas_datos = []
    for _c in cobros:
        _fd = _safe_date(_c.get("fecha"))
        if _fd != date.min:
            _fechas_datos.append(_fd)
    for _p in pagos:
        _fd = _safe_date(_p.get("fecha"))
        if _fd != date.min:
            _fechas_datos.append(_fd)
    for _tr in db.cargar_transferencias():
        _fd = _safe_date(_tr.get("fecha"))
        if _fd != date.min:
            _fechas_datos.append(_fd)
    for _aj in db.cargar_ajustes_caja():
        if _aj.get("tipo") == "ajuste":
            _fd = _safe_date(_aj.get("fecha"))
            if _fd != date.min:
                _fechas_datos.append(_fd)
    _hasta = max(_fechas_datos) if _fechas_datos else _hoy

    # Fecha mínima = fecha del saldo inicial más antiguo configurado
    _aj_ini_todos = db.cargar_ajustes_caja()
    _fechas_ini = [_safe_date(_aj.get("fecha")) for _aj in _aj_ini_todos if _aj.get("tipo") == "inicial"]
    _fecha_min = min((_f for _f in _fechas_ini if _f != date.min), default=date(2000, 1, 1))

    _default_desde = max(_hoy.replace(day=1), _fecha_min)

    _cajas_list = db.cargar_cajas()
    _cajas_map  = {c["id"]: c["nombre"] for c in _cajas_list}
    try:
        _wix_orders_mov = db.cargar_pedidos_wix()
    except Exception:
        _wix_orders_mov = []
    try:
        _fechas_pago_mov = db.cargar_fechas_pago_wix()
    except Exception:
        _fechas_pago_mov = {}

    _cfg_caja = db.cargar_config()
    try:
        _desde_def = date.fromisoformat(_cfg_caja.get("caja_desde", ""))
    except Exception:
        _desde_def = _default_desde
    try:
        _hasta_def = date.fromisoformat(_cfg_caja.get("caja_hasta", ""))
    except Exception:
        _hasta_def = _hasta
    _desde_def = max(_fecha_min, min(_desde_def, _hasta))
    _hasta_def = max(_fecha_min, min(_hasta_def, _hasta))

    with st.form("form_caja_fechas", border=False):
        _cc1, _cc2 = st.columns(2)
        with _cc1:
            _desde = st.date_input("Desde", value=_desde_def, key="caja_desde_in", format="DD/MM/YYYY")
        with _cc2:
            _hasta_in = st.date_input("Hasta", value=_hasta_def, key="caja_hasta_in", format="DD/MM/YYYY")
        _btn_caja = st.form_submit_button("Calcular", type="primary", use_container_width=True)
    if _btn_caja:
        db.guardar_config({"caja_desde": str(_desde), "caja_hasta": str(_hasta_in)})
    _hasta = _hasta_in
    _hasta_label = _hasta.strftime('%d/%m/%Y')
    _hasta_suffix = " (hoy)" if _hasta == _hoy else ""

    # caja_key -> {"Entradas": float, "Sal. Compras": float, "Sal. Gastos": float, "detalle": []}
    _por_caja = {}

    # Lookups para detectar pagos/cobros parciales
    _comp_pendiente  = {str(c.get("nro_comprobante") or ""): c.get("pago_pendiente", False)
                        for c in comprobantes_bal if c.get("nro_comprobante")}
    _comp_total_lkp  = {str(c.get("nro_comprobante") or ""): float(c.get("total") or 0)
                        for c in comprobantes_bal if c.get("nro_comprobante")}
    _fac_total_lkp   = {str(f.get("id") or ""): float(f.get("total") or 0) for f in facturas_bal if f.get("id")}
    _cob_por_fac_all = {}
    for _cx in cobros:
        for _ix in (_cx.get("imputaciones") or []):
            _fid = str(_ix.get("id_comp_venta") or "")
            if _fid:
                _cob_por_fac_all[_fid] = _cob_por_fac_all.get(_fid, 0.0) + float(_ix.get("monto_imputado") or 0)
    _pag_por_comp_all = {}
    for _px in pagos:
        for _ix in (_px.get("imputaciones") or []):
            _nro = str(_ix.get("nro_comprobante") or "")
            if _nro:
                _pag_por_comp_all[_nro] = _pag_por_comp_all.get(_nro, 0.0) + float(_ix.get("monto_imputado") or 0)

    for _c in cobros:
        try:
            _f = pd.to_datetime(str(_c.get("fecha") or "")).date()
        except Exception:
            continue
        if not (_desde <= _f <= _hasta):
            continue
        for _cob in _c.get("cobranza", []):
            _ck = _caja_key(_cob.get("tipo_valor"), _cob.get("descripcion"))
            _t = _por_caja.setdefault(_ck, {"Entradas": 0.0, "Sal. Compras": 0.0, "Sal. Gastos": 0.0, "detalle": []})
            _monto = float(_cob.get("monto") or 0)
            _t["Entradas"] += _monto
            _cli_obj = _c.get("cliente") or {}
            if isinstance(_cli_obj, dict):
                _cli_nombre = " ".join(filter(None, [
                    _cli_obj.get("apellido_razon_social", ""),
                    _cli_obj.get("nombre", ""),
                ])).strip() or "—"
            else:
                _cli_nombre = str(_cli_obj) or "—"
            _imput_cob = _c.get("imputaciones") or []
            _facts = ", ".join(
                str(i.get("nro_comprobante", "")).strip()
                for i in _imput_cob if i.get("nro_comprobante")
            ) or "—"
            _is_cob_parcial = bool(_imput_cob) and any(
                _cob_por_fac_all.get(str(i.get("id_comp_venta") or ""), 0) < _fac_total_lkp.get(str(i.get("id_comp_venta") or ""), float("inf"))
                for i in _imput_cob if i.get("id_comp_venta")
            )
            _tot_fac_ref  = sum(_fac_total_lkp.get(str(i.get("id_comp_venta") or ""), 0) for i in _imput_cob if i.get("id_comp_venta"))
            _tot_cob_ref  = sum(_cob_por_fac_all.get(str(i.get("id_comp_venta") or ""), 0) for i in _imput_cob if i.get("id_comp_venta"))
            _saldo_fac_ref = max(0.0, _tot_fac_ref - _tot_cob_ref)
            _t["detalle"].append({
                "Fecha":        _f,
                "Tipo":         "Entrada",
                "Cat.":         "",
                "Cliente":      _cli_nombre,
                "Facturas":     _facts,
                "Concepto":     _cli_nombre,
                "Proveedor":    "",
                "Cobro #":      _c.get("nro_comprobante") or "—",
                "Pago #":       "",
                "Cheque":       (_cob.get("descripcion") or _cob.get("tipo_valor") or "") if "CHEQUE" in (_cob.get("tipo_valor") or _cob.get("descripcion") or "").upper() else "",
                "Monto":        _monto,
                "Total factura": _tot_fac_ref,
                "Cobrado total": _tot_cob_ref,
                "Saldo":        _saldo_fac_ref,
                "imputaciones": _imput_cob,
                "_parcial":     _is_cob_parcial,
            })

    _ids_gastos = db.cargar_ids_gastos()

    for _p in pagos:
        try:
            _f = pd.to_datetime(str(_p.get("fecha") or "")).date()
        except Exception:
            continue
        if not (_desde <= _f <= _hasta):
            continue
        _imput = _p.get("imputaciones", [])
        def _es_gasto(i, _ids=_ids_gastos):
            _idc = i.get("id_comp_compra") or i.get("id_compra")
            return bool(i.get("id_gasto") or i.get("id_comp_gasto") or
                        (_idc and int(_idc) in _ids))
        def _es_compra(i, _ids=_ids_gastos):
            return not _es_gasto(i, _ids)
        def _gasto_label(i, _ids=_ids_gastos):
            _idc = i.get("id_comp_compra") or i.get("id_compra")
            if _idc and int(_idc) in _ids:
                return _ids[int(_idc)].get("label") or str(_idc)
            return str(i.get("nro_comprobante") or "")
        _tot_compra = sum(float(i.get("monto_imputado") or 0) for i in _imput if _es_compra(i))
        _tot_gasto  = sum(float(i.get("monto_imputado") or 0) for i in _imput if _es_gasto(i))
        _tot_imput  = _tot_compra + _tot_gasto
        _pct_compra = (_tot_compra / _tot_imput) if _tot_imput else 1.0
        _pct_gasto  = (_tot_gasto  / _tot_imput) if _tot_imput else 0.0
        _is_pag_parcial = bool(_imput) and any(
            _comp_pendiente.get(str(i.get("nro_comprobante") or ""), False)
            for i in _imput if _es_compra(i) and i.get("nro_comprobante")
        )

        for _lin in _p.get("lineas_pago", []):
            _ck = _caja_key(_lin.get("tipo_valor"), _lin.get("descripcion"))
            _t = _por_caja.setdefault(_ck, {"Entradas": 0.0, "Sal. Compras": 0.0, "Sal. Gastos": 0.0, "detalle": []})
            _monto      = float(_lin.get("monto") or 0)
            _sal_compra = _monto * _pct_compra
            _sal_gasto  = _monto * _pct_gasto
            _t["Sal. Compras"] += _sal_compra
            _t["Sal. Gastos"]  += _sal_gasto
            _cheque_det = ""
            if "CHEQUE" in (_lin.get("tipo_valor") or "").upper():
                _cheque_det = _lin.get("descripcion") or _lin.get("tipo_valor") or ""
            elif "CHEQUE" in (_lin.get("descripcion") or "").upper():
                _cheque_det = _lin.get("descripcion") or ""
            if _pct_compra == 1.0:
                _cat = "Compra"
            elif _pct_gasto == 1.0:
                _cat = "Gasto"
            else:
                _cat = "Mixto"
            if _cat == "Compra":
                _imput_filtro = [i for i in _imput if _es_compra(i)]
                _comp_list = ", ".join(
                    str(i.get("nro_comprobante", "")).strip()
                    for i in _imput_filtro if i.get("nro_comprobante")
                ) or "—"
            elif _cat == "Gasto":
                _imput_filtro = [i for i in _imput if _es_gasto(i)]
                _comp_list = ", ".join(
                    _gasto_label(i) for i in _imput_filtro
                ) or "—"
            else:
                _imput_filtro = _imput
                _comp_list = ", ".join(
                    str(i.get("nro_comprobante", "")).strip()
                    for i in _imput_filtro if i.get("nro_comprobante")
                ) or "—"
            _comp_imput_nros = [str(i.get("nro_comprobante") or "") for i in _imput if _es_compra(i) and i.get("nro_comprobante")]
            _tot_comp_ref  = sum(_comp_total_lkp.get(_n, 0) for _n in _comp_imput_nros)
            _tot_pag_ref   = sum(_pag_por_comp_all.get(_n, 0) for _n in _comp_imput_nros)
            _saldo_comp_ref = max(0.0, _tot_comp_ref - _tot_pag_ref)
            _t["detalle"].append({
                "Fecha":           _f,
                "Tipo":            "Salida",
                "Cat.":            _cat,
                "Concepto":        _comp_list,
                "Proveedor":       _p.get("proveedor") or "—",
                "Cobro #":         "",
                "Pago #":          _p.get("nro_comprobante") or "—",
                "Cheque":          _cheque_det,
                "Monto":           _monto,
                "Total comprobante": _tot_comp_ref,
                "Pagado total":    _tot_pag_ref,
                "Saldo":           _saldo_comp_ref,
                "imputaciones":    _imput,
                "_parcial":        _is_pag_parcial,
            })

    # Cobros Wix → Entradas
    for _wo in _wix_orders_mov:
        _oid = str(_wo.get("id") or "")
        _fp_raw = _fechas_pago_mov.get(_oid)
        if not _fp_raw:
            continue
        try:
            _wf = date.fromisoformat(str(_fp_raw))
        except Exception:
            continue
        if not (_desde <= _wf <= _hasta):
            continue
        _wcaja_id = _wo.get("caja_id")
        if not _wcaja_id:
            continue
        try:
            _wck = _cajas_map.get(int(_wcaja_id)) or _cajas_map.get(str(_wcaja_id))
        except (TypeError, ValueError):
            _wck = None
        if not _wck:
            continue
        _wmonto = _wix_monto(_wo)
        _t = _por_caja.setdefault(_wck, {"Entradas": 0.0, "Sal. Compras": 0.0, "Sal. Gastos": 0.0, "detalle": []})
        _t["Entradas"] += _wmonto
        _wbi = (_wo.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
        _wcli = (f"{_wbi.get('firstName', '')} {_wbi.get('lastName', '')}".strip()
                 or (_wo.get("buyerInfo") or {}).get("email", "") or "—")
        _wnro = str(_wo.get("number") or _oid)
        _t["detalle"].append({
            "Fecha":         _wf,
            "Tipo":          "Entrada",
            "Cat.":          "Wix",
            "Cliente":       _wcli,
            "Facturas":      "—",
            "Concepto":      f"Wix #{_wnro}",
            "Proveedor":     "",
            "Cobro #":       f"Wix #{_wnro}",
            "Pago #":        "",
            "Cheque":        "",
            "Monto":         _wmonto,
            "Total factura": 0.0,
            "Cobrado total": 0.0,
            "Saldo":         0.0,
            "imputaciones":  [],
            "_parcial":      False,
        })

    # Transferencias entre cajas
    _transferencias = db.cargar_transferencias()
    for _tr in _transferencias:
        try:
            _tf = pd.to_datetime(str(_tr.get("fecha") or "")).date()
        except Exception:
            continue
        if not (_desde <= _tf <= _hasta):
            continue
        _orig = (_tr.get("origen")  or {}).get("nombre") or _cajas_map.get(_tr.get("origen_id"), "—")
        _dest = (_tr.get("destino") or {}).get("nombre") or _cajas_map.get(_tr.get("destino_id"), "—")
        _tm   = float(_tr.get("monto") or 0)
        _conc = _tr.get("concepto") or "Transferencia"
        for _ck, _signo in [(_orig, -1), (_dest, 1)]:
            _t = _por_caja.setdefault(_ck, {"Entradas": 0.0, "Sal. Compras": 0.0, "Sal. Gastos": 0.0, "detalle": []})
            if _signo == 1:
                _t["Entradas"] += _tm
                _t["detalle"].append({"Fecha": _tf, "Tipo": "Entrada", "Cat.": "Transferencia", "Desde": _orig, "Hacia": _dest, "Concepto": _conc, "Proveedor": "", "Cobro #": "", "Pago #": "", "Cheque": "", "Monto": _tm, "imputaciones": []})
            else:
                _t["Sal. Compras"] += _tm
                _t["detalle"].append({"Fecha": _tf, "Tipo": "Salida", "Cat.": "Transferencia", "Desde": _orig, "Hacia": _dest, "Concepto": _conc, "Proveedor": "", "Cobro #": "", "Pago #": "", "Cheque": "", "Monto": _tm, "imputaciones": []})

    # Ajustes de caja (inicial + ajustes del período)
    _ajustes_todos = db.cargar_ajustes_caja()
    # saldo inicial por nombre de caja
    _inicial = {}
    for _aj in _ajustes_todos:
        if _aj.get("tipo") == "inicial":
            _cn = _cajas_map.get(_aj["caja_id"], "")
            if _cn:
                _inicial[_cn] = float(_aj.get("monto") or 0)
    # ajustes del período (para el desglose)
    _ajustes_periodo = {}
    for _aj in _ajustes_todos:
        if _aj.get("tipo") != "ajuste":
            continue
        try:
            _ajf = pd.to_datetime(str(_aj.get("fecha") or "")).date()
        except Exception:
            continue
        if not (_desde <= _ajf <= _hasta):
            continue
        _cn = _cajas_map.get(_aj["caja_id"], "")
        if _cn:
            _ajustes_periodo.setdefault(_cn, []).append(_aj)

    # Fecha de corte por caja (desde el saldo inicial configurado)
    _ini_fecha_hist = {}
    for _aj in _ajustes_todos:
        if _aj.get("tipo") == "inicial":
            _cn = _cajas_map.get(_aj["caja_id"], "")
            if _cn:
                _ini_fecha_hist[_cn] = _safe_date(_aj.get("fecha"))

    # Totales históricos desde la fecha de corte por caja para el saldo acumulativo
    _hist_total = {}
    for _c in cobros:
        _cf = _safe_date(_c.get("fecha"))
        if _cf == date.min:
            continue
        for _cob in _c.get("cobranza", []):
            _ck = _caja_key(_cob.get("tipo_valor"), _cob.get("descripcion"))
            if _cf < _ini_fecha_hist.get(_ck, date.min):
                continue
            _ht = _hist_total.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})
            _ht["Entradas"] += float(_cob.get("monto") or 0)
    for _p in pagos:
        _pf = _safe_date(_p.get("fecha"))
        if _pf == date.min:
            continue
        for _lin in _p.get("lineas_pago", []):
            _ck = _caja_key(_lin.get("tipo_valor"), _lin.get("descripcion"))
            if _pf < _ini_fecha_hist.get(_ck, date.min):
                continue
            _ht = _hist_total.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})
            _ht["Salidas"] += float(_lin.get("monto") or 0)
    for _tr in _transferencias:
        _trf = _safe_date(_tr.get("fecha"))
        if _trf == date.min:
            continue
        _horig = (_tr.get("origen")  or {}).get("nombre") or _cajas_map.get(_tr.get("origen_id"),  "—")
        _hdest = (_tr.get("destino") or {}).get("nombre") or _cajas_map.get(_tr.get("destino_id"), "—")
        _htm   = float(_tr.get("monto") or 0)
        if _trf >= _ini_fecha_hist.get(_horig, date.min):
            _hist_total.setdefault(_horig, {"Entradas": 0.0, "Salidas": 0.0})["Salidas"]  += _htm
        if _trf >= _ini_fecha_hist.get(_hdest, date.min):
            _hist_total.setdefault(_hdest, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += _htm
    for _wo in _wix_orders_mov:
        _oid = str(_wo.get("id") or "")
        _fp_raw = _fechas_pago_mov.get(_oid)
        if not _fp_raw:
            continue
        try:
            _wf = date.fromisoformat(str(_fp_raw))
        except Exception:
            continue
        _wcaja_id = _wo.get("caja_id")
        if not _wcaja_id:
            continue
        try:
            _wck = _cajas_map.get(int(_wcaja_id)) or _cajas_map.get(str(_wcaja_id))
        except (TypeError, ValueError):
            _wck = None
        if not _wck:
            continue
        if _wf < _ini_fecha_hist.get(_wck, date.min):
            continue
        _hist_total.setdefault(_wck, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += _wix_monto(_wo)

    # Totales del período seleccionado (_desde/_hasta) — misma lógica que _hist_total
    _periodo_total = {}
    for _c in cobros:
        _cf = _safe_date(_c.get("fecha"))
        if _cf == date.min or not (_desde <= _cf <= _hasta):
            continue
        for _cob in _c.get("cobranza", []):
            _ck = _caja_key(_cob.get("tipo_valor"), _cob.get("descripcion"))
            _periodo_total.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += float(_cob.get("monto") or 0)
    for _p in pagos:
        _pf = _safe_date(_p.get("fecha"))
        if _pf == date.min or not (_desde <= _pf <= _hasta):
            continue
        for _lin in _p.get("lineas_pago", []):
            _ck = _caja_key(_lin.get("tipo_valor"), _lin.get("descripcion"))
            _periodo_total.setdefault(_ck, {"Entradas": 0.0, "Salidas": 0.0})["Salidas"] += float(_lin.get("monto") or 0)
    for _tr in _transferencias:
        _trf = _safe_date(_tr.get("fecha"))
        if _trf == date.min or not (_desde <= _trf <= _hasta):
            continue
        _horig = (_tr.get("origen")  or {}).get("nombre") or _cajas_map.get(_tr.get("origen_id"),  "—")
        _hdest = (_tr.get("destino") or {}).get("nombre") or _cajas_map.get(_tr.get("destino_id"), "—")
        _htm   = float(_tr.get("monto") or 0)
        _periodo_total.setdefault(_horig, {"Entradas": 0.0, "Salidas": 0.0})["Salidas"]  += _htm
        _periodo_total.setdefault(_hdest, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += _htm
    for _wo in _wix_orders_mov:
        _oid = str(_wo.get("id") or "")
        _fp_raw = _fechas_pago_mov.get(_oid)
        if not _fp_raw:
            continue
        try:
            _wf = date.fromisoformat(str(_fp_raw))
        except Exception:
            continue
        if not (_desde <= _wf <= _hasta):
            continue
        _wcaja_id = _wo.get("caja_id")
        if not _wcaja_id:
            continue
        try:
            _wck = _cajas_map.get(int(_wcaja_id)) or _cajas_map.get(str(_wcaja_id))
        except (TypeError, ValueError):
            _wck = None
        if not _wck:
            continue
        _periodo_total.setdefault(_wck, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"] += _wix_monto(_wo)

    # ajustes desde la fecha de corte por caja (inclusive)
    _all_aj_sum = {}
    for _aj in _ajustes_todos:
        if _aj.get("tipo") != "ajuste":
            continue
        _cn = _cajas_map.get(_aj["caja_id"], "")
        if not _cn:
            continue
        _ajf = _safe_date(_aj.get("fecha"))
        if _ajf < _ini_fecha_hist.get(_cn, date.min):
            continue
        _all_aj_sum[_cn] = _all_aj_sum.get(_cn, 0.0) + float(_aj.get("monto") or 0)

    _total_saldo = sum(
        _inicial.get(_cn, 0.0) + _hist_total.get(_cn, {"Entradas": 0.0, "Salidas": 0.0})["Entradas"]
        - _hist_total.get(_cn, {"Entradas": 0.0, "Salidas": 0.0})["Salidas"]
        + _all_aj_sum.get(_cn, 0.0)
        for _cn in _inicial
    )
    _total_per_e = sum(_periodo_total.get(_cn, {"Entradas": 0.0})["Entradas"] for _cn in _inicial)
    _total_per_s = sum(_periodo_total.get(_cn, {"Salidas": 0.0})["Salidas"]   for _cn in _inicial)
    st.subheader("Total general")
    _k1, _k2, _k3 = st.columns(3)
    def _metric_card_total(col, label, value, color):
        col.markdown(
            f'<div style="padding:4px 0;margin-bottom:14px;"><p style="margin:0;font-size:0.8rem;font-weight:600;color:#777;">{label}</p><p style="margin:2px 0 0 0;font-size:1.25rem;font-weight:700;color:{color};">{value}</p></div>',
            unsafe_allow_html=True,
        )
    _metric_card_total(_k1, "Saldo",    _fmt_monto(_total_saldo), "#1a73e8")
    _metric_card_total(_k2, "Entradas", _fmt_monto(_total_per_e),  "#2e7d32")
    _metric_card_total(_k3, "Salidas",  _fmt_monto(_total_per_s),  "#c62828")

    if not _por_caja:
        st.info("No hay movimientos en el período seleccionado.")
        return

    st.divider()
    for _caja in sorted(_inicial):
        _ht = _hist_total.get(_caja, {"Entradas": 0.0, "Salidas": 0.0})
        _ini  = _inicial.get(_caja, 0.0)
        _saldo_actual = _ini + _ht["Entradas"] - _ht["Salidas"] + _all_aj_sum.get(_caja, 0.0)
        st.subheader(_caja)
        _m1, _m2, _m3 = st.columns(3)
        def _metric_card(col, label, value, color):
            col.markdown(
                f'<div style="padding:4px 0;margin-bottom:14px;"><p style="margin:0;font-size:0.8rem;font-weight:600;color:#777;">{label}</p><p style="margin:2px 0 0 0;font-size:1.25rem;font-weight:700;color:{color};">{value}</p></div>',
                unsafe_allow_html=True,
            )
        _pt = _periodo_total.get(_caja, {"Entradas": 0.0, "Salidas": 0.0})
        _metric_card(_m1, "Saldo actual", _fmt_monto(_saldo_actual), "#1a73e8")
        _metric_card(_m2, "Entradas",     _fmt_monto(_pt['Entradas']), "#2e7d32")
        _metric_card(_m3, "Salidas",      _fmt_monto(_pt['Salidas']), "#c62828")

        _v = _por_caja.get(_caja, {"detalle": []})
        _det = sorted(_v["detalle"], key=lambda r: r["Fecha"], reverse=True)
        _cfg_fecha = st.column_config.DateColumn("Fecha", format="DD/MM/YYYY")
        _cfg_monto = st.column_config.NumberColumn("Monto", format="$ %,.0f")

        _entradas    = [r for r in _det if r.get("Tipo") == "Entrada"]
        _sal_compras = [r for r in _det if r.get("Tipo") == "Salida" and r.get("Cat.") == "Compra" and not r.get("_parcial")]
        _sal_compras_parc = [r for r in _det if r.get("Tipo") == "Salida" and r.get("Cat.") == "Compra" and r.get("_parcial")]
        _sal_gastos  = [r for r in _det if r.get("Tipo") == "Salida" and r.get("Cat.") == "Gasto" and not r.get("_parcial")]
        _sal_gastos_parc = [r for r in _det if r.get("Tipo") == "Salida" and r.get("Cat.") == "Gasto" and r.get("_parcial")]
        _sal_transf  = [r for r in _det if r.get("Cat.") == "Transferencia" and r.get("Tipo") == "Salida"]
        _ent_transf  = [r for r in _det if r.get("Cat.") == "Transferencia" and r.get("Tipo") == "Entrada"]
        _sal_otros   = [r for r in _det if r.get("Tipo") == "Salida" and r.get("Cat.") not in ("Compra", "Gasto", "Transferencia")]

        _entradas_real      = [r for r in _entradas if r.get("Cat.") != "Transferencia" and not r.get("_parcial")]
        _entradas_real_parc = [r for r in _entradas if r.get("Cat.") != "Transferencia" and r.get("_parcial")]

        # Dedup cobros: un cobro puede tener múltiples cobranza lines en la misma caja
        def _dedup_cobros(rows):
            if not rows:
                return pd.DataFrame()
            _df = pd.DataFrame(rows)
            _agg = {"Monto": "sum", "Fecha": "first", "Cliente": "first",
                    "Facturas": lambda x: ", ".join(dict.fromkeys(v for v in x if str(v).strip())),
                    "Cheque": lambda x: ", ".join(v for v in x if str(v).strip())}
            for _ec in ["Total factura", "Cobrado total", "Saldo"]:
                if _ec in _df.columns:
                    _agg[_ec] = "first"
            return _df.groupby("Cobro #", sort=False).agg(_agg).reset_index()

        _df_ent = _dedup_cobros(_entradas_real + _entradas_real_parc)
        if not _df_ent.empty:
            _tot_ent = _df_ent["Monto"].sum()
            with st.expander(f"Entradas ({len(_df_ent)}) — {_fmt_monto(_tot_ent)}"):
                st.dataframe(
                    _df_ent[["Cobro #", "Fecha", "Cliente", "Monto"]],
                    use_container_width=True, hide_index=True,
                    column_config={"Fecha": _cfg_fecha, "Monto": _cfg_monto},
                )
        if _ent_transf:
            _tot_et = sum(r["Monto"] for r in _ent_transf)
            with st.expander(f"Entradas — Transferencias ({len(_ent_transf)}) — {_fmt_monto(_tot_et)}"):
                st.dataframe(
                    pd.DataFrame(_ent_transf)[["Fecha", "Desde", "Hacia", "Concepto", "Monto"]],
                    use_container_width=True, hide_index=True,
                    column_config={"Fecha": _cfg_fecha, "Monto": _cfg_monto},
                )
        if _sal_transf:
            _tot_st = sum(r["Monto"] for r in _sal_transf)
            with st.expander(f"Salidas — Transferencias ({len(_sal_transf)}) — {_fmt_monto(_tot_st)}"):
                st.dataframe(
                    pd.DataFrame(_sal_transf)[["Fecha", "Desde", "Hacia", "Concepto", "Monto"]],
                    use_container_width=True, hide_index=True,
                    column_config={"Fecha": _cfg_fecha, "Monto": _cfg_monto},
                )
        for _titulo, _rows in [
            ("Salidas — Compras", _sal_compras + _sal_compras_parc),
            ("Salidas — Gastos",  _sal_gastos  + _sal_gastos_parc),
            ("Salidas — Otros",   _sal_otros),
        ]:
            if _rows:
                _df_rows = pd.DataFrame(_rows)
                _agg_dict = {"Monto": "sum", "Fecha": "first", "Proveedor": "first",
                             "Cheque": lambda x: ", ".join(v for v in x if str(v).strip())}
                _df_rows = _df_rows.groupby("Pago #", sort=False).agg(_agg_dict).reset_index()
                _tot_rows = _df_rows["Monto"].sum()
                _tiene_cheque = _df_rows["Cheque"].astype(str).str.strip().ne("").any()
                _cols_sel = ["Pago #", "Fecha", "Proveedor", "Monto"]
                if _tiene_cheque:
                    _cols_sel.insert(3, "Cheque")
                with st.expander(f"{_titulo} ({len(_df_rows)}) — {_fmt_monto(_tot_rows)}"):
                    st.dataframe(
                        _df_rows[_cols_sel],
                        use_container_width=True, hide_index=True,
                        column_config={"Fecha": _cfg_fecha, "Monto": _cfg_monto},
                    )
        _aj_caja_periodo = _ajustes_periodo.get(_caja, [])
        if _aj_caja_periodo:
            _aj_sum = sum(float(_aj.get("monto") or 0) for _aj in _aj_caja_periodo)
            with st.expander(f"Ajustes ({len(_aj_caja_periodo)}) — {_fmt_monto(_aj_sum)}"):
                _aj_rows = [{"Fecha": _aj.get("fecha"), "Monto": float(_aj.get("monto") or 0), "Nota": _aj.get("nota") or ""} for _aj in _aj_caja_periodo]
                st.dataframe(pd.DataFrame(_aj_rows), use_container_width=True, hide_index=True,
                    column_config={"Fecha": _cfg_fecha, "Monto": st.column_config.NumberColumn("Monto", format="$ %.2f")})
        st.divider()


_cfg_monto = st.column_config.NumberColumn("Total", format="$ %,.2f")

def _bal_metric(col, label, value, color, sub=None):
    _sub = f'<p style="margin:0;font-size:0.75rem;color:#999;">{sub}</p>' if sub else ""
    col.markdown(
        f'<div style="padding:4px 0;margin-bottom:14px;"><p style="margin:0;font-size:0.8rem;font-weight:600;color:#777;">{label}</p><p style="margin:2px 0 0 0;font-size:1.25rem;font-weight:700;color:{color};">{value}</p>{_sub}</div>',
        unsafe_allow_html=True,
    )

def _parse_wix_total(v):
    try:
        import re as _re
        s = _re.sub(r"[^\d.,]", "", str(v or "0"))
        if not s:
            return 0.0
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", "." if (len(s) - s.rfind(",") - 1) <= 2 else "")
        return float(s)
    except (ValueError, TypeError):
        return 0.0

def _wix_monto(p):
    v = float(p.get("total_amount") or 0)
    if v == 0:
        v = _parse_wix_total((p.get("priceSummary") or {}).get("total", {}).get("formattedAmount"))
    return v

def _pesos(v):
    return f"{float(v or 0):,.2f}"


_cfg_bal = db.cargar_config()

if _sub_pendientes:
    with _sub_pendientes:
        # ── Rango de fechas propio ─────────────────────────────────────────
        try:
            _pend_desde_def = date.fromisoformat(_cfg_bal.get("pend_desde", ""))
        except Exception:
            _pend_desde_def = date(2020, 1, 1)
        try:
            _pend_hasta_def = date.fromisoformat(_cfg_bal.get("pend_hasta", ""))
        except Exception:
            _pend_hasta_def = date.today()

        with st.form("form_pend_fechas", border=False):
            _fc1, _fc2 = st.columns(2)
            with _fc1:
                _pend_desde = st.date_input("Desde", value=_pend_desde_def, key="pend_desde_in", format="DD/MM/YYYY")
            with _fc2:
                _pend_hasta = st.date_input("Hasta", value=_pend_hasta_def, key="pend_hasta_in", format="DD/MM/YYYY")
            _btn_pend = st.form_submit_button("🔄 Calcular", type="primary", use_container_width=True)
        if _btn_pend:
            db.guardar_config({"pend_desde": str(_pend_desde), "pend_hasta": str(_pend_hasta)})

        def _pend_en_rango(fecha_str):
            try:
                f = pd.to_datetime(str(fecha_str or "")).date()
                return _pend_desde <= f <= _pend_hasta
            except Exception:
                return False

        # Monto pagado por comprobante (para distinguir Parcial vs Pendiente)
        _pend_pagado_por_comp = {}
        for _pag in pagos_bal:
            for _imp in (_pag.get("imputaciones") or []):
                _nro = str(_imp.get("nro_comprobante") or "")
                if _nro:
                    _pend_pagado_por_comp[_nro] = _pend_pagado_por_comp.get(_nro, 0.0) + float(_imp.get("monto_imputado") or 0)

        def _pend_pagado_c(c):
            return min(float(c.get("total") or 0), _pend_pagado_por_comp.get(str(c.get("nro_comprobante") or ""), 0.0))
        def _pend_saldo_c(c):
            return max(0.0, float(c.get("total") or 0) - _pend_pagado_c(c))
        def _pend_pagado_g(g):
            return min(float(g.get("total") or 0), _pend_pagado_por_comp.get(str(g.get("nro_comprobante") or ""), 0.0))
        def _pend_saldo_g(g):
            return max(0.0, float(g.get("total") or 0) - _pend_pagado_g(g))

        # Monto cobrado real por factura (via imputaciones de cobros)
        _pend_cobrado_por_fac = {}
        for _cob in cobros_bal:
            for _imp in (_cob.get("imputaciones") or []):
                _fid = str(_imp.get("id_comp_venta") or "")
                if _fid:
                    _pend_cobrado_por_fac[_fid] = _pend_cobrado_por_fac.get(_fid, 0.0) + float(_imp.get("monto_imputado") or 0)

        def _pend_cobrado_f(f):
            return min(float(f.get("total") or 0), _pend_cobrado_por_fac.get(str(f.get("id") or ""), 0.0))
        def _pend_saldo_f(f):
            return max(0.0, float(f.get("total") or 0) - _pend_cobrado_f(f))

        # helpers de visualización
        def _pend_big(label, valor, color):
            st.markdown(
                f'<p style="margin:24px 0 2px 0;font-size:1rem;font-weight:700;color:#1a1a1a;">{label}</p>'
                f'<p style="margin:0 0 6px 0;font-size:1.5rem;font-weight:700;color:{color};">$ {valor}</p>',
                unsafe_allow_html=True,
            )

        # ── PAGOS PENDIENTES (lo que debemos) ──────────────────────────────
        _comp_pend_hist = [c for c in comprobantes_bal if c.get("pago_pendiente") and str(c.get("estado") or "").upper() != "ANULADA" and _pend_en_rango(c.get("fecha"))]
        _gas_pend_hist  = [g for g in gastos_bal       if g.get("pago_pendiente") and str(g.get("estado") or "").upper() != "ANULADA" and _pend_en_rango(g.get("fecha"))]
        _total_pend_comp = sum(_pend_saldo_c(c) for c in _comp_pend_hist)
        _total_pend_gas  = sum(_pend_saldo_g(g) for g in _gas_pend_hist)
        _total_pend      = _total_pend_comp + _total_pend_gas

        st.subheader(f"A pagar a proveedores — $ {_pesos(_total_pend)}")

        # Compras: agrupar por Proveedor → Parcial/Pendiente adentro
        _pend_big("Compras", _pesos(_total_pend_comp), "#c62828")
        if not _comp_pend_hist:
            st.caption("Sin compras pendientes en el rango seleccionado.")
        else:
            _by_prov_comp = {}
            for _c in _comp_pend_hist:
                _by_prov_comp.setdefault(_c.get("proveedor") or "—", []).append(_c)
            for _prov, _pi in sorted(_by_prov_comp.items(), key=lambda kv: sum(_pend_saldo_c(c) for c in kv[1]), reverse=True):
                _ptot = sum(_pend_saldo_c(c) for c in _pi)
                with st.expander(f"{_prov} ({len(_pi)}) — $ {_pesos(_ptot)}"):
                    _cp = [c for c in _pi if _pend_pagado_c(c) > 0]
                    _cn = [c for c in _pi if _pend_pagado_c(c) == 0]
                    for _lbl, _lst in [("Parciales", _cp), ("Pendientes", _cn)]:
                        if not _lst:
                            continue
                        _ltot = sum(_pend_saldo_c(c) for c in _lst)
                        with st.expander(f"{_lbl} ({len(_lst)}) — $ {_pesos(_ltot)}"):
                            _rows = [{
                                "Fecha":       _fmt_fecha(_c.get("fecha")),
                                "Comprobante": _c.get("nro_comprobante") or "—",
                                "Total":       float(_c.get("total") or 0),
                                **( {"Pagado": _pend_pagado_c(_c), "Saldo": _pend_saldo_c(_c)} if _lbl == "Parciales" else {} ),
                            } for _c in sorted(_lst, key=lambda x: str(x.get("fecha") or ""), reverse=True)]
                            _ccfg = {"Total": st.column_config.NumberColumn("Total", format="$ %,.2f")}
                            if _lbl == "Parciales":
                                _ccfg["Pagado"] = st.column_config.NumberColumn("Pagado", format="$ %,.2f")
                                _ccfg["Saldo"]  = st.column_config.NumberColumn("Saldo",  format="$ %,.2f")
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True, column_config=_ccfg)

        # Gastos: agrupar por Proveedor → Parcial/Pendiente adentro
        _pend_big("Gastos", _pesos(_total_pend_gas), "#c62828")
        if not _gas_pend_hist:
            st.caption("Sin gastos pendientes en el rango seleccionado.")
        else:
            _by_prov_gas = {}
            for _g in _gas_pend_hist:
                _by_prov_gas.setdefault(_g.get("proveedor") or "—", []).append(_g)
            for _prov, _pi in sorted(_by_prov_gas.items(), key=lambda kv: sum(_pend_saldo_g(g) for g in kv[1]), reverse=True):
                _ptot = sum(_pend_saldo_g(g) for g in _pi)
                with st.expander(f"{_prov} ({len(_pi)}) — $ {_pesos(_ptot)}"):
                    _gp = [g for g in _pi if _pend_pagado_g(g) > 0]
                    _gn = [g for g in _pi if _pend_pagado_g(g) == 0]
                    for _lbl, _lst in [("Parciales", _gp), ("Pendientes", _gn)]:
                        if not _lst:
                            continue
                        _ltot = sum(_pend_saldo_g(g) for g in _lst)
                        with st.expander(f"{_lbl} ({len(_lst)}) — $ {_pesos(_ltot)}"):
                            _rows = [{
                                "Fecha":       _fmt_fecha(_g.get("fecha")),
                                "Rubro":       " / ".join(filter(None, [_g.get("rubro_nombre"), _g.get("sub_rubro_nombre")])) or _g.get("gasto") or "—",
                                "Comprobante": _g.get("nro_comprobante") or "—",
                                "Total":       float(_g.get("total") or 0),
                                **( {"Pagado": _pend_pagado_g(_g), "Saldo": _pend_saldo_g(_g)} if _lbl == "Parciales" else {} ),
                            } for _g in sorted(_lst, key=lambda x: str(x.get("fecha") or ""), reverse=True)]
                            _gcfg = {"Total": st.column_config.NumberColumn("Total", format="$ %,.2f")}
                            if _lbl == "Parciales":
                                _gcfg["Pagado"] = st.column_config.NumberColumn("Pagado", format="$ %,.2f")
                                _gcfg["Saldo"]  = st.column_config.NumberColumn("Saldo",  format="$ %,.2f")
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True, column_config=_gcfg)

        st.divider()

        # ── DEUDORES (lo que nos deben) ────────────────────────────────────
        _fac_deud  = [f for f in facturas_bal    if str(f.get("anulada","N")).upper() != "S" and _pend_saldo_f(f) > 0 and _pend_en_rango(f.get("fecha_comp"))]
        _wix_deud  = [p for p in pedidos_wix_bal if str(p.get("paymentStatus") or "").upper() != "PAID" and str(p.get("status") or "").upper() != "CANCELED" and _pend_en_rango(p.get("createdDate"))]
        _total_deud_dux = sum(_pend_saldo_f(f) for f in _fac_deud)
        _total_deud_wix = sum(_wix_monto(p) for p in _wix_deud)
        _total_deud     = _total_deud_dux + _total_deud_wix

        st.subheader(f"A cobrar a clientes — $ {_pesos(_total_deud)}")

        # DUX: agrupar por Cliente → Parcial/Pendiente adentro
        _pend_big("DUX", _pesos(_total_deud_dux), "#c62828")
        if not _fac_deud:
            st.caption("Sin facturas pendientes de cobro en el rango seleccionado.")
        else:
            _by_cli_dux = {}
            for _f in _fac_deud:
                _cli = f"{_f.get('apellido_razon_soc','') or ''} {_f.get('nombre','') or ''}".strip() or "—"
                _by_cli_dux.setdefault(_cli, []).append(_f)
            for _cli, _ci in sorted(_by_cli_dux.items(), key=lambda kv: sum(_pend_saldo_f(f) for f in kv[1]), reverse=True):
                _ctot = sum(_pend_saldo_f(f) for f in _ci)
                with st.expander(f"{_cli} ({len(_ci)}) — $ {_pesos(_ctot)}"):
                    _fp = [f for f in _ci if _pend_cobrado_f(f) > 0]
                    _fn = [f for f in _ci if _pend_cobrado_f(f) == 0]
                    for _lbl, _lst in [("Parciales", _fp), ("Pendientes", _fn)]:
                        if not _lst:
                            continue
                        _ltot = sum(_pend_saldo_f(f) for f in _lst)
                        with st.expander(f"{_lbl} ({len(_lst)}) — $ {_pesos(_ltot)}"):
                            _rows = [{
                                "Fecha":       _fmt_fecha(_f.get("fecha_comp")),
                                "Comprobante": f"{_f.get('tipo_comp','')} {_f.get('letra_comp','')} {_f.get('nro_pto_vta','')}-{_f.get('nro_comp','')}".strip(),
                                "Total":       float(_f.get("total") or 0),
                                **( {"Cobrado": _pend_cobrado_f(_f), "Saldo": _pend_saldo_f(_f)} if _lbl == "Parciales" else {} ),
                                "PDF":         _f.get("url_factura") or None,
                            } for _f in sorted(_lst, key=lambda x: str(x.get("fecha_comp") or ""), reverse=True)]
                            _fcfg = {
                                "Total": st.column_config.NumberColumn("Total", format="$ %,.2f"),
                                "PDF":   st.column_config.LinkColumn("PDF", display_text="Ver PDF"),
                            }
                            if _lbl == "Parciales":
                                _fcfg["Cobrado"] = st.column_config.NumberColumn("Cobrado", format="$ %,.2f")
                                _fcfg["Saldo"]   = st.column_config.NumberColumn("Saldo",   format="$ %,.2f")
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True, column_config=_fcfg)

        # Wix: agrupar por Cliente (no hay parciales en Wix)
        _pend_big("Wix", _pesos(_total_deud_wix), "#c62828")
        if not _wix_deud:
            st.caption("Sin pedidos pendientes de cobro en el rango seleccionado.")
        else:
            _by_cli_wix = {}
            for _p in _wix_deud:
                _bi = (_p.get("billingInfo") or {}).get("contactDetails") or {}
                _cli = f"{_bi.get('firstName','') or ''} {_bi.get('lastName','') or ''}".strip() or "—"
                _by_cli_wix.setdefault(_cli, []).append(_p)
            for _cli, _citems in sorted(_by_cli_wix.items(), key=lambda kv: sum(_wix_monto(p) for p in kv[1]), reverse=True):
                _ctot = sum(_wix_monto(p) for p in _citems)
                with st.expander(f"{_cli} ({len(_citems)}) — $ {_pesos(_ctot)}"):
                    _rows = [{
                        "Fecha":    _fmt_fecha(_p.get("createdDate")),
                        "Pedido #": _p.get("number") or _p.get("id") or "—",
                        "Total":    _wix_monto(_p),
                    } for _p in sorted(_citems, key=lambda x: str(x.get("createdDate") or ""), reverse=True)]
                    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                 column_config={"Total": _cfg_monto})

if _sub_resumen:
    with _sub_resumen:
        _hoy_bal = date.today()
        try:
            _bal_desde_def = date.fromisoformat(_cfg_bal.get("bal_desde", ""))
        except Exception:
            _bal_desde_def = _hoy_bal.replace(day=1)
        try:
            _bal_hasta_def = date.fromisoformat(_cfg_bal.get("bal_hasta", ""))
        except Exception:
            _bal_hasta_def = _hoy_bal

        with st.form("form_bal_fechas", border=False):
            _bc1, _bc2 = st.columns(2)
            with _bc1:
                bal_desde = st.date_input("Desde", value=_bal_desde_def, key="bal_desde_in", format="DD/MM/YYYY")
            with _bc2:
                bal_hasta = st.date_input("Hasta", value=_bal_hasta_def, key="bal_hasta_in", format="DD/MM/YYYY")
            _btn_bal = st.form_submit_button("Calcular", type="primary", use_container_width=True)
        if _btn_bal:
            db.guardar_config({"bal_desde": str(bal_desde), "bal_hasta": str(bal_hasta)})

        def _en_rango(fecha_str):
            try:
                f = pd.to_datetime(str(fecha_str or "")).date()
                return bal_desde <= f <= bal_hasta
            except Exception:
                return False

        # Filtrar por rango
        facturas_vig  = [f for f in facturas_bal if _en_rango(f.get("fecha_comp")) and str(f.get("anulada","N")).upper() != "S"]
        facturas_anul = [f for f in facturas_bal if _en_rango(f.get("fecha_comp")) and str(f.get("anulada","N")).upper() == "S"]
        ped_wix_f     = [p for p in pedidos_wix_bal if _en_rango(p.get("createdDate"))]
        if not compras_bal.empty:
            compras_f = compras_bal[compras_bal["fecha"].apply(lambda v: _en_rango(str(v or "")))].copy()
            compras_f["subtotal"] = pd.to_numeric(compras_f["cantidad"], errors="coerce").fillna(0) * pd.to_numeric(compras_f["precio"], errors="coerce").fillna(0)
        else:
            compras_f = pd.DataFrame()
        comprobantes_f = [c for c in comprobantes_bal if _en_rango(str(c.get("fecha") or ""))]
        gastos_f = [g for g in gastos_bal if _en_rango(g.get("fecha"))]

        # Monto cobrado real por factura (via imputaciones de cobros)
        _cobrado_por_fac = {}
        for _cob in cobros_bal:
            for _imp in (_cob.get("imputaciones") or []):
                _fid = str(_imp.get("id_comp_venta") or "")
                if _fid:
                    _cobrado_por_fac[_fid] = _cobrado_por_fac.get(_fid, 0.0) + float(_imp.get("monto_imputado") or 0)

        # Monto pagado real por comprobante/gasto (via imputaciones de pagos a proveedores)
        _pagado_por_comp = {}
        for _pag in pagos_bal:
            for _imp in (_pag.get("imputaciones") or []):
                _nro = str(_imp.get("nro_comprobante") or "")
                if _nro:
                    _pagado_por_comp[_nro] = _pagado_por_comp.get(_nro, 0.0) + float(_imp.get("monto_imputado") or 0)

        # Categorizar facturas DUX
        fac_cobradas   = [f for f in facturas_vig if f.get("con_cobro") and _cobrado_por_fac.get(str(f.get("id") or ""), 0.0) >= float(f.get("total") or 0)]
        fac_parciales  = [f for f in facturas_vig if f.get("con_cobro") and _cobrado_por_fac.get(str(f.get("id") or ""), 0.0) < float(f.get("total") or 0)]
        fac_pendientes = [f for f in facturas_vig if not f.get("con_cobro")]

        # Categorizar Wix
        wix_cobradas      = [p for p in ped_wix_f if str(p.get("paymentStatus") or "").upper() == "PAID" and str(p.get("status") or "").upper() != "CANCELED"]
        wix_anulados      = [p for p in ped_wix_f if str(p.get("status") or "").upper() == "CANCELED"]
        wix_pendientes    = [p for p in ped_wix_f if str(p.get("fulfillmentStatus") or "").upper() == "FULFILLED" and str(p.get("paymentStatus") or "").upper() != "PAID" and str(p.get("status") or "").upper() != "CANCELED"]
        wix_no_entregados = [p for p in ped_wix_f if str(p.get("fulfillmentStatus") or "").upper() == "NOT_FULFILLED" and str(p.get("status") or "").upper() != "CANCELED"]

        # Totales — cobrado y pendiente calculados con monto_imputado real
        total_facturas    = sum(float(f.get("total") or 0) for f in facturas_vig)
        total_fac_cobr    = sum(
            min(float(f.get("total") or 0), _cobrado_por_fac.get(str(f.get("id") or ""), 0.0))
            for f in facturas_vig
        )
        total_fac_pend    = total_facturas - total_fac_cobr
        total_fac_anul    = sum(float(f.get("total") or 0) for f in facturas_anul)
        total_wix_cobr    = sum(_wix_monto(p) for p in wix_cobradas)
        total_wix_pend    = sum(_wix_monto(p) for p in wix_pendientes)
        total_wix_anul    = sum(_wix_monto(p) for p in wix_anulados)
        total_wix         = total_wix_cobr + total_wix_pend
        # Categorizar compras
        def _pagado_comp(c):
            return min(float(c.get("total") or 0), _pagado_por_comp.get(str(c.get("nro_comprobante") or ""), 0.0))
        def _saldo_comp(c):
            return max(0.0, float(c.get("total") or 0) - _pagado_comp(c))

        comp_pagadas    = [c for c in comprobantes_f if not c.get("pago_pendiente") and str(c.get("estado") or "").upper() != "ANULADA"]
        comp_parciales  = [c for c in comprobantes_f if c.get("pago_pendiente") and _pagado_comp(c) > 0 and str(c.get("estado") or "").upper() != "ANULADA"]
        comp_pendientes = [c for c in comprobantes_f if c.get("pago_pendiente") and _pagado_comp(c) == 0 and str(c.get("estado") or "").upper() != "ANULADA"]
        comp_anuladas   = [c for c in comprobantes_f if str(c.get("estado") or "").upper() == "ANULADA"]

        # Categorizar gastos
        def _pagado_gasto(g):
            return min(float(g.get("total") or 0), _pagado_por_comp.get(str(g.get("nro_comprobante") or ""), 0.0))
        def _saldo_gasto(g):
            return max(0.0, float(g.get("total") or 0) - _pagado_gasto(g))

        gas_pagados    = [g for g in gastos_f if not g.get("pago_pendiente") and str(g.get("estado") or "").upper() != "ANULADA"]
        gas_parciales  = [g for g in gastos_f if g.get("pago_pendiente") and _pagado_gasto(g) > 0 and str(g.get("estado") or "").upper() != "ANULADA"]
        gas_pendientes = [g for g in gastos_f if g.get("pago_pendiente") and _pagado_gasto(g) == 0 and str(g.get("estado") or "").upper() != "ANULADA"]
        gas_anulados   = [g for g in gastos_f if str(g.get("estado") or "").upper() == "ANULADA"]

        total_compras     = sum(float(c.get("total") or 0) for c in comp_pagadas + comp_parciales + comp_pendientes)
        total_gastos      = sum(float(g.get("total") or 0) for g in gas_pagados + gas_parciales + gas_pendientes)

        total_ing_cobr  = total_fac_cobr + total_wix_cobr
        total_ing_pend  = total_fac_pend + total_wix_pend
        total_ing_anul  = total_fac_anul + total_wix_anul

        total_comp_pag  = sum(float(c.get("total") or 0) for c in comp_pagadas) + sum(_pagado_comp(c) for c in comp_parciales)
        total_comp_pend = sum(_saldo_comp(c) for c in comp_parciales) + sum(float(c.get("total") or 0) for c in comp_pendientes)
        total_comp_anul = sum(float(c.get("total") or 0) for c in comp_anuladas)
        total_gas_pag   = sum(float(g.get("total") or 0) for g in gas_pagados) + sum(_pagado_gasto(g) for g in gas_parciales)
        total_gas_pend  = sum(_saldo_gasto(g) for g in gas_parciales) + sum(float(g.get("total") or 0) for g in gas_pendientes)
        total_gas_anul  = sum(float(g.get("total") or 0) for g in gas_anulados)
        total_egr_pag   = total_comp_pag + total_gas_pag
        total_egr_pend  = total_comp_pend + total_gas_pend
        total_egr_anul  = total_comp_anul + total_gas_anul

        total_ingresos = total_facturas + total_wix
        total_egresos  = total_compras + total_gastos
        resultado      = total_ingresos - total_egresos

        # ── INGRESOS ────────────────────────────────────────────────────────────
        st.divider()
        def _metric_cell(label, value, color):
            return f"<div><p style='margin:0;font-size:0.8rem;font-weight:600;color:#777'>{label}</p><p style='margin:2px 0 0;font-size:1.25rem;font-weight:700;color:{color}'>{value}</p></div>"
        st.markdown(f"""
<div style='background:#eef2f7;border-radius:10px;padding:16px 24px;margin-bottom:8px'>
  <h2 style='text-align:center;margin:0 0 14px 0'>Ingresos</h2>
  <div style='display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:16px'>
    {_metric_cell("Facturado", f"$ {_pesos(total_ingresos)}", "#1a1a1a")}
    {_metric_cell("Cobrado",   f"$ {_pesos(total_ing_cobr)}", "#2e7d32")}
    {_metric_cell("Pendiente", f"$ {_pesos(total_ing_pend)}", "#c62828")}
    {_metric_cell("Anulado",   f"$ {_pesos(total_ing_anul)}", "#757575")}
  </div>
</div>""", unsafe_allow_html=True)

        # Facturas DUX
        st.markdown(f"#### DUX · {len(facturas_vig)} facturas")
        _c1, _c2, _c3, _c4 = st.columns(4)
        _bal_metric(_c1, "Facturado",  f"$ {_pesos(total_facturas)}",  "#1a1a1a")
        _bal_metric(_c2, "Cobrado",    f"$ {_pesos(total_fac_cobr)}",  "#2e7d32")
        _bal_metric(_c3, "Pendiente",  f"$ {_pesos(total_fac_pend)}",  "#c62828")
        _bal_metric(_c4, "Anulado",    f"$ {_pesos(total_fac_anul)}",  "#757575")
        def _fac_saldo(f):
            _tot = float(f.get("total") or 0)
            _cob = _cobrado_por_fac.get(str(f.get("id") or ""), 0.0)
            return max(0.0, _tot - _cob)

        def _fac_cobrado(f):
            _tot = float(f.get("total") or 0)
            return min(_tot, _cobrado_por_fac.get(str(f.get("id") or ""), 0.0))

        for _label, _lista, _lbl_fn in [
            ("Cobrado",  fac_cobradas,   _fac_cobrado),
            ("Parcial",  fac_parciales,  _fac_cobrado),
            ("Pendiente", fac_pendientes, _fac_saldo),
            ("Anulado",  facturas_anul,   lambda f: float(f.get("total") or 0)),
        ]:
            if _lista:
                _lbl_total = sum(_lbl_fn(f) for f in _lista)
                with st.expander(f"{_label} ({len(_lista)}) — $ {_pesos(_lbl_total)}"):
                    _by_cli = {}
                    for _f in _lista:
                        _k = f"{_f.get('apellido_razon_soc','') or ''} {_f.get('nombre','') or ''}".strip() or "—"
                        _by_cli.setdefault(_k, []).append(_f)
                    for _cli, _fitems in sorted(_by_cli.items()):
                        _ctot = sum(_lbl_fn(f) for f in _fitems)
                        with st.expander(f"{_cli} — {len(_fitems)} factura{'s' if len(_fitems)!=1 else ''} — $ {_pesos(_ctot)}"):
                            _rows = []
                            for _f in sorted(_fitems, key=lambda x: str(x.get("fecha_comp") or ""), reverse=True):
                                _ftot = float(_f.get("total") or 0)
                                _fcob = _cobrado_por_fac.get(str(_f.get("id") or ""), 0.0)
                                _fsal = max(0.0, _ftot - _fcob)
                                _row = {
                                    "Fecha":       _fmt_fecha(_f.get("fecha_comp")),
                                    "Comprobante": f"{_f.get('tipo_comp','')} {_f.get('letra_comp','')} {_f.get('nro_pto_vta','')}-{_f.get('nro_comp','')}".strip(),
                                    "Total":       _ftot,
                                    "Cobrado":     _fcob,
                                }
                                if 0 < _fcob < _ftot:
                                    _row["Comprobante"] += " (parcial)"
                                _rows.append(_row)
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                         column_config={
                                             "Total":   st.column_config.NumberColumn("Total",   format="$ %,.2f"),
                                             "Cobrado": st.column_config.NumberColumn("Cobrado", format="$ %,.2f"),
                                         })

        # Wix
        _wix_fin_count = len(wix_cobradas) + len(wix_pendientes)
        st.markdown(f"#### Wix · {_wix_fin_count} pedidos")
        _w1, _w2, _w3, _w4 = st.columns(4)
        _bal_metric(_w1, "Facturado",  f"$ {_pesos(total_wix)}",      "#1a1a1a")
        _bal_metric(_w2, "Cobrado",    f"$ {_pesos(total_wix_cobr)}",  "#2e7d32")
        _bal_metric(_w3, "Pendiente",  f"$ {_pesos(total_wix_pend)}",  "#c62828")
        _bal_metric(_w4, "Anulado",    f"$ {_pesos(total_wix_anul)}",  "#757575")

        for _label, _lista in [
            ("Cobrado",    wix_cobradas),
            ("Pendiente", wix_pendientes),
            ("Anulado",    wix_anulados),
        ]:
            if _lista:
                with st.expander(f"{_label} ({len(_lista)}) — $ {_pesos(sum(_wix_monto(p) for p in _lista))}"):
                    _by_cli = {}
                    for _p in _lista:
                        _bi = (_p.get("billingInfo") or {}).get("contactDetails") or {}
                        _k = f"{_bi.get('firstName','') or ''} {_bi.get('lastName','') or ''}".strip() or "—"
                        _by_cli.setdefault(_k, []).append(_p)
                    for _cli, _pitems in sorted(_by_cli.items()):
                        _ctot = sum(_wix_monto(_p) for _p in _pitems)
                        with st.expander(f"{_cli} — {len(_pitems)} pedido{'s' if len(_pitems)!=1 else ''} — $ {_pesos(_ctot)}"):
                            _rows = [{
                                "Fecha":    _fmt_fecha(_p.get("createdDate")),
                                "Pedido #": _p.get("number") or _p.get("id") or "—",
                                "Total":    _wix_monto(_p),
                            } for _p in sorted(_pitems, key=lambda x: str(x.get("createdDate") or ""), reverse=True)]
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                         column_config={"Total": _cfg_monto})

        # ── EGRESOS ─────────────────────────────────────────────────────────────
        st.divider()
        st.markdown(f"""
<div style='background:#eef2f7;border-radius:10px;padding:16px 24px;margin-bottom:8px'>
  <h2 style='text-align:center;margin:0 0 14px 0'>Egresos</h2>
  <div style='display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:16px'>
    {_metric_cell("Total",     f"$ {_pesos(total_egresos)}", "#1a1a1a")}
    {_metric_cell("Pagado",    f"$ {_pesos(total_egr_pag)}", "#2e7d32")}
    {_metric_cell("Pendiente", f"$ {_pesos(total_egr_pend)}", "#c62828")}
    {_metric_cell("Anulado",   f"$ {_pesos(total_egr_anul)}", "#757575")}
  </div>
</div>""", unsafe_allow_html=True)

        # Compras
        st.markdown(f"#### Compras · {len(comp_pagadas) + len(comp_parciales) + len(comp_pendientes)} comprobantes")
        _ec1, _ec2, _ec3, _ec4 = st.columns(4)
        _bal_metric(_ec1, "Total",     f"$ {_pesos(total_compras)}",    "#1a1a1a")
        _bal_metric(_ec2, "Pagado",    f"$ {_pesos(total_comp_pag)}",   "#2e7d32")
        _bal_metric(_ec3, "Pendiente", f"$ {_pesos(total_comp_pend)}",  "#c62828")
        _bal_metric(_ec4, "Anulado",   f"$ {_pesos(total_comp_anul)}",  "#757575")
        for _label, _lista, _tot_fn in [
            ("Pagado",    comp_pagadas,    lambda c: float(c.get("total") or 0)),
            ("Parcial",   comp_parciales,  _pagado_comp),
            ("Pendiente", comp_pendientes, lambda c: float(c.get("total") or 0)),
            ("Anulado",   comp_anuladas,   lambda c: float(c.get("total") or 0)),
        ]:
            if _lista:
                _tot_lbl = sum(_tot_fn(c) for c in _lista)
                with st.expander(f"{_label} ({len(_lista)}) — $ {_pesos(_tot_lbl)}"):
                    _by_prov = {}
                    for _c in _lista:
                        _by_prov.setdefault(_c.get("proveedor") or "—", []).append(_c)
                    for _prov, _pitems in sorted(_by_prov.items()):
                        _ptot = sum(_tot_fn(c) for c in _pitems)
                        with st.expander(f"{_prov} — {len(_pitems)} comprobante{'s' if len(_pitems)!=1 else ''} — $ {_pesos(_ptot)}"):
                            _rows = [{
                                "Fecha":       _fmt_fecha(c.get("fecha")),
                                "Comprobante": c.get("nro_comprobante") or "—",
                                "Total":       float(c.get("total") or 0),
                                "Pagado":      _pagado_comp(c),
                            } for c in sorted(_pitems, key=lambda x: str(x.get("fecha") or ""), reverse=True)]
                            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                         column_config={
                                             "Total":  st.column_config.NumberColumn("Total",  format="$ %,.2f"),
                                             "Pagado": st.column_config.NumberColumn("Pagado", format="$ %,.2f"),
                                         })

        # Gastos
        st.markdown(f"#### Gastos · {len(gas_pagados) + len(gas_parciales) + len(gas_pendientes)} gastos")
        _eg1, _eg2, _eg3, _eg4 = st.columns(4)
        _bal_metric(_eg1, "Total",     f"$ {_pesos(total_gastos)}",    "#1a1a1a")
        _bal_metric(_eg2, "Pagado",    f"$ {_pesos(total_gas_pag)}",   "#2e7d32")
        _bal_metric(_eg3, "Pendiente", f"$ {_pesos(total_gas_pend)}",  "#c62828")
        _bal_metric(_eg4, "Anulado",   f"$ {_pesos(total_gas_anul)}",  "#757575")
        for _label, _lista, _tot_fn in [
            ("Pagado",    gas_pagados,    lambda g: float(g.get("total") or 0)),
            ("Parcial",   gas_parciales,  _pagado_gasto),
            ("Pendiente", gas_pendientes, lambda g: float(g.get("total") or 0)),
            ("Anulado",   gas_anulados,   lambda g: float(g.get("total") or 0)),
        ]:
            if _lista:
                _tot_lbl = sum(_tot_fn(g) for g in _lista)
                with st.expander(f"{_label} ({len(_lista)}) — $ {_pesos(_tot_lbl)}"):
                    _by_rubro = {}
                    for _g in _lista:
                        _rk = _g.get("rubro_nombre") or _g.get("gasto") or "Sin rubro"
                        _by_rubro.setdefault(_rk, []).append(_g)
                    for _rubro, _ritems in sorted(_by_rubro.items()):
                        _rtot = sum(_tot_fn(g) for g in _ritems)
                        with st.expander(f"{_rubro} ({len(_ritems)}) — $ {_pesos(_rtot)}"):
                            _by_sub = {}
                            for _g in _ritems:
                                _sk = _g.get("sub_rubro_nombre") or "Sin sub rubro"
                                _by_sub.setdefault(_sk, []).append(_g)
                            for _sub, _sitems in sorted(_by_sub.items()):
                                _stot = sum(_tot_fn(g) for g in _sitems)
                                with st.expander(f"{_sub} ({len(_sitems)}) — $ {_pesos(_stot)}"):
                                    _rows = [{
                                        "Fecha":       _fmt_fecha(g.get("fecha")),
                                        "Proveedor":   g.get("proveedor") or "—",
                                        "Items":       ", ".join(d.get("item","") for d in (g.get("detalles") or []) if (d.get("item") or "").strip()),
                                        "Comprobante": g.get("nro_comprobante") or "—",
                                        "Total":       float(g.get("total") or 0),
                                        **( {"Pagado": _pagado_gasto(g)} if _label == "Parcial" else {}),
                                    } for g in sorted(_sitems, key=lambda x: str(x.get("fecha") or ""), reverse=True)]
                                    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                                 column_config={
                                                     "Total":  st.column_config.NumberColumn("Total",  format="$ %,.2f"),
                                                     "Pagado": st.column_config.NumberColumn("Pagado", format="$ %,.2f"),
                                                 })

        # ── RESULTADO ────────────────────────────────────────────────────────────
        st.divider()
        _ing_real   = total_fac_cobr + total_wix_cobr
        _egr_real   = total_comp_pag + total_gas_pag
        _res_real   = _ing_real - _egr_real
        _fic_color  = "#2e7d32" if resultado >= 0 else "#c62828"
        _fic_signo  = "+" if resultado >= 0 else ""
        _real_color = "#2e7d32" if _res_real >= 0 else "#c62828"
        _real_signo = "+" if _res_real >= 0 else ""
        def _metric_cell_sub(label, value, color, sub):
            return f"<div><p style='margin:0;font-size:0.8rem;font-weight:600;color:#777'>{label}</p><p style='margin:2px 0 0;font-size:1.25rem;font-weight:700;color:{color}'>{value}</p><p style='margin:0;font-size:0.75rem;color:#999'>{sub}</p></div>"
        st.markdown(f"""
<div style='background:#eef2f7;border-radius:10px;padding:16px 24px;margin-bottom:8px'>
  <h2 style='text-align:center;margin:0 0 14px 0'>Resultado</h2>
  <div style='display:grid;grid-template-columns:1fr 1fr;gap:16px'>
    {_metric_cell_sub("Devengado", f"{_fic_signo}$ {_pesos(abs(resultado))}", _fic_color, "Facturado − Comprado/Gastado")}
    {_metric_cell_sub("Percibido", f"{_real_signo}$ {_pesos(abs(_res_real))}", _real_color, "Cobrado − Pagado")}
  </div>
</div>""", unsafe_allow_html=True)


if _stab_movimientos:
    with _stab_movimientos:
        _render_movimiento_caja(cobros_bal, pagos_bal)

if _stab_ajustes:
    with _stab_ajustes:
        st.subheader("Ajustes de caja")
        _aj_cajas_list = db.cargar_cajas()
        _aj_cajas_activas = [c for c in _aj_cajas_list if c.get("activa")]
        _aj_nombre_a_id = {c["nombre"]: c["id"] for c in _aj_cajas_activas}
        if not _aj_cajas_activas:
            st.info("No hay cajas activas.")
        else:
            with st.form("form_ajuste_caja"):
                _aj_fc1, _aj_fc2, _aj_fc3 = st.columns([2, 1, 1])
                _aj_caja  = _aj_fc1.selectbox("Caja", options=[c["nombre"] for c in _aj_cajas_activas])
                _aj_fecha = _aj_fc2.date_input("Fecha", value=date.today(), format="DD/MM/YYYY")
                _aj_monto_str = _aj_fc3.text_input("Diferencia ($)", value="0",
                    help="Positivo si sobra plata, negativo si falta.")
                _aj_nota = st.text_input("Nota (opcional)")
                if st.form_submit_button("💾 Guardar ajuste", type="primary", use_container_width=True):
                    try:
                        _aj_monto = float(str(_aj_monto_str).replace(",", ".").strip())
                    except ValueError:
                        st.error("El monto debe ser un número.")
                        _aj_monto = None
                    if _aj_monto is not None:
                        _aj_id = _aj_nombre_a_id.get(_aj_caja)
                        if _aj_id:
                            db.guardar_ajuste_caja(_aj_id, _aj_fecha, _aj_monto, _aj_nota, tipo="ajuste")
                            st.success(f"✅ Ajuste registrado en {_aj_caja}.")
                            st.rerun()

        st.divider()
        st.subheader("Historial de ajustes")
        _todos_aj = [a for a in db.cargar_ajustes_caja() if a.get("tipo") == "ajuste"]
        _aj_cajas_map = {c["id"]: c["nombre"] for c in _aj_cajas_list}
        if _todos_aj:
            _aj_sorted = sorted(_todos_aj, key=lambda x: str(x.get("fecha") or ""), reverse=True)
            _aj_rows = []
            for _a in _aj_sorted:
                _aj_rows.append({
                    "Fecha":  _safe_date(_a.get("fecha")).strftime("%d/%m/%Y") if _safe_date(_a.get("fecha")) != date.min else str(_a.get("fecha") or "")[:10],
                    "Caja":   _aj_cajas_map.get(_a.get("caja_id"), "—"),
                    "Monto":  float(_a.get("monto") or 0),
                    "Nota":   _a.get("nota") or "—",
                })
            st.dataframe(
                pd.DataFrame(_aj_rows),
                use_container_width=True,
                hide_index=True,
                column_config={"Monto": st.column_config.NumberColumn("Monto", format="$ %.0f")},
            )
            st.markdown("**🗑 Eliminar ajuste**")
            _aj_labels = {
                f"{r['Fecha']} · {r['Caja']} · $ {r['Monto']:,.0f}" + (f" · {r['Nota']}" if r["Nota"] != "—" else ""): _aj_sorted[i]["id"]
                for i, r in enumerate(_aj_rows)
            }
            _del_aj_col, _del_aj_btn_col = st.columns([5, 1])
            _del_aj_sel = _del_aj_col.selectbox("Ajuste", options=list(_aj_labels.keys()), key="del_aj_sel", label_visibility="collapsed")
            if _del_aj_btn_col.button("🗑 Eliminar", key="del_aj_btn", type="secondary"):
                db.eliminar_ajuste_caja(_aj_labels[_del_aj_sel])
                st.cache_data.clear()
                st.rerun()
        else:
            st.info("No hay ajustes registrados.")

if _stab_saldo_ini:
    with _stab_saldo_ini:
        st.subheader("Saldo inicial por caja")
        st.caption("Fecha única de corte para todas las cajas. Los movimientos posteriores a esa fecha acumulan sobre el saldo inicial.")
        _ini_cajas_list = db.cargar_cajas()
        _ini_cajas_con_id = [c for c in _ini_cajas_list if c.get("id")]
        if not _ini_cajas_con_id:
            st.info("No hay cajas configuradas.")
        else:
            _ini_ajustes = {
                int(_aj["caja_id"]): _aj
                for _aj in db.cargar_ajustes_caja()
                if _aj.get("tipo") == "inicial"
            }
            # Fecha global: tomar la del primer saldo inicial existente, o hoy
            _fecha_global_actual = date.today()
            for _aj_g in _ini_ajustes.values():
                _fg = _safe_date(_aj_g.get("fecha"))
                if _fg != date.min:
                    _fecha_global_actual = _fg
                    break

            with st.form("form_saldo_inicial_cajas"):
                _fecha_corte = st.date_input(
                    "📅 Fecha de corte (única para todas las cajas)",
                    value=_fecha_global_actual,
                    format="DD/MM/YYYY",
                    key="ini_fecha_global",
                )
                st.divider()
                _ini_vals = {}
                for _cj in _ini_cajas_con_id:
                    _aj_ini = _ini_ajustes.get(int(_cj["id"])) or {}
                    _ini_actual = float(_aj_ini.get("monto") or 0)
                    _fc1, _fc2 = st.columns([2, 2])
                    _fc1.markdown(f"**{_cj['nombre']}**")
                    _ini_vals[_cj["id"]] = _fc2.text_input(
                        "Monto",
                        value=str(int(_ini_actual)) if _ini_actual == int(_ini_actual) else str(_ini_actual),
                        key=f"ini_caja_{_cj['id']}",
                        label_visibility="collapsed",
                    )
                st.caption("Caja · Monto inicial")
                if st.form_submit_button("💾 Guardar", type="primary", use_container_width=True):
                    _ini_error = False
                    _ini_parsed = {}
                    for _cj_id, _ini_str in _ini_vals.items():
                        try:
                            _ini_parsed[_cj_id] = float(str(_ini_str).replace(",", ".").strip())
                        except ValueError:
                            st.error("Monto inválido.")
                            _ini_error = True
                            break
                    if not _ini_error:
                        for _cj_id, _monto in _ini_parsed.items():
                            db.guardar_ajuste_caja(_cj_id, _fecha_corte, _monto, "Saldo inicial", tipo="inicial")
                        st.cache_data.clear()
                        st.success("✅ Saldos iniciales guardados.")
                        st.rerun()

            st.divider()
            st.markdown("**🗑 Eliminar saldo inicial**")
            # Agrupar por fecha de corte
            _del_por_fecha = {}
            for _aj_v in _ini_ajustes.values():
                _fv = _safe_date(_aj_v.get("fecha"))
                _fv_str = _fv.strftime("%d/%m/%Y") if _fv != date.min else "—"
                _del_por_fecha.setdefault(_fv_str, []).append(_aj_v)
            if _del_por_fecha:
                _col_sel, _col_btn = st.columns([3, 1])
                _del_fecha_sel = _col_sel.selectbox(
                    "Fecha de corte",
                    options=list(_del_por_fecha.keys()),
                    key="del_ini_fecha_sel",
                    label_visibility="collapsed",
                )
                if _col_btn.button("🗑 Eliminar", type="secondary", key="del_ini_btn"):
                    for _aj_del in _del_por_fecha[_del_fecha_sel]:
                        db.eliminar_ajuste_caja(_aj_del["id"])
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.caption("No hay saldos iniciales configurados.")

            # Detalle del saldo inicial configurado
            if _ini_ajustes:
                st.divider()
                st.markdown("**📋 Detalle actual**")
                _ini_rows = []
                for _cj in _ini_cajas_con_id:
                    _aj_d = _ini_ajustes.get(int(_cj["id"]))
                    if _aj_d:
                        _ini_rows.append({
                            "Caja":        _cj["nombre"],
                            "Fecha corte": _safe_date(_aj_d.get("fecha")).strftime("%d/%m/%Y") if _safe_date(_aj_d.get("fecha")) != date.min else "—",
                            "Saldo inicial": float(_aj_d.get("monto") or 0),
                        })
                if _ini_rows:
                    _df_ini = pd.DataFrame(_ini_rows)
                    st.dataframe(
                        _df_ini,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Saldo inicial": st.column_config.NumberColumn("Saldo inicial", format="$ %.0f"),
                        },
                    )

if tab_iva:
    with tab_iva:
        st.subheader("🧾 Posición IVA")

        _hoy_iva = date.today()
        try:
            _iva_desde_def = date.fromisoformat(_cfg_bal.get("iva_desde", ""))
        except Exception:
            _iva_desde_def = _hoy_iva.replace(day=1)
        try:
            _iva_hasta_def = date.fromisoformat(_cfg_bal.get("iva_hasta", ""))
        except Exception:
            _iva_hasta_def = _hoy_iva

        with st.form("form_iva_fechas", border=False):
            _ivc1, _ivc2, _ivc3 = st.columns(3)
            with _ivc1:
                _iva_desde = st.date_input("Desde", value=_iva_desde_def, key="iva_desde_in", format="DD/MM/YYYY")
            with _ivc2:
                _iva_hasta = st.date_input("Hasta", value=_iva_hasta_def, key="iva_hasta_in", format="DD/MM/YYYY")
            with _ivc3:
                _sim_target_str = st.text_input("IVA que quiero pagar ($)", value="0", key="sim_iva_target", placeholder="ej: 2000000")
            _btn_iva = st.form_submit_button("Calcular", type="primary", use_container_width=True)
        if _btn_iva:
            db.guardar_config({"iva_desde": str(_iva_desde), "iva_hasta": str(_iva_hasta)})

        def _iva_en_rango(fecha_str):
            try:
                return _iva_desde <= pd.to_datetime(str(fecha_str or "")).date() <= _iva_hasta
            except Exception:
                return False

        _facturas_iva = [f for f in facturas_bal if _iva_en_rango(f.get("fecha_comp")) and str(f.get("anulada", "N")).upper() != "S" and str(f.get("letra_comp") or "").upper() == "A"]

        _iva_neto_gravado = sum(float(f.get("monto_gravado") or 0) for f in _facturas_iva)
        _iva_debito       = sum(float(f.get("monto_iva") or 0) for f in _facturas_iva)

        if not _facturas_iva:
            st.info("No hay facturas en el período seleccionado.")

        st.divider()
        try:
            _sim_target = float(str(_sim_target_str).replace(".", "").replace(",", ".").strip() or 0)
        except ValueError:
            _sim_target = 0.0
        _sim_credito_needed = max(0.0, _iva_debito - _sim_target)
        _sim_facturas_needed = _sim_credito_needed / 0.105

        _sc1, _sc2, _sc3, _sc4 = st.columns(4)
        _bal_metric(_sc1, "Neto Gravado",              f"$ {_pesos(_iva_neto_gravado)}",     "#1565c0")
        _bal_metric(_sc2, "IVA Débito",                f"$ {_pesos(_iva_debito)}",           "#6a1b9a")
        _bal_metric(_sc3, "Crédito fiscal necesario",  f"$ {_pesos(_sim_credito_needed)}",   "#e65100")
        _bal_metric(_sc4, "Facturas de compra (10.5%)", f"$ {_pesos(_sim_facturas_needed)}", "#2e7d32")

if _stab_transferencias:
    with _stab_transferencias:
        st.subheader("Transferencias entre cajas")
        _cajas_tr = db.cargar_cajas()
        _cajas_tr_opts = {c["nombre"]: c["id"] for c in _cajas_tr if c.get("activa")}
        with st.form("form_nueva_transferencia"):
            _tc1, _tc2, _tc3, _tc4 = st.columns(4)
            _tr_fecha   = _tc1.date_input("Fecha", value=date.today(), format="DD/MM/YYYY")
            _tr_origen  = _tc2.selectbox("Desde", options=list(_cajas_tr_opts.keys()))
            _tr_destino = _tc3.selectbox("Hacia",  options=list(_cajas_tr_opts.keys()))
            _tr_monto_str = _tc4.text_input("Monto", value="", placeholder="0")
            _tr_concepto = st.text_input("Concepto (opcional)")
            if st.form_submit_button("Registrar", type="primary", use_container_width=True):
                try:
                    _tr_monto = float(str(_tr_monto_str).replace(",", ".").strip())
                except ValueError:
                    _tr_monto = 0.0
                if _tr_origen == _tr_destino:
                    st.error("Origen y destino deben ser distintos.")
                elif _tr_monto <= 0:
                    st.error("El monto debe ser mayor a cero.")
                else:
                    db.guardar_transferencia(_tr_fecha, _cajas_tr_opts[_tr_origen], _cajas_tr_opts[_tr_destino], _tr_monto, _tr_concepto)
                    st.success("Transferencia registrada.")
                    st.rerun()

        st.divider()
        _todas_tr = db.cargar_transferencias()
        if _todas_tr:
            _tr_sorted = sorted(_todas_tr, key=lambda x: str(x.get("fecha") or ""), reverse=True)
            _tr_rows = []
            for _tr in _tr_sorted:
                _tr_rows.append({
                    "Fecha":    _safe_date(_tr.get("fecha")).strftime("%d/%m/%Y") if _safe_date(_tr.get("fecha")) != date.min else str(_tr.get("fecha") or "")[:10],
                    "Desde":   (_tr.get("origen")  or {}).get("nombre") or "—",
                    "Hacia":   (_tr.get("destino") or {}).get("nombre") or "—",
                    "Concepto": _tr.get("concepto") or "—",
                    "Monto":   float(_tr.get("monto") or 0),
                })
            st.dataframe(
                pd.DataFrame(_tr_rows),
                use_container_width=True,
                hide_index=True,
                column_config={"Monto": st.column_config.NumberColumn("Monto", format="$ %.0f")},
            )
            st.markdown("**🗑 Eliminar transferencia**")
            _tr_labels = {
                f"{r['Fecha']} · {r['Desde']} → {r['Hacia']} · $ {r['Monto']:,.0f}": _tr_sorted[i]["id"]
                for i, r in enumerate(_tr_rows)
            }
            _del_tr_col, _del_tr_btn_col = st.columns([5, 1])
            _del_tr_sel = _del_tr_col.selectbox("Transferencia", options=list(_tr_labels.keys()), key="del_tr_sel", label_visibility="collapsed")
            if _del_tr_btn_col.button("🗑 Eliminar", key="del_tr_btn", type="secondary"):
                db.eliminar_transferencia(_tr_labels[_del_tr_sel])
                st.cache_data.clear()
                st.rerun()
        else:
            st.info("No hay transferencias registradas.")

if tab_ingresos:
    with tab_ingresos:
        if tab_ing_facturas:
            with tab_ing_facturas:
                st.subheader("🧾 Facturas")
                _facturas = db.cargar_facturas()
                if not _facturas:
                    st.info("No hay facturas cargadas. Sincronizá desde el tab 🔄 Sincronizar.")
                else:
                    _fac_df_rows = []
                    for _f in _facturas:
                        _fac_df_rows.append({
                            "Comprobante": f"{_f.get('tipo_comp','')} {_f.get('letra_comp','')} {_f.get('nro_pto_vta','')}-{_f.get('nro_comp','')}".strip(),
                            "Fecha": _fmt_fecha(_f.get("fecha_comp")),
                            "Cliente": f"{_f.get('apellido_razon_soc','')} {_f.get('nombre','')}".strip(),
                            "CUIT": _f.get("cuit", ""),
                            "Nro Pedido": _f.get("nro_pedido", ""),
                            "Total": _f.get("total", 0.0),
                            "Anulada": _f.get("anulada", "N"),
                            "URL": _f.get("url_factura", ""),
                            "_raw": _f,
                        })
                    _total_fac = sum(r["Total"] for r in _fac_df_rows if r["Anulada"] != "S")
                    st.caption(f"{len(_fac_df_rows)} facturas · Total vigente: **$ {_total_fac:,.2f}**")
                    _tabla_fac = [
                        {
                            "Comprobante": r["Comprobante"] + (" ⛔" if r["Anulada"] == "S" else ""),
                            "Fecha": r["Fecha"],
                            "Cliente": r["Cliente"],
                            "Nro Pedido": str(r["Nro Pedido"] or ""),
                            "Total": r["Total"],
                            "PDF": r["URL"] or None,
                        }
                        for r in _fac_df_rows
                    ]
                    st.dataframe(
                        pd.DataFrame(_tabla_fac),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Total": st.column_config.NumberColumn("Total", format="$ %.2f"),
                            "PDF": st.column_config.LinkColumn("PDF", display_text="Ver PDF"),
                        },
                    )

if tab_ingresos:
    with tab_ingresos:
        if tab_ing_cobros:
            with tab_ing_cobros:
                st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('cobros'))}**")
                try:
                    cobros_saved = db.cargar_cobros()
                except Exception as e:
                    st.error(msg_error_sheets("leer cobros", e))
                    cobros_saved = []

                if not cobros_saved:
                    st.info("Todavía no hay cobros. Andá a **🔄 Sincronizar**.")
                else:
                    _total_cobros = sum(float(c.get("monto") or 0) for c in cobros_saved)
                    st.caption(f"{len(cobros_saved)} cobros · Total: **$ {_total_cobros:,.0f}**")
                    _rows = []
                    for _c in sorted(cobros_saved, key=lambda x: x.get("fecha") or "", reverse=True):
                        _imput = _c.get("imputaciones") or []
                        _facts = ", ".join(
                            str(i.get("nro_comprobante","")).strip()
                            for i in _imput if i.get("nro_comprobante")
                        ) or "—"
                        _rows.append({
                            "Cobro #":           _c.get("nro_comprobante") or "—",
                            "Fecha":             _fmt_fecha(_c.get("fecha")),
                            "Cliente":           str(_c.get("cliente") or "—").strip(),
                            "Facturas cobradas": _facts,
                            "Monto":             float(_c.get("monto") or 0),
                        })
                    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                                 column_config={"Monto": st.column_config.NumberColumn("Monto", format="$ %.0f")})

if tab_ing_cobros_wix:
    with tab_ing_cobros_wix:
        try:
            _cajas_cob = db.cargar_cajas()
        except Exception:
            _cajas_cob = []
        _cajas_activas_cob = [c for c in _cajas_cob if c.get("activa", True)]
        _cajas_names_cob = [c["nombre"] for c in _cajas_activas_cob]
        _cajas_por_id_cob = {c["id"]: c["nombre"] for c in _cajas_cob}
        _cajas_por_nombre_cob = {c["nombre"]: c["id"] for c in _cajas_cob}

        try:
            _wix_orders_cob = db.cargar_pedidos_wix()
        except Exception as _e_wc:
            st.error(f"No se pudieron cargar los pedidos Wix: {_e_wc}")
            _wix_orders_cob = []

        if not _wix_orders_cob:
            st.info("No hay pedidos Wix sincronizados.")
        else:
            _wix_sorted_cob = sorted(
                _wix_orders_cob,
                key=lambda o: int(str(o.get("number") or 0)),
                reverse=True,
            )[:100]

            _sels_wix_cob = db.cargar_selecciones("wix")
            try:
                _fechas_pago_cob = db.cargar_fechas_pago_wix()
            except Exception:
                _fechas_pago_cob = {}

            _pay_map = {"PAID": "✅ Pagado", "UNPAID": "❌ Sin pagar", "PENDING": "🟡 Pendiente",
                        "PARTIALLY_REFUNDED": "🟠 Parcial", "FULLY_REFUNDED": "⚫ Reembolsado"}
            _ful_map = {"FULFILLED": "✅ Entregado", "NOT_FULFILLED": "⏳ Pendiente",
                        "PARTIALLY_FULFILLED": "🔶 Parcial"}
            with st.form("form_cobros_wix_cajas", border=False):
                _guardar_cob = st.form_submit_button("💾 Guardar", type="primary", use_container_width=True)
                _nuevas_fpago_cob = {}
                _nuevas_cajas_cob = {}
                for _o in _wix_sorted_cob:
                    _nro_c = _o.get("number") or _o.get("id") or ""
                    _oid_c = str(_o.get("id") or _nro_c)
                    _bi = (_o.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
                    _nombre_c = (
                        f"{_bi.get('firstName', '')} {_bi.get('lastName', '')}".strip()
                        or (_o.get("buyerInfo") or {}).get("email", "")
                        or "—"
                    )
                    _caja_id_c = _o.get("caja_id")
                    _fecha_pago_raw = _fechas_pago_cob.get(_oid_c)
                    try:
                        _fecha_pago_val = date.fromisoformat(_fecha_pago_raw) if _fecha_pago_raw else None
                    except Exception:
                        _fecha_pago_val = None
                    _total_c = (_o.get("priceSummary", {}) or {}).get("total", {}).get("formattedAmount", "")
                    _pay_c = _pay_map.get(str(_o.get("paymentStatus") or "").upper(), "❌ Sin pagar")
                    _ful_c = _ful_map.get(str(_o.get("fulfillmentStatus") or "").upper(), "⏳ No entregado")
                    _fped_c = _fmt_fecha(_o.get("createdDate"))
                    _fent_c = _fmt_fecha(_sels_wix_cob.get(_oid_c))

                    with st.container(border=True):
                        _ci, _cd, _cc = st.columns([5, 2, 2])
                        with _ci:
                            st.markdown(f"**#{_nro_c} — {_nombre_c} · {_total_c}**")
                            _info2 = f" · 🚚 entrega {_fent_c}" if _fent_c and _fent_c != "—" else " · 🚚 —"
                            st.caption(f"{_pay_c} · {_ful_c} · 📅 pedido {_fped_c}{_info2}")
                        with _cd:
                            _fp_new = st.date_input(
                                "F. pago",
                                value=_fecha_pago_val,
                                key=f"fpago_{_oid_c}",
                                format="DD/MM/YYYY",
                                label_visibility="collapsed",
                            )
                        with _cc:
                            _current_caja_c = _cajas_por_id_cob.get(_caja_id_c) if _caja_id_c else None
                            _caja_opts_c = ["—"] + _cajas_names_cob
                            _caja_idx_c = _caja_opts_c.index(_current_caja_c) if _current_caja_c in _caja_opts_c else 0
                            _caja_new = st.selectbox(
                                "Caja",
                                options=_caja_opts_c,
                                index=_caja_idx_c,
                                key=f"caja_{_oid_c}",
                                label_visibility="collapsed",
                            )
                    _nuevas_fpago_cob[_oid_c] = str(_fp_new) if _fp_new is not None else None
                    _nuevas_cajas_cob[_oid_c] = _cajas_por_nombre_cob.get(_caja_new) if _caja_new != "—" else None

            if _guardar_cob:
                try:
                    db.asignar_cajas_pedidos_wix(_nuevas_cajas_cob)
                    db.guardar_fechas_pago_wix(_nuevas_fpago_cob)
                    st.success("✅ Guardado.")
                except Exception as _e_cob:
                    st.error(f"❌ {_e_cob}")

with tab_sync:
    _hoy_sync = date.today()
    _cfg_sync = db.cargar_config()
    try:
        _sync_desde_default = date.fromisoformat(_cfg_sync.get("dux_fecha_desde", ""))
    except Exception:
        _sync_desde_default = _hoy_sync.replace(day=1)
    try:
        _sync_hasta_default = date.fromisoformat(_cfg_sync.get("dux_fecha_hasta", ""))
    except Exception:
        _sync_hasta_default = _hoy_sync

    _ts_sync = db.ultima_carga("pedidos_dux")
    _rango_sync = ""
    if _cfg_sync.get("dux_fecha_desde") and _cfg_sync.get("dux_fecha_hasta"):
        _rango_sync = f" · Rango: {_cfg_sync['dux_fecha_desde']} → {_cfg_sync['dux_fecha_hasta']}"
    st.caption(f"🕒 Última sincronización: **{_fmt_ts(_ts_sync)}**{_rango_sync}")

    with st.form("form_sync_central", border=False):
        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            sync_desde = st.date_input(
                "Desde", value=_sync_desde_default, key="sync_central_desde", format="DD/MM/YYYY"
            )
        with col_s2:
            sync_hasta = st.date_input(
                "Hasta", value=_sync_hasta_default, key="sync_central_hasta", format="DD/MM/YYYY"
            )
        sincronizar_todo = st.form_submit_button(
            "🔄 Sincronizar", type="primary", use_container_width=True
        )

    if sincronizar_todo:
        # Orden: DUX[0], Wix (en el gap del rate limit), DUX[1..n]
        _sync_steps = [
            ("Gastos",               _sync_gastos),
            ("Pedidos Wix",          _sync_pedidos_wix),
            ("Pagos a proveedores",  _sync_pagos_proveedores),
            ("Compras",              _sync_compras),
            ("Pedidos DUX",          _sync_pedidos_dux),
            ("Facturas",             _sync_facturas),
            ("Cobros",               _sync_cobros),
        ]
        _n_steps   = len(_sync_steps)
        _prog_bar  = st.progress(0, text="0%")
        _results   = []

        for _si, (_slabel, _sfn) in enumerate(_sync_steps):
            _pct = int(_si / _n_steps * 100)
            _prog_bar.progress(_si / _n_steps, text=f"{_pct}%")
            # Rate-limit gap entre llamadas DUX (Wix ya corrió en el primer gap)
            if _si == 2:
                # gap cubierto por la llamada a Wix; completar si sobró tiempo
                pass
            elif _si > 1:
                time.sleep(DUX_RATE_LIMIT_SECONDS)
            try:
                _ok, _n, _msg = _sfn(sync_desde, sync_hasta)
            except Exception as _e:
                _ok, _msg = False, msg_error_sheets(_slabel, _e)
            _results.append((_ok, _slabel, _msg))

        _prog_bar.progress(1.0, text="100%")

        _errors = [(_slabel, _msg) for _ok, _slabel, _msg in _results if not _ok]
        for _slabel, _msg in _errors:
            st.error(_msg)

with tab_grupo_config:
    tab_mapeo, tab_packs, tab_mixes, tab_editar = st.tabs(
        ["🗺️ Mapeo Wix↔DUX", "🎁 Packs Wix", "🔀 Mixes DUX", "🔗 Relacionar productos"]
    )

if tab_grupo_config_avanzada:
    with tab_grupo_config_avanzada:
        (
            tab_dux_productos,
            tab_dux_rubros,
            tab_wix_productos,
            tab_proveedores,
            tab_probar,
            tab_migracion,
            tab_cajas,
            tab_gastos_catalogo,
            tab_percepciones,
        ) = st.tabs(
            [
                "DUX Productos",
                "DUX Rubros",
                "Wix Productos",
                "Proveedores",
                "Probar conversión",
                "📦 Migrar desde Sheets",
                "💰 Cajas",
                "📋 Items Gastos",
                "🧾 Percepciones",
            ]
        )

with tab_editar:
    ts_comp_ph = st.empty()
    st.info(
        "Editá las cantidades de las equivalencias. Ejemplo: "
        "1 REPOLLO ROJO - CAJA = 15 REPOLLO ROJO - KG. "
        "**Los cambios se aplican solo al apretar Guardar.**"
    )

    tabla_editor = compuestos[
        [
            "origen_label",
            "cantidad_origen",
            "componente_label",
            "cantidad_componente",
        ]
    ].copy()

    with st.form("form_relacionar", clear_on_submit=False, border=False):
        guardar = st.form_submit_button(
            "💾 Guardar cambios", type="primary"
        )
        tabla_editada = st.data_editor(
            tabla_editor,
            use_container_width=False,
            num_rows="fixed",
            disabled=["origen_label", "componente_label"],
            column_config={
                "origen_label": st.column_config.TextColumn("Producto origen"),
                "cantidad_origen": st.column_config.NumberColumn(
                    "Cantidad origen",
                    min_value=0.0,
                    step=1.0,
                    format="%.3f",
                ),
                "componente_label": st.column_config.TextColumn(
                    "Producto componente/base"
                ),
                "cantidad_componente": st.column_config.NumberColumn(
                    "Cantidad componente/base",
                    min_value=0.0,
                    step=0.5,
                    format="%.3f",
                ),
            },
            key="editor_valores",
        )

    if guardar:
        salida = tabla_editada.copy()
        salida = salida.dropna(subset=["origen_label", "componente_label"])

        salida["codigo_origen"] = salida["origen_label"].map(map_label_a_codigo)
        salida["producto_origen"] = salida["origen_label"].map(map_label_a_producto)
        salida["codigo_componente"] = salida["componente_label"].map(map_label_a_codigo)
        salida["producto_componente"] = salida["componente_label"].map(map_label_a_producto)

        salida = salida[
            [
                "codigo_origen",
                "producto_origen",
                "cantidad_origen",
                "codigo_componente",
                "producto_componente",
                "cantidad_componente",
            ]
        ]

        db.guardar_compuestos(salida)
        st.success("Compuestos guardados correctamente.")

    ts_comp = db.ultima_carga("compuestos")
    ts_comp_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_comp)}**")

if tab_probar:
    with tab_probar:
        st.info("Elegí un producto y se muestran todas las equivalencias de su familia.")

        producto_prueba = st.selectbox("Producto", opciones, key="probar_producto")

        codigo_prueba = map_label_a_codigo[producto_prueba]
        producto_nombre = map_label_a_producto[producto_prueba]

        partes_sel = producto_nombre.rsplit(" - ", 1)
        if len(partes_sel) < 2:
            st.info("Este producto no tiene una unidad parseable para convertir.")
        else:
            base_sel = partes_sel[0].strip()

            productos_fam = productos.copy()
            partes_fam = productos_fam["producto"].str.rsplit(" - ", n=1, expand=True)
            productos_fam["base"] = partes_fam[0].str.strip()

            familia = productos_fam[
                (productos_fam["base"] == base_sel)
                & (productos_fam["codigo"].astype(str) != str(codigo_prueba))
            ]

            if familia.empty:
                st.info(f"No hay otras unidades en la familia **{base_sel}**.")
            else:
                grafo = construir_grafo_conversion(compuestos)

                st.markdown(f"### 1 {producto_nombre} equivale a:")

                for _, otro in familia.iterrows():
                    factor = convertir(grafo, str(codigo_prueba), str(otro["codigo"]))
                    if factor is None:
                        st.markdown(
                            f"- ❓ **{otro['producto']}** — sin relación cargada"
                        )
                    else:
                        st.markdown(f"- **{factor:,.3f}** {otro['producto']}")

with tab_comprar:


    # Cargar fechas guardadas (si existen). Fallback solo la primera vez.
    cfg_comprar = db.cargar_config()
    fechas_stock_disp = db.fechas_stock()
    dias_est_disp = db.dias_semana_con_estimado()

    # Fechas disponibles con pedidos asignados (union DUX + Wix)
    _sels_dux = db.cargar_selecciones("dux")
    _sels_wix = db.cargar_selecciones("wix")
    fechas_entrega_disp = sorted(
        set(_sels_dux.values()) | set(_sels_wix.values()),
        reverse=False,
    )

    def_fent_list = []
    if cfg_comprar.get("comprar_fechas_entrega"):
        try:
            guardadas = cfg_comprar["comprar_fechas_entrega"].split(",")
            def_fent_list = [f.strip() for f in guardadas if f.strip() in fechas_entrega_disp]
        except Exception:
            pass
    if not def_fent_list:
        manana = str(date.today() + timedelta(days=1))
        if manana in fechas_entrega_disp:
            def_fent_list = [manana]

    def_fstk = (
        pd.to_datetime(fechas_stock_disp[0]).date() if fechas_stock_disp else date.today()
    )
    if cfg_comprar.get("comprar_fecha_stock"):
        try:
            def_fstk = pd.to_datetime(cfg_comprar["comprar_fecha_stock"]).date()
        except Exception:
            pass

    # Default dia estimado
    def_dia_est = DIAS_SEMANA[date.today().weekday()]
    if cfg_comprar.get("comprar_dia_estimado") in DIAS_SEMANA:
        def_dia_est = cfg_comprar["comprar_dia_estimado"]

    ts_comprar_ph = st.empty()

    with st.form("form_fechas_comprar", clear_on_submit=False, border=False):
        col_fc1, col_fc2, col_fc3 = st.columns([1.5, 1.2, 1.2])
        with col_fc1:
            fechas_entrega = st.multiselect(
                "📦 Fechas de entrega",
                options=fechas_entrega_disp,
                default=def_fent_list,
                key="comprar_fechas_entrega",
                format_func=_fmt_fecha,
                help="Elegí una o más fechas. Los pedidos de todas ellas se suman.",
            )
        with col_fc2:
            fecha_stock_sel = st.date_input(
                "📦 Fecha de stock",
                value=def_fstk,
                key="comprar_fecha_stock",
                format="DD/MM/YYYY",
            )
        with col_fc3:
            dia_estimado_sel = st.selectbox(
                "📈 Día de estimado",
                options=DIAS_SEMANA,
                format_func=lambda d: DIAS_DISPLAY[d],
                index=DIAS_SEMANA.index(def_dia_est),
                key="comprar_dia_estimado",
            )
        boton_actualizar = st.form_submit_button(
            "🔄 Calcular",
            type="primary",
            use_container_width=True,
        )

    if boton_actualizar:
        try:
            ts_actualizar = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            db.guardar_config({
                "comprar_fechas_entrega": ",".join(fechas_entrega) if fechas_entrega else "",
                "comprar_fecha_stock": str(fecha_stock_sel),
                "comprar_dia_estimado": str(dia_estimado_sel),
                "comprar_ultima_actualizacion": ts_actualizar,
            })
            cfg_comprar["comprar_ultima_actualizacion"] = ts_actualizar
        except Exception:
            pass
        st.cache_data.clear()

    ts_actualizar_ultimo = cfg_comprar.get("comprar_ultima_actualizacion")
    ts_comprar_ph.caption(
        f"🕒 Última actualización: **{_fmt_ts(ts_actualizar_ultimo)}**"
    )

    if str(fecha_stock_sel) not in (fechas_stock_disp or []):
        st.warning(
            f"⚠️ No hay stock cargado para el {fecha_stock_sel}. "
            f"Se va a usar **0 para todos los productos**."
        )
    if dia_estimado_sel not in (dias_est_disp or []):
        st.warning(
            f"⚠️ No hay estimado cargado para {DIAS_DISPLAY[dia_estimado_sel]}. "
            f"Se va a usar **0 para todos los productos**."
        )

    pedidos_actual = cargar_pedidos_dux_aggregated(
        productos,
        dia_estimado=dia_estimado_sel,
        fecha_compra=fechas_entrega if fechas_entrega else None,
    )
    stock_actual = db.cargar_stock(fecha=fecha_stock_sel)
    # Para mantener compatibilidad con el resto del código de la pestaña
    fecha_compra = fechas_entrega

    # Helper de fechas (usado en labels de varios expanders).
    def _fmt_fechas_label(fechas):
        if not fechas:
            return ""
        items = sorted(set(str(f) for f in (
            fechas if isinstance(fechas, (list, tuple, set)) else [fechas]
        )))
        if len(items) == 1:
            return f"({items[0]})"
        return f"({items[0]} a {items[-1]})"

    _lab_ped = _fmt_fechas_label(fechas_entrega)

    wix_sin_mapear = st.session_state.get("_wix_sin_mapear", {})
    if wix_sin_mapear:
        lineas = "\n".join(
            f"- **{v['nombre']}** × {v['cantidad']:g}"
            for v in wix_sin_mapear.values()
        )
        st.warning(
            "⚠️ Hay pedidos Wix con productos **sin mapear** — no se están sumando al total:\n\n"
            f"{lineas}\n\n"
            "Andá a 🔗 Mapeo Wix↔DUX para asignarlos."
        )

    mixes_sin_config = st.session_state.get("_mixes_sin_config", [])
    if mixes_sin_config:
        lineas_mix = "\n".join(f"- **{m}**" for m in mixes_sin_config)
        st.warning(
            "⚠️ Hay pedidos de productos **MIX sin configurar** — entran al total como MIX en vez de desglozarse en componentes:\n\n"
            f"{lineas_mix}\n\n"
            "Andá a ⚙️ Mixes DUX para configurar sus componentes."
        )

    # Expander con los pedidos que estan siendo contados, para poder verificar
    _dux_contados = st.session_state.get("_dux_contados", [])
    _wix_contados = st.session_state.get("_wix_contados", [])
    _total_pedidos = len(_dux_contados) + len(_wix_contados)
    with st.expander(
        f"📋 Ver pedidos que se están contando {_lab_ped} ({_total_pedidos})",
        expanded=False,
    ):
        if not _total_pedidos:
            st.caption("No hay pedidos asignados a esta fecha de entrega.")
        else:
            if _dux_contados:
                st.markdown(f"**DUX ({len(_dux_contados)})**")
                for o in _dux_contados:
                    nro = _dux_get_first(
                        o, ["nro_pedido", "nroPedido", "numero", "id"]
                    )
                    cliente = extraer_cliente_dux(o)
                    items = extraer_items_dux(o)
                    with st.expander(
                        f"#{nro or '-'} · {cliente} · {len(items)} ítems",
                        expanded=False,
                    ):
                        if items:
                            filas_it = [extraer_item_dux(it) for it in items]
                            st.dataframe(
                                pd.DataFrame(filas_it)[["producto", "cantidad"]].rename(
                                    columns={"producto": "Prod", "cantidad": "Cant"}
                                ),
                                use_container_width=False,
                                hide_index=True,
                            )
                        else:
                            st.caption("Sin items en este pedido.")

            if _wix_contados:
                st.markdown(f"**Wix ({len(_wix_contados)})**")
                for o in _wix_contados:
                    nro = o.get("number") or o.get("id", "")
                    bi = (o.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
                    nombre_w = (
                        f"{bi.get('firstName', '') or ''} {bi.get('lastName', '') or ''}".strip()
                        or "(sin cliente)"
                    )
                    items_w = o.get("lineItems") or []
                    with st.expander(
                        f"#{nro} · {nombre_w} · {len(items_w)} ítems",
                        expanded=False,
                    ):
                        if items_w:
                            filas_iw = []
                            for li in items_w:
                                nombre_prod = (
                                    (li.get("productName") or {}).get("translated")
                                    or (li.get("productName") or {}).get("original")
                                    or ""
                                )
                                filas_iw.append({
                                    "Prod": nombre_prod,
                                    "Cant": li.get("quantity") or 0,
                                })
                            st.dataframe(
                                pd.DataFrame(filas_iw),
                                use_container_width=False,
                                hide_index=True,
                            )
                        else:
                            st.caption("Sin items en este pedido.")

    # Expander para ver el stock crudo de la fecha elegida
    _stk_view = stock_actual[stock_actual["cantidad"].astype(float) > 0] if (
        stock_actual is not None and not stock_actual.empty
    ) else pd.DataFrame()
    with st.expander(
        f"📦 Ver stock cargado del {fecha_stock_sel} ({len(_stk_view)} con cantidad > 0)",
        expanded=False,
    ):
        if _stk_view.empty:
            st.caption("Sin stock cargado para esta fecha.")
        else:
            st.dataframe(
                _stk_view[["producto", "cantidad"]]
                .assign(
                    _base=lambda d: d["producto"].str.rsplit(" - ", n=1).str[0],
                    _prio=lambda d: d["producto"].str.rsplit(" - ", n=1).str[-1].map(_prio_unidad),
                )
                .sort_values(["_base", "_prio", "producto"]).drop(columns=["_base", "_prio"])
                .rename(columns={"producto": "Producto", "cantidad": "Cant"}),
                use_container_width=False,
                hide_index=True,
            )

    # Expander para ver el estimado del dia elegido
    _est_view = db.cargar_estimado_semanal(dia=dia_estimado_sel)
    if not _est_view.empty:
        _est_view = _est_view[_est_view["estimado"].astype(float) > 0]
    with st.expander(
        f"📈 Ver estimado de {DIAS_DISPLAY.get(dia_estimado_sel, dia_estimado_sel)} ({len(_est_view)} con estimado > 0)",
        expanded=False,
    ):
        if _est_view.empty:
            st.caption("Sin estimado cargado para este día.")
        else:
            st.dataframe(
                _est_view[["producto", "estimado"]]
                .assign(
                    _base=lambda d: d["producto"].str.rsplit(" - ", n=1).str[0],
                    _prio=lambda d: d["producto"].str.rsplit(" - ", n=1).str[-1].map(_prio_unidad),
                )
                .sort_values(["_base", "_prio", "producto"]).drop(columns=["_base", "_prio"])
                .rename(columns={"producto": "Producto", "estimado": "Cant"}),
                use_container_width=False,
                hide_index=True,
            )

    # Expander resumen crudo por codigo (sin conversiones): pedido + estimado + stock
    _raw = pedidos_actual.copy()
    _raw["codigo"] = _raw["codigo"].astype(str)
    if stock_actual is not None and not stock_actual.empty:
        _stk_map = dict(
            zip(stock_actual["codigo"].astype(str), stock_actual["cantidad"].astype(float))
        )
        _raw["stock"] = _raw["codigo"].map(_stk_map).fillna(0.0).astype(float)
    else:
        _raw["stock"] = 0.0
    _raw_view = _raw[
        (_raw["cantidad"].astype(float) > 0)
        | (_raw["estimado"].astype(float) > 0)
        | (_raw["stock"].astype(float) > 0)
    ].copy()
    with st.expander(
        f"🔍 Ver total a comprar **SIN** desglozar ({len(_raw_view)})",
        expanded=False,
    ):
        # Aclaracion compacta sobre como se decide el color del producto base
        # a partir de sus variantes (regla de prioridad).
        st.caption(
            "ℹ️ El color del producto sigue la **peor variante**: "
            "si una está en :red[**rojo**] → todo rojo. "
            "Sino, si alguna está en :gray[**gris**] → gris. "
            "Solo si todas están en :green[**verde**] → verde."
        )

        if _raw_view.empty:
            st.caption("Sin datos.")
        else:
            _raw_view = _raw_view.rename(columns={"cantidad": "pedido"}).sort_values("producto")
            _raw_view["a_comprar"] = (
                _raw_view["pedido"].astype(float)
                + _raw_view["estimado"].astype(float)
                - _raw_view["stock"].astype(float)
            )

            def _color_ac(v):
                if v > 0.001:
                    return "color: #d11; font-weight: bold;"
                if v < -0.001:
                    return "color: #1a8a1a; font-weight: bold;"
                return "color: #666;"

            # Partir producto en base / variante (mismo patron que Stock tab).
            def _split_producto_raw(p):
                s = str(p)
                if " - " in s:
                    base, var = s.rsplit(" - ", 1)
                    return base.strip(), var.strip()
                return s, ""

            _split_raw = _raw_view["producto"].apply(_split_producto_raw)
            _raw_view["Base"] = _split_raw.apply(lambda t: t[0])
            _raw_view["Variante"] = _split_raw.apply(lambda t: t[1])

            # Decidir color del expander segun prioridad rojo > gris > verde.
            # Mismo criterio que _color_ac:
            #   a_comprar > 0.001  -> rojo  (falta comprar)
            #   a_comprar < -0.001 -> verde (sobra)
            #   else               -> gris  (balanceado)
            def _color_base(df):
                vals = df["a_comprar"].astype(float)
                if (vals > 0.001).any():
                    return "red"
                if ((vals >= -0.001) & (vals <= 0.001)).any():
                    return "gray"
                return "green"

            for base_name, df_base in _raw_view.groupby("Base", sort=True):
                n_var = len(df_base)
                _label_txt = (
                    f"📦 {base_name} "
                    f"({n_var} variante{'s' if n_var != 1 else ''})"
                )
                _color = _color_base(df_base)
                _label = f":{_color}[**{_label_txt}**]"
                with st.expander(_label, expanded=False):
                    _disp = (
                        df_base[[
                            "Variante",
                            "stock", "pedido", "estimado", "a_comprar",
                        ]]
                        .assign(_prio=lambda d: d["Variante"].map(_prio_unidad))
                        .sort_values("_prio")
                        .drop(columns="_prio")
                        .rename(columns={
                            "Variante": "Var",
                            "stock": "S",
                            "pedido": "P",
                            "estimado": "E",
                            "a_comprar": "T",
                        })
                    )
                    styled = (
                        _disp.style
                        .map(_color_ac, subset=["T"])
                        .format({
                            "P": "{:.2f}",
                            "S": "{:.2f}",
                            "E": "{:.2f}",
                            "T": lambda v: f"{abs(v):.2f}",
                        })
                    )
                    st.dataframe(
                        styled,
                        use_container_width=False,
                        hide_index=True,
                    )

            st.caption(
                "**Total** = `pedido + estimado − stock` (por código, sin conversiones)."
            )

    # Si no hay pedidos sincronizados, la tabla queda vacia (sin warning)

    grafo = construir_grafo_conversion(compuestos)

    prod_temp = productos.copy()
    partes_pr = prod_temp["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
    prod_temp["base"] = partes_pr[0].str.strip()
    prod_temp["unidad"] = (
        partes_pr[1].fillna("").str.strip()
        if 1 in partes_pr.columns
        else ""
    )

    ped = pedidos_actual.dropna(subset=["producto"]).copy()
    ped["cantidad"] = ped["cantidad"].fillna(0).astype(float)
    if "estimado" not in ped.columns:
        ped["estimado"] = 0.0
    ped["estimado"] = ped["estimado"].fillna(0).astype(float)
    partes_ped = ped["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
    ped["base"] = partes_ped[0].str.strip() if not partes_ped.empty else ""

    if stock_actual is not None and not stock_actual.empty:
        stk = stock_actual.dropna(subset=["producto"]).copy()
        stk["cantidad"] = stk["cantidad"].fillna(0)
        partes_stk = stk["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
        stk["base"] = partes_stk[0].str.strip() if not partes_stk.empty else ""
    else:
        stk = pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "cantidad", "base"]
        )

    # Mostrar productos que tengan ALGUN valor: pedido, estimado o stock
    ped_relevante = ped[(ped["cantidad"] > 0) | (ped["estimado"] > 0)]
    bases_set = set(ped_relevante["base"].unique())
    if not stk.empty:
        bases_set |= set(stk[stk["cantidad"] > 0]["base"].unique())
    bases = sorted(bases_set)

    # Headers cortos (S/Pedido/E/T) en las tablas del desglozado.
    # Las fechas correspondientes ya se muestran en los labels de los
    # expanders de arriba (Ver stock / Ver pedidos / Ver estimado).

    with st.expander(
        f"🔧 Ver total a comprar **desglozado** ({len(bases)})",
        expanded=False,
    ):
        for base in bases:
            opciones_grupo = prod_temp[prod_temp["base"] == base]
            if opciones_grupo.empty:
                continue

            codigos_familia = opciones_grupo["codigo"].astype(str).tolist()
            componentes = componentes_conectados(codigos_familia, grafo)

            ped_base = ped[ped["base"] == base]
            stk_base = stk[stk["base"] == base] if not stk.empty else stk

            pedido_codigos = set(
                ped_base[
                    (ped_base["cantidad"] > 0) | (ped_base["estimado"] > 0)
                ]["codigo"].astype(str)
            )
            stock_codigos = (
                set(stk_base[stk_base["cantidad"] > 0]["codigo"].astype(str))
                if not stk_base.empty
                else set()
            )
            codigos_con_valor = pedido_codigos | stock_codigos

            for comp in componentes:
                if not (comp & codigos_con_valor):
                    continue

                comp_productos = opciones_grupo[
                    opciones_grupo["codigo"].astype(str).isin(comp)
                ]
                # Lista de unidades unicas preservando orden
                unidades_unicas = list(dict.fromkeys(comp_productos["unidad"].tolist()))

                # Calcular totales para CADA unidad de la familia
                resultados = []
                for unidad in unidades_unicas:
                    codigo_destino = str(
                        comp_productos[comp_productos["unidad"] == unidad].iloc[0]["codigo"]
                    )
                    total_ped = 0.0
                    total_est = 0.0
                    for _, fila in ped_base.iterrows():
                        if str(fila["codigo"]) not in comp:
                            continue
                        factor = convertir(grafo, str(fila["codigo"]), codigo_destino)
                        if factor is None:
                            continue
                        total_ped += float(fila["cantidad"]) * factor
                        total_est += float(fila["estimado"]) * factor

                    total_stk = 0.0
                    if not stk_base.empty:
                        for _, fila in stk_base.iterrows():
                            if str(fila["codigo"]) not in comp:
                                continue
                            cant = float(fila["cantidad"])
                            if cant == 0:
                                continue
                            factor = convertir(grafo, str(fila["codigo"]), codigo_destino)
                            if factor is None:
                                continue
                            total_stk += cant * factor

                    resultados.append({
                        "codigo": codigo_destino,
                        "unidad": unidad,
                        "pedido": total_ped,
                        "estimado": total_est,
                        "stock": total_stk,
                        "diff": total_ped - total_stk,
                        "diff_est": (total_ped + total_est) - total_stk,
                    })

                if not resultados:
                    continue

                # Status overall (todos los diff dentro de la familia deberian tener el mismo signo)
                primer = resultados[0]["diff_est"]
                if primer > 0.001:
                    icono = "🔴"
                elif primer < -0.001:
                    icono = "🟢"
                else:
                    icono = "⚪"

                # Nombre: si la familia tiene un solo producto, usar su nombre completo
                nombre = (
                    comp_productos.iloc[0]["producto"] if len(comp) == 1 else base
                )

                with st.expander(f"{icono} **{nombre}**", expanded=False):
                    df_show = pd.DataFrame([
                        {
                            "Var": r["unidad"],
                            "S": r["stock"],
                            "P": r["pedido"],
                            "E": r["estimado"],
                            "T": r["diff_est"],
                        }
                        for r in sorted(resultados, key=lambda r: _prio_unidad(r["unidad"]))
                    ])

                    def _color_diff(v):
                        try:
                            n = float(v)
                        except (ValueError, TypeError):
                            return ""
                        if n > 0.001:
                            return "color: #d11; font-weight: bold"
                        if n < -0.001:
                            return "color: #1a8a1a; font-weight: bold"
                        return ""

                    styled_grupo = (
                        df_show.style
                        .format({
                            "P": "{:,.2f}",
                            "S": "{:,.2f}",
                            "E": "{:,.2f}",
                            "T": lambda v: f"{abs(float(v)):,.2f}",
                        })
                        .map(_color_diff, subset=["T"])
                    )
                    st.dataframe(
                        styled_grupo,
                        use_container_width=False,
                        hide_index=True,
                    )

with tab_estimado:
    dia_actual = DIAS_SEMANA[date.today().weekday()]
    cfg_est_tab = db.cargar_config()
    dia_default_idx = DIAS_SEMANA.index(dia_actual)
    if cfg_est_tab.get("estimado_dia") in DIAS_SEMANA:
        dia_default_idx = DIAS_SEMANA.index(cfg_est_tab["estimado_dia"])

    def _save_dia_estimado():
        v = st.session_state.get("dia_estimado")
        if v in DIAS_SEMANA:
            try:
                db.guardar_config({"estimado_dia": str(v)})
            except Exception:
                pass

    # Timestamp arriba de todo (debajo de las pestañas)
    ts_est_ph = st.empty()

    dia_estimado = st.selectbox(
        "Día de la semana",
        options=DIAS_SEMANA,
        format_func=lambda d: DIAS_DISPLAY[d],
        index=dia_default_idx,
        key="dia_estimado",
        on_change=_save_dia_estimado,
    )

    df_dia_est = db.cargar_estimado_semanal(dia=dia_estimado)
    map_est_dia = (
        dict(zip(df_dia_est["codigo"].astype(str), df_dia_est["estimado"]))
        if not df_dia_est.empty
        else {}
    )

    base_est = productos[["codigo", "producto", "unidad_medida"]].copy()
    base_est["estimado"] = (
        base_est["codigo"]
        .astype(str)
        .map(map_est_dia)
        .fillna(0.0)
        .astype(float)
    )

    # "Poner a cero" llena el editor con ceros (sin guardar).
    if st.session_state.get(f"_est_zero_{dia_estimado}"):
        base_est["estimado"] = 0.0

    # Boton "Resetear a cero" (fuera de form)
    reset_est = st.button(
        "🧹 Resetear a cero",
        key="btn_reset_estimado",
        help="Llena todo el estimado con 0. No se guarda hasta apretar 💾 Guardar estimado.",
    )

    base_est_view = base_est.copy()
    # TextColumn para aceptar coma decimal (1,5) ademas de punto (1.5)
    base_est_view["estimado"] = base_est_view["estimado"].apply(_fmt_num_es)

    # Enriquecer con rubro (catalogo productos) y partir producto en
    # base / variante por ' - '. Misma logica que Stock teorico.
    cod_to_rubro_est = dict(zip(
        productos["codigo"].astype(str),
        productos.get("rubro", pd.Series([""] * len(productos))).fillna("").astype(str),
    ))

    def _split_producto_est(p):
        s = str(p)
        if " - " in s:
            b, v = s.rsplit(" - ", 1)
            return b.strip(), v.strip()
        return s, ""

    base_est_view["Rubro"] = base_est_view["codigo"].astype(str).map(
        lambda c: (cod_to_rubro_est.get(c, "") or "").strip().upper()
    )
    _split_est_v = base_est_view["producto"].apply(_split_producto_est)
    base_est_view["Base"] = _split_est_v.apply(lambda t: t[0])
    base_est_view["Variante"] = _split_est_v.apply(lambda t: t[1])

    # Ocultar productos sin rubro (no son productos reales).
    base_est_view = base_est_view[base_est_view["Rubro"] != ""].copy()

    # Orden fijo de rubros (mismo que Stock tab).
    orden_rubros_est = [
        "HOJAS", "VERDURAS", "FRUTAS", "HIERBAS",
        "HONGOS", "BROTES", "AJIES", "CONDIMENTOS", "OTROS",
    ]
    rubros_presentes_est = [
        r for r in orden_rubros_est if r in base_est_view["Rubro"].values
    ]
    rubros_presentes_est += sorted(
        set(base_est_view["Rubro"].values) - set(orden_rubros_est)
    )

    edits_por_clave_est = {}  # (rubro, base) -> edited_df

    st.caption(
        "ℹ️ Los productos / rubros en :gray[**gris**] no tienen ningún "
        "estimado cargado para este día."
    )

    with st.form(key=f"form_estimado_{dia_estimado}", clear_on_submit=False):
        guardar_est = st.form_submit_button(
            "💾 Guardar estimado", type="primary"
        )

        def _df_estimado_tiene_carga(df):
            for v in df["estimado"]:
                try:
                    if abs(_parse_num_es(str(v))) > 1e-6:
                        return True
                except Exception:
                    pass
            return False

        for rubro_name in rubros_presentes_est:
            df_rubro = base_est_view[base_est_view["Rubro"] == rubro_name]
            n_bases = df_rubro["Base"].nunique()
            _rubro_lbl_txt = f"📁 {rubro_name} ({n_bases} productos)"
            _rubro_lbl = (
                _rubro_lbl_txt if _df_estimado_tiene_carga(df_rubro)
                else f":gray[{_rubro_lbl_txt}]"
            )
            with st.expander(_rubro_lbl, expanded=False):
                for base_name, df_base in df_rubro.groupby("Base", sort=True):
                    n_var = len(df_base)
                    _base_lbl_txt = (
                        f"📦 {base_name} "
                        f"({n_var} variante{'s' if n_var != 1 else ''})"
                    )
                    _base_lbl = (
                        _base_lbl_txt if _df_estimado_tiene_carga(df_base)
                        else f":gray[{_base_lbl_txt}]"
                    )
                    with st.expander(_base_lbl, expanded=False):
                        _df_est_sorted = (
                            df_base
                            .assign(_prio=lambda d: d["Variante"].map(_prio_unidad))
                            .sort_values(["_prio", "Variante"]).drop(columns="_prio")
                        )
                        edited = st.data_editor(
                            _df_est_sorted[["codigo", "Variante", "estimado"]].reset_index(drop=True),
                            use_container_width=False,
                            hide_index=True,
                            disabled=["codigo", "Variante"],
                            # column_order oculta 'codigo' del display sin
                            # sacarla del df subyacente -> el save sigue usando
                            # row["codigo"] sin problemas.
                            column_order=["Variante", "estimado"],
                            column_config={
                                "codigo": st.column_config.TextColumn("Código"),
                                "Variante": st.column_config.TextColumn("Var"),
                                "estimado": st.column_config.TextColumn(
                                    "Cant",
                                    help="Podés usar coma (1,5) o punto (1.5)",
                                ),
                            },
                            key=f"editor_estimado_{rubro_name}_{base_name}_{dia_estimado}",
                        )
                        edits_por_clave_est[(rubro_name, base_name)] = edited

    if guardar_est:
        edits_map_e = {}
        for _key, edited in edits_por_clave_est.items():
            for _, row in edited.iterrows():
                edits_map_e[str(row["codigo"])] = _parse_num_es(row["estimado"])

        salida = base_est.copy()
        salida["estimado"] = [
            edits_map_e.get(str(c), v)
            for c, v in zip(salida["codigo"], salida["estimado"])
        ]
        salida["estimado"] = salida["estimado"].fillna(0).astype(float)
        db.guardar_estimado_semanal_dia(salida, dia_estimado)
        st.session_state.pop(f"_est_zero_{dia_estimado}", None)
        st.success(
            f"Estimado para {DIAS_DISPLAY[dia_estimado]} guardado en Sheets."
        )

    if reset_est:
        st.session_state[f"_est_zero_{dia_estimado}"] = True
        # Pop todas las keys de los editors por base (no sabemos los nombres
        # exactos, asi que limpiamos las que coincidan con el patron).
        prefix = "editor_estimado_"
        suffix = f"_{dia_estimado}"
        for k in list(st.session_state.keys()):
            if k.startswith(prefix) and k.endswith(suffix):
                st.session_state.pop(k, None)
        st.rerun()

    # Refrescar timestamp despues del posible save (placeholder esta arriba)
    ts_est_ultimo = db.ultima_carga("estimado_semanal")
    ts_est_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_est_ultimo)}**")


with tab_stock:
    # Stock (single-day): Stock(F0) + Compras(Fc) - Pedidos(Fp)
    # Las fechas se persisten en gsheets config y el resultado vive en
    # session_state (no se pierde al cambiar fechas, solo se recalcula
    # cuando se aprieta el boton).

    ts_stk_save_ph = st.empty()
    ts_stk_save_ph.caption(
        f"🕒 Último guardado de stock: **{_fmt_ts(db.ultima_carga('stock'))}**"
    )

    fechas_stk_disp_t = db.fechas_stock()
    cfg_teorico = db.cargar_config()

    def _default_or_saved(key_cfg, fallback):
        v = cfg_teorico.get(key_cfg)
        if v:
            try:
                return pd.to_datetime(v).date()
            except Exception:
                pass
        return fallback

    f0_fallback = (
        pd.to_datetime(fechas_stk_disp_t[0]).date()
        if fechas_stk_disp_t else date.today() - timedelta(days=7)
    )

    # Los defaults vienen del ultimo calculo guardado (no de un on_change).
    f0_default = _default_or_saved("st_teorico_ultimo_f0", f0_fallback)
    fc_default = _default_or_saved("st_teorico_ultimo_fc", date.today())
    fp_default = _default_or_saved("st_teorico_ultimo_fp", date.today())
    # fecha_conteo se persiste al apretar 'Guardar Stock', defaults a la
    # ultima guardada o a hoy si nunca se guardo.
    fecha_conteo_default = _default_or_saved("st_teorico_fecha_conteo", date.today())

    with st.form("form_params_teorico", border=False):
        col_t1, col_t2, col_t3, col_t4 = st.columns([1, 1, 1, 1])
        with col_t1:
            f0 = st.date_input(
                "📦 Stock inicial",
                value=f0_default,
                key="st_teorico_f0",
                format="DD/MM/YYYY",
                help="Día con conteo físico cargado en Stock.",
            )
        with col_t2:
            fc = st.date_input(
                "🛒 Compras",
                value=fc_default,
                key="st_teorico_fc",
                format="DD/MM/YYYY",
                help="Día de la compra a sumar.",
            )
        with col_t3:
            fp = st.date_input(
                "📋 Pedidos",
                value=fp_default,
                key="st_teorico_fp",
                format="DD/MM/YYYY",
                help="Día de entrega del pedido a restar.",
            )
        with col_t4:
            fecha_conteo = st.date_input(
                "📅 Stock",
                value=fecha_conteo_default,
                key="fecha_conteo_real",
                format="DD/MM/YYYY",
                help="Día con el que se guardará el Stock al apretar Guardar.",
            )
        actualizar = st.form_submit_button(
            "🔄 Calcular",
            type="primary",
            use_container_width=True,
        )

    if actualizar:
        try:
            db.guardar_config({
                "st_teorico_ultimo_f0": str(f0),
                "st_teorico_ultimo_fc": str(fc),
                "st_teorico_ultimo_fp": str(fp),
            })
        except Exception:
            pass
        st.cache_data.clear()

    # Calcular siempre al cargar (igual que Total a comprar)
    fechas_actuales = db.fechas_stock()
    if str(f0) not in (fechas_actuales or []):
        _disp = ", ".join(_fmt_fecha(f) for f in (fechas_actuales or [])[:5]) or "ninguna"
        st.error(
            f"⚠️ No hay stock para {_fmt_fecha(f0)}. "
            f"Fechas disponibles: {_disp}."
        )
    else:
        try:
            stk_ini_df = db.cargar_stock(fecha=f0)
        except Exception as _e_stk:
            st.error(f"⚠️ Error cargando stock: {_e_stk}")
            stk_ini_df = pd.DataFrame()
        map_stock_ini = {}
        if not stk_ini_df.empty:
            map_stock_ini = dict(zip(
                stk_ini_df["codigo"].astype(str),
                stk_ini_df["cantidad"].astype(float),
            ))

        try:
            compras_res = db.cargar_compras_desde_gastos(fc)
        except Exception:
            compras_res = {"cantidades": {}, "compras": []}
        map_compras = compras_res.get("cantidades", {})
        compras_raw = compras_res.get("compras", [])

        try:
            df_ped_agg = cargar_pedidos_dux_aggregated(
                productos, dia_estimado=None, fecha_compra=[str(fp)]
            )
        except Exception:
            df_ped_agg = pd.DataFrame()
        map_pedidos = {}
        if not df_ped_agg.empty:
            for _, r in df_ped_agg.iterrows():
                cod = str(r.get("codigo", ""))
                ctd = float(r.get("cantidad", 0) or 0)
                if cod and ctd > 0:
                    map_pedidos[cod] = map_pedidos.get(cod, 0.0) + ctd

        prod_map = {
            str(c): (str(p), str(u))
            for c, p, u in zip(
                productos["codigo"],
                productos["producto"],
                productos["unidad_medida"],
            )
        }
        rows = []
        for cod in prod_map.keys():
            nombre, _u = prod_map[cod]
            s = float(map_stock_ini.get(cod, 0.0))
            c = float(map_compras.get(cod, 0.0))
            p = float(map_pedidos.get(cod, 0.0))
            t = s + c - p
            rows.append({
                "Código": cod,
                "Producto": nombre,
                "Stock inicial": s,
                "+ Compras": c,
                "− Pedidos": p,
                "= Teórico": t,
            })

        if not rows:
            st.info("No hay movimientos en las fechas seleccionadas.")
        else:
            df_teorico_r = (
                pd.DataFrame(rows)
                .sort_values("Producto", ascending=True)
                .reset_index(drop=True)
            )

            def _tiene_mov(row):
                return (
                    abs(float(row.get("Stock inicial", 0))) > 1e-6
                    or abs(float(row.get("+ Compras", 0))) > 1e-6
                    or abs(float(row.get("− Pedidos", 0))) > 1e-6
                )
            n_con_mov = sum(1 for _, r in df_teorico_r.iterrows() if _tiene_mov(r))
            n_stock_ini = int((df_teorico_r["Stock inicial"] > 0.001).sum())

            _prod_nombre = dict(zip(
                productos["codigo"].astype(str),
                productos["producto"].astype(str),
            ))

            with st.expander(
                f"📦 Stock inicial del {_fmt_fecha(f0)} ({n_stock_ini} códigos)",
                expanded=False,
            ):
                if not map_stock_ini:
                    st.caption("Sin datos.")
                else:
                    _filas_ini = [
                        {"Prod": _prod_nombre.get(cod, "(desconocido)"), "Cant": float(cant)}
                        for cod, cant in map_stock_ini.items()
                        if float(cant) > 1e-6
                    ]
                    if _filas_ini:
                        st.dataframe(
                            pd.DataFrame(_filas_ini).sort_values("Prod"),
                            use_container_width=False,
                            hide_index=True,
                        )
                    else:
                        st.caption("Stock inicial todo en 0.")

            with st.expander(
                f"🛒 Compras del {_fmt_fecha(fc)} ({len(compras_raw)} compras)",
                expanded=False,
            ):
                if not compras_raw:
                    st.caption("No hubo compras ese día (o no fueron sincronizadas en Egresos → Gastos).")
                else:
                    for c in compras_raw:
                        nro = c.get("nro_comprobante", "?")
                        prov = (c.get("proveedor") or {}).get("razon_social") or "?"
                        items = c.get("items") or []
                        with st.expander(
                            f"#{nro} · {prov} · {len(items)} ítems",
                            expanded=False,
                        ):
                            if items:
                                filas_c = [
                                    {
                                        "Prod": _prod_nombre.get(
                                            str(it.get("cod_item", "")), "(desconocido)"
                                        ),
                                        "Cant": float(it.get("ctd_recepcionada", 0) or 0),
                                    }
                                    for it in items
                                ]
                                st.dataframe(
                                    pd.DataFrame(filas_c),
                                    use_container_width=False,
                                    hide_index=True,
                                )
                            else:
                                st.caption("Sin items.")

            _dux_ct = st.session_state.get("_dux_contados", [])
            _wix_ct = st.session_state.get("_wix_contados", [])
            _total_ped = len(_dux_ct) + len(_wix_ct)
            with st.expander(
                f"📋 Pedidos contados del {_fmt_fecha(fp)} ({_total_ped} pedidos)",
                expanded=False,
            ):
                if not _total_ped:
                    st.caption("No hay pedidos asignados a esa fecha de entrega.")
                else:
                    if _dux_ct:
                        st.markdown(f"**DUX ({len(_dux_ct)})**")
                        for o in _dux_ct:
                            nro = _dux_get_first(
                                o, ["nro_pedido", "nroPedido", "numero", "id"]
                            )
                            cliente = extraer_cliente_dux(o)
                            items = extraer_items_dux(o)
                            with st.expander(
                                f"#{nro or '-'} · {cliente} · {len(items)} ítems",
                                expanded=False,
                            ):
                                if items:
                                    filas_it = [extraer_item_dux(it) for it in items]
                                    st.dataframe(
                                        pd.DataFrame(filas_it)[
                                            ["producto", "cantidad"]
                                        ].rename(columns={
                                            "producto": "Prod", "cantidad": "Cant",
                                        }),
                                        use_container_width=False,
                                        hide_index=True,
                                    )
                                else:
                                    st.caption("Sin items.")
                    if _wix_ct:
                        st.markdown(f"**Wix ({len(_wix_ct)})**")
                        for o in _wix_ct:
                            nro = o.get("number") or o.get("id", "")
                            bi = (
                                (o.get("billingInfo", {}) or {})
                                .get("contactDetails", {}) or {}
                            )
                            nombre_w = (
                                f"{bi.get('firstName', '') or ''} "
                                f"{bi.get('lastName', '') or ''}".strip()
                                or "(sin cliente)"
                            )
                            items_w = o.get("lineItems") or []
                            with st.expander(
                                f"#{nro} · {nombre_w} · {len(items_w)} ítems",
                                expanded=False,
                            ):
                                if items_w:
                                    filas_iw = []
                                    for li in items_w:
                                        nombre_prod = (
                                            (li.get("productName") or {}).get("translated")
                                            or (li.get("productName") or {}).get("original")
                                            or ""
                                        )
                                        cant = li.get("quantity") or 0
                                        filas_iw.append({
                                            "Prod": nombre_prod,
                                            "Cant": cant,
                                        })
                                    st.dataframe(
                                        pd.DataFrame(filas_iw),
                                        use_container_width=False,
                                        hide_index=True,
                                    )
                                else:
                                    st.caption("Sin items.")

            stk_conteo_df = db.cargar_stock(fecha=fecha_conteo)
            map_stk_conteo = (
                dict(zip(
                    stk_conteo_df["codigo"].astype(str),
                    stk_conteo_df["cantidad"].astype(float),
                )) if not stk_conteo_df.empty else {}
            )

            _n_real = sum(1 for v in map_stk_conteo.values() if float(v) > 1e-6)
            with st.expander(
                f"✏️ Stock real del {_fmt_fecha(fecha_conteo)} ({_n_real} códigos)",
                expanded=False,
            ):
                if not map_stk_conteo:
                    st.caption("Aún no se cargó stock real para esta fecha.")
                else:
                    _filas_real = [
                        {
                            "Prod": _prod_nombre.get(cod, "(desconocido)"),
                            "Cant": float(cant),
                        }
                        for cod, cant in map_stk_conteo.items()
                        if float(cant) > 1e-6
                    ]
                    if _filas_real:
                        st.dataframe(
                            pd.DataFrame(_filas_real).sort_values("Prod"),
                            use_container_width=False,
                            hide_index=True,
                        )
                    else:
                        st.caption("Aún no hay valores > 0 cargados.")

            df_editor = df_teorico_r.copy()
            df_editor["Stock"] = df_editor["Código"].astype(str).map(
                lambda c: _fmt_num_es(map_stk_conteo.get(c, 0.0))
            )

            cod_to_rubro = dict(zip(
                productos["codigo"].astype(str),
                productos.get("rubro", pd.Series([""] * len(productos))).fillna("").astype(str),
            ))

            def _split_producto(prod_str):
                s = str(prod_str)
                if " - " in s:
                    base, variante = s.rsplit(" - ", 1)
                    return base.strip(), variante.strip()
                return s, ""

            df_editor["Rubro"] = df_editor["Código"].astype(str).map(
                lambda c: (cod_to_rubro.get(c, "") or "").strip().upper()
            )
            _split_series = df_editor["Producto"].apply(_split_producto)
            df_editor["Base"] = _split_series.apply(lambda t: t[0])
            df_editor["Variante"] = _split_series.apply(lambda t: t[1])

            df_editor = df_editor[df_editor["Rubro"] != ""].copy()

            orden_rubros = [
                "HOJAS", "VERDURAS", "FRUTAS", "HIERBAS",
                "HONGOS", "BROTES", "AJIES", "CONDIMENTOS", "OTROS",
            ]
            rubros_presentes = [r for r in orden_rubros if r in df_editor["Rubro"].values]
            extras = sorted(set(df_editor["Rubro"].values) - set(orden_rubros))
            rubros_presentes += extras

            edited_por_clave = {}

            st.caption(
                "ℹ️ Los productos / rubros en :gray[**gris**] no tienen ningún "
                "valor: sin stock inicial, sin compras, sin pedidos y sin "
                "stock real cargado."
            )

            with st.form("form_conteo_fisico", clear_on_submit=False):
                guardar_conteo = st.form_submit_button(
                    "💾 Guardar Stock", type="primary", use_container_width=True,
                )
                stk_save_msg_ph = st.empty()

                def _df_tiene_mov(df):
                    if (
                        df["Stock inicial"].abs().astype(float).sum() > 1e-6
                        or df["+ Compras"].abs().astype(float).sum() > 1e-6
                        or df["− Pedidos"].abs().astype(float).sum() > 1e-6
                    ):
                        return True
                    for v in df["Stock"]:
                        try:
                            if abs(_parse_num_es(str(v))) > 1e-6:
                                return True
                        except Exception:
                            pass
                    return False

                for rubro_name in rubros_presentes:
                    df_rubro = df_editor[df_editor["Rubro"] == rubro_name]
                    n_bases = df_rubro["Base"].nunique()
                    _rubro_label_txt = f"📁 {rubro_name} ({n_bases} productos)"
                    _rubro_label = (
                        _rubro_label_txt if _df_tiene_mov(df_rubro)
                        else f":gray[{_rubro_label_txt}]"
                    )
                    with st.expander(_rubro_label, expanded=False):
                        for base_name, df_base in df_rubro.groupby("Base", sort=True):
                            n_var = len(df_base)
                            _base_label_txt = (
                                f"📦 {base_name} "
                                f"({n_var} variante{'s' if n_var != 1 else ''})"
                            )
                            label = (
                                _base_label_txt if _df_tiene_mov(df_base)
                                else f":gray[{_base_label_txt}]"
                            )
                            with st.expander(label, expanded=False):
                                _df_stk_sorted = (
                                    df_base
                                    .assign(_prio=lambda d: d["Variante"].map(_prio_unidad))
                                    .sort_values(["_prio", "Variante"]).drop(columns="_prio")
                                )
                                edited = st.data_editor(
                                    _df_stk_sorted[[
                                        "Código", "Variante",
                                        "Stock inicial", "+ Compras", "− Pedidos", "= Teórico",
                                        "Stock",
                                    ]].reset_index(drop=True),
                                    use_container_width=False,
                                    hide_index=True,
                                    disabled=[
                                        "Código", "Variante",
                                        "Stock inicial", "+ Compras", "− Pedidos", "= Teórico",
                                    ],
                                    column_order=[
                                        "Variante",
                                        "Stock inicial", "+ Compras", "− Pedidos", "= Teórico",
                                        "Stock",
                                    ],
                                    column_config={
                                        "Código": st.column_config.TextColumn("Código"),
                                        "Variante": st.column_config.TextColumn("Var"),
                                        "Stock inicial": st.column_config.NumberColumn(
                                            "S.I", format="%.2f"
                                        ),
                                        "+ Compras": st.column_config.NumberColumn(
                                            "+ Com", format="%.2f"
                                        ),
                                        "− Pedidos": st.column_config.NumberColumn(
                                            "− Ped", format="%.2f"
                                        ),
                                        "= Teórico": st.column_config.NumberColumn(
                                            "= Tot", format="%.2f"
                                        ),
                                        "Stock": st.column_config.TextColumn(
                                            "✏️ S",
                                            help="Cargá el stock real medido. Coma o punto. Vacío = 0.",
                                            required=False,
                                        ),
                                    },
                                    key=f"editor_stock_{rubro_name}_{base_name}_{fecha_conteo}",
                                )
                                edited_por_clave[(rubro_name, base_name)] = edited

            if guardar_conteo:
                valores_stock = {}
                for _clave, edited in edited_por_clave.items():
                    for _, row in edited.iterrows():
                        cod = str(row["Código"])
                        v_str = str(row.get("Stock", "") or "").strip()
                        valores_stock[cod] = (
                            _parse_num_es(v_str) if v_str else 0.0
                        )

                salida = productos[["codigo", "producto", "unidad_medida"]].copy()
                salida["cantidad"] = salida["codigo"].astype(str).map(
                    lambda c: valores_stock.get(c, 0.0)
                ).astype(float)

                try:
                    db.guardar_stock(salida, fecha_conteo)
                    try:
                        db.guardar_config(
                            {"st_teorico_fecha_conteo": str(fecha_conteo)}
                        )
                    except Exception:
                        pass
                    try:
                        ts_stk_save_ph.caption(
                            f"🕒 Último guardado de stock: **{_fmt_ts(db.ultima_carga('stock'))}**"
                        )
                    except Exception:
                        pass
                    stk_save_msg_ph.success(
                        f"✅ Stock del {_fmt_fecha(fecha_conteo)} guardado en Sheets."
                    )
                except Exception as e:
                    stk_save_msg_ph.error(f"⚠️ Error al guardar: {e}")

with tab_dux:
    dux_cfg = st.secrets.get("dux", {})
    token = dux_cfg.get("token", "")
    base_url = dux_cfg.get(
        "base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services"
    )
    id_empresa_default = int(dux_cfg.get("id_empresa", 3455))
    id_sucursal_default = int(dux_cfg.get("id_sucursal", 3))

    if not token:
        st.error(
            "Falta configurar el token de DUX en `.streamlit/secrets.toml` "
            "bajo `[dux] token = \"...\"`."
        )
    else:
        all_orders_saved = []
        selecciones_dux = db.cargar_selecciones("dux")
        try:
            all_orders_saved = _cargar_pedidos_dux_cached()
        except Exception as e:
            st.error(msg_error_sheets("leer pedidos DUX", e))

        st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('pedidos_dux'))}**")

        if all_orders_saved:
            n_asignados = sum(1 for v in selecciones_dux.values() if v)

            # Ordenar: más recientes primero
            def _fecha_dux(o):
                f = o.get("fecha") or ""
                try:
                    return pd.to_datetime(f)
                except Exception:
                    return pd.Timestamp.min
            # Sort por nro_pedido DESC (mas reciente en numero arriba).
            # Fallback -1 para los que no tengan numero parseable.
            def _nro_dux_sort(o):
                raw = _dux_get_first(
                    o, ["nro_pedido", "nroPedido", "numero", "id"]
                )
                try:
                    return int(str(raw).strip())
                except (ValueError, TypeError):
                    return -1

            all_orders_sorted = sorted(
                all_orders_saved, key=_nro_dux_sort, reverse=True
            )

            if "dux_n_show" not in st.session_state:
                st.session_state["dux_n_show"] = 50
            _dux_n_show = st.session_state["dux_n_show"]
            all_orders_sorted = all_orders_sorted[:_dux_n_show]

            if not all_orders_sorted:
                st.info("No hay pedidos sincronizados todavía.")

            with st.form(key="form_dux_seleccion", clear_on_submit=False):
                guardar_sel_dux = st.form_submit_button(
                    "💾 Guardar selección de entregas", type="primary"
                )

                nuevas_selecciones_dux = {}
                for i, orden in enumerate(all_orders_sorted, start=1):
                    cliente_str = extraer_cliente_dux(orden)
                    nro = _dux_get_first(
                        orden,
                        ["nro_pedido", "nroPedido", "numero", "id"],
                    )
                    items = extraer_items_dux(orden)

                    oid = str(orden.get("id") or nro or i)
                    asignado_prev = selecciones_dux.get(oid)
                    if asignado_prev:
                        fecha_default_entrega = pd.to_datetime(asignado_prev).date()
                    else:
                        # Default: fecha de registro del pedido (cuando se cargo en DUX).
                        # Fallback: manana.
                        f_reg = _fecha_dux(orden)
                        if f_reg and f_reg != pd.Timestamp.min:
                            fecha_default_entrega = f_reg.date()
                        else:
                            fecha_default_entrega = date.today() + timedelta(days=1)

                    estado_fact = orden.get("estado_facturacion") or ""
                    estado_badges = {
                        "PENDIENTE": "🟡 Pendiente",
                        "FACTURADO": "🟢 Facturado",
                        "FACTURADO_PARCIAL": "🟠 Fact. parcial",
                        "CERRADO": "⚫ Cerrado",
                    }
                    estado_badge = estado_badges.get(
                        estado_fact, f"⚪ {estado_fact}" if estado_fact else ""
                    )

                    es_anulado = str(orden.get("anulado", "N")).upper() == "S"
                    with st.container(border=True):
                        c_info, c_chk, c_fec = st.columns([4, 1.2, 1.6])
                        with c_info:
                            # Fecha de registro del pedido en DUX
                            f_reg_dux = _fecha_dux(orden)
                            registro_badge = ""
                            if f_reg_dux and f_reg_dux != pd.Timestamp.min:
                                registro_badge = (
                                    f" · 📅 registrado {f_reg_dux.strftime('%d/%m/%Y')}"
                                )
                            anulado_badge = " · 🚫 **ANULADO**" if es_anulado else ""
                            st.markdown(
                                f"**#{nro or i}** — {cliente_str} · "
                                f"{len(items)} ítems · {estado_badge}{registro_badge}{anulado_badge}"
                            )
                        if not es_anulado:
                            with c_chk:
                                asignar = st.checkbox(
                                    "Asignar entrega",
                                    value=bool(asignado_prev),
                                    key=f"dux_chk_{oid}",
                                )
                            with c_fec:
                                fecha_entrega = st.date_input(
                                    "Fecha de entrega",
                                    value=fecha_default_entrega,
                                    key=f"dux_fent_{oid}",
                                    format="DD/MM/YYYY",
                                    label_visibility="collapsed",
                                )

                            if asignar:
                                nuevas_selecciones_dux[oid] = str(fecha_entrega)

                        if items:
                            with st.expander("Ver productos"):
                                filas = [extraer_item_dux(it) for it in items]
                                _df_items = pd.DataFrame(filas)
                                _cols_show = [c for c in ["producto", "cantidad"] if c in _df_items.columns]
                                st.dataframe(
                                    _df_items[_cols_show],
                                    use_container_width=False,
                                    hide_index=True,
                                )

            if guardar_sel_dux:
                try:
                    db.guardar_selecciones("dux", nuevas_selecciones_dux)
                    st.success(
                        f"✅ {len(nuevas_selecciones_dux)} entregas guardadas en Sheets."
                    )
                    selecciones_dux = nuevas_selecciones_dux
                except Exception as e:
                    st.error(msg_error_sheets("guardar selecciones DUX", e))

            _total_dux = len(all_orders_saved)
            if _dux_n_show < _total_dux:
                _c1, _c2, _c3 = st.columns([2, 1, 2])
                with _c2:
                    if st.button("Cargar más", key="dux_ver_mas", type="primary", use_container_width=True):
                        st.session_state["dux_n_show"] += 50
                        st.rerun()

        else:
            st.info(
                "Todavía no hay pedidos guardados. Apretá **Sincronizar** para traerlos."
            )

if tab_dux_productos:
    with tab_dux_productos:
        ts_dux_prod_ph = st.empty()

        if not token:
            st.error("Falta configurar el token de DUX en `.streamlit/secrets.toml`.")
        else:
            sincronizar = st.button(
                "🔄 Sincronizar productos desde DUX",
                type="primary",
                key="dux_sincronizar_productos",
                use_container_width=True,
            )

            if sincronizar:
                url_pr = f"{base_url}/items"
                headers_pr = {"accept": "application/json", "authorization": token}
                page_offset = 0
                page_size = 50
                all_prods = []
                error_corte = False
                total_servidor = None

                progress = st.progress(0.0, text="Trayendo productos desde DUX...")

                while True:
                    params_pr = {
                        "offset": page_offset,
                        "limit": page_size,
                    }
                    try:
                        r = requests.get(
                            url_pr, params=params_pr, headers=headers_pr, timeout=30
                        )
                    except requests.RequestException as e:
                        st.error(msg_error_red("DUX", e))
                        error_corte = True
                        break

                    if r.status_code != 200:
                        st.error(msg_error_http("DUX", r.status_code, r.text))
                        error_corte = True
                        break

                    try:
                        d = r.json()
                    except ValueError:
                        st.error("❌ DUX devolvió una respuesta inválida. Probá de nuevo.")
                        error_corte = True
                        break

                    if isinstance(d, dict) and "message" in d and "results" not in d:
                        st.error(f"DUX respondió: {d['message']}")
                        error_corte = True
                        break

                    if isinstance(d, dict):
                        page = d.get("results", []) or []
                        if total_servidor is None:
                            total_servidor = (d.get("paging") or {}).get("total")
                    else:
                        page = []

                    if not page:
                        break

                    all_prods.extend(page)

                    if total_servidor:
                        progress.progress(
                            min(1.0, len(all_prods) / total_servidor),
                            text=f"{len(all_prods)} / {total_servidor}",
                        )

                    if len(page) < page_size:
                        break
                    page_offset += page_size
                    time.sleep(DUX_RATE_LIMIT_SECONDS)

                progress.empty()

                if not error_corte:
                    if not all_prods:
                        st.warning("No hay productos en DUX.")
                    else:
                        filas = []
                        for p in all_prods:
                            nombre = str(p.get("item", "")).strip()
                            if " - " in nombre:
                                unidad = nombre.rsplit(" - ", 1)[1].strip()
                            else:
                                unidad = ""
                            rubro_obj = p.get("rubro") or {}
                            rubro_nombre = str(rubro_obj.get("nombre", "") or "").strip()
                            filas.append(
                                {
                                    "codigo": str(p.get("cod_item", "")).strip(),
                                    "producto": nombre,
                                    "unidad_medida": unidad,
                                    "descripcion": "",
                                    "rubro": rubro_nombre,
                                }
                            )

                        df_nuevo = (
                            pd.DataFrame(filas)
                            .sort_values("codigo")
                            .reset_index(drop=True)
                        )

                        db.guardar_productos(df_nuevo)

                        st.success(
                            f"✅ Sincronizado. {len(df_nuevo)} productos guardados en Sheets."
                        )

            st.divider()
            st.subheader("📋 Productos cargados")

            try:
                df_csv_actual = db.cargar_productos()
                if not df_csv_actual.empty:
                    cols_mostrar = [
                        c
                        for c in ["codigo", "producto", "unidad_medida", "rubro"]
                        if c in df_csv_actual.columns
                    ]
                    st.caption(f"{len(df_csv_actual)} productos en Sheets.")

                    df_show = df_csv_actual[cols_mostrar].sort_values("producto").reset_index(drop=True)
                    opciones_dxp = df_show["producto"].astype(str).tolist()
                    filtro_prod_dxp = st.multiselect(
                        "Producto",
                        options=opciones_dxp,
                        key="dxp_filtro_prod_sel",
                    )
                    if filtro_prod_dxp:
                        df_show = df_show[
                            df_show["producto"].astype(str).isin(filtro_prod_dxp)
                        ].reset_index(drop=True)

                    st.dataframe(
                        df_show,
                        use_container_width=False,
                        hide_index=True,
                    )
                else:
                    st.info(
                        "Todavía no hay productos en Sheets. Apretá **Sincronizar**."
                    )
            except Exception as e:
                st.error(msg_error_sheets("leer productos", e))

        ts_dux_prod = db.ultima_carga("dux_productos")
        ts_dux_prod_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_dux_prod)}**")

if tab_dux_rubros:
    with tab_dux_rubros:
        ts_dux_rubros_ph = st.empty()

        if not token:
            st.error("Falta configurar el token de DUX en `.streamlit/secrets.toml`.")
        else:
            # ---- RUBROS Y SUBRUBROS (un solo endpoint) ----
            st.subheader("Rubros y Subrubros")
            sincronizar_rubros = st.button(
                "🔄 Sincronizar desde DUX",
                type="primary",
                key="dux_sincronizar_rubros",
                use_container_width=True,
            )

            if sincronizar_rubros:
                url_sr = f"{base_url}/subrubros"
                headers_sr = {"accept": "application/json", "authorization": token}
                params_sr = {"id_empresa": id_empresa_default}
                try:
                    resp_sr = requests.get(url_sr, headers=headers_sr, params=params_sr, timeout=30)
                except requests.RequestException as e:
                    st.error(msg_error_red("DUX", e))
                    resp_sr = None

                if resp_sr is not None:
                    if resp_sr.status_code != 200:
                        st.error(msg_error_http("DUX", resp_sr.status_code, resp_sr.text))
                    else:
                        try:
                            data_sr = resp_sr.json()
                        except ValueError:
                            data_sr = None
                            st.error("❌ DUX devolvió una respuesta inválida.")

                        if data_sr is not None:
                            items_sr = data_sr if isinstance(data_sr, list) else data_sr.get("results", [])

                            # Rubros únicos extraídos del mismo endpoint
                            rubros_vistos = {}
                            for sr in (items_sr or []):
                                rid = sr.get("id_rubro")
                                if rid is not None and rid not in rubros_vistos:
                                    rubros_vistos[rid] = str(sr.get("rubro", "") or "").strip()
                            registros_r = [{"id": rid, "nombre": nombre} for rid, nombre in rubros_vistos.items()]
                            db.guardar_rubros(registros_r)

                            # Subrubros: id único = id_rubro * 10000 + id_sub_rubro
                            registros_sr = []
                            for sr in (items_sr or []):
                                rid = sr.get("id_rubro")
                                sid = sr.get("id_sub_rubro")
                                if rid is None or sid is None:
                                    continue
                                registros_sr.append({
                                    "id":          rid * 10000 + sid,
                                    "nombre":      str(sr.get("sub_rubro", "") or "").strip(),
                                    "rubro_id":    rid,
                                    "rubro_nombre": str(sr.get("rubro", "") or "").strip(),
                                })
                            db.guardar_subrubros(registros_sr)
                            st.success(f"✅ {len(registros_r)} rubros y {len(registros_sr)} subrubros sincronizados.")

            st.divider()
            _rc, _src = st.columns(2)
            with _rc:
                st.caption("Rubros")
                try:
                    df_rubros = db.cargar_rubros()
                    if not df_rubros.empty:
                        st.dataframe(df_rubros[["nombre"]].sort_values("nombre").reset_index(drop=True), use_container_width=True, hide_index=True)
                    else:
                        st.info("Sin rubros.")
                except Exception as e:
                    st.error(msg_error_sheets("leer rubros", e))
            with _src:
                st.caption("Subrubros")
                try:
                    df_subrubros = db.cargar_subrubros()
                    if not df_subrubros.empty:
                        cols_sr = [c for c in ["rubro_nombre", "nombre"] if c in df_subrubros.columns]
                        st.dataframe(df_subrubros[cols_sr].sort_values(["rubro_nombre", "nombre"]).reset_index(drop=True), use_container_width=True, hide_index=True)
                    else:
                        st.info("Sin subrubros.")
                except Exception as e:
                    st.error(msg_error_sheets("leer subrubros", e))

        ts_dux_rubros = db.ultima_carga("dux_rubros")
        ts_dux_rubros_ph.caption(f"🕒 Última actualización rubros: **{_fmt_ts(ts_dux_rubros)}**")

with tab_wix:
    wix_cfg = st.secrets.get("wix", {})
    wix_token = wix_cfg.get("api_key", "")
    wix_account = wix_cfg.get("account_id", "")
    wix_site = wix_cfg.get("site_id", "")

    if not wix_token or not wix_account or not wix_site:
        st.error(
            "Falta configurar las credenciales de Wix en `.streamlit/secrets.toml`."
        )
    else:
        try:
            wix_orders_saved = db.cargar_pedidos_wix()
        except Exception as e:
            st.error(msg_error_sheets("leer pedidos Wix", e))
            wix_orders_saved = []

        st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('pedidos_wix'))}**")

        orders_saved = wix_orders_saved or []
        selecciones = db.cargar_selecciones("wix")

        if not orders_saved:
            st.info("Todavía no hay pedidos. Apretá **Sincronizar**.")
        else:
            pass

            def _wix_contact(o):
                bi = (o.get("billingInfo", {}) or {}).get("contactDetails", {}) or {}
                if bi.get("firstName") or bi.get("lastName"):
                    return bi
                si = (
                    ((o.get("shippingInfo", {}) or {}).get("logistics", {}) or {})
                    .get("shippingDestination", {})
                    .get("contactDetails", {})
                ) or {}
                if si.get("firstName") or si.get("lastName"):
                    return si
                return (o.get("buyerInfo", {}) or {}).get("contactDetails", {}) or {}

            def _wix_address(o):
                bi = (o.get("billingInfo", {}) or {}).get("address", {}) or {}
                if bi.get("addressLine") or bi.get("city"):
                    return bi
                si = (
                    ((o.get("shippingInfo", {}) or {}).get("logistics", {}) or {})
                    .get("shippingDestination", {})
                    .get("address", {})
                ) or {}
                return si or bi

            def _fmt_addr(a):
                if not a:
                    return ""
                parts = [
                    a.get("addressLine"),
                    a.get("addressLine2"),
                    a.get("city"),
                    a.get("subdivision"),
                ]
                return ", ".join(p for p in parts if p)

            def _wix_cliente(o):
                c = _wix_contact(o)
                nombre = ((c.get("firstName") or "") + " " + (c.get("lastName") or "")).strip()
                return nombre or "(sin nombre)"

            def _wix_email(o):
                return (
                    (o.get("buyerInfo", {}) or {}).get("email")
                    or _wix_contact(o).get("email")
                    or ""
                )

            def _wix_nro(o):
                return str(o.get("number") or o.get("id", "?"))

            # Ordenar Wix: más recientes primero (createdDate)
            def _fecha_wix(o):
                f = o.get("createdDate") or ""
                try:
                    ts = pd.to_datetime(f)
                    # Wix devuelve fechas en UTC con tz: las convierto a naive
                    # para poder comparar con Timestamps locales sin tz.
                    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                        ts = ts.tz_localize(None)
                    return ts
                except Exception:
                    return pd.Timestamp.min
            # Sort por number (Wix) DESC.
            def _nro_wix_sort(o):
                raw = o.get("number") or o.get("id") or ""
                try:
                    return int(str(raw).strip())
                except (ValueError, TypeError):
                    return -1

            orders_saved_sorted = sorted(
                orders_saved, key=_nro_wix_sort, reverse=True
            )

            # Mostrar los ultimos 100 por number (independiente de fecha).
            orders_saved_sorted = orders_saved_sorted[:100]

            if not orders_saved_sorted:
                st.info("No hay pedidos sincronizados todavía.")

            with st.form(key="form_wix_seleccion", clear_on_submit=False):
                guardar_sel = st.form_submit_button(
                    "💾 Guardar selección de entregas", type="primary"
                )

                nuevas_selecciones = {}
                for o in orders_saved_sorted:
                    nro = _wix_nro(o)
                    cliente = _wix_cliente(o)
                    items = o.get("lineItems", [])
                    total = (
                        o.get("priceSummary", {}).get("total", {}).get("formattedAmount", "")
                    )
                    direccion = _fmt_addr(_wix_address(o))
                    email = _wix_email(o)

                    oid = o.get("id") or nro
                    asignado_prev = selecciones.get(oid)
                    if asignado_prev:
                        fecha_default_entrega = pd.to_datetime(asignado_prev).date()
                    else:
                        # Default: fecha de creacion del pedido (Wix createdDate).
                        # Fallback: manana.
                        f_reg = _fecha_wix(o)
                        if f_reg and f_reg != pd.Timestamp.min:
                            fecha_default_entrega = f_reg.date()
                        else:
                            fecha_default_entrega = date.today() + timedelta(days=1)

                    es_cancelado = str(o.get("status", "")).upper() == "CANCELED"
                    _pay_badges = {
                        "PAID": "🟢 Pagado",
                        "UNPAID": "🔴 Sin pagar",
                        "PENDING": "🟡 Pago pendiente",
                        "PARTIALLY_REFUNDED": "🟠 Parcialmente reembolsado",
                        "FULLY_REFUNDED": "⚫ Reembolsado",
                    }
                    _ful_badges = {
                        "FULFILLED": "✅ Entregado",
                        "NOT_FULFILLED": "⏳ No entregado",
                        "PARTIALLY_FULFILLED": "🔶 Entrega parcial",
                    }
                    pay_badge = _pay_badges.get(str(o.get("paymentStatus") or "").upper(), "")
                    ful_badge = _ful_badges.get(str(o.get("fulfillmentStatus") or "").upper(), "")
                    buyer_note = o.get("buyerNote") or ""
                    with st.container(border=True):
                        c_info, c_chk, c_fec = st.columns([4, 1.2, 1.6])
                        with c_info:
                            f_reg_wix = _fecha_wix(o)
                            registro_badge = ""
                            if f_reg_wix and f_reg_wix != pd.Timestamp.min:
                                registro_badge = f" · 📅 {f_reg_wix.strftime('%d/%m/%Y')}"
                            cancelado_badge = " · 🚫 **CANCELADO**" if es_cancelado else ""
                            badges_line = " · ".join(b for b in [pay_badge, ful_badge] if b)
                            st.markdown(
                                f"**#{nro}** — {cliente} · {len(items)} ítems · "
                                f"**{total}**{registro_badge}{cancelado_badge}"
                                + (f" · {badges_line}" if badges_line else "")
                            )
                            detalles = []
                            if direccion:
                                detalles.append(f"📍 {direccion}")
                            if email:
                                detalles.append(f"✉️ {email}")
                            if buyer_note:
                                detalles.append(f"💬 {buyer_note}")
                            if detalles:
                                st.caption(" · ".join(detalles))
                        if not es_cancelado:
                            with c_chk:
                                asignar = st.checkbox(
                                    "Asignar entrega",
                                    value=bool(asignado_prev),
                                    key=f"wix_chk_{oid}",
                                )
                            with c_fec:
                                fecha_entrega = st.date_input(
                                    "Fecha de entrega",
                                    value=fecha_default_entrega,
                                    key=f"wix_fent_{oid}",
                                    format="DD/MM/YYYY",
                                    label_visibility="collapsed",
                                )

                            if asignar:
                                nuevas_selecciones[oid] = str(fecha_entrega)

                        if items:
                            with st.expander("Ver productos"):
                                filas = []
                                for it in items:
                                    nombre_obj = it.get("productName", {}) or {}
                                    nombre = (
                                        nombre_obj.get("original")
                                        or nombre_obj.get("translated")
                                        or ""
                                    )
                                    price_obj = it.get("price") or {}
                                    filas.append(
                                        {
                                            "producto": nombre,
                                            "cantidad": it.get("quantity", 0),
                                            "precio unit.": price_obj.get("formattedAmount") or "",
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(filas),
                                    use_container_width=False,
                                    hide_index=True,
                                )

            if guardar_sel:
                try:
                    db.guardar_selecciones("wix", nuevas_selecciones)
                    selecciones = nuevas_selecciones
                    st.success(f"✅ {len(nuevas_selecciones)} entregas guardadas.")
                except Exception as e:
                    st.error(msg_error_sheets("guardar selecciones Wix", e))

if tab_wix_productos:
    with tab_wix_productos:
        ts_wix_prod_ph = st.empty()

        wix_cfg_p = st.secrets.get("wix", {})
        wix_token_p = wix_cfg_p.get("api_key", "")
        wix_account_p = wix_cfg_p.get("account_id", "")
        wix_site_p = wix_cfg_p.get("site_id", "")

        if not wix_token_p or not wix_account_p or not wix_site_p:
            st.error("Faltan credenciales de Wix en `.streamlit/secrets.toml`.")
        else:
            sincronizar_wix_p = st.button(
                "🔄 Sincronizar productos desde Wix",
                type="primary",
                key="wix_sincronizar_productos",
                use_container_width=True,
            )

            if sincronizar_wix_p:
                url_wp = "https://www.wixapis.com/stores/v1/products/query"
                headers_wp = {
                    "Authorization": wix_token_p,
                    "wix-account-id": wix_account_p,
                    "wix-site-id": wix_site_p,
                    "Content-Type": "application/json",
                }
                all_wix_prods = []
                page_offset = 0
                page_size = 100
                error_corte = False
                total_servidor = None

                progress = st.progress(0.0, text="Trayendo productos desde Wix...")

                while True:
                    body_wp = {
                        "query": {
                            "paging": {"limit": page_size, "offset": page_offset}
                        }
                    }
                    try:
                        r = requests.post(
                            url_wp, json=body_wp, headers=headers_wp, timeout=30
                        )
                    except requests.RequestException as e:
                        st.error(msg_error_red("Wix", e))
                        error_corte = True
                        break

                    if r.status_code != 200:
                        st.error(msg_error_http("Wix", r.status_code, r.text))
                        error_corte = True
                        break

                    try:
                        d = r.json()
                    except ValueError:
                        st.error("❌ Wix devolvió una respuesta inválida. Probá de nuevo.")
                        error_corte = True
                        break

                    page = d.get("products", []) if isinstance(d, dict) else []
                    if total_servidor is None:
                        total_servidor = d.get("totalResults") if isinstance(d, dict) else None

                    if not page:
                        break

                    all_wix_prods.extend(page)

                    if total_servidor:
                        progress.progress(
                            min(1.0, len(all_wix_prods) / total_servidor),
                            text=f"{len(all_wix_prods)} / {total_servidor}",
                        )

                    if len(page) < page_size:
                        break
                    page_offset += page_size

                progress.empty()

                if not error_corte:
                    if not all_wix_prods:
                        st.warning("Wix no devolvió productos.")
                    else:
                        filas = []
                        for p in all_wix_prods:
                            filas.append(
                                {
                                    "wix_id": p.get("id", ""),
                                    "producto": p.get("name", ""),
                                    "descripcion": (p.get("description") or "").strip(),
                                }
                            )
                        df_wix_prods = (
                            pd.DataFrame(filas)
                            .sort_values("producto")
                            .reset_index(drop=True)
                        )
                        db.guardar_wix_productos(df_wix_prods)
                        st.success(
                            f"✅ Sincronizado. {len(df_wix_prods)} productos guardados en Sheets."
                        )

            st.divider()
            st.subheader("📋 Productos cargados")

            try:
                df_wix_csv = db.cargar_wix_productos()
                if not df_wix_csv.empty:
                    st.caption(f"{len(df_wix_csv)} productos en Sheets.")

                    df_show_wp = df_wix_csv.copy()
                    if "descripcion" not in df_show_wp.columns:
                        df_show_wp["descripcion"] = ""
                    opciones_wxp = sorted(df_show_wp["producto"].dropna().astype(str).unique().tolist())
                    filtro_prod_wxp = st.multiselect(
                        "Producto",
                        options=opciones_wxp,
                        key="wxp_filtro_prod_sel",
                    )
                    if filtro_prod_wxp:
                        df_show_wp = df_show_wp[
                            df_show_wp["producto"].astype(str).isin(filtro_prod_wxp)
                        ].reset_index(drop=True)

                    st.dataframe(
                        df_show_wp[["wix_id", "producto", "descripcion"]],
                        use_container_width=False,
                        hide_index=True,
                        column_config={
                            "wix_id": st.column_config.TextColumn("ID Wix"),
                            "producto": st.column_config.TextColumn("Producto"),
                            "descripcion": st.column_config.TextColumn("Descripción"),
                        },
                    )
                else:
                    st.info("Todavía no hay productos Wix en Sheets. Apretá **Sincronizar**.")
            except Exception as e:
                st.error(msg_error_sheets("leer productos Wix", e))

        ts_wix_prod = db.ultima_carga("wix_productos")
        ts_wix_prod_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_wix_prod)}**")

if tab_proveedores:
    with tab_proveedores:
        ts_prov_ph = st.empty()

        st.markdown(
            "Subí el **Excel exportado desde DUX**. **Pisa todo lo cargado anteriormente.**"
        )

        SCHEMA_PROV = [
            "proveedor_id", "proveedor", "nombre_fantasia", "categoria_fiscal",
            "tipo_documento", "numero_documento", "cuit_cuil", "codigo",
            "email", "provincia", "localidad", "barrio", "domicilio",
            "telefono", "celular", "condicion_pago", "fecha_creacion",
            "persona_contacto", "lugar_entrega", "tipo_comprobante", "habilitado",
        ]
        # Mapeo de columnas del Excel de DUX → columnas del schema.
        # Las claves del alias estan normalizadas: lowercase + espacios colapsados.
        ALIAS_PROV = {
            "proveedor_id": ["id"],
            "proveedor": ["proveedor", "razon social", "razon_social"],
            "nombre_fantasia": ["nombre de fantasia", "nombre fantasia"],
            "categoria_fiscal": ["categoria fiscal"],
            "tipo_documento": ["tipo documento"],
            "numero_documento": ["numero documento", "nro documento"],
            "cuit_cuil": ["cuit/cuil", "cuit_cuil", "cuit", "cuil"],
            "codigo": ["codigo"],
            "email": ["correo electronico", "email", "mail", "e-mail", "correo"],
            "provincia": ["provincia"],
            "localidad": ["localidad"],
            "barrio": ["barrio"],
            "domicilio": ["domicilio", "direccion"],
            "telefono": ["telefono", "tel"],
            "celular": ["celular", "movil"],
            "condicion_pago": ["condicion pago", "condicion de pago"],
            "fecha_creacion": ["fecha creacion"],
            "persona_contacto": ["persona contacto", "contacto"],
            "lugar_entrega": ["lugar entrega por defecto", "lugar entrega"],
            "tipo_comprobante": ["tipo comprobante por defecto", "tipo comprobante"],
            "habilitado": ["habilitado"],
        }

        def _normalizar_col(c):
            # Lower + sin acentos + espacios colapsados (DUX exporta 'Condición  Pago' con doble espacio)
            s = str(c).strip().lower()
            # Sacar tildes basicas
            for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                         ("ñ", "n")):
                s = s.replace(a, b)
            # Colapsar espacios multiples
            s = " ".join(s.split())
            return s

        archivo_prov = st.file_uploader(
            "Subir Excel (.xlsx) o CSV",
            type=["xlsx", "xls", "csv"],
            key="upload_proveedores",
        )

        if archivo_prov is not None:
            try:
                if archivo_prov.name.lower().endswith(".csv"):
                    df_excel = pd.read_csv(archivo_prov, dtype=str).fillna("")
                else:
                    df_excel = pd.read_excel(archivo_prov, dtype=str).fillna("")

                df_excel.columns = [_normalizar_col(c) for c in df_excel.columns]

                df_norm = pd.DataFrame()
                cols_no_encontradas = []
                for destino, aliases in ALIAS_PROV.items():
                    col_found = next(
                        (a for a in aliases if a in df_excel.columns),
                        None,
                    )
                    if col_found:
                        df_norm[destino] = df_excel[col_found].astype(str).fillna("")
                    else:
                        df_norm[destino] = ""
                        cols_no_encontradas.append(destino)

                if cols_no_encontradas:
                    st.caption(
                        "ℹ️ Columnas del schema sin equivalente en el Excel "
                        f"(quedan vacías): {', '.join(cols_no_encontradas)}"
                    )

                st.caption(f"Previa ({len(df_norm)} filas):")
                st.dataframe(
                    df_norm[["proveedor_id", "proveedor", "cuit_cuil", "telefono",
                             "celular", "email", "localidad"]].head(20),
                    use_container_width=False,
                    hide_index=True,
                )

                if st.button(
                    f"💾 Guardar {len(df_norm)} proveedores",
                    type="primary",
                    key="confirmar_subir_proveedores",
                ):
                    try:
                        db.guardar_proveedores(df_norm)
                        st.success(f"✅ {len(df_norm)} proveedores guardados.")
                    except Exception as e:
                        st.error(msg_error_sheets("guardar proveedores", e))
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")

        st.divider()
        try:
            df_prov_csv = db.cargar_proveedores()
            if not df_prov_csv.empty:
                df_prov_show = df_prov_csv.copy()
                for c in SCHEMA_PROV:
                    if c not in df_prov_show.columns:
                        df_prov_show[c] = ""
                opciones_prv = sorted(
                    df_prov_show["proveedor"].dropna().astype(str).unique().tolist()
                )
                filtro_prov_sel = st.multiselect(
                    "Proveedor",
                    options=opciones_prv,
                    key="prv_filtro_sel",
                )
                if filtro_prov_sel:
                    df_prov_show = df_prov_show[
                        df_prov_show["proveedor"].astype(str).isin(filtro_prov_sel)
                    ].reset_index(drop=True)
                st.caption(f"{len(df_prov_show)} de {len(df_prov_csv)} proveedores.")
                st.dataframe(
                    df_prov_show[SCHEMA_PROV],
                    use_container_width=False,
                    hide_index=True,
                    column_config={
                        "proveedor_id": st.column_config.TextColumn("ID"),
                        "proveedor": st.column_config.TextColumn("Proveedor"),
                        "nombre_fantasia": st.column_config.TextColumn("Nombre Fantasía"),
                        "categoria_fiscal": st.column_config.TextColumn("Cat. Fiscal"),
                        "tipo_documento": st.column_config.TextColumn("Tipo Doc"),
                        "numero_documento": st.column_config.TextColumn("Nº Doc"),
                        "cuit_cuil": st.column_config.TextColumn("CUIT/CUIL"),
                        "codigo": st.column_config.TextColumn("Código"),
                        "email": st.column_config.TextColumn("Email"),
                        "provincia": st.column_config.TextColumn("Provincia"),
                        "localidad": st.column_config.TextColumn("Localidad"),
                        "barrio": st.column_config.TextColumn("Barrio"),
                        "domicilio": st.column_config.TextColumn("Domicilio"),
                        "telefono": st.column_config.TextColumn("Teléfono"),
                        "celular": st.column_config.TextColumn("Celular"),
                        "condicion_pago": st.column_config.TextColumn("Cond. Pago"),
                        "fecha_creacion": st.column_config.TextColumn("Creación"),
                        "persona_contacto": st.column_config.TextColumn("Contacto"),
                        "lugar_entrega": st.column_config.TextColumn("Lugar Entrega"),
                        "tipo_comprobante": st.column_config.TextColumn("Tipo Comprob"),
                        "habilitado": st.column_config.TextColumn("Habilitado"),
                    },
                )
            else:
                st.info("Todavía no hay proveedores. Subí un Excel arriba.")
        except Exception as e:
            st.error(msg_error_sheets("leer proveedores", e))

        ts_prov = db.ultima_carga("proveedores")
        ts_prov_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_prov)}**")

if tab_eg_compras:
    with tab_eg_compras:
        st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('comprobantes_compra'))}**")

        # Visualización de compras sincronizadas
        try:
            df_compras_all = db.cargar_compras()
        except Exception as e:
            st.error(msg_error_sheets("leer compras", e))
            df_compras_all = pd.DataFrame()

        if df_compras_all.empty:
            st.info("Todavía no hay compras sincronizadas. Apretá **Sincronizar**.")
        else:
            df_compras_all["subtotal"] = (
                pd.to_numeric(df_compras_all["cantidad"], errors="coerce").fillna(0)
                * pd.to_numeric(df_compras_all["precio"], errors="coerce").fillna(0)
            )
            grupos = df_compras_all.groupby(
                ["comprobante", "fecha", "proveedor_nombre", "condicion_pago"],
                dropna=False, sort=False,
            )
            comprobantes = sorted(grupos.groups.keys(), key=lambda k: str(k[1]), reverse=True)
            st.caption(f"{len(comprobantes)} comprobantes sincronizados")
            for key in comprobantes:
                nro_comp, fecha_c, proveedor_c, cond_pago_c = key
                df_grupo = grupos.get_group(key)
                total_c = float(df_grupo["subtotal"].sum())
                n_items = len(df_grupo)
                with st.expander(f"#{nro_comp or '—'} — {proveedor_c or '—'} — {_fmt_fecha(fecha_c)} — {n_items} ítem{'s' if n_items!=1 else ''} — $ {total_c:,.0f}"):
                    filas_items = [{
                        "Producto":    str(r.get("producto_nombre", "")),
                        "Cantidad":    float(r.get("cantidad", 0) or 0),
                        "Precio unit.": float(r.get("precio", 0) or 0),
                        "Subtotal":    float(r.get("subtotal", 0) or 0),
                    } for _, r in df_grupo.iterrows()]
                    st.dataframe(pd.DataFrame(filas_items), use_container_width=True, hide_index=True,
                                 column_config={
                                     "Precio unit.": st.column_config.NumberColumn("Precio unit.", format="$ %.2f"),
                                     "Subtotal":     st.column_config.NumberColumn("Subtotal",     format="$ %.2f"),
                                 })

if tab_eg_gastos:
    with tab_eg_gastos:
        st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('gastos'))}**")

        # Display gastos guardados
        try:
            gastos_saved = db.cargar_gastos()
        except Exception as e:
            st.error(msg_error_sheets("leer gastos", e))
            gastos_saved = []

        if not gastos_saved:
            st.info("Todavía no hay gastos. Andá a **🔄 Sincronizar**.")
        else:
            gastos_sorted = sorted(gastos_saved, key=lambda g: g.get("fecha") or "", reverse=True)
            _total_gas = sum(float(g.get("total") or 0) for g in gastos_sorted)
            st.caption(f"{len(gastos_sorted)} gastos · Total: **$ {_total_gas:,.0f}**")
            _rows = [{
                "Comprobante": g.get("nro_comprobante") or "—",
                "Fecha":       _fmt_fecha(g.get("fecha")),
                "Proveedor":   g.get("proveedor") or "—",
                "Rubro":       " / ".join(filter(None, [g.get("rubro_nombre"), g.get("sub_rubro_nombre")])) or g.get("gasto") or "—",
                "Items":       ", ".join(d.get("item","") for d in (g.get("detalles") or []) if (d.get("item") or "").strip()),
                "Total":       float(g.get("total") or 0),
            } for g in gastos_sorted]
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                         column_config={"Total": st.column_config.NumberColumn("Total", format="$ %.0f")})

if tab_eg_pagos:
    with tab_eg_pagos:
        st.caption(f"🕒 Última sync: **{_fmt_ts(db.ultima_carga('pagos_proveedores'))}**")

        try:
            pagos_saved = db.cargar_pagos_proveedores()
        except Exception as e:
            st.error(msg_error_sheets("leer pagos proveedores", e))
            pagos_saved = []

        if not pagos_saved:
            st.info("Todavía no hay pagos. Andá a **🔄 Sincronizar**.")
        else:
            pagos_sorted = sorted(pagos_saved, key=lambda p: p.get("fecha") or "", reverse=True)
            _total_pag = sum(float(p.get("monto") or 0) for p in pagos_sorted)
            st.caption(f"{len(pagos_sorted)} pagos · Total: **$ {_total_pag:,.0f}**")
            _rows = []
            for _p in pagos_sorted:
                _imput = _p.get("imputaciones") or []
                _comps = ", ".join(
                    str(i.get("nro_comprobante","")).strip()
                    for i in _imput if i.get("nro_comprobante")
                ) or "—"
                _rows.append({
                    "Pago #":       _p.get("nro_comprobante") or "—",
                    "Fecha":        _fmt_fecha(_p.get("fecha")),
                    "Proveedor":    _p.get("proveedor") or "—",
                    "Comprobantes": _comps,
                    "Monto":        float(_p.get("monto") or 0),
                })
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                         column_config={"Monto": st.column_config.NumberColumn("Monto", format="$ %.0f")})

with tab_mapeo:
    ts_mapeo_ph = st.empty()
    ts_mapeo_ph.caption(
        f"🕒 Última actualización: **{_fmt_ts(db.ultima_carga('mapping_wix_dux'))}**"
    )

    st.info(
        "Mapeá cada producto de Wix con su equivalente en DUX. "
        "Lo que no tenga equivalente, dejalo en **(sin mapear)**."
    )

    df_dux_p = db.cargar_productos()
    df_wix_p = db.cargar_wix_productos()
    falta_dux = df_dux_p.empty
    falta_wix = df_wix_p.empty

    if falta_dux or falta_wix:
        faltantes = []
        if falta_dux:
            faltantes.append("📡 DUX Productos")
        if falta_wix:
            faltantes.append("🛍️ Wix Productos")
        st.warning(
            "Antes de mapear necesitás sincronizar: " + " y ".join(faltantes) + "."
        )
    else:
        df_wix_p["wix_id"] = df_wix_p["wix_id"].astype(str)
        df_wix_p["producto"] = df_wix_p["producto"].astype(str)
        # Excluir packs (gestionados en pestaña 🎁 Packs Wix). Detectados por prefijo "PACK".
        df_wix_p = df_wix_p[
            ~df_wix_p["producto"].str.upper().str.startswith("PACK")
        ]
        df_wix_p = df_wix_p.sort_values("producto").reset_index(drop=True)

        mapping_actual = {}
        factor_actual = {}
        df_map = db.cargar_mapping_wix_dux()
        if not df_map.empty:
            mapping_actual = dict(
                zip(df_map["wix_id"].astype(str), df_map["dux_codigo"].astype(str))
            )
            for wid, f in zip(df_map["wix_id"].astype(str), df_map.get("factor", [])):
                try:
                    factor_actual[wid] = float(f)
                except (ValueError, TypeError):
                    factor_actual[wid] = 1.0

        opciones_dux = ["(sin mapear)"] + [
            f"{c} - {p}"
            for c, p in zip(
                df_dux_p["codigo"].astype(str), df_dux_p["producto"].astype(str)
            )
        ]
        label_to_codigo = {
            f"{c} - {p}": c
            for c, p in zip(
                df_dux_p["codigo"].astype(str), df_dux_p["producto"].astype(str)
            )
        }
        codigo_to_label = {v: k for k, v in label_to_codigo.items()}

        mapeados = sum(1 for v in mapping_actual.values() if v)
        st.caption(
            f"{mapeados} / {len(df_wix_p)} productos mapeados"
        )

        with st.form(key="form_mapeo_wix_dux", clear_on_submit=False):
            guardar_map = st.form_submit_button(
                "💾 Guardar mapeo", type="primary"
            )

            nuevo_mapping = {}
            nuevo_factor = {}
            for _, row in df_wix_p.iterrows():
                wid = str(row["wix_id"])
                wname = str(row["producto"])

                current_codigo = mapping_actual.get(wid, "")

                default_idx = 0
                if current_codigo and current_codigo in codigo_to_label:
                    try:
                        default_idx = opciones_dux.index(
                            codigo_to_label[current_codigo]
                        )
                    except ValueError:
                        default_idx = 0

                default_factor = float(factor_actual.get(wid, 1.0))

                col_a, col_b, col_c = st.columns([2, 2, 1])
                with col_a:
                    st.markdown(f"**{wname}**")
                    st.caption(f"Wix ID: `{wid}`")
                with col_b:
                    sel = st.selectbox(
                        "DUX equivalente",
                        opciones_dux,
                        index=default_idx,
                        key=f"map_{wid}",
                        label_visibility="collapsed",
                    )
                with col_c:
                    factor_val = st.number_input(
                        "Factor",
                        value=default_factor,
                        min_value=0.0,
                        step=0.25,
                        format="%.4f",
                        key=f"factor_{wid}",
                        label_visibility="collapsed",
                    )

                if sel != "(sin mapear)":
                    nuevo_mapping[wid] = label_to_codigo[sel]
                    nuevo_factor[wid] = float(factor_val)

        if guardar_map:
            merged_map = nuevo_mapping
            merged_factor = nuevo_factor

            map_prod_dux = dict(
                zip(df_dux_p["codigo"].astype(str), df_dux_p["producto"].astype(str))
            )
            map_prod_wix = dict(zip(df_wix_p["wix_id"], df_wix_p["producto"]))

            rows = []
            for wid, code in merged_map.items():
                if not code:
                    continue
                rows.append(
                    {
                        "wix_id": wid,
                        "wix_producto": map_prod_wix.get(wid, ""),
                        "dux_codigo": code,
                        "dux_producto": map_prod_dux.get(code, ""),
                        "factor": merged_factor.get(wid, 1.0),
                    }
                )

            df_to_save = pd.DataFrame(
                rows,
                columns=[
                    "wix_id",
                    "wix_producto",
                    "dux_codigo",
                    "dux_producto",
                    "factor",
                ],
            )
            db.guardar_mapping_wix_dux(df_to_save)
            try:
                ts_mapeo_ph.caption(
                    f"🕒 Última actualización: **{_fmt_ts(db.ultima_carga('mapping_wix_dux'))}**"
                )
            except Exception:
                pass
            st.success(f"✅ {len(rows)} mapeos guardados en Sheets.")

with tab_packs:
    ts_packs_ph = st.empty()

    df_wix_p_packs = db.cargar_wix_productos()
    df_dux_p_packs = db.cargar_productos()

    if df_wix_p_packs.empty:
        st.warning("Falta sincronizar 🛍️ Wix Productos primero.")
    elif df_dux_p_packs.empty:
        st.warning("Falta sincronizar 📡 DUX Productos primero.")
    else:
        df_packs = df_wix_p_packs[
            df_wix_p_packs["producto"].astype(str).str.upper().str.startswith("PACK")
        ].copy()

        if df_packs.empty:
            st.warning("No se encontraron productos PACK en Wix.")
        else:
            opciones_dux_pack = [
                f"{c} - {p}"
                for c, p in zip(
                    df_dux_p_packs["codigo"].astype(str),
                    df_dux_p_packs["producto"].astype(str),
                )
            ]
            label_to_cod = {
                f"{c} - {p}": (c, p)
                for c, p in zip(
                    df_dux_p_packs["codigo"].astype(str),
                    df_dux_p_packs["producto"].astype(str),
                )
            }

            df_packs_saved = db.cargar_packs_wix()

            with st.form("form_packs", clear_on_submit=False, border=False):
                guardar_packs = st.form_submit_button(
                    "💾 Guardar packs", type="primary"
                )

                editor_outputs = {}
                for _, pack_row in df_packs.iterrows():
                    pack_id = str(pack_row["wix_id"])
                    pack_nombre = str(pack_row["producto"])

                    st.markdown(f"### 🎁 {pack_nombre}")

                    comp_actual = df_packs_saved[
                        df_packs_saved["wix_id_pack"].astype(str) == pack_id
                    ]
                    if not comp_actual.empty:
                        comp_view = pd.DataFrame(
                            {
                                "producto": [
                                    f"{c} - {p}"
                                    for c, p in zip(
                                        comp_actual["dux_codigo"].astype(str),
                                        comp_actual["dux_producto"].astype(str),
                                    )
                                ],
                                "cantidad": comp_actual["cantidad"]
                                .fillna(0)
                                .astype(float)
                                .values,
                            }
                        )
                    else:
                        comp_view = pd.DataFrame(
                            {"producto": pd.Series(dtype=str), "cantidad": pd.Series(dtype=float)}
                        )

                    edited = st.data_editor(
                        comp_view,
                        use_container_width=False,
                        num_rows="dynamic",
                        column_config={
                            "producto": st.column_config.SelectboxColumn(
                                "Producto DUX",
                                options=opciones_dux_pack,
                                required=True,
                            ),
                            "cantidad": st.column_config.NumberColumn(
                                "Cantidad",
                                min_value=0.0,
                                step=0.25,
                                format="%.3f",
                                required=True,
                            ),
                        },
                        key=f"editor_pack_{pack_id}",
                    )

                    editor_outputs[pack_id] = (pack_nombre, edited)

            if guardar_packs:
                rows_save = []
                for pack_id, (pack_nombre, edited) in editor_outputs.items():
                    if edited is None or edited.empty:
                        continue
                    for _, r in edited.iterrows():
                        prod_label = r.get("producto")
                        if not prod_label or prod_label not in label_to_cod:
                            continue
                        try:
                            cant = float(r.get("cantidad") or 0)
                        except (ValueError, TypeError):
                            cant = 0.0
                        if cant <= 0:
                            continue
                        codigo, producto_nombre = label_to_cod[prod_label]
                        rows_save.append(
                            {
                                "wix_id_pack": pack_id,
                                "pack_nombre": pack_nombre,
                                "dux_codigo": codigo,
                                "dux_producto": producto_nombre,
                                "cantidad": cant,
                            }
                        )

                df_to_save = pd.DataFrame(
                    rows_save,
                    columns=[
                        "wix_id_pack",
                        "pack_nombre",
                        "dux_codigo",
                        "dux_producto",
                        "cantidad",
                    ],
                )
                db.guardar_packs_wix(df_to_save)
                st.success(
                    f"✅ Packs guardados en Sheets ({len(rows_save)} líneas totales)."
                )

    ts_packs = db.ultima_carga("packs")
    ts_packs_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_packs)}**")

with tab_mixes:
    ts_mixes_ph = st.empty()
    st.markdown(
        "Configurá los productos MIX como combinación de otros productos DUX. "
        "Las cantidades se dividen automáticamente en partes iguales. "
        "Funciona en todas las unidades (KG, CAJA, etc.) gracias a la tabla de Compuestos."
    )

    df_prods_mix = db.cargar_productos()

    if df_prods_mix.empty:
        st.info("Primero sincronizá productos en 📡 DUX Productos.")
    else:
        # Identificar productos MIX por nombre (contiene 'MIX' case-insensitive)
        df_p_mix = df_prods_mix.copy()
        partes_m = df_p_mix["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
        df_p_mix["base"] = partes_m[0].str.strip()
        df_p_mix["unidad"] = (
            partes_m[1].fillna("").str.strip()
            if 1 in partes_m.columns
            else ""
        )

        bases_mix = sorted(
            df_p_mix[df_p_mix["base"].str.upper().str.contains("MIX", na=False)]
            ["base"].unique().tolist()
        )
        # Todos los bases NO-MIX para seleccionar como componentes
        bases_no_mix = sorted(
            df_p_mix[~df_p_mix["base"].str.upper().str.contains("MIX", na=False)]
            ["base"].unique().tolist()
        )

        if not bases_mix:
            st.info("No se encontraron productos cuyo nombre contenga 'MIX'.")
        else:
            mixes_guardados = db.cargar_mixes_dux()  # {mix_base: [componente_base, ...]}

            with st.form("form_mixes", clear_on_submit=False, border=False):
                guardar_mixes_btn = st.form_submit_button(
                    "💾 Guardar mixes", type="primary"
                )

                nuevos_mixes = {}
                for mix_base in bases_mix:
                    st.markdown(f"### {mix_base}")
                    componentes_default = mixes_guardados.get(mix_base, [])
                    componentes_default = [
                        c for c in componentes_default if c in bases_no_mix
                    ]
                    sel = st.multiselect(
                        "Componentes (se dividen en partes iguales)",
                        options=bases_no_mix,
                        default=componentes_default,
                        key=f"mix_{mix_base}",
                    )
                    if sel:
                        nuevos_mixes[mix_base] = sel
                        st.caption(
                            f"→ Cada componente recibirá **{1/len(sel):.4f}** del MIX "
                            f"(1 / {len(sel)})"
                        )
                    else:
                        st.caption("→ Sin componentes. Este MIX no se desglosará.")

            if guardar_mixes_btn:
                try:
                    db.guardar_mixes_dux(nuevos_mixes)
                    st.success(f"✅ {len(nuevos_mixes)} mixes guardados.")
                except Exception as e:
                    st.error(msg_error_sheets("guardar mixes", e))

    ts_mixes = db.ultima_carga("mixes_dux")
    ts_mixes_ph.caption(f"🕒 Última actualización: **{_fmt_ts(ts_mixes)}**")



if tab_migracion:
    with tab_migracion:
        st.subheader("📦 Migrar datos de Google Sheets → Supabase")
        st.info(
            "Copia cada tabla desde Google Sheets a Supabase, reemplazando lo que había. "
            "Hacé click en cada entidad por separado o usá **Migrar todo** para hacerlo de una."
        )

        try:
            import gsheets_db as _gdb
            _gdb_ok = True
        except Exception as _e_gdb:
            st.error(f"❌ No se pudo conectar a Google Sheets: {_e_gdb}")
            _gdb_ok = False

        if _gdb_ok:

            def _mig_run(label, cargar_fn, guardar_fn, count_fn=None):
                """Lee de Sheets, escribe en Supabase, devuelve (ok, mensaje)."""
                try:
                    data = cargar_fn()
                    guardar_fn(data)
                    n = count_fn(data) if count_fn else (len(data) if hasattr(data, "__len__") else "?")
                    return True, f"✅ {label}: {n} registros migrados"
                except Exception as _e:
                    return False, f"❌ {label}: {_e}"

            ENTIDADES = [
                ("🗺️ Mapeo Wix↔DUX",      _gdb.cargar_mapping_wix_dux, db.guardar_mapping_wix_dux, None),
                ("📦 Packs Wix",           _gdb.cargar_packs_wix,       db.guardar_packs_wix,       None),
                ("🔀 Mixes DUX",           _gdb.cargar_mixes_dux,       db.guardar_mixes_dux,
                 lambda d: sum(len(v) for v in d.values())),
                ("🔗 Compuestos",          _gdb.cargar_compuestos,      db.guardar_compuestos,      None),
                ("📅 Selecciones DUX",     lambda: _gdb.cargar_selecciones("dux"), lambda d: db.guardar_selecciones("dux", d), lambda d: len(d)),
                ("📅 Selecciones Wix",     lambda: _gdb.cargar_selecciones("wix"), lambda d: db.guardar_selecciones("wix", d), lambda d: len(d)),
                ("⚙️ Configuración",       None,                        None,                       None),  # handled separately
            ]

            if st.button("🚀 Migrar todo", type="primary", key="mig_todo"):
                # Config: filter out ephemeral presencia_* keys
                _msgs = []
                for label, cfn, gfn, cnt in ENTIDADES:
                    if cfn is None:
                        continue
                    ok, msg = _mig_run(label, cfn, gfn, cnt)
                    _msgs.append((ok, msg))
                # Config separado
                try:
                    _cfg_sheets = _gdb.cargar_config()
                    _cfg_filtrado = {k: v for k, v in _cfg_sheets.items() if not k.startswith("presencia_")}
                    db.guardar_config(_cfg_filtrado)
                    _msgs.append((True, f"✅ ⚙️ Configuración: {len(_cfg_filtrado)} claves migradas"))
                except Exception as _e:
                    _msgs.append((False, f"❌ ⚙️ Configuración: {_e}"))
                # Stock separado
                try:
                    _df_stock_mig = _gdb.cargar_stock_completo()
                    if not _df_stock_mig.empty:
                        # Normalizar fecha a ISO YYYY-MM-DD (Sheets puede traer DD/MM/YYYY)
                        _df_stock_mig["fecha"] = pd.to_datetime(
                            _df_stock_mig["fecha"], dayfirst=True, errors="coerce"
                        ).dt.strftime("%Y-%m-%d")
                        _df_stock_mig = _df_stock_mig[_df_stock_mig["fecha"].notna()]
                        _sc = db.get_client()
                        _sc.table("stock_historico").delete().neq("codigo", "___never___").execute()
                        _st_recs = _df_stock_mig.where(pd.notnull(_df_stock_mig), None).to_dict(orient="records")
                        for _ci in range(0, len(_st_recs), 500):
                            _sc.table("stock_historico").insert(_st_recs[_ci:_ci + 500]).execute()
                        _msgs.append((True, f"✅ 📦 Stock histórico: {len(_st_recs)} registros migrados"))
                    else:
                        _msgs.append((True, "✅ 📦 Stock histórico: Sheets vacío, nada que migrar"))
                except Exception as _e:
                    _msgs.append((False, f"❌ 📦 Stock histórico: {_e}"))
                for ok, msg in _msgs:
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

            st.divider()

            # Botones individuales
            _e1, _e2 = st.columns(2)

            with _e1:
                st.markdown("#### 🗺️ Mapeo Wix↔DUX")
                if st.button("Migrar mapeo", key="mig_mapeo"):
                    ok, msg = _mig_run("Mapeo", _gdb.cargar_mapping_wix_dux, db.guardar_mapping_wix_dux)
                    (st.success if ok else st.error)(msg)

                st.markdown("#### 🔀 Mixes DUX")
                if st.button("Migrar mixes", key="mig_mixes"):
                    ok, msg = _mig_run("Mixes", _gdb.cargar_mixes_dux, db.guardar_mixes_dux,
                                       lambda d: sum(len(v) for v in d.values()))
                    (st.success if ok else st.error)(msg)

                st.markdown("#### ⚙️ Configuración")
                st.caption("Excluye claves de presencia de usuario (efímeras).")
                if st.button("Migrar configuración", key="mig_config"):
                    try:
                        _cfg_sheets = _gdb.cargar_config()
                        _cfg_filtrado = {k: v for k, v in _cfg_sheets.items() if not k.startswith("presencia_")}
                        db.guardar_config(_cfg_filtrado)
                        st.success(f"✅ Configuración: {len(_cfg_filtrado)} claves migradas")
                    except Exception as _e:
                        st.error(f"❌ Configuración: {_e}")

                st.markdown("#### 📅 Selecciones DUX")
                st.caption("Fecha asignada de entrega de pedidos DUX.")
                if st.button("Migrar selecciones DUX", key="mig_sel_dux"):
                    ok, msg = _mig_run("Selecciones DUX", lambda: _gdb.cargar_selecciones("dux"), lambda d: db.guardar_selecciones("dux", d), lambda d: len(d))
                    (st.success if ok else st.error)(msg)

                st.markdown("#### 📦 Stock histórico")
                if st.button("Migrar stock", key="mig_stock"):
                    try:
                        _df_stock_b = _gdb.cargar_stock_completo()
                        if _df_stock_b.empty:
                            st.warning("⚠️ Stock: Sheets vacío, nada que migrar")
                        else:
                            # Normalizar fecha a ISO YYYY-MM-DD (Sheets puede traer DD/MM/YYYY)
                            _df_stock_b["fecha"] = pd.to_datetime(
                                _df_stock_b["fecha"], dayfirst=True, errors="coerce"
                            ).dt.strftime("%Y-%m-%d")
                            _df_stock_b = _df_stock_b[_df_stock_b["fecha"].notna()]
                            _sc_b = db.get_client()
                            _sc_b.table("stock_historico").delete().neq("codigo", "___never___").execute()
                            _st_recs_b = _df_stock_b.where(pd.notnull(_df_stock_b), None).to_dict(orient="records")
                            for _ci in range(0, len(_st_recs_b), 500):
                                _sc_b.table("stock_historico").insert(_st_recs_b[_ci:_ci + 500]).execute()
                            st.success(f"✅ Stock: {len(_st_recs_b)} registros migrados")
                    except Exception as _e:
                        st.error(f"❌ Stock: {_e}")

            with _e2:
                st.markdown("#### 📦 Packs Wix")
                if st.button("Migrar packs", key="mig_packs"):
                    ok, msg = _mig_run("Packs", _gdb.cargar_packs_wix, db.guardar_packs_wix)
                    (st.success if ok else st.error)(msg)

                st.markdown("#### 🔗 Compuestos (Relacionar productos)")
                if st.button("Migrar compuestos", key="mig_compuestos"):
                    ok, msg = _mig_run("Compuestos", _gdb.cargar_compuestos, db.guardar_compuestos)
                    (st.success if ok else st.error)(msg)

                st.markdown("#### 📅 Selecciones Wix")
                st.caption("Fecha asignada de entrega de pedidos Wix.")
                if st.button("Migrar selecciones Wix", key="mig_sel_wix"):
                    ok, msg = _mig_run("Selecciones Wix", lambda: _gdb.cargar_selecciones("wix"), lambda d: db.guardar_selecciones("wix", d), lambda d: len(d))
                    (st.success if ok else st.error)(msg)


if tab_cajas:
    with tab_cajas:
        st.subheader("💰 Cajas de cobro")
        st.caption(
            "Definí los canales de cobro que usás. "
            "Los pedidos Wix se asignan a estas cajas. "
            "En el futuro coincidirán con las cajas de DUX."
        )

        try:
            _cajas_data = db.cargar_cajas()
        except Exception as _e_cajas:
            st.error(f"No se pudieron cargar las cajas: {_e_cajas}")
            _cajas_data = []

        _cajas_df = pd.DataFrame(
            _cajas_data if _cajas_data else [{"id": None, "nombre": "", "activa": True}],
            columns=["id", "nombre", "activa"],
        )

        with st.form("form_cajas_config", border=False):
            _cajas_editadas = st.data_editor(
                _cajas_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_config={
                    "id": None,
                    "nombre": st.column_config.TextColumn("Nombre de caja", required=True),
                    "activa": st.column_config.CheckboxColumn("Activa", default=True),
                },
            )
            _guardar_cajas = st.form_submit_button("💾 Guardar cajas", type="primary", use_container_width=True)

        if _guardar_cajas:
            try:
                _cajas_list = _cajas_editadas.where(pd.notnull(_cajas_editadas), None).to_dict(orient="records")
                _cajas_list = [c for c in _cajas_list if (c.get("nombre") or "").strip()]
                db.guardar_cajas(_cajas_list)
                st.success(f"✅ {len(_cajas_list)} cajas guardadas.")
            except Exception as _e_gc:
                st.error(f"❌ No se pudieron guardar las cajas: {_e_gc}")



if tab_gastos_catalogo:
    with tab_gastos_catalogo:
        st.subheader("📋 Catálogo de Items de Gastos")
        st.caption(
            "Importá un Excel con las columnas: Cod Producto, Gasto, Rubro, Sub Rubro, Proveedor. "
            "La importación reemplaza todo el catálogo existente."
        )

        _cat_actual = db.cargar_gastos_catalogo()
        if not _cat_actual.empty:
            st.markdown(f"**Catálogo actual — {len(_cat_actual)} items**")
            _cols_cat = [c for c in ["cod_producto", "gasto", "rubro", "sub_rubro", "proveedor"] if c in _cat_actual.columns]
            st.dataframe(
                _cat_actual[_cols_cat].rename(columns={
                    "cod_producto": "Cod Producto",
                    "gasto":        "Gasto",
                    "rubro":        "Rubro",
                    "sub_rubro":    "Sub Rubro",
                    "proveedor":    "Proveedor",
                }),
                use_container_width=True,
                hide_index=True,
            )
            if st.button("🗑 Borrar todo el catálogo", type="secondary", key="btn_borrar_cat_gastos"):
                db.guardar_gastos_catalogo([])
                st.success("Catálogo borrado.")
                st.rerun()
        else:
            st.info("El catálogo está vacío. Importá un Excel para empezar.")

        st.divider()
        st.markdown("**Importar desde Excel**")
        _archivo_cat = st.file_uploader(
            "Seleccioná el archivo Excel",
            type=["xlsx", "xls"],
            key="uploader_gastos_catalogo",
        )

        if _archivo_cat:
            try:
                _df_excel = pd.read_excel(_archivo_cat, dtype=str).fillna("")
                _col_map = {
                    "Cod Producto": "cod_producto",
                    "Gasto":        "gasto",
                    "Rubro":        "rubro",
                    "Sub Rubro":    "sub_rubro",
                    "Proveedor":    "proveedor",
                }
                _cols_faltantes = [c for c in _col_map if c not in _df_excel.columns]
                if _cols_faltantes:
                    st.error(f"Columnas faltantes en el Excel: {', '.join(_cols_faltantes)}")
                else:
                    _df_import = _df_excel.rename(columns=_col_map)[list(_col_map.values())]
                    _df_import = _df_import[_df_import["gasto"].str.strip().ne("")]
                    st.markdown(f"**Vista previa — {len(_df_import)} items**")
                    st.dataframe(
                        _df_import.rename(columns={v: k for k, v in _col_map.items()}),
                        use_container_width=True,
                        hide_index=True,
                    )
                    if st.button("✅ Importar y reemplazar catálogo", type="primary", key="btn_importar_cat_gastos"):
                        _registros = _df_import.to_dict(orient="records")
                        db.guardar_gastos_catalogo(_registros)
                        st.success(f"✅ {len(_registros)} items importados correctamente.")
                        st.rerun()
            except Exception as _e_imp:
                st.error(f"Error al leer el archivo: {_e_imp}")

if tab_percepciones:
    with tab_percepciones:
        st.subheader("🧾 Percepciones e Impuestos")
        st.caption("Catálogo de percepciones e impuestos de DUX. Sincronizá manualmente cuando sea necesario.")

        if st.button("🔄 Sincronizar Percepciones", type="primary", key="btn_sync_percepciones"):
            _ok_p, _n_p, _msg_p = _sync_percepciones(None, None)
            if _ok_p:
                st.success(_msg_p)
                st.rerun()
            else:
                st.error(_msg_p)

        _percepciones_data = db.cargar_percepciones_impuestos()
        if _percepciones_data:
            _df_perc = pd.DataFrame(_percepciones_data)
            _cols_perc = [c for c in ["id_percepcion_impuesto", "percepcion_impuesto", "tipo_percepcion_impuesto", "jurisdiccion", "descripcion"] if c in _df_perc.columns]
            st.dataframe(
                _df_perc[_cols_perc].rename(columns={
                    "id_percepcion_impuesto":   "ID",
                    "percepcion_impuesto":      "Nombre",
                    "tipo_percepcion_impuesto": "Tipo",
                    "jurisdiccion":             "Jurisdicción",
                    "descripcion":              "Descripción",
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No hay percepciones cargadas. Sincronizá para obtener los datos de DUX.")


#python -m streamlit run app.py
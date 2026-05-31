import hashlib
import io
import re
import time
from datetime import date, timedelta

import requests
import streamlit as st
import pandas as pd

import gsheets_db as db

DUX_RATE_LIMIT_SECONDS = 5.5

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

# Password gate: si en secrets.toml hay [app] password = "...", la pide al entrar.
# Despues del primer login, se persiste un token en la URL (?t=...) para que
# recargas y nuevas pestañas no vuelvan a pedir la contraseña.
_app_password_esperada = st.secrets.get("app", {}).get("password", "")
_app_token = (
    hashlib.sha256(_app_password_esperada.encode()).hexdigest()[:24]
    if _app_password_esperada
    else ""
)
if _app_token and st.query_params.get("t") == _app_token:
    st.session_state["_authed"] = True

if _app_password_esperada and not st.session_state.get("_authed", False):
    st.markdown("### Ingresá la contraseña para continuar")
    _pw_input = st.text_input(
        "Contraseña",
        type="password",
        key="_pw_input",
        label_visibility="collapsed",
    )
    if st.button("Entrar", type="primary", key="_pw_entrar"):
        if _pw_input == _app_password_esperada:
            st.session_state["_authed"] = True
            st.query_params["t"] = _app_token
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()

# Multi-usuario: identificar quien esta usando la app + avisar si hay otros activos
USUARIOS_APP = ["Carlos", "Ariel", "Tomás", "Claudia", "Otro"]
PRESENCIA_WINDOW = 600  # 10 min — considerado "activo" si dio señal en este lapso
HEARTBEAT_INTERVAL = 300  # 5 min — refrescamos nuestra presencia cada este lapso

if "usuario_app" not in st.session_state:
    st.markdown("### ¿Quién sos?")
    cols_pick = st.columns(len(USUARIOS_APP))
    for i_pick, u_pick in enumerate(USUARIOS_APP):
        if cols_pick[i_pick].button(u_pick, key=f"pick_user_{u_pick}", use_container_width=True):
            st.session_state["usuario_app"] = u_pick
            try:
                db.guardar_config({f"presencia_{u_pick}": str(int(time.time()))})
                st.session_state["_ultimo_heartbeat"] = time.time()
            except Exception:
                pass
            st.rerun()
    st.stop()

_usuario_actual = st.session_state["usuario_app"]
_ahora = int(time.time())

# Heartbeat: si pasaron >5 min desde el ultimo, refrescamos presencia
if _ahora - st.session_state.get("_ultimo_heartbeat", 0) > HEARTBEAT_INTERVAL:
    try:
        db.guardar_config({f"presencia_{_usuario_actual}": str(_ahora)})
        st.session_state["_ultimo_heartbeat"] = _ahora
    except Exception:
        pass

# Detectar otros usuarios activos en los ultimos 10 min
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
        st.warning(
            f"⚠️ **{', '.join(_otros_activos)}** también está/n usando la app ahora. "
            "Tené cuidado con los cambios para no pisarse."
        )
except Exception:
    pass

# Pequeño chip arriba mostrando quien sos
st.caption(f"👤 Sesión: **{_usuario_actual}**")


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


@st.cache_data(ttl=120)
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
if compuestos_orig.empty or "codigo_origen" not in compuestos_orig.columns:
    st.error(
        "⚠️ La tabla `compuestos` de Google Sheets está vacía o corrupta. "
        "Andá a la pestaña ⚙️ Relacionar productos y volvé a guardar las relaciones, "
        "o avisale a Tomás."
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

# Top-level tabs: agrupados por funcion. Sub-tabs adentro de cada grupo.
(
    tab_comprar,
    tab_compras,
    tab_grupo_pedidos,
    tab_grupo_diario,
    tab_grupo_analitica,
    tab_grupo_config,
) = st.tabs(
    [
        "🛒 Total a comprar",
        "💰 Compras",
        "📋 Pedidos",
        "📦 Diario",
        "📊 Analítica",
        "⚙️ Configuración",
    ]
)

with tab_grupo_pedidos:
    tab_dux, tab_wix = st.tabs(["DUX", "Wix"])

with tab_grupo_diario:
    tab_stock, tab_estimado = st.tabs(["Stock", "Estimado"])

with tab_grupo_analitica:
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

with tab_grupo_config:
    (
        tab_mapeo,
        tab_packs,
        tab_dux_productos,
        tab_wix_productos,
        tab_proveedores,
        tab_editar,
        tab_probar,
    ) = st.tabs(
        [
            "Mapeo Wix↔DUX",
            "Packs Wix",
            "DUX Productos",
            "Wix Productos",
            "Proveedores",
            "Relacionar productos",
            "Probar conversión",
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
            use_container_width=True,
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
    ts_comp_ph.caption(f"🕒 Última actualización: **{ts_comp or '?'}**")

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

with tab_stock:
    df_stock_full = db.cargar_stock_completo()

    fechas_stock_disp = db.fechas_stock()
    cfg_stk_tab = db.cargar_config()
    fecha_stock_default = (
        pd.to_datetime(fechas_stock_disp[0]).date()
        if fechas_stock_disp
        else date.today()
    )
    if cfg_stk_tab.get("stock_fecha"):
        try:
            fecha_stock_default = pd.to_datetime(cfg_stk_tab["stock_fecha"]).date()
        except Exception:
            pass

    def _save_fecha_stock():
        v = st.session_state.get("fecha_stock_local")
        if v:
            try:
                db.guardar_config({"stock_fecha": str(v)})
            except Exception:
                pass

    col_st1, col_st2 = st.columns([1, 3])
    with col_st1:
        fecha_stock = st.date_input(
            "Fecha",
            value=fecha_stock_default,
            key="fecha_stock_local",
            format="YYYY-MM-DD",
            on_change=_save_fecha_stock,
        )
    ts_stk_ph = col_st2.empty()

    df_dia_stk_full = db.cargar_stock(fecha=fecha_stock)
    map_stock_dia = dict(
        zip(df_dia_stk_full["codigo"].astype(str), df_dia_stk_full["cantidad"])
    ) if not df_dia_stk_full.empty else {}

    base_stk = productos[["codigo", "producto", "unidad_medida"]].copy()
    base_stk["cantidad"] = (
        base_stk["codigo"]
        .astype(str)
        .map(map_stock_dia)
        .fillna(0.0)
        .astype(float)
    )

    # "Poner a cero" llena el editor con ceros (sin guardar).
    # El usuario despues presiona Guardar para persistir.
    if st.session_state.get(f"_stk_zero_{fecha_stock}"):
        base_stk["cantidad"] = 0.0

    # Botones arriba: Cero (fuera de form) + caption
    col_btn_s1, col_btn_s2 = st.columns([1, 4])
    with col_btn_s1:
        cero_s = st.button(
            "🧹 Poner stock a cero",
            key="btn_cero_stock",
            help="Llena todo el stock con 0. No se guarda hasta apretar 💾 Guardar stock.",
        )
    with col_btn_s2:
        st.caption(f"Guarda para la fecha **{fecha_stock}**.")

    prods_disp_stk = sorted(base_stk["producto"].dropna().astype(str).unique().tolist())
    filtro_prod_stk = st.multiselect(
        "Producto",
        options=prods_disp_stk,
        key="stk_filtro_prod_sel",
    )
    if filtro_prod_stk:
        base_stk_view = base_stk[
            base_stk["producto"].astype(str).isin(filtro_prod_stk)
        ].reset_index(drop=True)
    else:
        base_stk_view = base_stk

    with st.form(key=f"form_stock_{fecha_stock}", clear_on_submit=False):
        guardar_s = st.form_submit_button(
            "💾 Guardar stock", type="primary"
        )
        stock_editado = st.data_editor(
            base_stk_view,
            use_container_width=True,
            num_rows="fixed",
            disabled=["codigo", "producto", "unidad_medida"],
            column_config={
                "codigo": st.column_config.TextColumn("Código"),
                "producto": st.column_config.TextColumn("Producto"),
                "unidad_medida": st.column_config.TextColumn("Unidad"),
                "cantidad": st.column_config.NumberColumn(
                    "Cantidad",
                    min_value=0.0,
                    step=1.0,
                    format="%.3f",
                ),
            },
            key=f"editor_stock_{fecha_stock}",
        )

    if guardar_s:
        edits_map = dict(
            zip(
                stock_editado["codigo"].astype(str),
                stock_editado["cantidad"].fillna(0).astype(float),
            )
        )
        salida_s = base_stk.copy()
        salida_s["cantidad"] = [
            edits_map.get(str(c), v)
            for c, v in zip(salida_s["codigo"], salida_s["cantidad"])
        ]
        salida_s["cantidad"] = salida_s["cantidad"].fillna(0).astype(float)
        db.guardar_stock(salida_s, fecha_stock)
        st.session_state.pop(f"_stk_zero_{fecha_stock}", None)
        st.success(f"Stock del {fecha_stock} guardado en Sheets.")

    if cero_s:
        st.session_state[f"_stk_zero_{fecha_stock}"] = True
        editor_key = f"editor_stock_{fecha_stock}"
        st.session_state.pop(editor_key, None)
        st.rerun()

    # Refrescar fechas y timestamp despues del posible save
    fechas_stock_disp_post = db.fechas_stock()
    ts_stk_ultimo = db.ultima_carga("stock")
    ts_stk_ph.caption(
        f"📅 Fechas guardadas: {len(fechas_stock_disp_post)} · "
        f"🕒 Última actualización: **{ts_stk_ultimo or '?'}**"
    )

with tab_comprar:
    ts_ped = db.ultima_carga("pedidos_dux")
    ts_wix = db.ultima_carga("pedidos_wix")
    ts_stk = db.ultima_carga("stock")
    ts_est = db.ultima_carga("estimado_semanal")
    st.caption(
        f"🕒 DUX: **{ts_ped or '?'}** · "
        f"Wix: **{ts_wix or '?'}** · "
        f"Stock: **{ts_stk or '?'}** · "
        f"Estimado: **{ts_est or '?'}**"
    )


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

    # st.form: los cambios NO disparan rerun hasta apretar el boton.
    with st.form("form_fechas_comprar", clear_on_submit=False, border=False):
        col_fc1, col_fc2, col_fc3, col_fc4 = st.columns([1.5, 1.2, 1.2, 1])
        with col_fc1:
            fechas_entrega = st.multiselect(
                "📦 Fechas de entrega",
                options=fechas_entrega_disp,
                default=def_fent_list,
                key="comprar_fechas_entrega",
                help="Elegí una o más fechas. Los pedidos de todas ellas se suman.",
            )
        with col_fc2:
            fecha_stock_sel = st.date_input(
                "📦 Fecha de stock",
                value=def_fstk,
                key="comprar_fecha_stock",
                format="YYYY-MM-DD",
            )
        with col_fc3:
            dia_estimado_sel = st.selectbox(
                "📈 Día de estimado",
                options=DIAS_SEMANA,
                format_func=lambda d: DIAS_DISPLAY[d],
                index=DIAS_SEMANA.index(def_dia_est),
                key="comprar_dia_estimado",
            )
        with col_fc4:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            boton_actualizar = st.form_submit_button(
                "🔄 Actualizar",
                type="primary",
                use_container_width=True,
            )

    if boton_actualizar:
        try:
            db.guardar_config({
                "comprar_fechas_entrega": ",".join(fechas_entrega) if fechas_entrega else "",
                "comprar_fecha_stock": str(fecha_stock_sel),
                "comprar_dia_estimado": str(dia_estimado_sel),
            })
        except Exception:
            pass
        st.cache_data.clear()

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

    # Expander con los pedidos que estan siendo contados, para poder verificar
    _dux_contados = st.session_state.get("_dux_contados", [])
    _wix_contados = st.session_state.get("_wix_contados", [])
    _total_pedidos = len(_dux_contados) + len(_wix_contados)
    with st.expander(
        f"📋 Ver pedidos que se están contando ({_total_pedidos})",
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
                                pd.DataFrame(filas_it)[["codigo", "producto", "cantidad"]],
                                use_container_width=True,
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
                                wix_id_prod = (
                                    (li.get("catalogReference") or {}).get("catalogItemId")
                                    or li.get("productId") or ""
                                )
                                filas_iw.append({
                                    "wix_id": str(wix_id_prod),
                                    "producto": nombre_prod,
                                    "cantidad": li.get("quantity") or 0,
                                })
                            st.dataframe(
                                pd.DataFrame(filas_iw),
                                use_container_width=True,
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
                _stk_view[["codigo", "producto", "unidad_medida", "cantidad"]],
                use_container_width=True,
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
                _est_view[["codigo", "producto", "unidad_medida", "estimado"]],
                use_container_width=True,
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
        f"🔍 Ver resumen por código sin conversiones ({len(_raw_view)})",
        expanded=False,
    ):
        if _raw_view.empty:
            st.caption("Sin datos.")
        else:
            _raw_view = _raw_view.rename(columns={"cantidad": "pedido"}).sort_values("producto")
            st.dataframe(
                _raw_view[["codigo", "producto", "unidad_medida", "pedido", "estimado", "stock"]],
                use_container_width=True,
                hide_index=True,
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
                estado_label = "Falta"
            elif primer < -0.001:
                icono = "🟢"
                estado_label = "Sobra"
            else:
                icono = "⚪"
                estado_label = "OK"

            # Nombre: si la familia tiene un solo producto, usar su nombre completo
            nombre = (
                comp_productos.iloc[0]["producto"] if len(comp) == 1 else base
            )

            with st.expander(f"{icono} **{nombre}** — {estado_label}", expanded=False):
                cols_h = st.columns([1, 1, 1, 1, 1.5, 1.5])
                cols_h[0].markdown("**Unidad**")
                cols_h[1].markdown("**Pedido**")
                cols_h[2].markdown("**Estimado**")
                cols_h[3].markdown("**Stock**")
                cols_h[4].markdown("**Resultado**")
                cols_h[5].markdown("**Con estimado**")

                def _badge(valor, unidad):
                    if valor > 0.001:
                        return (
                            f"<span style='color:#d11; font-weight:bold;'>"
                            f"Falta {valor:,.2f} {unidad}</span>"
                        )
                    if valor < -0.001:
                        return (
                            f"<span style='color:#1a8a1a; font-weight:bold;'>"
                            f"Sobra {-valor:,.2f} {unidad}</span>"
                        )
                    return f"OK"

                for r in resultados:
                    cols = st.columns([1, 1, 1, 1, 1.5, 1.5])
                    cols[0].markdown(f"**{r['unidad']}**")
                    cols[1].markdown(f"{r['pedido']:,.2f}")
                    cols[2].markdown(f"{r['estimado']:,.2f}")
                    cols[3].markdown(f"{r['stock']:,.2f}")
                    cols[4].markdown(_badge(r["diff"], r["unidad"]), unsafe_allow_html=True)
                    cols[5].markdown(_badge(r["diff_est"], r["unidad"]), unsafe_allow_html=True)

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

    col_es1, col_es2 = st.columns([1, 3])
    with col_es1:
        dia_estimado = st.selectbox(
            "Día de la semana",
            options=DIAS_SEMANA,
            format_func=lambda d: DIAS_DISPLAY[d],
            index=dia_default_idx,
            key="dia_estimado",
            on_change=_save_dia_estimado,
        )
    ts_est_ph = col_es2.empty()

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

    # Botones arriba: Cero (fuera de form) + caption
    col_btn_e1, col_btn_e2 = st.columns([1, 4])
    with col_btn_e1:
        reset_est = st.button(
            "🧹 Resetear a cero",
            key="btn_reset_estimado",
            help="Llena todo el estimado con 0. No se guarda hasta apretar 💾 Guardar estimado.",
        )
    with col_btn_e2:
        st.caption(f"Guarda para el día **{DIAS_DISPLAY[dia_estimado]}** (fijo, se aplica a todos los {DIAS_DISPLAY[dia_estimado].lower()}).")

    prods_disp_est = sorted(base_est["producto"].dropna().astype(str).unique().tolist())
    filtro_prod_est = st.multiselect(
        "Producto",
        options=prods_disp_est,
        key="est_filtro_prod_sel",
    )
    if filtro_prod_est:
        base_est_view = base_est[
            base_est["producto"].astype(str).isin(filtro_prod_est)
        ].reset_index(drop=True)
    else:
        base_est_view = base_est

    with st.form(key=f"form_estimado_{dia_estimado}", clear_on_submit=False):
        guardar_est = st.form_submit_button(
            "💾 Guardar estimado", type="primary"
        )
        editor_estimado = st.data_editor(
            base_est_view,
            use_container_width=True,
            num_rows="fixed",
            disabled=["codigo", "producto", "unidad_medida"],
            column_config={
                "codigo": st.column_config.TextColumn("Código"),
                "producto": st.column_config.TextColumn("Producto"),
                "unidad_medida": st.column_config.TextColumn("Unidad"),
                "estimado": st.column_config.NumberColumn(
                    "Estimado",
                    min_value=0.0,
                    step=1.0,
                    format="%.3f",
                ),
            },
            key=f"editor_estimado_{dia_estimado}",
        )

    if guardar_est:
        edits_map_e = dict(
            zip(
                editor_estimado["codigo"].astype(str),
                editor_estimado["estimado"].fillna(0).astype(float),
            )
        )
        salida = base_est.copy()
        salida["estimado"] = [
            edits_map_e.get(str(c), v)
            for c, v in zip(salida["codigo"], salida["estimado"])
        ]
        salida["estimado"] = salida["estimado"].fillna(0).astype(float)
        db.guardar_estimado_semanal_dia(salida, dia_estimado)
        st.session_state.pop(f"_est_zero_{dia_estimado}", None)
        st.success(f"Estimado para {DIAS_DISPLAY[dia_estimado]} guardado en Sheets.")

    if reset_est:
        st.session_state[f"_est_zero_{dia_estimado}"] = True
        editor_key = f"editor_estimado_{dia_estimado}"
        st.session_state.pop(editor_key, None)
        st.rerun()

    dias_con_est_post = db.dias_semana_con_estimado()
    ts_est_ultimo = db.ultima_carga("estimado_semanal")
    ts_est_ph.caption(
        f"📅 Días configurados: {len(dias_con_est_post)} / 7 · "
        f"🕒 Última actualización: **{ts_est_ultimo or '?'}**"
    )

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
        id_empresa = id_empresa_default
        id_sucursal = id_sucursal_default

        all_orders_saved = []
        selecciones_dux = db.cargar_selecciones("dux")
        config_app = db.cargar_config()
        # Rango persistido en Sheets (config); fallback a hoy
        fecha_desde_default = date.today() - timedelta(days=7)
        fecha_hasta_default = date.today()
        if config_app.get("dux_fecha_desde"):
            try:
                fecha_desde_default = pd.to_datetime(config_app["dux_fecha_desde"]).date()
            except Exception:
                pass
        if config_app.get("dux_fecha_hasta"):
            try:
                fecha_hasta_default = pd.to_datetime(config_app["dux_fecha_hasta"]).date()
            except Exception:
                pass
        try:
            all_orders_saved = db.cargar_pedidos_dux()
        except Exception as e:
            st.error(msg_error_sheets("leer pedidos DUX", e))

        # st.form: los cambios de fecha NO disparan rerun hasta apretar Sincronizar.
        with st.form("form_dux_sync", clear_on_submit=False, border=False):
            col_d1, col_d2, col_d3 = st.columns([1, 1, 1])
            with col_d1:
                fecha_desde = st.date_input(
                    "Fecha desde",
                    value=fecha_desde_default,
                    key="dux_fecha_desde",
                    format="YYYY-MM-DD",
                )
            with col_d2:
                fecha_hasta = st.date_input(
                    "Fecha hasta",
                    value=fecha_hasta_default,
                    key="dux_fecha_hasta",
                    format="YYYY-MM-DD",
                )
            with col_d3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                consultar = st.form_submit_button(
                    "🔄 Sincronizar pedidos desde DUX",
                    type="primary",
                    use_container_width=True,
                )

        if consultar:
            url_p = f"{base_url}/pedidos"
            headers_p = {"accept": "application/json", "authorization": token}
            page_offset = 0
            page_size = 50
            all_orders = []
            error_corte = False

            with st.spinner("Consultando DUX..."):
                while True:
                    params_p = {
                        "idEmpresa": int(id_empresa),
                        "idSucursal": int(id_sucursal),
                        "fechaDesde": fecha_desde.strftime("%Y-%m-%d"),
                        "fechaHasta": fecha_hasta.strftime("%Y-%m-%d"),
                        "offset": page_offset,
                        "limit": page_size,
                    }
                    try:
                        r = requests.get(
                            url_p, params=params_p, headers=headers_p, timeout=30
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
                        st.error(f"❌ DUX dice: {d['message']}. Avisale a Tomás si no se arregla.")
                        error_corte = True
                        break

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

            if not error_corte:
                try:
                    db.guardar_pedidos_dux(all_orders)
                except Exception as e:
                    st.error(msg_error_sheets("guardar pedidos DUX", e))

                # Persistir rango en Sheets (config) para que sobreviva reinicios
                try:
                    db.guardar_config(
                        {
                            "dux_fecha_desde": str(fecha_desde),
                            "dux_fecha_hasta": str(fecha_hasta),
                        }
                    )
                except Exception:
                    pass

                all_orders_saved = all_orders
                if all_orders:
                    st.success(
                        f"✅ {len(all_orders)} pedidos guardados."
                    )
                else:
                    st.warning("No hay pedidos pendientes en ese rango.")

        st.divider()

        if all_orders_saved:
            ts_ped = db.ultima_carga("pedidos_dux")
            n_asignados = sum(1 for v in selecciones_dux.values() if v)
            st.caption(
                f"📅 Rango: {fecha_desde_default} → {fecha_hasta_default} · "
                f"🕒 Última sync: **{ts_ped or '?'}** · "
                f"{n_asignados} con entrega asignada."
            )

            # Ordenar: más recientes primero
            def _fecha_dux(o):
                f = o.get("fecha") or ""
                try:
                    return pd.to_datetime(f)
                except Exception:
                    return pd.Timestamp.min
            all_orders_sorted = sorted(
                all_orders_saved, key=_fecha_dux, reverse=True
            )

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
                    fecha_default_entrega = (
                        pd.to_datetime(asignado_prev).date()
                        if asignado_prev
                        else date.today() + timedelta(days=1)
                    )

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

                    with st.container(border=True):
                        c_info, c_chk, c_fec = st.columns([4, 1.2, 1.6])
                        with c_info:
                            entrega_badge = (
                                f" · 📦 {asignado_prev}" if asignado_prev else ""
                            )
                            st.markdown(
                                f"**#{nro or i}** — {cliente_str} · "
                                f"{len(items)} ítems · {estado_badge}{entrega_badge}"
                            )
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
                                format="YYYY-MM-DD",
                                label_visibility="collapsed",
                            )

                        if asignar:
                            nuevas_selecciones_dux[oid] = str(fecha_entrega)

                        if items:
                            with st.expander("Ver productos"):
                                filas = [extraer_item_dux(it) for it in items]
                                st.dataframe(
                                    pd.DataFrame(filas),
                                    use_container_width=True,
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

        else:
            st.info(
                "Todavía no hay pedidos guardados. Apretá **Sincronizar** para traerlos."
            )

with tab_dux_productos:
    ts_dux_prod_ph = st.empty()

    if not token:
        st.error("Falta configurar el token de DUX en `.streamlit/secrets.toml`.")
    else:
        sincronizar = st.button(
            "🔄 Sincronizar productos desde DUX",
            type="primary",
            key="dux_sincronizar_productos",
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
                        filas.append(
                            {
                                "codigo": str(p.get("cod_item", "")).strip(),
                                "producto": nombre,
                                "unidad_medida": unidad,
                                "descripcion": "",
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
                    for c in ["codigo", "producto", "unidad_medida"]
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
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "Todavía no hay productos en Sheets. Apretá **Sincronizar**."
                )
        except Exception as e:
            st.error(msg_error_sheets("leer productos", e))

    ts_dux_prod = db.ultima_carga("dux_productos")
    ts_dux_prod_ph.caption(f"🕒 Última actualización: **{ts_dux_prod or '?'}**")

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

        config_app_wix = db.cargar_config()
        fecha_desde_default = date.today() - timedelta(days=3)
        fecha_hasta_default = date.today()
        if config_app_wix.get("wix_fecha_desde"):
            try:
                fecha_desde_default = pd.to_datetime(config_app_wix["wix_fecha_desde"]).date()
            except Exception:
                pass
        if config_app_wix.get("wix_fecha_hasta"):
            try:
                fecha_hasta_default = pd.to_datetime(config_app_wix["wix_fecha_hasta"]).date()
            except Exception:
                pass

        # st.form: los cambios de fecha NO disparan rerun hasta apretar Sincronizar.
        with st.form("form_wix_sync", clear_on_submit=False, border=False):
            col_w1, col_w2, col_w3 = st.columns([1, 1, 1])
            with col_w1:
                wix_desde = st.date_input(
                    "Fecha desde",
                    value=fecha_desde_default,
                    key="wix_fecha_desde",
                    format="YYYY-MM-DD",
                )
            with col_w2:
                wix_hasta = st.date_input(
                    "Fecha hasta",
                    value=fecha_hasta_default,
                    key="wix_fecha_hasta",
                    format="YYYY-MM-DD",
                )
            with col_w3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                consultar_wix = st.form_submit_button(
                    "🔄 Sincronizar pedidos desde Wix",
                    type="primary",
                    use_container_width=True,
                )

        if consultar_wix:
            url = "https://www.wixapis.com/ecom/v1/orders/search"
            headers = {
                "Authorization": wix_token,
                "wix-account-id": wix_account,
                "wix-site-id": wix_site,
                "Content-Type": "application/json",
            }
            body = {
                "search": {
                    "filter": {
                        "$and": [
                            {"createdDate": {"$gte": f"{wix_desde}T00:00:00.000Z"}},
                            {"createdDate": {"$lte": f"{wix_hasta}T23:59:59.999Z"}},
                        ]
                    },
                    "cursorPaging": {"limit": 100},
                }
            }

            try:
                with st.spinner("Consultando Wix..."):
                    resp = requests.post(url, json=body, headers=headers, timeout=30)
            except requests.RequestException as e:
                st.error(msg_error_red("Wix", e))
                resp = None

            if resp is not None:
                if resp.status_code != 200:
                    st.error(msg_error_http("Wix", resp.status_code, resp.text))
                else:
                    try:
                        data = resp.json()
                    except ValueError:
                        st.error("❌ Wix devolvió una respuesta inválida. Probá de nuevo.")
                        data = None

                    if data is not None:
                        orders = data.get("orders", [])
                        # Recortar campos no usados para no superar el limite de 50k chars/celda de Sheets
                        orders_slim = [_slim_wix_order(o) for o in orders]
                        try:
                            db.guardar_pedidos_wix(orders_slim)
                        except Exception as e:
                            st.error(msg_error_sheets("guardar pedidos Wix", e))

                        try:
                            db.guardar_config(
                                {
                                    "wix_fecha_desde": str(wix_desde),
                                    "wix_fecha_hasta": str(wix_hasta),
                                }
                            )
                        except Exception:
                            pass

                        wix_orders_saved = orders_slim
                        st.success(f"✅ {len(orders)} pedidos guardados.")

        st.divider()

        orders_saved = wix_orders_saved or []
        selecciones = db.cargar_selecciones("wix")

        if not orders_saved:
            st.info("Todavía no hay pedidos. Apretá **Sincronizar**.")
        else:
            ts_wix = db.ultima_carga("pedidos_wix")
            st.caption(
                f"{len(orders_saved)} pedidos · 🕒 última sync: **{ts_wix or '?'}** · "
                f"{len(selecciones)} con entrega asignada."
            )

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
                    return pd.to_datetime(f)
                except Exception:
                    return pd.Timestamp.min
            orders_saved_sorted = sorted(
                orders_saved, key=_fecha_wix, reverse=True
            )

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
                    fecha_default_entrega = (
                        pd.to_datetime(asignado_prev).date()
                        if asignado_prev
                        else date.today() + timedelta(days=1)
                    )

                    with st.container(border=True):
                        c_info, c_chk, c_fec = st.columns([4, 1.2, 1.6])
                        with c_info:
                            badge = f" · 📦 {asignado_prev}" if asignado_prev else ""
                            st.markdown(
                                f"**#{nro}** — {cliente} · {len(items)} ítems · "
                                f"**{total}**{badge}"
                            )
                            detalles = []
                            if direccion:
                                detalles.append(f"📍 {direccion}")
                            if email:
                                detalles.append(f"✉️ {email}")
                            if detalles:
                                st.caption(" · ".join(detalles))
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
                                format="YYYY-MM-DD",
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
                                    filas.append(
                                        {
                                            "producto": nombre,
                                            "cantidad": it.get("quantity", 0),
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(filas),
                                    use_container_width=True,
                                    hide_index=True,
                                )

            if guardar_sel:
                try:
                    db.guardar_selecciones("wix", nuevas_selecciones)
                    selecciones = nuevas_selecciones
                    st.success(
                        f"✅ {len(nuevas_selecciones)} entregas guardadas en Sheets."
                    )
                except Exception as e:
                    st.error(msg_error_sheets("guardar selecciones Wix", e))

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
                    use_container_width=True,
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
    ts_wix_prod_ph.caption(f"🕒 Última actualización: **{ts_wix_prod or '?'}**")

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
                use_container_width=True,
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
                use_container_width=True,
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
    ts_prov_ph.caption(f"🕒 Última actualización: **{ts_prov or '?'}**")

with tab_compras:
    ts_compras_ph = st.empty()

    COND_PAGO_OPCIONES = ["CONTADO", "EFECTIVO", "CHEQUE", "CUENTA CORRIENTE"]
    COLUMNAS_DUX = [
        "COMPROBANTE", "TIPO COMPROBANTE", "ID PROVEEDOR", "FECHA",
        "FECHA IMPUTACION CONTABLE", "FECHA VENCIMIENTO", "CONDICION PAGO",
        "REALIZA RECEPCION", "DEPOSITO", "OBSERVACIONES", "CÓDIGO PRODUCTO",
        "TALLE", "COLOR", "CANTIDAD", "PRECIO", "PRECIO INCLUYE IVA",
        "PORCENTAJE DESCUENTO", "PORCENTAJE IVA", "COMENTARIOS",
        "NUMERO IDENTIFICACION TRAZABLE", "DESCRIPCION TRAZABLE",
        "PERCEPCIONES", "VALORES PERCEPCIONES",
    ]

    df_prov_data = db.cargar_proveedores()
    df_prods_data = db.cargar_productos()

    if df_prov_data.empty:
        st.warning("Primero cargá proveedores en 👥 Proveedores.")
    elif df_prods_data.empty:
        st.warning("Primero sincronizá productos en 📡 DUX Productos.")
    else:
        fechas_comp = db.fechas_compras()
        cfg_comp_tab = db.cargar_config()
        fecha_compra_default = (
            pd.to_datetime(fechas_comp[0]).date() if fechas_comp else date.today()
        )
        if cfg_comp_tab.get("compras_fecha"):
            try:
                fecha_compra_default = pd.to_datetime(
                    cfg_comp_tab["compras_fecha"]
                ).date()
            except Exception:
                pass

        def _save_fecha_compras():
            v = st.session_state.get("compras_fecha")
            if v:
                try:
                    db.guardar_config({"compras_fecha": str(v)})
                except Exception:
                    pass

        fecha_compra_sel = st.date_input(
            "Fecha de compra",
            value=fecha_compra_default,
            key="compras_fecha",
            format="YYYY-MM-DD",
            on_change=_save_fecha_compras,
        )

        # Opciones para los selectbox
        opciones_prov = [
            f"{pid} - {nom}"
            for pid, nom in zip(
                df_prov_data["proveedor_id"].astype(str),
                df_prov_data["proveedor"].astype(str),
            )
        ]
        prov_label_to_id = {
            f"{pid} - {nom}": (pid, nom)
            for pid, nom in zip(
                df_prov_data["proveedor_id"].astype(str),
                df_prov_data["proveedor"].astype(str),
            )
        }

        opciones_prod = [
            f"{cod} - {prod}"
            for cod, prod in zip(
                df_prods_data["codigo"].astype(str),
                df_prods_data["producto"].astype(str),
            )
        ]
        prod_label_to_codigo = {
            f"{cod} - {prod}": (cod, prod)
            for cod, prod in zip(
                df_prods_data["codigo"].astype(str),
                df_prods_data["producto"].astype(str),
            )
        }

        # Cargar compras existentes para esta fecha
        df_compras_all = db.cargar_compras()
        if not df_compras_all.empty:
            df_compras_fecha = df_compras_all[
                df_compras_all["fecha"] == str(fecha_compra_sel)
            ].reset_index(drop=True)
        else:
            df_compras_fecha = pd.DataFrame(columns=db.SCHEMA["compras"])

        # Armar vista editable
        if not df_compras_fecha.empty:
            view_rows = []
            for _, r in df_compras_fecha.iterrows():
                prov_label = f"{r['proveedor_id']} - {r.get('proveedor_nombre', '')}"
                prod_label = f"{r['codigo_producto']} - {r.get('producto_nombre', '')}"
                view_rows.append({
                    "Proveedor": prov_label if prov_label in opciones_prov else "",
                    "Producto": prod_label if prod_label in opciones_prod else "",
                    "Cantidad": float(r.get("cantidad", 0) or 0),
                    "Precio Unit.": float(r.get("precio", 0) or 0),
                    "Cond. Pago": str(r.get("condicion_pago", "") or "CONTADO"),
                })
            df_view = pd.DataFrame(view_rows)
        else:
            df_view = pd.DataFrame({
                "Proveedor": pd.Series(dtype=str),
                "Producto": pd.Series(dtype=str),
                "Cantidad": pd.Series(dtype=float),
                "Precio Unit.": pd.Series(dtype=float),
                "Cond. Pago": pd.Series(dtype=str),
            })

        with st.form(f"form_compras_{fecha_compra_sel}", clear_on_submit=False, border=False):
            guardar_c = st.form_submit_button(
                "💾 Guardar compras del día", type="primary"
            )

            edited_compras = st.data_editor(
                df_view,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "Proveedor": st.column_config.SelectboxColumn(
                        "Proveedor",
                        options=opciones_prov,
                        required=True,
                    ),
                    "Producto": st.column_config.SelectboxColumn(
                        "Producto",
                        options=opciones_prod,
                        required=True,
                    ),
                    "Cantidad": st.column_config.NumberColumn(
                        "Cantidad", min_value=0.0, step=1.0, format="%.3f",
                    ),
                    "Precio Unit.": st.column_config.NumberColumn(
                        "Precio Unit.", min_value=0.0, step=0.01, format="%.2f",
                    ),
                    "Cond. Pago": st.column_config.SelectboxColumn(
                        "Cond. Pago",
                        options=COND_PAGO_OPCIONES,
                    ),
                },
                key=f"editor_compras_{fecha_compra_sel}",
            )

        if guardar_c:
            rows_save = []
            for _, r in edited_compras.iterrows():
                prov_label = r.get("Proveedor")
                prod_label = r.get("Producto")
                if not prov_label or not prod_label:
                    continue
                if prov_label not in prov_label_to_id or prod_label not in prod_label_to_codigo:
                    continue
                pid, pnom = prov_label_to_id[prov_label]
                pcod, ppnom = prod_label_to_codigo[prod_label]
                try:
                    cant = float(r.get("Cantidad") or 0)
                    precio = float(r.get("Precio Unit.") or 0)
                except (ValueError, TypeError):
                    cant, precio = 0.0, 0.0
                rows_save.append({
                    "fecha": str(fecha_compra_sel),
                    "proveedor_id": str(pid),
                    "proveedor_nombre": str(pnom),
                    "codigo_producto": str(pcod),
                    "producto_nombre": str(ppnom),
                    "cantidad": cant,
                    "precio": precio,
                    "condicion_pago": str(r.get("Cond. Pago") or "CONTADO"),
                })
            df_save = pd.DataFrame(rows_save, columns=db.SCHEMA["compras"])
            try:
                db.guardar_compras_fecha(df_save, fecha_compra_sel)
                st.success(f"✅ {len(df_save)} líneas guardadas para el {fecha_compra_sel}.")
            except Exception as e:
                st.error(msg_error_sheets("guardar compras", e))

        # Botón de descargar Excel DUX
        # Releemos lo guardado (post-save) para que la descarga refleje el estado actual
        df_compras_all_post = db.cargar_compras()
        if not df_compras_all_post.empty:
            df_compras_fecha_post = df_compras_all_post[
                df_compras_all_post["fecha"] == str(fecha_compra_sel)
            ].reset_index(drop=True)
        else:
            df_compras_fecha_post = pd.DataFrame()

        if not df_compras_fecha_post.empty:
            import xlwt
            # DUX pide fecha con guiones DD-MM-AAAA
            fecha_str_dux = pd.to_datetime(fecha_compra_sel).strftime("%d/%m/%Y")

            def _num_es(v):
                try:
                    n = float(v)
                except (ValueError, TypeError):
                    return ""
                return f"{n:.3f}".rstrip("0").rstrip(".").replace(".", ",")

            filas_excel = []
            for _, r in df_compras_fecha_post.iterrows():
                pid = str(r.get("proveedor_id", "") or "")
                fila = {col: "" for col in COLUMNAS_DUX}
                # El comprobante ya viene asignado por proveedor desde guardar_compras_fecha
                fila["COMPROBANTE"] = str(r.get("comprobante", "") or "")
                fila["TIPO COMPROBANTE"] = "COMPROBANTE COMPRA"
                fila["DEPOSITO"] = "DEPOSITO"
                fila["ID PROVEEDOR"] = pid
                fila["FECHA"] = fecha_str_dux
                fila["FECHA IMPUTACION CONTABLE"] = fecha_str_dux
                fila["FECHA VENCIMIENTO"] = fecha_str_dux
                fila["CONDICION PAGO"] = r.get("condicion_pago", "") or "CONTADO"
                fila["CÓDIGO PRODUCTO"] = r.get("codigo_producto", "") or ""
                fila["CANTIDAD"] = _num_es(r.get("cantidad", 0) or 0)
                fila["PRECIO"] = _num_es(r.get("precio", 0) or 0)
                filas_excel.append(fila)

            # Escribir como .xls (Excel 97-2003) con sheet "Hoja Principal"
            # tal cual el template oficial de DUX.
            wb = xlwt.Workbook(encoding="utf-8")
            sheet = wb.add_sheet("Hoja Principal")
            for col_idx, col_name in enumerate(COLUMNAS_DUX):
                sheet.write(0, col_idx, col_name)
            for row_idx, fila in enumerate(filas_excel, start=1):
                for col_idx, col_name in enumerate(COLUMNAS_DUX):
                    val = fila.get(col_name, "")
                    if val == "" or val is None:
                        continue  # celda vacia
                    sheet.write(row_idx, col_idx, val)
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            st.download_button(
                "📥 Descargar Excel para DUX",
                data=buf.getvalue(),
                file_name=f"compras_dux_{fecha_compra_sel}.xls",
                mime="application/vnd.ms-excel",
                type="primary",
            )

            # ---------- Resumen del día ----------
            df_resumen = df_compras_fecha_post.copy()
            df_resumen["subtotal"] = (
                df_resumen["cantidad"].astype(float) * df_resumen["precio"].astype(float)
            )
            total_gastado = float(df_resumen["subtotal"].sum())

            st.markdown("### 📊 Resumen del día")
            col_m1, col_m2 = st.columns(2)
            col_m1.metric("💰 Total gastado", f"$ {total_gastado:,.2f}")
            col_m2.metric("🧾 Facturas", df_resumen["comprobante"].nunique())

            col_r1, col_r2 = st.columns(2)
            with col_r1:
                st.markdown("**Por proveedor**")
                por_prov = (
                    df_resumen.groupby("proveedor_nombre")
                    .agg(items=("codigo_producto", "count"),
                         total=("subtotal", "sum"))
                    .reset_index()
                    .sort_values("total", ascending=False)
                )
                por_prov["total"] = por_prov["total"].apply(lambda v: f"$ {v:,.2f}")
                st.dataframe(
                    por_prov,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "proveedor_nombre": st.column_config.TextColumn("Proveedor"),
                        "items": st.column_config.NumberColumn("Items"),
                        "total": st.column_config.TextColumn("Total"),
                    },
                )
            with col_r2:
                st.markdown("**Por forma de pago**")
                por_pago = (
                    df_resumen.groupby("condicion_pago")
                    .agg(items=("codigo_producto", "count"),
                         total=("subtotal", "sum"))
                    .reset_index()
                    .sort_values("total", ascending=False)
                )
                por_pago["total"] = por_pago["total"].apply(lambda v: f"$ {v:,.2f}")
                st.dataframe(
                    por_pago,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "condicion_pago": st.column_config.TextColumn("Forma de pago"),
                        "items": st.column_config.NumberColumn("Items"),
                        "total": st.column_config.TextColumn("Total"),
                    },
                )

            # Precio promedio por producto (cada codigo/unidad individual, sin conversiones)
            st.markdown("**Precio promedio por producto**")
            por_prod_dia = (
                df_resumen.groupby(["codigo_producto", "producto_nombre"])
                .agg(cantidad=("cantidad", "sum"), gastado=("subtotal", "sum"))
                .reset_index()
            )
            por_prod_dia["precio_prom"] = (
                por_prod_dia["gastado"] / por_prod_dia["cantidad"]
            )
            por_prod_dia = por_prod_dia.sort_values("producto_nombre")
            disp_dia = por_prod_dia.copy()
            disp_dia["cantidad"] = disp_dia["cantidad"].apply(
                lambda v: f"{v:,.3f}".rstrip("0").rstrip(".")
            )
            disp_dia["gastado"] = disp_dia["gastado"].apply(lambda v: f"$ {v:,.2f}")
            disp_dia["precio_prom"] = disp_dia["precio_prom"].apply(
                lambda v: f"$ {v:,.2f}"
            )
            st.dataframe(
                disp_dia[["codigo_producto", "producto_nombre", "cantidad",
                           "precio_prom", "gastado"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "codigo_producto": st.column_config.TextColumn("Código"),
                    "producto_nombre": st.column_config.TextColumn("Producto"),
                    "cantidad": st.column_config.TextColumn("Cantidad"),
                    "precio_prom": st.column_config.TextColumn("Precio prom."),
                    "gastado": st.column_config.TextColumn("Gastado"),
                },
            )

            with st.expander(f"Ver detalle línea por línea ({len(df_compras_fecha_post)} líneas)"):
                df_det = df_compras_fecha_post.copy()
                df_det["subtotal"] = (
                    df_det["cantidad"].astype(float) * df_det["precio"].astype(float)
                )
                st.dataframe(
                    df_det[[
                        "comprobante", "proveedor_nombre", "codigo_producto",
                        "producto_nombre", "cantidad", "precio", "subtotal",
                        "condicion_pago",
                    ]],
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.caption("Cargá líneas y guardá para poder descargar el Excel DUX.")

    ts_compras = db.ultima_carga("compras")
    ts_compras_ph.caption(f"🕒 Última actualización: **{ts_compras or '?'}**")

with tab_resumen_rango:
    st.markdown("### 📊 Resumen de compras por rango de fechas")

    df_rr = db.cargar_compras()
    if df_rr.empty:
        st.info("Todavía no hay compras cargadas.")
    else:
        cfg_rr = db.cargar_config()
        def_desde_rr = date.today() - timedelta(days=30)
        def_hasta_rr = date.today()
        if cfg_rr.get("rr_fecha_desde"):
            try:
                def_desde_rr = pd.to_datetime(cfg_rr["rr_fecha_desde"]).date()
            except Exception:
                pass
        if cfg_rr.get("rr_fecha_hasta"):
            try:
                def_hasta_rr = pd.to_datetime(cfg_rr["rr_fecha_hasta"]).date()
            except Exception:
                pass

        with st.form("form_resumen_rango", border=False):
            col_rr1, col_rr2, col_rr3 = st.columns([1, 1, 1])
            with col_rr1:
                fecha_desde_rr = st.date_input(
                    "Desde",
                    value=def_desde_rr,
                    key="rr_desde",
                    format="YYYY-MM-DD",
                )
            with col_rr2:
                fecha_hasta_rr = st.date_input(
                    "Hasta",
                    value=def_hasta_rr,
                    key="rr_hasta",
                    format="YYYY-MM-DD",
                )
            with col_rr3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                aplicar_rr = st.form_submit_button(
                    "🔄 Aplicar", type="primary", use_container_width=True
                )

        if aplicar_rr:
            try:
                db.guardar_config({
                    "rr_fecha_desde": str(fecha_desde_rr),
                    "rr_fecha_hasta": str(fecha_hasta_rr),
                })
            except Exception:
                pass

        df_rr["fecha_dt"] = pd.to_datetime(df_rr["fecha"], errors="coerce")
        mask_rr = (
            (df_rr["fecha_dt"] >= pd.to_datetime(fecha_desde_rr))
            & (df_rr["fecha_dt"] <= pd.to_datetime(fecha_hasta_rr))
        )
        df_rng = df_rr[mask_rr].copy()

        if df_rng.empty:
            st.warning("No hay compras en el rango seleccionado.")
        else:
            df_rng["subtotal"] = (
                df_rng["cantidad"].astype(float) * df_rng["precio"].astype(float)
            )
            total_gastado_rr = float(df_rng["subtotal"].sum())

            col_mrr1, col_mrr2 = st.columns(2)
            col_mrr1.metric("💰 Total gastado", f"$ {total_gastado_rr:,.2f}")
            col_mrr2.metric("🧾 Facturas", df_rng["comprobante"].nunique())

            col_brr1, col_brr2 = st.columns(2)
            with col_brr1:
                st.markdown("**Por proveedor**")
                por_prov_rr = (
                    df_rng.groupby("proveedor_nombre")
                    .agg(items=("codigo_producto", "count"),
                         total=("subtotal", "sum"))
                    .reset_index()
                    .sort_values("total", ascending=False)
                )
                por_prov_rr["total"] = por_prov_rr["total"].apply(
                    lambda v: f"$ {v:,.2f}"
                )
                st.dataframe(
                    por_prov_rr,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "proveedor_nombre": st.column_config.TextColumn("Proveedor"),
                        "items": st.column_config.NumberColumn("Items"),
                        "total": st.column_config.TextColumn("Total"),
                    },
                )
            with col_brr2:
                st.markdown("**Por forma de pago**")
                por_pago_rr = (
                    df_rng.groupby("condicion_pago")
                    .agg(items=("codigo_producto", "count"),
                         total=("subtotal", "sum"))
                    .reset_index()
                    .sort_values("total", ascending=False)
                )
                por_pago_rr["total"] = por_pago_rr["total"].apply(
                    lambda v: f"$ {v:,.2f}"
                )
                st.dataframe(
                    por_pago_rr,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "condicion_pago": st.column_config.TextColumn("Forma de pago"),
                        "items": st.column_config.NumberColumn("Items"),
                        "total": st.column_config.TextColumn("Total"),
                    },
                )

            # Precio promedio por producto (cada codigo/unidad por si mismo, sin conversiones)
            st.markdown("**Precio promedio por producto**")
            por_prod_rr = (
                df_rng.groupby(["codigo_producto", "producto_nombre"])
                .agg(cantidad=("cantidad", "sum"), gastado=("subtotal", "sum"))
                .reset_index()
            )
            por_prod_rr["precio_prom"] = (
                por_prod_rr["gastado"] / por_prod_rr["cantidad"]
            )
            por_prod_rr = por_prod_rr.sort_values("producto_nombre")
            disp_rr = por_prod_rr.copy()
            disp_rr["cantidad"] = disp_rr["cantidad"].apply(
                lambda v: f"{v:,.3f}".rstrip("0").rstrip(".")
            )
            disp_rr["gastado"] = disp_rr["gastado"].apply(lambda v: f"$ {v:,.2f}")
            disp_rr["precio_prom"] = disp_rr["precio_prom"].apply(
                lambda v: f"$ {v:,.2f}"
            )
            st.dataframe(
                disp_rr[["codigo_producto", "producto_nombre", "cantidad",
                          "precio_prom", "gastado"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "codigo_producto": st.column_config.TextColumn("Código"),
                    "producto_nombre": st.column_config.TextColumn("Producto"),
                    "cantidad": st.column_config.TextColumn("Cantidad"),
                    "precio_prom": st.column_config.TextColumn("Precio prom."),
                    "gastado": st.column_config.TextColumn("Gastado"),
                },
            )

            st.caption(
                f"📅 Rango: {fecha_desde_rr} → {fecha_hasta_rr} · "
                f"{len(df_rng)} líneas"
            )

with tab_desglose_rango:
    st.markdown("### 📐 Desglose por unidad (con conversiones)")
    st.caption(
        "Para cada producto: precio promedio en TODAS las unidades de su familia "
        "(usando las relaciones de compuestos). Ej: si compraste 1 caja de ACELGA, "
        "te muestra el precio equivalente en ATADO, KG, UNIDAD, etc."
    )

    df_dr = db.cargar_compras()
    if df_dr.empty:
        st.info("Todavía no hay compras cargadas.")
    else:
        cfg_dr = db.cargar_config()
        def_desde_dr = date.today() - timedelta(days=30)
        def_hasta_dr = date.today()
        if cfg_dr.get("dr_fecha_desde"):
            try:
                def_desde_dr = pd.to_datetime(cfg_dr["dr_fecha_desde"]).date()
            except Exception:
                pass
        if cfg_dr.get("dr_fecha_hasta"):
            try:
                def_hasta_dr = pd.to_datetime(cfg_dr["dr_fecha_hasta"]).date()
            except Exception:
                pass

        with st.form("form_desglose_rango", border=False):
            col_dr1, col_dr2, col_dr3 = st.columns([1, 1, 1])
            with col_dr1:
                fecha_desde_dr = st.date_input(
                    "Desde",
                    value=def_desde_dr,
                    key="dr_desde",
                    format="YYYY-MM-DD",
                )
            with col_dr2:
                fecha_hasta_dr = st.date_input(
                    "Hasta",
                    value=def_hasta_dr,
                    key="dr_hasta",
                    format="YYYY-MM-DD",
                )
            with col_dr3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                aplicar_dr = st.form_submit_button(
                    "🔄 Aplicar", type="primary", use_container_width=True
                )

        if aplicar_dr:
            try:
                db.guardar_config({
                    "dr_fecha_desde": str(fecha_desde_dr),
                    "dr_fecha_hasta": str(fecha_hasta_dr),
                })
            except Exception:
                pass

        df_dr["fecha_dt"] = pd.to_datetime(df_dr["fecha"], errors="coerce")
        mask_dr = (
            (df_dr["fecha_dt"] >= pd.to_datetime(fecha_desde_dr))
            & (df_dr["fecha_dt"] <= pd.to_datetime(fecha_hasta_dr))
        )
        df_rng_dr = df_dr[mask_dr].copy()

        if df_rng_dr.empty:
            st.warning("No hay compras en el rango seleccionado.")
        else:
            df_rng_dr["subtotal"] = (
                df_rng_dr["cantidad"].astype(float) * df_rng_dr["precio"].astype(float)
            )

            grafo_dr = construir_grafo_conversion(compuestos)
            prod_temp_dr = productos.copy()
            partes_pr_dr = (
                prod_temp_dr["producto"].astype(str).str.rsplit(" - ", n=1, expand=True)
            )
            prod_temp_dr["base"] = partes_pr_dr[0].str.strip()
            prod_temp_dr["unidad"] = (
                partes_pr_dr[1].fillna("").str.strip()
                if 1 in partes_pr_dr.columns
                else ""
            )

            df_prom_dr = df_rng_dr.copy()
            map_prod_full_dr = dict(
                zip(productos["codigo"].astype(str), productos["producto"].astype(str))
            )
            df_prom_dr["producto_full"] = (
                df_prom_dr["codigo_producto"].astype(str).map(map_prod_full_dr)
                .fillna(df_prom_dr["producto_nombre"])
            )
            partes_pr_src_dr = (
                df_prom_dr["producto_full"].str.rsplit(" - ", n=1, expand=True)
            )
            df_prom_dr["base"] = partes_pr_src_dr[0].str.strip()

            filas_prom_dr = []
            for base in df_prom_dr["base"].dropna().unique():
                lineas_base = df_prom_dr[df_prom_dr["base"] == base]
                if lineas_base.empty:
                    continue
                gastado_total = float(lineas_base["subtotal"].sum())

                familia = prod_temp_dr[prod_temp_dr["base"] == base]
                if familia.empty:
                    continue

                codigos_familia = familia["codigo"].astype(str).tolist()
                componentes = componentes_conectados(codigos_familia, grafo_dr)
                codigos_comprados = set(lineas_base["codigo_producto"].astype(str))

                comp_relevante = None
                for comp in componentes:
                    if comp & codigos_comprados:
                        comp_relevante = comp
                        break
                if not comp_relevante:
                    continue

                productos_comp = familia[
                    familia["codigo"].astype(str).isin(comp_relevante)
                ]
                unidades_unicas = list(
                    dict.fromkeys(productos_comp["unidad"].tolist())
                )

                for unidad in unidades_unicas:
                    if not unidad:
                        continue
                    codigo_destino = str(
                        productos_comp[productos_comp["unidad"] == unidad]
                        .iloc[0]["codigo"]
                    )
                    cantidad_total = 0.0
                    for _, linea in lineas_base.iterrows():
                        cod_origen = str(linea["codigo_producto"])
                        factor = convertir(grafo_dr, cod_origen, codigo_destino)
                        if factor is None:
                            continue
                        cantidad_total += float(linea["cantidad"]) * factor
                    if cantidad_total <= 0:
                        continue
                    filas_prom_dr.append({
                        "base": base,
                        "unidad": unidad,
                        "cantidad": cantidad_total,
                        "gastado": gastado_total,
                        "precio_promedio": gastado_total / cantidad_total,
                    })

            if filas_prom_dr:
                bases_orden_dr = sorted(set(f["base"] for f in filas_prom_dr))
                for base in bases_orden_dr:
                    filas_base_dr = [f for f in filas_prom_dr if f["base"] == base]
                    gastado_base_dr = filas_base_dr[0]["gastado"]
                    with st.expander(
                        f"**{base}** — $ {gastado_base_dr:,.2f}",
                        expanded=False,
                    ):
                        cols_h = st.columns([1, 1.2, 1.2])
                        cols_h[0].markdown("**Unidad**")
                        cols_h[1].markdown("**Cantidad**")
                        cols_h[2].markdown("**Precio prom.**")
                        for f in filas_base_dr:
                            cols = st.columns([1, 1.2, 1.2])
                            cols[0].markdown(f"**{f['unidad']}**")
                            cant_str = (
                                f"{f['cantidad']:,.3f}".rstrip("0").rstrip(".")
                            )
                            cols[1].markdown(cant_str)
                            cols[2].markdown(f"$ {f['precio_promedio']:,.2f}")
            else:
                st.caption("Sin datos para calcular precios promedio.")

            st.caption(
                f"📅 Rango: {fecha_desde_dr} → {fecha_hasta_dr} · "
                f"{len(df_rng_dr)} líneas"
            )

with tab_hist_precios:
    st.markdown("### 📊 Histórico de precios promedio")
    st.caption(
        "Para cada producto, ver el precio promedio ponderado en el rango elegido. "
        "Las compras se agrupan por producto y unidad."
    )

    df_compras_hp = db.cargar_compras()
    if df_compras_hp.empty:
        st.info("Todavía no hay compras cargadas.")
    else:
        cfg_hp = db.cargar_config()
        def_desde_hp = date.today() - timedelta(days=30)
        def_hasta_hp = date.today()
        if cfg_hp.get("hp_fecha_desde"):
            try:
                def_desde_hp = pd.to_datetime(cfg_hp["hp_fecha_desde"]).date()
            except Exception:
                pass
        if cfg_hp.get("hp_fecha_hasta"):
            try:
                def_hasta_hp = pd.to_datetime(cfg_hp["hp_fecha_hasta"]).date()
            except Exception:
                pass

        with st.form("form_hist_precios", border=False):
            col_hp1, col_hp2, col_hp3 = st.columns([1, 1, 1])
            with col_hp1:
                fecha_desde_hp = st.date_input(
                    "Desde",
                    value=def_desde_hp,
                    key="hp_desde",
                    format="YYYY-MM-DD",
                )
            with col_hp2:
                fecha_hasta_hp = st.date_input(
                    "Hasta",
                    value=def_hasta_hp,
                    key="hp_hasta",
                    format="YYYY-MM-DD",
                )
            with col_hp3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                aplicar_hp = st.form_submit_button(
                    "🔄 Aplicar", type="primary", use_container_width=True
                )

        if aplicar_hp:
            try:
                db.guardar_config({
                    "hp_fecha_desde": str(fecha_desde_hp),
                    "hp_fecha_hasta": str(fecha_hasta_hp),
                })
            except Exception:
                pass

        df_compras_hp["fecha_dt"] = pd.to_datetime(df_compras_hp["fecha"], errors="coerce")
        mask_hp = (
            (df_compras_hp["fecha_dt"] >= pd.to_datetime(fecha_desde_hp)) &
            (df_compras_hp["fecha_dt"] <= pd.to_datetime(fecha_hasta_hp))
        )
        df_rango_hp = df_compras_hp[mask_hp].copy()

        if df_rango_hp.empty:
            st.warning("No hay compras en el rango seleccionado.")
        else:
            df_rango_hp["subtotal"] = (
                df_rango_hp["cantidad"].astype(float) * df_rango_hp["precio"].astype(float)
            )

            # Agrupar por (codigo, producto_nombre) sin conversiones — cada
            # producto/unidad por si mismo.
            por_prod_hp = (
                df_rango_hp.groupby(["codigo_producto", "producto_nombre"])
                .agg(
                    cantidad=("cantidad", "sum"),
                    gastado=("subtotal", "sum"),
                    precio_min=("precio", "min"),
                    precio_max=("precio", "max"),
                )
                .reset_index()
            )
            por_prod_hp["precio_prom"] = por_prod_hp["gastado"] / por_prod_hp["cantidad"]
            por_prod_hp = por_prod_hp.sort_values("producto_nombre")

            prods_disp_hp = por_prod_hp["producto_nombre"].dropna().unique().tolist()
            filtro_prod_hp = st.multiselect(
                "Producto",
                options=sorted(prods_disp_hp),
                key="hp_filtro_prod_sel",
            )
            if filtro_prod_hp:
                por_prod_hp = por_prod_hp[
                    por_prod_hp["producto_nombre"].isin(filtro_prod_hp)
                ].reset_index(drop=True)

            st.caption(
                f"📅 Rango: {fecha_desde_hp} → {fecha_hasta_hp} · "
                f"{len(df_rango_hp)} compras · "
                f"{len(por_prod_hp)} productos"
            )

            disp_hp = por_prod_hp.copy()
            disp_hp["cantidad"] = disp_hp["cantidad"].apply(
                lambda v: f"{v:,.3f}".rstrip("0").rstrip(".")
            )
            disp_hp["gastado"] = disp_hp["gastado"].apply(lambda v: f"$ {v:,.2f}")
            disp_hp["precio_min"] = disp_hp["precio_min"].apply(lambda v: f"$ {v:,.2f}")
            disp_hp["precio_max"] = disp_hp["precio_max"].apply(lambda v: f"$ {v:,.2f}")
            disp_hp["precio_prom"] = disp_hp["precio_prom"].apply(lambda v: f"$ {v:,.2f}")
            st.dataframe(
                disp_hp[["codigo_producto", "producto_nombre", "cantidad",
                          "precio_min", "precio_prom", "precio_max", "gastado"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "codigo_producto": st.column_config.TextColumn("Código"),
                    "producto_nombre": st.column_config.TextColumn("Producto"),
                    "cantidad": st.column_config.TextColumn("Cantidad"),
                    "precio_min": st.column_config.TextColumn("Mín"),
                    "precio_prom": st.column_config.TextColumn("Promedio"),
                    "precio_max": st.column_config.TextColumn("Máx"),
                    "gastado": st.column_config.TextColumn("Gastado"),
                },
            )

            # Evolucion diaria de un producto especifico
            productos_disp_hp = sorted(por_prod_hp["producto_nombre"].unique().tolist())
            if productos_disp_hp:
                sel_hp = st.selectbox(
                    "📈 Ver evolución diaria de:",
                    options=["(elegir)"] + productos_disp_hp,
                    key="hp_evol_sel",
                )
                if sel_hp != "(elegir)":
                    df_evol = df_rango_hp[df_rango_hp["producto_nombre"] == sel_hp].copy()
                    df_evol_agg = (
                        df_evol.groupby(df_evol["fecha_dt"].dt.date)
                        .apply(lambda g: g["subtotal"].sum() / g["cantidad"].sum())
                        .reset_index(name="precio_prom")
                    )
                    df_evol_agg.columns = ["fecha", "precio_prom"]
                    df_evol_agg = df_evol_agg.set_index("fecha")
                    st.line_chart(df_evol_agg)

with tab_detalle_compras:
    st.markdown("### 📋 Detalle compras")
    st.caption(
        "Listado completo de compras: qué día, qué producto, qué proveedor, cuánto te cobró."
    )

    df_compras_dc = db.cargar_compras()
    if df_compras_dc.empty:
        st.info("Todavía no hay compras cargadas.")
    else:
        cfg_dc = db.cargar_config()
        def_desde_dc = date.today() - timedelta(days=30)
        def_hasta_dc = date.today()
        if cfg_dc.get("dc_fecha_desde"):
            try:
                def_desde_dc = pd.to_datetime(cfg_dc["dc_fecha_desde"]).date()
            except Exception:
                pass
        if cfg_dc.get("dc_fecha_hasta"):
            try:
                def_hasta_dc = pd.to_datetime(cfg_dc["dc_fecha_hasta"]).date()
            except Exception:
                pass

        with st.form("form_detalle_compras", border=False):
            col_dc1, col_dc2, col_dc3 = st.columns([1, 1, 1])
            with col_dc1:
                fecha_desde_dc = st.date_input(
                    "Desde",
                    value=def_desde_dc,
                    key="dc_desde",
                    format="YYYY-MM-DD",
                )
            with col_dc2:
                fecha_hasta_dc = st.date_input(
                    "Hasta",
                    value=def_hasta_dc,
                    key="dc_hasta",
                    format="YYYY-MM-DD",
                )
            with col_dc3:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                aplicar_dc = st.form_submit_button(
                    "🔄 Aplicar", type="primary", use_container_width=True
                )

        if aplicar_dc:
            try:
                db.guardar_config({
                    "dc_fecha_desde": str(fecha_desde_dc),
                    "dc_fecha_hasta": str(fecha_hasta_dc),
                })
            except Exception:
                pass

        df_compras_dc["fecha_dt"] = pd.to_datetime(
            df_compras_dc["fecha"], errors="coerce"
        )
        mask_dc = (
            (df_compras_dc["fecha_dt"] >= pd.to_datetime(fecha_desde_dc))
            & (df_compras_dc["fecha_dt"] <= pd.to_datetime(fecha_hasta_dc))
        )
        df_rango_dc = df_compras_dc[mask_dc].copy()

        if df_rango_dc.empty:
            st.warning("No hay compras en el rango seleccionado.")
        else:
            df_rango_dc["subtotal"] = (
                df_rango_dc["cantidad"].astype(float)
                * df_rango_dc["precio"].astype(float)
            )

            # Filtros opcionales
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                provs_disp = sorted(df_rango_dc["proveedor_nombre"].dropna().unique().tolist())
                filtro_prov = st.multiselect(
                    "Proveedor", options=provs_disp, key="dc_filtro_prov"
                )
            with col_f2:
                prods_disp_dc = sorted(
                    df_rango_dc["producto_nombre"].dropna().unique().tolist()
                )
                filtro_prod_dc = st.multiselect(
                    "Producto", options=prods_disp_dc, key="dc_filtro_prod_sel",
                )
            with col_f3:
                pagos_disp = sorted(df_rango_dc["condicion_pago"].dropna().unique().tolist())
                filtro_pago = st.multiselect(
                    "Forma de pago", options=pagos_disp, key="dc_filtro_pago"
                )

            if filtro_prov:
                df_rango_dc = df_rango_dc[
                    df_rango_dc["proveedor_nombre"].isin(filtro_prov)
                ]
            if filtro_prod_dc:
                df_rango_dc = df_rango_dc[
                    df_rango_dc["producto_nombre"].isin(filtro_prod_dc)
                ]
            if filtro_pago:
                df_rango_dc = df_rango_dc[
                    df_rango_dc["condicion_pago"].isin(filtro_pago)
                ]

            # Ordenar por fecha desc, luego proveedor
            df_rango_dc = df_rango_dc.sort_values(
                ["fecha", "proveedor_nombre", "producto_nombre"],
                ascending=[False, True, True],
            )

            total_filtrado = float(df_rango_dc["subtotal"].sum())
            st.caption(
                f"📅 Rango: {fecha_desde_dc} → {fecha_hasta_dc} · "
                f"{len(df_rango_dc)} líneas · "
                f"**Total filtrado: $ {total_filtrado:,.2f}**"
            )

            disp_dc = df_rango_dc.copy()
            disp_dc["cantidad"] = disp_dc["cantidad"].apply(lambda v: f"{v:,.2f}")
            disp_dc["precio"] = disp_dc["precio"].apply(lambda v: f"$ {v:,.2f}")
            disp_dc["subtotal"] = disp_dc["subtotal"].apply(lambda v: f"$ {v:,.2f}")
            st.dataframe(
                disp_dc[[
                    "fecha", "proveedor_nombre", "codigo_producto",
                    "producto_nombre", "cantidad", "precio", "subtotal",
                    "condicion_pago", "comprobante",
                ]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fecha": st.column_config.TextColumn("Fecha"),
                    "proveedor_nombre": st.column_config.TextColumn("Proveedor"),
                    "codigo_producto": st.column_config.TextColumn("Código"),
                    "producto_nombre": st.column_config.TextColumn("Producto"),
                    "cantidad": st.column_config.TextColumn("Cantidad"),
                    "precio": st.column_config.TextColumn("Precio unit."),
                    "subtotal": st.column_config.TextColumn("Subtotal"),
                    "condicion_pago": st.column_config.TextColumn("Cond. pago"),
                    "comprobante": st.column_config.TextColumn("Comprobante"),
                },
            )

with tab_mapeo:
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
                        use_container_width=True,
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
    ts_packs_ph.caption(f"🕒 Última actualización: **{ts_packs or '?'}**")


#python -m streamlit run app.py
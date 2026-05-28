import json
import re
import time
from datetime import date, datetime, timedelta

import requests
import streamlit as st
import pandas as pd
from pathlib import Path

DUX_RATE_LIMIT_SECONDS = 5.5


def ultima_sync(path):
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

st.set_page_config(page_title="Frutiverdu - Compuestos", layout="wide")

PRODUCTOS_CSV = Path("productos.csv")

COMPUESTOS_CSV = Path("compuestos.csv")
if not COMPUESTOS_CSV.exists():
    COMPUESTOS_CSV = Path("compuestos")

STOCK_CSV = Path("stock.csv")

PEDIDOS_DUX_JSON = Path("pedidos_dux.json")

ESTIMADO_CSV = Path("estimado.csv")

WIX_PEDIDOS_JSON = Path("wix_pedidos.json")

WIX_PRODUCTOS_CSV = Path("wix_productos.csv")

MAPPING_WIX_DUX_CSV = Path("mapping_wix_dux.csv")

PACKS_WIX_CSV = Path("packs_wix.csv")

EXCEPCIONES = {
    ("061", "062"),
    ("0256", "0205"),
}

st.title("🍎 Frutiverdu ")

st.markdown(
    """
<style>
/* Operativas (1-5) - verde */
.stTabs [data-baseweb="tab-list"] button:nth-child(-n+5) {
    background-color: #e8f5e9;
    border-top: 3px solid #2E7D32;
}
.stTabs [data-baseweb="tab-list"] button:nth-child(-n+5):hover {
    background-color: #c8e6c9;
}

/* Configuración (6-10) - naranja */
.stTabs [data-baseweb="tab-list"] button:nth-child(n+6) {
    background-color: #fff3e0;
    border-top: 3px solid #ef6c00;
}
.stTabs [data-baseweb="tab-list"] button:nth-child(n+6):hover {
    background-color: #ffe0b2;
}
</style>
""",
    unsafe_allow_html=True,
)


def cargar_productos():
    return pd.read_csv(PRODUCTOS_CSV, dtype={"codigo": str})


def cargar_compuestos():
    return pd.read_csv(
        COMPUESTOS_CSV,
        dtype={
            "codigo_origen": str,
            "codigo_componente": str,
        },
    )


def guardar_compuestos(df):
    df.to_csv(COMPUESTOS_CSV, index=False)


def cargar_stock():
    """Devuelve el stock de la última fecha guardada (para uso en Total a comprar)."""
    if not STOCK_CSV.exists():
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "cantidad"]
        )
    df = pd.read_csv(STOCK_CSV, dtype={"codigo": str})
    if "fecha" in df.columns and not df.empty:
        try:
            latest = pd.to_datetime(df["fecha"]).max()
            df = df[pd.to_datetime(df["fecha"]) == latest].drop(columns=["fecha"])
        except Exception:
            pass
    return df


def cargar_estimado_ultimo():
    """Devuelve el estimado de la última fecha guardada en estimado.csv."""
    if not ESTIMADO_CSV.exists():
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "estimado"]
        )
    df = pd.read_csv(ESTIMADO_CSV, dtype={"codigo": str})
    if "fecha" in df.columns and not df.empty:
        try:
            latest = pd.to_datetime(df["fecha"]).max()
            df = df[pd.to_datetime(df["fecha"]) == latest].drop(columns=["fecha"])
        except Exception:
            pass
    return df


def fechas_disponibles(csv_path):
    if not csv_path.exists():
        return []
    try:
        df = pd.read_csv(csv_path, dtype=str)
        if "fecha" not in df.columns:
            return []
        return sorted(df["fecha"].dropna().unique().tolist(), reverse=True)
    except Exception:
        return []


def cargar_estimado_fecha(fecha):
    if not ESTIMADO_CSV.exists():
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "estimado"]
        )
    df = pd.read_csv(ESTIMADO_CSV, dtype={"codigo": str})
    if "fecha" in df.columns:
        df = df[df["fecha"] == str(fecha)].drop(columns=["fecha"])
    return df


def cargar_stock_fecha(fecha):
    if not STOCK_CSV.exists():
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "cantidad"]
        )
    df = pd.read_csv(STOCK_CSV, dtype={"codigo": str})
    if "fecha" in df.columns:
        df = df[df["fecha"] == str(fecha)].drop(columns=["fecha"])
    return df


def _convertir_wix_orders_a_dux(orders_filtrados):
    """Convierte orders Wix (filtrados) en dict {dux_codigo: cantidad_total}
    usando mapping_wix_dux.csv y packs_wix.csv."""
    resultado = {}

    mapping = {}
    if MAPPING_WIX_DUX_CSV.exists():
        try:
            df_m = pd.read_csv(MAPPING_WIX_DUX_CSV, dtype=str)
            for _, r in df_m.iterrows():
                wid = str(r.get("wix_id", ""))
                dcod = str(r.get("dux_codigo", "") or "")
                try:
                    factor = float(r.get("factor", 1.0))
                except (ValueError, TypeError):
                    factor = 1.0
                if wid and dcod:
                    mapping[wid] = (dcod, factor)
        except Exception:
            pass

    packs = {}
    if PACKS_WIX_CSV.exists():
        try:
            df_p = pd.read_csv(PACKS_WIX_CSV, dtype={"dux_codigo": str, "wix_id_pack": str})
            for _, r in df_p.iterrows():
                pid = str(r.get("wix_id_pack", ""))
                dcod = str(r.get("dux_codigo", "") or "")
                try:
                    cant = float(r.get("cantidad", 0))
                except (ValueError, TypeError):
                    cant = 0.0
                if pid and dcod:
                    packs.setdefault(pid, []).append((dcod, cant))
        except Exception:
            pass

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

    return resultado


def cargar_pedidos_dux_aggregated(productos_df, estimado_fecha=None, fecha_compra=None):
    """Lee pedidos_dux.json, agrega cantidades por código y suma estimado
    de estimado.csv (de la fecha indicada o la última si es None).
    Si fecha_compra está dada, filtra los pedidos DUX por selecciones[fecha_compra]
    y agrega los pedidos de Wix con esa misma fecha de entrega."""
    cols = ["codigo", "producto", "unidad_medida", "cantidad", "estimado"]
    if not PEDIDOS_DUX_JSON.exists():
        df_agg = pd.DataFrame(columns=["codigo", "producto", "cantidad"])
        all_orders = []
        selecciones_dux = {}
    else:
        try:
            with open(PEDIDOS_DUX_JSON, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            saved = {"orders": [], "selecciones": {}}
        all_orders = saved.get("orders", [])
        selecciones_dux = saved.get("selecciones", {}) or {}

    if fecha_compra is not None:
        fecha_str = str(fecha_compra)
        all_orders = [
            o
            for o in all_orders
            if selecciones_dux.get(str(o.get("id") or o.get("nro_pedido") or "")) == fecha_str
        ]

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
    if fecha_compra is not None and WIX_PEDIDOS_JSON.exists():
        try:
            with open(WIX_PEDIDOS_JSON, "r", encoding="utf-8") as f:
                wix_saved_full = json.load(f)
            wix_orders = wix_saved_full.get("orders", [])
            wix_sel = wix_saved_full.get("selecciones", {}) or {}
            fecha_str = str(fecha_compra)
            wix_filtrados = [
                o for o in wix_orders if wix_sel.get(o.get("id")) == fecha_str
            ]
            wix_dux_map = _convertir_wix_orders_a_dux(wix_filtrados)
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

    if estimado_fecha is None:
        df_est = cargar_estimado_ultimo()
    else:
        df_est = cargar_estimado_fecha(estimado_fecha)

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


def guardar_stock(df):
    df.to_csv(STOCK_CSV, index=False)


def _dux_get_first(d, claves):
    if not isinstance(d, dict):
        return None
    for k in claves:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


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


productos = cargar_productos()
compuestos_orig = cargar_compuestos()
compuestos = completar_relaciones(compuestos_orig, productos, EXCEPCIONES)
if len(compuestos) != len(compuestos_orig):
    guardar_compuestos(compuestos)

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

(
    tab_comprar,
    tab_dux,
    tab_wix,
    tab_stock,
    tab_estimado,
    tab_mapeo,
    tab_packs,
    tab_dux_productos,
    tab_wix_productos,
    tab_editar,
    tab_probar,
) = st.tabs(
    [
        "🛒 Total a comprar",
        "📡 DUX Pedidos",
        "🛍️ Wix Orders",
        "📦 Stock",
        "📈 Estimado",
        "🔗 Mapeo Wix↔DUX",
        "🎁 Packs Wix",
        "📡 DUX Productos",
        "🛍️ Wix Productos",
        "⚙️ Editar valores",
        "🧪 Probar conversión",
    ]
)

with tab_editar:
    st.info(
        "Editá las cantidades de las equivalencias. Ejemplo: "
        "1 REPOLLO ROJO - CAJA = 15 REPOLLO ROJO - KG."
    )

    tabla_editor = compuestos[
        [
            "origen_label",
            "cantidad_origen",
            "componente_label",
            "cantidad_componente",
        ]
    ].copy()

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

    col1, col2 = st.columns([1, 4])

    with col1:
        guardar = st.button("💾 Guardar cambios", type="primary")

    with col2:
        st.caption("Los cambios se guardan en compuestos.csv.")

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

        guardar_compuestos(salida)
        st.success("Compuestos guardados correctamente.")

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
    st.info(
        "Cargá el stock por producto y fecha. "
        "Se guarda en `stock.csv` con histórico por fecha."
    )

    df_stock_full = None
    if STOCK_CSV.exists():
        try:
            df_stock_full = pd.read_csv(STOCK_CSV, dtype={"codigo": str})
        except Exception as e:
            st.error(f"No se pudo leer stock.csv: {e}")

    fecha_stock_default = date.today()
    if (
        df_stock_full is not None
        and "fecha" in df_stock_full.columns
        and not df_stock_full.empty
    ):
        try:
            fecha_stock_default = pd.to_datetime(df_stock_full["fecha"]).max().date()
        except Exception:
            pass

    col_st1, col_st2 = st.columns([1, 3])
    with col_st1:
        fecha_stock = st.date_input(
            "Fecha",
            value=fecha_stock_default,
            key="fecha_stock_local",
            format="YYYY-MM-DD",
        )
    with col_st2:
        ts_stock = ultima_sync(STOCK_CSV)
        st.caption(f"🕒 Última edición: **{ts_stock or '?'}**")

    map_stock_dia = {}
    if df_stock_full is not None and "fecha" in df_stock_full.columns:
        df_dia_stk = df_stock_full[df_stock_full["fecha"] == str(fecha_stock)]
        map_stock_dia = dict(
            zip(df_dia_stk["codigo"].astype(str), df_dia_stk["cantidad"])
        )

    base_stk = productos[["codigo", "producto", "unidad_medida"]].copy()
    base_stk["cantidad"] = (
        base_stk["codigo"]
        .astype(str)
        .map(map_stock_dia)
        .fillna(0.0)
        .astype(float)
    )

    if st.session_state.get("resetear_stock"):
        base_stk["cantidad"] = 0.0
        otros = (
            df_stock_full[df_stock_full["fecha"] != str(fecha_stock)]
            if df_stock_full is not None and "fecha" in df_stock_full.columns
            else pd.DataFrame(
                columns=["fecha", "codigo", "producto", "unidad_medida", "cantidad"]
            )
        )
        nuevo = base_stk.copy()
        nuevo["fecha"] = str(fecha_stock)
        combinado = pd.concat(
            [
                otros,
                nuevo[["fecha", "codigo", "producto", "unidad_medida", "cantidad"]],
            ],
            ignore_index=True,
        )
        combinado.to_csv(STOCK_CSV, index=False)
        st.session_state["resetear_stock"] = False
        st.success(f"Stock del {fecha_stock} puesto en cero.")

    buscar_stk = st.text_input(
        "🔎 Buscar producto",
        key="buscar_stock",
        placeholder="Filtra por nombre o código...",
    )
    if buscar_stk:
        mask = base_stk["producto"].str.contains(buscar_stk, case=False, na=False) | base_stk[
            "codigo"
        ].astype(str).str.contains(buscar_stk, case=False, na=False)
        base_stk_view = base_stk[mask].reset_index(drop=True)
    else:
        base_stk_view = base_stk

    with st.form(key=f"form_stock_{fecha_stock}", clear_on_submit=False):
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
        guardar_s = st.form_submit_button(
            "💾 Guardar stock", type="primary"
        )

    col_s2, col_s3 = st.columns([1, 4])
    with col_s2:
        cero_s = st.button(
            "🧹 Poner stock a cero",
            key="btn_cero_stock",
        )
    with col_s3:
        st.caption(f"Guarda para la fecha {fecha_stock}.")

    if guardar_s:
        # merge edits filtrados de vuelta al dataset completo
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
        salida_s["fecha"] = str(fecha_stock)
        otros = (
            df_stock_full[df_stock_full["fecha"] != str(fecha_stock)]
            if df_stock_full is not None and "fecha" in df_stock_full.columns
            else pd.DataFrame(
                columns=["fecha", "codigo", "producto", "unidad_medida", "cantidad"]
            )
        )
        combinado = pd.concat(
            [
                otros,
                salida_s[["fecha", "codigo", "producto", "unidad_medida", "cantidad"]],
            ],
            ignore_index=True,
        )
        combinado.to_csv(STOCK_CSV, index=False)
        st.success(f"Stock del {fecha_stock} guardado.")

    if cero_s:
        st.session_state["resetear_stock"] = True
        st.rerun()

with tab_comprar:
    ts_ped = ultima_sync(PEDIDOS_DUX_JSON)
    ts_wix = ultima_sync(WIX_PEDIDOS_JSON)
    ts_stk = ultima_sync(STOCK_CSV)
    ts_est = ultima_sync(ESTIMADO_CSV)
    st.caption(
        f"🕒 DUX: **{ts_ped or '?'}** · "
        f"Wix: **{ts_wix or '?'}** · "
        f"Stock: **{ts_stk or '?'}** · "
        f"Estimado: **{ts_est or '?'}**"
    )

    fecha_compra = st.date_input(
        "🛒 Fecha de compra (fecha de entrega)",
        value=date.today() + timedelta(days=1),
        key="comprar_fecha",
        format="YYYY-MM-DD",
        help=(
            "Filtra pedidos DUX y Wix con esa fecha de entrega asignada. "
            "Stock y estimado se leen de esa misma fecha."
        ),
    )

    pedidos_actual = cargar_pedidos_dux_aggregated(
        productos,
        estimado_fecha=fecha_compra,
        fecha_compra=fecha_compra,
    )
    stock_actual = cargar_stock_fecha(fecha_compra)

    if pedidos_actual is None or pedidos_actual.empty:
        st.warning(
            "No hay pedidos sincronizados. Andá a 📡 DUX Pedidos y apretá Sincronizar."
        )
    else:
        col_mc1, col_mc2 = st.columns([3, 2])
        with col_mc1:
            modo = st.radio(
                "Vista",
                ["Detallada (agrupada por producto)", "Simple (por código)"],
                horizontal=True,
                key="modo_comprar",
            )
        with col_mc2:
            buscar_comprar = st.text_input(
                "🔎 Buscar producto",
                key="buscar_comprar",
                placeholder="Filtra por nombre o código...",
            )

        grafo = construir_grafo_conversion(compuestos)

        prod_temp = productos.copy()
        partes_pr = prod_temp["producto"].str.rsplit(" - ", n=1, expand=True)
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
        partes_ped = ped["producto"].str.rsplit(" - ", n=1, expand=True)
        ped["base"] = partes_ped[0].str.strip()

        if stock_actual is not None and not stock_actual.empty:
            stk = stock_actual.dropna(subset=["producto"]).copy()
            stk["cantidad"] = stk["cantidad"].fillna(0)
            partes_stk = stk["producto"].str.rsplit(" - ", n=1, expand=True)
            stk["base"] = partes_stk[0].str.strip()
        else:
            stk = pd.DataFrame(
                columns=["codigo", "producto", "unidad_medida", "cantidad", "base"]
            )

        if modo.startswith("Detallada"):
            ped_relevante = ped[(ped["cantidad"] > 0) | (ped["estimado"] > 0)]
            bases = sorted(ped_relevante["base"].unique())
            if buscar_comprar:
                bases = [b for b in bases if buscar_comprar.lower() in b.lower()]

            col_h1, col_h2, col_h3, col_h4, col_h5, col_h6, col_h7 = st.columns(
                [1.8, 1.0, 0.8, 0.9, 0.8, 1.4, 1.4]
            )
            col_h1.caption("**Producto**")
            col_h2.caption("**Unidad**")
            col_h3.caption("**Pedido**")
            col_h4.caption("**Estimado**")
            col_h5.caption("**Stock**")
            col_h6.caption("**Resultado**")
            col_h7.caption("**Con estimado**")

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

                for comp in componentes:
                    if not (comp & pedido_codigos):
                        continue

                    comp_productos = opciones_grupo[
                        opciones_grupo["codigo"].astype(str).isin(comp)
                    ]
                    unidades_comp = comp_productos["unidad"].tolist()

                    col_t, col_u, col_p, col_est, col_s, col_r, col_e = st.columns(
                        [1.8, 1.0, 0.8, 0.9, 0.8, 1.4, 1.4]
                    )

                    if len(comp) == 1:
                        unica = comp_productos.iloc[0]
                        col_t.markdown(f"**{unica['producto']}**")
                        unidad_destino = unica["unidad"]
                        codigo_destino = str(unica["codigo"])
                        col_u.markdown(f"_{unidad_destino}_")
                    else:
                        col_t.markdown(f"**{base}**")
                        idx_default = (
                            unidades_comp.index("KG")
                            if "KG" in unidades_comp
                            else 0
                        )
                        key_sufijo = "-".join(sorted(comp))
                        unidad_destino = col_u.selectbox(
                            "Unidad",
                            unidades_comp,
                            index=idx_default,
                            key=f"unidad_comprar_{base}_{key_sufijo}",
                            label_visibility="collapsed",
                        )
                        codigo_destino = str(
                            comp_productos[
                                comp_productos["unidad"] == unidad_destino
                            ].iloc[0]["codigo"]
                        )

                    total_ped = 0.0
                    total_est = 0.0
                    for _, fila in ped_base.iterrows():
                        if str(fila["codigo"]) not in comp:
                            continue
                        factor = convertir(
                            grafo, str(fila["codigo"]), codigo_destino
                        )
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
                            factor = convertir(
                                grafo, str(fila["codigo"]), codigo_destino
                            )
                            if factor is None:
                                continue
                            total_stk += cant * factor

                    diff = total_ped - total_stk
                    diff_est = (total_ped + total_est) - total_stk

                    col_p.markdown(f"{total_ped:,.2f}")
                    col_est.markdown(f"{total_est:,.2f}")
                    col_s.markdown(f"{total_stk:,.2f}")

                    def render_diff(valor, col, unidad):
                        if valor > 0:
                            col.markdown(
                                f"<span style='color:#d11; font-weight:bold;'>"
                                f"Falta {valor:,.2f} {unidad}</span>",
                                unsafe_allow_html=True,
                            )
                        elif valor < 0:
                            col.markdown(
                                f"<span style='color:#1a8a1a; font-weight:bold;'>"
                                f"Sobra {-valor:,.2f} {unidad}</span>",
                                unsafe_allow_html=True,
                            )
                        else:
                            col.markdown(f"OK ({unidad})")

                    render_diff(diff, col_r, unidad_destino)
                    render_diff(diff_est, col_e, unidad_destino)

        else:
            ped_agg = ped.groupby(["codigo"], as_index=False)[
                ["cantidad", "estimado"]
            ].sum()
            ped_agg.columns = ["codigo", "pedido", "estimado"]

            if not stk.empty:
                stk_agg = stk.groupby(["codigo"], as_index=False)["cantidad"].sum()
                stk_agg.columns = ["codigo", "stock"]
            else:
                stk_agg = pd.DataFrame(columns=["codigo", "stock"])

            merged = ped_agg.merge(stk_agg, on="codigo", how="outer")
            merged["pedido"] = merged["pedido"].fillna(0).astype(float)
            merged["estimado"] = merged["estimado"].fillna(0).astype(float)
            merged["stock"] = merged["stock"].fillna(0).astype(float)
            merged["a_comprar"] = merged["pedido"] - merged["stock"]
            merged["a_comprar_estimado"] = (
                merged["pedido"] + merged["estimado"] - merged["stock"]
            )

            map_codigo_a_prod = dict(
                zip(productos["codigo"].astype(str), productos["producto"])
            )
            map_codigo_a_un = dict(
                zip(productos["codigo"].astype(str), productos["unidad_medida"])
            )
            merged["producto"] = merged["codigo"].astype(str).map(map_codigo_a_prod)
            merged["unidad"] = merged["codigo"].astype(str).map(map_codigo_a_un)
            merged = merged.sort_values("producto").reset_index(drop=True)
            merged = merged[
                [
                    "codigo",
                    "producto",
                    "unidad",
                    "pedido",
                    "estimado",
                    "stock",
                    "a_comprar",
                    "a_comprar_estimado",
                ]
            ]

            if buscar_comprar:
                mask = merged["producto"].astype(str).str.contains(
                    buscar_comprar, case=False, na=False
                ) | merged["codigo"].astype(str).str.contains(
                    buscar_comprar, case=False, na=False
                )
                merged = merged[mask].reset_index(drop=True)

            def color_a_comprar(v):
                if pd.isna(v) or v == 0:
                    return ""
                if v > 0:
                    return "color: #d11; font-weight: bold;"
                return "color: #1a8a1a; font-weight: bold;"

            try:
                styled = merged.style.map(
                    color_a_comprar,
                    subset=["a_comprar", "a_comprar_estimado"],
                )
            except AttributeError:
                styled = merged.style.applymap(
                    color_a_comprar,
                    subset=["a_comprar", "a_comprar_estimado"],
                )

            styled = styled.format(
                {
                    "pedido": "{:.2f}",
                    "estimado": "{:.2f}",
                    "stock": "{:.2f}",
                    "a_comprar": "{:+.2f}",
                    "a_comprar_estimado": "{:+.2f}",
                }
            )

            st.dataframe(styled, use_container_width=True, hide_index=True)

            st.caption(
                "**a_comprar** = `pedido − stock`. "
                "**a_comprar_estimado** = `(pedido + estimado) − stock`. "
                "Positivo (rojo) = falta comprar · negativo (verde) = sobra."
            )

with tab_estimado:
    st.info(
        "Cargá el estimado de compra adicional por producto y fecha. "
        "Se guarda en `estimado.csv` con histórico por fecha."
    )

    df_est_full = None
    if ESTIMADO_CSV.exists():
        try:
            df_est_full = pd.read_csv(ESTIMADO_CSV, dtype={"codigo": str})
        except Exception as e:
            st.error(f"No se pudo leer estimado.csv: {e}")

    fecha_est_default = date.today()
    if (
        df_est_full is not None
        and "fecha" in df_est_full.columns
        and not df_est_full.empty
    ):
        try:
            fecha_est_default = pd.to_datetime(df_est_full["fecha"]).max().date()
        except Exception:
            pass

    col_es1, col_es2 = st.columns([1, 3])
    with col_es1:
        fecha_estimado = st.date_input(
            "Fecha",
            value=fecha_est_default,
            key="fecha_estimado",
            format="YYYY-MM-DD",
        )
    with col_es2:
        ts_est = ultima_sync(ESTIMADO_CSV)
        st.caption(f"🕒 Última edición: **{ts_est or '?'}**")

    map_est_dia = {}
    if df_est_full is not None and "fecha" in df_est_full.columns:
        df_dia = df_est_full[df_est_full["fecha"] == str(fecha_estimado)]
        map_est_dia = dict(
            zip(df_dia["codigo"].astype(str), df_dia["estimado"])
        )

    base_est = productos[["codigo", "producto", "unidad_medida"]].copy()
    base_est["estimado"] = (
        base_est["codigo"]
        .astype(str)
        .map(map_est_dia)
        .fillna(0.0)
        .astype(float)
    )

    if st.session_state.get("reset_estimado"):
        base_est["estimado"] = 0.0
        # persist reset
        otros = (
            df_est_full[df_est_full["fecha"] != str(fecha_estimado)]
            if df_est_full is not None and "fecha" in df_est_full.columns
            else pd.DataFrame(
                columns=["fecha", "codigo", "producto", "unidad_medida", "estimado"]
            )
        )
        nuevo = base_est.copy()
        nuevo["fecha"] = str(fecha_estimado)
        combinado = pd.concat(
            [
                otros,
                nuevo[["fecha", "codigo", "producto", "unidad_medida", "estimado"]],
            ],
            ignore_index=True,
        )
        combinado.to_csv(ESTIMADO_CSV, index=False)
        st.session_state["reset_estimado"] = False
        st.success(f"Estimado del {fecha_estimado} puesto en cero.")

    buscar_est = st.text_input(
        "🔎 Buscar producto",
        key="buscar_estimado",
        placeholder="Filtra por nombre o código...",
    )
    if buscar_est:
        mask = base_est["producto"].str.contains(buscar_est, case=False, na=False) | base_est[
            "codigo"
        ].astype(str).str.contains(buscar_est, case=False, na=False)
        base_est_view = base_est[mask].reset_index(drop=True)
    else:
        base_est_view = base_est

    with st.form(key=f"form_estimado_{fecha_estimado}", clear_on_submit=False):
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
            key=f"editor_estimado_{fecha_estimado}",
        )
        guardar_est = st.form_submit_button(
            "💾 Guardar estimado", type="primary"
        )

    col_eb2, col_eb3 = st.columns([1, 4])
    with col_eb2:
        reset_est = st.button(
            "🧹 Resetear a cero",
            key="btn_reset_estimado",
        )
    with col_eb3:
        st.caption(f"Guarda para la fecha {fecha_estimado}.")

    if guardar_est:
        # merge edits filtrados de vuelta al dataset completo
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
        salida["fecha"] = str(fecha_estimado)

        otros = (
            df_est_full[df_est_full["fecha"] != str(fecha_estimado)]
            if df_est_full is not None and "fecha" in df_est_full.columns
            else pd.DataFrame(
                columns=["fecha", "codigo", "producto", "unidad_medida", "estimado"]
            )
        )

        combinado = pd.concat(
            [
                otros,
                salida[["fecha", "codigo", "producto", "unidad_medida", "estimado"]],
            ],
            ignore_index=True,
        )
        combinado.to_csv(ESTIMADO_CSV, index=False)
        st.success(f"Estimado del {fecha_estimado} guardado.")

    if reset_est:
        st.session_state["reset_estimado"] = True
        st.rerun()

with tab_dux:
    st.info(
        "Consulta pedidos del ERP DUX. "
        "El token vive en `.streamlit/secrets.toml` (no se commitea)."
    )

    dux_cfg = st.secrets.get("dux", {})
    token = dux_cfg.get("token", "")
    base_url = dux_cfg.get(
        "base_url", "https://erp.duxsoftware.com.ar/WSERP/rest/services"
    )
    id_empresa_default = int(dux_cfg.get("id_empresa", 3455))
    id_sucursal_default = int(dux_cfg.get("id_sucursal", 3))

    def _get_first(d, claves):
        if not isinstance(d, dict):
            return None
        for k in claves:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return None

    def _extraer_cliente(orden):
        cliente_obj = orden.get("cliente")
        if isinstance(cliente_obj, dict):
            nombre = _get_first(
                cliente_obj,
                ["razon_social", "nombre", "razonSocial", "nombre_completo"],
            )
            if nombre:
                return str(nombre)
        return str(
            _get_first(
                orden,
                ["cliente", "razon_social", "razonSocial", "nombre_cliente",
                 "apellido_razon_social"],
            )
            or "(sin cliente)"
        )

    def _extraer_items_dux(orden):
        for f in ["detalles", "items", "productos", "lineas", "renglones", "detalle"]:
            v = orden.get(f)
            if isinstance(v, list):
                return v
        return []

    def _extraer_item(item):
        codigo = _get_first(
            item,
            ["cod_item", "codItem", "codigo", "codigoItem",
             "codigoProducto", "cod_producto"],
        )
        descr = _get_first(
            item,
            ["item", "descripcion", "producto", "detalle", "nombre"],
        )
        cant = _get_first(
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

    if not token:
        st.error(
            "Falta configurar el token de DUX en `.streamlit/secrets.toml` "
            "bajo `[dux] token = \"...\"`."
        )
    else:
        id_empresa = id_empresa_default
        id_sucursal = id_sucursal_default

        all_orders_saved = []
        selecciones_dux = {}
        fecha_desde_default = date.today() - timedelta(days=7)
        fecha_hasta_default = date.today()
        if PEDIDOS_DUX_JSON.exists():
            try:
                with open(PEDIDOS_DUX_JSON, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                all_orders_saved = saved.get("orders", [])
                selecciones_dux = saved.get("selecciones", {}) or {}
                if saved.get("fecha_desde"):
                    fecha_desde_default = pd.to_datetime(saved["fecha_desde"]).date()
                if saved.get("fecha_hasta"):
                    fecha_hasta_default = pd.to_datetime(saved["fecha_hasta"]).date()
            except Exception as e:
                st.error(f"No se pudo leer pedidos_dux.json: {e}")

        col_d1, col_d2 = st.columns(2)
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

        consultar = st.button(
            "🔄 Sincronizar pedidos desde DUX",
            type="primary",
            key="dux_consultar",
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
                        "estadoFacturacion": "PENDIENTE",
                    }
                    try:
                        r = requests.get(
                            url_p, params=params_p, headers=headers_p, timeout=30
                        )
                    except requests.RequestException as e:
                        st.error(f"Error de red: {e}")
                        error_corte = True
                        break

                    if r.status_code != 200:
                        st.error(f"HTTP {r.status_code}: {r.text[:500]}")
                        error_corte = True
                        break

                    try:
                        d = r.json()
                    except ValueError:
                        st.error("Respuesta no JSON.")
                        error_corte = True
                        break

                    if isinstance(d, dict) and "message" in d and "results" not in d:
                        st.error(f"DUX respondió: {d['message']}")
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
                    with open(PEDIDOS_DUX_JSON, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "fecha_desde": str(fecha_desde),
                                "fecha_hasta": str(fecha_hasta),
                                "orders": all_orders,
                                "selecciones": selecciones_dux,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                except Exception as e:
                    st.error(f"No se pudo guardar pedidos_dux.json: {e}")

                all_orders_saved = all_orders
                if all_orders:
                    st.success(
                        f"✅ {len(all_orders)} pedidos guardados en `pedidos_dux.json`."
                    )
                else:
                    st.warning("No hay pedidos pendientes en ese rango.")

        st.divider()

        if all_orders_saved:
            ts_ped = ultima_sync(PEDIDOS_DUX_JSON)
            n_asignados = sum(1 for v in selecciones_dux.values() if v)
            st.caption(
                f"📅 Rango: {fecha_desde_default} → {fecha_hasta_default} · "
                f"🕒 Última sync: **{ts_ped or '?'}** · "
                f"{n_asignados} con entrega asignada."
            )

            buscar_dux_ped = st.text_input(
                "🔎 Buscar pedido (cliente / nro)",
                key="buscar_dux_pedidos",
                placeholder="Filtra por nombre de cliente o número...",
            )

            with st.form(key="form_dux_seleccion", clear_on_submit=False):
                nuevas_selecciones_dux = {}
                for i, orden in enumerate(all_orders_saved, start=1):
                    cliente_str = _extraer_cliente(orden)
                    nro = _get_first(
                        orden,
                        ["nro_pedido", "nroPedido", "numero", "id"],
                    )
                    if buscar_dux_ped:
                        q = buscar_dux_ped.lower()
                        if q not in cliente_str.lower() and q not in str(nro or "").lower():
                            continue
                    items = _extraer_items_dux(orden)

                    oid = str(orden.get("id") or nro or i)
                    asignado_prev = selecciones_dux.get(oid)
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
                                f"**#{nro or i}** — {cliente_str} · {len(items)} ítems{badge}"
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
                                filas = [_extraer_item(it) for it in items]
                                st.dataframe(
                                    pd.DataFrame(filas),
                                    use_container_width=True,
                                    hide_index=True,
                                )

                guardar_sel_dux = st.form_submit_button(
                    "💾 Guardar selección de entregas", type="primary"
                )

            if guardar_sel_dux:
                try:
                    with open(PEDIDOS_DUX_JSON, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "fecha_desde": str(fecha_desde_default),
                                "fecha_hasta": str(fecha_hasta_default),
                                "orders": all_orders_saved,
                                "selecciones": nuevas_selecciones_dux,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                    st.success(
                        f"✅ {len(nuevas_selecciones_dux)} entregas guardadas."
                    )
                    selecciones_dux = nuevas_selecciones_dux
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")

            st.divider()
            st.subheader("📊 Suma de productos pendientes")

            items_planos = []
            sin_items = 0
            for orden in all_orders_saved:
                items = _extraer_items_dux(orden)
                if not items:
                    sin_items += 1
                    continue
                for item in items:
                    items_planos.append(_extraer_item(item))

            if items_planos:
                df_items = pd.DataFrame(items_planos)
                df_sum = (
                    df_items.groupby(["codigo", "producto"], as_index=False)[
                        "cantidad"
                    ].sum()
                    .sort_values("producto")
                    .reset_index(drop=True)
                )
                st.dataframe(df_sum, use_container_width=True, hide_index=True)
                st.caption(
                    f"{len(df_sum)} productos distintos · "
                    f"Suma total: {df_sum['cantidad'].sum():,.2f}"
                )
            else:
                st.warning("No pude detectar items dentro de los pedidos.")
        else:
            st.warning(
                "Todavía no hay pedidos guardados. Apretá **Sincronizar** para traerlos."
            )

with tab_dux_productos:
    st.info(
        "Catálogo local (`productos.csv`). El resto del app lee de acá. "
        "Si actualizaste productos en DUX, apretá **Sincronizar** para refrescar el CSV."
    )

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
                    st.error(f"Error de red: {e}")
                    error_corte = True
                    break

                if r.status_code != 200:
                    st.error(f"HTTP {r.status_code}: {r.text[:500]}")
                    error_corte = True
                    break

                try:
                    d = r.json()
                except ValueError:
                    st.error("Respuesta no JSON.")
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

                    df_nuevo.to_csv(PRODUCTOS_CSV, index=False)

                    st.success(
                        f"✅ Sincronizado. {len(df_nuevo)} productos guardados en `productos.csv`."
                    )

        st.divider()
        st.subheader("📋 Productos cargados")

        if PRODUCTOS_CSV.exists():
            try:
                df_csv_actual = pd.read_csv(PRODUCTOS_CSV, dtype={"codigo": str})
                cols_mostrar = [
                    c
                    for c in ["codigo", "producto", "unidad_medida"]
                    if c in df_csv_actual.columns
                ]
                ts_prod = ultima_sync(PRODUCTOS_CSV)
                st.caption(
                    f"{len(df_csv_actual)} productos · "
                    f"🕒 última sync: **{ts_prod or '?'}**"
                )

                buscar_prod = st.text_input(
                    "🔎 Buscar producto",
                    key="buscar_dux_productos",
                    placeholder="Filtra por nombre o código...",
                )
                df_show = df_csv_actual[cols_mostrar].sort_values("producto").reset_index(drop=True)
                if buscar_prod:
                    mask = df_show["producto"].astype(str).str.contains(
                        buscar_prod, case=False, na=False
                    ) | df_show["codigo"].astype(str).str.contains(
                        buscar_prod, case=False, na=False
                    )
                    df_show = df_show[mask].reset_index(drop=True)

                st.dataframe(
                    df_show,
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception as e:
                st.error(f"No se pudo leer productos.csv: {e}")
        else:
            st.warning(
                "Todavía no hay `productos.csv`. Apretá **Sincronizar** para crearlo."
            )

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
        wix_saved = {"orders": [], "selecciones": {}, "fecha_desde": None, "fecha_hasta": None}
        if WIX_PEDIDOS_JSON.exists():
            try:
                with open(WIX_PEDIDOS_JSON, "r", encoding="utf-8") as f:
                    wix_saved = json.load(f)
            except Exception as e:
                st.error(f"No se pudo leer wix_pedidos.json: {e}")

        fecha_desde_default = date.today() - timedelta(days=3)
        fecha_hasta_default = date.today()
        if wix_saved.get("fecha_desde"):
            try:
                fecha_desde_default = pd.to_datetime(wix_saved["fecha_desde"]).date()
            except Exception:
                pass
        if wix_saved.get("fecha_hasta"):
            try:
                fecha_hasta_default = pd.to_datetime(wix_saved["fecha_hasta"]).date()
            except Exception:
                pass

        col_w1, col_w2 = st.columns(2)
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

        consultar_wix = st.button(
            "🔄 Sincronizar orders desde Wix",
            type="primary",
            key="wix_consultar",
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
                st.error(f"Error de red: {e}")
                resp = None

            if resp is not None:
                if resp.status_code != 200:
                    st.error(f"HTTP {resp.status_code}: {resp.text[:500]}")
                else:
                    try:
                        data = resp.json()
                    except ValueError:
                        st.error("Respuesta no JSON.")
                        data = None

                    if data is not None:
                        orders = data.get("orders", [])
                        try:
                            with open(WIX_PEDIDOS_JSON, "w", encoding="utf-8") as f:
                                json.dump(
                                    {
                                        "fecha_desde": str(wix_desde),
                                        "fecha_hasta": str(wix_hasta),
                                        "orders": orders,
                                        "selecciones": wix_saved.get("selecciones", {}),
                                    },
                                    f,
                                    ensure_ascii=False,
                                    indent=2,
                                )
                        except Exception as e:
                            st.error(f"No se pudo guardar wix_pedidos.json: {e}")
                        wix_saved["orders"] = orders
                        st.success(f"✅ {len(orders)} orders guardadas.")

        st.divider()

        orders_saved = wix_saved.get("orders", []) or []
        selecciones = dict(wix_saved.get("selecciones", {}) or {})

        if not orders_saved:
            st.warning("Todavía no hay orders. Apretá **Sincronizar**.")
        else:
            ts_wix = ultima_sync(WIX_PEDIDOS_JSON)
            st.caption(
                f"{len(orders_saved)} orders · 🕒 última sync: **{ts_wix or '?'}** · "
                f"{len(selecciones)} con entrega asignada."
            )

            buscar_wix = st.text_input(
                "🔎 Buscar pedido (número o cliente)",
                key="buscar_wix",
                placeholder="Filtra...",
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

            with st.form(key="form_wix_seleccion", clear_on_submit=False):
                nuevas_selecciones = {}
                for o in orders_saved:
                    nro = _wix_nro(o)
                    cliente = _wix_cliente(o)
                    items = o.get("lineItems", [])
                    total = (
                        o.get("priceSummary", {}).get("total", {}).get("formattedAmount", "")
                    )
                    direccion = _fmt_addr(_wix_address(o))
                    email = _wix_email(o)

                    if buscar_wix:
                        q = buscar_wix.lower()
                        if q not in nro.lower() and q not in cliente.lower():
                            continue

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

                guardar_sel = st.form_submit_button(
                    "💾 Guardar selección de entregas", type="primary"
                )

            if guardar_sel:
                wix_saved["selecciones"] = nuevas_selecciones
                try:
                    with open(WIX_PEDIDOS_JSON, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "fecha_desde": wix_saved.get("fecha_desde"),
                                "fecha_hasta": wix_saved.get("fecha_hasta"),
                                "orders": wix_saved.get("orders", []),
                                "selecciones": nuevas_selecciones,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                    st.success(
                        f"✅ {len(nuevas_selecciones)} entregas guardadas."
                    )
                except Exception as e:
                    st.error(f"No se pudo guardar: {e}")

with tab_wix_productos:
    st.info(
        "Catálogo local de Wix (`wix_productos.csv`). "
        "Apretá **Sincronizar** para refrescar desde Wix."
    )

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
                    st.error(f"Error de red: {e}")
                    error_corte = True
                    break

                if r.status_code != 200:
                    st.error(f"HTTP {r.status_code}: {r.text[:500]}")
                    error_corte = True
                    break

                try:
                    d = r.json()
                except ValueError:
                    st.error("Respuesta no JSON.")
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
                    df_wix_prods.to_csv(WIX_PRODUCTOS_CSV, index=False)
                    st.success(
                        f"✅ Sincronizado. {len(df_wix_prods)} productos guardados en `wix_productos.csv`."
                    )

        st.divider()
        st.subheader("📋 Productos cargados")

        if WIX_PRODUCTOS_CSV.exists():
            try:
                df_wix_csv = pd.read_csv(WIX_PRODUCTOS_CSV)
                ts_wix_prod = ultima_sync(WIX_PRODUCTOS_CSV)
                st.caption(
                    f"{len(df_wix_csv)} productos · "
                    f"🕒 última sync: **{ts_wix_prod or '?'}**"
                )

                buscar_wix_prod = st.text_input(
                    "🔎 Buscar producto",
                    key="buscar_wix_productos",
                    placeholder="Filtra por nombre o descripción...",
                )

                df_show_wp = df_wix_csv.copy()
                if "descripcion" not in df_show_wp.columns:
                    df_show_wp["descripcion"] = ""
                if buscar_wix_prod:
                    q = buscar_wix_prod.lower()
                    mask = (
                        df_show_wp["producto"].astype(str).str.lower().str.contains(q, na=False)
                        | df_show_wp["descripcion"].astype(str).str.lower().str.contains(q, na=False)
                    )
                    df_show_wp = df_show_wp[mask].reset_index(drop=True)

                st.dataframe(
                    df_show_wp[["producto", "descripcion"]],
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception as e:
                st.error(f"No se pudo leer wix_productos.csv: {e}")
        else:
            st.warning(
                "Todavía no hay `wix_productos.csv`. Apretá **Sincronizar**."
            )

with tab_mapeo:
    st.info(
        "Mapeá cada producto de Wix con su equivalente en DUX. "
        "Lo que no tenga equivalente, dejalo en **(sin mapear)**."
    )

    falta_dux = not PRODUCTOS_CSV.exists()
    falta_wix = not WIX_PRODUCTOS_CSV.exists()

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
        df_dux_p = pd.read_csv(PRODUCTOS_CSV, dtype={"codigo": str})
        df_wix_p = pd.read_csv(WIX_PRODUCTOS_CSV)
        df_wix_p["wix_id"] = df_wix_p["wix_id"].astype(str)
        df_wix_p["producto"] = df_wix_p["producto"].astype(str)
        df_wix_p = df_wix_p.sort_values("producto").reset_index(drop=True)

        mapping_actual = {}
        factor_actual = {}
        if MAPPING_WIX_DUX_CSV.exists():
            try:
                df_map = pd.read_csv(MAPPING_WIX_DUX_CSV, dtype=str)
                mapping_actual = dict(
                    zip(df_map["wix_id"].astype(str), df_map["dux_codigo"].astype(str))
                )
                if "factor" in df_map.columns:
                    factor_actual = {}
                    for wid, f in zip(df_map["wix_id"].astype(str), df_map["factor"]):
                        try:
                            factor_actual[wid] = float(f)
                        except (ValueError, TypeError):
                            factor_actual[wid] = 1.0
            except Exception as e:
                st.error(f"No se pudo leer mapping_wix_dux.csv: {e}")

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

        col_h1, col_h2 = st.columns([3, 1])
        with col_h1:
            buscar_mapeo = st.text_input(
                "🔎 Buscar producto Wix",
                key="buscar_mapeo",
                placeholder="Filtra por nombre Wix...",
            )
        with col_h2:
            solo_sin_mapear = st.checkbox(
                "Solo sin mapear",
                value=False,
                key="solo_sin_mapear",
            )

        ts_map = ultima_sync(MAPPING_WIX_DUX_CSV)
        mapeados = sum(1 for v in mapping_actual.values() if v)
        st.caption(
            f"{mapeados} / {len(df_wix_p)} productos mapeados · "
            f"🕒 última edición: **{ts_map or '?'}**"
        )

        with st.form(key="form_mapeo_wix_dux", clear_on_submit=False):
            st.caption(
                "💡 **Factor** = cuántas unidades DUX representa 1 unidad Wix. "
                "Ej: Wix `VERDEO - 1/4 KG` → DUX `VERDEO - ATADO` con factor `0.25`."
            )
            nuevo_mapping = {}
            nuevo_factor = {}
            mostradas = 0
            for _, row in df_wix_p.iterrows():
                wid = str(row["wix_id"])
                wname = str(row["producto"])

                if buscar_mapeo and buscar_mapeo.lower() not in wname.lower():
                    continue

                current_codigo = mapping_actual.get(wid, "")
                if solo_sin_mapear and current_codigo:
                    continue

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
                mostradas += 1

            st.caption(f"Mostrando {mostradas} productos.")

            guardar_map = st.form_submit_button(
                "💾 Guardar mapeo", type="primary"
            )

        if guardar_map:
            # Merge: keep existing mappings for products NOT shown (e.g., filtered out)
            shown_ids = set()
            for _, row in df_wix_p.iterrows():
                wid = str(row["wix_id"])
                wname = str(row["producto"])
                if buscar_mapeo and buscar_mapeo.lower() not in wname.lower():
                    continue
                if solo_sin_mapear and mapping_actual.get(wid, ""):
                    continue
                shown_ids.add(wid)

            # Start from existing, override only the shown ones
            merged_map = {
                wid: code for wid, code in mapping_actual.items() if wid not in shown_ids
            }
            merged_map.update(nuevo_mapping)

            merged_factor = {
                wid: factor_actual.get(wid, 1.0)
                for wid in mapping_actual
                if wid not in shown_ids
            }
            merged_factor.update(nuevo_factor)

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

            pd.DataFrame(
                rows,
                columns=[
                    "wix_id",
                    "wix_producto",
                    "dux_codigo",
                    "dux_producto",
                    "factor",
                ],
            ).to_csv(MAPPING_WIX_DUX_CSV, index=False)

            st.success(f"✅ {len(rows)} mapeos guardados.")

with tab_packs:
    st.info(
        "Configurá la composición de cada PACK de Wix con productos DUX y cantidades. "
        "Agregá / quitá filas según necesites."
    )

    if not WIX_PRODUCTOS_CSV.exists():
        st.warning("Falta sincronizar 🛍️ Wix Productos primero.")
    elif not PRODUCTOS_CSV.exists():
        st.warning("Falta sincronizar 📡 DUX Productos primero.")
    else:
        df_wix_p_packs = pd.read_csv(WIX_PRODUCTOS_CSV)
        df_dux_p_packs = pd.read_csv(PRODUCTOS_CSV, dtype={"codigo": str})

        df_packs = df_wix_p_packs[
            df_wix_p_packs["producto"].astype(str).str.upper().str.startswith("PACK")
        ].copy()

        if df_packs.empty:
            st.warning(
                "No se encontraron productos PACK en `wix_productos.csv`."
            )
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

            df_packs_saved = pd.DataFrame(
                columns=[
                    "wix_id_pack",
                    "pack_nombre",
                    "dux_codigo",
                    "dux_producto",
                    "cantidad",
                ]
            )
            if PACKS_WIX_CSV.exists():
                try:
                    df_packs_saved = pd.read_csv(
                        PACKS_WIX_CSV, dtype={"dux_codigo": str, "wix_id_pack": str}
                    )
                except Exception as e:
                    st.error(f"No se pudo leer packs_wix.csv: {e}")

            ts_packs = ultima_sync(PACKS_WIX_CSV)
            st.caption(f"🕒 última edición: **{ts_packs or '?'}**")

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

            if st.button("💾 Guardar packs", type="primary", key="btn_guardar_packs"):
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

                pd.DataFrame(
                    rows_save,
                    columns=[
                        "wix_id_pack",
                        "pack_nombre",
                        "dux_codigo",
                        "dux_producto",
                        "cantidad",
                    ],
                ).to_csv(PACKS_WIX_CSV, index=False)

                st.success(
                    f"✅ Packs guardados ({len(rows_save)} líneas totales)."
                )


#python -m streamlit run app.py
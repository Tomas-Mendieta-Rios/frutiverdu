import re
import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Frutiverdu - Compuestos", layout="wide")

PRODUCTOS_CSV = Path("productos.csv")

COMPUESTOS_CSV = Path("compuestos.csv")
if not COMPUESTOS_CSV.exists():
    COMPUESTOS_CSV = Path("compuestos")

STOCK_CSV = Path("stock.csv")

PEDIDOS_CSV = Path("pedidos.csv")

st.title("🍎 Frutiverdu - Editor de Compuestos")


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
    if not STOCK_CSV.exists():
        return pd.DataFrame(
            columns=["codigo", "producto", "unidad_medida", "cantidad"]
        )
    return pd.read_csv(STOCK_CSV, dtype={"codigo": str})


def guardar_stock(df):
    df.to_csv(STOCK_CSV, index=False)


def cargar_pedidos():
    if not PEDIDOS_CSV.exists():
        return None
    return pd.read_csv(PEDIDOS_CSV, dtype={"codigo": str})


def guardar_pedidos(df):
    df.to_csv(PEDIDOS_CSV, index=False)


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


def completar_relaciones(compuestos_df, productos_df):
    prio = {u: i for i, u in enumerate(UNIDAD_BASE_PRIORIDAD)}

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

    columnas = [
        "codigo_origen",
        "producto_origen",
        "cantidad_origen",
        "codigo_componente",
        "producto_componente",
        "cantidad_componente",
    ]

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
compuestos = completar_relaciones(compuestos_orig, productos)
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

tab_editar, tab_probar, tab_stock, tab_pedidos, tab_comprar = st.tabs(
    [
        "⚙️ Editar valores",
        "🧪 Probar conversión",
        "📦 Stock",
        "📋 Pedidos",
        "🛒 Total a comprar",
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
            "origen_label": st.column_config.TextColumn(
                "Producto origen",
            ),
            "cantidad_origen": st.column_config.NumberColumn(
                "Cantidad origen",
                min_value=0.0,
                step=1.0,
                format="%.3f",
            ),
            "componente_label": st.column_config.TextColumn(
                "Producto componente/base",
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
        st.caption("Los cambios se guardan en compuestos.csv o compuestos.")

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
    opciones_prueba = tabla_editada["origen_label"].dropna().unique()

    if len(opciones_prueba) == 0:
        st.warning("No hay productos origen para probar.")
    else:
        producto_prueba = st.selectbox(
            "Producto origen",
            opciones_prueba,
        )

        cantidad_prueba = st.number_input(
            "Cantidad",
            min_value=0.0,
            value=1.0,
            step=0.5,
        )

        fila = tabla_editada[tabla_editada["origen_label"] == producto_prueba]

        if not fila.empty:
            fila = fila.iloc[0]

            cantidad_origen = fila["cantidad_origen"]
            cantidad_componente = fila["cantidad_componente"]

            if pd.isna(cantidad_origen) or pd.isna(cantidad_componente):
                st.error("La equivalencia está incompleta.")
            elif cantidad_origen == 0:
                st.error("La cantidad origen no puede ser 0.")
            else:
                factor = cantidad_componente / cantidad_origen
                resultado = cantidad_prueba * factor

                st.metric(
                    "Resultado",
                    f"{resultado:.2f} {fila['componente_label']}",
                )

with tab_stock:
    st.info(
        "Cargá la cantidad de cada producto. "
        "Los cambios se guardan en stock.csv."
    )

    stock_actual = cargar_stock()
    map_codigo_a_cantidad = dict(
        zip(stock_actual["codigo"].astype(str), stock_actual["cantidad"])
    )

    stock_base = productos[["codigo", "producto", "unidad_medida"]].copy()
    stock_base["cantidad"] = (
        stock_base["codigo"].map(map_codigo_a_cantidad).fillna(0.0).astype(float)
    )

    if st.session_state.get("resetear_stock"):
        stock_base["cantidad"] = 0.0
        guardar_stock(stock_base)
        st.session_state["resetear_stock"] = False
        st.success("Stock puesto en cero.")

    stock_editado = st.data_editor(
        stock_base,
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
        key="editor_stock",
    )

    col_s1, col_s2, col_s3 = st.columns([1, 1, 3])

    with col_s1:
        guardar_s = st.button(
            "💾 Guardar stock",
            type="primary",
            key="btn_guardar_stock",
        )

    with col_s2:
        cero_s = st.button(
            "🧹 Poner stock a cero",
            key="btn_cero_stock",
        )

    with col_s3:
        st.caption("Los cambios se guardan en stock.csv.")

    if guardar_s:
        salida_s = stock_editado.copy()
        salida_s["cantidad"] = salida_s["cantidad"].fillna(0).astype(float)
        salida_s = salida_s[["codigo", "producto", "unidad_medida", "cantidad"]]
        guardar_stock(salida_s)
        st.success("Stock guardado correctamente.")

    if cero_s:
        st.session_state["resetear_stock"] = True
        st.rerun()

with tab_pedidos:
    st.info(
        "Subí el Excel de pedidos. Se leen las columnas "
        "**Código Producto** y **Cantidad**. "
        "Los pedidos quedan guardados en pedidos.csv y se sobrescriben al subir uno nuevo."
    )

    archivo_pedidos = st.file_uploader(
        "Archivo de pedidos (.xlsx)",
        type=["xlsx", "xls"],
        key="uploader_pedidos",
    )

    pedidos = None
    error_carga = False

    if archivo_pedidos is not None:
        try:
            df_pedidos = pd.read_excel(
                archivo_pedidos,
                header=2,
                dtype={"Código Producto": str},
            )
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
            df_pedidos = None
            error_carga = True

        if df_pedidos is not None:
            columnas_requeridas = ["Código Producto", "Cantidad"]
            faltantes = [c for c in columnas_requeridas if c not in df_pedidos.columns]

            if faltantes:
                st.error(
                    f"Faltan columnas en el archivo: {', '.join(faltantes)}. "
                    f"Columnas encontradas: {', '.join(df_pedidos.columns)}"
                )
                error_carga = True
            else:
                pedidos = df_pedidos[["Código Producto", "Cantidad"]].copy()
                pedidos.columns = ["codigo", "cantidad"]
                pedidos["codigo"] = pedidos["codigo"].astype(str).str.strip()
                pedidos = pedidos.dropna(subset=["codigo", "cantidad"])

                map_codigo_a_producto = dict(
                    zip(productos["codigo"], productos["producto"])
                )
                map_codigo_a_unidad = dict(
                    zip(productos["codigo"], productos["unidad_medida"])
                )

                pedidos["producto"] = pedidos["codigo"].map(map_codigo_a_producto)
                pedidos["unidad_medida"] = pedidos["codigo"].map(map_codigo_a_unidad)
                pedidos = pedidos[["codigo", "producto", "unidad_medida", "cantidad"]]

                guardar_pedidos(pedidos)
                st.success("Pedidos cargados y guardados en pedidos.csv.")

    if pedidos is None and not error_carga:
        pedidos = cargar_pedidos()
        if pedidos is not None and not pedidos.empty:
            st.caption(
                f"📂 Mostrando los últimos pedidos guardados ({PEDIDOS_CSV.name})."
            )

    if pedidos is not None and not pedidos.empty:
        desconocidos = pedidos[pedidos["producto"].isna()]
        if not desconocidos.empty:
            st.warning(
                f"Códigos no encontrados en productos.csv: "
                f"{', '.join(desconocidos['codigo'].unique())}"
            )

        st.subheader("Pedidos cargados")
        st.dataframe(pedidos, use_container_width=True)

        st.caption(
            f"{len(pedidos)} filas · "
            f"{pedidos['producto'].notna().sum()} con producto válido · "
            "los totales y el cruce con stock están en la pestaña 🛒 Total a comprar."
        )

with tab_comprar:
    st.info(
        "Cuánto hay que comprar = pedidos − stock. "
        "Si te sobra (stock > pedido) aparece en **verde**; si te falta, en **rojo**."
    )

    pedidos_actual = cargar_pedidos()
    stock_actual = cargar_stock()

    if pedidos_actual is None or pedidos_actual.empty:
        st.warning(
            "No hay pedidos cargados. Subí un Excel en la pestaña 📋 Pedidos."
        )
    else:
        modo = st.radio(
            "Vista",
            ["Detallada (agrupada por producto)", "Simple (por código)"],
            horizontal=True,
            key="modo_comprar",
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

        ped = pedidos_actual.dropna(subset=["producto", "cantidad"]).copy()
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
            bases = sorted(ped["base"].unique())

            col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns(
                [2, 1.3, 1, 1, 1.5]
            )
            col_h1.caption("**Producto**")
            col_h2.caption("**Unidad**")
            col_h3.caption("**Pedido**")
            col_h4.caption("**Stock**")
            col_h5.caption("**Resultado**")

            for base in bases:
                opciones_grupo = prod_temp[prod_temp["base"] == base]
                if opciones_grupo.empty:
                    continue

                unidades = opciones_grupo["unidad"].tolist()
                idx_default = unidades.index("KG") if "KG" in unidades else 0

                col_t, col_u, col_p, col_s, col_r = st.columns(
                    [2, 1.3, 1, 1, 1.5]
                )

                col_t.markdown(f"**{base}**")
                unidad_destino = col_u.selectbox(
                    "Unidad",
                    unidades,
                    index=idx_default,
                    key=f"unidad_comprar_{base}",
                    label_visibility="collapsed",
                )
                codigo_destino = opciones_grupo[
                    opciones_grupo["unidad"] == unidad_destino
                ].iloc[0]["codigo"]

                total_ped = 0.0
                sin_rel = []
                for _, fila in ped[ped["base"] == base].iterrows():
                    factor = convertir(
                        grafo, str(fila["codigo"]), codigo_destino
                    )
                    if factor is None:
                        sin_rel.append(fila["producto"])
                        continue
                    total_ped += float(fila["cantidad"]) * factor

                total_stk = 0.0
                for _, fila in stk[stk["base"] == base].iterrows():
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

                col_p.markdown(f"{total_ped:,.2f}")
                col_s.markdown(f"{total_stk:,.2f}")

                if diff > 0:
                    col_r.markdown(
                        f"<span style='color:#d11; font-weight:bold;'>"
                        f"Falta {diff:,.2f} {unidad_destino}</span>",
                        unsafe_allow_html=True,
                    )
                elif diff < 0:
                    col_r.markdown(
                        f"<span style='color:#1a8a1a; font-weight:bold;'>"
                        f"Sobra {-diff:,.2f} {unidad_destino}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    col_r.markdown(f"OK ({unidad_destino})")

                if sin_rel:
                    st.caption(
                        f"⚠️ Sin relación cargada para: "
                        f"{', '.join(set(sin_rel))}"
                    )

        else:
            ped_agg = ped.groupby(["codigo"], as_index=False)["cantidad"].sum()
            ped_agg.columns = ["codigo", "pedido"]

            if not stk.empty:
                stk_agg = stk.groupby(["codigo"], as_index=False)["cantidad"].sum()
                stk_agg.columns = ["codigo", "stock"]
            else:
                stk_agg = pd.DataFrame(columns=["codigo", "stock"])

            merged = ped_agg.merge(stk_agg, on="codigo", how="outer")
            merged["pedido"] = merged["pedido"].fillna(0).astype(float)
            merged["stock"] = merged["stock"].fillna(0).astype(float)
            merged["a_comprar"] = merged["pedido"] - merged["stock"]

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
                ["codigo", "producto", "unidad", "pedido", "stock", "a_comprar"]
            ]

            def color_a_comprar(v):
                if pd.isna(v) or v == 0:
                    return ""
                if v > 0:
                    return "color: #d11; font-weight: bold;"
                return "color: #1a8a1a; font-weight: bold;"

            try:
                styled = merged.style.map(color_a_comprar, subset=["a_comprar"])
            except AttributeError:
                styled = merged.style.applymap(
                    color_a_comprar, subset=["a_comprar"]
                )

            styled = styled.format(
                {
                    "pedido": "{:.2f}",
                    "stock": "{:.2f}",
                    "a_comprar": "{:+.2f}",
                }
            )

            st.dataframe(styled, use_container_width=True, hide_index=True)

            st.caption(
                "El valor en **a_comprar** es `pedido − stock`: "
                "positivo (rojo) = falta comprar, negativo (verde) = sobra."
            )


#python -m streamlit run app.py
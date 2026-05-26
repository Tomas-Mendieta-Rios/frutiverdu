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

EXCEPCIONES = {
    ("061", "062"),
}

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
    df = pd.read_csv(PEDIDOS_CSV, dtype={"codigo": str})
    if "estimado" not in df.columns:
        df["estimado"] = 0.0
    return df


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
        "Subí el Excel de pedidos o editá los valores a mano. "
        "**Estimado** = cuánto querés comprar de más previendo ventas. "
        "Los datos se guardan en pedidos.csv."
    )

    archivo_pedidos = st.file_uploader(
        "Archivo de pedidos (.xlsx)",
        type=["xlsx", "xls"],
        key="uploader_pedidos",
    )

    if archivo_pedidos is not None:
        file_id = (archivo_pedidos.name, archivo_pedidos.size)
        if st.session_state.get("ultimo_upload_pedidos") != file_id:
            try:
                df_excel = pd.read_excel(
                    archivo_pedidos,
                    header=2,
                    dtype={"Código Producto": str},
                )
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")
                df_excel = None

            if df_excel is not None:
                columnas_requeridas = ["Código Producto", "Cantidad"]
                faltantes = [
                    c for c in columnas_requeridas if c not in df_excel.columns
                ]
                if faltantes:
                    st.error(
                        f"Faltan columnas: {', '.join(faltantes)}. "
                        f"Encontradas: {', '.join(df_excel.columns)}"
                    )
                else:
                    df_parsed = df_excel[["Código Producto", "Cantidad"]].copy()
                    df_parsed.columns = ["codigo", "cantidad"]
                    df_parsed["codigo"] = df_parsed["codigo"].astype(str).str.strip()
                    df_parsed = df_parsed.dropna(subset=["codigo", "cantidad"])
                    df_parsed = df_parsed.groupby("codigo", as_index=False)[
                        "cantidad"
                    ].sum()

                    map_cant_excel = dict(
                        zip(df_parsed["codigo"], df_parsed["cantidad"])
                    )

                    pedidos_prev = cargar_pedidos()
                    map_est = {}
                    if pedidos_prev is not None and "estimado" in pedidos_prev.columns:
                        map_est = dict(
                            zip(
                                pedidos_prev["codigo"].astype(str),
                                pedidos_prev["estimado"].fillna(0),
                            )
                        )

                    full = productos[
                        ["codigo", "producto", "unidad_medida"]
                    ].copy()
                    full["cantidad"] = (
                        full["codigo"]
                        .astype(str)
                        .map(map_cant_excel)
                        .fillna(0)
                        .astype(float)
                    )
                    full["estimado"] = (
                        full["codigo"]
                        .astype(str)
                        .map(map_est)
                        .fillna(0)
                        .astype(float)
                    )

                    guardar_pedidos(full)
                    st.session_state["ultimo_upload_pedidos"] = file_id

                    codigos_excel = set(df_parsed["codigo"])
                    codigos_prod = set(productos["codigo"].astype(str))
                    desconocidos = codigos_excel - codigos_prod
                    st.success(
                        f"✅ Excel procesado. "
                        f"{(full['cantidad'] > 0).sum()} productos con pedido."
                    )
                    if desconocidos:
                        st.warning(
                            f"Códigos del Excel que no están en productos.csv "
                            f"(se ignoraron): {', '.join(sorted(desconocidos))}"
                        )

    pedidos_full = cargar_pedidos()
    if pedidos_full is None or pedidos_full.empty:
        pedidos_full = productos[["codigo", "producto", "unidad_medida"]].copy()
        pedidos_full["cantidad"] = 0.0
        pedidos_full["estimado"] = 0.0
    else:
        if "estimado" not in pedidos_full.columns:
            pedidos_full["estimado"] = 0.0
        existentes = set(pedidos_full["codigo"].astype(str))
        nuevos = productos[
            ~productos["codigo"].astype(str).isin(existentes)
        ].copy()
        if not nuevos.empty:
            nuevos = nuevos[["codigo", "producto", "unidad_medida"]]
            nuevos["cantidad"] = 0.0
            nuevos["estimado"] = 0.0
            pedidos_full = pd.concat([pedidos_full, nuevos], ignore_index=True)

    pedidos_full["cantidad"] = pedidos_full["cantidad"].fillna(0).astype(float)
    pedidos_full["estimado"] = pedidos_full["estimado"].fillna(0).astype(float)
    pedidos_full = pedidos_full[
        ["codigo", "producto", "unidad_medida", "cantidad", "estimado"]
    ].sort_values("producto").reset_index(drop=True)

    col_f1, col_f2 = st.columns([2, 4])
    with col_f1:
        solo_pedidos = st.checkbox(
            "Mostrar solo productos pedidos",
            value=False,
            help="Oculta filas con pedido = 0 y estimado = 0",
        )
    with col_f2:
        st.caption(
            f"{(pedidos_full['cantidad'] > 0).sum()} con pedido · "
            f"{(pedidos_full['estimado'] > 0).sum()} con estimado · "
            f"{len(pedidos_full)} productos totales"
        )

    if solo_pedidos:
        pedidos_view = pedidos_full[
            (pedidos_full["cantidad"] > 0) | (pedidos_full["estimado"] > 0)
        ].copy()
    else:
        pedidos_view = pedidos_full.copy()

    if pedidos_view.empty:
        st.warning("No hay productos con pedido o estimado para mostrar.")
    else:
        pedidos_editado = st.data_editor(
            pedidos_view,
            use_container_width=True,
            num_rows="fixed",
            disabled=["codigo", "producto", "unidad_medida"],
            column_config={
                "codigo": st.column_config.TextColumn("Código"),
                "producto": st.column_config.TextColumn("Producto"),
                "unidad_medida": st.column_config.TextColumn("Unidad"),
                "cantidad": st.column_config.NumberColumn(
                    "Pedido",
                    min_value=0.0,
                    step=1.0,
                    format="%.3f",
                ),
                "estimado": st.column_config.NumberColumn(
                    "Estimado (extra)",
                    min_value=0.0,
                    step=1.0,
                    format="%.3f",
                ),
            },
            key="editor_pedidos",
        )

        col_g1, col_g2 = st.columns([1, 4])
        with col_g1:
            guardar_ped = st.button(
                "💾 Guardar pedidos",
                type="primary",
                key="btn_guardar_pedidos",
            )
        with col_g2:
            st.caption("Los cambios se guardan en pedidos.csv.")

        if guardar_ped:
            edit_cant = dict(
                zip(
                    pedidos_editado["codigo"].astype(str),
                    pedidos_editado["cantidad"].fillna(0).astype(float),
                )
            )
            edit_est = dict(
                zip(
                    pedidos_editado["codigo"].astype(str),
                    pedidos_editado["estimado"].fillna(0).astype(float),
                )
            )
            pedidos_full["cantidad"] = pedidos_full.apply(
                lambda r: edit_cant.get(str(r["codigo"]), r["cantidad"]),
                axis=1,
            )
            pedidos_full["estimado"] = pedidos_full.apply(
                lambda r: edit_est.get(str(r["codigo"]), r["estimado"]),
                axis=1,
            )
            guardar_pedidos(pedidos_full)
            st.success("Pedidos guardados.")

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


#python -m streamlit run app.py
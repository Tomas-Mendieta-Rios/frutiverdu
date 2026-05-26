import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Frutiverdu - Compuestos", layout="wide")

PRODUCTOS_CSV = Path("productos.csv")

COMPUESTOS_CSV = Path("compuestos.csv")
if not COMPUESTOS_CSV.exists():
    COMPUESTOS_CSV = Path("compuestos")

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


productos = cargar_productos()
compuestos = cargar_compuestos()

productos["label"] = productos["codigo"] + " - " + productos["producto"]

opciones = productos["label"].tolist()

map_label_a_producto = dict(zip(productos["label"], productos["producto"]))
map_label_a_codigo = dict(zip(productos["label"], productos["codigo"]))

st.info(
    "Editá las equivalencias. Ejemplo: "
    "1 REPOLLO ROJO - CAJA = 15 REPOLLO ROJO - KG."
)

st.subheader("⚙️ Tabla editable")

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
    num_rows="dynamic",
    column_config={
        "origen_label": st.column_config.SelectboxColumn(
            "Producto origen",
            options=opciones,
            required=True,
        ),
        "cantidad_origen": st.column_config.NumberColumn(
            "Cantidad origen",
            min_value=0.0,
            step=1.0,
            format="%.3f",
            required=True,
        ),
        "componente_label": st.column_config.SelectboxColumn(
            "Producto componente/base",
            options=opciones,
            required=True,
        ),
        "cantidad_componente": st.column_config.NumberColumn(
            "Cantidad componente/base",
            min_value=0.0,
            step=0.5,
            format="%.3f",
            required=True,
        ),
    },
)

col1, col2 = st.columns([1, 4])

with col1:
    guardar = st.button("💾 Guardar cambios", type="primary")

with col2:
    st.caption("Los cambios se guardan en compuestos.csv o compuestos.")

if guardar:
    salida = tabla_editada.copy()

    salida = salida.dropna(
        subset=[
            "origen_label",
            "cantidad_origen",
            "componente_label",
            "cantidad_componente",
        ]
    )

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

st.divider()

st.subheader("🧪 Probar conversión")

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
import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Frutiverdu", layout="wide")

st.title("🍎 Frutiverdu - Conversiones de Productos")

ARCHIVO_CONVERSIONES = Path("conversiones.csv")

PRODUCTOS = [
    {"codigo": "0219", "producto": "REPOLLO ROJO - CAJA", "unidad_medida": "CAJA"},
    {"codigo": "0220", "producto": "REPOLLO ROJO - KG", "unidad_medida": "KG"},
    {"codigo": "0221", "producto": "REPOLLO ROJO - UNIDAD", "unidad_medida": "UNIDAD"},
]


def crear_conversiones_iniciales():
    return pd.DataFrame([
        {
            "codigo_origen": "0219",
            "producto_origen": "REPOLLO ROJO - CAJA",
            "cantidad_origen": 1.0,
            "codigo_destino": "0220",
            "producto_destino": "REPOLLO ROJO - KG",
            "cantidad_destino": 15.0,
        },
        {
            "codigo_origen": "0221",
            "producto_origen": "REPOLLO ROJO - UNIDAD",
            "cantidad_origen": 1.0,
            "codigo_destino": "0220",
            "producto_destino": "REPOLLO ROJO - KG",
            "cantidad_destino": 2.0,
        },
        {
            "codigo_origen": "0220",
            "producto_origen": "REPOLLO ROJO - KG",
            "cantidad_origen": 1.0,
            "codigo_destino": "0220",
            "producto_destino": "REPOLLO ROJO - KG",
            "cantidad_destino": 1.0,
        },
    ])


def cargar_conversiones():
    if ARCHIVO_CONVERSIONES.exists():
        return pd.read_csv(
            ARCHIVO_CONVERSIONES,
            dtype={
                "codigo_origen": str,
                "codigo_destino": str,
            },
        )

    return crear_conversiones_iniciales()


def guardar_conversiones(df):
    df.to_csv(ARCHIVO_CONVERSIONES, index=False)


conversiones = cargar_conversiones()

st.info(
    "Acá definís cómo se convierte cada producto. "
    "Ejemplo: 1 REPOLLO ROJO - CAJA equivale a 15 REPOLLO ROJO - KG."
)

st.subheader("⚙️ Tabla editable de conversiones")

conversiones_editadas = st.data_editor(
    conversiones,
    use_container_width=True,
    num_rows="dynamic",
    column_config={
        "codigo_origen": st.column_config.TextColumn("Código origen"),
        "producto_origen": st.column_config.SelectboxColumn(
            "Producto origen",
            options=[p["producto"] for p in PRODUCTOS],
        ),
        "cantidad_origen": st.column_config.NumberColumn(
            "Cantidad origen",
            min_value=0.0,
            step=1.0,
            format="%.3f",
        ),
        "codigo_destino": st.column_config.TextColumn("Código destino"),
        "producto_destino": st.column_config.SelectboxColumn(
            "Producto destino/base",
            options=[p["producto"] for p in PRODUCTOS],
        ),
        "cantidad_destino": st.column_config.NumberColumn(
            "Cantidad destino/base",
            min_value=0.0,
            step=0.5,
            format="%.3f",
        ),
    },
)

if st.button("💾 Guardar conversiones"):
    guardar_conversiones(conversiones_editadas)
    st.success("Conversiones guardadas.")

st.divider()

st.subheader("🧪 Probar conversión")

producto = st.selectbox(
    "Producto a convertir",
    conversiones_editadas["producto_origen"].unique(),
)

cantidad = st.number_input(
    "Cantidad",
    min_value=0.0,
    value=1.0,
    step=1.0,
)

fila = conversiones_editadas[
    conversiones_editadas["producto_origen"] == producto
].iloc[0]

factor = fila["cantidad_destino"] / fila["cantidad_origen"]

resultado = cantidad * factor

st.metric(
    "Resultado",
    f"{resultado:.2f} {fila['producto_destino']}"
)
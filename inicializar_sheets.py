"""Sube los datos locales al Google Sheet.

Correr una sola vez al hacer el setup inicial:

    python inicializar_sheets.py

Lee:
  - productos.csv          → hoja `productos`
  - compuestos.csv         → hoja `compuestos`
  - stock.csv              → hoja `stock_historico`
  - estimado.csv           → hoja `estimado_historico`
  - wix_productos.csv      → hoja `wix_productos`
  - mapping_wix_dux.csv    → hoja `mapping_wix_dux`
  - packs_wix.csv          → hoja `packs_wix`
  - pedidos_dux.json       → extrae `selecciones` → hoja `selecciones_dux`
  - wix_pedidos.json       → extrae `selecciones` → hoja `selecciones_wix`
"""

import json
import tomllib
from pathlib import Path

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCHEMA = {
    "productos": ["codigo", "producto", "unidad_medida", "descripcion"],
    "compuestos": [
        "codigo_origen",
        "producto_origen",
        "cantidad_origen",
        "codigo_componente",
        "producto_componente",
        "cantidad_componente",
    ],
    "stock_historico": ["fecha", "codigo", "producto", "unidad_medida", "cantidad"],
    "estimado_historico": [
        "fecha",
        "codigo",
        "producto",
        "unidad_medida",
        "estimado",
    ],
    "wix_productos": ["wix_id", "producto", "descripcion"],
    "mapping_wix_dux": [
        "wix_id",
        "wix_producto",
        "dux_codigo",
        "dux_producto",
        "factor",
    ],
    "packs_wix": [
        "wix_id_pack",
        "pack_nombre",
        "dux_codigo",
        "dux_producto",
        "cantidad",
    ],
    "selecciones_dux": ["order_id", "fecha_entrega"],
    "selecciones_wix": ["order_id", "fecha_entrega"],
}


def conectar():
    with open(".streamlit/secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    creds = Credentials.from_service_account_info(
        secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(secrets["gsheets"]["spreadsheet_id"])


def get_or_create_ws(sheet, nombre):
    try:
        return sheet.worksheet(nombre)
    except gspread.WorksheetNotFound:
        return sheet.add_worksheet(title=nombre, rows=1000, cols=20)


def escribir(ws, df, columnas):
    df = df.copy()
    for c in columnas:
        if c not in df.columns:
            df[c] = ""
    df = df[columnas]
    # Convertir TODO a string para preservar ceros a la izquierda
    df = df.astype(str).replace({"nan": "", "None": ""})
    ws.clear()
    ws.update(
        values=[columnas] + df.values.tolist(),
        range_name="A1",
        value_input_option="RAW",
    )


def subir_csv(sheet, archivo, hoja, dtype=None):
    p = Path(archivo)
    if not p.exists():
        print(f"  (no existe {archivo}, omitido)")
        return 0
    # Forzar TODAS las columnas como string para preservar ceros a la izquierda
    df = pd.read_csv(p, dtype=str)
    df = df.fillna("")
    ws = get_or_create_ws(sheet, hoja)
    escribir(ws, df, SCHEMA[hoja])
    print(f"  ✅ {hoja}: {len(df)} filas")
    return len(df)


def subir_selecciones(sheet, archivo_json, hoja):
    p = Path(archivo_json)
    if not p.exists():
        print(f"  (no existe {archivo_json}, omitido)")
        return 0
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠️ no se pudo leer {archivo_json}: {e}")
        return 0
    sel = data.get("selecciones", {}) or {}
    if not sel:
        print(f"  ({hoja}: sin selecciones para subir)")
        # igual escribimos hoja vacia con header
        ws = get_or_create_ws(sheet, hoja)
        escribir(ws, pd.DataFrame(columns=SCHEMA[hoja]), SCHEMA[hoja])
        return 0
    rows = [
        {"order_id": str(oid), "fecha_entrega": str(fent)}
        for oid, fent in sel.items()
        if fent
    ]
    df = pd.DataFrame(rows, columns=SCHEMA[hoja])
    ws = get_or_create_ws(sheet, hoja)
    escribir(ws, df, SCHEMA[hoja])
    print(f"  ✅ {hoja}: {len(df)} selecciones")
    return len(df)


def main():
    print("Conectando al Sheet...")
    sheet = conectar()
    print(f"Sheet: {sheet.title}\n")

    print("📦 Subiendo CSVs...")
    subir_csv(sheet, "productos.csv", "productos", {"codigo": str})
    subir_csv(
        sheet,
        "compuestos.csv",
        "compuestos",
        {"codigo_origen": str, "codigo_componente": str},
    )
    subir_csv(sheet, "stock.csv", "stock_historico", {"codigo": str})
    subir_csv(sheet, "estimado.csv", "estimado_historico", {"codigo": str})
    subir_csv(sheet, "wix_productos.csv", "wix_productos")
    subir_csv(sheet, "mapping_wix_dux.csv", "mapping_wix_dux")
    subir_csv(
        sheet,
        "packs_wix.csv",
        "packs_wix",
        {"dux_codigo": str, "wix_id_pack": str},
    )

    print("\n📋 Subiendo selecciones desde JSONs...")
    subir_selecciones(sheet, "pedidos_dux.json", "selecciones_dux")
    subir_selecciones(sheet, "wix_pedidos.json", "selecciones_wix")

    print("\n✅ Listo. Datos iniciales subidos al Sheet.")


if __name__ == "__main__":
    main()

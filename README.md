# Frutiverdu

App de gestión de stock, pedidos y compras para frutería/verdulería.

## Pestañas

- **⚙️ Editar valores** — cantidades de las equivalencias entre unidades (CAJA, KG, UNIDAD, ATADO, etc.)
- **🧪 Probar conversión** — muestra todas las equivalencias de un producto
- **📦 Stock** — carga de stock por producto
- **📋 Pedidos** — sube un Excel con códigos y cantidades, o edita a mano. Incluye columna **Estimado** (compra extra previendo ventas)
- **🛒 Total a comprar** — pedido − stock, agrupado por producto, con conversión a la unidad elegida y columna que considera el estimado

## Correr local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy en Streamlit Community Cloud

1. Pushear este repo a GitHub (público o privado).
2. Entrar a https://share.streamlit.io y conectar la cuenta de GitHub.
3. "New app" → elegir el repo, branch (`main`) y file path (`app.py`).
4. Click "Deploy".

### Aviso sobre persistencia

Streamlit Cloud usa filesystem efímero: cualquier cambio que la app escriba a
`stock.csv`, `pedidos.csv` o `compuestos.csv` **no sobrevive a un reinicio**
del contenedor. Para persistencia real conviene migrar esos CSVs a una DB
externa (Supabase, Postgres, etc.).

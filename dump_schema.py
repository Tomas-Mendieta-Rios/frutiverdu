"""
Genera schema.md con tablas, columnas y relaciones de Supabase.

Requiere que exista la funcion get_schema_info() en Supabase (ver README o comentario abajo).
Uso: python dump_schema.py
"""
import os
import tomllib
from datetime import datetime
from supabase import create_client

_secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
with open(_secrets_path, "rb") as f:
    _secrets = tomllib.load(f)

_cfg = _secrets.get("supabase", {})
client = create_client(_cfg["url"], _cfg["key"])

print("Conectando a Supabase...")
data = client.rpc("get_schema_info").execute().data

tables_raw = data.get("tables") or []
fks_raw    = data.get("fks") or []

# Agrupar columnas por tabla
tables = {}
for col in tables_raw:
    tables.setdefault(col["table"], []).append(col)

# Agrupar FKs por tabla
fks = {}
for fk in (fks_raw or []):
    fks.setdefault(fk["tabla"], []).append(fk)

out = []
out.append("# Schema — frutiverdu (Supabase)")
out.append(f"_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")

for table_name in sorted(tables.keys()):
    out.append(f"## `{table_name}`")
    out.append("| Columna | Tipo | Nullable |")
    out.append("|---------|------|----------|")
    for col in tables[table_name]:
        nullable = "✓" if col["nullable"] == "YES" else ""
        out.append(f"| `{col['column']}` | {col['type']} | {nullable} |")

    if table_name in fks:
        out.append("")
        out.append("**FK:**")
        for fk in fks[table_name]:
            out.append(f"- `{fk['columna']}` → `{fk['ref_tabla']}.{fk['ref_columna']}`")
    out.append("")

output_path = os.path.join(os.path.dirname(__file__), "schema.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))

print(f"✅ schema.md generado — {len(tables)} tablas, {len(fks_raw or [])} FK relaciones")

# Schema — frutiverdu (Supabase)

_Generado: 2026-07-18_

---

## Notas importantes

- `cobros_imputaciones` tiene DOS campos para imputaciones: `id_comp_venta` (FK a `facturas`) **y** `id_nota_credito_debito_venta` (FK a notas de crédito/débito). Cuando un cobro se aplica a una NC, `id_comp_venta` es NULL y `id_nota_credito_debito_venta` está poblado. Esto explica por qué las facturas cubiertas por NC muestran `cobrado = 0`.
- `pagos_proveedores_imputaciones` tiene de forma análoga el campo `id_nota_credito_debito_compra`.

---

## `cajas`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | integer | NO |
| nombre | text | NO |
| activa | boolean | YES |
| created_at | timestamp with time zone | YES |

---

## `cajas_ajustes`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| caja_id | integer | YES |
| fecha | date | NO |
| monto | numeric | YES |
| nota | text | YES |
| tipo | text | NO |
| afecta_balance | boolean | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `caja_id` → `cajas.id`

---

## `categorias_planilla`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| orden | integer | NO |

---

## `cobros`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| id_empresa | integer | YES |
| id_sucursal | integer | YES |
| fecha | text | YES |
| nro_comprobante | text | YES |
| tipo_comprobante | text | YES |
| monto | numeric | YES |
| moneda | text | YES |
| observaciones | text | YES |
| id_cliente | bigint | YES |
| cliente | text | YES |
| nombre_cliente | text | YES |
| tipo_doc | text | YES |
| nro_doc | text | YES |
| id_personal | bigint | YES |
| personal | text | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |

---

## `cobros_cobranza`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| cobro_id | bigint | YES |
| tipo_valor | text | YES |
| descripcion | text | YES |
| referencia | text | YES |
| monto | numeric | YES |
| id_tarjeta | bigint | YES |
| id_plan_tarjeta | bigint | YES |
| id_terminal | bigint | YES |
| nro_cupon | text | YES |
| nro_lote | text | YES |

**FK:**
- `cobro_id` → `cobros.id`

---

## `cobros_imputaciones`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| cobro_id | bigint | YES |
| id_comp_venta | bigint | YES |
| id_nota_credito_debito_venta | bigint | YES |
| tipo_comp | text | YES |
| nro_comprobante | text | YES |
| monto_imputado | numeric | YES |

**FK:**
- `cobro_id` → `cobros.id`
- `id_comp_venta` → `facturas.factura_id` _(NULL cuando la imputación es contra una NC)_
- `id_nota_credito_debito_venta` → notas de crédito/débito venta _(NULL cuando la imputación es contra una factura)_

---

## `comprobantes_compra`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| id_empresa | integer | YES |
| id_sucursal | integer | YES |
| id_proveedor | bigint | YES |
| cuit | text | YES |
| proveedor | text | YES |
| nro_comprobante | text | YES |
| tipo_comprobante | text | YES |
| condicion_pago | text | YES |
| estado | text | YES |
| fecha | text | YES |
| fecha_vencimiento | text | YES |
| monto_exento | numeric | YES |
| monto_gravado | numeric | YES |
| monto_iva | numeric | YES |
| monto_desc | numeric | YES |
| total | numeric | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |
| json | jsonb | YES |
| pago_pendiente | boolean | YES |
| forma_pago | text | YES |
| provincia | text | YES |
| estado_recepcion | text | YES |
| fecha_imputacion_contable | text | YES |
| monto_pendiente | numeric | YES |
| monto_percepciones | numeric | YES |

---

## `facturas`

| Columna | Tipo | Nullable |
|---------|------|----------|
| factura_id | text | NO |
| tipo_comp | text | YES |
| letra_comp | text | YES |
| nro_comp | text | YES |
| nro_pto_vta | text | YES |
| fecha_comp | text | YES |
| apellido_razon_soc | text | YES |
| nombre | text | YES |
| cuit | text | YES |
| nro_pedido | text | YES |
| monto_exento | numeric | YES |
| monto_gravado | numeric | YES |
| monto_iva | numeric | YES |
| monto_desc | numeric | YES |
| total | numeric | YES |
| anulada | text | YES |
| nro_cae_cai | text | YES |
| url_factura | text | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |
| con_cobro | boolean | YES |

---

## `items_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| rubro_id | bigint | YES |
| subrubro_id | integer | YES |

**FK:**
- `rubro_id` → `rubros_egresos.id`
- `subrubro_id` → `subrubros_egresos.id`

---

## `otros_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| fecha | date | NO |
| rubro_id | bigint | YES |
| subrubro_id | bigint | YES |
| item | text | YES |
| monto | numeric | NO |
| caja_id | bigint | YES |
| descripcion | text | YES |
| estado | text | NO |
| fecha_movimiento | date | YES |
| usuario | text | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `rubro_id` → `rubros_egresos.id`
- `subrubro_id` → `subrubros_egresos.id`
- `caja_id` → `cajas.id`

---

## `otros_ingresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| fecha | date | NO |
| rubro_id | bigint | YES |
| subrubro_id | bigint | YES |
| monto | numeric | NO |
| caja_id | bigint | YES |
| descripcion | text | YES |
| usuario | text | YES |
| created_at | timestamp with time zone | YES |
| fecha_movimiento | date | YES |
| estado | text | NO |

**FK:**
- `rubro_id` → `rubros_ingresos.id`
- `subrubro_id` → `subrubros_ingresos.id`

---

## `pagos_proveedores_imputaciones`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id_nota_credito_debito_compra | bigint | YES |

**FK:**
- `pago_id` → `pagos_proveedores.id`
- `id_nota_credito_debito_compra` → notas de crédito/débito compra _(NULL cuando la imputación es contra un comprobante directo)_

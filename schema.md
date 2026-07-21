# Schema — frutiverdu (Supabase)

_Generado: 2026-07-21_

---

## Notas importantes

- `cobros_imputaciones` tiene DOS campos para imputaciones: `id_comp_venta` (FK a `facturas`) **y** `id_nota_credito_debito_venta` (FK a notas de crédito/débito). Cuando un cobro se aplica a una NC, `id_comp_venta` es NULL y `id_nota_credito_debito_venta` está poblado.
- `pagos_proveedores_imputaciones` tiene de forma análoga el campo `id_nota_credito_debito_compra`.
- `items_egresos` e `items_ingresos` son permanentes — no se borran, solo se anulan con `activo = false`. Cada item pertenece a un solo subrubro.
- `otros_egresos` y `otros_ingresos` referencian el item por `item_id` (FK), preservando el historial aunque el item se anule.
- `items_egresos_subrubros` e `items_ingresos_subrubros` existen en la DB como tablas legacy pero ya no se usan en la app.

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
| tipo | text | NO (default 'ajuste') |
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
| orden | integer | NO (default 0) |

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
| estado | text | YES (default 'EMITIDA') |
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

## `compuestos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| codigo_origen | text | YES |
| producto_origen | text | YES |
| cantidad_origen | text | YES |
| codigo_componente | text | YES |
| producto_componente | text | YES |
| cantidad_componente | text | YES |
| created_at | timestamp with time zone | YES |

---

## `config`

| Columna | Tipo | Nullable |
|---------|------|----------|
| key | text | NO |
| value | text | YES |
| created_at | timestamp with time zone | YES |

---

## `estimado_historico`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| fecha | text | YES |
| codigo | text | YES |
| producto | text | YES |
| unidad_medida | text | YES |
| estimado | text | YES |
| created_at | timestamp with time zone | YES |

---

## `estimado_semanal`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| dia_semana | text | YES |
| codigo | text | YES |
| producto | text | YES |

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

## `facturas_items`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| factura_id | text | YES |
| cod_item | text | YES |
| item | text | YES |
| ctd | numeric | YES |
| precio_uni | numeric | YES |
| porc_desc | numeric | YES |
| porc_iva | numeric | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `factura_id` → `facturas.factura_id`

---

## `fechas_pago_wix`

| Columna | Tipo | Nullable |
|---------|------|----------|
| order_id | text | NO |
| fecha_pago | text | YES |

---

## `gastos`

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
| gasto | text | YES |
| estado | text | YES |
| fecha | text | YES |
| fecha_vencimiento | text | YES |
| pago_pendiente | boolean | YES |
| monto_exento | numeric | YES |
| monto_gravado | numeric | YES |
| monto_iva | numeric | YES |
| monto_desc | numeric | YES |
| total | numeric | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |
| id_rubro | bigint | YES |
| rubro_nombre | text | YES |
| id_sub_rubro | bigint | YES |
| sub_rubro_nombre | text | YES |
| observaciones | text | YES |
| condicion_pago | text | YES |
| monto_pendiente | numeric | YES |

---

## `gastos_catalogo`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| cod_producto | text | YES |
| gasto | text | NO |
| rubro | text | YES |
| sub_rubro | text | YES |
| proveedor | text | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |

---

## `gastos_items`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| gasto_id | bigint | YES |
| cod_item | text | YES |
| item | text | YES |
| ctd | numeric | YES |
| precio_uni | numeric | YES |
| porc_desc | numeric | YES |
| porc_iva | numeric | YES |
| comentarios | text | YES |
| created_at | timestamp with time zone | YES |
| monto_total | numeric | YES |

**FK:**
- `gasto_id` → `gastos.id`

---

## `items_compra`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| comprobante_id | bigint | YES |
| cod_item | text | YES |
| item | text | YES |
| ctd | numeric | YES |
| precio_uni | numeric | YES |
| porc_desc | numeric | YES |
| porc_iva | numeric | YES |
| created_at | timestamp with time zone | YES |
| json | jsonb | YES |

**FK:**
- `comprobante_id` → `comprobantes_compra.id`

---

## `items_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| subrubro_id | bigint | YES |
| activo | boolean | YES (default true) |

**FK:**
- `subrubro_id` → `subrubros_egresos.id`

**Constraints:**
- `UNIQUE (nombre, subrubro_id)`

**Notas:**
- Items son permanentes: no se borran, se anulan con `activo = false`
- Un item pertenece a un solo subrubro (one-to-many, no many-to-many)
- `items_egresos_subrubros` (junction table) existe en DB pero ya no se usa en la app

---

## `items_egresos_subrubros` _(legacy — no usar)_

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| item_id | bigint | NO |
| subrubro_id | integer | NO |

**FK:**
- `item_id` → `items_egresos.id`
- `subrubro_id` → `subrubros_egresos.id`

---

## `items_ingresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| subrubro_id | bigint | YES |
| activo | boolean | YES (default true) |

**FK:**
- `subrubro_id` → `subrubros_ingresos.id`

**Constraints:**
- `UNIQUE (nombre, subrubro_id)`

**Notas:**
- Items son permanentes: no se borran, se anulan con `activo = false`
- Un item pertenece a un solo subrubro (one-to-many, no many-to-many)
- `items_ingresos_subrubros` (junction table) existe en DB pero ya no se usa en la app

---

## `items_ingresos_subrubros` _(legacy — no usar)_

| Columna | Tipo | Nullable |
|---------|------|----------|
| item_id | bigint | NO |
| subrubro_id | bigint | NO |

**FK:**
- `item_id` → `items_ingresos.id`
- `subrubro_id` → `subrubros_ingresos.id`

---

## `otros_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| fecha | date | NO |
| rubro_id | bigint | YES |
| subrubro_id | bigint | YES |
| item_id | bigint | YES |
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
- `item_id` → `items_egresos.id`
- `caja_id` → `cajas.id`

---

## `otros_ingresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| fecha | date | NO |
| rubro_id | bigint | YES |
| subrubro_id | bigint | YES |
| item_id | bigint | YES |
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
- `item_id` → `items_ingresos.id`

---

## `pagos_proveedores`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| id_empresa | integer | YES |
| id_sucursal | integer | YES |
| id_proveedor | bigint | YES |
| proveedor | text | YES |
| cuit | text | YES |
| nro_comprobante | text | YES |
| tipo_comprobante | text | YES |
| fecha | text | YES |
| monto | numeric | YES |
| moneda | text | YES |
| observaciones | text | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |

---

## `pagos_proveedores_imputaciones`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| pago_id | bigint | YES |
| id_comp_compra | bigint | YES |
| id_nota_credito_debito_compra | bigint | YES |
| tipo_comp | text | YES |
| nro_comprobante | text | YES |
| monto_imputado | numeric | YES |

**FK:**
- `pago_id` → `pagos_proveedores.id`
- `id_nota_credito_debito_compra` → notas de crédito/débito compra _(NULL cuando la imputación es contra un comprobante directo)_

---

## `pagos_proveedores_lineas`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| pago_id | bigint | YES |
| tipo_valor | text | YES |
| descripcion | text | YES |
| referencia | text | YES |
| monto | numeric | YES |

**FK:**
- `pago_id` → `pagos_proveedores.id`

---

## `pedidos_dux`

| Columna | Tipo | Nullable |
|---------|------|----------|
| order_id | bigint | NO |
| id_empresa | integer | YES |
| id_sucursal | integer | YES |
| fecha | text | YES |
| estado | text | YES |
| cliente | text | YES |
| total | numeric | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |

---

## `pedidos_dux_items`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| order_id | bigint | YES |
| cod_item | text | YES |
| item | text | YES |
| ctd | numeric | YES |
| precio_uni | numeric | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `order_id` → `pedidos_dux.order_id`

---

## `pedidos_wix`

| Columna | Tipo | Nullable |
|---------|------|----------|
| order_id | text | NO |
| numero | integer | YES |
| fecha | text | YES |
| estado | text | YES |
| estado_pago | text | YES |
| cliente | text | YES |
| email | text | YES |
| total | numeric | YES |
| subtotal | numeric | YES |
| descuento | numeric | YES |
| envio | numeric | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |
| caja_id | bigint | YES |
| fecha_pago | text | YES |
| fecha_fulfillment | text | YES |
| total_amount | numeric | YES |

**FK:**
- `caja_id` → `cajas.id`

---

## `pedidos_wix_items`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| order_id | text | YES |
| cod_item | text | YES |
| item | text | YES |
| ctd | numeric | YES |
| precio_uni | numeric | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `order_id` → `pedidos_wix.order_id`

---

## `rubros_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |

---

## `rubros_ingresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |

---

## `subrubros_egresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| rubro_id | bigint | YES |

**FK:**
- `rubro_id` → `rubros_egresos.id`

---

## `subrubros_ingresos`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| nombre | text | NO |
| rubro_id | bigint | YES |

**FK:**
- `rubro_id` → `rubros_ingresos.id`

---

## `transferencias_cajas`

| Columna | Tipo | Nullable |
|---------|------|----------|
| id | bigint | NO |
| origen_id | bigint | YES |
| destino_id | bigint | YES |
| monto | numeric | NO |
| fecha | date | NO |
| descripcion | text | YES |
| created_at | timestamp with time zone | YES |

**FK:**
- `origen_id` → `cajas.id`
- `destino_id` → `cajas.id`

-- Funciones atómicas para reemplazar tablas de referencia.
-- Cada función ejecuta DELETE + INSERT en una sola transacción PostgreSQL,
-- eliminando la ventana de tabla vacía del patrón delete-then-insert en Python.

CREATE OR REPLACE FUNCTION replace_productos(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM productos;
  INSERT INTO productos (codigo, producto, unidad_medida, descripcion, rubro)
  SELECT codigo, producto, unidad_medida, descripcion, rubro
  FROM jsonb_to_recordset(rows) AS x(
    codigo text, producto text, unidad_medida text, descripcion text, rubro text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_rubros(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM rubros;
  INSERT INTO rubros (id, nombre)
  SELECT id, nombre
  FROM jsonb_to_recordset(rows) AS x(id bigint, nombre text);
END;
$$;

CREATE OR REPLACE FUNCTION replace_subrubros(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM subrubros;
  INSERT INTO subrubros (id, nombre, rubro_id, rubro_nombre)
  SELECT id, nombre, rubro_id, rubro_nombre
  FROM jsonb_to_recordset(rows) AS x(
    id bigint, nombre text, rubro_id bigint, rubro_nombre text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_gastos_catalogo(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM gastos_catalogo;
  INSERT INTO gastos_catalogo (cod_producto, gasto, rubro, sub_rubro, proveedor)
  SELECT cod_producto, gasto, rubro, sub_rubro, proveedor
  FROM jsonb_to_recordset(rows) AS x(
    cod_producto text, gasto text, rubro text, sub_rubro text, proveedor text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_compuestos(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM compuestos;
  INSERT INTO compuestos (codigo_origen, producto_origen, cantidad_origen, codigo_componente, producto_componente, cantidad_componente)
  SELECT codigo_origen, producto_origen, cantidad_origen, codigo_componente, producto_componente, cantidad_componente
  FROM jsonb_to_recordset(rows) AS x(
    codigo_origen text, producto_origen text, cantidad_origen text,
    codigo_componente text, producto_componente text, cantidad_componente text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_wix_productos(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM wix_productos;
  INSERT INTO wix_productos (wix_id, producto, descripcion)
  SELECT wix_id, producto, descripcion
  FROM jsonb_to_recordset(rows) AS x(wix_id text, producto text, descripcion text);
END;
$$;

CREATE OR REPLACE FUNCTION replace_mapping_wix_dux(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM mapping_wix_dux;
  INSERT INTO mapping_wix_dux (wix_id, wix_producto, dux_codigo, dux_producto, factor)
  SELECT wix_id, wix_producto, dux_codigo, dux_producto, factor
  FROM jsonb_to_recordset(rows) AS x(
    wix_id text, wix_producto text, dux_codigo text, dux_producto text, factor text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_packs_wix(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM packs_wix;
  INSERT INTO packs_wix (wix_id_pack, pack_nombre, dux_codigo, dux_producto, cantidad)
  SELECT wix_id_pack, pack_nombre, dux_codigo, dux_producto, cantidad
  FROM jsonb_to_recordset(rows) AS x(
    wix_id_pack text, pack_nombre text, dux_codigo text, dux_producto text, cantidad text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_selecciones_dux(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM selecciones_dux;
  INSERT INTO selecciones_dux (order_id, fecha_entrega)
  SELECT order_id, fecha_entrega
  FROM jsonb_to_recordset(rows) AS x(order_id text, fecha_entrega text);
END;
$$;

CREATE OR REPLACE FUNCTION replace_selecciones_wix(rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM selecciones_wix;
  INSERT INTO selecciones_wix (order_id, fecha_entrega)
  SELECT order_id, fecha_entrega
  FROM jsonb_to_recordset(rows) AS x(order_id text, fecha_entrega text);
END;
$$;

-- Para stock/estimado/semanal: reemplaza solo los registros de una fecha/dia específico

CREATE OR REPLACE FUNCTION replace_stock_fecha(p_fecha text, rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM stock_historico WHERE fecha = p_fecha;
  INSERT INTO stock_historico (fecha, codigo, producto, unidad_medida, cantidad)
  SELECT p_fecha, codigo, producto, unidad_medida, cantidad
  FROM jsonb_to_recordset(rows) AS x(
    codigo text, producto text, unidad_medida text, cantidad text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_estimado_fecha(p_fecha text, rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM estimado_historico WHERE fecha = p_fecha;
  INSERT INTO estimado_historico (fecha, codigo, producto, unidad_medida, estimado)
  SELECT p_fecha, codigo, producto, unidad_medida, estimado
  FROM jsonb_to_recordset(rows) AS x(
    codigo text, producto text, unidad_medida text, estimado text
  );
END;
$$;

CREATE OR REPLACE FUNCTION replace_estimado_semanal_dia(p_dia text, rows jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  DELETE FROM estimado_semanal WHERE dia_semana = p_dia;
  INSERT INTO estimado_semanal (dia_semana, codigo, producto, unidad_medida, estimado)
  SELECT p_dia, codigo, producto, unidad_medida, estimado
  FROM jsonb_to_recordset(rows) AS x(
    codigo text, producto text, unidad_medida text, estimado text
  );
END;
$$;

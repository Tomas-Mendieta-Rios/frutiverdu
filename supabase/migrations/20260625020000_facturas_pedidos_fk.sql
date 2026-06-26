-- Relacionar facturas con pedidos_dux via nro_pedido
-- nro_pedido es el numero de pedido legible (ej. "12345"), unico en DUX

ALTER TABLE pedidos_dux
    ADD CONSTRAINT pedidos_dux_nro_pedido_unique UNIQUE (nro_pedido);

ALTER TABLE facturas
    ADD CONSTRAINT facturas_nro_pedido_fkey
    FOREIGN KEY (nro_pedido)
    REFERENCES pedidos_dux (nro_pedido)
    ON DELETE SET NULL
    ON UPDATE CASCADE
    DEFERRABLE INITIALLY DEFERRED;

-- Actualizar cajas para que coincidan con los valores que manda DUX
-- tipo_valor: EFECTIVO, CHEQUE, CUENTA
-- descripcion cuando es CUENTA: MP FRUTIVERDU, MP CARLOS MENDIETA, BBVA, VALES

UPDATE cajas SET nombre = 'MP CARLOS MENDIETA' WHERE nombre = 'MP CARLOS';

INSERT INTO cajas (nombre) VALUES
    ('BBVA'),
    ('VALES')
ON CONFLICT (nombre) DO NOTHING;

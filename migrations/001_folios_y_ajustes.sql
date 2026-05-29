-- ============================================================
-- MIGRACIÓN 001 — Folios automáticos y Ajustes de Inventario
-- Ejecutar en Supabase → SQL Editor
-- ============================================================

-- 1. Secuencia para folios de Traspasos (T-1, T-2 ...)
CREATE SEQUENCE IF NOT EXISTS traspaso_folio_seq START 1;

-- 2. Secuencia para folios de Ajustes de Inventario (I-1, I-2 ...)
CREATE SEQUENCE IF NOT EXISTS ajuste_folio_seq START 1;

-- 3. Tabla de Ajustes de Inventario
--    (SQLAlchemy la crea automáticamente al iniciar el backend,
--     pero puedes crearla manualmente si prefieres)
CREATE TABLE IF NOT EXISTS ajustes_inventario (
    id         SERIAL PRIMARY KEY,
    folio      VARCHAR(20)  NOT NULL UNIQUE,
    modulo_id  INTEGER      NOT NULL REFERENCES modulos(id),
    usuario_id INTEGER      NOT NULL REFERENCES usuarios(id),
    fecha      TIMESTAMPTZ  NOT NULL,
    motivo     TEXT
);

-- 4. Tabla de productos de cada ajuste
CREATE TABLE IF NOT EXISTS ajustes_inventario_items (
    id                SERIAL PRIMARY KEY,
    ajuste_id         INTEGER NOT NULL REFERENCES ajustes_inventario(id) ON DELETE CASCADE,
    producto          TEXT    NOT NULL,
    clave             TEXT    NOT NULL,
    cantidad_anterior INTEGER NOT NULL,
    cantidad_nueva    INTEGER NOT NULL,
    delta             INTEGER NOT NULL
);

-- 5. Agregar valor AJUSTE_INVENTARIO al enum de kardex
--    (solo si no existe — Postgres 9.1+)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumlabel = 'AJUSTE_INVENTARIO'
          AND enumtypid = 'tipo_movimiento_enum'::regtype
    ) THEN
        ALTER TYPE tipo_movimiento_enum ADD VALUE 'AJUSTE_INVENTARIO';
    END IF;
END
$$;

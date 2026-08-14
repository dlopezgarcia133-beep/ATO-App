-- ============================================================
-- MIGRACIÓN 002 — Campo "asegurado" en usuarios
-- Ejecutar en Supabase → SQL Editor
-- ============================================================

-- Marca si el usuario cuenta con seguro. Se agrega con DEFAULT FALSE
-- porque la tabla ya tiene filas y la columna es NOT NULL: sin el
-- default el ALTER falla sobre los registros existentes.
ALTER TABLE usuarios
ADD COLUMN IF NOT EXISTS asegurado BOOLEAN NOT NULL DEFAULT FALSE;

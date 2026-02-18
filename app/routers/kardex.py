
from datetime import date
from pydoc import text
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app import models
from app.database import get_db
from app.config import get_current_user
from app.models import KardexMovimiento
from sqlalchemy import func
from sqlalchemy import text as sql_text


from pyexpat import model



router = APIRouter()



def registrar_kardex(
    db,
    producto,
    tipo_producto,
    cantidad,
    tipo_movimiento,
    usuario_id,
    modulo_origen_id=None,
    modulo_destino_id=None,
    referencia_id=None
):
    query = sql_text("""
        INSERT INTO kardex_movimientos (
            producto,
            tipo_producto,
            cantidad,
            tipo_movimiento,
            modulo_origen_id,
            modulo_destino_id,
            referencia_id,
            usuario_id
        )
        VALUES (
            :producto,
            :tipo_producto,
            :cantidad,
            :tipo_movimiento,
            :modulo_origen_id,
            :modulo_destino_id,
            :referencia_id,
            :usuario_id
        )
    """)

    db.execute(query, {
        "producto": producto,
        "tipo_producto": tipo_producto,
        "cantidad": cantidad,
        "tipo_movimiento": tipo_movimiento,
        "modulo_origen_id": modulo_origen_id,
        "modulo_destino_id": modulo_destino_id,
        "referencia_id": referencia_id,
        "usuario_id": usuario_id
    })

@router.get("/kardex")
def obtener_kardex(
    producto: str = None,
    modulo_id: int = None,
    fecha_inicio: date = None,
    fecha_fin: date = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(KardexMovimiento)

    if producto:
        query = query.filter(KardexMovimiento.producto == producto)

    if modulo_id:
        query = query.filter(
            (KardexMovimiento.modulo_origen_id == modulo_id) |
            (KardexMovimiento.modulo_destino_id == modulo_id)
        )

    if fecha_inicio and fecha_fin:
        query = query.filter(
            func.date(KardexMovimiento.fecha).between(fecha_inicio, fecha_fin)
        )

    return query.order_by(KardexMovimiento.fecha.desc()).all()

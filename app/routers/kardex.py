
from datetime import date
from pydoc import text
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, aliased
from app import models
from app.database import get_db
from app.config import get_current_user
from app.models import KardexMovimiento
from sqlalchemy import func
from sqlalchemy import text as sql_text
from datetime import date, timedelta

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
    tipo_movimiento: str = None,
    fecha_inicio: date = None,
    fecha_fin: date = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    modulo_origen = aliased(models.Modulo)
    modulo_destino = aliased(models.Modulo)

    query = db.query(
        KardexMovimiento,
        modulo_origen.nombre.label("modulo_origen_nombre"),
        modulo_destino.nombre.label("modulo_destino_nombre")
    ).outerjoin(
        modulo_origen,
        KardexMovimiento.modulo_origen_id == modulo_origen.id
    ).outerjoin(
        modulo_destino,
        KardexMovimiento.modulo_destino_id == modulo_destino.id
    )

    # ---------------- SEGURIDAD ----------------
    if current_user.rol == "encargado":
        query = query.filter(
            (KardexMovimiento.modulo_origen_id == current_user.modulo_id) |
            (KardexMovimiento.modulo_destino_id == current_user.modulo_id)
        )
    else:
        if modulo_id:
            query = query.filter(
                (KardexMovimiento.modulo_origen_id == modulo_id) |
                (KardexMovimiento.modulo_destino_id == modulo_id)
            )

    # ---------------- FILTROS ----------------

    if tipo_movimiento:
        query = query.filter(
            KardexMovimiento.tipo_movimiento == tipo_movimiento
        )

    if producto:
        query = query.filter(
            KardexMovimiento.producto == producto
        )

    # 🔹 si no mandan fechas, usar últimos 7 días
    if not fecha_inicio and not fecha_fin:
        fecha_inicio = date.today() - timedelta(days=7)
        fecha_fin = date.today()

    if fecha_inicio and fecha_fin:
        query = query.filter(
            func.date(KardexMovimiento.fecha).between(fecha_inicio, fecha_fin)
        )

    resultados = query.order_by(
        KardexMovimiento.fecha.desc()
    ).offset(skip).limit(limit).all()

    data = []

    for kardex, origen_nombre, destino_nombre in resultados:

        item = kardex.__dict__.copy()
        item["modulo_origen"] = origen_nombre
        item["modulo_destino"] = destino_nombre
        item.pop("_sa_instance_state", None)

        data.append(item)

    return data
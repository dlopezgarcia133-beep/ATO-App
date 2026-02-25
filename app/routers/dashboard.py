
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta

from app.database import get_db
from app import models

router = APIRouter()


@router.get("/ventas-dia")
def ventas_dia(db: Session = Depends(get_db)):

    hoy = date.today()

    data = db.query(
        models.Venta.modulo_id,
        func.sum(models.Venta.total).label("total")
    ).filter(
        func.date(models.Venta.fecha) == hoy
    ).group_by(
        models.Venta.modulo_id
    ).all()

    return [
        {
            "modulo_id": d.modulo_id,
            "total": float(d.total)
        }
        for d in data
    ]


@router.get("/comisiones-semana")
def comisiones_semana(db: Session = Depends(get_db)):

    hoy = date.today()
    inicio = hoy - timedelta(days=hoy.weekday())

    data = db.query(
        models.Venta.empleado_id,
        func.sum(models.Venta.comision).label("total")
    ).filter(
        func.date(models.Venta.fecha) >= inicio
    ).group_by(
        models.Venta.empleado_id
    ).all()

    return [
        {
            "empleado_id": d.empleado_id,
            "total_comision": float(d.total or 0)
        }
        for d in data
    ]



@router.get("/inventario")
def inventario(db: Session = Depends(get_db)):

    data = db.query(
        models.InventarioModulo.modulo_id,
        models.InventarioModulo.producto,
        models.InventarioModulo.cantidad
    ).all()

    return [
        {
            "modulo_id": d.modulo_id,
            "producto": d.producto,
            "cantidad": d.cantidad
        }
        for d in data
    ]



@router.get("/traspasos")
def traspasos(db: Session = Depends(get_db)):

    data = db.query(
        models.Traspaso.producto,
        models.Traspaso.modulo_origen,
        models.Traspaso.modulo_destino,
        models.Traspaso.estado,
        models.Traspaso.fecha
    ).all()

    resultado = []

    for row in data:
        resultado.append({
            "producto": row.producto,
            "modulo_origen": row.modulo_origen,
            "modulo_destino": row.modulo_destino,
            "estado": row.estado,
            "fecha": row.fecha
        })

    return resultado


@router.get("/nomina")
def nomina(db: Session = Depends(get_db)):

    data = db.query(
        models.Usuario.nombre_completo,
        models.NominaEmpleado.total_comisiones,
        models.NominaEmpleado.sanciones,
        models.NominaEmpleado.total_pagar
    ).join(
        models.Usuario,
        models.Usuario.id == models.NominaEmpleado.usuario_id
    ).all()

    return data
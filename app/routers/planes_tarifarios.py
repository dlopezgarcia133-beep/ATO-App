from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo

from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.routers.kardex import registrar_kardex

router = APIRouter()


@router.post("", response_model=schemas.PlanTarifarioResponse)
def crear_plan_tarifario(
    plan: schemas.PlanTarifarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    modulo_id = current_user.modulo_id

    # Si hay equipo, descontar del inventario del módulo (mismo patrón que ventas)
    if plan.equipo and plan.equipo.strip():
        inventario = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.modulo_id == modulo_id,
                models.InventarioModulo.producto == plan.equipo,
                models.InventarioModulo.tipo_producto == "telefono"
            )
            .first()
        )
        if not inventario:
            raise HTTPException(400, f"No hay inventario para {plan.equipo}")
        if inventario.cantidad < 1:
            raise HTTPException(400, f"Inventario insuficiente para {plan.equipo}")
        inventario.cantidad -= 1

    nuevo = models.PlanTarifario(
        fecha=datetime.now(ZoneInfo("America/Mexico_City")),
        empleado_id=current_user.id,
        modulo_id=modulo_id,
        tipo_plan=plan.tipo_plan,
        estatus=plan.estatus,
        categoria=plan.categoria,
        clasificacion=plan.clasificacion,
        equipo=plan.equipo,
        imei=plan.imei,
        precio_equipo=plan.precio_equipo,
        plazo=plan.plazo,
        linea=plan.linea,
        cuenta=plan.cuenta,
        pago_inicial=plan.pago_inicial or False,
        monto_pago_inicial=plan.monto_pago_inicial or 0,
    )
    db.add(nuevo)
    db.flush()

    # Kardex solo si se descontó equipo
    if plan.equipo and plan.equipo.strip():
        registrar_kardex(
            db=db,
            producto=plan.equipo,
            tipo_producto="telefono",
            cantidad=1,
            tipo_movimiento="VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_id,
            referencia_id=nuevo.id
        )

    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.get("", response_model=List[schemas.PlanTarifarioResponse])
def listar_planes_tarifarios(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return (
        db.query(models.PlanTarifario)
        .order_by(models.PlanTarifario.id.desc())
        .all()
    )

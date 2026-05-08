from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app import models, schemas
from app.config import get_current_user
from app.database import get_db

router = APIRouter()


def _verificar_rol(user: models.Usuario):
    if user.is_admin:
        return
    if user.rol not in (models.RolEnum.direccion, models.RolEnum.admin):
        raise HTTPException(status_code=403, detail="Sin permiso para este recurso")


@router.get("/cortes", response_model=Optional[schemas.DireccionCorteResponse])
def obtener_corte_direccion(
    modulo_id: int = Query(...),
    fecha: date = Query(...),
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    corte = (
        db.query(models.CorteDia)
        .filter(
            models.CorteDia.fecha == fecha,
            models.CorteDia.modulo_id == modulo_id,
        )
        .first()
    )

    if corte is None:
        return None

    chips = (
        db.query(models.VentaChip)
        .join(models.Usuario, models.VentaChip.empleado_id == models.Usuario.id)
        .filter(
            models.Usuario.modulo_id == modulo_id,
            models.VentaChip.fecha == fecha,
            models.VentaChip.cancelada == False,
        )
        .all()
    )

    chips_por_tipo: dict = {}
    for chip in chips:
        tipo = chip.tipo_chip or "Sin tipo"
        chips_por_tipo[tipo] = chips_por_tipo.get(tipo, 0) + 1

    base = schemas.CorteDiaResponse.model_validate(corte)
    return schemas.DireccionCorteResponse(
        **base.model_dump(),
        chips_count=len(chips),
        chips_por_tipo=chips_por_tipo,
    )

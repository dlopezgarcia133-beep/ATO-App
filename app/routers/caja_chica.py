
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido

router = APIRouter()


@router.get("/caja-chica", response_model=schemas.CajaChicaResponse)
def obtener_caja_chica(
    modulo_id: int = Query(...),
    fecha: date = Query(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    registro = (
        db.query(models.CajaChica)
        .filter(
            models.CajaChica.modulo_id == modulo_id,
            models.CajaChica.fecha == fecha,
        )
        .first()
    )
    if not registro:
        return schemas.CajaChicaResponse(id=0, modulo_id=modulo_id, fecha=fecha, monto=0.0)
    return registro


@router.post("/caja-chica", response_model=schemas.CajaChicaResponse)
def guardar_caja_chica(
    data: schemas.CajaChicaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.direccion])
    ),
):
    if data.monto < 0:
        raise HTTPException(status_code=400, detail="El monto no puede ser negativo")

    registro = (
        db.query(models.CajaChica)
        .filter(
            models.CajaChica.modulo_id == data.modulo_id,
            models.CajaChica.fecha == data.fecha,
        )
        .first()
    )

    if registro:
        registro.monto = data.monto
    else:
        registro = models.CajaChica(
            modulo_id=data.modulo_id,
            fecha=data.fecha,
            monto=data.monto,
        )
        db.add(registro)

    db.commit()
    db.refresh(registro)
    return registro

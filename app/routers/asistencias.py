
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db



router = APIRouter()


# ------------------- ASISTENCIAS -------------------
@router.post("/asistencias", response_model=schemas.AsistenciaLegacyResponse)
def registrar_asistencia(
    turno: str,  
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    
    nombre = current_user.username
    modulo = current_user.modulo.nombre if current_user.modulo else None

    # 2. Verificamos que no exista ya una asistencia hoy
    hoy = datetime.now().date()
    if db.query(models.AsistenciaLegacy).filter(models.AsistenciaLegacy.nombre==nombre, models.AsistenciaLegacy.fecha==hoy).first():
        raise HTTPException(400, "Ya registraste asistencia hoy")

    # 3. Creamos la nueva asistencia
    nueva = models.AsistenciaLegacy(
        nombre=nombre,
        modulo=modulo,
        turno=turno,
        fecha=hoy,
        hora=datetime.now().time()
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva



@router.post("/logout")
def logout(current_user: models.Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    zona_horaria = ZoneInfo("America/Mexico_City")
    ahora = datetime.now(zona_horaria)
    hoy = ahora.date()

    asistencia = db.query(models.AsistenciaLegacy).filter(
        models.AsistenciaLegacy.nombre == current_user.username,
        models.AsistenciaLegacy.fecha == hoy
    ).order_by(models.AsistenciaLegacy.hora.desc()).first()

    if not asistencia:
        raise HTTPException(status_code=404, detail="No se encontró asistencia para hoy")

    if asistencia.hora_salida:
        raise HTTPException(status_code=400, detail="La salida ya fue registrada")

    asistencia.hora_salida = ahora.time()
    db.commit()
    db.refresh(asistencia)

    return {"mensaje": "Sesión cerrada y salida registrada correctamente"}
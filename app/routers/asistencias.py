
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db



router = APIRouter()


# ------------------- ASISTENCIAS -------------------
@router.post("/asistencias", response_model=schemas.Asistencia)
def registrar_asistencia(
    turno: str,  
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    
    nombre = current_user.username
    modulo = current_user.modulo.nombre if current_user.modulo else None

    # 2. Verificamos que no exista ya una asistencia hoy
    hoy = datetime.now().date()
    if db.query(models.Asistencia).filter(models.Asistencia.nombre==nombre, models.Asistencia.fecha==hoy).first():
        raise HTTPException(400, "Ya registraste asistencia hoy")

    # 3. Creamos la nueva asistencia
    nueva = models.Asistencia(
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
    hoy = datetime.now().date()

    asistencia = db.query(models.Asistencia).filter(
        models.Asistencia.nombre == current_user.username,
        models.Asistencia.fecha == hoy
    ).order_by(models.Asistencia.hora.desc()).first()

    if not asistencia:
        raise HTTPException(status_code=404, detail="No se encontró asistencia para hoy")

    if asistencia.hora_salida:
        raise HTTPException(status_code=400, detail="La salida ya fue registrada")

    asistencia.hora_salida = datetime.now().time()
    db.commit()
    db.refresh(asistencia)

    return {"mensaje": "Sesión cerrada y salida registrada correctamente"}
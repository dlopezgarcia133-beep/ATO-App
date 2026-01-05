
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app import models
from app.config import crear_token, get_current_user
from app.database import get_db
from passlib.context import CryptContext


router = APIRouter()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

zona_horaria_local = ZoneInfo("America/Mexico_City")

@router.post("/token")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(models.Usuario).filter(
        models.Usuario.username == form_data.username
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # 🚫 Usuario desactivado
    if not user.activo:
        raise HTTPException(
            status_code=403,
            detail="Usuario desactivado. Contacta al administrador."
        )

    if not pwd_context.verify(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # 👑 ADMIN
    if user.is_admin:
        token = crear_token({"sub": user.username, "rol": user.rol})
        return {
            "access_token": token,
            "token_type": "bearer",
            "usuario": user.username,
            "modulo": user.modulo.nombre if user.modulo else None,
            "rol": user.rol
        }

    # ⏰ lógica de asistencia (igual que la tuya)
    ahora_local = datetime.now(tz=zona_horaria_local)
    hoy = ahora_local.date()

    asistencia_existente = db.query(models.Asistencia).filter(
        models.Asistencia.nombre == user.username,
        models.Asistencia.fecha == hoy
    ).first()

    if not asistencia_existente:
        turno = determinar_turno(ahora_local.time())
        nueva_asistencia = models.Asistencia(
            nombre=user.username,
            modulo=user.modulo.nombre if user.modulo else None,
            turno=turno,
            fecha=hoy,
            hora=ahora_local.time()
        )
        db.add(nueva_asistencia)
        db.commit()

    token = crear_token({"sub": user.username, "rol": user.rol})
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": user.username,
        "modulo": user.modulo.nombre if user.modulo else None,
        "rol": user.rol
    }


@router.get("/usuarios/me")
def get_me(current_user: models.Usuario = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "rol": current_user.rol,
        "is_admin": current_user.is_admin
    }

# ------------------- UTILIDAD PARA CONTRASEÑAS -------------------
def hashear_contraseña(password: str):
    return pwd_context.hash(password)


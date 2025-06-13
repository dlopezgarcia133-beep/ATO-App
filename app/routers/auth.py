
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app import models
from app.config import crear_token
from app.database import get_db
from passlib.context import CryptContext


router = APIRouter()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.Usuario).filter(models.Usuario.username == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    
    if user.is_admin:
        token = crear_token({"sub": user.username})
        return {"access_token": token, "token_type": "bearer"}

    # Verifica si ya tiene asistencia registrada hoy
    hoy = datetime.now().date()
    asistencia_existente = db.query(models.Asistencia).filter(
        models.Asistencia.nombre == user.username,
        models.Asistencia.fecha == hoy
    ).first()



    
    def determinar_turno (hora: datetime.time) -> str:
        if hora >= datetime.strptime("08:00", "%H:%M").time() and hora < datetime.strptime("15:00", "%H:%M").time():
            return "mañana"
        elif hora >= datetime.strptime("15:00", "%H:%M").time() and hora < datetime.strptime("20:00", "%H:%M").time():
            return "tarde"
        else:
            return "fuera de turno"

    if not asistencia_existente:
        hora_actual = datetime.now().time()  # Hora actual del sistema
        turno = determinar_turno(hora_actual) 
        
        nueva_asistencia = models.Asistencia(
            nombre=user.username,
            modulo=user.modulo,  
            turno= turno,
            fecha=hoy,
            hora=datetime.now().time()
        )
        db.add(nueva_asistencia)
        db.commit()
        db.refresh(nueva_asistencia)
    token = crear_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}



# ------------------- UTILIDAD PARA CONTRASEÑAS -------------------
def hashear_contraseña(password: str):
    return pwd_context.hash(password)


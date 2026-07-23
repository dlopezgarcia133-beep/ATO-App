

from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt
from passlib.context import CryptContext
from app import models
from app.database import get_db



# ------------------- CONFIGURACIÓN JWT -------------------

SECRET_KEY = "mi_clave_secreta"
ALGORITHM = "HS256"


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _exp_cierre_diario() -> datetime:
    """Devuelve el proximo 23:59 hora de Mexico City, en UTC aware."""
    zona = ZoneInfo("America/Mexico_City")
    ahora = datetime.now(zona)
    corte = ahora.replace(hour=23, minute=59, second=0, microsecond=0)
    if ahora >= corte:
        corte = corte + timedelta(days=1)
    return corte.astimezone(timezone.utc)


def crear_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta is not None:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = _exp_cierre_diario()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        user = db.query(models.Usuario).filter(models.Usuario.username == username).first()
        if user is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
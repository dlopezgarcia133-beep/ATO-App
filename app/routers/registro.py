from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2 import IntegrityError
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.rutas import get_current_user, hashear_contraseña




router = APIRouter()


# ------------------- REGISTRO -------------------
@router.post("/registro", response_model=schemas.UsuarioResponse)
def registrar_usuario(
    usuario: schemas.UsuarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if len(usuario.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    if not any(char.isdigit() for char in usuario.password):
        raise HTTPException(status_code=400, detail="La contraseña debe contener al menos un número")
    if not any(char.isalpha() for char in usuario.password):
        raise HTTPException(status_code=400, detail="La contraseña debe contener al menos una letra")

    usuario_existente = db.query(models.Usuario).filter(models.Usuario.username == usuario.username).first()

    try:
        if usuario.is_admin and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="No tienes permisos para crear usuarios administradores")
        if usuario_existente:
            raise HTTPException(status_code=400, detail="El usuario ya existe")

        usuario_nuevo = models.Usuario(
            username=usuario.username,
            ident=usuario.ident,
            password=hashear_contraseña(usuario.password),
            modulo=usuario.modulo,
            is_admin=usuario.is_admin or False
        )
        db.add(usuario_nuevo)
        db.commit()
        db.refresh(usuario_nuevo)
        return usuario_nuevo
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar el usuario")
    
    

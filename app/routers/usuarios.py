
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.rutas import get_current_user


router = APIRouter()






@router.post("/seleccionar_modulo")
def seleccionar_modulo(data: schemas.ModuloSelect, 
                       db: Session = Depends(get_db), 
                       user: models.Usuario = Depends(get_current_user)):
    usuario_db = db.query(models.Usuario).filter(models.Usuario.id == user.id).first()

    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario_db.modulo = data.modulo
    db.commit()
    db.refresh(usuario_db)

    return {"message": f"Módulo '{data.modulo}' asignado correctamente"}



def verificar_rol(usuario: models.Usuario, roles_permitidos: list[str]):
    if usuario.rol not in roles_permitidos:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes permisos suficientes (se requiere uno de: {roles_permitidos})"
        )
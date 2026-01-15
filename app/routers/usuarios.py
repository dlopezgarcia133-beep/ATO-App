
from sqlalchemy import case
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2 import IntegrityError
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.routers.auth import hashear_contraseña
from app.utilidades import verificar_rol_requerido





router = APIRouter()


# ------------------- REGISTRO -------------------
@router.post("/registro", response_model=schemas.UsuarioResponse)
def registrar_usuario(
    usuario: schemas.UsuarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
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
        
        modulo_obj = None
        if not usuario.is_admin:
            if usuario.modulo_id is None:
                raise HTTPException(status_code=400, detail="El módulo es obligatorio para este rol")
            modulo_obj = db.query(models.Modulo).filter_by(id=usuario.modulo_id).first()
            if not modulo_obj:
                raise HTTPException(status_code=404, detail="El módulo no existe")

        usuario_nuevo = models.Usuario(
            username=usuario.username,
            rol=usuario.rol,
            password=hashear_contraseña(usuario.password),
            modulo=modulo_obj,
            is_admin=usuario.is_admin or False
        )
        db.add(usuario_nuevo)
        db.commit()
        db.refresh(usuario_nuevo)
        return usuario_nuevo
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar el usuario")
    
    

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

@router.get("/modulos", response_model=list[schemas.ModuloResponse])
def obtener_modulos(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return db.query(models.Modulo).all()



def verificar_rol(usuario: models.Usuario, roles_permitidos: list[str]):
    if usuario.rol not in roles_permitidos:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes permisos suficientes (se requiere uno de: {roles_permitidos})"
        )
        

@router.put("/usuarios/{usuario_id}", response_model=schemas.UsuarioResponse)
def editar_usuario(
    usuario_id: int,
    datos: schemas.UsuarioUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    usuario_db = db.query(models.Usuario).filter_by(id=usuario_id).first()

    if not usuario_db:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if datos.username:
        usuario_db.username = datos.username
    if datos.rol:
        usuario_db.rol = datos.rol
    if datos.modulo_id is not None:
        modulo_obj = db.query(models.Modulo).filter_by(id=datos.modulo_id).first()
        if not modulo_obj:
            raise HTTPException(status_code=404, detail="Módulo no encontrado")
        usuario_db.modulo = modulo_obj
    if datos.is_admin is not None:
        usuario_db.is_admin = datos.is_admin
    if datos.password:
        if len(datos.password) < 8 or not any(c.isdigit() for c in datos.password) or not any(c.isalpha() for c in datos.password):
            raise HTTPException(status_code=400, detail="La contraseña no cumple con los requisitos")
        usuario_db.password = hashear_contraseña(datos.password)

    db.commit()
    db.refresh(usuario_db)
    return usuario_db



@router.delete("/usuarios/{usuario_id}")
def desactivar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db)
):
    usuario = db.query(models.Usuario).filter(
        models.Usuario.id == usuario_id
    ).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.activo = False
    db.commit()

    return {"message": "Usuario desactivado correctamente"}





@router.get("/usuarios", response_model=list[schemas.UsuarioResponse])
def obtener_usuarios(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido(models.RolEnum.admin)
    )
):
    return (
        db.query(models.Usuario)
        .filter(models.Usuario.activo == True)
        .order_by(
            case(
                (models.Usuario.username.ilike("A%"), 1),
                (models.Usuario.username.ilike("C%"), 2),
                else_=0
            ),
            models.Usuario.username.asc()
        )
        .all()
    )




@router.put("/usuarios/{usuario_id}/sueldo")
def actualizar_sueldo_base(
    usuario_id: int,
    sueldo_base: float,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    usuario = db.query(models.Usuario).get(usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.sueldo_base = sueldo_base
    db.commit()

    return {"ok": True, "sueldo_base": sueldo_base}

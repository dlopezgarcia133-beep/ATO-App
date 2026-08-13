
import sys
import traceback
from sqlalchemy import case, func
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2 import IntegrityError
from sqlalchemy.orm import Session, joinedload
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
        roles_sin_modulo = ("check", "direccion")
        rol_str = usuario.rol.value if hasattr(usuario.rol, "value") else str(usuario.rol)
        if not usuario.is_admin and rol_str not in roles_sin_modulo:
            if usuario.modulo_id is None:
                raise HTTPException(status_code=400, detail="El módulo es obligatorio para este rol")
            modulo_obj = db.query(models.Modulo).filter_by(id=usuario.modulo_id).first()
            if not modulo_obj:
                raise HTTPException(status_code=404, detail="El módulo no existe")

        usuario_nuevo = models.Usuario(
            nombre_completo=usuario.nombre_completo,
            username=usuario.username,
            rol=usuario.rol,
            password=hashear_contraseña(usuario.password),
            modulo=modulo_obj,
            is_admin=usuario.is_admin or False,
            forma_pago=usuario.forma_pago or None,
            cuenta_clabe=usuario.cuenta_clabe or None,
            cuenta_interbancaria=usuario.cuenta_interbancaria or None,
            nombre_englobado=usuario.nombre_englobado or None,
            jornada_fija=usuario.jornada_fija or 0,
            tienda_id=usuario.tienda_id or None,
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


# ------------------- CADENAS (catálogo padre de tiendas) -------------------
@router.get("/cadenas", response_model=list[schemas.CadenaResponse])
def obtener_cadenas(
    incluir_inactivas: bool = False,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(models.Cadena)
    if not incluir_inactivas:
        query = query.filter(models.Cadena.activo == True)
    return query.order_by(models.Cadena.nombre).all()


# ------------------- TIENDAS (catálogo para módulos Cadenas) -------------------
CAMPOS_TIENDA = [
    "cadena_id", "num_tienda", "garantizados",
    "clave_1", "clave_2", "clave_3", "clave_4",
]


def _validar_cadena(db: Session, cadena_id):
    if cadena_id is None:
        return
    existe = db.query(models.Cadena).filter_by(id=cadena_id).first()
    if not existe:
        raise HTTPException(status_code=400, detail="La cadena indicada no existe")


def _validar_tienda(db: Session, tienda_id):
    if tienda_id is None:
        return
    existe = db.query(models.Tienda).filter_by(id=tienda_id).first()
    if not existe:
        raise HTTPException(status_code=400, detail="La tienda indicada no existe")


def _validar_num_tienda(db: Session, num_tienda, excluir_id=None):
    if num_tienda is None:
        return
    query = db.query(models.Tienda).filter(models.Tienda.num_tienda == num_tienda)
    if excluir_id is not None:
        query = query.filter(models.Tienda.id != excluir_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Ya existe una tienda con el número {num_tienda}")


@router.get("/tiendas", response_model=list[schemas.TiendaResponse])
def obtener_tiendas(
    incluir_inactivas: bool = False,
    cadena_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(models.Tienda).options(joinedload(models.Tienda.cadena))
    if not incluir_inactivas:
        query = query.filter(models.Tienda.activo == True)
    if cadena_id is not None:
        query = query.filter(models.Tienda.cadena_id == cadena_id)
    return query.order_by(models.Tienda.nombre).all()


@router.put("/tiendas/{tienda_id}", response_model=schemas.TiendaResponse)
def actualizar_tienda(
    tienda_id: int,
    datos: schemas.TiendaUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    tienda = db.query(models.Tienda).filter_by(id=tienda_id).first()
    if not tienda:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")

    enviados = datos.model_dump(exclude_unset=True)

    if "nombre" in enviados:
        nombre = (enviados["nombre"] or "").strip()
        if not nombre:
            raise HTTPException(status_code=400, detail="El nombre de la tienda es obligatorio")
        duplicada = (
            db.query(models.Tienda)
            .filter(func.lower(models.Tienda.nombre) == nombre.lower(), models.Tienda.id != tienda_id)
            .first()
        )
        if duplicada:
            raise HTTPException(status_code=400, detail="Ya existe una tienda con ese nombre")
        tienda.nombre = nombre

    if "activo" in enviados:
        tienda.activo = enviados["activo"]

    if "cadena_id" in enviados:
        _validar_cadena(db, enviados["cadena_id"])

    if "num_tienda" in enviados:
        _validar_num_tienda(db, enviados["num_tienda"], excluir_id=tienda_id)

    for campo in CAMPOS_TIENDA:
        if campo in enviados:
            setattr(tienda, campo, enviados[campo])

    db.commit()
    db.refresh(tienda)
    return tienda


@router.post("/tiendas", response_model=schemas.TiendaResponse)
def crear_tienda(
    tienda: schemas.TiendaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    nombre = (tienda.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre de la tienda es obligatorio")

    existente = (
        db.query(models.Tienda)
        .filter(func.lower(models.Tienda.nombre) == nombre.lower())
        .first()
    )
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una tienda con ese nombre")

    _validar_cadena(db, tienda.cadena_id)
    _validar_num_tienda(db, tienda.num_tienda)

    nueva = models.Tienda(
        nombre=nombre,
        cadena_id=tienda.cadena_id,
        num_tienda=tienda.num_tienda,
        garantizados=tienda.garantizados,
        clave_1=tienda.clave_1,
        clave_2=tienda.clave_2,
        clave_3=tienda.clave_3,
        clave_4=tienda.clave_4,
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva



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
    try:
        usuario_db = db.query(models.Usuario).filter_by(id=usuario_id).first()

        if not usuario_db:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        if "nombre_completo" in datos.model_fields_set:
            usuario_db.nombre_completo = datos.nombre_completo or None
        if datos.username and datos.username != usuario_db.username:
            duplicado = db.query(models.Usuario).filter(
                models.Usuario.username == datos.username,
                models.Usuario.id != usuario_id
            ).first()
            if duplicado:
                raise HTTPException(status_code=400, detail=f"El username '{datos.username}' ya está en uso")
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
        if datos.sueldo_base is not None:
            usuario_db.sueldo_base = datos.sueldo_base
        if "forma_pago" in datos.model_fields_set:
            usuario_db.forma_pago = datos.forma_pago or None
        if "cuenta_clabe" in datos.model_fields_set:
            usuario_db.cuenta_clabe = datos.cuenta_clabe or None
        if "tienda_id" in datos.model_fields_set:
            _validar_tienda(db, datos.tienda_id)
            usuario_db.tienda_id = datos.tienda_id
        if "cuenta_interbancaria" in datos.model_fields_set:
            usuario_db.cuenta_interbancaria = datos.cuenta_interbancaria or None
        if "nombre_englobado" in datos.model_fields_set:
            usuario_db.nombre_englobado = datos.nombre_englobado or None
        if datos.jornada_fija is not None:
            usuario_db.jornada_fija = datos.jornada_fija

        db.commit()
        db.refresh(usuario_db)
        return usuario_db

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print("=== ERROR EN editar_usuario ===", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        print("================================", file=sys.stderr, flush=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {type(e).__name__}: {str(e)}")



@router.delete("/usuarios/{usuario_id}")
def desactivar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin, models.RolEnum.direccion]))
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
def actualizar_sueldo(
    usuario_id: int,
    data: schemas.SueldoBaseUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    usuario.sueldo_base = data.sueldo_base
    db.commit()

    return {"ok": True, "sueldo_base": usuario.sueldo_base}

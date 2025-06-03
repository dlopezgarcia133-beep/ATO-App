from fastapi import APIRouter, Depends, HTTPException, Query, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from psycopg2 import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from datetime import datetime, timedelta
from passlib.context import CryptContext

router = APIRouter()

# ------------------- CONFIGURACIÓN JWT -------------------
SECRET_KEY = "mi_clave_secreta"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def crear_token(data: dict, expires_delta: timedelta = timedelta(hours=12)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
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


# ------------------- AUTENTICACIÓN -------------------
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
            modulo=user.modulo,  # Puedes cambiarlo por un valor predeterminado o campo de usuario
            turno= turno,
            fecha=hoy,
            hora=datetime.now().time()
        )
        db.add(nueva_asistencia)
        db.commit()

    token = crear_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}



# ------------------- UTILIDAD PARA CONTRASEÑAS -------------------
def hashear_contraseña(password: str):
    return pwd_context.hash(password)


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


# ------------------- ASISTENCIAS -------------------
@router.post("/asistencias", response_model=schemas.Asistencia)
def registrar_asistencia(
    turno: str = Query(..., description="turno: 'mañana' o 'tarde'"),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # 1. Reconstruimos el nombre y módulo desde el usuario
    nombre = current_user.username
    modulo = current_user.modulo

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


@router.put("/asistencias/salida", response_model=schemas.Asistencia)
def marcar_salida(nombre: str = Query(...), db: Session = Depends(get_db)):
    hoy = datetime.now().date()

    asistencia = db.query(models.Asistencia)\
        .filter(models.Asistencia.nombre == nombre, models.Asistencia.fecha == hoy)\
        .order_by(models.Asistencia.hora.desc())\
        .first()

    if not asistencia:
        raise HTTPException(status_code=404, detail="No se encontró asistencia para hoy")

    if asistencia.hora_salida:
        raise HTTPException(status_code=400, detail="La salida ya fue registrada")

    asistencia.hora_salida = datetime.now().time()
    db.commit()
    db.refresh(asistencia)
    return asistencia


# ------------------- VENTAS -------------------
@router.post("/ventas", response_model=schemas.VentaResponse)
def crear_venta(venta: schemas.VentaCreate, db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    # 1. Buscar comisión (case-insensitive)
    com = (
        db.query(models.Comision)
          .filter(func.lower(models.Comision.producto) == venta.producto.strip().lower())
          .first()
    )
    comision = com.cantidad if com else None

    # 2. Calcular total
    total = venta.precio_unitario * venta.cantidad

    modulo = current_user.modulo
    
    # 3. Crear la venta
    nueva_venta = models.Venta(
        empleado_id=current_user.id,
        modulo=modulo,
        producto=venta.producto,
        cantidad=venta.cantidad,
        precio_unitario=venta.precio_unitario,
        comision=comision,
        fecha=datetime.now().date(),
        hora=datetime.now().time()
    )
    # Si dejaste el campo total en el modelo, descomenta esta línea:
    # nueva_venta.total = total

    db.add(nueva_venta)
    db.commit()
    db.refresh(nueva_venta)

    # 4. Añadir el atributo total al objeto de respuesta
    respuesta = schemas.VentaResponse.from_orm(nueva_venta)
    respuesta.total = total
    return respuesta


@router.get("/ventas", response_model=list[schemas.VentaResponse])
def obtener_ventas(db: Session = Depends(get_db)):
    ventas = db.query(models.Venta).all()
    # Calcular total en cada uno si borraste la columna
    resultados = []
    for v in ventas:
        item = schemas.VentaResponse.from_orm(v)
        item.total = v.precio_unitario * v.cantidad
        resultados.append(item)
    return resultados


@router.get("/ventas/resumen")
def resumen_ventas(db: Session = Depends(get_db)):
    total_ventas = db.query(func.sum(models.Venta.precio_unitario * models.Venta.cantidad)).scalar() or 0
    total_comisiones = db.query(func.sum(models.Venta.comision)).scalar() or 0
    return {
        "total_ventas": total_ventas,
        "total_comisiones": total_comisiones
    }


# CREAR COMISIÓN
@router.post("/comisiones", response_model=schemas.ComisionResponse)
def crear_comision(
    comision: schemas.ComisionCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    existente = db.query(models.Comision).filter_by(producto=comision.producto).first()
    if existente:
        raise HTTPException(status_code=400, detail="Este producto ya tiene comisión registrada")

    nueva = models.Comision(**comision.dict())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


# EDITAR COMISIÓN
@router.put("/comisiones/{producto}", response_model=schemas.ComisionResponse)
def actualizar_comision(
    producto: str,
    comision: schemas.ComisionUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    com_db = db.query(models.Comision).filter_by(producto=producto).first()
    if not com_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    com_db.cantidad = comision.cantidad
    db.commit()
    db.refresh(com_db)
    return com_db


# ELIMINAR COMISIÓN
@router.delete("/comisiones/{producto}")
def eliminar_comision(
    producto: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    com_db = db.query(models.Comision).filter_by(producto=producto).first()
    if not com_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    db.delete(com_db)
    db.commit()
    return {"mensaje": f"Comisión para producto '{producto}' eliminada"}



@router.get("/comisiones", response_model=list[schemas.ComisionCreate])
def obtener_comisiones(db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Solo el admin puede ver todas las comisiones")
    return db.query(models.Comision).all()

@router.get("/comisiones/{producto}", response_model=schemas.ComisionCreate)
def obtener_comision_producto(producto: str, db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    comision = db.query(models.Comision).filter_by(producto=producto).first()
    if not comision:
        raise HTTPException(status_code=404, detail="No se encontró comisión para ese producto")
    return comision






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

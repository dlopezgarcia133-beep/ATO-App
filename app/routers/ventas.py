
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.rutas import get_current_user


router = APIRouter()


# ------------------- VENTAS -------------------
@router.post("/ventas", response_model=schemas.VentaResponse)
def crear_venta(venta: schemas.VentaCreate, db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    
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
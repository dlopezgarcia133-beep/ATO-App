
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.utilidades import enviar_ticket, verificar_rol_requerido


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
    
    
    inventario = (
        db.query(models.InventarioModulo)
        .filter_by(modulo=modulo, producto=venta.producto)
        .first()
    )

    if not inventario:
        raise HTTPException(status_code=404, detail="Producto no registrado en el inventario del módulo")

    if inventario.cantidad < venta.cantidad:
        raise HTTPException(status_code=400, detail="Inventario insuficiente para esta venta")


    inventario.cantidad -= venta.cantidad
    
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
    
    
    try:
        enviar_ticket(venta.cliente_email, {
            "producto": venta.producto,
            "cantidad": venta.cantidad,
            "total": nueva_venta.total
        })
    except Exception as e:
        print("Error al enviar correo:", e)


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
    
    
    
@router.post("/ventas/{venta_id}/cancelar")
def cancelar_venta(
    venta_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    venta = db.query(models.Venta).filter_by(id=venta_id).first()

    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    if venta.cancelada:
        raise HTTPException(status_code=400, detail="La venta ya fue cancelada")

    # Permitir solo al admin o encargado del módulo
    if current_user.rol != models.RolEnum.admin:
        if current_user.rol != models.RolEnum.encargado or venta.modulo != current_user.modulo:
            raise HTTPException(status_code=403, detail="No tienes permisos para cancelar esta venta")

    # Reintegrar al inventario del módulo
    inventario = (
        db.query(models.InventarioModulo)
        .filter_by(modulo=venta.modulo, producto=venta.producto)
        .first()
    )

    if not inventario:
        # Si no existía el producto en inventario (muy raro pero posible)
        inventario = models.InventarioModulo(
            producto=venta.producto, cantidad=venta.cantidad, modulo=venta.modulo
        )
        db.add(inventario)
    else:
        inventario.cantidad += venta.cantidad

    # Marcar como cancelada
    venta.cancelada = True

    db.commit()

    return {"mensaje": f"Venta ID {venta_id} cancelada correctamente y producto reintegrado al inventario."}


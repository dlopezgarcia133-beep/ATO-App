from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido



router = APIRouter()

# CREAR COMISIÓN
@router.post("/comisiones", response_model=schemas.ComisionResponse)
def crear_comision(
    comision: schemas.ComisionCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

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
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

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
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

    com_db = db.query(models.Comision).filter_by(producto=producto).first()
    if not com_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    db.delete(com_db)
    db.commit()
    return {"mensaje": f"Comisión para producto '{producto}' eliminada"}



@router.get("/comisiones", response_model=list[schemas.ComisionCreate])
def obtener_comisiones(db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    
    return db.query(models.Comision).all()

@router.get("/comisiones/{producto}", response_model=schemas.ComisionCreate)
def obtener_comision_producto(producto: str, db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    comision = db.query(models.Comision).filter_by(producto=producto).first()
    if not comision:
        raise HTTPException(status_code=404, detail="No se encontró comisión para ese producto")
    return comision



@router.get("/ciclo_por_fechas", response_model=schemas.ComisionesCicloResponse)
def obtener_comisiones_por_fechas(
    inicio: date = Query(..., description="Fecha de inicio del ciclo (lunes)"),
    fin: date = Query(..., description="Fecha de fin del ciclo (domingo)"),
    empleado_id: int | None = Query(None, description="ID del empleado (solo admin)"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_current_user),
):
    # Si es admin y se proporcionó un empleado_id, obtener ese usuario
    if usuario_actual.rol == models.RolEnum.admin and empleado_id is not None:
        usuario = db.query(models.Usuario).filter(models.Usuario.id == empleado_id).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
    else:
        usuario = usuario_actual  # Si no es admin o no se envió empleado_id

    fecha_pago = fin + timedelta(days=3)

    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == usuario.id,
        models.VentaChip.validado == True,
        models.VentaChip.fecha >= inicio,
        models.VentaChip.fecha <= fin,
    ).all()

    ventas_accesorios = db.query(models.Venta).filter(
        models.Venta.empleado_id == usuario.id,
        models.Venta.fecha >= inicio,
        models.Venta.fecha <= fin,
    ).all()

    ventas_telefonos = db.query(models.VentaTelefono).filter(
        models.VentaTelefono.empleado_id == usuario.id,
        models.VentaTelefono.fecha >= inicio,
        models.VentaTelefono.fecha <= fin,
    ).all()

    if not ventas_accesorios and not ventas_telefonos and not ventas_chips:
        return {
            "inicio_ciclo": inicio,
            "fin_ciclo": fin,
            "fecha_pago": None,
            "total_chips": 0,
            "total_accesorios": 0,
            "total_telefonos": 0,
            "total_general": 0,
            "ventas_accesorios": [],
            "ventas_telefonos": [],
            "ventas_chips": []
        }

    accesorios = [
        {
            "producto": v.producto,
            "cantidad": v.cantidad,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha.strftime("%Y-%m-%d"),
            "hora": v.hora.strftime("%H:%M:%S")
        }
        for v in ventas_accesorios if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    telefonos = [
        {
            "marca": v.marca,
            "modelo": v.modelo,
            "tipo": v.tipo,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha.strftime("%Y-%m-%d"),
            "hora": v.hora.strftime("%H:%M:%S")
        }
        for v in ventas_telefonos if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    chips = [
        {
            "tipo_chip": v.tipo_chip,
            "numero": v.numero_telefono,
            "comision": v.comision or 0,
            "fecha": v.fecha.strftime("%Y-%m-%d"),
            "hora": v.hora.strftime("%H:%M:%S")
        }
        for v in ventas_chips if (v.comision or 0) > 0
    ]

    return {
        "inicio_ciclo": inicio,
        "fin_ciclo": fin,
        "fecha_pago": fecha_pago,
        "total_chips": sum(c["comision"] for c in chips),
        "total_accesorios": sum(a["comision"] for a in accesorios),
        "total_telefonos": sum(t["comision"] for t in telefonos),
        "total_general": sum(c["comision"] for c in chips) +
                         sum(a["comision"] for a in accesorios) +
                         sum(t["comision"] for t in telefonos),
        "ventas_accesorios": accesorios,
        "ventas_telefonos": telefonos,
        "ventas_chips": chips
    }



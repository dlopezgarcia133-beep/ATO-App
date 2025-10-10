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
    current_user: models.Usuario = Depends(get_current_user),
):
    
    empleado_id = current_user.id 

    fecha_pago = fin + timedelta(days=3)

    # 🔹 Obtener todas las ventas (accesorios y teléfonos)
    ventas = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha >= inicio,
        models.Venta.fecha <= fin,
        models.Venta.cancelada == False
    ).all()

    # 🔹 Obtener ventas de chips
    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_id,
        models.VentaChip.numero_telefono.isnot(None),
        models.VentaChip.validado == True,
        models.VentaChip.fecha >= inicio,
        models.VentaChip.fecha <= fin,
    ).all()

    if not ventas and not ventas_chips:
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

    # 🔹 Inicializar acumuladores
    accesorios = []
    telefonos = []
    chips = []

    total_accesorios = 0
    total_telefonos = 0
    total_chips = 0

    # 🔹 Comisiones extra para teléfonos según tipo de venta
    comisiones_por_tipo = {
        "Contado": 10,
        "Paguitos": 100,
        "Payoy": 110
    }

    # 🔹 Procesar ventas (accesorios y teléfonos)
    for v in ventas:
        comision_base = v.comision_obj.cantidad if v.comision_obj else 0
        comision_extra = comisiones_por_tipo.get(v.tipo_venta, 0)
        comision_total = comision_base * v.cantidad

        # 📱 Teléfonos
        if v.tipo_producto == "telefono":
            comision_total += comision_extra
            total_telefonos += comision_total

            telefonos.append({
                "producto": v.producto,
                "cantidad": v.cantidad,
                "comision_total": comision_total,
                "tipo_venta": v.tipo_venta,
                "fecha": v.fecha.strftime("%Y-%m-%d"),
                "hora": v.hora.strftime("%H:%M:%S")
            })

        # 🎧 Accesorios
        elif v.tipo_producto == "accesorio":
            total_accesorios += comision_total

            accesorios.append({
                "producto": v.producto,
                "cantidad": v.cantidad,
                "comision": comision_base,
                "tipo_venta": v.tipo_venta,
                "comision_total": comision_total,
                "fecha": v.fecha.strftime("%Y-%m-%d"),
                "hora": v.hora.strftime("%H:%M:%S")
            })

    # 🔹 Procesar chips
    for v in ventas_chips:
        comision_total = v.comision or 0
        total_chips += comision_total

        chips.append({
            "tipo_chip": v.tipo_chip,
            "numero_telefono": v.numero_telefono,
            "comision": v.comision or 0,
            "comision_manual": 0,
            "fecha": v.fecha.strftime("%Y-%m-%d"),
            "hora": v.hora.strftime("%H:%M:%S")
        })

    # 🔹 Totales generales
    total_general = total_accesorios + total_telefonos + total_chips

    return {
        "inicio_ciclo": inicio,
        "fin_ciclo": fin,
        "fecha_pago": fecha_pago,
        "total_chips": total_chips,
        "total_accesorios": total_accesorios,
        "total_telefonos": total_telefonos,
        "total_general": total_general,
        "ventas_accesorios": accesorios,
        "ventas_telefonos": telefonos,
        "ventas_chips": chips
    }





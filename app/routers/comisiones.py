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


from sqlalchemy import func

@router.get("/ciclo_por_fechas", response_model=schemas.ComisionesCicloResponse)
def obtener_comisiones_por_fechas(
    inicio: date = Query(..., description="Fecha de inicio del ciclo (lunes)"),
    fin: date = Query(..., description="Fecha de fin del ciclo (domingo)"),
    empleado_id: int | None = Query(None, description="ID del empleado (solo admin)"),
    db: Session = Depends(get_db),
    usuario_actual: models.Usuario = Depends(get_current_user),
):
    # Si vino empleado_id (admin), usarlo; si no, usar el id del usuario autenticado
    empleado_a_consultar = empleado_id if empleado_id is not None else usuario_actual.id

    fecha_pago = fin + timedelta(days=3)

    # 🔹 Obtener todas las ventas (accesorios y teléfonos)
    ventas = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_a_consultar,
        func.date(models.Venta.fecha) >= inicio,  # comparar solo fecha
        func.date(models.Venta.fecha) <= fin,
        models.Venta.cancelada == False
    ).all()

    # 🔹 Obtener ventas de chips
    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_a_consultar,
        models.VentaChip.numero_telefono.isnot(None),
        models.VentaChip.validado == True,
        func.date(models.VentaChip.fecha) >= inicio,
        func.date(models.VentaChip.fecha) <= fin,
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

    total_accesorios = 0.0
    total_telefonos = 0.0
    total_chips = 0.0

    # 🔹 Comisiones extra para teléfonos según tipo de venta
    comisiones_por_tipo = {
        "Contado": 10,
        "Paguitos": 110,
        "Pajoy": 100
    }

    # 🔹 Procesar ventas (accesorios y teléfonos)
    for v in ventas:
        # Leer de forma segura
        comision_base = getattr(getattr(v, "comision_obj", None), "cantidad", 0) or 0
        comision_extra = comisiones_por_tipo.get(getattr(v, "tipo_venta", "") or "", 0)
        cantidad = getattr(v, "cantidad", 0) or 0

        # Comision base total (unitaria * cantidad)
        comision_total = comision_base * cantidad

        # 📱 Teléfonos
        if getattr(v, "tipo_producto", "") == "telefono":
            # aplicar extra siempre para telefono
            comision_total += comision_extra
            total_telefonos += comision_total

            # Asegurarnos de entregar los tipos que espera el schema:
            # VentaTelefonoConComision: producto:str, cantidad:int, tipo_venta:str, comision_total:float, fecha:date, hora:time
            telefonos.append({
                "producto": getattr(v, "producto", ""),
                "cantidad": int(cantidad),
                "comision_total": float(comision_total),
                "tipo_venta": getattr(v, "tipo_venta", "") or "",  # obligatorio en schema, entregar string
                "fecha": getattr(v, "fecha"),  # entregar date (no str)
                "hora": getattr(v, "hora")     # entregar time (no str)
            })

        # 🎧 Accesorios
        elif getattr(v, "tipo_producto", "") == "accesorio":
            total_accesorios += comision_total

            accesorios.append({
                "producto": getattr(v, "producto", ""),
                "cantidad": int(cantidad),
                "comision": float(comision_base),
                "tipo_venta": getattr(v, "tipo_venta", None),
                "comision_total": float(comision_total),
                "fecha": getattr(v, "fecha"),
                "hora": getattr(v, "hora")
            })

    # 🔹 Procesar chips
    for v in ventas_chips:
        comision_val = getattr(v, "comision", 0) or 0
        total_chips += float(comision_val)

        # Atención: el schema VentaChipConComision NO incluye comision_manual
        # así que no lo añadimos aquí para evitar errores de validación.
        chips.append({
            "tipo_chip": getattr(v, "tipo_chip", ""),
            "numero_telefono": getattr(v, "numero_telefono", ""),
            "comision": float(comision_val),
            "fecha": getattr(v, "fecha"),
            "hora": getattr(v, "hora")
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




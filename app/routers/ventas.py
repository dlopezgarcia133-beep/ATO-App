
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.utilidades import enviar_ticket, verificar_rol_requerido
from datetime import date


router = APIRouter()


zona_horaria = ZoneInfo("America/Mexico_City")


@router.post("/ventas", response_model=List[schemas.VentaResponse])
def crear_ventas(
    venta: schemas.VentaMultipleCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ventas_realizadas = []

    for item in venta.productos:
        # Buscar comisión por producto (si aplica)
        com = (
            db.query(models.Comision)
            .filter(func.lower(models.Comision.producto) == item.producto.strip().lower())
            .first()
        )
        comision_id = com.id if com else None
        modulo_id = current_user.modulo_id

        # 🔎 Buscar en inventario unificado
        inventario = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.modulo_id == modulo_id,
                models.InventarioModulo.producto == item.producto,
                models.InventarioModulo.tipo_producto == item.tipo_producto
            )
            .first()
        )

        if not inventario:
            raise HTTPException(
                status_code=400,
                detail=f"No hay inventario para el producto: {item.producto}"
            )

        if inventario.cantidad < item.cantidad:
            raise HTTPException(
                status_code=400,
                detail=f"Inventario insuficiente para el producto: {item.producto}"
            )

        # Actualizar inventario
        inventario.cantidad -= item.cantidad

        fecha_actual = datetime.now(zona_horaria)
        tipo_producto = "telefono" if item.producto.strip().upper().startswith("TELEFONO") else "accesorio"

        nueva = models.Venta(
    empleado_id=current_user.id,
    modulo_id=modulo_id,
    producto=item.producto,
    cantidad=item.cantidad,
    precio_unitario=item.precio_unitario,
    tipo_producto=tipo_producto,  
    tipo_venta=item.tipo_venta,
    metodo_pago=venta.metodo_pago,
    cancelada=False,
    comision_id=comision_id,
    fecha=fecha_actual.date(),
    hora=fecha_actual.time(),
    correo_cliente=venta.correo_cliente,
)

        db.add(nueva)
        ventas_realizadas.append(nueva)

    db.commit()
    for v in ventas_realizadas:
        db.refresh(v)

    return [
        schemas.VentaResponse(
            id=v.id,
            empleado=schemas.UsuarioResponse.from_orm(v.empleado) if v.empleado else None,
            modulo=v.modulo,
            producto=v.producto,
            cantidad=v.cantidad,
            precio_unitario=v.precio_unitario,
            metodo_pago=v.metodo_pago, 
            
            total=v.precio_unitario * v.cantidad,
            comision=db.query(models.Comision).filter_by(id=v.comision_id).first().cantidad if v.comision_id else None,
            fecha=v.fecha,
            hora=v.hora,
            cancelada=v.cancelada
        )
        for v in ventas_realizadas
    ]



# ------------------- VENTAS -------------------
# @router.post("/ventas", response_model=schemas.VentaResponse)
# def crear_venta(venta: schemas.VentaCreate, db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    
#     com = (
#         db.query(models.Comision)
#           .filter(func.lower(models.Comision.producto) == venta.producto.strip().lower())
#           .first()
#     )
#     comision = com.cantidad if com else None

    
#     total = venta.precio_unitario * venta.cantidad

#     modulo = current_user.modulo
    
    
#     inventario = (
#         db.query(models.InventarioModulo)
#         .filter_by(modulo=modulo, producto=venta.producto)
#         .first()
#     )

#     if not inventario:
#         raise HTTPException(status_code=404, detail="Producto no registrado en el inventario del módulo")

#     if inventario.cantidad < venta.cantidad:
#         raise HTTPException(status_code=400, detail="Inventario insuficiente para esta venta")

#     fecha_actual = datetime.now(zona_horaria)
#     inventario.cantidad -= venta.cantidad
    
#     # 3. Crear la venta
#     nueva_venta = models.Venta(
#         empleado_id=current_user.id,
#         modulo=modulo,
#         producto=venta.producto,
#         cantidad=venta.cantidad,
#         precio_unitario=venta.precio_unitario,
#         total = venta.precio_unitario * venta.cantidad,
#         comision=comision,
#         fecha=fecha_actual.date(),
#         hora=fecha_actual.time(),
#         correo_cliente=venta.correo_cliente
#     )
#     # Si dejaste el campo total en el modelo, descomenta esta línea:
#     # nueva_venta.total = total

#     db.add(nueva_venta)
#     db.commit()
#     db.refresh(nueva_venta)
    
    
#     try:
#         enviar_ticket(venta.correo_cliente, {
#             "producto": venta.producto,
#             "cantidad": venta.cantidad,
#             "total": nueva_venta.total
#         })
#     except Exception as e:
#         print("Error al enviar correo:", e)


#     respuesta = schemas.VentaResponse.from_orm(nueva_venta)
#     respuesta.total = total        
#     return respuesta

    


from datetime import date

from datetime import datetime, date

@router.get("/ventas", response_model=list[schemas.VentaResponse])
def obtener_ventas(
    fecha: date = None,
    modulo_id: int = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)  # quien hizo login
):
    hoy = date.today()
    fecha_consulta = fecha or hoy

    query = (
        db.query(models.Venta)
        .options(joinedload(models.Venta.empleado))
        .filter(models.Venta.fecha == fecha_consulta)
    )

    # 🔒 Si no es admin, solo puede ver su propio módulo
    if not current_user.is_admin:
        query = query.filter(models.Venta.modulo_id == current_user.modulo_id)
    else:
        # si es admin y mandó modulo_id → filtrar
        if modulo_id is not None:
            query = query.filter(models.Venta.modulo_id == modulo_id)

    ventas = query.all()

    resultados = []
    for v in ventas:
        item = schemas.VentaResponse.from_orm(v)
        item.total = v.precio_unitario * v.cantidad
        print("Debug venta:", item.dict())
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
    
    
    

@router.put("/ventas/{venta_id}/cancelar", response_model=schemas.VentaResponse)
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

    if current_user.rol != models.RolEnum.admin:
        if current_user.rol != models.RolEnum.encargado or venta.modulo != current_user.modulo:
            raise HTTPException(status_code=403, detail="No tienes permisos para cancelar esta venta")

    # Reintegrar inventario
        inventario = (
    db.query(models.InventarioModulo)
    .filter(
        models.InventarioModulo.producto == venta.producto,
        models.InventarioModulo.modulo_id == venta.modulo_id
    )
    .first()
)
        if not inventario:
            inventario = models.InventarioModulo(
                producto=venta.producto, cantidad=venta.cantidad, modulo=venta.modulo
            )
            db.add(inventario)
        else:
            inventario.cantidad += venta.cantidad

        venta.cancelada = True
        db.commit()
        return {"mensaje": f"Venta ID {venta_id} cancelada correctamente y producto reintegrado al inventario."}

    # 2. Buscar en VentaTelefono
    venta_tel = db.query(models.VentaTelefono).filter_by(id=venta_id).first()
    if venta_tel:
        if venta_tel.cancelada:
            raise HTTPException(status_code=400, detail="La venta ya fue cancelada")

        if current_user.rol != models.RolEnum.admin:
            if current_user.rol != models.RolEnum.encargado or venta_tel.modulo != current_user.modulo:
                raise HTTPException(status_code=403, detail="No tienes permisos para cancelar esta venta")

        # Reintegrar teléfono al inventario
        inventario_tel = db.query(models.InventarioTelefono).filter_by(
            modulo=venta_tel.modulo_id,
            marca=venta_tel.marca,
            modelo=venta_tel.modelo
        ).first()

        if not inventario_tel:
            inventario_tel = models.InventarioTelefono(
                marca=venta_tel.marca,
                modelo=venta_tel.modelo,
                cantidad=1,
                modulo=venta_tel.modulo
            )
            db.add(inventario_tel)
        else:
            inventario_tel.cantidad += 1

        venta_tel.cancelada = True

    venta.cancelada = True
    db.commit()
    db.refresh(venta)   # 🔥 refresca la instancia para devolver la versión actualizada
    return venta
    




@router.post("/ventas/multiples", response_model=List[schemas.VentaResponse])
def crear_ventas_multiples(
    venta: schemas.VentaMultipleCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ventas_realizadas = []

    for item in venta.productos:
        com = (
            db.query(models.Comision)
            .filter(func.lower(models.Comision.producto) == item.producto.strip().lower())
            .first()
        )
        comision_id = com.id if com else None
        modulo_id = current_user.modulo.id

        inventario = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.modulo_id == modulo_id,
                models.InventarioModulo.producto == item.producto
            )
            .first()
        )

        if not inventario:
            raise HTTPException(
                status_code=400,
                detail=f"No hay inventario para el producto: {item.producto}"
            )

        if inventario.cantidad < item.cantidad:
            raise HTTPException(
                status_code=400,
                detail=f"Inventario insuficiente para el producto: {item.producto}"
            )
        fecha_actual = datetime.now(zona_horaria)
        inventario.cantidad -= item.cantidad

        tipo_producto = "telefono" if item.producto.strip().upper().startswith("TELEFONO") else "accesorio"

        nueva = models.Venta(
    empleado_id=current_user.id,
    modulo_id=modulo_id,
    producto=item.producto,
    cantidad=item.cantidad,
    precio_unitario=item.precio_unitario,
    total=item.cantidad * item.precio_unitario,
    metodo_pago=venta.metodo_pago,
    comision_id=comision_id,
    tipo_producto=tipo_producto,   
    hora=fecha_actual.time(),
    correo_cliente=venta.correo_cliente,
)

        db.add(nueva)
        ventas_realizadas.append(nueva)

    db.commit()
    for v in ventas_realizadas:
        db.refresh(v)

    # Conversión manual segura
    return [
        schemas.VentaResponse(
            id=v.id,
            empleado=schemas.UsuarioResponse.from_orm(v.empleado) if v.empleado else None,
            modulo=v.modulo,
            producto=v.producto,
            cantidad=v.cantidad,
            precio_unitario=v.precio_unitario,
            metodo_pago=v.metodo_pago,
            total=v.precio_unitario * v.cantidad,
            comision=db.query(models.Comision).filter_by(id=v.comision_id).first().cantidad if v.comision_id else None,
            fecha=v.fecha,
            hora=v.hora,
            cancelada=v.cancelada
        )
        for v in ventas_realizadas
    ]



@router.post("/venta_chips", response_model=schemas.VentaChipResponse)
def crear_venta_chip(
    venta: schemas.VentaChipCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    fecha_actual = datetime.now(zona_horaria)
    nueva_venta = models.VentaChip(
        empleado_id=current_user.id,
        tipo_chip=venta.tipo_chip,
        numero_telefono=venta.numero_telefono,
        monto_recarga=venta.monto_recarga,
        fecha=fecha_actual.date(),
        hora=fecha_actual.time(),
    )

    db.add(nueva_venta)
    db.commit()
    db.refresh(nueva_venta)
    return nueva_venta



@router.get("/venta_chips", response_model=list[schemas.VentaChipResponse])
def obtener_ventas_chips(
    empleado_id: Optional[int] = None, 
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    if current_user.rol == "admin":
        query = db.query(models.VentaChip)
        if empleado_id is not None:
            query = query.filter(models.VentaChip.empleado_id == empleado_id)
        return query.all()
    else:
        return db.query(models.VentaChip).filter(models.VentaChip.empleado_id == current_user.id).all()


@router.put("/venta_chips/{id}/validar", response_model=schemas.VentaChipResponse)
def validar_chip(
    id: int,
    data: schemas.ComisionInput = Body(...),
    db: Session = Depends(get_db)
):
    chip = db.query(models.VentaChip).filter(models.VentaChip.id == id).first()
    if not chip:
        raise HTTPException(status_code=404, detail="Venta de chip no encontrada")

    if chip.validado:
        raise HTTPException(status_code=400, detail="Ya ha sido validado")

    tipo = chip.tipo_chip
    monto = int(chip.monto_recarga)

    if tipo == "Activacion":
        if data.comision_manual is None:
            raise HTTPException(status_code=400, detail="Debe proporcionar una comisión para chip Activacion")
        chip.comision = data.comision_manual
    else:
        # Comisiones usando rangos (min, max)
        comisiones_por_chip = {
            "Chip Azul": [
                ((0, 49), 5),
                ((50, 99), 10),
                ((100, 1000), 15)
            ],
            "Chip ATO": [
                ((0, 50), 5),
                ((51, 100), 10),
                ((101, 150), 15)
            ],
            "Portabilidad": [
                ((0, 500), 50),
                
            ],
            "Chip Cero/Libre": [
                ((0, 500), 25),
                
            ],
            "Chip Preactivado": [
                ((0, 500), 35),
                
            ]
        }

        if tipo not in comisiones_por_chip:
            raise HTTPException(status_code=404, detail="No hay comisión configurada para este tipo de chip")

        comision_asignada = None
        for (min_monto, max_monto), comision in comisiones_por_chip[tipo]:
            if min_monto <= monto <= max_monto:
                comision_asignada = comision
                break

        if comision_asignada is None:
            raise HTTPException(status_code=404, detail="Monto de recarga fuera de rango para este tipo de chip")

        chip.comision = comision_asignada

    chip.validado = True

    db.commit()
    db.refresh(chip)

    return chip



@router.put("/ventas/{id}/comision_tipo", response_model=schemas.VentaResponse)
def agregar_comision_por_tipo_venta(
    id: int,
    db: Session = Depends(get_db)
):
    venta = db.query(models.Venta).filter(models.Venta.id == id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    # Configuración de comisiones fijas por tipo de venta
    comisiones_por_tipo = {
        "Contado": 10, 
        "Pajoy": 100,  
        "Paguitos": 110
             
    }

    tipo_venta = venta.tipo_venta


    if venta.comision_id is not None:
        venta.comision_id += comisiones_por_tipo.get(tipo_venta, 0)


    db.commit()
    db.refresh(venta)

    return venta





@router.put("/venta_chips/{venta_id}/motivo_rechazo")
def motivo_rechazo_chip(
    venta_id: int,
    descripcion: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    venta = db.query(models.VentaChip).filter_by(id=venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    
    venta.descripcion_rechazo = descripcion
    db.commit()
    return {"mensaje": "Motivo de rechazo registrado"}

@router.get("/ventas/chips_rechazados", response_model=List[schemas.VentaChipResponse])
def obtener_chips_rechazados(
    empleado_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.VentaChip).filter(
        models.VentaChip.descripcion_rechazo.isnot(None),
        models.VentaChip.validado == False
    )
    if empleado_id is not None:
        query = query.filter(models.VentaChip.empleado_id == empleado_id)

    return query.all()

@router.put("/revertir_rechazo/{chip_id}", response_model=schemas.VentaChipResponse)
def revertir_rechazo(chip_id: int, db: Session = Depends(get_db)):
    chip = db.query(models.VentaChip).filter(models.VentaChip.id == chip_id).first()
    if not chip:
        raise HTTPException(status_code=404, detail="Chip no encontrado")

    chip.descripcion_rechazo = None
    db.commit()
    db.refresh(chip)
    return chip

@router.delete("/eliminar_chip/{chip_id}", status_code=status.HTTP_200_OK)
def eliminar_chip(chip_id: int, db: Session = Depends(get_db)):
    chip = db.query(models.VentaChip).filter(models.VentaChip.id == chip_id).first()
    if not chip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chip no encontrado"
        )
    
    db.delete(chip)
    db.commit()
    return {"message": f"Chip con id {chip_id} eliminado correctamente"}






@router.put("/venta_telefonos/{venta_id}/cancelar")
def cancelar_venta_telefono(
    venta_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    venta = db.query(models.VentaTelefono).filter_by(id=venta_id).first()

    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    if venta.cancelada:
        raise HTTPException(status_code=400, detail="La venta ya está cancelada")

    # Buscar el inventario del módulo del vendedor
    empleado = db.query(models.Usuario).filter_by(id=venta.empleado_id).first()
    if not empleado or not empleado.modulo_id:
        raise HTTPException(status_code=400, detail="El vendedor no tiene módulo asignado")

    inventario = db.query(models.InventarioTelefono).filter_by(
        marca=venta.marca,
        modelo=venta.modelo,
        modulo_id=empleado.modulo_id
    ).first()

    if not inventario:
        raise HTTPException(status_code=404, detail="Inventario de teléfono no encontrado")

    # Revertir cancelación
    inventario.cantidad += 1
    venta.cancelada = True

    db.commit()

    return {"mensaje": "Venta cancelada y stock restaurado"}



@router.get("/ventas_telefonos", response_model=List[schemas.VentaTelefonoResponse])
def obtener_ventas_telefonos(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # Solo mostrar ventas del módulo del usuario (si aplica)
    ventas = (
        db.query(models.VentaTelefono)
        .filter(models.VentaTelefono.empleado.has(modulo_id=current_user.modulo_id))
        .order_by(models.VentaTelefono.fecha.desc(), models.VentaTelefono.hora.desc())
        .all()
    )
    return ventas



@router.get("/corte-general")
def corte_general(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    hoy = date.today()

    # 🔹 Obtiene todas las ventas del día del módulo actual
    ventas = db.query(models.Venta).filter(
        func.date(models.Venta.fecha) == hoy,
        models.Venta.modulo_id == current_user.modulo_id
    ).all()

    # 🔹 Separa accesorios y teléfonos usando tipo_producto
    ventas_productos = [v for v in ventas if v.tipo_producto == "accesorio"]
    ventas_telefonos = [v for v in ventas if v.tipo_producto == "telefono"]

    # Totales productos (solo ventas activas)
    efectivo_productos = sum(v.total for v in ventas_productos if v.metodo_pago == "efectivo" and not v.cancelada)
    tarjeta_productos = sum(v.total for v in ventas_productos if v.metodo_pago == "tarjeta" and not v.cancelada)

    # Totales teléfonos (solo ventas activas)
    efectivo_tel = sum(v.precio_unitario for v in ventas_telefonos if v.metodo_pago == "efectivo" and not v.cancelada)
    tarjeta_tel = sum(v.precio_unitario for v in ventas_telefonos if v.metodo_pago == "tarjeta" and not v.cancelada)

    # Totales generales
    total_efectivo = efectivo_productos + efectivo_tel
    total_tarjeta = tarjeta_productos + tarjeta_tel
    total_sistema = total_efectivo + total_tarjeta
    total_general = total_efectivo + total_tarjeta

    return {
        "ventas_telefonos": {
            "efectivo": round(efectivo_tel, 2),
            "tarjeta": round(tarjeta_tel, 2)
        },
        "ventas_productos": {
            "efectivo": round(efectivo_productos, 2),
            "tarjeta": round(tarjeta_productos, 2)
        },
        "total_sistema": round(total_sistema, 2),
        "totales": {
            "efectivo": round(total_efectivo, 2),
            "tarjeta": round(total_tarjeta, 2),
            "sistema": round(total_sistema, 2),
            "general": round(total_general, 2)
        }
    }



@router.get("/ventas/cortes")
def obtener_cortes(
    fecha: date = Query(None),
    modulo_id: int = Query(None),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(models.CorteDia)

    if fecha:
        query = query.filter(models.CorteDia.fecha == fecha)
    if modulo_id:
        query = query.filter(models.CorteDia.modulo_id == modulo_id)

    cortes = query.order_by(models.CorteDia.fecha.desc()).all()

    cortes_completos = []

    for corte in cortes:
        # 🔍 Obtener ventas por fecha y módulo, y que no estén canceladas
        ventas = db.query(models.Venta).filter(
            func.date(models.Venta.fecha) == corte.fecha,
            models.Venta.modulo_id == corte.modulo_id,
            models.Venta.cancelada == False
        ).all()

        # 🔄 Convertir a dict y agregar las ventas
        cortes_completos.append({
            "fecha": corte.fecha,
            "total_efectivo": corte.total_efectivo,
            "total_tarjeta": corte.total_tarjeta,
            "adicional_recargas": corte.adicional_recargas,
            "adicional_transporte": corte.adicional_transporte,
            "adicional_otros": corte.adicional_otros,
            "total_sistema": corte.total_sistema,
            "total_general": corte.total_general,
            "modulo_id": corte.modulo_id,
            "accesorios_efectivo": corte.accesorios_efectivo,
            "accesorios_tarjeta": corte.accesorios_tarjeta,
            "accesorios_total": corte.accesorios_total,
            "telefonos_efectivo": corte.telefonos_efectivo,
            "telefonos_tarjeta": corte.telefonos_tarjeta,
            "telefonos_total": corte.telefonos_total,

            # 👇 Aquí incluyes las ventas (ya sea accesorio o teléfono)
            "ventas": [
                {
                    "id": v.id,
                    "producto": v.producto,
                    "tipo_producto": v.tipo_producto,
                    "tipo_venta": v.tipo_venta,
                    "precio_unitario": v.precio_unitario,
                    "cantidad": v.cantidad,
                    "total": v.total,
                    "fecha": v.fecha,
                   
                }
                for v in ventas
            ]
        })

    return cortes_completos



    
@router.post("/cortes")
def crear_corte(
    corte_data: schemas.CorteDiaCreate,
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.rol != "encargado":
        raise HTTPException(status_code=403, detail="Solo los encargados pueden hacer cortes")
    
    if not user.modulo_id:
        raise HTTPException(status_code=400, detail="El encargado no tiene un módulo asignado")

    nuevo_corte = models.CorteDia(
        fecha=date.today(),
        modulo_id=user.modulo_id,
        # Accesorios
        accesorios_efectivo=corte_data.accesorios_efectivo,
        accesorios_tarjeta=corte_data.accesorios_tarjeta,
        accesorios_total=corte_data.accesorios_total,
        # Teléfonos
        telefonos_efectivo=corte_data.telefonos_efectivo,
        telefonos_tarjeta=corte_data.telefonos_tarjeta,
        telefonos_total=corte_data.telefonos_total,
        # Totales
        total_efectivo=corte_data.total_efectivo,
        total_tarjeta=corte_data.total_tarjeta,
        total_sistema=corte_data.total_sistema,
        total_general=corte_data.total_general,
        # Adicionales
        adicional_recargas=corte_data.adicional_recargas,
        adicional_transporte=corte_data.adicional_transporte,
        adicional_otros=corte_data.adicional_otros,
    )

    db.add(nuevo_corte)
    db.commit()
    db.refresh(nuevo_corte)
    return nuevo_corte



    
    
@router.get("/comisiones/ciclo", response_model=schemas.ComisionesCicloResponse)
def obtener_comisiones_ciclo(
    empleado_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(get_current_user)
):
    hoy = date.today()
    dias_desde_lunes = hoy.weekday()
    inicio_ciclo = hoy - timedelta(days=dias_desde_lunes)
    fin_ciclo = inicio_ciclo + timedelta(days=6)
    fecha_pago = fin_ciclo + timedelta(days=3)

    # Validar si puede consultar a otros
    if empleado_id is None:
        empleado_id = usuario.id
    elif usuario.rol != "admin" and usuario.rol != "encargado":
        raise HTTPException(status_code=403, detail="No tienes permiso para ver comisiones de otros usuarios")

    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_id,
        models.VentaChip.validado == True,
        models.VentaChip.fecha >= inicio_ciclo,
        models.VentaChip.fecha <= fin_ciclo,
    ).all()

    ventas_accesorios = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha >= inicio_ciclo,
        models.Venta.fecha <= fin_ciclo,
        models.Venta.cancelada == False,
    ).all()

    ventas_telefonos = db.query(models.Venta).filter(
        models.VentaTelefono.empleado_id == empleado_id,
        models.VentaTelefono.fecha >= inicio_ciclo,
        models.VentaTelefono.fecha <= fin_ciclo,
        models.Venta.cancelada == False,
    ).all()

    accesorios = [
        {
            "producto": v.producto,
            "cantidad": v.cantidad,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_accesorios if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    telefonos = [
        {
            "marca": v.marca,
            "modelo": v.modelo,
            "tipo": v.tipo,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_telefonos if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    chips = [
        {
            "tipo_chip": v.tipo_chip,
            "numero_telefono": v.numero_telefono,
            "comision": v.comision or 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_chips if (v.comision or 0) > 0
    ]

    total_accesorios = sum(v["comision"] for v in accesorios)
    total_telefonos = sum(v["comision"] for v in telefonos)
    total_chips = sum(v["comision"] for v in chips)

    return {
        "inicio_ciclo": inicio_ciclo,
        "fin_ciclo": fin_ciclo,
        "fecha_pago": fecha_pago,
        "total_chips": total_chips,
        "total_accesorios": total_accesorios,
        "total_telefonos": total_telefonos,
        "total_general": total_chips + total_accesorios + total_telefonos,
        "ventas_accesorios": accesorios,
        "ventas_telefonos": telefonos,
        "ventas_chips": chips
    }


@router.get("/comisiones/ciclo/{empleado_id}", response_model=schemas.ComisionesCicloResponse)
def obtener_comisiones_ciclo_admin(
    empleado_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    hoy = date.today()
    dias_desde_lunes = hoy.weekday()
    inicio_ciclo = hoy - timedelta(days=dias_desde_lunes)
    fin_ciclo = inicio_ciclo + timedelta(days=6)
    fecha_pago = fin_ciclo + timedelta(days=3)

    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_id,
        models.VentaChip.validado == True,
        models.VentaChip.fecha >= inicio_ciclo,
        models.VentaChip.fecha <= fin_ciclo,
    ).all()

    ventas_accesorios = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha >= inicio_ciclo,
        models.Venta.fecha <= fin_ciclo,
    ).all()

    ventas_telefonos = db.query(models.VentaTelefono).filter(
        models.VentaTelefono.empleado_id == empleado_id,
        models.VentaTelefono.fecha >= inicio_ciclo,
        models.VentaTelefono.fecha <= fin_ciclo,
    ).all()

    accesorios = [
        {
            "producto": v.producto,
            "cantidad": v.cantidad,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_accesorios if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    telefonos = [
        {
            "marca": v.marca,
            "modelo": v.modelo,
            "tipo": v.tipo,
            "comision": v.comision_obj.cantidad if v.comision_obj else 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_telefonos if v.comision_obj and v.comision_obj.cantidad > 0
    ]

    chips = [
        {
            "tipo_chip": v.tipo_chip,
            "numero_telefono": v.numero_telefono,
            "comision": v.comision or 0,
            "fecha": v.fecha,
            "hora": v.hora
        }
        for v in ventas_chips if (v.comision or 0) > 0
    ]

    total_accesorios = sum(v["comision"] for v in accesorios)
    total_telefonos = sum(v["comision"] for v in telefonos)
    total_chips = sum(v["comision"] for v in chips)

    return {
        "inicio_ciclo": inicio_ciclo,
        "fin_ciclo": fin_ciclo,
        "fecha_pago": fecha_pago,
        "total_chips": total_chips,
        "total_accesorios": total_accesorios,
        "total_telefonos": total_telefonos,
        "total_general": total_chips + total_accesorios + total_telefonos,
        "ventas_accesorios": accesorios,
        "ventas_telefonos": telefonos,
        "ventas_chips": chips
    }

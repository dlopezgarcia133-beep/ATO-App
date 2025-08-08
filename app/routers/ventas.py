
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.utilidades import enviar_ticket, verificar_rol_requerido


router = APIRouter()


zona_horaria = ZoneInfo("America/Mexico_City")

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

    fecha_actual = datetime.now(zona_horaria)
    inventario.cantidad -= venta.cantidad
    
    # 3. Crear la venta
    nueva_venta = models.Venta(
        empleado_id=current_user.id,
        modulo=modulo,
        producto=venta.producto,
        cantidad=venta.cantidad,
        precio_unitario=venta.precio_unitario,
        comision=comision,
        fecha=fecha_actual.date(),
        hora=fecha_actual.time(),
        correo_cliente=venta.correo_cliente
    )
    # Si dejaste el campo total en el modelo, descomenta esta línea:
    # nueva_venta.total = total

    db.add(nueva_venta)
    db.commit()
    db.refresh(nueva_venta)
    
    
    try:
        enviar_ticket(venta.correo_cliente, {
            "producto": venta.producto,
            "cantidad": venta.cantidad,
            "total": nueva_venta.total
        })
    except Exception as e:
        print("Error al enviar correo:", e)


    respuesta = schemas.VentaResponse.from_orm(nueva_venta)
    respuesta.total = total        
    return respuesta

    


from datetime import date

@router.get("/ventas", response_model=list[schemas.VentaResponse])
def obtener_ventas(
    modulo_id: int = None,
    db: Session = Depends(get_db)
):
    hoy = date.today()

    query = db.query(models.Venta).filter(models.Venta.fecha == hoy)

    if modulo_id is not None:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    ventas = query.all()

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
    
    
    
@router.put("/ventas/{venta_id}/cancelar")
def cancelar_venta(
    venta_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    # 1. Buscar en Venta (accesorios)
    venta = db.query(models.Venta).filter_by(id=venta_id).first()
    if venta:
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
        db.commit()
        return {"mensaje": f"Venta de teléfono ID {venta_id} cancelada correctamente y equipo reintegrado al inventario."}
    

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

        nueva = models.Venta(
            empleado_id=current_user.id,
            modulo_id=modulo_id,
            producto=item.producto,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            metodo_pago=venta.metodo_pago,
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

    # Conversión manual segura
    return [
        schemas.VentaResponse(
            id=v.id,
            empleado=schemas.UsuarioResponse.from_orm(v.empleado) if v.empleado else None,
            modulo=v.modulo,
            producto=v.producto,
            cantidad=v.cantidad,
            precio_unitario=v.precio_unitario,
            total=v.precio_unitario * v.cantidad,
            comision=db.query(models.Comision).filter_by(id=v.comision_id).first().cantidad if v.comision_id else None,
            fecha=v.fecha,
            hora=v.hora,
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
    empleado_id: Optional[int] = None,  # <- nuevo parámetro
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
        # Diccionario de comisiones según tipo_chip y monto_recarga
        comisiones_por_chip = {
            "Chip Azul": {50: 5, 
                          100: 10, 
                          150: 15},
            "Chip ATO": {50: 5, 
                         100: 10, 
                         150: 15},
            "Portabilidad": {50: 50, 
                             100: 50, 
                             150: 50},
            "Chip Cero": {50: 50, 
                          100: 50, 
                          150: 50},
            "Chip Preactivado": {50: 25, 
                                 100: 35, 
                                 150: 40},
            "Activacion": {50: 50, 
                           100: 50, 
                           150: 50},  
        }

        if tipo not in comisiones_por_chip or monto not in comisiones_por_chip[tipo]:
            raise HTTPException(status_code=404, detail="No hay comisión configurada para este tipo de chip y monto")
        
        chip.comision = comisiones_por_chip[tipo][monto]

    chip.validado = True

    db.commit()
    db.refresh(chip)

    return chip





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
def obtener_chips_rechazados(db: Session = Depends(get_db)):
    return db.query(models.VentaChip).filter(
        models.VentaChip.descripcion_rechazo.isnot(None),
        models.VentaChip.validado == False
    ).all()


@router.post("/venta_telefonos")
def vender_telefono(
    venta: schemas.VentaTelefonoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # 1. Obtener el módulo al que pertenece el usuario
    if not current_user.modulo_id:
        raise HTTPException(status_code=400, detail="El usuario no tiene un módulo asignado")

    # 2. Buscar el teléfono en el inventario de su módulo
    telefono = db.query(models.InventarioTelefono).filter_by(
        marca=venta.marca.strip().upper(),
        modelo=venta.modelo.strip().upper(),
        modulo_id=current_user.modulo_id
    ).first()

    if not telefono:
        raise HTTPException(status_code=404, detail="Teléfono no encontrado en inventario del módulo")

    if telefono.cantidad < 1:
        raise HTTPException(status_code=400, detail="No hay stock disponible para este teléfono")

    fecha_actual = datetime.now(zona_horaria)
    nueva_venta = models.VentaTelefono(
        empleado_id=current_user.id,
        marca=venta.marca.strip().upper(),
        modelo=venta.modelo.strip().upper(),
        tipo=venta.tipo,
        precio_venta=venta.precio_venta,
        metodo_pago=venta.metodo_pago,
        fecha=fecha_actual.today(),
        hora=fecha_actual.time()
    )

  
    telefono.cantidad -= 1

    db.add(nueva_venta)
    db.commit()

    return {"mensaje": "Venta registrada y stock actualizado"}



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

    # Ventas normales
    ventas = db.query(models.Venta).filter(
        models.Venta.fecha == hoy,
        models.Venta.cancelada == False
    ).all()

    total_productos = sum(v.total for v in ventas)
    efectivo = sum(v.total for v in ventas if v.metodo_pago == "efectivo")
    tarjeta = sum(v.total for v in ventas if v.metodo_pago == "tarjeta")


    # Teléfonos
    telefonos = db.query(models.VentaTelefono).filter(
        models.VentaTelefono.fecha == hoy,
        models.VentaTelefono.cancelada == False
    ).all()

    total_telefonos = sum(t.precio for t in telefonos)
    efectivo_tel = sum(t.precio for t in telefonos if t.metodo_pago == "efectivo")
    tarjeta_tel = sum(t.precio for t in telefonos if t.metodo_pago == "tarjeta")
    transferencia_tel = sum(t.precio for t in telefonos if t.metodo_pago == "transferencia")

    return {
        "total_general": round(total_productos + total_telefonos, 2),

        "ventas_productos": {
            "total": round(total_productos, 2),
            "efectivo": round(efectivo, 2),
            "tarjeta": round(tarjeta, 2),
        },


        "ventas_telefonos": {
            "total": round(total_telefonos, 2),
            "efectivo": round(efectivo_tel, 2),
            "tarjeta": round(tarjeta_tel, 2),
        }
    }
    
@router.post("/cortes")
def crear_corte(
    corte_data: schemas.CorteDiaCreate,  # schema con los totales del frontend
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.rol != "encargado":
        raise HTTPException(status_code=403, detail="Solo los encargados pueden hacer cortes")
    
    if not user.modulo_id:
        raise HTTPException(status_code=400, detail="El encargado no tiene un módulo asignado")

    nuevo_corte = models.CorteDia(
        fecha=datetime.date.today(),
        total_efectivo=corte_data.total_efectivo,
        total_tarjeta=corte_data.total_tarjeta,
        adicional_recargas=corte_data.adicional_recargas,
        adicional_transporte=corte_data.adicional_transporte,
        adicional_otros=corte_data.adicional_otros,
        total_sistema=corte_data.total_sistema,
        total_general=corte_data.total_general,
        modulo_id=user.modulo_id  
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

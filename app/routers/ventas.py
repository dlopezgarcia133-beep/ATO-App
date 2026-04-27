
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.utilidades import calcular_comision_telefono, enviar_ticket, verificar_rol_requerido
from datetime import date
from app.routers.kardex import registrar_kardex



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
        com = (
            db.query(models.Comision)
            .filter(func.lower(models.Comision.producto) == item.producto.strip().lower())
            .first()
        )
        comision_id = com.id if com else None
        modulo_id = current_user.modulo_id

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
            raise HTTPException(400, f"No hay inventario para {item.producto}")

        if inventario.cantidad < item.cantidad:
            raise HTTPException(400, f"Inventario insuficiente para {item.producto}")

        inventario.cantidad -= item.cantidad

        fecha_actual = datetime.now(zona_horaria)

        # ✅ VALIDACIÓN CORRECTA
        if item.tipo_producto == "telefono":
            if not item.chip_casado:
                raise HTTPException(
                    status_code=400,
                    detail=f"chip_casado es obligatorio para teléfonos: {item.producto}"
                )

        total = item.precio_unitario * item.cantidad

        nueva = models.Venta(
            empleado_id=current_user.id,
            modulo_id=modulo_id,
            producto=item.producto,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            tipo_producto=item.tipo_producto,
            tipo_venta=item.tipo_venta,
            metodo_pago=venta.metodo_pago,
            total=total,
            cancelada=False,
            comision_id=comision_id,
            chip_casado=item.chip_casado,
            fecha=fecha_actual.date(),
            hora=fecha_actual.time(),
            telefono_cliente=venta.telefono_cliente,
        )

        db.add(nueva)
        db.flush()

        # ✅ YA NO TRUENA
        registrar_kardex(
            db=db,
            producto=nueva.producto,
            tipo_producto=nueva.tipo_producto,
            cantidad=nueva.cantidad,
            tipo_movimiento="VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_id,
            referencia_id=nueva.id
        )

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
            chip_casado=v.chip_casado,
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

    # Validar permisos
    if current_user.rol != models.RolEnum.admin:
        if current_user.rol != models.RolEnum.encargado or venta.modulo_id != current_user.modulo_id:
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
            producto=venta.producto,
            cantidad=venta.cantidad,
            modulo_id=venta.modulo_id
        )
        db.add(inventario)
    else:
        inventario.cantidad += venta.cantidad

    # Marcar cancelada
    venta.cancelada = True

    # 🔥 Registrar Kardex (ENTRADA por cancelación)
    registrar_kardex(
        db=db,
        producto=venta.producto,
        tipo_producto=venta.tipo_producto,
        cantidad=venta.cantidad,
        tipo_movimiento="CANCELACION_VENTA",
        usuario_id=current_user.id,
        modulo_origen_id=None,
        modulo_destino_id=venta.modulo_id,
        referencia_id=venta.id
    )

    db.commit()
    db.refresh(venta)

    return venta








# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.orm import Session
# from sqlalchemy import func
# from typing import List
# from datetime import datetime
# from io import BytesIO
# from reportlab.pdfgen import canvas
# from reportlab.lib.pagesizes import letter
# import requests
# import uuid
# from supabase import create_client

# from .. import models, schemas
# from ..database import get_db
# from ..dependencies import get_current_user
# from ..config import zona_horaria  # si ya la tienes en tu config

# router = APIRouter()

# # --- Configuración ---
# SUPABASE_URL = "https://TU_PROYECTO.supabase.co"
# SUPABASE_KEY = "TU_SUPABASE_KEY"
# WHATSAPP_TOKEN = "TU_TOKEN_PERMANENTE"
# PHONE_NUMBER_ID = "861665657026345"  # tu ID de app Meta
# BUCKET_NAME = "tickets"


# # --- Función: Generar ticket PDF ---
# def generar_ticket_pdf(cliente: str, telefono: str, ventas: List[models.Venta]):
#     buffer = BytesIO()
#     pdf = canvas.Canvas(buffer, pagesize=letter)

#     pdf.setFont("Helvetica-Bold", 16)
#     pdf.drawString(200, 750, "Ticket de Compra")

#     pdf.setFont("Helvetica", 12)
#     pdf.drawString(50, 720, f"Cliente: {cliente}")
#     pdf.drawString(50, 700, f"Teléfono: {telefono}")
#     pdf.drawString(50, 680, f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

#     pdf.drawString(50, 650, "Productos:")
#     y = 630
#     total = 0
#     for v in ventas:
#         linea = f"- {v.producto} x{v.cantidad}  ${v.precio_unitario:.2f} c/u"
#         pdf.drawString(70, y, linea)
#         y -= 20
#         total += v.cantidad * v.precio_unitario

#     pdf.setFont("Helvetica-Bold", 12)
#     pdf.drawString(50, y - 10, f"TOTAL: ${total:.2f}")

#     pdf.showPage()
#     pdf.save()
#     buffer.seek(0)
#     return buffer


# # --- Subir PDF a Supabase ---
# def subir_ticket_supabase(buffer):
#     supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
#     nombre_archivo = f"ticket_{uuid.uuid4()}.pdf"
#     ruta = f"{BUCKET_NAME}/{nombre_archivo}"
#     supabase.storage.from_(BUCKET_NAME).upload(ruta, buffer.getvalue(), {"content-type": "application/pdf"})
#     public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(ruta)
#     return public_url


# # --- Enviar ticket por WhatsApp ---
# def enviar_ticket_whatsapp(numero_cliente: str, url_pdf: str):
#     url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
#     payload = {
#         "messaging_product": "whatsapp",
#         "to": numero_cliente,
#         "type": "document",
#         "document": {
#             "link": url_pdf,
#             "filename": "ticket.pdf",
#             "caption": "Gracias por tu compra 💙 Aquí está tu ticket."
#         }
#     }
#     headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
#     response = requests.post(url, json=payload, headers=headers)
#     return response.json()





@router.post("/ventas/multiples", response_model=List[schemas.VentaResponse])
def crear_ventas_multiples(
    venta: schemas.VentaMultipleCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    ventas_realizadas = []

    # calcular la fecha/hora una sola vez (evita inconsistencias por zona horaria)
    fecha_actual = datetime.now(zona_horaria)

    for item in venta.productos:
        com = (
            db.query(models.Comision)
            .filter(func.lower(models.Comision.producto) == item.producto.strip().lower())
            .filter(models.Comision.activo == True)
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
            raise HTTPException(status_code=400, detail=f"No hay inventario para el producto: {item.producto}")

        if inventario.cantidad < item.cantidad:
            raise HTTPException(status_code=400, detail=f"Inventario insuficiente para el producto: {item.producto}")

        # disminuir inventario
        inventario.cantidad -= item.cantidad

        # detectar tipo de producto buscando la palabra TELEFONO en cualquier parte
        tipo_producto = (
            "telefono"
            if "TELEFONO" in item.producto.strip().upper()
            else "accesorios"
        )

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
            fecha=fecha_actual.date(),
            hora=fecha_actual.time(),
            telefono_cliente=venta.telefono_cliente,
        )

        db.add(nueva)
        db.flush()

        registrar_kardex(
            db=db,
            producto=nueva.producto,
            tipo_producto=nueva.tipo_producto,
            cantidad=nueva.cantidad,
            tipo_movimiento="VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_id,
            referencia_id=nueva.id
        )

        ventas_realizadas.append(nueva)

    # confirmar transacción de ventas e inventario
    db.commit()

    # refrescar objetos creados para tener los id y relaciones
    for v in ventas_realizadas:
        db.refresh(v)

    # --- UPSET/ACTUALIZACIÓN de CorteDia ---
    try:
        # obtener o crear corte para la fecha y módulo
        fecha_corte = fecha_actual.date()
        modulo_id = current_user.modulo.id

        corte = db.query(models.CorteDia).filter(
            models.CorteDia.fecha == fecha_corte,
            models.CorteDia.modulo_id == modulo_id
        ).first()

        if not corte:
            corte = models.CorteDia(
                fecha=fecha_corte,
                modulo_id=modulo_id,
                total_efectivo=0.0,
                total_tarjeta=0.0,
                adicional_recargas=0.0,
                adicional_transporte=0.0,
                adicional_otros=0.0,
                total_sistema=0.0,
                total_general=0.0,
                accesorios_efectivo=0.0,
                accesorios_tarjeta=0.0,
                accesorios_total=0.0,
                telefonos_efectivo=0.0,
                telefonos_tarjeta=0.0,
                telefonos_total=0.0
            )
            db.add(corte)
            db.flush()  # asegura que corte tenga id si es necesario

        # Sumarizar las ventas realizadas en este request al corte
        suma_request = 0.0
        for v in ventas_realizadas:
            pago = (v.metodo_pago or "").strip().lower()
            es_efectivo = pago == "efectivo" or pago == "cash"  # ajusta si tienes otros valores
            total_v = float(v.total or 0)

            if es_efectivo:
                corte.total_efectivo = (corte.total_efectivo or 0) + total_v
                if v.tipo_producto == "accesorios":
                    corte.accesorios_efectivo = (corte.accesorios_efectivo or 0) + total_v
                else:
                    corte.telefonos_efectivo = (corte.telefonos_efectivo or 0) + total_v
            else:
                # todo lo que no sea "efectivo" lo acumulamos en tarjeta (ajusta según necesites)
                corte.total_tarjeta = (corte.total_tarjeta or 0) + total_v
                if v.tipo_producto == "accesorios":
                    corte.accesorios_tarjeta = (corte.accesorios_tarjeta or 0) + total_v
                else:
                    corte.telefonos_tarjeta = (corte.telefonos_tarjeta or 0) + total_v

            # totales por tipo
            if v.tipo_producto == "accesorios":
                corte.accesorios_total = (corte.accesorios_total or 0) + total_v
            else:
                corte.telefonos_total = (corte.telefonos_total or 0) + total_v

            # acumulador para total sistema y general
            corte.total_sistema = (corte.total_sistema or 0) + total_v
            suma_request += total_v

        # Actualizar total_general (si quieres incluir ya las adicionales, agrégalas aquí)
        corte.total_general = (corte.total_general or 0) + suma_request

        db.commit()
        # opcional: db.refresh(corte)
    except Exception as e:
        # No queremos romper la respuesta si falla la actualización del corte,
        # pero sí devolvemos información del error en logs.
        db.rollback()
        # loguear e.g. logger.error(...) si tienes logger
        print("Error actualizando CorteDia:", e)

    # Generar ticket PDF y enviar por WhatsApp
    try:
        pdf_buffer = generar_ticket_pdf(
            cliente=venta.cliente if hasattr(venta, "cliente") else "Cliente",
            telefono=venta.telefono_cliente,
            ventas=ventas_realizadas,
        )
        url_pdf = subir_ticket_supabase(pdf_buffer)
        respuesta_whatsapp = enviar_ticket_whatsapp(venta.telefono_cliente, url_pdf)
    except Exception as e:
        respuesta_whatsapp = {"error": str(e)}

    # Conversión manual segura y respuesta
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
    
    if venta.cvip is None:
        raise HTTPException(
            status_code=400,
            detail="Debes seleccionar una opcion (Si o No)"
        )
    
    fecha_actual = datetime.now(zona_horaria)
    nueva_venta = models.VentaChip(
        empleado_id=current_user.id,
        tipo_chip=venta.tipo_chip,
        numero_telefono=venta.numero_telefono,
        monto_recarga=venta.monto_recarga,
        cvip=venta.cvip,
        fecha=fecha_actual.date(),
        hora=fecha_actual.time(),
    )

    db.add(nueva_venta)
    db.commit()
    db.refresh(nueva_venta)
    return nueva_venta



@router.get("/venta_chips/verificar_numero/{numero}")
def verificar_numero_duplicado(numero: str, db: Session = Depends(get_db)):
    existe = db.query(models.VentaChip).filter(
        models.VentaChip.numero_telefono == numero
    ).first()
    return {"duplicado": existe is not None}


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
            "Chip Equipo": [
                ((0,50), 15),
                ((51, 100), 20),
                ((101, 1000), 30)
            ],
            "Chip Express": [
                ((0, 50), 5),
                ((51, 100), 10),
                ((101, 150),30)
            ],
            "Portabilidad": [
                ((0, 500), 50),
                
            ],
            "Chip Cero/Libre": [
                ((0, 50), 25),
                ((51, 100), 30),
                ((101, 150),35)
                
            ],
            "Chip Preactivado": [
                ((0, 500), 35),
                
            ],

              "Chip Coppel": [
              ((0, 50), 10),
                ((51, 100), 15),
            ],

            "Portabilidad Coppel": [
                ((0, 500), 25),
            ],
            
            "Porta Otras cadenas": [
                ((0, 500), 50), 
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
    venta.es_incubadora = True
    db.commit()
    return {"mensaje": "Motivo de rechazo registrado"}

@router.get("/ventas/chips_rechazados", response_model=List[schemas.VentaChipResponse])
def obtener_chips_rechazados(
    empleado_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):

    query = db.query(models.VentaChip).filter(
        models.VentaChip.descripcion_rechazo != None,
        models.VentaChip.validado == False
    )

    # 🔹 Si NO es admin → solo ve sus chips
    if current_user.rol != "admin":
        query = query.filter(
            models.VentaChip.empleado_id == current_user.id
        )

    # 🔹 Si es admin y selecciona empleado
    elif empleado_id:
        query = query.filter(
            models.VentaChip.empleado_id == empleado_id
        )

    return query.all()

@router.put("/validar_chip_incubadora/{chip_id}", response_model=schemas.VentaChipResponse)
def validar_chip_incubadora(
    chip_id: int,
    data: schemas.ValidarChipIncubadoraRequest,
    db: Session = Depends(get_db)):

    chip = db.query(models.VentaChip).filter(
        models.VentaChip.id == chip_id
    ).first()

    if not chip:
        raise HTTPException(status_code=404, detail="Chip no encontrado")

    if chip.validado:
        raise HTTPException(status_code=400, detail="El chip ya está validado")

    tipo = chip.tipo_chip
    monto = int(chip.monto_recarga)

    comisiones_por_chip = {
        "Chip Equipo": [
            ((0,50), 15),
            ((51, 100), 20),
            ((101, 1000), 30)
        ],
        "Chip Express": [
            ((0, 50), 5),
            ((51, 100), 10),
            ((101, 150),30)
        ],
        "Portabilidad": [
            ((0, 500), 50),
        ],
        "Chip Cero/Libre": [
            ((0, 50), 25),
            ((51, 100), 30),
            ((101, 150),35)
        ],
        "Chip Preactivado": [
            ((0, 500), 35),
        ],
        "Chip Coppel": [
            ((0, 50), 10),
            ((51, 100), 15),
        ],
        "Portabilidad Coppel": [
            ((0, 500), 25),
        ],
        "Porta Otras cadenas": [
            ((0, 500), 50), 
        ]
    }

    # 🔥 CASO ESPECIAL: ACTIVACION
    if tipo == "Activacion":
        if not data.comision_manual or data.comision_manual <= 0:
            raise HTTPException(
                status_code=400,
                detail="La comisión manual es obligatoria para chips de Activación"
            )

        chip.comision = data.comision_manual

    # 🔹 RESTO DE CHIPS (automático)
    else:
        if tipo not in comisiones_por_chip:
            raise HTTPException(status_code=404, detail="No hay comisión configurada para este tipo de chip")

        comision_asignada = None

        for (min_monto, max_monto), comision in comisiones_por_chip[tipo]:
            if min_monto <= monto <= max_monto:
                comision_asignada = comision
                break

        if comision_asignada is None:
            raise HTTPException(status_code=404, detail="Monto de recarga fuera de rango")

        chip.comision = comision_asignada
    # 🔹 Marcar como incubadora
    

    # 🔹 Limpiar rechazo
    chip.descripcion_rechazo = None

    # 🔹 Validar
    chip.validado = True

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
    modulo_id: int | None = Query(None),    
    current_user: models.Usuario = Depends(get_current_user)
):
    hoy = date.today()

    modulo_final = modulo_id or current_user.modulo_id

    ventas = db.query(models.Venta).filter(
        func.date(models.Venta.fecha) == hoy,
        models.Venta.modulo_id == modulo_final
    ).all()

    ventas_productos = [v for v in ventas if v.tipo_producto == "accesorios"]
    ventas_telefonos = [v for v in ventas if v.tipo_producto == "telefono"]

    # ACCESORIOS
    efectivo_productos = sum(
        v.total for v in ventas_productos
        if v.metodo_pago == "efectivo" and not v.cancelada
    )

    tarjeta_productos = sum(
        v.total for v in ventas_productos
        if v.metodo_pago == "tarjeta" and not v.cancelada
    )

    def total_tel(v):
        return (v.precio_unitario or 0) * (v.cantidad or 1)

    efectivo_tel = sum(
        total_tel(v)
        for v in ventas_telefonos
        if v.metodo_pago == "efectivo" and not v.cancelada
    )

    tarjeta_tel = sum(
        total_tel(v)
        for v in ventas_telefonos
        if v.metodo_pago == "tarjeta" and not v.cancelada
    )

    total_efectivo = efectivo_productos + efectivo_tel
    total_tarjeta = tarjeta_productos + tarjeta_tel
    total_sistema = total_efectivo + total_tarjeta

    print("TOTAL VENTAS:", len(ventas))
    print("TELEFONOS:", len([v for v in ventas if v.tipo_producto == "telefono"]))
    print("TIPOS:", list(set([v.tipo_producto for v in ventas])))

    return {
    "ventas_telefonos": {
        "efectivo": round(efectivo_tel, 2),
        "tarjeta": round(tarjeta_tel, 2),
        "total": round(efectivo_tel + tarjeta_tel, 2)
    },
    "ventas_productos": {
        "efectivo": round(efectivo_productos, 2),
        "tarjeta": round(tarjeta_productos, 2),
        "total": round(efectivo_productos + tarjeta_productos, 2)
    },
    "total_sistema": round(total_sistema, 2),
    "totales": {
        "efectivo": round(total_efectivo, 2),
        "tarjeta": round(total_tarjeta, 2),
        "sistema": round(total_sistema, 2),
        "general": round(total_sistema, 2)
    }
}
    


@router.get("/ventas/cortes")
def obtener_cortes(
    fecha: Optional[date] = Query(None),
    modulo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):


    
    # Query base
    query = db.query(models.CorteDia)

    if fecha:
        query = query.filter(models.CorteDia.fecha == fecha)

    if modulo_id:
        query = query.filter(models.CorteDia.modulo_id == modulo_id)

    # 🔹 ORDEN CORRECTO (sin joinedload mal usado)
    cortes = query.order_by(models.CorteDia.fecha.desc()).all()

    cortes_completos = []

    for corte in cortes:

        # 🔹 Obtener ventas del día por módulo
        ventas = db.query(models.Venta).filter(
            func.date(models.Venta.fecha) == corte.fecha,
            models.Venta.modulo_id == corte.modulo_id,
            models.Venta.cancelada == False
        ).all()

        cortes_completos.append({
            "fecha": corte.fecha,
            "modulo_id": corte.modulo_id,

            # Totales generales
            "total_efectivo": corte.total_efectivo,
            "total_tarjeta": corte.total_tarjeta,
            "total_sistema": corte.total_sistema,
            "total_general": corte.total_general,

            # Adicionales
            "adicional_recargas": corte.adicional_recargas,
            "adicional_transporte": corte.adicional_transporte,
            "adicional_otros": corte.adicional_otros,

            # Accesorios
            "accesorios_efectivo": corte.accesorios_efectivo,
            "accesorios_tarjeta": corte.accesorios_tarjeta,
            "accesorios_total": corte.accesorios_total,

            # Teléfonos
            "telefonos_efectivo": corte.telefonos_efectivo,
            "telefonos_tarjeta": corte.telefonos_tarjeta,
            "telefonos_total": corte.telefonos_total,

            # 🔹 Ventas detalladas
            "ventas": [
                {
                    "id": v.id,
                    "producto": v.producto,
                    "tipo_producto": v.tipo_producto,
                    "tipo_venta": v.tipo_venta,
                    "precio_unitario": v.precio_unitario,
                    "cantidad": v.cantidad,
                    "total": v.total,

                    # 🔹 Fecha con hora real (evita bug timezone)
                    "fecha": f"{v.fecha} {v.hora}" if v.hora else str(v.fecha),

                    # 🔹 Nombre del empleado
                    "empleado": {
                        "id": v.empleado.id if v.empleado else None,
                        "username": v.empleado.username if v.empleado else "Sin nombre"
                    }
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



    
    

# vamos a modificar ya no se que es 




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
        models.Venta.fecha<= fin_ciclo,
        models.Venta.cancelada == False,
        models.Venta.tipo_producto == "accesorios"
    ).all()

    # ← CORRECCIÓN: usar models.Venta aquí para teléfonos (consistente)
    ventas_telefonos = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha >= inicio_ciclo,
        models.Venta.fecha <= fin_ciclo,
        models.Venta.cancelada == False,
        models.Venta.tipo_producto == "telefono"
    ).all()

    # ------------------------------------------------
    # Procesar ACCESORIOS: si comision_obj es None -> comision 0
    # ------------------------------------------------
    accesorios = []
    for v in ventas_accesorios:
        comision_unitaria = getattr(getattr(v, "comision_obj", None), "cantidad", 0)
        comision_total_attr = getattr(v, "comision_total", None)
        # En accesorios si no existe comision_total lo calculamos sólo si hay comision_obj
        comision_total = comision_total_attr if comision_total_attr is not None else (comision_unitaria * getattr(v, "cantidad", 0))
        # incluir solo si hay comisión (según tu regla)
        if comision_unitaria > 0 or (comision_total and comision_total > 0):
            accesorios.append({
                "producto": getattr(v, "producto", None),
                "cantidad": getattr(v, "cantidad", 0),
                "comision": comision_unitaria,
                "comision_total": comision_total,
                "tipo_venta": getattr(v, "tipo_venta", None),
                "fecha": getattr(v, "fecha", None),
                "hora": getattr(v, "hora", None)
            })

    # ------------------------------------------------
    # Procesar TELÉFONOS: siempre considerar comision_total cuando exista
    # ------------------------------------------------
    telefonos = []
    for v in ventas_telefonos:
        comision_unitaria = getattr(getattr(v, "comision_obj", None), "cantidad", 0)
        comision_total_attr = getattr(v, "comision_total", None)

        # En teléfonos: si comision_total existe lo usamos; si no, lo calculamos si comision_obj existe; si no, 0
        if comision_total_attr is not None:
            comision_total = comision_total_attr
        else:
            comision_total = (comision_unitaria * getattr(v, "cantidad", 0)) if comision_unitaria > 0 else 0

        telefonos.append({
            "producto": getattr(v, "producto", None),
            "cantidad": getattr(v, "cantidad", 0),
            "tipo_venta": getattr(v, "tipo_venta", None),
            "comision": comision_unitaria,
            "comision_total": comision_total,
            "fecha": getattr(v, "fecha", None),
            "hora": getattr(v, "hora", None)
        })

    # ------------------------------------------------
    # Procesar CHIPS
    # ------------------------------------------------
    chips = []
    for v in ventas_chips:
        com = getattr(v, "comision", 0) or 0
        if com > 0:
            chips.append({
                "tipo_chip": getattr(v, "tipo_chip", None),
                "numero_telefono": getattr(v, "numero_telefono", None),
                "comision": com,
                "fecha": getattr(v, "fecha", None),
                "hora": getattr(v, "hora", None)
            })

    # ------------------------------------------------
    # Totales (usar comision_total para accesorios y telefonos)
    # ------------------------------------------------
    total_accesorios = sum(v.get("comision_total", 0) or 0 for v in accesorios)
    total_telefonos = sum(v.get("comision_total", 0) or 0 for v in telefonos)
    total_chips = sum(v.get("comision", 0) or 0 for v in chips)

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


@router.put("/ventas/{id}/comision_tipo", response_model=schemas.VentaTelefonoConComision)
def agregar_comision_por_tipo_venta(
    id: int,
    db: Session = Depends(get_db)
):
    venta = db.query(models.Venta).filter(models.Venta.id == id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    # Tabla de comisiones adicionales según tipo de venta
    comisiones_por_tipo = {
        "Contado": 10,
        "Paguitos": 110,
        "Pajoy": 100
    }

    # Comisión base (si no tiene, se asume 0)
    comision_base = venta.comision_obj.cantidad if venta.comision_obj else 0

    # Comisión extra según el tipo de venta
    comision_extra = comisiones_por_tipo.get(venta.tipo_venta, 0)

    # Cálculo total
    if venta.tipo_producto and venta.tipo_producto.lower() == "telefono":
        comision_total = (comision_base * venta.cantidad) + comision_extra
    else:
        comision_total = comision_base * venta.cantidad

    # Guardar cambios (si quisieras persistir la comisión total en BD, aquí podrías hacerlo)
    db.commit()
    db.refresh(venta)

    return {
        "id": venta.id,
        "producto": venta.producto,
        "cantidad": venta.cantidad,
        "tipo_venta": venta.tipo_venta,
        "tipo_producto": venta.tipo_producto,
        "comision_base": comision_base,
        "comision_extra": comision_extra,
        "comision_total": comision_total,
        "fecha": venta.fecha,
        "hora": venta.hora
    }




@router.get("/clientes_vip")
def clientes_vip(db: Session = Depends(get_db)):

    clientes = db.query(models.VentaChip).filter(
        models.VentaChip.cvip == True
    ).all()

    telefonos = list({c.numero_telefono for c in clientes})

    return [{"telefono": tel} for tel in telefonos]

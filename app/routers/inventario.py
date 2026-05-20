import datetime
import pandas as pd
import os
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, Form
from fastapi.params import File
from zoneinfo import ZoneInfo
from sqlalchemy import func, text
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido
from sqlalchemy.orm import Session
from app.models import InventarioGeneral, InventarioModulo, EntradaMercancia
from datetime import datetime, date
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from io import BytesIO
from app.routers.kardex import registrar_kardex


router = APIRouter()

@router.post("/inventario/general", response_model=schemas.InventarioGeneralResponse)
def crear_producto_inventario_general(
    producto: schemas.InventarioGeneralCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    existente = db.query(models.InventarioGeneral).filter_by(producto=producto.producto).first()
    if existente:
        raise HTTPException(status_code=400, detail="El producto ya existe en el inventario general.")
    
    nuevo = models.InventarioGeneral(**producto.dict())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo



@router.put("/inventario/general/{producto}", response_model=schemas.InventarioGeneralResponse)
def actualizar_producto_inventario_general(
    producto: str,
    datos: schemas.InventarioGeneralUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    producto_db = db.query(models.InventarioGeneral).filter_by(producto=producto).first()
    if not producto_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")
    
    producto_db.cantidad = datos.cantidad
    db.commit()
    db.refresh(producto_db)
    return producto_db




@router.get("/inventario/buscar-autocomplete")
def buscar_productos_general_autocomplete(
    q: str,
    db: Session = Depends(get_db)
):
    productos = (
        db.query(
            models.InventarioGeneral.id,
            models.InventarioGeneral.producto,
            models.InventarioGeneral.clave,
            models.InventarioGeneral.precio
        )
        .filter(
            (models.InventarioGeneral.clave.ilike(f"%{q}%")) |
            (models.InventarioGeneral.producto.ilike(f"%{q}%"))
        )
        .order_by(models.InventarioGeneral.precio.asc())
        .limit(20)
        .all()
    )

    return [
        {
            "id": p.id,
            "producto": p.producto,
            "clave": p.clave,
            "precio": p.precio
        }
        for p in productos
    ]




@router.get("/inventario/descargar/{modulo_id}")
def descargar_inventario_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # 🔒 SOLO ADMIN
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    productos = (
        db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .all()
    )

    if not productos:
        raise HTTPException(status_code=404, detail="Inventario vacío")



    data = [
        {
            "Clave": p.clave,
            "Producto": p.producto,
            "Cantidad": p.cantidad,
            "Precio": p.precio
        }
        for p in productos
    ]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=inventario_modulo_{modulo_id}.xlsx"
        }
    )



@router.get(
    "/inventario/general/productos-nombres",
    response_model=List[str]
)
def obtener_productos_nombres(
    db: Session = Depends(get_db),
        current_user: models.Usuario = Depends(get_current_user)
):
    productos = (
        db.query(
            models.InventarioModulo.producto,
            func.min(models.InventarioModulo.precio).label("precio_min")
        )
        .filter(
            models.InventarioModulo.modulo_id == current_user.modulo_id
        )
        .group_by(models.InventarioModulo.producto)
        .order_by(func.min(models.InventarioModulo.precio).asc())
        .all()
    )

    return [p.producto for p in productos]

@router.get("/buscar", response_model=List[str])
def autocomplete_telefonos(
    query: str = Query(..., min_length=1, description="Texto a buscar"),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    productos = (
        db.query(models.InventarioModulo.producto)
        .filter(
            models.InventarioModulo.tipo_producto == "telefono",
            models.InventarioModulo.modulo_id == current_user.modulo_id,
            models.func.upper(models.InventarioModulo.producto).ilike(f"%{query.upper()}%")
        )
        .limit(10)
        .all()
    )

    return [p[0] for p in productos]




@router.get("/inventario/general/{producto}", response_model=schemas.InventarioGeneralResponse)
def produtos_inventario(
    producto: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    producto_normalizado = producto.strip().lower()
    
    producto_db = db.query(models.InventarioGeneral).filter(
        func.lower(func.trim(models.InventarioGeneral.producto)) == producto_normalizado
    ).first()

    if not producto_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")

    return producto_db


@router.get("/inventario/general", response_model=list[schemas.InventarioGeneralResponse])
def obtener_inventario_general(
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(models.InventarioGeneral)
    if tipo:
        query = query.filter(models.InventarioGeneral.tipo == tipo)
    return query.all()



@router.post("/inventario/entrada_mercancia")
def entrada_mercancia(
    data: schemas.EntradaMercanciaRequest,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.admin])
    )
):

    # Folio atómico: nextval es no-transaccional en Postgres, nunca se repite
    folio = db.execute(
        text("SELECT 'E' || nextval('entrada_folio_seq')")
    ).scalar()

    entrada = EntradaMercancia(
        folio=folio,
        modulo_id=data.modulo_id,
        usuario_id=current_user.id,
        fecha=datetime.now(ZoneInfo("America/Mexico_City")),
    )
    db.add(entrada)
    db.flush()  # obtiene entrada.id antes del commit

    for item in data.productos:
        producto_base = (
            db.query(models.InventarioGeneral)
            .filter(models.InventarioGeneral.id == item.producto_id)
            .first()
        )

        if not producto_base:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        registro = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave     == producto_base.clave,
                models.InventarioModulo.modulo_id == data.modulo_id
            )
            .first()
        )

        if registro:
            registro.cantidad  += item.cantidad
            registro.producto   = producto_base.producto
            registro.precio     = producto_base.precio
        else:
            nuevo = models.InventarioModulo(
                producto=producto_base.producto,
                clave=producto_base.clave,
                precio=producto_base.precio,
                tipo_producto=producto_base.tipo_producto,
                cantidad=item.cantidad,
                modulo_id=data.modulo_id
            )
            db.add(nuevo)

        registrar_kardex(
            db=db,
            producto=producto_base.producto,
            tipo_producto=producto_base.tipo_producto,
            cantidad=item.cantidad,
            tipo_movimiento="ENTRADA",
            usuario_id=current_user.id,
            modulo_origen_id=None,
            modulo_destino_id=data.modulo_id,
            referencia_id=entrada.id,
        )

    db.commit()
    return {"ok": True, "folio": folio, "message": "Entrada registrada correctamente"}


@router.get("/inventario/entradas")
def listar_entradas_mercancia(
    folio: Optional[str] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    modulo_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    ZONA = ZoneInfo("America/Mexico_City")

    query = (
        db.query(EntradaMercancia, models.Modulo, models.Usuario)
        .join(models.Modulo, EntradaMercancia.modulo_id == models.Modulo.id)
        .join(models.Usuario, EntradaMercancia.usuario_id == models.Usuario.id)
    )

    if folio:
        query = query.filter(EntradaMercancia.folio.ilike(f"%{folio}%"))

    if modulo_id:
        query = query.filter(EntradaMercancia.modulo_id == modulo_id)

    if fecha_desde:
        dt_desde = datetime(
            fecha_desde.year, fecha_desde.month, fecha_desde.day,
            0, 0, 0, tzinfo=ZONA,
        )
        query = query.filter(EntradaMercancia.fecha >= dt_desde)

    if fecha_hasta:
        dt_hasta = datetime(
            fecha_hasta.year, fecha_hasta.month, fecha_hasta.day,
            23, 59, 59, tzinfo=ZONA,
        )
        query = query.filter(EntradaMercancia.fecha <= dt_hasta)

    rows = (
        query.order_by(EntradaMercancia.fecha.desc())
        .limit(50)
        .all()
    )

    resultado = []
    for entrada, modulo, usuario in rows:
        kardex_items = (
            db.query(
                models.KardexMovimiento.producto,
                models.KardexMovimiento.cantidad,
                models.InventarioGeneral.clave,
            )
            .outerjoin(
                models.InventarioGeneral,
                models.KardexMovimiento.producto == models.InventarioGeneral.producto,
            )
            .filter(
                models.KardexMovimiento.referencia_id == entrada.id,
                models.KardexMovimiento.tipo_movimiento == models.TipoMovimientoEnum.ENTRADA,
            )
            .all()
        )

        resultado.append({
            "id": entrada.id,
            "folio": entrada.folio,
            "fecha": entrada.fecha,
            "modulo_id": modulo.id,
            "modulo_nombre": modulo.nombre,
            "usuario_id": usuario.id,
            "usuario_username": usuario.username,
            "usuario_nombre": usuario.nombre_completo,
            "productos": [
                {
                    "clave": krow.clave or "",
                    "producto": krow.producto,
                    "cantidad": krow.cantidad,
                }
                for krow in kardex_items
            ],
        })

    return resultado


@router.delete("/inventario/entradas/{entrada_id}")
def eliminar_entrada_mercancia(
    entrada_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    entrada = db.query(EntradaMercancia).filter(EntradaMercancia.id == entrada_id).first()
    if not entrada:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")

    kardex_items = (
        db.query(models.KardexMovimiento)
        .filter(
            models.KardexMovimiento.referencia_id == entrada_id,
            models.KardexMovimiento.tipo_movimiento == models.TipoMovimientoEnum.ENTRADA,
        )
        .all()
    )

    # Cargar inventario de cada producto de una vez — lookup por clave si disponible
    inventario_map = {}
    for k in kardex_items:
        if k.clave:
            inv = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.clave     == k.clave,
                    models.InventarioModulo.modulo_id == entrada.modulo_id,
                )
                .first()
            )
        else:
            inv = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.producto  == k.producto,
                    models.InventarioModulo.modulo_id == entrada.modulo_id,
                )
                .first()
            )
        inventario_map[k.producto] = inv

    # Fase 1: validar todo ANTES de mutar nada
    errores = []
    for k in kardex_items:
        inv = inventario_map.get(k.producto)
        stock_actual = inv.cantidad if inv else 0
        if stock_actual - k.cantidad < 0:
            faltantes = k.cantidad - stock_actual
            errores.append(
                f"'{k.producto}': stock actual {stock_actual}, "
                f"la entrada registró {k.cantidad}, faltan {faltantes} piezas"
            )

    if errores:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar la entrada porque quedaría stock negativo: "
            + "; ".join(errores),
        )

    # Fase 2: bloquear la fila para serializar solicitudes concurrentes sobre la misma entrada
    entrada = (
        db.query(EntradaMercancia)
        .filter(EntradaMercancia.id == entrada_id)
        .with_for_update()
        .first()
    )
    if not entrada:
        raise HTTPException(status_code=404, detail="La entrada ya fue eliminada por otro proceso")

    for k in kardex_items:
        inv = inventario_map.get(k.producto)
        if inv is None:
            continue
        inv.cantidad -= k.cantidad
        registrar_kardex(
            db=db,
            producto=k.producto,
            tipo_producto=k.tipo_producto,
            cantidad=k.cantidad,
            tipo_movimiento="AJUSTE_NEGATIVO",
            usuario_id=current_user.id,
            modulo_origen_id=entrada.modulo_id,
            modulo_destino_id=None,
            referencia_id=entrada_id,
        )

    db.delete(entrada)
    db.commit()
    return {"ok": True, "message": f"Entrada {entrada.folio} eliminada correctamente"}


@router.put("/inventario/entradas/{entrada_id}")
def editar_entrada_mercancia(
    entrada_id: int,
    data: schemas.EditarEntradaRequest,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not data.productos:
        raise HTTPException(status_code=400, detail="La entrada debe tener al menos un producto")

    entrada = db.query(EntradaMercancia).filter(EntradaMercancia.id == entrada_id).first()
    if not entrada:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")

    kardex_original = (
        db.query(models.KardexMovimiento)
        .filter(
            models.KardexMovimiento.referencia_id == entrada_id,
            models.KardexMovimiento.tipo_movimiento == models.TipoMovimientoEnum.ENTRADA,
        )
        .all()
    )
    # producto_nombre → (cantidad_original, tipo_producto)
    mapa_original = {k.producto: (k.cantidad, k.tipo_producto) for k in kardex_original}

    # Resolver cada producto nuevo desde inventario_general
    # base_info: producto_nombre → (clave, precio, tipo_producto, nueva_cantidad)
    base_info = {}
    for item in data.productos:
        base = (
            db.query(models.InventarioGeneral)
            .filter(models.InventarioGeneral.id == item.producto_id)
            .first()
        )
        if not base:
            raise HTTPException(status_code=404, detail=f"Producto ID {item.producto_id} no encontrado")
        if item.cantidad <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"La cantidad para '{base.producto}' debe ser mayor a 0",
            )
        base_info[base.producto] = (base.clave, base.precio, base.tipo_producto, item.cantidad)

    # Calcular deltas: producto_nombre → (delta, tipo_producto)
    deltas = {}

    for prod_nombre, (clave, precio, tipo_prod, nueva_cant) in base_info.items():
        cant_orig, tipo_orig = mapa_original.get(prod_nombre, (0, tipo_prod))
        delta = nueva_cant - cant_orig
        if delta != 0:
            deltas[prod_nombre] = (delta, tipo_prod)

    # Productos eliminados: estaban en original, no están en nuevos
    for prod_nombre, (cant_orig, tipo_prod) in mapa_original.items():
        if prod_nombre not in base_info:
            deltas[prod_nombre] = (-cant_orig, tipo_prod)

    if not deltas:
        return {"ok": True, "message": "Sin cambios que aplicar"}

    # Fase 1: validar todos los deltas negativos ANTES de mutar nada
    # (La Fase 2 adquirirá el lock con with_for_update antes de cualquier mutación)
    errores = []
    for prod_nombre, (delta, _) in deltas.items():
        if delta < 0:
            inv = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.producto == prod_nombre,
                    models.InventarioModulo.modulo_id == entrada.modulo_id,
                )
                .first()
            )
            stock_actual = inv.cantidad if inv else 0
            if stock_actual + delta < 0:
                faltantes = abs(stock_actual + delta)
                errores.append(
                    f"'{prod_nombre}': stock actual {stock_actual}, "
                    f"reducción de {abs(delta)}, faltan {faltantes} piezas"
                )

    if errores:
        raise HTTPException(
            status_code=400,
            detail="No se puede editar la entrada porque quedaría stock negativo: "
            + "; ".join(errores),
        )

    # Fase 2: bloquear la fila para serializar solicitudes concurrentes sobre la misma entrada
    entrada = (
        db.query(EntradaMercancia)
        .filter(EntradaMercancia.id == entrada_id)
        .with_for_update()
        .first()
    )
    if not entrada:
        raise HTTPException(status_code=404, detail="La entrada ya fue procesada por otro proceso")

    for prod_nombre, (delta, tipo_prod) in deltas.items():
        clave, precio, _, _ = base_info[prod_nombre]
        inv = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave     == clave,
                models.InventarioModulo.modulo_id == entrada.modulo_id,
            )
            .first()
        )
        if inv:
            inv.cantidad += delta
        else:
            # Producto nuevo que no existía en este módulo (delta > 0 garantizado por validación)
            db.add(
                models.InventarioModulo(
                    producto=prod_nombre,
                    clave=clave,
                    precio=precio,
                    tipo_producto=tipo_prod,
                    cantidad=delta,
                    modulo_id=entrada.modulo_id,
                )
            )

        tipo_mov = "AJUSTE_POSITIVO" if delta > 0 else "AJUSTE_NEGATIVO"
        registrar_kardex(
            db=db,
            producto=prod_nombre,
            tipo_producto=tipo_prod,
            cantidad=abs(delta),
            tipo_movimiento=tipo_mov,
            usuario_id=current_user.id,
            modulo_origen_id=entrada.modulo_id if delta < 0 else None,
            modulo_destino_id=entrada.modulo_id if delta > 0 else None,
            referencia_id=entrada_id,
        )

    db.commit()
    return {"ok": True, "message": "Entrada actualizada correctamente"}


@router.post("/inventario/modulo", response_model=schemas.InventarioModuloResponse)
def crear_producto_modulo(
    datos: schemas.InventarioModuloCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.admin])
    )
):
    # Buscar módulo por ID en lugar de nombre
    modulo_obj = db.query(models.Modulo).filter_by(id=datos.modulo_id).first()
    if not modulo_obj:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Verificar si ya existe el producto en el módulo
    existente = db.query(models.InventarioModulo).filter_by(
        clave=datos.clave, modulo_id=modulo_obj.id
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="El producto ya existe en el módulo")

    # Crear nuevo producto
    nuevo = models.InventarioModulo(
        producto=datos.producto,
        clave=datos.clave,
        cantidad=datos.cantidad,
        precio=datos.precio,
        modulo_id=modulo_obj.id,
        tipo_producto=datos.tipo_producto
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

@router.put("/inventario/modulo/{producto}", response_model=schemas.InventarioModuloResponse)
def actualizar_inventario_modulo(
    producto: str,
    datos: schemas.InventarioModuloUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.admin])
    )
):
    
    item = db.query(models.InventarioModulo).filter_by(
        producto=producto,
        modulo_id=datos.modulo_id
    ).first()

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado en el módulo."
        )

    producto_general = db.query(models.InventarioGeneral).filter_by(
        producto=producto
    ).first()

    if not producto_general:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado en inventario general."
        )


    cantidad_anterior = item.cantidad


    nueva_cantidad = datos.cantidad

 
    diferencia = nueva_cantidad - cantidad_anterior

    
    if diferencia > 0:
        if producto_general.cantidad < diferencia:
            raise HTTPException(
                status_code=400,
                detail="No hay suficiente producto en inventario general."
            )

        producto_general.cantidad -= diferencia

   
    elif diferencia < 0:
        producto_general.cantidad += abs(diferencia)

    
    item.cantidad = nueva_cantidad

    db.commit()
    db.refresh(item)

    return item
 
@router.get("/inventario/modulo", response_model=list[schemas.InventarioModuloResponse])
def obtener_inventario_modulo(
    modulo: Optional[str] = None,
    modulo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # Validar que al menos uno se haya proporcionado
    if not modulo and not modulo_id:
        raise HTTPException(status_code=400, detail="Debes proporcionar el nombre o el ID del módulo")

    # Obtener el objeto del módulo según el parámetro disponible
    if modulo:
        modulo_obj = db.query(models.Modulo).filter_by(nombre=modulo).first()
    else:
        modulo_obj = db.query(models.Modulo).filter_by(id=modulo_id).first()

    if not modulo_obj:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Consultar inventario usando el ID del módulo
    return db.query(models.InventarioModulo).filter(models.InventarioModulo.modulo_id == modulo_obj.id).all()



@router.delete("/inventario/modulo/{id}")
def eliminar_producto_modulo(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    # Buscar el producto en el inventario del módulo
    item_modulo = db.query(models.InventarioModulo).filter_by(id=id).first()
    if not item_modulo:
        raise HTTPException(status_code=404, detail="Producto no encontrado en ese módulo.")

    # Buscar el producto en el inventario general por la clave o nombre del producto
    producto_general = db.query(models.InventarioGeneral).filter_by(clave=item_modulo.clave).first()
    if not producto_general:
        raise HTTPException(status_code=404, detail="Producto no encontrado en el inventario general.")

    # Sumar la cantidad del módulo al inventario general
    producto_general.cantidad += item_modulo.cantidad

    # Eliminar el producto del módulo
    db.delete(item_modulo)
    db.commit()

    return {
        "mensaje": f"Producto '{item_modulo.producto}' eliminado del módulo y cantidad regresada al inventario general."
    }






@router.get("/inventario/buscar")
def buscar_producto(
    modulo_id: int = Query(...),
    clave: str = Query(...),
    db: Session = Depends(get_db)
):
    producto = (
        db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .filter(models.InventarioModulo.clave.ilike(f"%{clave}%"))
        .first()
    )

    if not producto:
        return {"ok": False, "msg": "Producto no encontrado"}

    return {
        "ok": True,
        "producto": {
            "id": producto.id,              # ✅ OBLIGATORIO
            "producto": producto.producto,
            "clave": producto.clave,
            "cantidad_actual": producto.cantidad
        }
    }




@router.post("/mover_a_modulo")
def mover_producto_a_modulo(
    producto_id: int,
    modulo: str,
    cantidad: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(["admin"]))
):
    # Buscar producto en inventario general
    producto_general = db.query(models.InventarioGeneral).filter_by(id=producto_id).first()
    if not producto_general:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general")

    if producto_general.cantidad < cantidad:
        raise HTTPException(status_code=400, detail="Cantidad insuficiente en inventario general")

    # Descontar del inventario general
    producto_general.cantidad -= cantidad

    # Buscar o crear producto en inventario del módulo
    inventario_modulo = db.query(models.InventarioModulo).filter_by(
        producto_id=producto_id, modulo=modulo
    ).first()

    if inventario_modulo:
        inventario_modulo.cantidad += cantidad
    else:
        nuevo = models.InventarioModulo(
            producto_id=producto_id,
            modulo=modulo,
            cantidad=cantidad
        )
        db.add(nuevo)

    db.commit()
    return {"mensaje": f"{cantidad} unidades movidas al módulo {modulo} correctamente"}




@router.post("/replicar", response_model=dict)
def agregar_o_actualizar_producto_todos_modulos(
    datos: schemas.InventarioGlobalCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin, models.RolEnum.direccion]))
):
    # 1️⃣ Obtener todos los módulos registrados
    modulos = db.query(models.Modulo).all()
    if not modulos:
        raise HTTPException(status_code=404, detail="No hay módulos registrados")

    # 2️⃣ Recorrer cada módulo
    for modulo in modulos:
        producto_existente = (
            db.query(models.InventarioModulo)
            .filter_by(clave=datos.clave, modulo_id=modulo.id)
            .first()
        )

        if producto_existente:
            # 3️⃣ Si ya existe el producto en este módulo, actualizamos datos
            producto_existente.producto = datos.producto
            producto_existente.precio = datos.precio
            producto_existente.tipo_producto = datos.tipo_producto
            # Si quieres también actualizar cantidad, descomenta la siguiente línea:
            # producto_existente.cantidad = datos.cantidad
        else:
            # 4️⃣ Si no existe, creamos un nuevo registro para este módulo
            nuevo_producto = models.InventarioModulo(
                cantidad=datos.cantidad,
                clave=datos.clave,
                producto=datos.producto,
                precio=datos.precio,
                modulo_id=modulo.id,
                tipo_producto=datos.tipo_producto
            )
            db.add(nuevo_producto)

    # 5️⃣ Guardamos todos los cambios
    db.commit()
    return {"message": "Producto agregado o actualizado en todos los módulos"}




@router.put("/actualizar_todos/{producto}", response_model=dict)
def actualizar_producto_en_todos_los_modulos(
    producto: str,
    datos: schemas.InventarioGlobalUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin, models.RolEnum.direccion]))
):
    # Buscar todos los productos con esa producto
    productos = db.query(models.InventarioModulo).filter_by(producto=producto).all()

    if not productos:
        raise HTTPException(status_code=404, detail="No se encontró ningún producto con esa producto")

    # Actualizar los campos especificados
    for producto in productos:
        if datos.producto is not None:
            producto.producto = datos.producto
        if datos.precio is not None:
            producto.precio = datos.precio
        if datos.tipo_producto is not None:
            producto.tipo_producto = datos.tipo_producto

    db.commit()
    return {"message": f"Producto '{producto}' actualizado en todos los módulos"}



@router.delete("/eliminar_todos/{clave}", response_model=dict)
def eliminar_producto_en_todos_los_modulos(
    clave: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin, models.RolEnum.direccion]))
):
    # Buscar todos los registros con la clave dada
    productos = db.query(models.InventarioModulo).filter_by(clave=clave).all()

    if not productos:
        raise HTTPException(status_code=404, detail="No se encontró ningún producto con esa clave")

    # Eliminar todos los productos encontrados
    for producto in productos:
        db.delete(producto)

    db.commit()
    return {"message": f"Producto '{clave}' eliminado de todos los módulos"}




@router.post("/preview_excel")
def preview_inventario_excel(
    modulo_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    df = pd.read_excel(archivo.file)

    # Normalizar columnas
    df.columns = [
        str(c).strip().upper()
        .replace("Á", "A").replace("É", "E")
        .replace("Í", "I").replace("Ó", "O")
        .replace("Ú", "U")
        for c in df.columns
    ]

    equivalencias = {
        "CANTIDAD": ["CANTIDAD", "QTY", "CANT", "CANTIDAD DISPONIBLE"],
        "CLAVE": ["CLAVE", "CODIGO", "CÓDIGO", "CODE"],
        "DESCRIPCION": ["DESCRIPCION", "PRODUCTO", "NOMBRE", "DESC"],
        "PRECIO": ["PRECIO", "PRECIO UNITARIO", "PRICE", "COSTO"],
    }

    columnas = {}
    for requerido, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas[requerido] = col
                break

    faltantes = [c for c in equivalencias if c not in columnas]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan columnas requeridas: {', '.join(faltantes)}"
        )

    filas_validas = []
    filas_error = []
    claves_en_excel = set()

    # 🔁 ESTE for ES CLAVE
    for index, fila in df.iterrows():
        errores = []

        clave = str(fila[columnas["CLAVE"]]).strip()
        producto = str(fila[columnas["DESCRIPCION"]]).strip()

        if not clave:
            errores.append("Clave vacía")

        if clave in claves_en_excel:
            errores.append("Clave duplicada en el archivo")
        claves_en_excel.add(clave)

        # 1️⃣ Detectar tipo PRIMERO
        tipo_producto = (
            "telefono"
            if producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
            else "accesorios"
        )

        # 2️⃣ Cantidad
        try:
            cantidad = int(fila[columnas["CANTIDAD"]])
            if cantidad < 0:
                errores.append("Cantidad negativa")
        except:
            errores.append("Cantidad inválida")

        # 3️⃣ Precio
        precio = 0
        precio_raw = str(fila[columnas["PRECIO"]]).replace("$", "").replace(",", "").strip()
        try:
            precio = int(float(precio_raw))
        except:
            if tipo_producto == "accesorios":
                errores.append("Precio inválido")

        # 4️⃣ Validación por tipo
        if tipo_producto == "accesorios" and precio <= 0:
            errores.append("Precio inválido para accesorio")

        existe = (
            db.query(models.InventarioModulo)
            .filter_by(clave=clave, modulo_id=modulo_id)
            .first()
        )

        if errores:
            filas_error.append({
                "fila": index + 2,
                "clave": clave,
                "errores": errores
            })
        else:
            filas_validas.append({
                "clave": clave,
                "producto": producto,
                "cantidad": cantidad,
                "precio": precio,
                "tipo_producto": tipo_producto,
                "accion": "actualizar" if existe else "agregar"
            })

    return {
        "validas": filas_validas,
        "errores": filas_error
    }



@router.post("/actualizar_inventario_excel", response_model=dict)
def actualizar_inventario_desde_excel(
    modulo_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    # 1️⃣ Leer el Excel
    try:
        df = pd.read_excel(archivo.file)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error al leer el archivo Excel: {e}"
        )

    # 2️⃣ Normalizar columnas
    df.columns = [
        str(c).strip().upper()
        .replace("Á", "A").replace("É", "E")
        .replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
        for c in df.columns
    ]

    # 3️⃣ Equivalencias flexibles
    equivalencias = {
        "CANTIDAD": ["CANTIDAD", "QTY", "CANT"],
        "CLAVE": ["CLAVE", "CODIGO", "CÓDIGO"],
        "DESCRIPCION": ["DESCRIPCION", "PRODUCTO", "NOMBRE"],
        "PRECIO": ["PRECIO", "PRICE", "COSTO"],
    }

    columnas = {}
    for requerido, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas[requerido] = col
                break

    faltantes = [c for c in equivalencias if c not in columnas]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan columnas requeridas: {', '.join(faltantes)}"
        )

    actualizados = 0
    agregados = 0

    # 🔑 Guardar todas las claves del Excel
    claves_excel = set()

    # 4️⃣ Procesar filas
    for _, fila in df.iterrows():
        clave = str(fila[columnas["CLAVE"]]).strip()
        producto = str(fila[columnas["DESCRIPCION"]]).strip()

        claves_excel.add(clave)

        try:
            cantidad = int(fila[columnas["CANTIDAD"]])
        except:
            raise HTTPException(
                status_code=400,
                detail=f"Cantidad inválida en la clave {clave}"
            )

        precio_str = str(fila[columnas["PRECIO"]]).replace("$", "").replace(",", "").strip()
        try:
            precio = int(float(precio_str))
        except:
            raise HTTPException(
                status_code=400,
                detail=f"Precio inválido en la clave {clave}"
            )

        tipo_producto = (
            "telefono"
            if producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
            else "accesorios"
        )

        if tipo_producto == "accesorios" and precio <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Precio inválido para accesorio ({clave})"
            )

        producto_db = (
            db.query(models.InventarioModulo)
            .filter_by(clave=clave, modulo_id=modulo_id)
            .first()
        )

        if producto_db:
            producto_db.producto = producto
            producto_db.cantidad = cantidad
            producto_db.precio = precio
            producto_db.tipo_producto = tipo_producto
            actualizados += 1
        else:
            db.add(models.InventarioModulo(
                clave=clave,
                producto=producto,
                cantidad=cantidad,
                precio=precio,
                tipo_producto=tipo_producto,
                modulo_id=modulo_id
            ))
            agregados += 1

    # 🧹 5️⃣ ELIMINAR productos que NO vienen en el Excel
    eliminados = (
        db.query(models.InventarioModulo)
        .filter(
            models.InventarioModulo.modulo_id == modulo_id,
            ~models.InventarioModulo.clave.in_(claves_excel)
        )
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "message": (
            f"Inventario del módulo {modulo_id} actualizado correctamente. "
            f"{actualizados} actualizados, "
            f"{agregados} agregados, "
            f"{eliminados} eliminados."
        )
    }



@router.post("/preview_excel_general")
def preview_inventario_excel_general(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    try:
        df = pd.read_excel(archivo.file)
    except Exception as e:
        raise HTTPException(400, f"Error al leer Excel: {e}")

    # Normalizar columnas
    df.columns = [
        str(c).strip().upper()
        .replace("Á","A").replace("É","E")
        .replace("Í","I").replace("Ó","O")
        .replace("Ú","U")
        for c in df.columns
    ]

    equivalencias = {
        "CLAVE": ["CLAVE","CODIGO","CÓDIGO","CODE"],
        "DESCRIPCION": ["DESCRIPCION","PRODUCTO","NOMBRE","DESC"],
        "CANTIDAD": ["CANTIDAD","QTY","CANT"],
        "PRECIO": ["PRECIO","PRICE","COSTO"],
    }

    columnas = {}
    for req, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas[req] = col
                break

    faltantes = [k for k in equivalencias if k not in columnas]
    if faltantes:
        raise HTTPException(400, f"Faltan columnas: {', '.join(faltantes)}")

    validos = []
    errores = []
    claves_vistas = set()

    for i, fila in df.iterrows():
        errs = []

        clave = str(fila[columnas["CLAVE"]]).strip()
        producto = str(fila[columnas["DESCRIPCION"]]).strip()

        if not clave:
            errs.append("Clave vacía")

        if clave in claves_vistas:
            errs.append("Clave duplicada en Excel")
        claves_vistas.add(clave)

        tipo_producto = "telefono" if (
            producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
        ) else "accesorios"

        try:
            cantidad = int(fila[columnas["CANTIDAD"]])
            if cantidad < 0:
                errs.append("Cantidad negativa")
        except:
            errs.append("Cantidad inválida")

        precio_raw = str(fila[columnas["PRECIO"]]).replace("$","").replace(",","").strip()
        try:
            precio = int(float(precio_raw))
        except:
            precio = 0

        if tipo_producto == "accesorios" and precio <= 0:
            errs.append("Precio inválido para accesorio")

        existe = (
            db.query(models.InventarioGeneral)
            .filter_by(clave=clave)
            .first()
        )

        if errs:
            errores.append({
                "fila": i + 2,
                "clave": clave,
                "errores": errs
            })
        else:
            validos.append({
                "clave": clave,
                "producto": producto,
                "cantidad": cantidad,
                "precio": precio,
                "tipo_producto": tipo_producto,
                "accion": "actualizar" if existe else "agregar"
            })

    return {"validas": validos, "errores": errores}



@router.post("/actualizar_inventario_excel_general")
def actualizar_inventario_excel_general(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    df = pd.read_excel(archivo.file)

    df.columns = [
        str(c).strip().upper()
        .replace("Á","A").replace("É","E")
        .replace("Í","I").replace("Ó","O")
        .replace("Ú","U")
        for c in df.columns
    ]

    claves_excel = set()  # 🔥 CLAVES QUE VIENEN EN EL EXCEL
    actualizados = 0
    agregados = 0
    eliminados = 0

    for _, fila in df.iterrows():
        clave = str(fila["CLAVE"]).strip()
        producto = str(fila["PRODUCTO"]).strip()
        cantidad = int(fila["CANTIDAD"])
        precio = int(float(str(fila["PRECIO"]).replace("$","").replace(",","")))

        claves_excel.add(clave)

        tipo_producto = "telefono" if (
            producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
        ) else "accesorios"

        existente = (
            db.query(models.InventarioGeneral)
            .filter_by(clave=clave)
            .first()
        )

        if existente:
            existente.producto = producto
            existente.cantidad = cantidad
            existente.precio = precio
            existente.tipo_producto = tipo_producto
            actualizados += 1
        else:
            db.add(models.InventarioGeneral(
                clave=clave,
                producto=producto,
                cantidad=cantidad,
                precio=precio,
                tipo_producto=tipo_producto
            ))
            agregados += 1

    # 🔥 ELIMINAR PRODUCTOS QUE NO VIENEN EN EL EXCEL
    productos_bd = db.query(models.InventarioGeneral).all()

    for prod in productos_bd:
        if prod.clave not in claves_excel:
            db.delete(prod)
            eliminados += 1

    db.commit()

    return {
        "message": (
            f"{actualizados} actualizados, "
            f"{agregados} agregados, "
            f"{eliminados} eliminados"
        )
    }





@router.post("/inventario/fisico", response_model=schemas.InventarioFisicoResponse)
def registrar_inventario_fisico(
    datos: schemas.InventarioFisicoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    nuevo = models.InventarioFisico(**datos.dict())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.get("/reportes/diferencias")
def reporte_diferencias(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    inventario_general = db.query(models.InventarioGeneral).all()
    inventario_fisico = db.query(models.InventarioFisico).all()

    # Diccionario con el físico (clave única: producto+clave)
    fisico_dict = {(p.producto, p.clave): p.cantidad for p in inventario_fisico}

    reporte = []
    for prod in inventario_general:
        cantidad_fisica = fisico_dict.get((prod.producto, prod.clave), 0)
        diferencia = cantidad_fisica - prod.cantidad
        reporte.append({
            "producto": prod.producto,
            "clave": prod.clave,
            "sistema": prod.cantidad,
            "fisico": cantidad_fisica,
            "diferencia": diferencia
        })

    return reporte


@router.post("/upload/")
async def upload_inventario(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # Validar que sea un Excel
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser Excel (.xlsx o .xls)")

    # Leer el archivo Excel
    try:
        df = pd.read_excel(file.file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al leer el archivo: {e}")

    # Validar que tenga las columnas necesarias
    columnas_validas = {"producto", "clave", "cantidad"}
    if not columnas_validas.issubset(df.columns):
        raise HTTPException(status_code=400, detail=f"El archivo debe contener las columnas: {columnas_validas}")

    # Guardar en la base de datos
    registros = []
    for _, row in df.iterrows():
        inventario = models.InventarioFisico(
            producto=row["producto"],
            clave=row["clave"],
            cantidad=int(row["cantidad"]),
            fecha=datetime.utcnow()
        )
        registros.append(inventario)

    db.bulk_save_objects(registros)
    db.commit()

    return {"status": "success", "insertados": len(registros)}





@router.post("/guardar_conteo")
def guardar_conteo(
    data: schemas.ConteoInventarioRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # 🔐 Solo admins
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not data.productos:
        raise HTTPException(status_code=400, detail="No hay productos para guardar")

    for item in data.productos:
        registro = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave == item.clave,  # ✅ FIX REAL
                models.InventarioModulo.modulo_id == data.modulo_id
            )
            .first()
        )

        if not registro:
            print("NO ENCONTRADO:", item.clave)
            continue

        registro.cantidad = item.cantidad

    db.commit()

    return {
        "ok": True,
        "message": "Inventario actualizado correctamente con conteo físico"
    }



# # Crear teléfono en inventario_general
# @router.post("/inventario/telefonos", response_model=schemas.InventarioGeneralResponse)
# def crear_telefono(
#     datos: schemas.InventarioTelefonoGeneralCreate,
#     db: Session = Depends(get_db),
#     current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
# ):
#     # Generar clave automática o esperar que venga de otro proceso
#     clave_generada = f"{datos.marca[:3].upper()}-{datos.modelo[:3].upper()}"

#     existente = db.query(models.InventarioGeneral).filter_by(clave=clave_generada).first()
#     if existente:
#         raise HTTPException(status_code=400, detail="El teléfono ya está registrado en inventario.")

#     nuevo = models.InventarioGeneral(
#         clave=clave_generada,
#         producto=f"{datos.marca.upper()} {datos.modelo.upper()}",
#         cantidad=datos.cantidad,
#         precio=int(datos.precio),
#         tipo="telefono"
#     )
#     db.add(nuevo)
#     db.commit()
#     db.refresh(nuevo)
#     return nuevo


# # Obtener todos los teléfonos
# @router.get("/inventario/telefonos", response_model=list[schemas.InventarioGeneralResponse])
# def obtener_telefonos(
#     db: Session = Depends(get_db),
#     current_user: models.Usuario = Depends(get_current_user)
# ):
#     return db.query(models.InventarioGeneral).filter_by(tipo="telefono").all()

@router.post("/inventario/fisico/upload")
def subir_inventario_fisico(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    if not archivo.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser de Excel (.xlsx o .xls)")

    try:
        df = pd.read_excel(archivo.file)

        # Validar columnas esperadas
        columnas_necesarias = {"clave", "cantidad"}
        if not columnas_necesarias.issubset(df.columns):
            raise HTTPException(
                status_code=400,
                detail=f"El archivo debe contener las columnas: {', '.join(columnas_necesarias)}"
            )

        # Borrar registros previos del inventario físico (opcional, si solo hay un corte por mes)
        db.query(models.InventarioFisico).delete()

        # Insertar nuevos registros
        registros = []
        for _, row in df.iterrows():
            inventario = models.InventarioFisico(
                clave=row["clave"],
                producto=row.get("producto", ""),  # opcional si el excel trae nombre
                cantidad=int(row["cantidad"]),
                fecha=datetime.utcnow()
            )
            registros.append(inventario)

        db.bulk_save_objects(registros)
        db.commit()

        # Comparar contra inventario general
        inventario_sistema = db.query(models.InventarioGeneral).all()
        fisico_dict = {row["clave"]: row["cantidad"] for _, row in df.iterrows()}

        reporte = []
        for prod in inventario_sistema:
            cantidad_fisica = fisico_dict.get(prod.clave, 0)
            diferencia = cantidad_fisica - prod.cantidad
            reporte.append({
                "producto": prod.producto,
                "clave": prod.clave,
                "tipo": prod.tipo,  
                "sistema": prod.cantidad,
                "fisico": cantidad_fisica,
                "diferencia": diferencia
            })

        return reporte

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {str(e)}")


# Eliminar teléfono
@router.delete("/inventario/telefonos/{telefono_id}")
def eliminar_telefono(
    telefono_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    telefono = db.query(models.InventarioGeneral).filter_by(id=telefono_id, tipo="telefono").first()
    if not telefono:
        raise HTTPException(status_code=404, detail="Teléfono no encontrado.")

    db.delete(telefono)
    db.commit()
    return {"mensaje": "Teléfono eliminado del inventario."}





@router.get("/inventario/congelar/{modulo_id}")
def congelar_inventario(modulo_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    Genera un Excel con las cantidades actuales y luego pone a 0 las cantidades
    del módulo. Solo accesible para admins.
    """

    # --- 1) Validar permiso de admin ---
    # Ajusta la comprobación según tu modelo de usuario real.
    is_admin = False
    if hasattr(current_user, "is_admin"):
        is_admin = bool(getattr(current_user, "is_admin"))
    elif hasattr(current_user, "role"):
        is_admin = getattr(current_user, "role") in ("admin", "superadmin", "owner")
    # Si tu user tiene otro campo, reemplaza la lógica anterior.
    if not is_admin:
        raise HTTPException(status_code=403, detail="Solo administradores pueden congelar el inventario")

    # --- 2) Leer inventario del módulo ---
    inventario = (
        db.query(InventarioModulo)
        .filter(InventarioModulo.modulo_id == modulo_id)
        .all()
    )

    if not inventario:
        raise HTTPException(status_code=404, detail="No hay inventario para ese módulo")

    # --- 3) Preparar datos para Excel (tomar cantidades actuales) ---
    rows = []
    for item in inventario:
        rows.append({
            "inventario_id": item.id,
            "producto": getattr(item, "producto", ""),
            "clave": getattr(item, "clave", ""),
            "cantidad_anterior": item.cantidad
        })

    # --- 4) Generar Excel EN MEMORIA (bytes buffer) ---
    try:
        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="inventario_previo", index=False)
        output.seek(0)
    except Exception as e:
        # Si la generación del archivo falla, no tocamos la BD
        raise HTTPException(status_code=500, detail=f"Error generando Excel: {e}")

    # --- 5) Poner cantidades a 0 en la BD (dentro de try/except para rollback) ---
    try:
        for item in inventario:
            item.cantidad = 0
            db.add(item)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al setear cantidades a 0: {e}")

    # --- 6) Devolver el Excel como streaming response (descarga en cliente) ---
    filename = f"inventario_modulo_{modulo_id}_congelado_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )



@router.get("/inventario/modulo/{modulo_id}/existencia")
def obtener_existencia(
    modulo_id: int,
    clave: str,
    db: Session = Depends(get_db)
):
    item = db.query(InventarioModulo).filter(
        InventarioModulo.modulo_id == modulo_id,
        InventarioModulo.clave == clave
    ).first()

    return {
        "existencia_actual": item.cantidad if item else 0
    }



@router.get("/inventario/buscar-modulos")
def buscar_producto_en_modulos(
    producto: str,
    db: Session = Depends(get_db)
):

    resultados = (
        db.query(
            models.InventarioModulo.producto,
            models.InventarioModulo.cantidad,
            models.Modulo.nombre.label("modulo")
        )
        .join(models.Modulo, models.InventarioModulo.modulo_id == models.Modulo.id)
        .filter(models.InventarioModulo.producto.ilike(f"%{producto}%"))
        .order_by(models.InventarioModulo.producto)
        .all()
    )

    return [
        {
            "producto": r.producto,
            "modulo": r.modulo,
            "cantidad": r.cantidad
        }
        for r in resultados
    ]

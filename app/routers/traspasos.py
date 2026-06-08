
from datetime import datetime, date
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido, verificar_modulo_no_congelado
from app.routers.kardex import registrar_kardex

router = APIRouter()
zona_horaria = ZoneInfo("America/Mexico_City")


# ── Crear traspaso (encargado) ────────────────────────────────────────────────

@router.post("/traspasos", response_model=schemas.TraspasoResponse)
def crear_traspaso(
    traspaso: schemas.TraspasoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.encargado)),
):
    # C3 — cantidad > 0
    if traspaso.cantidad <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")

    # C5 — módulo destino debe existir
    modulo_destino_obj = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_destino).first()
    if not modulo_destino_obj:
        raise HTTPException(status_code=400, detail=f"El módulo '{traspaso.modulo_destino}' no existe")

    # C2 — origen ≠ destino
    if current_user.modulo.nombre == traspaso.modulo_destino:
        raise HTTPException(status_code=400, detail="El módulo destino debe ser diferente al módulo origen")

    # Bloquear si el módulo origen está congelado
    verificar_modulo_no_congelado(db, current_user.modulo.id)

    # Validar stock en módulo origen
    inventario = db.query(models.InventarioModulo).filter(
        models.InventarioModulo.producto == traspaso.producto,
        models.InventarioModulo.modulo_id == current_user.modulo.id,
    ).first()

    if not inventario or inventario.cantidad < traspaso.cantidad:
        raise HTTPException(status_code=400, detail="Inventario insuficiente")

    # PASO 2 — folio automático T-X
    folio = db.execute(
        text("SELECT 'T-' || nextval('traspaso_folio_seq')")
    ).scalar()

    nuevo = models.Traspaso(
        folio=folio,
        producto=inventario.producto,
        clave=inventario.clave,
        precio=inventario.precio,
        tipo_producto=inventario.tipo_producto,
        cantidad=traspaso.cantidad,
        modulo_origen=current_user.modulo.nombre,
        modulo_destino=traspaso.modulo_destino,
        solicitado_por=current_user.id,
        fecha=datetime.now(zona_horaria),
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


# ── Aprobar o rechazar traspaso (admin) ──────────────────────────────────────

@router.put("/traspasos/{traspaso_id}", response_model=schemas.TraspasoResponse)
def actualizar_estado_traspaso(
    traspaso_id: int,
    estado: schemas.TraspasoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    traspaso = db.query(models.Traspaso).filter_by(id=traspaso_id).first()
    if not traspaso:
        raise HTTPException(status_code=404, detail="Traspaso no encontrado")

    es_admin = current_user.rol == models.RolEnum.admin
    es_destino = (
        current_user.rol == models.RolEnum.encargado
        and current_user.modulo is not None
        and current_user.modulo.nombre == traspaso.modulo_destino
    )
    if not es_admin and not es_destino:
        raise HTTPException(status_code=403, detail="Sin permiso para aprobar este traspaso")

    if traspaso.estado != "pendiente":
        raise HTTPException(status_code=400, detail="Este traspaso ya fue procesado")

    traspaso.estado = estado.estado

    if estado.estado == "aprobado":
        modulo_origen = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_origen).first()
        modulo_destino = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_destino).first()

        if not modulo_origen or not modulo_destino:
            raise HTTPException(status_code=404, detail="Módulo origen o destino no encontrado")

        inv_origen = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == traspaso.clave,
            models.InventarioModulo.modulo_id == modulo_origen.id,
        ).first()

        if not inv_origen:
            raise HTTPException(status_code=404, detail="Producto no encontrado en módulo origen")
        if inv_origen.cantidad < traspaso.cantidad:
            raise HTTPException(status_code=400, detail="Inventario insuficiente en módulo origen")

        inv_destino = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == traspaso.clave,
            models.InventarioModulo.modulo_id == modulo_destino.id,
        ).first()

        inv_origen.cantidad -= traspaso.cantidad

        if inv_destino:
            inv_destino.cantidad += traspaso.cantidad
        else:
            db.add(models.InventarioModulo(
                cantidad=traspaso.cantidad,
                clave=traspaso.clave,
                producto=traspaso.producto,
                precio=traspaso.precio,
                tipo_producto=traspaso.tipo_producto,
                modulo_id=modulo_destino.id,
            ))

        registrar_kardex(
            db=db,
            producto=traspaso.producto,
            tipo_producto=traspaso.tipo_producto,
            cantidad=traspaso.cantidad,
            tipo_movimiento="TRASPASO_SALIDA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_origen.id,
            modulo_destino_id=modulo_destino.id,
            referencia_id=traspaso.id,
        )
        registrar_kardex(
            db=db,
            producto=traspaso.producto,
            tipo_producto=traspaso.tipo_producto,
            cantidad=traspaso.cantidad,
            tipo_movimiento="TRASPASO_ENTRADA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_origen.id,
            modulo_destino_id=modulo_destino.id,
            referencia_id=traspaso.id,
        )

        traspaso.aprobado_por = current_user.id

    db.commit()
    db.refresh(traspaso)
    return traspaso


# ── Listar traspasos (autenticado) ────────────────────────────────────────────

@router.get("/traspasos", response_model=list[schemas.TraspasoResponse])
def listar_traspasos(
    folio: str | None = Query(default=None),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    modulo_origen: str | None = Query(default=None),
    modulo_destino: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    incluir_archivados: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),   # C1 — auth requerida
):
    query = db.query(models.Traspaso)

    if not incluir_archivados:
        query = query.filter(models.Traspaso.visible_en_pendientes == True)

    if folio and folio.strip():
        query = query.filter(models.Traspaso.folio.ilike(f"%{folio.strip()}%"))

    if fecha_desde:
        desde_dt = datetime.combine(fecha_desde, datetime.min.time()).replace(tzinfo=zona_horaria)
        query = query.filter(models.Traspaso.fecha >= desde_dt)

    if fecha_hasta:
        hasta_dt = datetime.combine(fecha_hasta, datetime.max.time()).replace(tzinfo=zona_horaria)
        query = query.filter(models.Traspaso.fecha <= hasta_dt)

    if modulo_origen and modulo_origen.strip():
        query = query.filter(models.Traspaso.modulo_origen == modulo_origen.strip())

    if modulo_destino and modulo_destino.strip():
        query = query.filter(models.Traspaso.modulo_destino == modulo_destino.strip())

    if estado and estado.strip():
        query = query.filter(models.Traspaso.estado == estado.strip())

    return query.order_by(models.Traspaso.fecha.desc()).all()


# ── Archivar traspaso (admin) ─────────────────────────────────────────────────

@router.put("/traspasos/{traspaso_id}/ocultar", status_code=204)
def ocultar_traspaso(
    traspaso_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    traspaso = db.query(models.Traspaso).filter(
        models.Traspaso.id == traspaso_id,
        models.Traspaso.visible_en_pendientes == True,
    ).first()

    if not traspaso:
        raise HTTPException(status_code=404, detail="Traspaso no encontrado")

    traspaso.visible_en_pendientes = False
    db.commit()


# ── Eliminar / revertir traspaso (admin) — C4 ─────────────────────────────────

@router.delete("/traspasos/{traspaso_id}")
def eliminar_traspaso(
    traspaso_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    traspaso = db.query(models.Traspaso).filter_by(id=traspaso_id).first()
    if not traspaso:
        raise HTTPException(status_code=404, detail="Traspaso no encontrado")

    folio = traspaso.folio or str(traspaso_id)

    if traspaso.estado == "aprobado":
        # Revertir el movimiento de inventario
        modulo_origen = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_origen).first()
        modulo_destino = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_destino).first()

        if not modulo_origen or not modulo_destino:
            raise HTTPException(status_code=400, detail="No se puede revertir: módulo origen o destino no encontrado")

        inv_origen = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == traspaso.clave,
            models.InventarioModulo.modulo_id == modulo_origen.id,
        ).first()

        inv_destino = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == traspaso.clave,
            models.InventarioModulo.modulo_id == modulo_destino.id,
        ).first()

        stock_destino = inv_destino.cantidad if inv_destino else 0
        if stock_destino < traspaso.cantidad:
            raise HTTPException(
                status_code=400,
                detail=f"No se puede revertir: {traspaso.modulo_destino} solo tiene "
                       f"{stock_destino} unidades de '{traspaso.producto}', "
                       f"se necesitan {traspaso.cantidad}",
            )

        # Restaurar origen
        if inv_origen:
            inv_origen.cantidad += traspaso.cantidad
        else:
            db.add(models.InventarioModulo(
                producto=traspaso.producto,
                clave=traspaso.clave,
                precio=traspaso.precio,
                tipo_producto=traspaso.tipo_producto,
                cantidad=traspaso.cantidad,
                modulo_id=modulo_origen.id,
            ))

        # Reducir destino
        if inv_destino:
            inv_destino.cantidad -= traspaso.cantidad

        # Registrar reversión en kardex (los movimientos originales se conservan)
        registrar_kardex(
            db=db,
            producto=traspaso.producto,
            tipo_producto=traspaso.tipo_producto,
            cantidad=traspaso.cantidad,
            tipo_movimiento="AJUSTE_POSITIVO",   # origen recupera stock
            usuario_id=current_user.id,
            modulo_origen_id=None,
            modulo_destino_id=modulo_origen.id,
            referencia_id=traspaso_id,
        )
        registrar_kardex(
            db=db,
            producto=traspaso.producto,
            tipo_producto=traspaso.tipo_producto,
            cantidad=traspaso.cantidad,
            tipo_movimiento="AJUSTE_NEGATIVO",   # destino pierde stock
            usuario_id=current_user.id,
            modulo_origen_id=modulo_destino.id,
            modulo_destino_id=None,
            referencia_id=traspaso_id,
        )

    db.delete(traspaso)
    db.commit()
    return {"ok": True, "message": f"Traspaso {folio} eliminado correctamente"}

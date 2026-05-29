from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app import models, schemas
from app.database import get_db
from app.utilidades import verificar_rol_requerido
from app.routers.kardex import registrar_kardex

router = APIRouter()
zona_horaria = ZoneInfo("America/Mexico_City")


def _build_response(ajuste: models.AjusteInventario) -> schemas.AjusteInventarioResponse:
    return schemas.AjusteInventarioResponse(
        id=ajuste.id,
        folio=ajuste.folio,
        modulo_id=ajuste.modulo_id,
        modulo_nombre=ajuste.modulo.nombre if ajuste.modulo else "",
        usuario_id=ajuste.usuario_id,
        usuario_nombre=(
            ajuste.usuario.nombre_completo or ajuste.usuario.username
            if ajuste.usuario else ""
        ),
        fecha=ajuste.fecha,
        motivo=ajuste.motivo,
        items=[
            schemas.AjusteItemResponse(
                id=item.id,
                clave=item.clave,
                producto=item.producto,
                cantidad_anterior=item.cantidad_anterior,
                cantidad_nueva=item.cantidad_nueva,
                delta=item.delta,
            )
            for item in ajuste.items
        ],
    )


# ── POST — Crear ajuste ────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.AjusteInventarioResponse)
def crear_ajuste(
    data: schemas.AjusteInventarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin])),
):
    if not data.productos:
        raise HTTPException(status_code=400, detail="El ajuste debe incluir al menos un producto")

    modulo = db.query(models.Modulo).filter_by(id=data.modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=400, detail=f"Módulo ID {data.modulo_id} no existe")

    # Resolver cada producto y calcular deltas
    items_data = []
    for p in data.productos:
        if p.cantidad_nueva < 0:
            raise HTTPException(
                status_code=400,
                detail=f"La cantidad física para '{p.clave}' no puede ser negativa",
            )

        inv = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == p.clave,
            models.InventarioModulo.modulo_id == data.modulo_id,
        ).first()

        if not inv:
            raise HTTPException(
                status_code=404,
                detail=f"Producto con clave '{p.clave}' no encontrado en el módulo",
            )

        delta = p.cantidad_nueva - inv.cantidad
        if delta == 0:
            continue  # sin cambio, no registrar

        items_data.append({
            "inv": inv,
            "clave": p.clave,
            "producto": inv.producto,
            "cantidad_anterior": inv.cantidad,
            "cantidad_nueva": p.cantidad_nueva,
            "delta": delta,
        })

    if not items_data:
        raise HTTPException(status_code=400, detail="No hay cambios que registrar (todas las cantidades son iguales al sistema)")

    # Generar folio I-X
    folio = db.execute(text("SELECT 'I-' || nextval('ajuste_folio_seq')")).scalar()

    ajuste = models.AjusteInventario(
        folio=folio,
        modulo_id=data.modulo_id,
        usuario_id=current_user.id,
        fecha=datetime.now(zona_horaria),
        motivo=data.motivo,
    )
    db.add(ajuste)
    db.flush()  # obtiene ajuste.id

    for d in items_data:
        inv = d["inv"]

        # Actualizar InventarioModulo
        inv.cantidad = d["cantidad_nueva"]

        # Registrar item del ajuste
        db.add(models.AjusteInventarioItem(
            ajuste_id=ajuste.id,
            producto=d["producto"],
            clave=d["clave"],
            cantidad_anterior=d["cantidad_anterior"],
            cantidad_nueva=d["cantidad_nueva"],
            delta=d["delta"],
        ))

        # Registrar kardex
        tipo_mov = "AJUSTE_POSITIVO" if d["delta"] > 0 else "AJUSTE_NEGATIVO"
        registrar_kardex(
            db=db,
            producto=d["producto"],
            tipo_producto=inv.tipo_producto,
            cantidad=abs(d["delta"]),
            tipo_movimiento=tipo_mov,
            usuario_id=current_user.id,
            modulo_origen_id=data.modulo_id if d["delta"] < 0 else None,
            modulo_destino_id=data.modulo_id if d["delta"] > 0 else None,
            referencia_id=ajuste.id,
        )

    db.commit()
    db.refresh(ajuste)
    return _build_response(ajuste)


# ── GET — Listar ajustes ───────────────────────────────────────────────────────

@router.get("/", response_model=list[schemas.AjusteInventarioResponse])
def listar_ajustes(
    modulo_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin])),
):
    query = db.query(models.AjusteInventario)
    if modulo_id:
        query = query.filter(models.AjusteInventario.modulo_id == modulo_id)
    ajustes = query.order_by(models.AjusteInventario.fecha.desc()).all()
    return [_build_response(a) for a in ajustes]


# ── GET — Detalle de un ajuste ────────────────────────────────────────────────

@router.get("/{ajuste_id}", response_model=schemas.AjusteInventarioResponse)
def obtener_ajuste(
    ajuste_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin])),
):
    ajuste = db.query(models.AjusteInventario).filter_by(id=ajuste_id).first()
    if not ajuste:
        raise HTTPException(status_code=404, detail="Ajuste no encontrado")
    return _build_response(ajuste)


# ── DELETE — Revertir ajuste ──────────────────────────────────────────────────

@router.delete("/{ajuste_id}")
def eliminar_ajuste(
    ajuste_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin])),
):
    ajuste = db.query(models.AjusteInventario).filter_by(id=ajuste_id).first()
    if not ajuste:
        raise HTTPException(status_code=404, detail="Ajuste no encontrado")

    # Validar que la reversión no deje stock negativo
    errores = []
    for item in ajuste.items:
        inv = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == item.clave,
            models.InventarioModulo.modulo_id == ajuste.modulo_id,
        ).first()

        stock_actual = inv.cantidad if inv else 0
        stock_revertido = stock_actual - item.delta  # deshacer el delta original

        if stock_revertido < 0:
            errores.append(
                f"'{item.producto}': stock actual {stock_actual}, "
                f"revertir delta {item.delta:+d} dejaría {stock_revertido}"
            )

    if errores:
        raise HTTPException(
            status_code=400,
            detail="No se puede revertir el ajuste porque quedaría stock negativo: "
            + "; ".join(errores),
        )

    # Limpiar kardex de este ajuste
    db.query(models.KardexMovimiento).filter(
        models.KardexMovimiento.referencia_id == ajuste_id,
    ).delete(synchronize_session=False)

    # Revertir inventario y registrar kardex de reversión
    for item in ajuste.items:
        inv = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.clave == item.clave,
            models.InventarioModulo.modulo_id == ajuste.modulo_id,
        ).first()

        if inv:
            inv.cantidad -= item.delta  # deshacer delta

        tipo_mov = "AJUSTE_NEGATIVO" if item.delta > 0 else "AJUSTE_POSITIVO"
        registrar_kardex(
            db=db,
            producto=item.producto,
            tipo_producto=inv.tipo_producto if inv else "accesorios",
            cantidad=abs(item.delta),
            tipo_movimiento=tipo_mov,
            usuario_id=current_user.id,
            modulo_origen_id=ajuste.modulo_id if item.delta > 0 else None,
            modulo_destino_id=ajuste.modulo_id if item.delta < 0 else None,
            referencia_id=ajuste_id,
        )

    folio = ajuste.folio
    db.delete(ajuste)
    db.commit()
    return {"ok": True, "message": f"Ajuste {folio} revertido correctamente"}

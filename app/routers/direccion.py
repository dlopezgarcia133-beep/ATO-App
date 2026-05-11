from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.config import get_current_user
from app.database import get_db

ZONA = ZoneInfo("America/Mexico_City")
MODULOS_EXCLUIR = {"v2", "cadenas c.", "mi2", "bo", "prueba"}

router = APIRouter()


def _verificar_rol(user: models.Usuario):
    if user.is_admin:
        return
    if user.rol not in (models.RolEnum.direccion, models.RolEnum.admin):
        raise HTTPException(status_code=403, detail="Sin permiso para este recurso")


@router.get("/cortes", response_model=Optional[schemas.DireccionCorteResponse])
def obtener_corte_direccion(
    modulo_id: int = Query(...),
    fecha: date = Query(...),
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    corte = (
        db.query(models.CorteDia)
        .filter(
            models.CorteDia.fecha == fecha,
            models.CorteDia.modulo_id == modulo_id,
        )
        .first()
    )

    if corte is None:
        return None

    chips = (
        db.query(models.VentaChip)
        .join(models.Usuario, models.VentaChip.empleado_id == models.Usuario.id)
        .filter(
            models.Usuario.modulo_id == modulo_id,
            models.VentaChip.fecha == fecha,
            models.VentaChip.cancelada.isnot(True),
        )
        .all()
    )

    chips_por_tipo: dict = {}
    for chip in chips:
        tipo = chip.tipo_chip or "Sin tipo"
        chips_por_tipo[tipo] = chips_por_tipo.get(tipo, 0) + 1

    ventas_db = (
        db.query(models.Venta)
        .options(joinedload(models.Venta.empleado))
        .filter(
            models.Venta.fecha == fecha,
            models.Venta.modulo_id == modulo_id,
            models.Venta.cancelada.isnot(True),
        )
        .all()
    )

    ventas_list = [
        schemas.VentaResumenItem(
            id=v.id,
            producto=v.producto,
            tipo_producto=v.tipo_producto,
            tipo_venta=v.tipo_venta,
            precio_unitario=v.precio_unitario,
            cantidad=v.cantidad,
            total=v.precio_unitario * v.cantidad,
            metodo_pago=v.metodo_pago,
            empleado_username=v.empleado.username if v.empleado else None,
            cancelada=v.cancelada or False,
        )
        for v in ventas_db
    ]

    base = schemas.CorteDiaResponse.model_validate(corte)
    return schemas.DireccionCorteResponse(
        **base.model_dump(),
        chips_count=len(chips),
        chips_por_tipo=chips_por_tipo,
        ventas=ventas_list,
    )


@router.get("/cortes-pendientes", response_model=List[schemas.CortePendienteItem])
def cortes_pendientes(
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    cortes = (
        db.query(models.CorteDia)
        .join(models.Modulo, models.CorteDia.modulo_id == models.Modulo.id)
        .filter(
            models.CorteDia.revisado_direccion == False,  # noqa: E712
            models.CorteDia.fecha >= date(2026, 5, 10),
        )
        .order_by(models.CorteDia.fecha.desc(), models.Modulo.nombre.asc())
        .all()
    )

    resultado = []
    for c in cortes:
        modulo = c.modulo
        if not modulo or modulo.nombre.lower() in MODULOS_EXCLUIR:
            continue
        ef = (
            (c.accesorios_efectivo or 0)
            + (c.telefonos_efectivo or 0)
            + (c.adicional_recargas or 0)
            + (c.adicional_transporte or 0)
            + (c.adicional_otros or 0)
            + (c.adicional_mayoreo or 0)
            - (c.salida_efectivo or 0)
        )
        ta = (c.accesorios_tarjeta or 0) + (c.telefonos_tarjeta or 0)
        resultado.append(schemas.CortePendienteItem(
            id=c.id,
            modulo_id=c.modulo_id,
            modulo_nombre=modulo.nombre,
            fecha=c.fecha,
            total_efectivo=round(ef, 2),
            total_tarjeta=round(ta, 2),
            total_general=round(ef + ta, 2),
        ))

    return resultado


@router.put("/cortes/{corte_id}/marcar-revisado", response_model=schemas.CorteRevisarResponse)
def marcar_corte_revisado(
    corte_id: int,
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    corte = db.query(models.CorteDia).filter(models.CorteDia.id == corte_id).first()
    if not corte:
        raise HTTPException(404, "Corte no encontrado")

    ahora = datetime.now(ZONA)
    corte.revisado_direccion = True
    corte.revisado_por = user.username
    corte.revisado_at = ahora

    db.add(models.NotificacionAsistencia(
        asistencia_id=None,
        usuario_id=user.id,
        username=user.username,
        modulo_id=corte.modulo_id,
        mensaje=f"✅ Tu corte del {corte.fecha} fue revisado por dirección ({user.username})",
        distancia_metros=None,
    ))

    db.commit()
    db.refresh(corte)

    return schemas.CorteRevisarResponse(
        revisado_direccion=corte.revisado_direccion,
        revisado_por=corte.revisado_por,
        revisado_at=corte.revisado_at,
    )

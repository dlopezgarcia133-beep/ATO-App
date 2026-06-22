from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo

from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.routers.kardex import registrar_kardex

router = APIRouter()


@router.post("", response_model=schemas.PlanTarifarioResponse)
def crear_plan_tarifario(
    plan: schemas.PlanTarifarioCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    modulo_id = current_user.modulo_id

    # Si hay equipo, descontar del inventario del módulo (mismo patrón que ventas)
    if plan.equipo and plan.equipo.strip():
        inventario = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.modulo_id == modulo_id,
                models.InventarioModulo.producto == plan.equipo,
                models.InventarioModulo.tipo_producto == "telefono"
            )
            .first()
        )
        if not inventario:
            raise HTTPException(400, f"No hay inventario para {plan.equipo}")
        if inventario.cantidad < 1:
            raise HTTPException(400, f"Inventario insuficiente para {plan.equipo}")
        inventario.cantidad -= 1

    nuevo = models.PlanTarifario(
        fecha=datetime.now(ZoneInfo("America/Mexico_City")),
        empleado_id=current_user.id,
        modulo_id=modulo_id,
        tipo_plan=plan.tipo_plan,
        estatus=plan.estatus,
        categoria=plan.categoria,
        clasificacion=plan.clasificacion,
        equipo=plan.equipo,
        imei=plan.imei,
        precio_equipo=plan.precio_equipo,
        plazo=plan.plazo,
        linea=plan.linea,
        cuenta=plan.cuenta,
        pago_inicial=plan.pago_inicial or False,
        monto_pago_inicial=plan.monto_pago_inicial or 0,
        metodo_pago_inicial=plan.metodo_pago_inicial,
    )
    db.add(nuevo)
    db.flush()

    # Kardex solo si se descontó equipo
    if plan.equipo and plan.equipo.strip():
        registrar_kardex(
            db=db,
            producto=plan.equipo,
            tipo_producto="telefono",
            cantidad=1,
            tipo_movimiento="VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=modulo_id,
            referencia_id=nuevo.id
        )

    # --- Venta espejo del pago inicial (entra al corte) ---
    if plan.pago_inicial and plan.monto_pago_inicial and float(plan.monto_pago_inicial) > 0:
        metodo = (plan.metodo_pago_inicial or "efectivo").strip().lower()
        monto_pi = float(plan.monto_pago_inicial)
        ahora = datetime.now(ZoneInfo("America/Mexico_City"))

        if plan.equipo and plan.equipo.strip():
            nombre_pi = f"PAGO INICIAL - {plan.equipo}"
        else:
            nombre_pi = f"PAGO INICIAL PLAN - {plan.clasificacion or ''}".strip()

        venta_pi = models.Venta(
            empleado_id=current_user.id,
            modulo_id=modulo_id,
            producto=nombre_pi,
            cantidad=1,
            precio_unitario=monto_pi,
            tipo_venta="plan",
            total=monto_pi,
            comision_id=None,
            comision_monto=None,
            metodo_pago=metodo,
            cancelada=False,
            chip_casado=None,
            fecha=ahora.date(),
            hora=ahora.time(),
            telefono_cliente=None,
            tipo_producto="telefono",
        )
        db.add(venta_pi)
        db.flush()
        nuevo.venta_pi_id = venta_pi.id

        # Acumular al CorteDia (mismo patron que ventas.py)
        try:
            fecha_corte = ahora.date()
            corte = db.query(models.CorteDia).filter(
                models.CorteDia.fecha == fecha_corte,
                models.CorteDia.modulo_id == modulo_id
            ).first()
            if not corte:
                corte = models.CorteDia(
                    fecha=fecha_corte, modulo_id=modulo_id,
                    total_efectivo=0.0, total_tarjeta=0.0,
                    adicional_recargas=0.0, adicional_transporte=0.0, adicional_otros=0.0,
                    total_sistema=0.0, total_general=0.0,
                    accesorios_efectivo=0.0, accesorios_tarjeta=0.0, accesorios_total=0.0,
                    telefonos_efectivo=0.0, telefonos_tarjeta=0.0, telefonos_total=0.0
                )
                db.add(corte)
                db.flush()

            es_efectivo = metodo == "efectivo" or metodo == "cash"
            if es_efectivo:
                corte.total_efectivo = (corte.total_efectivo or 0) + monto_pi
                corte.telefonos_efectivo = (corte.telefonos_efectivo or 0) + monto_pi
            else:
                corte.total_tarjeta = (corte.total_tarjeta or 0) + monto_pi
                corte.telefonos_tarjeta = (corte.telefonos_tarjeta or 0) + monto_pi
            corte.telefonos_total = (corte.telefonos_total or 0) + monto_pi
            corte.total_sistema = (corte.total_sistema or 0) + monto_pi
            corte.total_general = (corte.total_general or 0) + monto_pi
        except Exception as e:
            print("Error actualizando CorteDia desde plan:", e)

    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.get("", response_model=List[schemas.PlanTarifarioResponse])
def listar_planes_tarifarios(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return (
        db.query(models.PlanTarifario)
        .order_by(models.PlanTarifario.id.desc())
        .all()
    )


@router.patch("/{plan_id}/pagado")
def marcar_pagado(
    plan_id: int,
    pagado: bool,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    plan = db.query(models.PlanTarifario).filter(models.PlanTarifario.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    plan.pagado = pagado
    plan.fecha_pago = datetime.now(ZoneInfo("America/Mexico_City")) if pagado else None
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "pagado": plan.pagado, "fecha_pago": plan.fecha_pago}


@router.patch("/{plan_id}/contrato-listo")
def marcar_contrato_listo(
    plan_id: int,
    contrato_listo: bool,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    plan = db.query(models.PlanTarifario).filter(models.PlanTarifario.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    plan.contrato_listo = contrato_listo
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "contrato_listo": plan.contrato_listo}


@router.put("/{plan_id}", response_model=schemas.PlanTarifarioResponse)
def editar_plan_tarifario(
    plan_id: int,
    datos: schemas.PlanTarifarioUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    plan = db.query(models.PlanTarifario).filter(models.PlanTarifario.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # No se permite editar equipo ni monto_pago_inicial (tocan inventario/corte)
    campos = datos.dict(exclude_unset=True)
    campos.pop("equipo", None)
    campos.pop("monto_pago_inicial", None)
    for k, v in campos.items():
        setattr(plan, k, v)

    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}")
def eliminar_plan_tarifario(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    plan = db.query(models.PlanTarifario).filter(models.PlanTarifario.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # 1. Regresar el telefono al inventario del modulo
    if plan.equipo and plan.equipo.strip():
        inventario = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.modulo_id == plan.modulo_id,
                models.InventarioModulo.producto == plan.equipo,
                models.InventarioModulo.tipo_producto == "telefono",
            )
            .first()
        )
        if inventario:
            inventario.cantidad += 1

        # 2. Kardex de reversa (entrada)
        registrar_kardex(
            db=db,
            producto=plan.equipo,
            tipo_producto="telefono",
            cantidad=1,
            tipo_movimiento="CANCELACION_VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=plan.modulo_id,
            referencia_id=plan.id,
        )

    # 3. Borrar la venta espejo y restar del corte
    if plan.venta_pi_id:
        venta_pi = db.query(models.Venta).filter(models.Venta.id == plan.venta_pi_id).first()
        if venta_pi:
            monto_pi = float(venta_pi.total or 0)
            metodo = (venta_pi.metodo_pago or "efectivo").strip().lower()
            fecha_corte = venta_pi.fecha

            # 4. Restar del CorteDia
            corte = db.query(models.CorteDia).filter(
                models.CorteDia.fecha == fecha_corte,
                models.CorteDia.modulo_id == plan.modulo_id,
            ).first()
            if corte:
                es_efectivo = metodo == "efectivo" or metodo == "cash"
                if es_efectivo:
                    corte.total_efectivo = (corte.total_efectivo or 0) - monto_pi
                    corte.telefonos_efectivo = (corte.telefonos_efectivo or 0) - monto_pi
                else:
                    corte.total_tarjeta = (corte.total_tarjeta or 0) - monto_pi
                    corte.telefonos_tarjeta = (corte.telefonos_tarjeta or 0) - monto_pi
                corte.telefonos_total = (corte.telefonos_total or 0) - monto_pi
                corte.total_sistema = (corte.total_sistema or 0) - monto_pi
                corte.total_general = (corte.total_general or 0) - monto_pi

            db.delete(venta_pi)

    db.delete(plan)
    db.commit()
    return {"ok": True, "id": plan_id}

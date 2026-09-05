from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo

from app import models, schemas
from app.database import get_db
from app.routers.usuarios import get_current_user
from app.routers.kardex import registrar_kardex
from app.utilidades import mismo_folio

router = APIRouter()


def revertir_plan(
    db: Session,
    plan: models.PlanTarifario,
    current_user: models.Usuario,
    borrar_ventas_espejo: bool = True,
):
    """
    Reversion completa de un plan tarifario, en un solo lugar.

    Concentra lo que antes vivia suelto dentro de eliminar_plan_tarifario, mas
    la liberacion del IMEI, que hoy no existe en NINGUN camino.

    borrar_ventas_espejo=True  -> DELETE del plan: las ventas espejo se borran.
    borrar_ventas_espejo=False -> cancelacion desde /ventas/{id}/cancelar: las
                                  ventas espejo se marcan cancelada=True, no se
                                  borran, para no romper el historial de la
                                  pantalla de ventas ni el return del endpoint.

    NO hace commit: eso queda del lado del caller.
    """
    # ── a) Devolver el telefono al inventario del modulo ──────────────────────
    # Se usa plan.equipo, que es el nombre REAL del equipo. Nunca venta.producto:
    # la venta espejo se llama "PAGO INICIAL - X" o "X - PLAN SIN ENGANCHE", y ese
    # nombre no existe en inventario_modulo. Por eso el stock se perdia al cancelar.
    if plan.equipo and plan.equipo.strip():
        nombre_equipo = plan.equipo.strip()

        # Lookup por clave (mismo patron que cancelar_venta); fallback por nombre.
        prod_general = (
            db.query(models.InventarioGeneral)
            .filter(models.InventarioGeneral.producto == nombre_equipo)
            .first()
        )
        inventario = None
        if prod_general:
            inventario = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.clave     == prod_general.clave,
                    models.InventarioModulo.modulo_id == plan.modulo_id,
                )
                .first()
            )
        if not inventario:
            inventario = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.producto  == nombre_equipo,
                    models.InventarioModulo.modulo_id == plan.modulo_id,
                )
                .first()
            )

        if inventario:
            inventario.cantidad += 1
        else:
            print(
                f"[ALERTA revertir_plan] Plan {plan.id} equipo '{nombre_equipo}' "
                f"modulo {plan.modulo_id}: sin fila en inventario_modulo. "
                f"Stock NO devuelto, revisar manualmente."
            )

        # ── b) Kardex de reversa, con el nombre REAL del equipo ───────────────
        registrar_kardex(
            db=db,
            producto=nombre_equipo,
            tipo_producto="telefono",
            cantidad=1,
            tipo_movimiento="CANCELACION_VENTA",
            usuario_id=current_user.id,
            modulo_origen_id=None,
            modulo_destino_id=plan.modulo_id,
            referencia_id=plan.id,
        )

    # ── c) Liberar el IMEI en equipos_telcel (PASO NUEVO) ─────────────────────
    # El flujo de planes NUNCA marca un equipo como vendido. Si el IMEI de este
    # plan aparece en 'vendido', es porque una venta normal distinta lo vendio y
    # puede seguir viva: liberarlo a ciegas le quitaria el equipo a esa venta.
    # Por eso solo se libera cuando el equipo no tiene folio_venta, o cuando ese
    # folio corresponde a la venta espejo de este mismo plan.
    if plan.imei and str(plan.imei).strip():
        imei_norm = str(plan.imei).strip().upper()
        equipo = (
            db.query(models.EquiposTelcel)
            .filter(func.upper(func.trim(models.EquiposTelcel.imei)) == imei_norm)
            .first()
        )
        if equipo is None:
            print(
                f"[ALERTA revertir_plan IMEI] Plan {plan.id} imei '{plan.imei}': "
                f"no existe en equipos_telcel. Nada que liberar."
            )
        elif equipo.estatus != "vendido":
            print(
                f"[INFO revertir_plan IMEI] Plan {plan.id} imei '{plan.imei}': "
                f"estatus '{equipo.estatus}', no se toca."
            )
        else:
            venta_espejo = (
                db.query(models.Venta)
                .filter(models.Venta.id == plan.venta_pi_id)
                .first()
                if plan.venta_pi_id
                else None
            )
            folio_plan = venta_espejo.folio if venta_espejo else None

            if not (equipo.folio_venta or "").strip() or mismo_folio(equipo.folio_venta, folio_plan):
                equipo.estatus = "surtido"
                equipo.fecha_venta = None
                equipo.folio_venta = None
            else:
                print(
                    f"[ALERTA revertir_plan IMEI] Plan {plan.id} imei '{plan.imei}': "
                    f"vendido con folio_venta '{equipo.folio_venta}' que no corresponde "
                    f"a este plan. NO liberado."
                )

    # ── d) Ventas espejo: restar del CorteDia y borrarlas o cancelarlas ───────
    if plan.venta_pi_id:
        venta_pi = db.query(models.Venta).filter(models.Venta.id == plan.venta_pi_id).first()
        if venta_pi:
            # Si la venta espejo tiene folio, puede ser pago dividido:
            # recuperar todas las partes que comparten ese folio.
            if venta_pi.folio:
                ventas_pi = db.query(models.Venta).filter(
                    models.Venta.folio == venta_pi.folio,
                    models.Venta.tipo_venta == "plan",
                ).all()
            else:
                ventas_pi = [venta_pi]

            for vpi in ventas_pi:
                # Una parte ya cancelada no sigue sumando al corte: no restarla dos veces.
                if not borrar_ventas_espejo and vpi.cancelada:
                    continue

                monto_pi = float(vpi.total or 0)
                metodo = (vpi.metodo_pago or "efectivo").strip().lower()
                fecha_corte = vpi.fecha

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

                if borrar_ventas_espejo:
                    db.delete(vpi)
                else:
                    vpi.cancelada = True

    # ── e) Borrar el plan ─────────────────────────────────────────────────────
    db.delete(plan)


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

    # --- Venta espejo ---
    # Se crea en dos casos:
    #  (a) con enganche (pago inicial > 0): entra dinero y SÍ acumula al CorteDia.
    #  (b) sin enganche pero con equipo: venta espejo en $0 para que el teléfono
    #      aparezca en ventas/recibos/ticket, SIN tocar el CorteDia.
    hay_enganche = bool(plan.pago_inicial and plan.monto_pago_inicial and float(plan.monto_pago_inicial) > 0)
    hay_equipo = bool(plan.equipo and plan.equipo.strip())

    if hay_enganche:
        metodo = (plan.metodo_pago_inicial or "efectivo").strip().lower()
        monto_pi = float(plan.monto_pago_inicial)
        ahora = datetime.now(ZoneInfo("America/Mexico_City"))

        if hay_equipo:
            nombre_pi = f"PAGO INICIAL - {plan.equipo}"
        else:
            nombre_pi = f"PAGO INICIAL PLAN - {plan.clasificacion or ''}".strip()

        # Determinar las partes del pago
        if metodo == "dividido":
            monto_efe = float(plan.monto_inicial_efectivo or 0)
            monto_tar = float(plan.monto_inicial_tarjeta or 0)
            if monto_efe <= 0 or monto_tar <= 0:
                raise HTTPException(400, "En pago dividido, efectivo y tarjeta deben ser mayores a cero")
            if round(monto_efe + monto_tar, 2) != round(monto_pi, 2):
                raise HTTPException(400, f"La suma de efectivo (${monto_efe}) y tarjeta (${monto_tar}) debe ser igual al pago inicial (${monto_pi})")
            partes = [("efectivo", monto_efe), ("tarjeta", monto_tar)]
            seq = db.execute(text("SELECT nextval('venta_folio_seq')")).scalar()
            folio_pi = f"V-{seq}"
        else:
            partes = [(metodo, monto_pi)]
            folio_pi = None

        primera_venta_id = None
        for metodo_parte, monto_parte in partes:
            venta_pi = models.Venta(
                empleado_id=current_user.id,
                modulo_id=modulo_id,
                producto=nombre_pi,
                cantidad=1,
                precio_unitario=monto_parte,
                tipo_venta="plan",
                total=monto_parte,
                comision_id=None,
                comision_monto=None,
                metodo_pago=metodo_parte,
                cancelada=False,
                chip_casado=None,
                fecha=ahora.date(),
                hora=ahora.time(),
                telefono_cliente=None,
                tipo_producto="telefono",
                folio=folio_pi,
            )
            db.add(venta_pi)
            db.flush()
            if primera_venta_id is None:
                primera_venta_id = venta_pi.id

        nuevo.venta_pi_id = primera_venta_id

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

            for metodo_parte, monto_parte in partes:
                es_efectivo = metodo_parte == "efectivo" or metodo_parte == "cash"
                if es_efectivo:
                    corte.total_efectivo = (corte.total_efectivo or 0) + monto_parte
                    corte.telefonos_efectivo = (corte.telefonos_efectivo or 0) + monto_parte
                else:
                    corte.total_tarjeta = (corte.total_tarjeta or 0) + monto_parte
                    corte.telefonos_tarjeta = (corte.telefonos_tarjeta or 0) + monto_parte
                corte.telefonos_total = (corte.telefonos_total or 0) + monto_parte
                corte.total_sistema = (corte.total_sistema or 0) + monto_parte
                corte.total_general = (corte.total_general or 0) + monto_parte
        except Exception as e:
            print("Error actualizando CorteDia desde plan:", e)

    elif hay_equipo:
        # Plan sin enganche pero con equipo: venta espejo en $0 (NO toca el CorteDia).
        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
        venta_pi = models.Venta(
            empleado_id=current_user.id,
            modulo_id=modulo_id,
            producto=f"{plan.equipo} - PLAN SIN ENGANCHE",
            cantidad=1,
            precio_unitario=0,
            tipo_venta="plan",
            total=0,
            comision_id=None,
            comision_monto=None,
            metodo_pago="efectivo",
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

    revertir_plan(db, plan, current_user, borrar_ventas_espejo=True)

    db.commit()
    return {"ok": True, "id": plan_id}

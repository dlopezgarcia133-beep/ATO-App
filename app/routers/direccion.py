import calendar
from collections import defaultdict
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.config import get_current_user
from app.database import get_db

ZONA = ZoneInfo("America/Mexico_City")
MODULOS_EXCLUIR = {"v2", "cadenas c.", "mi2", "bo", "prueba"}
MODULOS_EXCLUIR_SQL = ["V2", "Cadenas C.", "MI2", "BO", "prueba"]

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


@router.get("/buscar-producto", response_model=List[schemas.ProductoBusquedaResult])
def buscar_producto(
    q: str = Query(default=""),
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    if len(q.strip()) < 2:
        return []

    rows = (
        db.query(
            models.InventarioModulo.producto,
            models.Modulo.nombre.label("modulo_nombre"),
            func.sum(models.InventarioModulo.cantidad).label("total_cant"),
        )
        .join(models.Modulo, models.InventarioModulo.modulo_id == models.Modulo.id)
        .filter(
            models.InventarioModulo.producto.ilike(f"%{q.strip()}%"),
            ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
            models.InventarioModulo.cantidad > 0,
        )
        .group_by(models.InventarioModulo.producto, models.Modulo.nombre)
        .all()
    )

    agrupado: dict = defaultdict(list)
    for row in rows:
        agrupado[row.producto].append(
            schemas.ModuloStockItem(modulo=row.modulo_nombre, cantidad=int(row.total_cant))
        )

    resultado = []
    for producto, modulos in agrupado.items():
        total = sum(m.cantidad for m in modulos)
        resultado.append(schemas.ProductoBusquedaResult(
            producto=producto,
            total=total,
            modulos=sorted(modulos, key=lambda x: x.cantidad, reverse=True),
        ))

    resultado.sort(key=lambda x: x.total, reverse=True)
    return resultado[:50]


@router.get("/stock-por-modulo", response_model=List[schemas.StockPorModuloItem])
def stock_por_modulo(
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    rows = (
        db.query(
            models.Modulo.nombre.label("modulo"),
            func.sum(models.InventarioModulo.cantidad).label("total_productos"),
            func.count(func.distinct(models.InventarioModulo.producto)).label("tipos_distintos"),
        )
        .join(models.InventarioModulo, models.Modulo.id == models.InventarioModulo.modulo_id)
        .filter(~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL))
        .group_by(models.Modulo.nombre)
        .order_by(func.sum(models.InventarioModulo.cantidad).desc())
        .all()
    )

    return [
        schemas.StockPorModuloItem(
            modulo=row.modulo,
            total_productos=int(row.total_productos or 0),
            tipos_distintos=int(row.tipos_distintos or 0),
        )
        for row in rows
    ]


MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@router.get("/estadisticas", response_model=schemas.EstadisticasMesResponse)
def estadisticas_mes(
    mes: Optional[str] = Query(default=None),
    user: models.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verificar_rol(user)

    if mes:
        try:
            año, m = int(mes[:4]), int(mes[5:7])
        except Exception:
            raise HTTPException(400, "Formato inválido. Use YYYY-MM")
    else:
        ahora = datetime.now(ZONA)
        año, m = ahora.year, ahora.month

    fecha_inicio = date(año, m, 1)
    _, ultimo_dia = calendar.monthrange(año, m)
    fecha_fin = date(año, m, ultimo_dia)
    dt_inicio = datetime(año, m, 1, 0, 0, 0)
    dt_fin = datetime(año, m, ultimo_dia, 23, 59, 59, 999999)

    periodo_texto = f"{MESES_ES[m - 1]} {año}"
    mes_str = f"{año:04d}-{m:02d}"

    # ── Filtros base ──────────────────────────────────────────────────────────
    # Teléfonos Y accesorios están TODOS en la tabla 'ventas'.
    # Se distinguen por tipo_producto = 'telefono' (case-insensitive).
    f_ventas = [
        models.Venta.fecha >= fecha_inicio,
        models.Venta.fecha <= fecha_fin,
        models.Venta.cancelada.isnot(True),
        ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
    ]
    f_ventas_tel = f_ventas + [models.Venta.tipo_producto.ilike("telefono")]
    f_ventas_acc = f_ventas + [~models.Venta.tipo_producto.ilike("telefono")]

    f_chips = [
        models.VentaChip.fecha >= fecha_inicio,
        models.VentaChip.fecha <= fecha_fin,
        models.VentaChip.cancelada.isnot(True),
        ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
    ]

    # ── Teléfonos (tabla ventas, tipo_producto = 'telefono') ──────────────────
    # Clasificación por tipo_venta: Contado / Pajoy (o Payjoy) / Paguitos
    tel_tipo_rows = (
        db.query(
            models.Venta.tipo_venta,
            func.count(models.Venta.id).label("cnt"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("monto"),
        )
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas_tel)
        .group_by(models.Venta.tipo_venta)
        .all()
    )

    contado: dict = {"cantidad": 0, "monto": 0.0}
    payjoy: dict = {"cantidad": 0, "monto": 0.0}
    paguitos: dict = {"cantidad": 0, "monto": 0.0}
    sin_clasificar: dict = {"cantidad": 0, "monto": 0.0}

    for row in tel_tipo_rows:
        tv = (row.tipo_venta or "").strip().lower()
        cnt = int(row.cnt or 0)
        monto_t = float(row.monto or 0)
        if tv in ("pajoy", "payjoy"):
            payjoy["cantidad"] += cnt
            payjoy["monto"] += monto_t
        elif tv == "paguitos":
            paguitos["cantidad"] += cnt
            paguitos["monto"] += monto_t
        elif not tv:
            sin_clasificar["cantidad"] += cnt
            sin_clasificar["monto"] += monto_t
        else:
            contado["cantidad"] += cnt
            contado["monto"] += monto_t

    total_telefonos = (
        contado["cantidad"] + payjoy["cantidad"]
        + paguitos["cantidad"] + sin_clasificar["cantidad"]
    )

    # ── Accesorios (tabla ventas, excluyendo tipo_producto = 'telefono') ──────
    acc_agg = (
        db.query(
            func.sum(models.Venta.cantidad).label("total_unidades"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("monto_total"),
        )
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas_acc)
        .first()
    )
    total_unidades_acc = int(acc_agg.total_unidades or 0)
    monto_acc = float(acc_agg.monto_total or 0)

    top5 = (
        db.query(
            models.Venta.producto,
            func.sum(models.Venta.cantidad).label("total_cantidad"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("total_monto"),
        )
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas_acc)
        .group_by(models.Venta.producto)
        .order_by(func.sum(models.Venta.cantidad).desc())
        .limit(5)
        .all()
    )

    # Total MXN = todas las ventas (teléfonos + accesorios)
    total_mxn_row = (
        db.query(
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("total"),
        )
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas)
        .first()
    )
    total_ventas_mxn = round(float(total_mxn_row.total or 0), 2)

    # ── Chips ─────────────────────────────────────────────────────────────────
    chips_tipo_rows = (
        db.query(
            models.VentaChip.tipo_chip,
            func.count(models.VentaChip.id).label("cnt"),
        )
        .join(models.Usuario, models.VentaChip.empleado_id == models.Usuario.id)
        .join(models.Modulo, models.Usuario.modulo_id == models.Modulo.id)
        .filter(*f_chips)
        .group_by(models.VentaChip.tipo_chip)
        .order_by(func.count(models.VentaChip.id).desc())
        .all()
    )

    chips_monto_rows = (
        db.query(
            models.VentaChip.monto_recarga,
            func.count(models.VentaChip.id).label("cnt"),
        )
        .join(models.Usuario, models.VentaChip.empleado_id == models.Usuario.id)
        .join(models.Modulo, models.Usuario.modulo_id == models.Modulo.id)
        .filter(*f_chips)
        .group_by(models.VentaChip.monto_recarga)
        .all()
    )

    total_chips = sum(int(r.cnt or 0) for r in chips_tipo_rows)

    # Normalizar montos de chips en buckets (chips < $50 se omiten)
    _BUCKET_ORDER = ["$50", "$100", "$150", "$200", "$Otro"]

    def _bucket_monto(m: float) -> Optional[str]:
        if m < 50:
            return None
        elif m < 90:
            return "$50"
        elif m < 125:
            return "$100"
        elif m < 175:
            return "$150"
        elif m < 225:
            return "$200"
        else:
            return "$Otro"

    monto_buckets: dict = defaultdict(int)
    for row in chips_monto_rows:
        label = _bucket_monto(float(row.monto_recarga or 0))
        if label is not None:
            monto_buckets[label] += int(row.cnt or 0)

    por_monto_recarga = [
        schemas.MontoRecargaStatItem(monto=label, cantidad=cnt)
        for label, cnt in sorted(
            monto_buckets.items(),
            key=lambda x: _BUCKET_ORDER.index(x[0]) if x[0] in _BUCKET_ORDER else 99,
        )
        if cnt > 0
    ]

    # ── Planes ────────────────────────────────────────────────────────────────
    planes_tramite_rows = (
        db.query(
            func.trim(models.Plan.tipo_tramite).label("tramite"),
            func.count(models.Plan.id).label("cnt"),
        )
        .join(models.Modulo, models.Plan.modulo_id == models.Modulo.id)
        .filter(
            models.Plan.fecha >= dt_inicio,
            models.Plan.fecha <= dt_fin,
            ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
        )
        .group_by(func.trim(models.Plan.tipo_tramite))
        .order_by(func.count(models.Plan.id).desc())
        .all()
    )

    planes_plan_rows = (
        db.query(
            func.trim(models.Plan.tipo_plan).label("plan"),
            func.count(models.Plan.id).label("cnt"),
        )
        .join(models.Modulo, models.Plan.modulo_id == models.Modulo.id)
        .filter(
            models.Plan.fecha >= dt_inicio,
            models.Plan.fecha <= dt_fin,
            ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
        )
        .group_by(func.trim(models.Plan.tipo_plan))
        .order_by(func.count(models.Plan.id).desc())
        .all()
    )

    total_planes = sum(int(r.cnt or 0) for r in planes_tramite_rows)

    # ── Por módulo ────────────────────────────────────────────────────────────
    modulo_map: dict = defaultdict(lambda: {"total_mxn": 0.0, "telefonos": 0, "chips": 0, "accesorios": 0})

    acc_mod = (
        db.query(
            models.Modulo.nombre.label("modulo"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("monto"),
            func.sum(models.Venta.cantidad).label("unidades"),
        )
        .select_from(models.Venta)
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas_acc)
        .group_by(models.Modulo.nombre)
        .all()
    )
    for row in acc_mod:
        modulo_map[row.modulo]["total_mxn"] += float(row.monto or 0)
        modulo_map[row.modulo]["accesorios"] += int(row.unidades or 0)

    tel_mod = (
        db.query(
            models.Modulo.nombre.label("modulo"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("monto"),
            func.count(models.Venta.id).label("cnt"),
        )
        .select_from(models.Venta)
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas_tel)
        .group_by(models.Modulo.nombre)
        .all()
    )
    for row in tel_mod:
        modulo_map[row.modulo]["total_mxn"] += float(row.monto or 0)
        modulo_map[row.modulo]["telefonos"] += int(row.cnt or 0)

    chips_mod = (
        db.query(
            models.Modulo.nombre.label("modulo"),
            func.count(models.VentaChip.id).label("cnt"),
        )
        .select_from(models.VentaChip)
        .join(models.Usuario, models.VentaChip.empleado_id == models.Usuario.id)
        .join(models.Modulo, models.Usuario.modulo_id == models.Modulo.id)
        .filter(*f_chips)
        .group_by(models.Modulo.nombre)
        .all()
    )
    for row in chips_mod:
        modulo_map[row.modulo]["chips"] += int(row.cnt or 0)

    por_modulo = sorted(
        [
            schemas.ModuloEstadItem(
                modulo=mod,
                total_mxn=round(vals["total_mxn"], 2),
                telefonos=vals["telefonos"],
                chips=vals["chips"],
                accesorios=vals["accesorios"],
            )
            for mod, vals in modulo_map.items()
        ],
        key=lambda x: x.total_mxn,
        reverse=True,
    )

    # ── Ventas por día (todas las ventas = accesorios + teléfonos) ────────────
    dia_rows = (
        db.query(
            extract("day", models.Venta.fecha).label("dia"),
            func.sum(models.Venta.precio_unitario * models.Venta.cantidad).label("total"),
        )
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(*f_ventas)
        .group_by(extract("day", models.Venta.fecha))
        .all()
    )
    dia_total: dict = {int(r.dia): float(r.total or 0) for r in dia_rows}

    ventas_por_dia = [
        schemas.VentaDiaItem(dia=d, total=round(dia_total.get(d, 0.0), 2))
        for d in range(1, ultimo_dia + 1)
    ]

    # ── Teléfonos por módulo (venta_telefonos, agrupado por módulo y tipo) ────
    f_vt = [
        models.VentaTelefono.fecha >= fecha_inicio,
        models.VentaTelefono.fecha <= fecha_fin,
        models.VentaTelefono.cancelada.isnot(True),
        ~models.Modulo.nombre.in_(MODULOS_EXCLUIR_SQL),
    ]

    tel_mod_tipo_rows = (
        db.query(
            models.Modulo.nombre.label("modulo"),
            models.VentaTelefono.tipo,
            func.count(models.VentaTelefono.id).label("cnt"),
            func.sum(models.VentaTelefono.precio_venta).label("monto"),
        )
        .select_from(models.VentaTelefono)
        .join(models.Modulo, models.VentaTelefono.modulo_id == models.Modulo.id)
        .filter(*f_vt)
        .group_by(models.Modulo.nombre, models.VentaTelefono.tipo)
        .all()
    )

    tel_mod_map: dict = defaultdict(
        lambda: {"total": 0, "monto": 0.0, "contado": 0, "payjoy": 0, "paguitos": 0}
    )
    for row in tel_mod_tipo_rows:
        t = (row.tipo or "").strip().lower()
        cnt = int(row.cnt or 0)
        m = float(row.monto or 0)
        tel_mod_map[row.modulo]["total"] += cnt
        tel_mod_map[row.modulo]["monto"] += m
        if t in ("pajoy", "payjoy"):
            tel_mod_map[row.modulo]["payjoy"] += cnt
        elif t == "paguitos":
            tel_mod_map[row.modulo]["paguitos"] += cnt
        else:
            tel_mod_map[row.modulo]["contado"] += cnt

    telefonos_por_modulo = sorted(
        [
            schemas.TelefonoModuloItem(
                modulo=mod,
                total_telefonos=vals["total"],
                monto_total=round(vals["monto"], 2),
                contado=vals["contado"],
                payjoy=vals["payjoy"],
                paguitos=vals["paguitos"],
            )
            for mod, vals in tel_mod_map.items()
            if vals["total"] > 0
        ],
        key=lambda x: x.total_telefonos,
        reverse=True,
    )

    # ── Respuesta ─────────────────────────────────────────────────────────────
    return schemas.EstadisticasMesResponse(
        mes=mes_str,
        periodo_texto=periodo_texto,
        resumen_general=schemas.ResumenGeneralStats(
            total_ventas_mxn=total_ventas_mxn,
            total_telefonos=total_telefonos,
            total_chips=total_chips,
            total_accesorios=total_unidades_acc,
            total_planes=total_planes,
        ),
        telefonos=schemas.TelefonosStats(
            total=total_telefonos,
            contado=schemas.CantidadMonto(
                cantidad=contado["cantidad"], monto=round(contado["monto"], 2)
            ),
            payjoy=schemas.CantidadMonto(
                cantidad=payjoy["cantidad"], monto=round(payjoy["monto"], 2)
            ),
            paguitos=schemas.CantidadMonto(
                cantidad=paguitos["cantidad"], monto=round(paguitos["monto"], 2)
            ),
            sin_clasificar=schemas.CantidadMonto(
                cantidad=sin_clasificar["cantidad"], monto=round(sin_clasificar["monto"], 2)
            ),
        ),
        accesorios=schemas.AccesoriosStats(
            total_unidades=total_unidades_acc,
            monto_total=round(monto_acc, 2),
            top_5_productos=[
                schemas.TopProductoItem(
                    producto=r.producto,
                    cantidad=int(r.total_cantidad or 0),
                    monto=round(float(r.total_monto or 0), 2),
                )
                for r in top5
            ],
        ),
        chips=schemas.ChipsStats(
            total=total_chips,
            por_tipo=[
                schemas.TipoChipStatItem(
                    tipo_chip=r.tipo_chip or "Sin tipo",
                    cantidad=int(r.cnt or 0),
                )
                for r in chips_tipo_rows
            ],
            por_monto_recarga=por_monto_recarga,
        ),
        planes=schemas.PlanesStats(
            total=total_planes,
            por_tramite=[
                schemas.TramiteStatItem(
                    tramite=r.tramite or "Sin trámite",
                    cantidad=int(r.cnt or 0),
                )
                for r in planes_tramite_rows
            ],
            por_plan=[
                schemas.PlanStatItem(
                    plan=r.plan or "Sin plan",
                    cantidad=int(r.cnt or 0),
                )
                for r in planes_plan_rows
            ],
        ),
        por_modulo=por_modulo,
        ventas_por_dia=ventas_por_dia,
        telefonos_por_modulo=telefonos_por_modulo,
    )

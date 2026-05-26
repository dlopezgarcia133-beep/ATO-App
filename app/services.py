
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app import models
from sqlalchemy import case, func



from sqlalchemy import func, case

def obtener_comisiones_por_empleado_optimizado(db: Session, inicio: date, fin: date):

    _base = func.coalesce(models.Comision.cantidad, 0)
    _extra = case(
        (models.Venta.tipo_venta == "Contado",  10),
        (models.Venta.tipo_venta == "Pajoy",   100),
        (models.Venta.tipo_venta == "Paguitos",110),
        else_=0
    )
    # Contado con comision especial: solo base (sin sumar $10)
    _unitaria_tel = case(
        (
            (models.Venta.tipo_venta == "Contado") & (_base > 0),
            _base
        ),
        else_=_base + _extra
    )
    ventas_rows = (
        db.query(
            models.Venta.empleado_id,
            func.sum(
                case(
                    (models.Venta.tipo_producto == "telefono",
                     _unitaria_tel * models.Venta.cantidad),
                    else_=_base * models.Venta.cantidad
                )
            ).label("total_comisiones")
        )
        .outerjoin(models.Comision, models.Comision.id == models.Venta.comision_id)
        .filter(
            models.Venta.cancelada == False,
            models.Venta.fecha.between(inicio, fin)
        )
        .group_by(models.Venta.empleado_id)
        .all()
    )

    chips_rows = (
        db.query(
            models.VentaChip.empleado_id,
            func.sum(models.VentaChip.comision).label("total_chips")
        )
        .filter(
            models.VentaChip.cancelada == False,
            models.VentaChip.validado == True,
            models.VentaChip.numero_telefono.isnot(None),
            models.VentaChip.fecha.between(inicio, fin)
        )
        .group_by(models.VentaChip.empleado_id)
        .all()
    )

    comisiones = {}

    for r in ventas_rows:
        comisiones[r.empleado_id] = float(r.total_comisiones or 0)

    for r in chips_rows:
        comisiones[r.empleado_id] = comisiones.get(r.empleado_id, 0) + float(r.total_chips or 0)

    return comisiones








def obtener_desglose_comisiones_por_empleado(db: Session, inicio: date, fin: date) -> dict:
    """Returns {empleado_id: {accesorios, telefonos, chips, total}} in one query per table."""
    ventas_rows = (
        db.query(
            models.Venta.empleado_id,
            func.sum(
                case(
                    (models.Venta.tipo_producto != "telefono",
                     func.coalesce(models.Comision.cantidad, 0) * models.Venta.cantidad),
                    else_=0
                )
            ).label("total_accesorios"),
            func.sum(
                case(
                    (models.Venta.tipo_producto == "telefono",
                     case(
                         (
                             (models.Venta.tipo_venta == "Contado") &
                             (func.coalesce(models.Comision.cantidad, 0) > 0),
                             func.coalesce(models.Comision.cantidad, 0) * models.Venta.cantidad
                         ),
                         else_=(
                             func.coalesce(models.Comision.cantidad, 0) +
                             case(
                                 (models.Venta.tipo_venta == "Contado",  10),
                                 (models.Venta.tipo_venta == "Pajoy",   100),
                                 (models.Venta.tipo_venta == "Paguitos",110),
                                 else_=0
                             )
                         ) * models.Venta.cantidad
                     )),
                    else_=0
                )
            ).label("total_telefonos"),
        )
        .outerjoin(models.Comision, models.Comision.id == models.Venta.comision_id)
        .filter(models.Venta.cancelada == False, models.Venta.fecha.between(inicio, fin))
        .group_by(models.Venta.empleado_id)
        .all()
    )

    chips_rows = (
        db.query(
            models.VentaChip.empleado_id,
            func.sum(models.VentaChip.comision).label("total_chips")
        )
        .filter(
            models.VentaChip.cancelada == False,
            models.VentaChip.validado == True,
            models.VentaChip.numero_telefono.isnot(None),
            models.VentaChip.fecha.between(inicio, fin)
        )
        .group_by(models.VentaChip.empleado_id)
        .all()
    )

    result: dict = {}
    for r in ventas_rows:
        acc = float(r.total_accesorios or 0)
        tel = float(r.total_telefonos or 0)
        result[r.empleado_id] = {"accesorios": acc, "telefonos": tel, "chips": 0.0, "total": acc + tel}

    for r in chips_rows:
        chips = float(r.total_chips or 0)
        if r.empleado_id in result:
            result[r.empleado_id]["chips"] = chips
            result[r.empleado_id]["total"] += chips
        else:
            result[r.empleado_id] = {"accesorios": 0.0, "telefonos": 0.0, "chips": chips, "total": chips}

    return result


def calcular_totales_comisiones(
    db: Session,
    empleado_id: int,
    inicio: date,
    fin: date
) -> dict:

    ventas = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha >= inicio,
        models.Venta.fecha <= fin,
        models.Venta.cancelada == False
    ).all()

    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_id,
        models.VentaChip.cancelada == False,
        models.VentaChip.validado == True,
        models.VentaChip.numero_telefono.isnot(None),
        models.VentaChip.fecha >= inicio,
        models.VentaChip.fecha <= fin,
    ).all()

    total_accesorios = 0.0
    total_telefonos = 0.0
    total_chips = 0.0

    _extra_por_tipo = {"Contado": 10, "Paguitos": 110, "Pajoy": 100}

    for v in ventas:
        comision_base = getattr(getattr(v, "comision_obj", None), "cantidad", 0) or 0
        cantidad = getattr(v, "cantidad", 0) or 0

        if v.tipo_producto == "telefono":
            tipo = v.tipo_venta or ""
            if tipo == "Contado" and comision_base > 0:
                comision_total = comision_base * cantidad
            else:
                comision_total = (comision_base + _extra_por_tipo.get(tipo, 0)) * cantidad
            total_telefonos += comision_total

        elif v.tipo_producto == "accesorios":
            total_accesorios += comision_base * cantidad

    for v in ventas_chips:
        total_chips += float(getattr(v, "comision", 0) or 0)

    return {
        "accesorios": total_accesorios,
        "telefonos": total_telefonos,
        "chips": total_chips,
        "total": total_accesorios + total_telefonos + total_chips
    }






from datetime import date, timedelta
from sqlalchemy.orm import Session
from app import models
from sqlalchemy import case, func



from sqlalchemy import func, case

def obtener_comisiones_por_empleado_optimizado(db: Session, inicio: date, fin: date):

    ventas_rows = (
        db.query(
            models.Venta.empleado_id,
            func.sum(
                func.coalesce(models.Comision.cantidad, 0) * models.Venta.cantidad +
                case(
                    (
                        models.Venta.tipo_producto == "telefono",
                        case(
                            (models.Venta.tipo_venta == "Contado", 10),
                            (models.Venta.tipo_venta == "Pajoy", 100),
                            (models.Venta.tipo_venta == "Paguitos", 110),
                            else_=0
                        )
                    ),
                    else_=0
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
        models.VentaChip.numero_telefono.isnot(None),
        models.VentaChip.validado == True,
        models.VentaChip.fecha >= inicio,
        models.VentaChip.fecha <= fin,
    ).all()

    total_accesorios = 0.0
    total_telefonos = 0.0
    total_chips = 0.0

    comisiones_por_tipo = {
        "Contado": 10,
        "Paguitos": 110,
        "Pajoy": 100
    }

    for v in ventas:
        comision_base = getattr(getattr(v, "comision_obj", None), "cantidad", 0) or 0
        cantidad = getattr(v, "cantidad", 0) or 0
        comision_total = comision_base * cantidad

        if v.tipo_producto == "telefono":
            comision_total += comisiones_por_tipo.get(v.tipo_venta or "", 0)
            total_telefonos += comision_total

        elif v.tipo_producto == "accesorio":
            total_accesorios += comision_total

    for v in ventas_chips:
        total_chips += float(getattr(v, "comision", 0) or 0)

    return {
        "accesorios": total_accesorios,
        "telefonos": total_telefonos,
        "chips": total_chips,
        "total": total_accesorios + total_telefonos + total_chips
    }





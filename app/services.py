
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app import models
from sqlalchemy import case, func



from sqlalchemy import func, case

def obtener_comisiones_por_empleado_optimizado(
    db: Session,
    inicio: date,
    fin: date
):

    rows = (
        db.query(
            models.Venta.empleado_id,

            func.sum(
                # comisión por producto (si existe)
                func.coalesce(models.Comision.cantidad, 0) * models.Venta.cantidad +

                # comisión extra SOLO para teléfonos
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
        .outerjoin(
            models.Comision,
            models.Comision.id == models.Venta.comision_id
        )
        .filter(
            models.Venta.cancelada == False,
            models.Venta.fecha >= inicio,
            models.Venta.fecha <= fin
        )
        .group_by(models.Venta.empleado_id)
        .all()
    )

    return {r.empleado_id: float(r.total_comisiones or 0) for r in rows}

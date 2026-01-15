
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app import models




def calcular_totales_comisiones(
    db: Session,
    empleado_id: int,
    inicio: date,
    fin: date
) -> dict:

    ventas = db.query(models.Venta).filter(
        models.Venta.empleado_id == empleado_id,
        models.Venta.fecha.between(inicio, fin),
        models.Venta.cancelada == False
    ).all()

    ventas_chips = db.query(models.VentaChip).filter(
        models.VentaChip.empleado_id == empleado_id,
        models.VentaChip.numero_telefono.isnot(None),
        models.VentaChip.validado == True,
        models.VentaChip.fecha.between(inicio, fin),
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
        cantidad = v.cantidad or 1

        # Comisión por producto (si existe)
        comision_producto = (
            getattr(getattr(v, "comision_obj", None), "cantidad", 0) or 0
        ) * cantidad

        # Comisión por tipo de venta (solo teléfonos)
        comision_tipo = comisiones_por_tipo.get(
            v.tipo_venta or "", 0
        ) if v.tipo_producto == "telefono" else 0

        comision_total = comision_producto + comision_tipo

        if v.tipo_producto == "accesorio":
            total_accesorios += comision_producto

        elif v.tipo_producto == "telefono":
            total_telefonos += comision_total

    for v in ventas_chips:
        total_chips += float(getattr(v, "comision", 0) or 0)

    total_general = total_accesorios + total_telefonos + total_chips

    return {
        "total_accesorios": total_accesorios,
        "total_telefonos": total_telefonos,
        "total_chips": total_chips,
        "total_general": total_general
    }

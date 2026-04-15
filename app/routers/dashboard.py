
from http.client import HTTPException
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta
from sqlalchemy import  case
from app.database import get_db
from app import models
from app import schemas

router = APIRouter()


@router.get("/ventas-dia")
def ventas_dia(db: Session = Depends(get_db)):

    hoy = date.today()

    data = db.query(
        models.Modulo.nombre.label("modulo"),
        func.sum(models.Venta.total).label("total")
    ).join(
        models.Modulo,
        models.Modulo.id == models.Venta.modulo_id
    ).filter(
        models.Venta.fecha == hoy
    ).group_by(
        models.Modulo.nombre
    ).all()

    return [dict(row._mapping) for row in data]


@router.get("/comisiones-semana")
def comisiones_semana(db: Session = Depends(get_db)):

    hoy = date.today()
    inicio = hoy - timedelta(days=hoy.weekday())

    data = db.query(
        models.Venta.empleado_id,
            func.sum(models.Comision.cantidad).label("total")
        ).filter(
        func.date(models.Venta.fecha) >= inicio
    ).group_by(
        models.Venta.empleado_id
    ).all()

    return [
        {
            "empleado_id": d.empleado_id,
            "total_comision": float(d.total or 0)
        }
        for d in data
    ]



@router.get("/inventario")
def inventario(db: Session = Depends(get_db)):

    data = db.query(
        models.InventarioModulo.modulo_id,
        models.InventarioModulo.producto,
        models.InventarioModulo.cantidad
    ).all()

    return [
        {
            "modulo_id": d.modulo_id,
            "producto": d.producto,
            "cantidad": d.cantidad
        }
        for d in data
    ]



@router.get("/traspasos")
def traspasos(db: Session = Depends(get_db)):

    data = db.query(
        models.Traspaso.producto,
        models.Traspaso.modulo_origen,
        models.Traspaso.modulo_destino,
        models.Traspaso.estado,
        models.Traspaso.fecha
    ).all()

    resultado = []

    for row in data:
        resultado.append({
            "producto": row.producto,
            "modulo_origen": row.modulo_origen,
            "modulo_destino": row.modulo_destino,
            "estado": row.estado.value,
            "fecha": row.fecha
        })

    return resultado


@router.get("/nomina")
def nomina(db: Session = Depends(get_db)):

    data = db.query(
        models.NominaEmpleado.usuario_id,
        models.NominaEmpleado.total_comisiones,
        models.NominaEmpleado.horas_extra,
        models.NominaEmpleado.sanciones,
        models.NominaEmpleado.total_pagar,
        models.NominaPeriodo.fecha_inicio,
        models.NominaPeriodo.fecha_fin,
        models.Usuario.username
    ).join(
        models.NominaPeriodo,
        models.NominaPeriodo.id == models.NominaEmpleado.periodo_id
    ).join(
        models.Usuario,
        models.Usuario.id == models.NominaEmpleado.usuario_id
    ).all()

    return [dict(row._mapping) for row in data]




@router.get("/ventas-empleado")
def ventas_empleado(db: Session = Depends(get_db)):

    data = db.query(
        models.Usuario.id.label("empleado_id"),
        models.Usuario.username.label("empleado"),
        models.Modulo.id.label("modulo_id"),
        models.Modulo.nombre.label("modulo"),
    ).join(
        models.Usuario,
        models.Usuario.id == models.Venta.empleado_id
    ).join(
        models.Modulo,
        models.Modulo.id == models.Venta.modulo_id
    ).filter(
        models.Venta.cancelada == False
    ).group_by(
        models.Usuario.username,
        models.Modulo.nombre
    ).all()

    return [dict(row._mapping) for row in data]




@router.get("/empleados")
def empleados(db: Session = Depends(get_db)):

    data = db.query(
        models.Usuario.id,
        models.Usuario.username.label("nombre_usuario"),
        models.Modulo.id.label("modulo_id"),
        models.Modulo.nombre.label("modulo")
    ).join(
        models.Modulo,
        models.Modulo.id == models.Usuario.modulo_id,
        isouter=True
    ).filter(
        models.Usuario.activo == True
    ).all()

    return [dict(row._mapping) for row in data]


@router.get("/modulos")
def modulos(db: Session = Depends(get_db)):

    data = db.query(
        models.Modulo.id,
        models.Modulo.nombre
    ).all()

    return [dict(row._mapping) for row in data]


@router.get("/ventas-modulo")
def ventas_modulo(db: Session = Depends(get_db)):

    data = db.query(
        models.Usuario.id,
        models.Usuario.username.label("nombre_usuario"),
        models.Modulo.id.label("modulo_id"),
        models.Modulo.nombre.label("modulo"),
        func.sum(models.Venta.total).label("total")
    ).join(
        models.Modulo,
        models.Modulo.id == models.Venta.modulo_id
    ).group_by(
        models.Modulo.id,
        models.Modulo.nombre
    ).all()

    return [dict(row._mapping) for row in data]



from datetime import date
from fastapi import Query
from sqlalchemy.orm import aliased


@router.get("/ventas-detalle")
def ventas_detalle(
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db)
):

    query = db.query(
        models.Venta.id,
        models.Venta.fecha,
        models.Venta.hora,
        models.Usuario.id.label("empleado_id"),
        models.Modulo.id.label("modulo_id"),

        # 🔹 Datos visuales
        models.Usuario.username.label("nombre_usuario"),
        models.Usuario.rol,
        models.Modulo.id.label("modulo_id"),
        models.Modulo.nombre.label("modulo"),
        models.Venta.producto,
        models.Venta.tipo_producto,
        models.Venta.cantidad,
        models.Venta.precio_unitario,
        models.Venta.total,
        models.Venta.metodo_pago
    ).join(
        models.Usuario,
        models.Usuario.id == models.Venta.empleado_id
    ).join(
        models.Modulo,
        models.Modulo.id == models.Venta.modulo_id
    ).filter(
        models.Venta.cancelada == False
    )

    # filtros opcionales
    if fecha_inicio:
        query = query.filter(models.Venta.fecha >= fecha_inicio)

    if fecha_fin:
        query = query.filter(models.Venta.fecha <= fecha_fin)

    data = query.order_by(models.Venta.fecha.desc()).all()

    return [dict(row._mapping) for row in data]


from sqlalchemy import func, case

@router.get("/metricas/empleados")
def metricas_empleados(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    mes: int | None = None,
    anio: int | None = None,
    modulo_id: int | None = Query(None),
    db: Session = Depends(get_db)
):
    hoy = date.today()

    if fecha_inicio and fecha_fin:
        inicio = fecha_inicio
        fin = fecha_fin
    elif mes and anio:
        inicio = date(anio, mes, 1)
        fin = date(anio, mes + 1, 1) - timedelta(days=1) if mes < 12 else date(anio, 12, 31)
    else:
        inicio = hoy.replace(day=1)
        fin = hoy

    query = db.query(
        models.Venta.empleado_id,
        models.Usuario.username,

        func.sum(
            case(
                (models.Venta.tipo_producto == "accesorios",
                 models.Venta.precio_unitario * models.Venta.cantidad),
                else_=0
            )
        ).label("total_accesorios"),

        func.sum(
            case(
                (models.Venta.tipo_producto == "telefono",
                 models.Venta.precio_unitario * models.Venta.cantidad),
                else_=0
            )
        ).label("total_telefonos"),

        func.sum(
            case((func.lower(models.Venta.tipo_venta).like("%contado%"), 1), else_=0)
        ).label("contado"),

        func.sum(
            case((func.lower(models.Venta.tipo_venta).like("%paguitos%"), 1), else_=0)
        ).label("paguitos"),

        func.sum(
            case((func.lower(models.Venta.tipo_venta).like("%pajoy%"), 1), else_=0)
        ).label("pajoy"),

    ).join(models.Usuario).filter(
        models.Venta.fecha >= inicio,
        models.Venta.fecha <= fin,
        models.Venta.cancelada == False
    )

    # 🔥 FILTRO POR MÓDULO
    if modulo_id:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    ventas = query.group_by(
        models.Venta.empleado_id,
        models.Usuario.username
    ).all()

    return {
        "inicio": inicio,
        "fin": fin,
        "data": [dict(row._mapping) for row in ventas]
    }


@router.get("/ventas-por-dia")
def ventas_por_dia(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    modulo_id: int | None = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(
        models.Venta.fecha,
        func.sum(models.Venta.total).label("total")
    ).filter(
        models.Venta.cancelada == False
    )

    if fecha_inicio:
        query = query.filter(models.Venta.fecha >= fecha_inicio)

    if fecha_fin:
        query = query.filter(models.Venta.fecha <= fecha_fin)

    # 🔥 FILTRO
    if modulo_id:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    data = query.group_by(
        models.Venta.fecha
    ).order_by(
        models.Venta.fecha
    ).all()

    return [dict(row._mapping) for row in data]



@router.get("/top-productos")
def top_productos(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    modulo_id: int | None = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(
        models.Venta.producto,
        func.sum(models.Venta.cantidad).label("total_vendidos"),
        func.sum(models.Venta.total).label("total_dinero")
    ).filter(
        models.Venta.cancelada == False
    )

    if fecha_inicio:
        query = query.filter(models.Venta.fecha >= fecha_inicio)

    if fecha_fin:
        query = query.filter(models.Venta.fecha <= fecha_fin)

    # 🔥 FILTRO
    if modulo_id:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    data = query.group_by(
        models.Venta.producto
    ).order_by(
        func.sum(models.Venta.cantidad).desc()
    ).limit(10).all()

    return [dict(row._mapping) for row in data]



@router.get("/ventas-por-modulo")
def ventas_por_modulo(
    fecha_inicio: date,
    fecha_fin: date,
    modulo_id: Optional[int] = None,
    db: Session = Depends(get_db)
):

    query = db.query(
        models.Modulo.id.label("modulo_id"),
        models.Modulo.nombre.label("modulo"),

        func.sum(
            models.Venta.precio_unitario * models.Venta.cantidad
        ).label("total")

    ).join(
        models.Modulo, models.Modulo.id == models.Venta.modulo_id
    ).filter(
        models.Venta.cancelada == False,
        models.Venta.fecha >= fecha_inicio,
        models.Venta.fecha <= fecha_fin
    )

    # 🔥 FILTRO POR MÓDULO
    if modulo_id:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    data = query.group_by(
        models.Modulo.id,
        models.Modulo.nombre
    ).all()

    return [dict(row._mapping) for row in data]



@router.get("/resumen-por-modulo")
def resumen_por_modulo(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(
        models.Modulo.nombre.label("modulo"),

        # 💰 ACCESORIOS
        func.sum(
            case(
                (
                    func.lower(models.Venta.tipo_producto) == "accesorios",
                    models.Venta.total
                ),
                else_=0
            )
        ).label("total_accesorios"),

        # 📱 TELEFONOS
        func.sum(
            case(
                (
                    func.lower(models.Venta.tipo_producto) == "telefono",
                    models.Venta.total
                ),
                else_=0
            )
        ).label("total_telefonos"),

        # 💵 CONTADO
        func.sum(
            case(
                (
                    func.lower(models.Venta.tipo_venta).like("%contado%"),
                    1
                ),
                else_=0
            )
        ).label("contado"),

        # 📲 PAGUITOS
        func.sum(
            case(
                (
                    func.lower(models.Venta.tipo_venta).like("%paguitos%"),
                    1
                ),
                else_=0
            )
        ).label("paguitos"),

        # 🧾 PAJOY
        func.sum(
            case(
                (
                    func.lower(models.Venta.tipo_venta).like("%pajoy%"),
                    1
                ),
                else_=0
            )
        ).label("pajoy"),

        # 🔥 TOTAL GENERAL
        func.sum(models.Venta.total).label("total_general")

    ).join(
        models.Modulo, models.Modulo.id == models.Venta.modulo_id
    ).filter(
        models.Venta.cancelada == False
    )

    if fecha_inicio:
        query = query.filter(models.Venta.fecha >= fecha_inicio)

    if fecha_fin:
        query = query.filter(models.Venta.fecha <= fecha_fin)

    data = query.group_by(
        models.Modulo.nombre
    ).order_by(
        func.sum(models.Venta.total).desc()
    ).all()

    return [dict(row._mapping) for row in data]


from sqlalchemy import text

@router.get("/chips")
def get_chips(
    fecha_inicio: str = None,
    fecha_fin: str = None,
    db: Session = Depends(get_db)
):
    query = """
        SELECT tipo_chip as tipo, COUNT(*) as total
        FROM venta_chips
        WHERE 1=1
    """

    params = {}

    if fecha_inicio and fecha_fin:
        query += " AND fecha BETWEEN :inicio AND :fin"
        params["inicio"] = fecha_inicio
        params["fin"] = fecha_fin

    query += " GROUP BY tipo_chip ORDER BY total DESC"

    result = db.execute(text(query), params).fetchall()

    return [
        {"tipo": row.tipo, "total": row.total}
        for row in result
    ]


@router.post("/planes")
def crear_plan(data: schemas.PlanCreate, db: Session = Depends(get_db)):
     # Validar que el empleado exista
    empleado = db.query(models.Usuario).filter_by(id=data.empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Validar que el módulo exista
    modulo = db.query(models.Modulo).filter_by(id=data.modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    nuevo_plan = models.Plan(
        tipo_tramite=data.tipo_tramite,
        tipo_plan=data.tipo_plan,
        empleado_id=data.empleado_id,
        modulo_id=data.modulo_id,
        fecha_inicio=date.today(),

    )

    db.add(nuevo_plan)
    db.commit()
    db.refresh(nuevo_plan)

    return nuevo_plan


@router.get("/planes")
def get_planes(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db)
):
    data = db.query(
        models.Plan.id,
        models.Plan.tipo_tramite,
        models.Plan.tipo_plan,
        models.Usuario.username.label("empleado"),
        models.Modulo.nombre.label("modulo"),
        models.Plan.fecha_inicio
    ).join(models.Usuario, models.Plan.empleado_id == models.Usuario.id)\
     .join(models.Modulo, models.Plan.modulo_id == models.Modulo.id)\
     .filter(
        models.Plan.fecha_inicio >= fecha_inicio,
        models.Plan.fecha_inicio <= fecha_fin
     )\
     .order_by(models.Plan.fecha_inicio.desc())\
     .all()

    return [dict(row._mapping) for row in data]

@router.get("/ventas-por-dia-detalle")
def ventas_por_dia_detalle(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    modulo_id: int | None = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(
        models.Venta.fecha,

        # 🔥 ACCESORIOS
        func.sum(
            case(
                (models.Venta.tipo_producto == "accesorios", models.Venta.total),
                else_=0
            )
        ).label("accesorios"),

        # 🔥 TELEFONOS
        func.sum(
            case(
                (models.Venta.tipo_producto == "telefono", models.Venta.total),
                else_=0
            )
        ).label("telefonos")

    ).filter(
        models.Venta.cancelada == False
    )

    if fecha_inicio:
        query = query.filter(models.Venta.fecha >= fecha_inicio)

    if fecha_fin:
        query = query.filter(models.Venta.fecha <= fecha_fin)

    if modulo_id:
        query = query.filter(models.Venta.modulo_id == modulo_id)

    data = query.group_by(
        models.Venta.fecha
    ).order_by(
        models.Venta.fecha
    ).all()

    return [dict(row._mapping) for row in data]
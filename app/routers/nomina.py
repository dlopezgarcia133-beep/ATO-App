from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NominaEmpleado, NominaPeriodo
from app.schemas import NominaEmpleadoResponse, NominaEmpleadoUpdate, NominaPeriodoCreate, NominaPeriodoFechasUpdate, NominaPeriodoResponse
from app.models import Usuario
from app.config import get_current_user
from app.services import  calcular_totales_comisiones, obtener_comisiones_por_empleado_optimizado

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from io import BytesIO



router = APIRouter()

@router.get("/periodo/activo", response_model=NominaPeriodoResponse)
def obtener_periodo_activo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = db.query(NominaPeriodo).filter(
        NominaPeriodo.activa == True,

    ).first()

    if not periodo:
        raise HTTPException(404, "No hay periodo activo")

    return periodo



def verificar_admin(user):
    if user.rol != "admin":
        raise HTTPException(
            status_code=403,
            detail="No autorizado"
        )




@router.post("/periodo/activar", response_model=NominaPeriodoResponse)
def activar_periodo_nomina(
    data: NominaPeriodoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    # 🔹 Cerrar cualquier periodo activo anterior
    db.query(NominaPeriodo).filter(
        NominaPeriodo.activa == True
    ).update(
        {"activa": False},
        synchronize_session=False
    )

    # 🔹 Crear nuevo periodo
    nuevo = NominaPeriodo(
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,

        # 👉 Por defecto ambos grupos usan el mismo rango
        inicio_a=data.fecha_inicio,
        fin_a=data.fecha_fin,
        inicio_c=data.fecha_inicio,
        fin_c=data.fecha_fin,

        activa=True
    )

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return nuevo



def obtener_periodo_activo(db: Session):
    return db.query(NominaPeriodo).filter(
        NominaPeriodo.activa == True
    ).first()



@router.get("/resumen", response_model=list[NominaEmpleadoResponse])
def obtener_resumen_nomina(
    inicio_a: Optional[date] = Query(None),
    fin_a: Optional[date] = Query(None),
    inicio_c: Optional[date] = Query(None),
    fin_c: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # 🔹 Periodo activo (solo referencia / excel)
    periodo = obtener_periodo_activo(db)
    if not periodo:
        return []

    # 🔹 Empleados activos
    empleados = db.query(Usuario).filter(Usuario.activo == True).all()

    # 🔹 Nómina guardada del periodo
    nominas = db.query(NominaEmpleado).filter(
        NominaEmpleado.periodo_id == periodo.id
    ).all()

    nomina_map = {n.usuario_id: n for n in nominas}

    # 🔹 Rangos reales a usar
    inicio_a_calc = inicio_a or periodo.inicio_a
    fin_a_calc = fin_a or periodo.fin_a


    inicio_c_calc = inicio_c or periodo.inicio_c
    fin_c_calc = fin_c or periodo.fin_c


    # 🔹 Comisiones
    comisiones_a = obtener_comisiones_por_empleado_optimizado(
    db=db,
    inicio=inicio_a_calc,
    fin=fin_a_calc
    )

    comisiones_c = obtener_comisiones_por_empleado_optimizado(
        db=db,
        inicio=inicio_c_calc,
        fin=fin_c_calc
    )
    resultado = []

    for emp in empleados:
        if not emp.username:
            continue

        grupo = emp.username.upper()[0]
        if grupo not in ("A", "C"):
            continue

        if grupo == "A":
            total_comisiones = comisiones_a.get(emp.id, 0)
        else:
            total_comisiones = comisiones_c.get(emp.id, 0)


        nomina = nomina_map.get(emp.id)

        sueldo_base = emp.sueldo_base or 0
        horas_extra = nomina.horas_extra if nomina else 0
        pago_hora_extra = nomina.pago_horas_extra if nomina else 0
        precio_hora_extra = nomina.precio_hora_extra if nomina else 0


        sanciones = (nomina.sanciones or 0) if nomina else 0
        comisiones_pendientes = (nomina.comisiones_pendientes or 0) if nomina else 0


        total = sueldo_base + total_comisiones + pago_hora_extra + comisiones_pendientes - sanciones

        resultado.append({
            "usuario_id": emp.id,
            "username": emp.username,
            "grupo": grupo,
            "comisiones": total_comisiones,
            "total_comisiones": total_comisiones,
            "sueldo_base": sueldo_base,
            "horas_extra": horas_extra,
            "pago_hora_extra": pago_hora_extra,
            "precio_hora_extra": precio_hora_extra, 
            "sanciones": sanciones,
            "comisiones_pendientes": comisiones_pendientes,
            "total_pagar": total
        })

    return resultado



@router.get("/resumen/empleado/{usuario_id}")
def resumen_comisiones_empleado(
    usuario_id: int,
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo and not (fecha_inicio and fecha_fin):
        raise HTTPException(
            status_code=400,
            detail="No hay periodo activo ni rango de fechas"
        )

    usuario = db.query(Usuario).get(usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    grupo = usuario.username.upper()[0] if usuario.username else None

    if fecha_inicio and fecha_fin:
        inicio = fecha_inicio
        fin = fecha_fin
    else:
        if grupo == "A":
            inicio = periodo.inicio_a
            fin = periodo.fin_a
        else:
            inicio = periodo.inicio_c
            fin = periodo.fin_c 

    totales = calcular_totales_comisiones(
        db=db,
        empleado_id=usuario_id,
        inicio=inicio,
        fin=fin
    )
    
    return {
        "usuario_id": usuario.id,
        "username": usuario.username,
        "grupo": grupo,
        "accesorios": totales["accesorios"],
        "telefonos": totales["telefonos"],
        "chips": totales["chips"],
        "total_comisiones": totales["total"],
        "inicio_usado": inicio,  # 👈 debug útil
        "fin_usado": fin
    }


@router.put("/empleado/{usuario_id}")
def actualizar_nomina_empleado(
    usuario_id: int,
    data: NominaEmpleadoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(status_code=400, detail="No hay periodo activo")

    nomina = db.query(NominaEmpleado).filter_by(
        usuario_id=usuario_id,
        periodo_id=periodo.id
    ).first()

    if not nomina:
        nomina = NominaEmpleado(
            usuario_id=usuario_id,
            periodo_id=periodo.id
        )
        db.add(nomina)
        db.flush()  # 👈 asegura que exista antes de calcular

    # 🧮 HORAS
    if data.horas_extra is not None:
        nomina.horas_extra = data.horas_extra

    # 💰 PRECIO
    if data.precio_hora_extra is not None:
        nomina.precio_hora_extra = data.precio_hora_extra

    # ❗ SANCIONES
    if data.sanciones is not None:
        nomina.sanciones = data.sanciones

    # ➕ COMISIONES PENDIENTES
    if data.comisiones_pendientes is not None:
        nomina.comisiones_pendientes = data.comisiones_pendientes

    # 🔁 RECÁLCULO
    nomina.pago_horas_extra = (
        (nomina.horas_extra or 0) * (nomina.precio_hora_extra or 0)
    )

    db.commit()


    return {"ok": True}





@router.post("/cerrar")
def cerrar_nomina(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(403, "No autorizado")

    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(400, "No hay periodo activo")

    # 🔒 CERRAR PERIODO
    periodo.activa = False
    periodo.estado = "cerrada"

    db.commit()

    return {"ok": True}




@router.get("/descargar")
def descargar_nomina(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(400, "No hay periodo activo")

    nominas = (
        db.query(NominaEmpleado, Usuario)
        .join(Usuario, Usuario.id == NominaEmpleado.usuario_id)
        .filter(NominaEmpleado.periodo_id == periodo.id)
        .all()
    )

    if not nominas:
        raise HTTPException(400, "No hay datos de nómina")

    # 🟢 CALCULAR COMISIONES REALES
    comisiones_por_empleado = obtener_comisiones_por_empleado_optimizado(
        db,
        periodo.fecha_inicio,
        periodo.fecha_fin
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Nómina"

    ws.append([
        "Empleado",
        "Sueldo base",
        "Horas extra",
        "Precio hora extra",
        "Pago horas extra",
        "Comisiones",
        "Comisiones pendientes",
        "Sanciones",
        "Total a pagar"
    ])

    for nomina, usuario in nominas:
        sueldo_base = usuario.sueldo_base or 0
        horas_extra = nomina.horas_extra or 0
        precio_hora = nomina.precio_hora_extra or 0
        pago_horas = nomina.pago_horas_extra or 0
        sanciones = nomina.sanciones or 0
        comisiones_pendientes = nomina.comisiones_pendientes or 0
        comisiones = comisiones_por_empleado.get(usuario.id, 0)

        total = (
            sueldo_base
            + pago_horas
            + comisiones
            + comisiones_pendientes
            - sanciones
        )


        ws.append([
            usuario.username,
            sueldo_base,
            horas_extra,
            precio_hora,
            pago_horas,
            comisiones,
            comisiones_pendientes,
            sanciones,
            total
        ])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    nombre_archivo = (
        f"nomina_{periodo.fecha_inicio:%Y-%m-%d}_"
        f"{periodo.fecha_fin:%Y-%m-%d}.xlsx"
    )

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}"
        }
    )



@router.get("/mi-resumen")
def obtener_mi_nomina(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(status_code=400, detail="No hay periodo activo")

    empleado = current_user

    # 🔹 Detectar grupo
    if empleado.username.startswith("A"):
        
        fecha_inicio = periodo.inicio_a
        fecha_fin = periodo.fin_a
    elif empleado.username.startswith("C"):
        
        fecha_inicio = periodo.inicio_c
        fecha_fin = periodo.fin_c
    else:
        raise HTTPException(status_code=400, detail="Grupo inválido")

    # 🔹 Comisiones
    totales = calcular_totales_comisiones(
        db=db,
        empleado_id=empleado.id,
        inicio=fecha_inicio,
        fin=fecha_fin
    )

    total_comisiones = (
        totales.get("accesorios", 0) +
        totales.get("telefonos", 0) +
        totales.get("chips", 0)
    )

    # 🔹 Nómina guardada
    nomina = db.query(NominaEmpleado).filter(
        NominaEmpleado.usuario_id == empleado.id,
        NominaEmpleado.periodo_id == periodo.id
    ).first()

    sueldo_base = empleado.sueldo_base or 0
    horas_extra = nomina.horas_extra if nomina else 0
    pago_horas_extra = nomina.pago_horas_extra if nomina else 0
    sanciones = nomina.sanciones if nomina and nomina.sanciones else 0
    comisiones_pendientes = nomina.comisiones_pendientes if nomina and nomina.comisiones_pendientes else 0

    total_pagar = (
        sueldo_base
        + total_comisiones
        + pago_horas_extra
        + comisiones_pendientes
        - sanciones
    )

    return {
        "empleado": {
            "id": empleado.id,
            "username": empleado.username,
            "modulo": empleado.modulo_id
        },
        "periodo": {
            "inicio": fecha_inicio,
            "fin": fecha_fin
        },
        "comisiones": {
            "accesorios": totales.get("accesorios", 0),
            "telefonos": totales.get("telefonos", 0),
            "chips": totales.get("chips", 0),
            "total": total_comisiones
        },
        "sueldo": {
            "base": sueldo_base,
            "horas_extra": horas_extra,
            "pago_horas_extra": pago_horas_extra,
            "comisiones_pendientes": comisiones_pendientes,
            "sanciones": sanciones
        },
        "total_pagar": total_pagar
    }


@router.put("/periodo/fechas", response_model=NominaPeriodoResponse)
def actualizar_fechas_periodo(
    data: NominaPeriodoFechasUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(status_code=400, detail="No hay periodo activo")

    # 🔹 Actualizar solo lo que venga
    if data.inicio_a is not None:
        periodo.inicio_a = data.inicio_a

    if data.fin_a is not None:
        periodo.fin_a = data.fin_a

    if data.inicio_c is not None:
        periodo.inicio_c = data.inicio_c

    if data.fin_c is not None:
        periodo.fin_c = data.fin_c

    db.commit()
    db.refresh(periodo)

    return periodo

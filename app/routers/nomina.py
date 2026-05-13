from datetime import date, timedelta
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NominaEmpleado, NominaHistorial, NominaPeriodo, Venta
from app.schemas import NominaEmpleadoResponse, NominaEmpleadoUpdate, NominaHistorialCreate, NominaHistorialResponse, NominaPeriodoCreate, NominaPeriodoFechasUpdate, NominaPeriodoResponse
from app.models import Usuario
from app.config import get_current_user
from app.services import calcular_totales_comisiones, obtener_comisiones_por_empleado_optimizado
from datetime import datetime, timezone
import openpyxl
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
    semana_inicio: date,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    registros = (
        db.query(NominaHistorial)
        .filter(NominaHistorial.semana_inicio == semana_inicio)
        .order_by(NominaHistorial.grupo, NominaHistorial.username)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nómina"

    ws.append([
        "Empleado",
        "Grupo",
        "Com. inicio",
        "Com. fin",
        "Sueldo Base",
        "Horas Extra",
        "Precio Hora Extra",
        "Pago Horas Extra",
        "Com. Accesorios",
        "Com. Teléfonos",
        "Com. Chips",
        "Com. Total",
        "Sanciones",
        "Com. Pendientes",
        "Hrs Faltantes",
        "Total a Pagar",
    ])

    for r in registros:
        ws.append([
            r.username,
            r.grupo,
            str(r.comisiones_inicio),
            str(r.comisiones_fin),
            r.sueldo_base,
            r.horas_extra,
            r.precio_hora_extra,
            r.pago_horas_extra,
            r.comisiones_accesorios,
            r.comisiones_telefonos,
            r.comisiones_chips,
            r.comisiones_total,
            r.sanciones,
            r.comisiones_pendientes,
            r.horas_faltantes,
            r.total_pagar,
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"nomina_{semana_inicio}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
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

    if not nomina:
        nomina = NominaEmpleado(
            usuario_id=empleado.id,
            periodo_id=periodo.id,
            horas_extra=0,
            precio_hora_extra=0,
            pago_horas_extra=0,
            sanciones=0,
            comisiones_pendientes=0
        )
        db.add(nomina)
        db.commit()
        db.refresh(nomina)

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


# =========================
# HISTORIAL DE NÓMINAS
# =========================

@router.get("/historial/semanas")
def listar_semanas_historial(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    verificar_admin(current_user)

    semanas = (
        db.query(NominaHistorial.semana_inicio)
        .distinct()
        .order_by(NominaHistorial.semana_inicio.desc())
        .all()
    )

    return [str(s.semana_inicio) for s in semanas]


@router.get("/historial", response_model=list[NominaHistorialResponse])
def obtener_historial_semana(
    semana_inicio: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    verificar_admin(current_user)

    return (
        db.query(NominaHistorial)
        .filter(NominaHistorial.semana_inicio == semana_inicio)
        .all()
    )


@router.post("/historial")
def guardar_historial_nomina(
    data: NominaHistorialCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    verificar_admin(current_user)

    for emp in data.empleados:
        comisiones_inicio = (
            data.comisiones_inicio_a if emp.grupo == "A" else data.comisiones_inicio_c
        )
        comisiones_fin = (
            data.comisiones_fin_a if emp.grupo == "A" else data.comisiones_fin_c
        )

        registro = db.query(NominaHistorial).filter_by(
            semana_inicio=data.semana_inicio,
            usuario_id=emp.usuario_id
        ).first()

        if registro:
            registro.semana_fin = data.semana_fin
            registro.comisiones_inicio = comisiones_inicio
            registro.comisiones_fin = comisiones_fin
            registro.username = emp.username
            registro.grupo = emp.grupo
            registro.comisiones_accesorios = emp.comisiones_accesorios
            registro.comisiones_telefonos = emp.comisiones_telefonos
            registro.comisiones_chips = emp.comisiones_chips
            registro.comisiones_total = emp.comisiones_total
            registro.sueldo_base = emp.sueldo_base
            registro.horas_extra = emp.horas_extra
            registro.precio_hora_extra = emp.precio_hora_extra
            registro.pago_horas_extra = emp.pago_horas_extra
            registro.sanciones = emp.sanciones
            registro.comisiones_pendientes = emp.comisiones_pendientes
            registro.total_pagar = emp.total_pagar
            registro.guardado_at = datetime.now(timezone.utc)
        else:
            registro = NominaHistorial(
                semana_inicio=data.semana_inicio,
                semana_fin=data.semana_fin,
                comisiones_inicio=comisiones_inicio,
                comisiones_fin=comisiones_fin,
                usuario_id=emp.usuario_id,
                username=emp.username,
                grupo=emp.grupo,
                comisiones_accesorios=emp.comisiones_accesorios,
                comisiones_telefonos=emp.comisiones_telefonos,
                comisiones_chips=emp.comisiones_chips,
                comisiones_total=emp.comisiones_total,
                sueldo_base=emp.sueldo_base,
                horas_extra=emp.horas_extra,
                precio_hora_extra=emp.precio_hora_extra,
                pago_horas_extra=emp.pago_horas_extra,
                sanciones=emp.sanciones,
                comisiones_pendientes=emp.comisiones_pendientes,
                total_pagar=emp.total_pagar,
            )
            db.add(registro)

    db.commit()
    return {"ok": True, "guardados": len(data.empleados)}


@router.get("/mi-historial", response_model=Optional[NominaHistorialResponse])
def obtener_mi_historial(
    semana_inicio: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    query = db.query(NominaHistorial).filter(
        NominaHistorial.usuario_id == current_user.id
    )
    if semana_inicio:
        query = query.filter(NominaHistorial.semana_inicio == semana_inicio)
    else:
        # Devolver la semana cuya fecha de pago (semana_inicio + 9 días = miércoles)
        # sea la más reciente que ya llegó o ya pasó respecto a hoy.
        cutoff = date.today() - timedelta(days=9)
        query = (
            query
            .filter(NominaHistorial.semana_inicio <= cutoff)
            .order_by(NominaHistorial.semana_inicio.desc())
        )
    return query.first()

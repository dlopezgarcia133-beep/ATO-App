from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NominaEmpleado, NominaPeriodo
from app.schemas import NominaEmpleadoResponse, NominaEmpleadoUpdate, NominaPeriodoCreate, NominaPeriodoResponse
from app.models import Usuario
from app.config import get_current_user
from app.services import  obtener_comisiones_por_empleado_optimizado

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

    # 🔹 cerrar periodo activo del mismo grupo
    db.query(NominaPeriodo).filter(
        NominaPeriodo.activa == True,
        
    ).update({"activa": False})

    nuevo = NominaPeriodo(
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        activa=True,
        
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
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo:
        return []

    empleados = db.query(Usuario).filter(Usuario.activo == True).all()

    nominas = db.query(NominaEmpleado).filter(
        NominaEmpleado.periodo_id == periodo.id
    ).all()

    nomina_map = {n.usuario_id: n for n in nominas}

    resultado = []

    for emp in empleados:
        if not emp.username:
            continue

        primera_letra = emp.username.upper()[0]
        if primera_letra not in ("A", "C"):
            continue

        grupo = primera_letra

        # ✅ AQUÍ ESTÁ EL CAMBIO CLAVE
        totales = obtener_comisiones_por_empleado_optimizado(
            db=db,
            empleado_id=emp.id,
            inicio=periodo.fecha_inicio,
            fin=periodo.fecha_fin
        )

        total_comisiones = totales["total_general"]

        nomina = nomina_map.get(emp.id)
        sueldo_base = nomina.sueldo_base if nomina else 0
        horas_extra = nomina.horas_extra if nomina else 0
        pago_horas_extra = nomina.pago_horas_extra if nomina else 0

        total = sueldo_base + total_comisiones + pago_horas_extra

        resultado.append({
            "usuario_id": emp.id,
            "username": emp.username,
            "grupo": grupo,

            # 👇 ahora sí es real
            "comisiones": total_comisiones,
            "total_comisiones": total_comisiones,

            "sueldo_base": sueldo_base,
            "horas_extra": horas_extra,
            "pago_horas_extra": pago_horas_extra,
            "total_pagar": total
        })

    return resultado




@router.get("/resumen/empleado/{usuario_id}")
def resumen_comisiones_empleado(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(400, "No hay periodo activo")

    usuario = db.query(Usuario).get(usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    grupo = usuario.username.upper()[0] if usuario.username else None

    totales = calcular_totales_comisiones(
        db=db,
        empleado_id=usuario_id,
        inicio=periodo.fecha_inicio,
        fin=periodo.fecha_fin
    )

    return {
        "usuario_id": usuario.id,
        "username": usuario.username,
        "grupo": grupo,
        "accesorios": totales["total_accesorios"],
        "telefonos": totales["total_telefonos"],
        "chips": totales["total_chips"],
        "total_comisiones": totales["total_general"]
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

    # 🔢 CÁLCULO HORAS EXTRA
    COSTO_HORA_EXTRA = 50  # ⚠️ AJUSTABLE
    pago_horas_extra = data.horas_extra * COSTO_HORA_EXTRA

    nomina.sueldo_base = data.sueldo_base
    nomina.horas_extra = data.horas_extra
    nomina.pago_horas_extra = pago_horas_extra

    db.commit()

    return {"ok": True}



@router.post("/cerrar")
def cerrar_nomina(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    periodo = obtener_periodo_activo(db)
    if not periodo:
        raise HTTPException(status_code=400, detail="No hay periodo activo")

    periodo.activo = False
    periodo.cerrado = True

    db.commit()

    return {"ok": True, "mensaje": "Nómina cerrada correctamente"}




@router.get("/descargar")
def descargar_nomina(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = obtener_periodo_activo(db)
    if not periodo or not periodo.cerrado:
        raise HTTPException(400, "La nómina no está cerrada")

    # aquí generas el Excel como hicimos con inventario

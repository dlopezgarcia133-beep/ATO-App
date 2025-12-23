from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NominaPeriodo
from app.schemas import NominaPeriodoResponse
from app.models import Usuario
from app.config import get_current_user


router = APIRouter()

@router.get("/periodo/activo", response_model=NominaPeriodoResponse)
def obtener_periodo_activo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    periodo = (
        db.query(NominaPeriodo)
        .filter(NominaPeriodo.activa == True)
        .first()
    )

    if not periodo:
        raise HTTPException(
            status_code=404,
            detail="No hay un periodo de nómina activo"
        )

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
    verificar_admin(current_user)

    # Desactivar periodos anteriores
    db.query(NominaPeriodo).filter(
        NominaPeriodo.activa == True
    ).update({"activa": False})

    # Crear nuevo periodo
    nuevo = NominaPeriodo(
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        activa=True,
        estado="abierta"
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

    empleados = db.query(Usuario).filter(
        Usuario.rol.in_(["asesor", "encargado"])
    ).all()

    resultado = []

    for emp in empleados:
        # 🔹 COMISIONES YA EXISTENTES (solo dinero)
        total_comisiones = obtener_total_comisiones(
            db=db,
            usuario_id=emp.id,
            fecha_inicio=periodo.fecha_inicio,
            fecha_fin=periodo.fecha_fin
        )

        # 🔹 Datos de nómina (si no existen, 0)
        nomina = db.query(NominaEmpleado).filter_by(
            usuario_id=emp.id,
            periodo_id=periodo.id
        ).first()

        sueldo_base = nomina.sueldo_base if nomina else 0
        horas_extra = nomina.horas_extra if nomina else 0
        pago_horas_extra = nomina.pago_horas_extra if nomina else 0

        total = sueldo_base + total_comisiones + pago_horas_extra

        resultado.append({
            "usuario_id": emp.id,
            "usuario": emp.usuario,
            "nombre": emp.nombre,
            "rol": emp.rol,
            "comisiones": total_comisiones,
            "sueldo_base": sueldo_base,
            "horas_extra": horas_extra,
            "pago_horas_extra": pago_horas_extra,
            "total_pagar": total
        })

    return resultado



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

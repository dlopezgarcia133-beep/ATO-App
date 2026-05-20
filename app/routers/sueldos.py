import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.services import obtener_comisiones_por_empleado_optimizado

router = APIRouter()

_ZONA = ZoneInfo("America/Mexico_City")
_COMISION_FIJA = 10.0

# Productos sin comisión (no aparecen en el resumen)
_EXCLUIR_PALABRAS = {"CHIP", "FICHA"}

# Palabras que convierten un "SMART WATCH" en accesorio (no dispositivo)
_ACCESORIOS_SW = {
    "EXTENSIBLE", "FUNDA", "MICA", "PROTECTOR",
    "CARGADOR", "CABLE", "CORREA", "BANDA",
}


def _normalizar(nombre: str) -> str:
    nfkd = unicodedata.normalize("NFD", nombre)
    return nfkd.encode("ascii", "ignore").decode().upper()


def _calcular_comision(
    nombre_norm: str,
    precio_unitario: float,
    cantidad: int,
    neto: float,
    porcentaje: float,
) -> tuple[float, str]:
    """Devuelve (monto_comision, etiqueta_porcentaje). 'excluido' = sin comisión."""

    # 1. Productos excluidos (sin comisión, no se muestran)
    if any(p in nombre_norm for p in _EXCLUIR_PALABRAS) or "TARJETA DE YOVOY" in nombre_norm:
        return (0.0, "excluido")

    # 2. Teléfono
    if nombre_norm.startswith("TELEFONO"):
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    # 3. Bocina
    if "BOCINA" in nombre_norm:
        if precio_unitario >= 950:
            return (_COMISION_FIJA * cantidad, "$10 fijo")
        return (round(neto * porcentaje / 100, 2), f"{porcentaje:.2f}%")

    # 4. Smart Watch — solo el dispositivo paga $10; accesorios pagan porcentaje
    if "SMART WATCH" in nombre_norm or "SMARTWATCH" in nombre_norm:
        if any(acc in nombre_norm for acc in _ACCESORIOS_SW):
            return (round(neto * porcentaje / 100, 2), f"{porcentaje:.2f}%")
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    # 5. Tablet
    if "TABLET" in nombre_norm:
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    # 6. Cualquier otro accesorio
    return (round(neto * porcentaje / 100, 2), f"{porcentaje:.2f}%")


def _es_telefono(nombre_norm: str) -> bool:
    return nombre_norm.startswith("TELEFONO")


@router.get("/encargados", response_model=schemas.SueldoEncargadoResponse)
def sueldos_encargados(
    modulo: str = Query(..., description="Nombre exacto del módulo"),
    fecha_inicio: date = Query(..., description="Viernes de inicio del ciclo"),
    fecha_fin: date = Query(..., description="Jueves de fin del ciclo"),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("direccion", "admin"):
        raise HTTPException(status_code=403, detail="Solo dirección")

    # Porcentaje del módulo (default 0 si aún no existe el registro)
    comision_mod = (
        db.query(models.ComisionModulo)
        .filter(models.ComisionModulo.modulo == modulo)
        .first()
    )
    porcentaje = float(comision_mod.porcentaje) if comision_mod else 0.0

    # Ventas del módulo en el rango de fechas, no canceladas
    ventas = (
        db.query(models.Venta)
        .join(models.Modulo, models.Venta.modulo_id == models.Modulo.id)
        .filter(
            models.Modulo.nombre == modulo,
            models.Venta.fecha >= fecha_inicio,
            models.Venta.fecha <= fecha_fin,
            models.Venta.cancelada == False,
        )
        .order_by(models.Venta.fecha, models.Venta.id)
        .all()
    )

    print(f"[SUELDO] módulo={modulo!r} rango={fecha_inicio}→{fecha_fin} ventas={len(ventas)} porcentaje={porcentaje}%")

    # ── Bloque A: resumen por producto ──────────────────────────────────────
    producto_map: dict = defaultdict(
        lambda: {"cantidad": 0, "neto": 0.0, "comision": 0.0, "tipo": "", "porcentaje_label": ""}
    )

    for i, v in enumerate(ventas):
        nombre_norm = _normalizar(v.producto)
        neto = round(v.precio_unitario * v.cantidad, 2)
        comision, label = _calcular_comision(nombre_norm, v.precio_unitario, v.cantidad, neto, porcentaje)

        if label == "excluido":
            categoria = "EXCLUIDO"
        elif _es_telefono(nombre_norm):
            categoria = "telefono"
        elif "BOCINA" in nombre_norm:
            categoria = "bocina"
        elif "SMART WATCH" in nombre_norm or "SMARTWATCH" in nombre_norm:
            categoria = "smartwatch-acc" if any(a in nombre_norm for a in _ACCESORIOS_SW) else "smartwatch-dev"
        elif "TABLET" in nombre_norm:
            categoria = "tablet"
        else:
            categoria = "accesorio"

        if i < 15:
            print(
                f"[SUELDO]   [{i}] cat={categoria} prod={v.producto!r} "
                f"pu={v.precio_unitario} cant={v.cantidad} "
                f"neto={neto:.2f} comision={comision:.2f} label={label}"
            )

        if label == "excluido":
            continue

        tipo = "telefono" if _es_telefono(nombre_norm) else "accesorio"
        p = producto_map[v.producto]
        p["cantidad"] += v.cantidad
        p["neto"] = round(p["neto"] + neto, 2)
        p["comision"] = round(p["comision"] + comision, 2)
        p["tipo"] = tipo
        p["porcentaje_label"] = label

    productos = [
        schemas.ProductoResumen(
            nombre=nombre,
            tipo=d["tipo"],
            cantidad=d["cantidad"],
            neto=d["neto"],
            porcentaje_label=d["porcentaje_label"],
            comision=d["comision"],
        )
        for nombre, d in producto_map.items()
    ]

    sueldo_total = round(sum(p.comision for p in productos), 2)
    print(f"[SUELDO] sueldo_total={sueldo_total}")

    # ── Bloque B: desglose diario ────────────────────────────────────────────
    desglose: List[schemas.DiaDiario] = []
    total_equipos = 0
    total_accesorios = 0.0

    dia = fecha_inicio
    while dia <= fecha_fin:
        ventas_dia = [v for v in ventas if v.fecha == dia]
        equipos = sum(
            v.cantidad for v in ventas_dia
            if _es_telefono(_normalizar(v.producto))
        )
        accesorios = sum(
            round(v.precio_unitario * v.cantidad, 2)
            for v in ventas_dia
            if not _es_telefono(_normalizar(v.producto))
            and _calcular_comision(
                _normalizar(v.producto), v.precio_unitario, v.cantidad,
                round(v.precio_unitario * v.cantidad, 2), porcentaje
            )[1] != "excluido"
        )
        desglose.append(
            schemas.DiaDiario(
                fecha=dia,
                label=dia.strftime("%A %d %b").lower(),
                equipos=equipos,
                accesorios=round(accesorios, 2),
            )
        )
        total_equipos += equipos
        total_accesorios = round(total_accesorios + accesorios, 2)
        dia += timedelta(days=1)

    # Fila TOTAL
    desglose.append(
        schemas.DiaDiario(
            fecha=None,
            label="TOTAL",
            equipos=total_equipos,
            accesorios=total_accesorios,
        )
    )

    return schemas.SueldoEncargadoResponse(
        modulo=modulo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        porcentaje_modulo=porcentaje,
        productos=productos,
        desglose_diario=desglose,
        sueldo_total=sueldo_total,
    )


@router.get("/resumen-modulo", response_model=schemas.ResumenModuloResponse)
def resumen_modulo(
    modulo: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("direccion", "admin"):
        raise HTTPException(status_code=403, detail="Solo dirección")

    # Semana de nómina: lunes de la semana ANTERIOR (ya completada).
    # Nomina.tsx inicializa semanaInicio = calcularLunes() = lunes de la semana actual,
    # pero el admin trabaja con la semana que acaba de cerrar (Sunday pasado).
    # Fórmula: today - today.weekday() = lunes actual; - 7 = lunes semana anterior.
    # weekday(): 0=lun … 6=dom (Python)
    today_mx = datetime.now(_ZONA).date()
    lunes = today_mx - timedelta(days=today_mx.weekday()) - timedelta(days=7)
    domingo = lunes + timedelta(days=6)

    # Grupo C: Nomina.tsx usa semanaInicio-9 → semanaInicio-3
    lunes_c = lunes - timedelta(days=9)
    domingo_c = lunes - timedelta(days=3)

    print(
        f"[RESUMEN-MOD] hoy={today_mx} "
        f"lunes={lunes} domingo={domingo} "
        f"lunes_c={lunes_c} domingo_c={domingo_c}"
    )

    # Empleados activos del módulo (asesores + encargados)
    empleados = (
        db.query(models.Usuario)
        .join(models.Modulo, models.Usuario.modulo_id == models.Modulo.id)
        .filter(
            models.Modulo.nombre == modulo,
            models.Usuario.activo == True,
            models.Usuario.rol.in_(["asesor", "encargado"]),
        )
        .all()
    )

    # NominaHistorial guardado por el admin para esta semana
    historial_map = {
        h.usuario_id: h
        for h in db.query(models.NominaHistorial)
        .filter(models.NominaHistorial.semana_inicio == lunes)
        .all()
    }

    # NominaEmpleado del periodo que inicia en lunes (fallback si no hay historial)
    periodo = (
        db.query(models.NominaPeriodo)
        .filter(models.NominaPeriodo.fecha_inicio == lunes)
        .first()
    )
    nomina_emp_map: dict = {}
    if periodo:
        nomina_emp_map = {
            n.usuario_id: n
            for n in db.query(models.NominaEmpleado)
            .filter(models.NominaEmpleado.periodo_id == periodo.id)
            .all()
        }

    # Comisiones en vivo — misma función que usa /nomina/resumen
    comisiones_a = obtener_comisiones_por_empleado_optimizado(db, lunes, domingo)
    comisiones_c = obtener_comisiones_por_empleado_optimizado(db, lunes_c, domingo_c)

    asesores_list: List[schemas.ResumenEmpleadoNomina] = []
    encargados_list: List[schemas.ResumenEmpleadoNomina] = []

    for emp in empleados:
        es_encargado = emp.username.upper().startswith("C")
        hist = historial_map.get(emp.id)
        nomina_e = nomina_emp_map.get(emp.id)

        sueldo_base = float(hist.sueldo_base if hist else (emp.sueldo_base or 0))
        pago_horas_extra = float(
            hist.pago_horas_extra if hist
            else (nomina_e.pago_horas_extra if nomina_e else 0)
        )

        if hist:
            comisiones = float(hist.comisiones_total)
        elif es_encargado:
            comisiones = float(comisiones_c.get(emp.id, 0))
        else:
            comisiones = float(comisiones_a.get(emp.id, 0))

        total = round(sueldo_base + pago_horas_extra + comisiones, 2)
        nombre = emp.nombre_completo or emp.username

        item = schemas.ResumenEmpleadoNomina(
            nombre=nombre,
            rol="encargado" if es_encargado else "asesor",
            sueldo_base=sueldo_base,
            horas_extras_pagadas=pago_horas_extra,
            comisiones=comisiones,
            total=total,
        )
        (encargados_list if es_encargado else asesores_list).append(item)

    asesores_list.sort(key=lambda x: x.nombre)

    return schemas.ResumenModuloResponse(
        nomina_inicio=lunes,
        nomina_fin=domingo,
        empleados=asesores_list + encargados_list,
    )

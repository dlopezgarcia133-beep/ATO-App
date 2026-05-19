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

router = APIRouter()

_ZONA = ZoneInfo("America/Mexico_City")
_COMISION_FIJA = 10.0


def _normalizar(nombre: str) -> str:
    """Quita acentos y pasa a mayúsculas para comparar nombres de productos."""
    nfkd = unicodedata.normalize("NFD", nombre)
    return nfkd.encode("ascii", "ignore").decode().upper()


def _calcular_comision(
    nombre_norm: str,
    precio_unitario: float,
    cantidad: int,
    neto: float,
    porcentaje: float,
) -> tuple[float, str]:
    """
    Reglas de comisión por producto.
    Devuelve (monto_comision, etiqueta_porcentaje).
    """
    if nombre_norm.startswith("TELEFONO"):
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    if "BOCINA" in nombre_norm:
        if precio_unitario >= 950:
            return (_COMISION_FIJA * cantidad, "$10 fijo")
        return (round(neto * porcentaje / 100, 2), f"{porcentaje:.2f}%")

    if "SMART WATCH" in nombre_norm or "SMARTWATCH" in nombre_norm:
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    if "TABLET" in nombre_norm:
        return (_COMISION_FIJA * cantidad, "$10 fijo")

    # Cualquier otro accesorio
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
        tipo = "telefono" if _es_telefono(nombre_norm) else "accesorio"

        if i < 5:
            print(
                f"[SUELDO]   [{i}] prod={v.producto!r} norm={nombre_norm!r} "
                f"tipo={tipo} pu={v.precio_unitario} cant={v.cantidad} "
                f"neto={neto:.2f} comision={comision:.2f} label={label}"
            )

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

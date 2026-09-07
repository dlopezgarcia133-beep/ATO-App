
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from app import models
from app.database import get_db
from app.utilidades import verificar_rol_requerido

router = APIRouter()

ZONA = ZoneInfo("America/Mexico_City")

# Primer dia con datos de cadenas en produccion.
FECHA_INICIO_DATOS = date(2025, 8, 19)

_MESES = ["ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]

# Llaves = valores reales de venta_chips.tipo_chip.
TIPOS_CADENAS = {
    "tel_activado":  ["Activacion"],
    "chip_express":  ["Chip Coppel"],
    "chip_cero":     ["Chip Cero/Libre"],
    "preactivado":   ["Chip Preactivado"],
    "portabilidad":  ["Portabilidad Coppel", "Porta Otras cadenas"],
    "boletin63":     ["Boletin 63"],
}


def _domingo_de(d: date) -> date:
    return d if d.weekday() == 6 else d - timedelta(days=d.weekday() + 1)


def _hoy() -> date:
    return datetime.now(ZONA).date()


def _etiqueta(inicio: date, fin: date) -> str:
    return (
        f"{inicio.day:02d} {_MESES[inicio.month - 1]} - "
        f"{fin.day:02d} {_MESES[fin.month - 1]} {fin.year}"
    )


def _ciclo(inicio: date, ciclo_actual: date) -> dict:
    fin = inicio + timedelta(days=6)
    return {
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "etiqueta": _etiqueta(inicio, fin),
        "actual": inicio == ciclo_actual,
    }


@router.get("/ciclos")
def obtener_ciclos(
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    # Se calcula en Python, sin tocar la BD.
    primero = _domingo_de(FECHA_INICIO_DATOS)
    actual = _domingo_de(_hoy())

    ciclos = []
    cursor = actual
    while cursor >= primero:
        ciclos.append(_ciclo(cursor, actual))
        cursor -= timedelta(days=7)

    return ciclos


@router.get("/resumen")
def obtener_resumen(
    inicio: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    actual = _domingo_de(_hoy())
    inicio = _domingo_de(inicio) if inicio else actual
    fin = inicio + timedelta(days=6)

    conteos = {
        clave: func.count(models.VentaChip.id)
        .filter(models.VentaChip.tipo_chip.in_(tipos))
        .label(clave)
        for clave, tipos in TIPOS_CADENAS.items()
    }
    total_col = func.count(models.VentaChip.id).label("total")

    # LEFT JOIN para que salgan todos los promotores aunque tengan 0 ventas.
    filas_db = (
        db.query(
            models.Usuario.username.label("promotor"),
            models.Usuario.nombre_completo.label("nombre"),
            models.Tienda.nombre.label("tienda"),
            *conteos.values(),
            total_col,
        )
        .select_from(models.Usuario)
        .join(models.Tienda, models.Tienda.id == models.Usuario.tienda_id)
        .outerjoin(
            models.VentaChip,
            and_(
                models.VentaChip.empleado_id == models.Usuario.id,
                models.VentaChip.fecha >= inicio,
                models.VentaChip.fecha <= fin,
                func.coalesce(models.VentaChip.cancelada, False) == False,
            ),
        )
        .filter(
            models.Usuario.tienda_id.isnot(None),
            models.Usuario.activo == True,
        )
        .group_by(
            models.Usuario.id,
            models.Usuario.username,
            models.Usuario.nombre_completo,
            models.Tienda.nombre,
        )
        .order_by(
            conteos["tel_activado"].desc(),
            total_col.desc(),
            models.Usuario.username.asc(),
        )
        .all()
    )

    llaves = list(TIPOS_CADENAS.keys()) + ["total"]

    filas = []
    totales = {k: 0 for k in llaves}
    for f in filas_db:
        fila = {
            "promotor": f.promotor,
            "nombre": f.nombre,
            "tienda": f.tienda,
        }
        for k in llaves:
            valor = int(getattr(f, k) or 0)
            fila[k] = valor
            totales[k] += valor
        filas.append(fila)

    return {
        "ciclo": _ciclo(inicio, actual),
        "filas": filas,
        "totales": totales,
    }

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.database import get_db

router = APIRouter()

ZONA = ZoneInfo("America/Mexico_City")
TIPOS = ["personal", "iglesia", "prestamos"]


def _ahora():
    return datetime.now(ZONA)


def _serializar_abono(abono: models.GastoAbono) -> dict:
    return {
        "id": abono.id,
        "monto": float(abono.monto or 0),
        "fecha": abono.fecha,
        "nota": abono.nota,
    }


def _serializar_pendiente(gasto: models.Gasto) -> dict:
    monto = float(gasto.monto or 0)
    total_abonado = sum(float(a.monto or 0) for a in gasto.abonos)
    return {
        "id": gasto.id,
        "concepto": gasto.concepto,
        "monto": monto,
        "total_abonado": total_abonado,
        "saldo": monto - total_abonado,
        "abonos": [_serializar_abono(a) for a in gasto.abonos],
        "fecha_registro": gasto.fecha_registro,
    }


def _serializar_pagado(gasto: models.Gasto) -> dict:
    return {
        "id": gasto.id,
        "concepto": gasto.concepto,
        "monto": float(gasto.monto or 0),
        "fecha_registro": gasto.fecha_registro,
        "fecha_pago": gasto.fecha_pago,
    }


@router.post("/gastos", response_model=schemas.GastoResponse)
def crear_gasto(data: schemas.GastoCreate, db: Session = Depends(get_db)):
    if data.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    gasto = models.Gasto(
        tipo=data.tipo,
        concepto=data.concepto,
        monto=data.monto,
        estado="pendiente",
        fecha_registro=_ahora(),
    )
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.get("/gastos")
def listar_gastos(db: Session = Depends(get_db)):
    gastos = (
        db.query(models.Gasto)
        .options(joinedload(models.Gasto.abonos))
        .all()
    )

    resultado = {
        tipo: {"pendientes": [], "pagados": [], "total_pendiente": 0.0}
        for tipo in TIPOS
    }

    for gasto in gastos:
        if gasto.tipo not in resultado:
            continue
        if gasto.estado == "pendiente":
            pendiente = _serializar_pendiente(gasto)
            resultado[gasto.tipo]["pendientes"].append(pendiente)
            resultado[gasto.tipo]["total_pendiente"] += pendiente["saldo"]
        else:
            resultado[gasto.tipo]["pagados"].append(_serializar_pagado(gasto))

    resultado["total_general_pendiente"] = sum(
        resultado[tipo]["total_pendiente"] for tipo in TIPOS
    )
    return resultado


@router.post("/gastos/{gasto_id}/pagar", response_model=schemas.GastoResponse)
def pagar_gasto(gasto_id: int, db: Session = Depends(get_db)):
    gasto = db.query(models.Gasto).filter(models.Gasto.id == gasto_id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    gasto.estado = "pagado"
    gasto.fecha_pago = _ahora()
    db.commit()
    db.refresh(gasto)
    return gasto


@router.post("/gastos/{gasto_id}/abonos")
def agregar_abono(
    gasto_id: int,
    data: schemas.GastoAbonoCreate,
    db: Session = Depends(get_db),
):
    gasto = (
        db.query(models.Gasto)
        .options(joinedload(models.Gasto.abonos))
        .filter(models.Gasto.id == gasto_id)
        .first()
    )
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    if data.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto del abono debe ser mayor a 0")

    abono = models.GastoAbono(
        gasto_id=gasto.id,
        monto=data.monto,
        nota=data.nota,
        fecha=_ahora(),
    )
    db.add(abono)
    db.flush()  # asegura que el abono entre en gasto.abonos para la suma

    total_abonado = sum(float(a.monto or 0) for a in gasto.abonos)
    if total_abonado >= float(gasto.monto or 0):
        gasto.estado = "pagado"
        gasto.fecha_pago = _ahora()

    db.commit()
    db.refresh(gasto)

    return _serializar_pendiente(gasto) if gasto.estado == "pendiente" else _serializar_pagado(gasto)


@router.put("/gastos/{gasto_id}", response_model=schemas.GastoResponse)
def editar_gasto(
    gasto_id: int,
    data: schemas.GastoUpdate,
    db: Session = Depends(get_db),
):
    gasto = db.query(models.Gasto).filter(models.Gasto.id == gasto_id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    if data.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")

    gasto.tipo = data.tipo
    gasto.concepto = data.concepto
    gasto.monto = data.monto
    db.commit()
    db.refresh(gasto)
    return gasto


@router.delete("/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int, db: Session = Depends(get_db)):
    gasto = db.query(models.Gasto).filter(models.Gasto.id == gasto_id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    db.delete(gasto)
    db.commit()
    return {"ok": True, "mensaje": "Gasto eliminado"}

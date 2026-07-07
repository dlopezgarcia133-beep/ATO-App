import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.params import File
from sqlalchemy.orm import Session

from app import models
from app.database import get_db

router = APIRouter()


@router.post("/upload/")
def upload_equipos_telcel(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1️⃣ Leer el Excel
    try:
        df = pd.read_excel(archivo.file)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error al leer el archivo Excel: {e}"
        )

    # 2️⃣ Normalizar encabezados a minúsculas sin espacios
    df.columns = [str(c).strip().lower() for c in df.columns]

    # 3️⃣ Validar columnas requeridas
    requeridas = ["imei", "clave", "producto", "fecha_compra"]
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan columnas requeridas: {', '.join(faltantes)}"
        )

    insertados = 0
    saltados_repetidos = 0

    # 4️⃣ Procesar filas
    for _, fila in df.iterrows():
        imei = str(fila["imei"]).strip()
        clave = str(fila["clave"]).strip()
        producto = str(fila["producto"]).strip()

        try:
            fecha_compra = pd.to_datetime(fila["fecha_compra"]).date()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Fecha de compra inválida en el IMEI {imei}"
            )

        # 🔒 PROTECCIÓN: saltar IMEI ya existente
        existente = (
            db.query(models.EquiposTelcel)
            .filter(models.EquiposTelcel.imei == imei)
            .first()
        )
        if existente:
            saltados_repetidos += 1
            continue

        db.add(models.EquiposTelcel(
            imei=imei,
            clave=clave,
            producto=producto,
            fecha_compra=fecha_compra
            # estatus: se deja el default 'en_bodega' de la tabla
        ))
        insertados += 1

    db.commit()

    return {
        "status": "success",
        "insertados": insertados,
        "saltados_repetidos": saltados_repetidos
    }


@router.get("/")
def listar_equipos(
    estatus: str | None = None,
    producto: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.EquiposTelcel)

    if estatus:
        query = query.filter(models.EquiposTelcel.estatus == estatus)
    if producto:
        query = query.filter(models.EquiposTelcel.producto.ilike(f"%{producto}%"))
    if fecha_inicio:
        query = query.filter(models.EquiposTelcel.fecha_compra >= fecha_inicio)
    if fecha_fin:
        query = query.filter(models.EquiposTelcel.fecha_compra <= fecha_fin)

    equipos = query.order_by(models.EquiposTelcel.id.desc()).all()

    return [
        {
            "id": e.id,
            "imei": e.imei,
            "clave": e.clave,
            "producto": e.producto,
            "fecha_compra": str(e.fecha_compra) if e.fecha_compra is not None else None,
            "estatus": e.estatus,
            "modulo_id": e.modulo_id,
            "fecha_salida": str(e.fecha_salida) if e.fecha_salida is not None else None,
        }
        for e in equipos
    ]

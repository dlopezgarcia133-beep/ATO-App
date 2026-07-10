import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.params import File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from zoneinfo import ZoneInfo

from app import models
from app.database import get_db

router = APIRouter()


class MarcarSurtidosRequest(BaseModel):
    imeis: list[str]
    modulo_id: int
    folio: str | None = None


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
    claves_no_reconocidas = []

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

        # 🔒 VALIDACIÓN: la clave debe existir en el catálogo maestro
        existe_clave = (
            db.query(models.InventarioGeneral)
            .filter(models.InventarioGeneral.clave == clave)
            .first()
        )
        if not existe_clave:
            claves_no_reconocidas.append(clave)
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
        "saltados_repetidos": saltados_repetidos,
        "rechazados_clave": len(claves_no_reconocidas),
        "claves_no_reconocidas": sorted(set(claves_no_reconocidas))
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

    modulos = {m.id: m.nombre for m in db.query(models.Modulo.id, models.Modulo.nombre).all()}

    return [
        {
            "id": e.id,
            "imei": e.imei,
            "clave": e.clave,
            "producto": e.producto,
            "fecha_compra": str(e.fecha_compra) if e.fecha_compra is not None else None,
            "estatus": e.estatus,
            "modulo_id": e.modulo_id,
            "modulo_nombre": modulos.get(e.modulo_id),
            "fecha_salida": str(e.fecha_salida) if e.fecha_salida is not None else None,
        }
        for e in equipos
    ]


@router.get("/buscar-imei/{imei}")
def buscar_por_imei(imei: str, db: Session = Depends(get_db)):
    imei = imei.strip()

    equipo = (
        db.query(models.EquiposTelcel)
        .filter(models.EquiposTelcel.imei == imei)
        .first()
    )
    if not equipo:
        raise HTTPException(
            status_code=404,
            detail=f"IMEI {imei} no está registrado en bodega"
        )

    if equipo.estatus != "en_bodega":
        raise HTTPException(
            status_code=409,
            detail=f"El equipo con IMEI {imei} ya fue surtido (estatus: {equipo.estatus})"
        )

    prod = (
        db.query(models.InventarioGeneral)
        .filter(models.InventarioGeneral.clave == equipo.clave)
        .first()
    )
    if not prod:
        raise HTTPException(
            status_code=404,
            detail=f"La clave {equipo.clave} del equipo no existe en el catálogo"
        )

    return {
        "id": equipo.id,
        "imei": equipo.imei,
        "clave": equipo.clave,
        "producto": equipo.producto,
        "producto_id": prod.id,
        "estatus": equipo.estatus,
    }


@router.post("/marcar-surtidos")
def marcar_surtidos(data: MarcarSurtidosRequest, db: Session = Depends(get_db)):
    if not data.imeis:
        return {"status": "success", "marcados": 0, "no_encontrados": [], "ya_surtidos": []}

    ahora = datetime.now(ZoneInfo("America/Mexico_City"))
    marcados = 0
    no_encontrados = []
    ya_surtidos = []

    for imei in data.imeis:
        imei_limpio = str(imei).strip()
        equipo = (
            db.query(models.EquiposTelcel)
            .filter(models.EquiposTelcel.imei == imei_limpio)
            .first()
        )
        if not equipo:
            no_encontrados.append(imei_limpio)
            continue
        if equipo.estatus != "en_bodega":
            ya_surtidos.append(imei_limpio)
            continue
        equipo.estatus = "surtido"
        equipo.modulo_id = data.modulo_id
        equipo.fecha_salida = ahora
        equipo.folio = data.folio
        marcados += 1

    db.commit()

    return {
        "status": "success",
        "marcados": marcados,
        "no_encontrados": no_encontrados,
        "ya_surtidos": ya_surtidos,
    }

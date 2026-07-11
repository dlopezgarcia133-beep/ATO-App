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


class AltaIndividualRequest(BaseModel):
    imei: str
    clave: str
    producto: str
    modulo_id: int


class AltaMultipleRequest(BaseModel):
    equipos: list[AltaIndividualRequest]


class CambiarActivacionRequest(BaseModel):
    activado: bool


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
            "fecha_venta": str(e.fecha_venta) if e.fecha_venta is not None else None,
            "activado": e.activado,
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

    ahora = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
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


@router.get("/faltantes-imei/{modulo_id}")
def faltantes_imei(modulo_id: int, db: Session = Depends(get_db)):
    # 1. Teléfonos en existencia del módulo (por cantidad)
    telefonos = (
        db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .filter(models.InventarioModulo.tipo_producto == 'telefono')
        .filter(models.InventarioModulo.cantidad > 0)
        .all()
    )
    # 2. Equipos ya con IMEI en este módulo, agrupados por clave (solo los que están en el módulo: surtido)
    equipos_por_clave = {}
    equipos = (
        db.query(models.EquiposTelcel)
        .filter(models.EquiposTelcel.modulo_id == modulo_id)
        .filter(models.EquiposTelcel.estatus == 'surtido')
        .all()
    )
    for e in equipos:
        equipos_por_clave.setdefault(e.clave, []).append(e)
    # 3. Construir la lista: por cada modelo, `cantidad` filas.
    #    Las primeras se llenan con los equipos que ya tienen IMEI; el resto van vacías.
    filas = []
    for t in telefonos:
        ya = equipos_por_clave.get(t.clave, [])
        for i in range(t.cantidad):
            if i < len(ya):
                eq = ya[i]
                filas.append({
                    "clave": t.clave,
                    "producto": t.producto,
                    "modulo_id": modulo_id,
                    "imei": eq.imei,
                    "equipo_id": eq.id,
                    "tiene_imei": True,
                })
            else:
                filas.append({
                    "clave": t.clave,
                    "producto": t.producto,
                    "modulo_id": modulo_id,
                    "imei": None,
                    "equipo_id": None,
                    "tiene_imei": False,
                })
    return filas


@router.post("/alta-individual")
def alta_individual(data: AltaIndividualRequest, db: Session = Depends(get_db)):
    imei = data.imei.strip()
    if not imei:
        raise HTTPException(status_code=400, detail="El IMEI no puede estar vacío")
    # No permitir IMEI duplicado
    existe = db.query(models.EquiposTelcel).filter(models.EquiposTelcel.imei == imei).first()
    if existe:
        raise HTTPException(status_code=400, detail=f"El IMEI {imei} ya está registrado")
    ahora = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
    equipo = models.EquiposTelcel(
        imei=imei,
        clave=data.clave.strip(),
        producto=data.producto.strip(),
        fecha_compra=ahora.date(),
        estatus="surtido",
        modulo_id=data.modulo_id,
        fecha_salida=ahora,
    )
    db.add(equipo)
    db.commit()
    db.refresh(equipo)
    return {"status": "success", "id": equipo.id, "imei": equipo.imei}


@router.post("/alta-multiple")
def alta_multiple(data: AltaMultipleRequest, db: Session = Depends(get_db)):
    if not data.equipos:
        return {"status": "success", "guardados": 0, "errores": []}
    ahora = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
    guardados = 0
    errores = []
    for eq in data.equipos:
        imei = eq.imei.strip()
        if not imei:
            errores.append({"imei": "", "motivo": "IMEI vacío"})
            continue
        existe = db.query(models.EquiposTelcel).filter(models.EquiposTelcel.imei == imei).first()
        if existe:
            errores.append({"imei": imei, "motivo": "ya registrado"})
            continue
        db.add(models.EquiposTelcel(
            imei=imei,
            clave=eq.clave.strip(),
            producto=eq.producto.strip(),
            fecha_compra=ahora.date(),
            estatus="surtido",
            modulo_id=eq.modulo_id,
            fecha_salida=ahora,
        ))
        guardados += 1
    db.commit()
    return {"status": "success", "guardados": guardados, "errores": errores}


@router.post("/activar/{equipo_id}")
def cambiar_activacion(equipo_id: int, data: CambiarActivacionRequest, db: Session = Depends(get_db)):
    equipo = db.query(models.EquiposTelcel).filter(models.EquiposTelcel.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")
    equipo.activado = data.activado
    db.commit()
    return {"status": "success", "id": equipo.id, "activado": equipo.activado}

import io
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.routers.kardex import registrar_kardex
from app.utilidades import verificar_rol_requerido

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
WARN_FILAS = 5000


def _detectar_tipo_producto(clave: str) -> str:
    return "telefono" if clave.upper().startswith(("TELI", "TETE")) else "accesorios"


def _leer_excel(contenido: bytes) -> pd.DataFrame:
    """Lee el archivo y elimina la primera fila si es encabezado."""
    df_raw = pd.read_excel(io.BytesIO(contenido), header=None, dtype=str)
    if df_raw.empty or df_raw.shape[1] < 3:
        raise HTTPException(
            status_code=400,
            detail="El archivo debe tener al menos 3 columnas: Clave, Nombre, Cantidad",
        )
    primera_cant = str(df_raw.iloc[0, 2]).strip()
    try:
        float(primera_cant)
        tiene_encabezado = False
    except (ValueError, TypeError):
        tiene_encabezado = True

    return df_raw.iloc[1:].reset_index(drop=True) if tiene_encabezado else df_raw.copy()


# ── POST /procesar ────────────────────────────────────────────────────────────

@router.post("/procesar", response_model=schemas.ProcesamientoResponse)
async def procesar_conteo(
    modulo_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    if not archivo.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .xlsx")

    contenido = await archivo.read()
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="El archivo supera el límite de 10 MB")

    modulo = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    try:
        df = _leer_excel(contenido)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {exc}")

    total_filas = len(df)
    claves_vistas: set = set()
    errores: list = []
    filas_validas: list = []  # (clave, producto, cantidad)

    for idx in range(len(df)):
        row = df.iloc[idx]
        fila_num = idx + 2  # 1-based, +1 for header row

        clave = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        producto = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
        cant_str = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""

        if not clave and not producto and (not cant_str or cant_str.lower() in ("nan", "none", "")):
            continue  # fila completamente vacía

        if not clave:
            errores.append({"fila": fila_num, "clave": "(vacía)", "motivo": "Clave vacía"})
            continue

        if len(clave) > 50:
            errores.append({"fila": fila_num, "clave": clave[:20] + "...", "motivo": "Clave supera 50 caracteres"})
            continue

        if clave in claves_vistas:
            errores.append({"fila": fila_num, "clave": clave, "motivo": "Clave duplicada en el Excel"})
            continue

        if not cant_str or cant_str.lower() in ("nan", "none", ""):
            errores.append({"fila": fila_num, "clave": clave, "motivo": "Cantidad vacía"})
            continue

        try:
            cant_float = float(cant_str)
        except (ValueError, TypeError):
            errores.append({"fila": fila_num, "clave": clave, "motivo": f"Cantidad no numérica: '{cant_str}'"})
            continue

        if cant_float < 0:
            errores.append({"fila": fila_num, "clave": clave, "motivo": f"Cantidad negativa: {cant_float}"})
            continue

        if cant_float != int(cant_float):
            errores.append({"fila": fila_num, "clave": clave, "motivo": f"Cantidad no entera: {cant_float}"})
            continue

        claves_vistas.add(clave)
        filas_validas.append((clave, producto, int(cant_float)))

    # Cargar catálogo y módulo en memoria
    claves_excel = [r[0] for r in filas_validas]
    ig_map: dict = {}
    if claves_excel:
        ig_map = {
            r.clave: r
            for r in db.query(models.InventarioGeneral)
            .filter(models.InventarioGeneral.clave.in_(claves_excel))
            .all()
        }

    im_map: dict = {
        r.clave: r
        for r in db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .all()
    }

    para_actualizar = []
    para_crear = []

    for clave, producto, cantidad_nueva in filas_validas:
        ig = ig_map.get(clave)
        im = im_map.get(clave)
        cantidad_actual = im.cantidad if im else 0

        if ig:
            para_actualizar.append({
                "clave": clave,
                "producto": ig.producto,
                "cantidad_actual": cantidad_actual,
                "cantidad_nueva": cantidad_nueva,
                "diferencia": cantidad_nueva - cantidad_actual,
            })
        else:
            para_crear.append({"clave": clave, "producto": producto, "cantidad": cantidad_nueva})

    # Productos del módulo con stock > 0 que NO están en el Excel
    decidir_caso_por_caso = [
        {"clave": clave, "producto": im.producto, "cantidad_actual": im.cantidad}
        for clave, im in im_map.items()
        if im.cantidad > 0 and clave not in claves_vistas
    ]

    return {
        "modulo_id": modulo_id,
        "modulo_nombre": modulo.nombre,
        "total_filas_excel": total_filas,
        "advertencia_volumen": total_filas > WARN_FILAS,
        "para_actualizar": para_actualizar,
        "para_crear": para_crear,
        "decidir_caso_por_caso": decidir_caso_por_caso,
        "errores": errores,
    }


# ── POST /aplicar ─────────────────────────────────────────────────────────────

@router.post("/aplicar", response_model=schemas.AplicarResponse)
def aplicar_conteo(
    data: schemas.AplicarRequest,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    modulo = db.query(models.Modulo).filter(models.Modulo.id == data.modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Crear registro maestro para obtener el id (folio se asigna después del flush)
    conteo = models.ConteoFisico(
        folio="PENDING",
        modulo=modulo.nombre,
        modulo_id=data.modulo_id,
        usuario=current_user.username,
        archivo_nombre=data.archivo_nombre,
        total_filas=data.total_filas_excel,
        notas=data.notas,
        estado="aplicado",
    )
    db.add(conteo)
    db.flush()  # genera el id sin hacer commit

    conteo.folio = f"CF-{conteo.id}"

    items_db: list = []
    cnt_actualizados = 0
    cnt_creados = 0
    cnt_en_cero = 0
    cnt_conservados = 0

    # ── Para actualizar ───────────────────────────────────────────────────────
    for item in data.para_actualizar:
        im = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave == item.clave,
                models.InventarioModulo.modulo_id == data.modulo_id,
            )
            .first()
        )
        ig = db.query(models.InventarioGeneral).filter(
            models.InventarioGeneral.clave == item.clave
        ).first()

        cantidad_anterior = im.cantidad if im else 0
        delta = item.cantidad_nueva - cantidad_anterior

        if im:
            im.cantidad = item.cantidad_nueva
        else:
            # Existe en catálogo pero no tenía registro en este módulo
            ig_ref = ig or db.query(models.InventarioGeneral).filter(
                models.InventarioGeneral.clave == item.clave
            ).first()
            nuevo_im = models.InventarioModulo(
                clave=item.clave,
                producto=item.producto,
                cantidad=item.cantidad_nueva,
                precio=ig_ref.precio or 0 if ig_ref else 0,
                modulo_id=data.modulo_id,
                tipo_producto=ig_ref.tipo_producto if ig_ref else _detectar_tipo_producto(item.clave),
            )
            db.add(nuevo_im)

        registrar_kardex(
            db,
            producto=item.producto,
            tipo_producto=ig.tipo_producto if ig else _detectar_tipo_producto(item.clave),
            cantidad=delta,
            tipo_movimiento="CONTEO_FISICO",
            usuario_id=current_user.id,
            modulo_origen_id=data.modulo_id,
            referencia_id=conteo.id,
        )

        items_db.append(models.ConteoFisicoItem(
            conteo_id=conteo.id,
            clave=item.clave,
            producto=item.producto,
            cantidad_anterior=cantidad_anterior,
            cantidad_nueva=item.cantidad_nueva,
            accion="actualizado",
            producto_creado=False,
        ))
        cnt_actualizados += 1

    # ── Para crear ────────────────────────────────────────────────────────────
    for item in data.para_crear:
        tipo_prod = _detectar_tipo_producto(item.clave)

        nuevo_ig = models.InventarioGeneral(
            clave=item.clave,
            producto=item.producto,
            cantidad=0,          # se actualiza al final de la unificación (Fase 1)
            precio=None,
            tipo_producto=tipo_prod,
        )
        db.add(nuevo_ig)
        db.flush()

        nuevo_im = models.InventarioModulo(
            clave=item.clave,
            producto=item.producto,
            cantidad=item.cantidad,
            precio=0,
            modulo_id=data.modulo_id,
            tipo_producto=tipo_prod,
        )
        db.add(nuevo_im)

        registrar_kardex(
            db,
            producto=item.producto,
            tipo_producto=tipo_prod,
            cantidad=item.cantidad,
            tipo_movimiento="CONTEO_FISICO",
            usuario_id=current_user.id,
            modulo_origen_id=data.modulo_id,
            referencia_id=conteo.id,
        )

        items_db.append(models.ConteoFisicoItem(
            conteo_id=conteo.id,
            clave=item.clave,
            producto=item.producto,
            cantidad_anterior=0,
            cantidad_nueva=item.cantidad,
            accion="creado",
            producto_creado=True,
        ))
        cnt_creados += 1

    # ── Caso por caso ─────────────────────────────────────────────────────────
    for item in data.caso_por_caso:
        im = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave == item.clave,
                models.InventarioModulo.modulo_id == data.modulo_id,
            )
            .first()
        )
        ig = db.query(models.InventarioGeneral).filter(
            models.InventarioGeneral.clave == item.clave
        ).first()

        cantidad_anterior = im.cantidad if im else 0

        if item.poner_en_cero:
            if im:
                im.cantidad = 0
            registrar_kardex(
                db,
                producto=item.producto,
                tipo_producto=ig.tipo_producto if ig else _detectar_tipo_producto(item.clave),
                cantidad=-cantidad_anterior,
                tipo_movimiento="CONTEO_FISICO",
                usuario_id=current_user.id,
                modulo_origen_id=data.modulo_id,
                referencia_id=conteo.id,
            )
            items_db.append(models.ConteoFisicoItem(
                conteo_id=conteo.id,
                clave=item.clave,
                producto=item.producto,
                cantidad_anterior=cantidad_anterior,
                cantidad_nueva=0,
                accion="puesto_en_cero",
                producto_creado=False,
            ))
            cnt_en_cero += 1
        else:
            items_db.append(models.ConteoFisicoItem(
                conteo_id=conteo.id,
                clave=item.clave,
                producto=item.producto,
                cantidad_anterior=cantidad_anterior,
                cantidad_nueva=cantidad_anterior,
                accion="conservado",
                producto_creado=False,
            ))
            cnt_conservados += 1

    conteo.productos_actualizados = cnt_actualizados
    conteo.productos_creados = cnt_creados
    conteo.productos_en_cero = cnt_en_cero

    db.bulk_save_objects(items_db)
    db.commit()

    return {
        "folio": conteo.folio,
        "modulo": modulo.nombre,
        "productos_actualizados": cnt_actualizados,
        "productos_creados": cnt_creados,
        "productos_en_cero": cnt_en_cero,
        "productos_conservados": cnt_conservados,
    }


# ── GET / (historial) ─────────────────────────────────────────────────────────

@router.get("", response_model=List[schemas.ConteoFisicoListItem])
def listar_conteos(
    modulo: Optional[str] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    q = db.query(models.ConteoFisico).order_by(models.ConteoFisico.fecha.desc())
    if modulo:
        q = q.filter(models.ConteoFisico.modulo == modulo)
    if estado:
        q = q.filter(models.ConteoFisico.estado == estado)
    return q.all()


# ── GET /{folio}/detalle ──────────────────────────────────────────────────────

@router.get("/{folio}/detalle", response_model=schemas.ConteoFisicoDetalleResponse)
def detalle_conteo(
    folio: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    conteo = db.query(models.ConteoFisico).filter(models.ConteoFisico.folio == folio).first()
    if not conteo:
        raise HTTPException(status_code=404, detail=f"Conteo {folio} no encontrado")
    return conteo


# ── POST /{folio}/revertir ────────────────────────────────────────────────────

@router.post("/{folio}/revertir", response_model=schemas.RevertirResponse)
def revertir_conteo(
    folio: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    conteo = db.query(models.ConteoFisico).filter(models.ConteoFisico.folio == folio).first()
    if not conteo:
        raise HTTPException(status_code=404, detail=f"Conteo {folio} no encontrado")
    if conteo.estado != "aplicado":
        raise HTTPException(status_code=400, detail="Este conteo ya fue revertido")

    advertencias: list[str] = []
    items_revertidos = 0

    for item in conteo.items:
        if item.accion == "conservado":
            continue  # nada que revertir

        im = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.clave == item.clave,
                models.InventarioModulo.modulo_id == conteo.modulo_id,
            )
            .first()
        )
        ig = db.query(models.InventarioGeneral).filter(
            models.InventarioGeneral.clave == item.clave
        ).first()
        tipo_prod = ig.tipo_producto if ig else _detectar_tipo_producto(item.clave or "")

        delta_reverso = (item.cantidad_anterior or 0) - (item.cantidad_nueva or 0)

        if item.producto_creado:
            # Verificar si hay movimientos de kardex DESPUÉS de este conteo
            movimientos_post = (
                db.query(models.KardexMovimiento)
                .filter(
                    models.KardexMovimiento.producto == item.producto,
                    models.KardexMovimiento.fecha > conteo.fecha,
                    models.KardexMovimiento.referencia_id != conteo.id,
                )
                .count()
            )
            if movimientos_post == 0:
                if im:
                    db.delete(im)
                if ig:
                    # Solo eliminar si no hay stock en otros módulos
                    otros_stock = (
                        db.query(models.InventarioModulo)
                        .filter(
                            models.InventarioModulo.clave == item.clave,
                            models.InventarioModulo.modulo_id != conteo.modulo_id,
                            models.InventarioModulo.cantidad > 0,
                        )
                        .count()
                    )
                    if otros_stock == 0:
                        db.delete(ig)
                    else:
                        advertencias.append(
                            f"{item.clave}: producto creado en este conteo, "
                            "pero tiene stock en otros módulos — solo se eliminó de este módulo"
                        )
            else:
                if im:
                    im.cantidad = 0
                advertencias.append(
                    f"{item.clave}: producto creado en este conteo con movimientos posteriores "
                    "— se dejó en el catálogo con cantidad 0"
                )
        else:
            if im:
                im.cantidad = item.cantidad_anterior or 0

        # Kardex inverso (solo si hubo cambio real de cantidad)
        if delta_reverso != 0:
            registrar_kardex(
                db,
                producto=item.producto or "",
                tipo_producto=tipo_prod,
                cantidad=delta_reverso,
                tipo_movimiento="CONTEO_FISICO",
                usuario_id=current_user.id,
                modulo_origen_id=conteo.modulo_id,
                referencia_id=conteo.id,
            )

        items_revertidos += 1

    conteo.estado = "revertido"
    db.commit()

    return {
        "folio": conteo.folio,
        "estado": "revertido",
        "items_revertidos": items_revertidos,
        "advertencias": advertencias,
    }

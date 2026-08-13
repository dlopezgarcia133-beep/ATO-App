import io
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.routers.kardex import registrar_kardex
from app.config import get_current_user
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

    # ── Conteo por IMEI (opcional) ────────────────────────────────────────────
    # REGLA MADRE: si data.imeis está vacío, nada de lo que sigue se ejecuta y el
    # flujo se comporta EXACTAMENTE como antes.
    snapshot_surtidos: list = []
    imeis_scan_norm: set = set()
    if data.imeis:
        # PASO A ── validaciones + snapshot ANTES de tocar nada ────────────────
        imeis_norm_list = [it.imei.strip() for it in data.imeis]
        if len(imeis_norm_list) != len(set(imeis_norm_list)):
            raise HTTPException(status_code=400, detail="Hay IMEIs duplicados en la lista")
        imeis_scan_norm = set(imeis_norm_list)

        snapshot_surtidos = (
            db.query(models.EquiposTelcel)
            .filter(
                models.EquiposTelcel.modulo_id == data.modulo_id,
                models.EquiposTelcel.estatus == "surtido",
            )
            .all()
        )

        # PASO B ── contar por clave SOLO ok/reasignado ────────────────────────
        conteo_por_clave: dict = {}
        clave_producto: dict = {}
        for it in data.imeis:
            if it.resultado in ("ok", "reasignado") and it.clave:
                conteo_por_clave[it.clave] = conteo_por_clave.get(it.clave, 0) + 1
                if it.producto:
                    clave_producto.setdefault(it.clave, it.producto)

        # Claves que SÍ manejan IMEI en este módulo (según el snapshot del
        # PASO A). Este es el criterio ÚNICO: si una clave tiene equipos
        # surtidos con IMEI aquí, se pistolea; si no, no se toca. No se filtra
        # por tipo de producto — el prefijo TELI/TETE dejaba fuera tablets,
        # módems y teléfonos que sí se pistolean (TABSAMA11, TETIPSEN, TEMOD*).
        # Este conjunto NO es una salvaguarda: hoy cubre casi todo el módulo.
        # Quien decide si una clave no pistoleada se manda a cero es el flag
        # data.conteo_imei_completo (ver C3); sin él, un conteo parcial dejaría
        # en cero todo lo que no alcanzó a escanearse.
        claves_con_imei = {e.clave for e in snapshot_surtidos}

        # PASO C ── fusionar con las listas del request ────────────────────────
        actualizar_por_clave = {it.clave: it for it in data.para_actualizar}

        # C1: cantidad pistoleada manda; sobrescribe o agrega item de actualización
        for clave, cant in conteo_por_clave.items():
            if clave in actualizar_por_clave:
                actualizar_por_clave[clave].cantidad_nueva = cant
            else:
                prod = clave_producto.get(clave)
                if not prod:
                    im_ref = (
                        db.query(models.InventarioModulo)
                        .filter(
                            models.InventarioModulo.clave == clave,
                            models.InventarioModulo.modulo_id == data.modulo_id,
                        )
                        .first()
                    )
                    prod = im_ref.producto if im_ref else clave
                nuevo = schemas.ItemAplicarActualizar(
                    clave=clave, producto=prod, cantidad_nueva=cant
                )
                data.para_actualizar.append(nuevo)
                actualizar_por_clave[clave] = nuevo

        # C2: el pistoleo manda → quitar de caso_por_caso SOLO las claves que
        # manejan IMEI en este módulo (están en claves_con_imei). El resto se
        # queda para que el admin decida, igual que hoy.
        data.caso_por_caso = [
            it for it in data.caso_por_caso
            if it.clave not in claves_con_imei
        ]

        # C3: clave con stock en el módulo que NO se pistoleó → cantidad 0,
        # SOLO si esa clave maneja IMEI aquí (está en claves_con_imei).
        # Bajo bandera: únicamente cuando el usuario declara que el pistoleo del
        # módulo está COMPLETO. En un conteo parcial, lo no escaneado se respeta.
        if data.conteo_imei_completo:
            ims_con_stock = (
                db.query(models.InventarioModulo)
                .filter(
                    models.InventarioModulo.modulo_id == data.modulo_id,
                    models.InventarioModulo.cantidad > 0,
                )
                .all()
            )
            for im in ims_con_stock:
                if (
                    im.clave not in conteo_por_clave
                    and im.clave in claves_con_imei
                ):
                    if im.clave in actualizar_por_clave:
                        actualizar_por_clave[im.clave].cantidad_nueva = 0
                    else:
                        nuevo = schemas.ItemAplicarActualizar(
                            clave=im.clave, producto=im.producto, cantidad_nueva=0
                        )
                        data.para_actualizar.append(nuevo)
                        actualizar_por_clave[im.clave] = nuevo

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

    # ── PASO D/E/F: registro de IMEIs y faltantes ─────────────────────────────
    faltantes_payload: list = []
    imeis_registrados = 0
    if data.imeis:
        # PASO D ── un ConteoFisicoImei por item; reasignar los 'reasignado' ───
        now_mx = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None)
        imeis_db: list = []
        for it in data.imeis:
            imei_norm = it.imei.strip()
            imeis_db.append(models.ConteoFisicoImei(
                conteo_id=conteo.id,
                imei=imei_norm,
                equipo_id=it.equipo_id,
                clave=it.clave,
                producto=it.producto,
                estatus_sistema=it.estatus_sistema,
                modulo_sistema_id=it.modulo_sistema_id,
                resultado=it.resultado,
                fecha=now_mx,
            ))
            if it.resultado == "reasignado":
                eq = None
                if it.equipo_id is not None:
                    eq = (
                        db.query(models.EquiposTelcel)
                        .filter(models.EquiposTelcel.id == it.equipo_id)
                        .first()
                    )
                if eq is None:
                    eq = (
                        db.query(models.EquiposTelcel)
                        .filter(func.trim(models.EquiposTelcel.imei) == imei_norm)
                        .first()
                    )
                if eq is not None:
                    eq.modulo_id = data.modulo_id
        db.bulk_save_objects(imeis_db)
        imeis_registrados = len(imeis_db)

        # PASO E ── faltantes: del snapshot, los que NO se pistolearon ─────────
        hoy = datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None).date()
        for eq in snapshot_surtidos:
            if (eq.imei or "").strip() in imeis_scan_norm:
                continue
            fecha_salida_str = None
            dias_en_piso = None
            if eq.fecha_salida:
                fs_date = eq.fecha_salida.date() if hasattr(eq.fecha_salida, "date") else eq.fecha_salida
                fecha_salida_str = fs_date.strftime("%Y-%m-%d")
                dias_en_piso = (hoy - fs_date).days
            faltantes_payload.append({
                "imei": (eq.imei or "").strip(),
                "clave": eq.clave,
                "producto": eq.producto,
                "fecha_salida": fecha_salida_str,
                "dias_en_piso": dias_en_piso,
            })

    # Descongelar automáticamente al aplicar el conteo
    modulo.congelado = False

    db.commit()

    # PASO F ── devolver faltantes e imeis_registrados (defaults = flujo viejo) ─
    return {
        "folio": conteo.folio,
        "modulo": modulo.nombre,
        "productos_actualizados": cnt_actualizados,
        "productos_creados": cnt_creados,
        "productos_en_cero": cnt_en_cero,
        "productos_conservados": cnt_conservados,
        "faltantes_imei": faltantes_payload,
        "imeis_registrados": imeis_registrados,
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
    conteo = db.query(models.ConteoFisico).filter(
        models.ConteoFisico.folio == folio
    ).first()
    if not conteo:
        raise HTTPException(status_code=404, detail=f"Conteo {folio} no encontrado")

    # IMEIs escaneados en este conteo, agrupados por clave normalizada
    filas_imei = db.query(models.ConteoFisicoImei).filter(
        models.ConteoFisicoImei.conteo_id == conteo.id
    ).all()

    imeis_por_clave = {}
    imeis_sin_clave = []

    # Un IMEI pudo darse de alta DESPUÉS de cerrar el conteo: la fila guardada
    # conserva clave NULL para siempre. Resolvemos esas filas contra
    # equipos_telcel con una sola consulta, no un query por fila.
    imeis_pendientes = {
        (f.imei or "").strip().upper()
        for f in filas_imei
        if not f.clave and (f.imei or "").strip()
    }
    clave_por_imei = {}
    if imeis_pendientes:
        rows_eq = db.query(
            models.EquiposTelcel.imei,
            models.EquiposTelcel.clave,
        ).filter(
            func.upper(func.trim(models.EquiposTelcel.imei)).in_(
                sorted(imeis_pendientes)
            )
        ).all()
        for imei_e, clave_e in rows_eq:
            if not imei_e or not clave_e:
                continue
            clave_por_imei[imei_e.strip().upper()] = clave_e.strip().upper()

    for f in filas_imei:
        if f.clave:
            k = f.clave.strip().upper()
            imeis_por_clave.setdefault(k, []).append(f.imei)
        else:
            k = clave_por_imei.get((f.imei or "").strip().upper())
            if k:
                imeis_por_clave.setdefault(k, []).append(f.imei)
            else:
                imeis_sin_clave.append(f.imei)

    # IMEIs surtidos hoy en el módulo del conteo que NO se escanearon
    imeis_escaneados_set = {
        (f.imei or "").strip() for f in filas_imei
    }
    faltantes_por_clave = {}
    if conteo.modulo_id:
        surtidos = db.query(
            models.EquiposTelcel.imei,
            models.EquiposTelcel.clave,
        ).filter(
            models.EquiposTelcel.modulo_id == conteo.modulo_id,
            models.EquiposTelcel.estatus == "surtido",
        ).all()
        for imei_s, clave_s in surtidos:
            if not imei_s or not clave_s:
                continue
            if imei_s.strip() in imeis_escaneados_set:
                continue
            faltantes_por_clave.setdefault(
                clave_s.strip().upper(), []
            ).append(imei_s.strip())

    # Claves que SÍ manejan IMEI (existen en equipos_telcel)
    claves_items = [
        i.clave.strip().upper() for i in conteo.items if i.clave
    ]
    claves_con_imei = set()
    if claves_items:
        rows = db.query(models.EquiposTelcel.clave).filter(
            func.upper(func.trim(models.EquiposTelcel.clave)).in_(claves_items)
        ).distinct().all()
        claves_con_imei = {r[0].strip().upper() for r in rows if r[0]}

    items_out = []
    for i in conteo.items:
        k = i.clave.strip().upper() if i.clave else ""
        lista = sorted(imeis_por_clave.get(k, []))
        faltan = sorted(faltantes_por_clave.get(k, []))
        aplica = k in claves_con_imei or len(lista) > 0 or len(faltan) > 0
        check = None
        if aplica:
            cuadra_cantidad = len(lista) == (i.cantidad_nueva or 0)
            check = "ok" if (not faltan and cuadra_cantidad) else "descuadre"
        items_out.append(schemas.ConteoFisicoItemResponse(
            id=i.id,
            clave=i.clave,
            producto=i.producto,
            cantidad_anterior=i.cantidad_anterior,
            cantidad_nueva=i.cantidad_nueva,
            accion=i.accion,
            producto_creado=bool(i.producto_creado),
            imeis=lista,
            imeis_escaneados=len(lista),
            imei_aplica=aplica,
            imei_check=check,
            imeis_faltantes=faltan,
        ))

    return schemas.ConteoFisicoDetalleResponse(
        id=conteo.id,
        folio=conteo.folio,
        modulo=conteo.modulo,
        fecha=conteo.fecha,
        usuario=conteo.usuario,
        archivo_nombre=conteo.archivo_nombre,
        total_filas=conteo.total_filas,
        productos_actualizados=conteo.productos_actualizados,
        productos_creados=conteo.productos_creados,
        productos_en_cero=conteo.productos_en_cero,
        estado=conteo.estado,
        notas=conteo.notas,
        items=items_out,
        imeis_sin_clave=sorted(imeis_sin_clave),
        total_imeis=len(filas_imei),
    )


# ── GET /{folio}/kardex/{clave} ───────────────────────────────────────────────

@router.get("/{folio}/kardex/{clave}", response_model=schemas.KardexProductoResponse)
def kardex_producto_conteo(
    folio: str,
    clave: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    # 1. Conteo actual
    conteo = db.query(models.ConteoFisico).filter(models.ConteoFisico.folio == folio).first()
    if not conteo:
        raise HTTPException(status_code=404, detail=f"Conteo {folio} no encontrado")

    modulo_id = conteo.modulo_id

    # 2. Conteo anterior del mismo módulo
    conteo_anterior = (
        db.query(models.ConteoFisico)
        .filter(
            models.ConteoFisico.modulo_id == modulo_id,
            models.ConteoFisico.fecha < conteo.fecha,
        )
        .order_by(models.ConteoFisico.fecha.desc())
        .first()
    )

    if conteo_anterior:
        item_anterior = (
            db.query(models.ConteoFisicoItem)
            .filter(
                models.ConteoFisicoItem.conteo_id == conteo_anterior.id,
                models.ConteoFisicoItem.clave == clave,
            )
            .first()
        )
        saldo_inicial = item_anterior.cantidad_nueva if item_anterior else 0
        fecha_inicio = conteo_anterior.fecha
        conteo_anterior_info = schemas.ConteoAnteriorInfo(
            folio=conteo_anterior.folio,
            fecha=conteo_anterior.fecha,
            saldo_inicial=saldo_inicial,
        )
    else:
        saldo_inicial = 0
        fecha_inicio = None
        conteo_anterior_info = None

    # 3. Nombre del producto en este módulo
    im = (
        db.query(models.InventarioModulo)
        .filter(
            models.InventarioModulo.clave == clave,
            models.InventarioModulo.modulo_id == modulo_id,
        )
        .first()
    )
    if not im:
        raise HTTPException(status_code=404, detail=f"Producto {clave} no encontrado en módulo {modulo_id}")
    nombre_producto = im.producto

    # 4. Movimientos de kardex del periodo (excluye CONTEO_FISICO)
    q = (
        db.query(models.KardexMovimiento)
        .filter(
            models.KardexMovimiento.producto == nombre_producto,
            models.KardexMovimiento.tipo_movimiento != models.TipoMovimientoEnum.CONTEO_FISICO,
            (
                (models.KardexMovimiento.modulo_origen_id == modulo_id) |
                (models.KardexMovimiento.modulo_destino_id == modulo_id)
            ),
            models.KardexMovimiento.fecha <= conteo.fecha,
        )
    )
    if fecha_inicio is not None:
        q = q.filter(models.KardexMovimiento.fecha > fecha_inicio)

    movimientos_db = q.order_by(models.KardexMovimiento.fecha.asc()).all()

    # 5. Calcular existencia corriente y totales
    existencia = saldo_inicial
    total_entradas = 0
    total_salidas = 0
    lineas = []

    _SUMAN = {
        models.TipoMovimientoEnum.ENTRADA,
        models.TipoMovimientoEnum.TRASPASO_ENTRADA,
        models.TipoMovimientoEnum.CANCELACION_VENTA,
        models.TipoMovimientoEnum.AJUSTE_POSITIVO,
    }
    _RESTAN = {
        models.TipoMovimientoEnum.VENTA,
        models.TipoMovimientoEnum.TRASPASO_SALIDA,
        models.TipoMovimientoEnum.AJUSTE_NEGATIVO,
    }

    for mov in movimientos_db:
        magnitud = abs(mov.cantidad or 0)
        tipo_mov = mov.tipo_movimiento
        if tipo_mov in _SUMAN:
            entrada = magnitud
            salida = 0
            existencia += magnitud
        elif tipo_mov in _RESTAN:
            entrada = 0
            salida = magnitud
            existencia -= magnitud
        else:
            entrada = 0
            salida = 0
        total_entradas += entrada
        total_salidas += salida
        lineas.append(schemas.KardexLineaItem(
            fecha=mov.fecha,
            tipo=tipo_mov.value if hasattr(tipo_mov, "value") else str(tipo_mov),
            entrada=entrada,
            salida=salida,
            existencia=existencia,
        ))

    # Cantidad contada en el conteo actual
    item_actual = (
        db.query(models.ConteoFisicoItem)
        .filter(
            models.ConteoFisicoItem.conteo_id == conteo.id,
            models.ConteoFisicoItem.clave == clave,
        )
        .first()
    )
    contado = item_actual.cantidad_nueva if item_actual else 0

    if conteo_anterior_info is not None:
        saldo_calculado = saldo_inicial + total_entradas - total_salidas
        diferencia = contado - saldo_calculado
        tiene_comparativo = True
    else:
        saldo_calculado = None
        diferencia = None
        tiene_comparativo = False

    return schemas.KardexProductoResponse(
        clave=clave,
        producto=nombre_producto,
        modulo=conteo.modulo,
        tiene_comparativo=tiene_comparativo,
        conteo_anterior=conteo_anterior_info,
        movimientos=lineas,
        total_entradas=total_entradas,
        total_salidas=total_salidas,
        saldo_calculado=saldo_calculado,
        contado=contado,
        diferencia=diferencia,
    )


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


# ── POST /imei/validar ────────────────────────────────────────────────────────

@router.post("/imei/validar", response_model=schemas.ValidarImeiResponse)
def validar_imei(
    request: schemas.ValidarImeiRequest,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    imei = request.imei.strip()

    if not imei:
        raise HTTPException(status_code=400, detail="IMEI vacio")

    equipo = (
        db.query(models.EquiposTelcel)
        .filter(func.trim(models.EquiposTelcel.imei) == imei)
        .first()
    )

    if not equipo:
        # No existe: ahora sí exigimos formato estándar de IMEI.
        if not imei.isdigit() or len(imei) < 14 or len(imei) > 15:
            raise HTTPException(
                status_code=400,
                detail=f"IMEI invalido: {imei}. Verifica el escaneo.",
            )
        return schemas.ValidarImeiResponse(
            imei=imei,
            encontrado=False,
            resultado="pendiente_alta",
            mensaje="IMEI no dado de alta. Se contara y queda pendiente.",
        )

    # Nombre del módulo actual del equipo (JOIN a modulos)
    modulo_sistema_nombre = None
    if equipo.modulo_id is not None:
        modulo = (
            db.query(models.Modulo)
            .filter(models.Modulo.id == equipo.modulo_id)
            .first()
        )
        if modulo:
            modulo_sistema_nombre = modulo.nombre

    if equipo.estatus == "vendido":
        resultado = "vendido_presente"
        mensaje = "OJO: este equipo figura como VENDIDO pero esta fisicamente."
    elif equipo.modulo_id != request.modulo_id:
        resultado = "reasignado"
        nombre_ref = modulo_sistema_nombre or "otro modulo"
        mensaje = f"Equipo estaba en {nombre_ref}. Se reasignara a este modulo."
    else:
        resultado = "ok"
        mensaje = "OK"

    return schemas.ValidarImeiResponse(
        imei=imei,
        encontrado=True,
        resultado=resultado,
        clave=equipo.clave,
        producto=equipo.producto,
        estatus_sistema=equipo.estatus,
        modulo_sistema_id=equipo.modulo_id,
        modulo_sistema_nombre=modulo_sistema_nombre,
        mensaje=mensaje,
    )


# ── Congelar / descongelar módulo ────────────────────────────────────────────

@router.post("/modulos/{modulo_id}/congelar")
def congelar_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    modulo = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")
    modulo.congelado = True
    db.commit()
    return {"modulo_id": modulo_id, "nombre": modulo.nombre, "congelado": True}


@router.post("/modulos/{modulo_id}/descongelar")
def descongelar_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    modulo = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")
    modulo.congelado = False
    db.commit()
    return {"modulo_id": modulo_id, "nombre": modulo.nombre, "congelado": False}


@router.get("/modulos/estado-congelado")
def estado_congelado_modulos(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    modulos = db.query(models.Modulo).order_by(models.Modulo.nombre).all()
    return [{"id": m.id, "nombre": m.nombre, "congelado": m.congelado} for m in modulos]


# ── Resumen IMEI del módulo (solo lectura) ───────────────────────────────────
# Alimenta el diálogo de confirmación del frontend ANTES de aplicar un conteo
# por IMEI. Repite a propósito las dos consultas del PASO A y de C3 en
# /aplicar, con el mismo criterio único (tener IMEI registrado en el módulo):
# si el número que ve el usuario saliera por otro criterio que el del borrado,
# el diálogo daría una falsa tranquilidad justo cuando más caro cuesta
# equivocarse.

@router.get("/modulos/{modulo_id}/resumen-imei")
def resumen_imei_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin)),
):
    modulo = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if not modulo:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Misma consulta que el snapshot del PASO A de /aplicar.
    snapshot_surtidos = (
        db.query(models.EquiposTelcel)
        .filter(
            models.EquiposTelcel.modulo_id == modulo_id,
            models.EquiposTelcel.estatus == "surtido",
        )
        .all()
    )
    claves_con_imei = {e.clave for e in snapshot_surtidos}

    # Misma consulta que ims_con_stock de C3.
    ims_con_stock = (
        db.query(models.InventarioModulo)
        .filter(
            models.InventarioModulo.modulo_id == modulo_id,
            models.InventarioModulo.cantidad > 0,
        )
        .all()
    )

    # Universo COMPLETO que C3 pondría en cero si no se pistolea. El frontend
    # resta lo que ya escaneó; aquí no se descuenta nada.
    claves_zeroables = [
        {
            "clave": im.clave,
            "producto": im.producto,
            "cantidad_actual": im.cantidad,
        }
        for im in ims_con_stock
        if im.clave in claves_con_imei
    ]
    claves_zeroables.sort(key=lambda x: x["clave"])

    return {
        "total_surtidos": len(snapshot_surtidos),
        "claves_con_imei": len(claves_con_imei),
        "claves_zeroables": claves_zeroables,
    }

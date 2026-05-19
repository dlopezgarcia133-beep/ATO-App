import base64
import os
import traceback
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_current_user
from app.database import get_db

ZONA = ZoneInfo("America/Mexico_City")


def _hora_mx_str(dt: datetime) -> str:
    """datetime (cualquier tz) → '9:20 a.m.' en zona México."""
    dt_mx = dt.astimezone(ZONA)
    hora = str(dt_mx.hour % 12 or 12)
    minuto = f"{dt_mx.minute:02d}"
    sufijo = "a.m." if dt_mx.hour < 12 else "p.m."
    return f"{hora}:{minuto} {sufijo}"


router = APIRouter(prefix="/asistencia", tags=["Asistencia"])
modulos_router = APIRouter(prefix="/modulos", tags=["Asistencia"])
promotores_router = APIRouter(prefix="/promotores", tags=["Promotores Cadenas"])


# ── Supabase admin client ─────────────────────────────────────────────────────

def _supabase_admin():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(500, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY no configurados")
    return create_client(url, key)


# ── Helper: agrupar registros por (usuario, fecha) ───────────────────────────

def _agrupar(registros: list, include_user: bool = False) -> List[schemas.AsistenciaResumenDia]:
    dias: dict = {}
    for r in registros:
        key = (r.usuario_id, r.fecha) if include_user else (0, r.fecha)
        if key not in dias:
            dias[key] = {"entrada": None, "salida": None}
        dias[key][r.tipo] = r

    resultado = []
    for key in sorted(dias):
        data = dias[key]
        ent = data.get("entrada")
        sal = data.get("salida")

        horas = 0.0
        if ent and sal and ent.hora and sal.hora:
            from datetime import timezone as _utc
            def _to_utc(dt):
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=_utc.utc)
                return dt.astimezone(_utc.utc)
            delta = _to_utc(sal.hora) - _to_utc(ent.hora)
            horas = max(0.0, delta.total_seconds() / 3600)

        ref = ent or sal
        modulo_nombre = None
        if ref and ref.modulo_rel:
            modulo_nombre = ref.modulo_rel.nombre

        lugar_trabajo = None
        if ref and ref.usuario:
            lugar_trabajo = ref.usuario.lugar_trabajo

        resultado.append(schemas.AsistenciaResumenDia(
            fecha=(ent or sal).fecha,
            entrada=ent.hora if ent else None,
            salida=sal.hora if sal else None,
            horas_trabajadas=round(horas, 2),
            foto_entrada_url=ent.foto_url if ent else None,
            foto_salida_url=sal.foto_url if sal else None,
            dentro_de_zona_entrada=ent.dentro_de_zona if ent else None,
            dentro_de_zona_salida=sal.dentro_de_zona if sal else None,
            distancia_metros_entrada=ent.distancia_metros if ent else None,
            distancia_metros_salida=sal.distancia_metros if sal else None,
            username=ent.username if ent else (sal.username if sal else None),
            modulo_id=ent.modulo_id if ent else (sal.modulo_id if sal else None),
            modulo_nombre=modulo_nombre,
            lugar_trabajo=lugar_trabajo,
        ))
    return resultado


# ── Endpoints de asistencia ───────────────────────────────────────────────────

@router.post("/check", response_model=schemas.AsistenciaResponse)
def check_asistencia(
    body: schemas.AsistenciaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("asesor", "encargado"):
        raise HTTPException(403, "Solo asesores y encargados pueden registrar asistencia")

    modulo = db.query(models.Modulo).filter(models.Modulo.id == current_user.modulo_id).first()
    if not modulo:
        raise HTTPException(404, "El usuario no tiene módulo asignado")

    fecha_actual = datetime.now(ZONA).date()

    if body.tipo == "entrada":
        existente = db.query(models.Asistencia).filter(
            models.Asistencia.usuario_id == current_user.id,
            models.Asistencia.fecha == fecha_actual,
            models.Asistencia.tipo == "entrada",
        ).first()
        if existente:
            raise HTTPException(400, detail={
                "codigo": "ENTRADA_DUPLICADA",
                "mensaje": f"Ya tienes registrado tu CHECK-IN de hoy a las {_hora_mx_str(existente.hora)}. Si crees que es un error, reporta a administración.",
            })
    else:
        entrada_hoy = db.query(models.Asistencia).filter(
            models.Asistencia.usuario_id == current_user.id,
            models.Asistencia.fecha == fecha_actual,
            models.Asistencia.tipo == "entrada",
        ).first()
        if not entrada_hoy:
            db.add(models.NotificacionAsistencia(
                asistencia_id=None,
                usuario_id=current_user.id,
                username=current_user.username,
                modulo_id=current_user.modulo_id,
                mensaje=(
                    f"🚨 SIN CHECK-IN: {current_user.username} intentó hacer check-out "
                    f"sin haber registrado entrada el día {fecha_actual}"
                ),
                distancia_metros=None,
            ))
            db.commit()
            raise HTTPException(400, detail={
                "codigo": "SIN_CHECKIN",
                "mensaje": "No tienes registrado tu CHECK-IN de hoy. Por favor reporta esto a administración para que lo revisen.",
            })
        salida_existente = db.query(models.Asistencia).filter(
            models.Asistencia.usuario_id == current_user.id,
            models.Asistencia.fecha == fecha_actual,
            models.Asistencia.tipo == "salida",
        ).first()
        if salida_existente:
            raise HTTPException(400, detail={
                "codigo": "SALIDA_DUPLICADA",
                "mensaje": f"Ya tienes registrado tu CHECK-OUT de hoy a las {_hora_mx_str(salida_existente.hora)}. Si crees que es un error, reporta a administración.",
            })

    # Determinar si es promotor de Cadenas (módulo contiene "Cadenas" y username empieza con "C")
    is_cadenas_promotor = (
        "Cadenas" in (modulo.nombre or "")
        and current_user.username.startswith("C")
    )

    dentro_de_zona = True
    distancia = None

    if is_cadenas_promotor:
        if (
            current_user.latitud_promotor is not None
            and current_user.longitud_promotor is not None
        ):
            from app.utils.geo import distancia_metros
            distancia = distancia_metros(
                body.latitud, body.longitud,
                current_user.latitud_promotor, current_user.longitud_promotor,
            )
            dentro_de_zona = distancia <= (current_user.radio_metros_promotor or 100)
        # Si no tiene coords configuradas: dentro_de_zona = True por default
    elif modulo.latitud is not None and modulo.longitud is not None:
        from app.utils.geo import distancia_metros
        distancia = distancia_metros(body.latitud, body.longitud, modulo.latitud, modulo.longitud)
        dentro_de_zona = distancia <= (modulo.radio_metros or 100)

    # Subir foto a Supabase Storage
    supabase = _supabase_admin()
    ts = int(datetime.now(ZONA).timestamp())
    fecha_str = fecha_actual.isoformat()
    filename = f"{current_user.username}_{fecha_str}_{body.tipo}_{ts}.jpg"

    raw_b64 = body.foto_base64.strip()
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1].strip()

    if not raw_b64:
        raise HTTPException(400, detail={
            "codigo": "FOTO_INVALIDA",
            "mensaje": "La foto no se capturó correctamente (imagen vacía). Intenta de nuevo.",
        })

    try:
        img_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(400, detail={
            "codigo": "FOTO_INVALIDA",
            "mensaje": "La foto no es válida (datos corruptos). Intenta de nuevo.",
        })

    if len(img_bytes) < 3072:
        raise HTTPException(400, detail={
            "codigo": "FOTO_INVALIDA",
            "mensaje": "La foto no se capturó correctamente (imagen demasiado pequeña). Intenta de nuevo.",
        })

    supabase.storage.from_("asistencia-fotos").upload(
        path=filename,
        file=img_bytes,
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )
    foto_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/asistencia-fotos/{filename}"

    ahora = datetime.now(ZONA)
    registro = models.Asistencia(
        usuario_id=current_user.id,
        username=current_user.username,
        modulo_id=current_user.modulo_id,
        fecha=fecha_actual,
        tipo=body.tipo,
        hora=ahora,
        latitud=body.latitud,
        longitud=body.longitud,
        foto_url=foto_url,
        dentro_de_zona=dentro_de_zona,
        distancia_metros=distancia,
    )
    db.add(registro)

    db.flush()

    if not dentro_de_zona:
        notif = models.NotificacionAsistencia(
            asistencia_id=registro.id,
            usuario_id=current_user.id,
            username=current_user.username,
            modulo_id=current_user.modulo_id,
            mensaje=(
                f"{current_user.username} hizo {body.tipo} fuera de zona "
                f"— a {int(distancia)} metros del punto de referencia"
            ),
            distancia_metros=distancia,
        )
        db.add(notif)

    db.commit()
    db.refresh(registro)
    return registro


@router.get("/mi-historial", response_model=List[schemas.AsistenciaResumenDia])
def mi_historial(
    desde: date = Query(...),
    hasta: date = Query(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("asesor", "encargado"):
        raise HTTPException(403, "Solo asesores y encargados")

    registros = (
        db.query(models.Asistencia)
        .filter(
            models.Asistencia.usuario_id == current_user.id,
            models.Asistencia.fecha >= desde,
            models.Asistencia.fecha <= hasta,
        )
        .all()
    )
    return _agrupar(registros)


@router.get("/admin", response_model=List[schemas.AsistenciaResumenDia])
def admin_historial(
    usuario_id: Optional[int] = None,
    modulo_id: Optional[int] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")

    q = db.query(models.Asistencia)
    if usuario_id:
        q = q.filter(models.Asistencia.usuario_id == usuario_id)
    if modulo_id:
        q = q.filter(models.Asistencia.modulo_id == modulo_id)
    if desde:
        q = q.filter(models.Asistencia.fecha >= desde)
    if hasta:
        q = q.filter(models.Asistencia.fecha <= hasta)

    return _agrupar(q.all(), include_user=True)


PRIMER_CICLO = date(2026, 5, 11)
_MESES = ["ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]


@router.get("/ciclos", response_model=List[schemas.CicloSemana])
def listar_ciclos(
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")

    hoy = datetime.now(ZONA).date()
    lunes_actual = hoy - timedelta(days=hoy.weekday())

    ciclos = []
    lunes = PRIMER_CICLO
    while lunes <= lunes_actual:
        domingo = lunes + timedelta(days=6)
        label = (
            f"lun {lunes.day} de {_MESES[lunes.month - 1]}"
            f" — dom {domingo.day} de {_MESES[domingo.month - 1]}"
        )
        ciclos.append(schemas.CicloSemana(inicio=lunes, fin=domingo, label=label))
        lunes += timedelta(days=7)

    ciclos.reverse()
    return ciclos


@router.get("/acumulado-semanal", response_model=List[schemas.EmpleadoAcumuladoSemanal])
def acumulado_semanal(
    ciclo: date = Query(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")

    if ciclo.weekday() != 0:
        raise HTTPException(400, "ciclo debe ser un lunes (weekday=0)")

    try:
        lunes = ciclo
        domingo = ciclo + timedelta(days=6)

        registros = (
            db.query(models.Asistencia)
            .filter(
                models.Asistencia.fecha >= lunes,
                models.Asistencia.fecha <= domingo,
            )
            .all()
        )
        resumenes = _agrupar(registros, include_user=True)

        por_username: Dict[str, Dict] = {}
        for r in resumenes:
            if r.username not in por_username:
                por_username[r.username] = {}
            por_username[r.username][r.fecha] = r

        empleados = (
            db.query(models.Usuario)
            .filter(models.Usuario.activo == True)  # noqa: E712
            .filter(models.Usuario.rol.in_(["asesor", "encargado"]))
            .order_by(models.Usuario.username)
            .all()
        )

        ciclo_anterior = lunes - timedelta(days=7)
        jornadas = (
            db.query(models.JornadaAsistencia)
            .filter(models.JornadaAsistencia.ciclo_inicio.in_([lunes, ciclo_anterior]))
            .all()
        )
        jornada_map: Dict[tuple, float] = {
            (j.usuario_id, j.ciclo_inicio): float(j.horas) for j in jornadas
        }

        resultado = []
        for emp in empleados:
            dias_emp = por_username.get(emp.username, {})
            dias: Dict[str, Optional[schemas.DiaResumen]] = {}
            total_horas = 0.0

            for i in range(7):
                dia = lunes + timedelta(days=i)
                r = dias_emp.get(dia)
                if r is not None:
                    dias[dia.isoformat()] = schemas.DiaResumen(
                        entrada=r.entrada,
                        salida=r.salida,
                        horas=r.horas_trabajadas,
                    )
                    total_horas += r.horas_trabajadas
                else:
                    dias[dia.isoformat()] = None

            total_horas = round(total_horas, 2)

            jornada = jornada_map.get((emp.id, lunes))
            if jornada is None:
                jornada = jornada_map.get((emp.id, ciclo_anterior))

            horas_extra = round(total_horas - jornada, 2) if jornada is not None else None

            resultado.append(schemas.EmpleadoAcumuladoSemanal(
                usuario_id=emp.id,
                username=emp.username,
                nombre_completo=emp.nombre_completo or emp.username,
                dias=dias,
                total_horas=total_horas,
                jornada=jornada,
                horas_extra=horas_extra,
            ))

        return resultado

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)} | {traceback.format_exc()}",
        )


@router.put("/jornada")
def upsert_jornada(
    body: schemas.JornadaUpsert,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")

    existente = (
        db.query(models.JornadaAsistencia)
        .filter(
            models.JornadaAsistencia.usuario_id == body.usuario_id,
            models.JornadaAsistencia.ciclo_inicio == body.ciclo,
        )
        .first()
    )

    if existente:
        existente.horas = body.horas
        existente.updated_at = datetime.now(ZONA)
    else:
        db.add(models.JornadaAsistencia(
            usuario_id=body.usuario_id,
            ciclo_inicio=body.ciclo,
            horas=body.horas,
        ))

    db.commit()
    return {"ok": True}


@router.get("/notificaciones", response_model=List[schemas.NotificacionResponse])
def listar_notificaciones(
    solo_no_leidas: bool = True,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion", "encargado"):
        raise HTTPException(403, "Sin permiso para ver notificaciones")

    q = db.query(models.NotificacionAsistencia)
    if current_user.rol == "encargado":
        q = q.filter(models.NotificacionAsistencia.modulo_id == current_user.modulo_id)
    if solo_no_leidas:
        q = q.filter(models.NotificacionAsistencia.leida == False)  # noqa: E712
    return q.order_by(models.NotificacionAsistencia.creada_at.desc()).all()


@router.put("/notificaciones/{notif_id}/marcar-leida")
def marcar_leida(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion", "encargado"):
        raise HTTPException(403, "Sin permiso para marcar notificaciones")

    notif = db.query(models.NotificacionAsistencia).filter(
        models.NotificacionAsistencia.id == notif_id
    ).first()
    if not notif:
        raise HTTPException(404, "Notificación no encontrada")

    if current_user.rol == "encargado" and notif.modulo_id != current_user.modulo_id:
        raise HTTPException(403, "Solo puedes marcar notificaciones de tu módulo")

    notif.leida = True
    db.commit()
    return {"ok": True}


# ── Endpoints de módulos (ubicación) ─────────────────────────────────────────

@modulos_router.put("/{modulo_id}/ubicacion")
def actualizar_ubicacion_modulo(
    modulo_id: int,
    body: schemas.ModuloUbicacionUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(403, "Solo admin")

    modulo = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if not modulo:
        raise HTTPException(404, "Módulo no encontrado")

    modulo.latitud = body.latitud
    modulo.longitud = body.longitud
    modulo.radio_metros = body.radio_metros
    db.commit()
    return {"ok": True}


@modulos_router.get("/con-ubicacion", response_model=List[schemas.ModuloConUbicacion])
def modulos_con_ubicacion(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")
    return db.query(models.Modulo).all()


@modulos_router.get("/{modulo_id}/encargado", response_model=schemas.EncargadoResponse)
def encargado_del_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    encargado = (
        db.query(models.Usuario)
        .filter(
            models.Usuario.modulo_id == modulo_id,
            models.Usuario.rol == "encargado",
            models.Usuario.activo == True,  # noqa: E712
        )
        .first()
    )
    if not encargado:
        raise HTTPException(404, "Este módulo no tiene encargado asignado")
    return schemas.EncargadoResponse(
        modulo_id=modulo_id,
        usuario_id=encargado.id,
        username=encargado.username,
        nombre_completo=encargado.nombre_completo,
    )


# ── Endpoints de promotores Cadenas (ubicación por promotor) ─────────────────

@promotores_router.get("/con-ubicacion", response_model=List[schemas.PromotorConUbicacion])
def promotores_con_ubicacion(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Solo admin y dirección")

    return (
        db.query(models.Usuario)
        .join(models.Modulo, models.Usuario.modulo_id == models.Modulo.id)
        .filter(
            models.Usuario.username.like("C%"),
            models.Modulo.nombre.contains("Cadenas"),
        )
        .all()
    )


@promotores_router.put("/{usuario_id}/ubicacion")
def actualizar_ubicacion_promotor(
    usuario_id: int,
    body: schemas.PromotorUbicacionUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(403, "Solo admin")

    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    modulo = db.query(models.Modulo).filter(models.Modulo.id == usuario.modulo_id).first()
    if not modulo or "Cadenas" not in (modulo.nombre or ""):
        raise HTTPException(400, "El usuario no pertenece al módulo Cadenas")

    if not usuario.username.startswith("C"):
        raise HTTPException(400, "El username del usuario no empieza con C")

    usuario.lugar_trabajo = body.lugar_trabajo
    usuario.latitud_promotor = body.latitud_promotor
    usuario.longitud_promotor = body.longitud_promotor
    usuario.radio_metros_promotor = body.radio_metros_promotor
    db.commit()
    return {"ok": True}

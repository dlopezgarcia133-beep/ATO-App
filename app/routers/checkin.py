from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.database import get_db
from app.routers.usuarios import get_current_user
from app import models

router = APIRouter()
ZONA = ZoneInfo("America/Mexico_City")


def _hoy():
    return datetime.now(ZONA).strftime("%Y-%m-%d")


def _sumar(h, mins):
    hh, mm = map(int, h.split(":"))
    return (datetime(2000, 1, 1, hh, mm) + timedelta(minutes=mins)).strftime("%H:%M")


def _dias_semana():
    d = datetime.now(ZONA)
    dom = d - timedelta(days=d.weekday() + 1) if d.weekday() != 6 else d
    return [(dom + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def _get_registros(db: Session):
    rows = db.execute(text(
        "SELECT fecha, idx, entrada, salida, horas, cumple FROM registros"
    )).mappings().all()
    result = {}
    for r in rows:
        f, i = str(r["fecha"]), str(r["idx"])
        if f not in result:
            result[f] = {}
        c = r["cumple"]
        cumple = True if c == "TRUE" else (False if c == "FALSE" else None)
        result[f][i] = {
            "entrada": r["entrada"] or None,
            "salida": r["salida"] or None,
            "horas": float(r["horas"]) if r["horas"] is not None else None,
            "cumple": cumple,
        }
    return result


def _upsert(db: Session, fecha, idx, entrada, salida, horas, cumple):
    cumple_str = "TRUE" if cumple is True else ("FALSE" if cumple is False else None)
    db.execute(text("""
        INSERT INTO registros (fecha, idx, entrada, salida, horas, cumple)
        VALUES (:fecha, :idx, :entrada, :salida, :horas, :cumple)
        ON CONFLICT (fecha, idx) DO UPDATE SET
            entrada = EXCLUDED.entrada,
            salida = EXCLUDED.salida,
            horas = EXCLUDED.horas,
            cumple = EXCLUDED.cumple
    """), {
        "fecha": str(fecha), "idx": str(idx),
        "entrada": entrada or None, "salida": salida or None,
        "horas": horas, "cumple": cumple_str,
    })
    db.commit()


def _delete(db: Session, fecha, idx):
    db.execute(text("DELETE FROM registros WHERE fecha = :fecha AND idx = :idx"),
               {"fecha": str(fecha), "idx": str(idx)})
    db.commit()


@router.get("/promotores")
def get_promotores(db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    rows = db.execute(text("""
        SELECT u.username, u.nombre_completo
        FROM usuarios u
        JOIN modulos m ON m.id = u.modulo_id
        WHERE m.nombre ILIKE '%cadena%' AND u.activo = true
        ORDER BY u.username
    """)).mappings().all()
    return [{"nombre": r["username"], "tel": ""} for r in rows]


@router.post("/promotores")
def save_promotores(data: list = Body(...), db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    db.execute(text("DELETE FROM promotores"))
    for p in data:
        db.execute(text("INSERT INTO promotores (nombre, tel) VALUES (:nombre, :tel)"),
                   {"nombre": p.get("nombre", ""), "tel": p.get("tel", "")})
    db.commit()
    return {"ok": True}


@router.get("/registros/todos")
def get_todos(db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    return _get_registros(db)


@router.get("/registros/semana")
def get_semana(db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    return {"registros": _get_registros(db), "dias": _dias_semana(), "hoy": _hoy()}


@router.post("/checkin")
def checkin(d: dict = Body(...), db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    idx = str(d["idx"]); hora = d["hora"]; fecha = d.get("fecha", _hoy())
    _upsert(db, fecha, idx, hora, None, None, None)
    return {"ok": True, "salida": _sumar(hora, 363)}


@router.post("/checkout")
def checkout(d: dict = Body(...), db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    idx = str(d["idx"]); fecha = d.get("fecha", _hoy())
    entrada = (_get_registros(db).get(fecha, {}).get(idx, {}) or {}).get("entrada", "")
    _upsert(db, fecha, idx, entrada, d["salida"], d["horas"], d["cumple"])
    return {"ok": True}


@router.delete("/checkin/{idx}")
def del_checkin(idx: str, fecha: str | None = None, db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    _delete(db, fecha or _hoy(), idx)
    return {"ok": True}


@router.post("/editar")
def editar(d: dict = Body(...), db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    idx = str(d["idx"]); fo = d["fecha_orig"]; fn = d["fecha_nueva"]
    entrada = d["entrada"]; salida = d.get("salida", "")
    horas = cumple = None
    if salida and entrada:
        try:
            hh1, mm1 = map(int, entrada.split(":")); hh2, mm2 = map(int, salida.split(":"))
            mins = (hh2 * 60 + mm2) - (hh1 * 60 + mm1)
            horas = round(mins / 60, 2); cumple = mins >= 360
        except Exception:
            pass
    _delete(db, fo, idx)
    _upsert(db, fn, idx, entrada, salida or None, horas, cumple)
    return {"ok": True}


@router.post("/semana/reset")
def reset_semana(db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    db.execute(text("DELETE FROM registros"))
    db.commit()
    return {"ok": True}


@router.post("/cerrar-semana")
def cerrar_semana(d: dict = Body(...), db: Session = Depends(get_db), _: models.Usuario = Depends(get_current_user)):
    inicio = d["inicio"]
    fin = d["fin"]
    promotores = db.execute(text("""
        SELECT u.username
        FROM usuarios u
        JOIN modulos m ON m.id = u.modulo_id
        WHERE m.nombre ILIKE '%cadena%' AND u.activo = true
    """)).mappings().all()

    resultados = []
    for p in promotores:
        usuario = p["username"]

        # detalle por dia: lista de fechas del rango y si cada una cumple
        regs = db.execute(text("""
            SELECT fecha, cumple
            FROM registros
            WHERE idx = :usuario AND fecha >= :inicio AND fecha <= :fin
        """), {"usuario": usuario, "inicio": inicio, "fin": fin}).mappings().all()
        cumple_por_fecha = {str(r["fecha"]): (r["cumple"] == "TRUE") for r in regs}

        # construir las 7 fechas del rango
        from datetime import datetime as _dt, timedelta as _td
        d0 = _dt.strptime(inicio, "%Y-%m-%d").date()
        fechas7 = [(d0 + _td(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        detalle = [{"fecha": f, "cumple": cumple_por_fecha.get(f, False)} for f in fechas7]

        dias = sum(1 for x in detalle if x["cumple"])
        bono = dias >= 6
        multa = 0 if dias >= 6 else 458 * (6 - dias)

        import json as _json
        db.execute(text("""
            INSERT INTO checkin_semanas (username, semana_inicio, semana_fin, dias_cumplidos, bono, multa, dias_detalle, cerrado_en)
            VALUES (:u, :ini, :fin, :dias, :bono, :multa, CAST(:detalle AS JSONB), now())
            ON CONFLICT (username, semana_inicio) DO UPDATE SET
                semana_fin = EXCLUDED.semana_fin,
                dias_cumplidos = EXCLUDED.dias_cumplidos,
                bono = EXCLUDED.bono,
                multa = EXCLUDED.multa,
                dias_detalle = EXCLUDED.dias_detalle,
                cerrado_en = now()
        """), {"u": usuario, "ini": inicio, "fin": fin, "dias": dias, "bono": bono, "multa": multa, "detalle": _json.dumps(detalle)})
        resultados.append({"username": usuario, "dias": dias, "bono": bono, "multa": multa})
    db.commit()
    return {"ok": True, "cerrados": len(resultados), "resultados": resultados}


@router.get("/mi-semana-pasada")
def mi_semana_pasada(db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    usuario = current_user.username
    row = db.execute(text("""
        SELECT username, semana_inicio, semana_fin, dias_cumplidos, bono, multa, dias_detalle
        FROM checkin_semanas
        WHERE username = :u
        ORDER BY semana_inicio DESC
        LIMIT 1
    """), {"u": usuario}).mappings().first()
    if not row:
        return None
    return dict(row)

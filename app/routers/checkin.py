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
    rows = db.execute(text("SELECT nombre, tel FROM promotores ORDER BY id")).mappings().all()
    return [{"nombre": r["nombre"], "tel": r["tel"] or ""} for r in rows]


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

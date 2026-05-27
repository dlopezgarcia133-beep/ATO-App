from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from app.database import get_db
from app.config import get_current_user
from app import models

router = APIRouter()


class MarquesinaIn(BaseModel):
    texto: str


@router.get("/config/marquesina")
def get_marquesina(db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT valor FROM configuracion WHERE clave = 'marquesina'")
    ).fetchone()
    return {"texto": row[0] if row else ""}


@router.put("/config/marquesina")
def put_marquesina(
    body: MarquesinaIn,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    if current_user.rol not in ("admin", "direccion"):
        raise HTTPException(403, "Sin permisos")
    db.execute(
        text(
            "INSERT INTO configuracion (clave, valor) VALUES ('marquesina', :v) "
            "ON CONFLICT (clave) DO UPDATE SET valor = :v"
        ),
        {"v": body.texto},
    )
    db.commit()
    return {"ok": True}

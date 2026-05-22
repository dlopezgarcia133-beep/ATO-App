from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.config import get_current_user
from app.database import get_db

router = APIRouter()

FORMAS_PAGO_VALIDAS = {"BBVA", "Banco Azteca", "Kids"}


class NominaGrupoUpdate(BaseModel):
    sueldo_base: float
    forma_pago: Optional[str] = None
    cuenta_clabe: Optional[str] = None
    cuenta_interbancaria: Optional[str] = None


class EnglobadoUpdate(BaseModel):
    nombre_englobado: Optional[str] = None


def _solo_admin(user: models.Usuario) -> None:
    if user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")


@router.get("/nomina")
def get_nomina_consolidada(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuarios = db.query(models.Usuario).filter(models.Usuario.activo == True).all()

    groups: dict = defaultdict(list)
    for u in usuarios:
        key = u.nombre_englobado or u.username
        groups[key].append(u)

    result = []
    for group_name, perfiles in sorted(groups.items()):
        principal = next((p for p in perfiles if (p.sueldo_base or 0) > 0), perfiles[0])
        sueldo_total = sum(p.sueldo_base or 0 for p in perfiles)

        result.append({
            "nombre_englobado": group_name,
            "sueldo_base_total": sueldo_total,
            "forma_pago": principal.forma_pago,
            "cuenta_clabe": principal.cuenta_clabe,
            "cuenta_interbancaria": principal.cuenta_interbancaria,
            "perfiles_incluidos": [
                {
                    "id": p.id,
                    "codigo": p.username,
                    "modulo": p.modulo.nombre if p.modulo else None,
                    "sueldo": p.sueldo_base or 0,
                }
                for p in sorted(perfiles, key=lambda x: x.id)
            ],
        })

    return result


@router.put("/nomina/{nombre_englobado}")
def update_nomina_grupo(
    nombre_englobado: str,
    data: NominaGrupoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    if data.forma_pago and data.forma_pago not in FORMAS_PAGO_VALIDAS:
        raise HTTPException(400, f"forma_pago debe ser uno de: {', '.join(FORMAS_PAGO_VALIDAS)}")
    if data.sueldo_base < 0:
        raise HTTPException(400, "sueldo_base debe ser >= 0")
    if data.cuenta_clabe and not (18 <= len(data.cuenta_clabe) <= 20):
        raise HTTPException(400, "cuenta_clabe debe tener entre 18 y 20 caracteres")

    # Buscar por nombre_englobado
    perfiles = (
        db.query(models.Usuario)
        .filter(
            models.Usuario.nombre_englobado == nombre_englobado,
            models.Usuario.activo == True,
        )
        .all()
    )

    # Si no hay, asumir grupo de uno (clave == username, sin nombre_englobado)
    if not perfiles:
        perfiles = (
            db.query(models.Usuario)
            .filter(
                models.Usuario.username == nombre_englobado,
                models.Usuario.activo == True,
                models.Usuario.nombre_englobado.is_(None),
            )
            .all()
        )

    if not perfiles:
        raise HTTPException(404, "Grupo no encontrado")

    principal = next((p for p in perfiles if (p.sueldo_base or 0) > 0), perfiles[0])

    for p in perfiles:
        p.forma_pago = data.forma_pago or None
        p.cuenta_clabe = data.cuenta_clabe or None
        p.cuenta_interbancaria = data.cuenta_interbancaria or None
        p.sueldo_base = data.sueldo_base if p.id == principal.id else 0

    db.commit()
    return {"ok": True}


@router.put("/usuarios/{usuario_id}/englobado")
def assign_nombre_englobado(
    usuario_id: int,
    data: EnglobadoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    usuario.nombre_englobado = data.nombre_englobado or None
    db.commit()
    return {"ok": True}

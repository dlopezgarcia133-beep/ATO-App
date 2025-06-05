from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido



router = APIRouter()

# CREAR COMISIÓN
@router.post("/comisiones", response_model=schemas.ComisionResponse)
def crear_comision(
    comision: schemas.ComisionCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

    existente = db.query(models.Comision).filter_by(producto=comision.producto).first()
    if existente:
        raise HTTPException(status_code=400, detail="Este producto ya tiene comisión registrada")

    nueva = models.Comision(**comision.dict())
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return nueva


# EDITAR COMISIÓN
@router.put("/comisiones/{producto}", response_model=schemas.ComisionResponse)
def actualizar_comision(
    producto: str,
    comision: schemas.ComisionUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

    com_db = db.query(models.Comision).filter_by(producto=producto).first()
    if not com_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    com_db.cantidad = comision.cantidad
    db.commit()
    db.refresh(com_db)
    return com_db


# ELIMINAR COMISIÓN
@router.delete("/comisiones/{producto}")
def eliminar_comision(
    producto: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):

    com_db = db.query(models.Comision).filter_by(producto=producto).first()
    if not com_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    db.delete(com_db)
    db.commit()
    return {"mensaje": f"Comisión para producto '{producto}' eliminada"}



@router.get("/comisiones", response_model=list[schemas.ComisionCreate])
def obtener_comisiones(db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    
    return db.query(models.Comision).all()

@router.get("/comisiones/{producto}", response_model=schemas.ComisionCreate)
def obtener_comision_producto(producto: str, db: Session = Depends(get_db), user: models.Usuario = Depends(get_current_user)):
    comision = db.query(models.Comision).filter_by(producto=producto).first()
    if not comision:
        raise HTTPException(status_code=404, detail="No se encontró comisión para ese producto")
    return comision

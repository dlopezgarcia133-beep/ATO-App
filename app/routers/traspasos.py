
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido


router = APIRouter()


# Crear traspaso (encargado)
@router.post("/traspasos", response_model=schemas.TraspasoResponse)
def crear_traspaso(
    traspaso: schemas.TraspasoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.encargado))
): 
    if current_user.rol != models.RolEnum.encargado:
        raise HTTPException(status_code=403, detail="Solo encargados pueden solicitar traspasos")

    inventario = db.query(models.InventarioModulo).filter(
        models.InventarioModulo.producto == traspaso.producto,
        models.InventarioModulo.modulo.has(nombre=current_user.modulo.nombre)
    ).first()

    if not inventario or inventario.cantidad < traspaso.cantidad:
        raise HTTPException(status_code=400, detail="Inventario insuficiente")
    
    nuevo = models.Traspaso(
        producto=traspaso.producto,
        cantidad=traspaso.cantidad,
        modulo_origen=current_user.modulo.nombre if current_user.modulo else None,
        modulo_destino=traspaso.modulo_destino,
        solicitado_por=current_user.id
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


# Aprobar o rechazar traspaso (admin)
@router.put("/traspasos/{traspaso_id}", response_model=schemas.TraspasoResponse)
def actualizar_estado_traspaso(
    traspaso_id: int,
    estado: schemas.TraspasoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    traspaso = db.query(models.Traspaso).filter_by(id=traspaso_id).first()
    if not traspaso:
        raise HTTPException(status_code=404, detail="Traspaso no encontrado")

    if traspaso.estado != "pendiente":
        raise HTTPException(status_code=400, detail="Este traspaso ya fue procesado")

    traspaso.estado = estado.estado

    if estado.estado == "aprobado":
        # Buscar módulo origen y destino por nombre
        modulo_origen = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_origen).first()
        modulo_destino = db.query(models.Modulo).filter_by(nombre=traspaso.modulo_destino).first()

        if not modulo_origen or not modulo_destino:
            raise HTTPException(status_code=404, detail="Módulo origen o destino no encontrado")

        origen = db.query(models.InventarioModulo).filter(
    models.InventarioModulo.producto == traspaso.producto,
    models.InventarioModulo.modulo_id == modulo_origen.id
).first()

        if not origen or origen.cantidad < traspaso.cantidad:
            raise HTTPException(status_code=400, detail="Inventario insuficiente en módulo origen")

        origen.cantidad -= traspaso.cantidad

        destino = db.query(models.InventarioModulo).filter_by(
            producto=traspaso.producto,
            modulo=modulo_destino.id
        ).first()

        if destino:
            destino.cantidad += traspaso.cantidad
        else:
            nuevo = models.InventarioModulo(
                producto=traspaso.producto,
                cantidad=traspaso.cantidad,
                modulo=modulo_destino.id
            )
            db.add(nuevo)

        traspaso.aprobado_por = current_user.id

    db.commit()
    db.refresh(traspaso)
    return traspaso


# Ver traspasos del módulo actual (asesor o encargado)
@router.get("/traspasos", response_model=list[schemas.TraspasoResponse])
def obtener_traspasos(db: Session = Depends(get_db), current_user: models.Usuario = Depends(get_current_user)):
    return db.query(models.Traspaso).all()

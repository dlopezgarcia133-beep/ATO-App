
from time import timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido


router = APIRouter()

zona_horaria = ZoneInfo("America/Mexico_City")
# Crear traspaso (encargado)
@router.post("/traspasos", response_model=schemas.TraspasoResponse)
def crear_traspaso(
    traspaso: schemas.TraspasoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.encargado))
):
    inventario = db.query(models.InventarioModulo).filter(
        models.InventarioModulo.producto == traspaso.producto,
        models.InventarioModulo.modulo_id == current_user.modulo.id
    ).first()

    if not inventario or inventario.cantidad < traspaso.cantidad:
        raise HTTPException(status_code=400, detail="Inventario insuficiente")

    nuevo = models.Traspaso(
        producto=inventario.producto,
        clave=inventario.clave,
        precio=inventario.precio,
        tipo_producto=inventario.tipo_producto,
        cantidad=traspaso.cantidad,
        modulo_origen=current_user.modulo.nombre,
        modulo_destino=traspaso.modulo_destino,
        solicitado_por=current_user.id,
        
        fecha=datetime.now(timezone.utc)  # ✅ UTC con hora
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

        # Inventario en módulo origen
        inv_origen = db.query(models.InventarioModulo).filter(
    models.InventarioModulo.producto == traspaso.producto,
    models.InventarioModulo.modulo_id == modulo_origen.id
).first()



        if not inv_origen:
            raise HTTPException(status_code=404, detail="Producto no encontrado en módulo origen")
        if inv_origen.cantidad < traspaso.cantidad:
            raise HTTPException(status_code=400, detail="Inventario insuficiente en módulo origen")

        # Inventario en módulo destino
        inv_destino = db.query(models.InventarioModulo).filter(
            models.InventarioModulo.producto == traspaso.producto,
            models.InventarioModulo.modulo_id == modulo_destino.id
        ).first()

        # Restar en origen
        inv_origen.cantidad -= traspaso.cantidad

        if inv_destino:
            # Sumar en destino
            inv_destino.cantidad += traspaso.cantidad
        else:
            # Crear el producto en destino copiando info del origen
            nuevo = models.InventarioModulo(
                cantidad=traspaso.cantidad,
                clave=inv_origen.clave,
                producto=inv_origen.producto,
                precio=inv_origen.precio,
                modulo_id=modulo_destino.id
            )
            db.add(nuevo)

        traspaso.aprobado_por = current_user.id

    db.commit()
    db.refresh(traspaso)
    return traspaso


# Ver traspasos del módulo actual (asesor o encargado)
@router.get(
    "/traspasos",
    response_model=list[schemas.TraspasoResponse]
)
def listar_traspasos(
    db: Session = Depends(get_db)
):
    return db.query(models.Traspaso)\
        .filter(models.Traspaso.visible_en_pendientes == True)\
        .order_by(models.Traspaso.fecha.desc())\
        .all()






@router.put("/traspasos/{traspaso_id}/ocultar", status_code=204)
def ocultar_traspaso(
    traspaso_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    traspaso = db.query(models.Traspaso).filter(
        models.Traspaso.id == traspaso_id,
        models.Traspaso.visible_en_pendientes == True
    ).first()

    if not traspaso:
        raise HTTPException(status_code=404, detail="Traspaso no encontrado")

    traspaso.visible_en_pendientes = False
    db.commit()

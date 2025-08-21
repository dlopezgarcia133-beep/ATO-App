import datetime
from turtle import pd
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.params import File
from sqlalchemy import func
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido
from sqlalchemy.orm import Session


router = APIRouter()

@router.post("/inventario/general", response_model=schemas.InventarioGeneralResponse)
def crear_producto_inventario_general(
    producto: schemas.InventarioGeneralCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    existente = db.query(models.InventarioGeneral).filter_by(producto=producto.producto).first()
    if existente:
        raise HTTPException(status_code=400, detail="El producto ya existe en el inventario general.")
    
    nuevo = models.InventarioGeneral(**producto.dict())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo



@router.put("/inventario/general/{producto}", response_model=schemas.InventarioGeneralResponse)
def actualizar_producto_inventario_general(
    producto: str,
    datos: schemas.InventarioGeneralUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    producto_db = db.query(models.InventarioGeneral).filter_by(producto=producto).first()
    if not producto_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")
    
    producto_db.cantidad = datos.cantidad
    db.commit()
    db.refresh(producto_db)
    return producto_db



@router.get("/inventario/general/productos-nombres", response_model=List[str])
def obtener_productos_nombres(db: Session = Depends(get_db),
                             current_user: models.Usuario = Depends(get_current_user)):
    productos = db.query(models.InventarioGeneral.producto).distinct().all()
    return [p[0] for p in productos]



@router.get("/inventario/general/{producto}", response_model=schemas.InventarioGeneralResponse)
def produtos_inventario(
    producto: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    producto_normalizado = producto.strip().lower()
    
    producto_db = db.query(models.InventarioGeneral).filter(
        func.lower(func.trim(models.InventarioGeneral.producto)) == producto_normalizado
    ).first()

    if not producto_db:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")

    return producto_db


@router.get("/inventario/general", response_model=list[schemas.InventarioGeneralResponse])
def obtener_inventario_general(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    return db.query(models.InventarioGeneral).all()




@router.post("/inventario/modulo", response_model=schemas.InventarioModuloResponse)
def crear_producto_modulo(
    datos: schemas.InventarioModuloCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([ models.RolEnum.admin]))
):
   
    modulo_obj = db.query(models.Modulo).filter_by(nombre=datos.modulo).first()
    if not modulo_obj:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    existente = db.query(models.InventarioModulo).filter_by(clave=datos.clave, modulo_id=modulo_obj.id).first()

    nuevo = models.InventarioModulo(producto=datos.producto, clave=datos.clave, cantidad=datos.cantidad, precio=datos.precio,  modulo_id=modulo_obj.id)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

@router.put("/inventario/modulo/{producto}", response_model=schemas.InventarioModuloResponse)
def actualizar_inventario_modulo(
    producto: str,
    datos: schemas.InventarioModuloUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    # Buscar producto en inventario del módulo
    item = db.query(models.InventarioModulo).filter_by(producto=producto, modulo_id=datos.modulo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado en el módulo.")

    # Calcular la diferencia de cantidad
    diferencia = datos.cantidad - item.cantidad

    # Si la diferencia es positiva, se está agregando producto => validar en inventario general
    if diferencia > 0:
        producto_general = db.query(models.InventarioGeneral).filter_by(producto=producto).first()
        if not producto_general:
            raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")
        
        if producto_general.cantidad < diferencia:
            raise HTTPException(status_code=400, detail="No hay suficiente producto en el inventario general.")
        
        producto_general.cantidad -= diferencia  # Descontar del general

    # Actualizar cantidad en el módulo
    item.cantidad = datos.cantidad
    db.commit()
    db.refresh(item)
    return item



@router.get("/inventario/modulo", response_model=list[schemas.InventarioModuloResponse])
def obtener_inventario_modulo(
    modulo: Optional[str] = None,
    modulo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # Validar que al menos uno se haya proporcionado
    if not modulo and not modulo_id:
        raise HTTPException(status_code=400, detail="Debes proporcionar el nombre o el ID del módulo")

    # Obtener el objeto del módulo según el parámetro disponible
    if modulo:
        modulo_obj = db.query(models.Modulo).filter_by(nombre=modulo).first()
    else:
        modulo_obj = db.query(models.Modulo).filter_by(id=modulo_id).first()

    if not modulo_obj:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Consultar inventario usando el ID del módulo
    return db.query(models.InventarioModulo).filter(models.InventarioModulo.modulo_id == modulo_obj.id).all()



@router.delete("/inventario/modulo/{id}")
def eliminar_producto_modulo(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    # Buscar el producto en el inventario del módulo
    item_modulo = db.query(models.InventarioModulo).filter_by(id=id).first()
    if not item_modulo:
        raise HTTPException(status_code=404, detail="Producto no encontrado en ese módulo.")

    # Buscar el producto en el inventario general por la clave o nombre del producto
    producto_general = db.query(models.InventarioGeneral).filter_by(clave=item_modulo.clave).first()
    if not producto_general:
        raise HTTPException(status_code=404, detail="Producto no encontrado en el inventario general.")

    # Sumar la cantidad del módulo al inventario general
    producto_general.cantidad += item_modulo.cantidad

    # Eliminar el producto del módulo
    db.delete(item_modulo)
    db.commit()

    return {
        "mensaje": f"Producto '{item_modulo.producto}' eliminado del módulo y cantidad regresada al inventario general."
    }


@router.delete("/inventario/modulo/{producto}")
def eliminar_producto_modulo(
    producto: str,
    modulo: str,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    item = db.query(models.InventarioModulo)\
        .join(models.InventarioModulo.modulo)\
        .filter(models.InventarioModulo.producto == producto)\
        .filter(models.Modulo.nombre == modulo)\
        .first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado en ese módulo.")
    db.delete(item)
    db.commit()
    return {"message": f"Producto '{producto}' eliminado del módulo '{modulo}'."}



@router.post("/mover_a_modulo")
def mover_producto_a_modulo(
    producto_id: int,
    modulo: str,
    cantidad: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(["admin"]))
):
    # Buscar producto en inventario general
    producto_general = db.query(models.InventarioGeneral).filter_by(id=producto_id).first()
    if not producto_general:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general")

    if producto_general.cantidad < cantidad:
        raise HTTPException(status_code=400, detail="Cantidad insuficiente en inventario general")

    # Descontar del inventario general
    producto_general.cantidad -= cantidad

    # Buscar o crear producto en inventario del módulo
    inventario_modulo = db.query(models.InventarioModulo).filter_by(
        producto_id=producto_id, modulo=modulo
    ).first()

    if inventario_modulo:
        inventario_modulo.cantidad += cantidad
    else:
        nuevo = models.InventarioModulo(
            producto_id=producto_id,
            modulo=modulo,
            cantidad=cantidad
        )
        db.add(nuevo)

    db.commit()
    return {"mensaje": f"{cantidad} unidades movidas al módulo {modulo} correctamente"}




@router.post("/inventario/fisico", response_model=schemas.InventarioFisicoResponse)
def registrar_inventario_fisico(
    datos: schemas.InventarioFisicoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    nuevo = models.InventarioFisico(**datos.dict())
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.get("/reportes/diferencias")
def reporte_diferencias(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    inventario_general = db.query(models.InventarioGeneral).all()
    inventario_fisico = db.query(models.InventarioFisico).all()

    # Diccionario con el físico (clave única: producto+clave)
    fisico_dict = {(p.producto, p.clave): p.cantidad for p in inventario_fisico}

    reporte = []
    for prod in inventario_general:
        cantidad_fisica = fisico_dict.get((prod.producto, prod.clave), 0)
        diferencia = cantidad_fisica - prod.cantidad
        reporte.append({
            "producto": prod.producto,
            "clave": prod.clave,
            "sistema": prod.cantidad,
            "fisico": cantidad_fisica,
            "diferencia": diferencia
        })

    return reporte


@router.post("/upload/")
async def upload_inventario(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # Validar que sea un Excel
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser Excel (.xlsx o .xls)")

    # Leer el archivo Excel
    try:
        df = pd.read_excel(file.file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al leer el archivo: {e}")

    # Validar que tenga las columnas necesarias
    columnas_validas = {"producto", "clave", "cantidad"}
    if not columnas_validas.issubset(df.columns):
        raise HTTPException(status_code=400, detail=f"El archivo debe contener las columnas: {columnas_validas}")

    # Guardar en la base de datos
    registros = []
    for _, row in df.iterrows():
        inventario = models.InventarioFisico(
            producto=row["producto"],
            clave=row["clave"],
            cantidad=int(row["cantidad"]),
            fecha=datetime.utcnow()
        )
        registros.append(inventario)

    db.bulk_save_objects(registros)
    db.commit()

    return {"status": "success", "insertados": len(registros)}
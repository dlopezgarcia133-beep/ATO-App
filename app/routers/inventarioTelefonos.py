import pandas as pd
from fastapi import APIRouter, HTTPException, Depends, UploadFile
from fastapi.params import File
from sqlalchemy.orm import Session
from datetime import date
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido


router = APIRouter()

# 🔧 1. Crear en Inventario General de Teléfonos
@router.post("/inventario_telefonos/general", response_model=schemas.InventarioTelefonoGeneralResponse)
def crear_telefono_general(
    datos: schemas.InventarioTelefonoGeneralCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    existente = db.query(models.InventarioTelefonoGeneral).filter_by(
        marca=datos.marca.strip().upper(),
        modelo=datos.modelo.strip().upper()
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="El teléfono ya está en el inventario general.")

    nuevo = models.InventarioTelefonoGeneral(
        marca=datos.marca.strip().upper(),
        modelo=datos.modelo.strip().upper(),
        cantidad=datos.cantidad,
        precio=datos.precio
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

# 🔧 2. Obtener todos los teléfonos del inventario general
@router.get("/inventario_telefonos/general", response_model=list[schemas.InventarioTelefonoGeneralResponse])
def obtener_inventario_telefonos_general(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return db.query(models.InventarioTelefonoGeneral).all()

# 🔧 3. Mover teléfono del inventario general a módulo
@router.post("/inventario_telefonos/mover_a_modulo")
def mover_telefono_a_modulo(
    datos: schemas.MovimientoTelefonoRequest,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    marca = datos.marca.strip().upper()
    modelo = datos.modelo.strip().upper()

    telefono_general = db.query(models.InventarioTelefonoGeneral).filter_by(
        marca=marca,
        modelo=modelo
    ).first()

    if not telefono_general:
        raise HTTPException(status_code=404, detail="Teléfono no encontrado en inventario general")

    if telefono_general.cantidad < datos.cantidad:
        raise HTTPException(status_code=400, detail="Cantidad insuficiente en inventario general")

    telefono_modulo = db.query(models.InventarioTelefono).filter_by(
        marca=marca,
        modelo=modelo,
        modulo_id=datos.modulo_id
    ).first()

    if telefono_modulo:
        telefono_modulo.cantidad += datos.cantidad
    else:
        nuevo = models.InventarioTelefono(
            marca=marca,
            modelo=modelo,
            cantidad=datos.cantidad,
            precio=telefono_general.precio,
            modulo_id=datos.modulo_id
        )
        db.add(nuevo)

    telefono_general.cantidad -= datos.cantidad
    db.commit()
    return {"mensaje": f"{datos.cantidad} unidades movidas al módulo correctamente"}

# 🔧 4. Obtener inventario de teléfonos por módulo
@router.get("/inventario_telefonos/modulo", response_model=list[schemas.InventarioTelefonoGeneralResponse])
def obtener_inventario_telefonos_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return db.query(models.InventarioTelefono).filter_by(modulo_id=modulo_id).all()

# 🔧 5. Eliminar teléfono del inventario general
@router.delete("/inventario_telefonos/general/{telefono_id}")
def eliminar_telefono_general(
    telefono_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    telefono = db.query(models.InventarioTelefonoGeneral).filter_by(id=telefono_id).first()
    if not telefono:
        raise HTTPException(status_code=404, detail="Teléfono no encontrado.")
    db.delete(telefono)
    db.commit()
    return {"mensaje": "Teléfono eliminado del inventario general."}


@router.get("/reportes/diferencias_telefonos")
def reporte_diferencias_telefonos(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    inventario_sistema = db.query(models.InventarioTelefonoGeneral).all()
    inventario_fisico = db.query(models.InventarioTelefonoFisico).all()

    fisico_dict = {(t.marca, t.modelo, t.clave): t.cantidad for t in inventario_fisico}

    reporte = []
    for tel in inventario_sistema:
        cantidad_fisica = fisico_dict.get((tel.marca, tel.modelo, tel.clave), 0)
        diferencia = cantidad_fisica - tel.cantidad
        reporte.append({
            "marca": tel.marca,
            "modelo": tel.modelo,
            "clave": tel.clave,
            "sistema": tel.cantidad,
            "fisico": cantidad_fisica,
            "diferencia": diferencia
        })

    return reporte


@router.post("/inventario/telefonos/fisico/upload")
def subir_inventario_telefonos_fisico(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.admin])
    )
):
    # Validar tipo de archivo
    if not archivo.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser de Excel (.xlsx o .xls)")

    try:
        # Leer Excel con pandas
        df = pd.read_excel(archivo.file)

        # Verificar que tenga las columnas necesarias
        columnas_necesarias = {"marca", "modelo", "clave", "cantidad"}
        if not columnas_necesarias.issubset(df.columns):
            raise HTTPException(
                status_code=400,
                detail=f"El archivo debe contener las columnas: {', '.join(columnas_necesarias)}"
            )

        # Borrar inventario físico anterior (opcional: porque se sube 1 vez al mes)
        db.query(models.InventarioTelefonoFisico).delete()

        # Insertar nuevo inventario físico
        for _, row in df.iterrows():
            item = models.InventarioTelefonoFisico(
                marca=row["marca"],
                modelo=row["modelo"],
                clave=row["clave"],
                cantidad=row["cantidad"]
            )
            db.add(item)

        db.commit()
        return {"mensaje": "Inventario físico de teléfonos actualizado correctamente"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {str(e)}")
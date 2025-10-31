import datetime
import pandas as pd
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, Form
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
    productos = db.query(models.InventarioModulo.producto).distinct().all()
    return [p[0] for p in productos]

@router.get("/buscar", response_model=List[str])
def autocomplete_telefonos(
    query: str = Query(..., min_length=1, description="Texto a buscar"),
    db: Session = Depends(get_db)
):
    """
    Autocomplete para teléfonos.
    Busca en inventario_general solo productos de tipo 'telefono'
    """
    productos = (
    db.query(models.InventarioModulo.producto)
    .filter(
        models.InventarioModulo.tipo_producto == "telefono",
        models.func.upper(models.InventarioModulo.producto).ilike(f"%{query.upper()}%")
    )
    .limit(10)
    .all()
)

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
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    query = db.query(models.InventarioGeneral)
    if tipo:
        query = query.filter(models.InventarioGeneral.tipo == tipo)
    return query.all()





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
    item = db.query(models.InventarioModulo).filter_by(producto=producto, modulo_id=datos.modulo_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Producto no encontrado en el módulo.")

    # Incrementar en vez de reemplazar
    item.cantidad += datos.cantidad  

    # También descontar del inventario general
    producto_general = db.query(models.InventarioGeneral).filter_by(producto=producto).first()
    if not producto_general:
        raise HTTPException(status_code=404, detail="Producto no encontrado en inventario general.")
    
    if producto_general.cantidad < datos.cantidad:
        raise HTTPException(status_code=400, detail="No hay suficiente producto en el inventario general.")

    producto_general.cantidad -= datos.cantidad

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




@router.post("/replicar", response_model=dict)
def agregar_o_actualizar_producto_todos_modulos(
    datos: schemas.InventarioGlobalCreate,
    db: Session = Depends(get_db)
):
    # 1️⃣ Obtener todos los módulos registrados
    modulos = db.query(models.Modulo).all()
    if not modulos:
        raise HTTPException(status_code=404, detail="No hay módulos registrados")

    # 2️⃣ Recorrer cada módulo
    for modulo in modulos:
        producto_existente = (
            db.query(models.InventarioModulo)
            .filter_by(clave=datos.clave, modulo_id=modulo.id)
            .first()
        )

        if producto_existente:
            # 3️⃣ Si ya existe el producto en este módulo, actualizamos datos
            producto_existente.producto = datos.producto
            producto_existente.precio = datos.precio
            producto_existente.tipo_producto = datos.tipo_producto
            # Si quieres también actualizar cantidad, descomenta la siguiente línea:
            # producto_existente.cantidad = datos.cantidad
        else:
            # 4️⃣ Si no existe, creamos un nuevo registro para este módulo
            nuevo_producto = models.InventarioModulo(
                cantidad=datos.cantidad,
                clave=datos.clave,
                producto=datos.producto,
                precio=datos.precio,
                modulo_id=modulo.id,
                tipo_producto=datos.tipo_producto
            )
            db.add(nuevo_producto)

    # 5️⃣ Guardamos todos los cambios
    db.commit()
    return {"message": "Producto agregado o actualizado en todos los módulos"}




@router.put("/actualizar_todos/{producto}", response_model=dict)
def actualizar_producto_en_todos_los_modulos(
    producto: str,
    datos: schemas.InventarioGlobalUpdate,
    db: Session = Depends(get_db)
):
    # Buscar todos los productos con esa producto
    productos = db.query(models.InventarioModulo).filter_by(producto=producto).all()

    if not productos:
        raise HTTPException(status_code=404, detail="No se encontró ningún producto con esa producto")

    # Actualizar los campos especificados
    for producto in productos:
        if datos.producto is not None:
            producto.producto = datos.producto
        if datos.precio is not None:
            producto.precio = datos.precio
        if datos.tipo_producto is not None:
            producto.tipo_producto = datos.tipo_producto

    db.commit()
    return {"message": f"Producto '{producto}' actualizado en todos los módulos"}



@router.delete("/eliminar_todos/{clave}", response_model=dict)
def eliminar_producto_en_todos_los_modulos(
    clave: str,
    db: Session = Depends(get_db)
):
    # Buscar todos los registros con la clave dada
    productos = db.query(models.InventarioModulo).filter_by(clave=clave).all()

    if not productos:
        raise HTTPException(status_code=404, detail="No se encontró ningún producto con esa clave")

    # Eliminar todos los productos encontrados
    for producto in productos:
        db.delete(producto)

    db.commit()
    return {"message": f"Producto '{clave}' eliminado de todos los módulos"}



@router.post("/actualizar_inventario_excel", response_model=dict)
def actualizar_inventario_desde_excel(
    modulo_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    # 1️⃣ Leer el archivo Excel
    try:
        df = pd.read_excel(archivo.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer el archivo Excel: {e}")

    # 2️⃣ Normalizar nombres de columnas
    df.columns = [c.strip().upper() for c in df.columns]

    # 3️⃣ Validar que tenga las columnas correctas
    columnas_requeridas = {"CANTIDAD", "CLAVE", "DESCRIPCION", "PRECIO"}
    if not columnas_requeridas.issubset(df.columns):
        raise HTTPException(
            status_code=400,
            detail=f"El archivo debe contener las columnas: {', '.join(columnas_requeridas)}"
        )

    # 4️⃣ Contadores
    actualizados = 0
    agregados = 0

    # 5️⃣ Recorrer filas del Excel
    for _, fila in df.iterrows():
        clave = str(fila["CLAVE"]).strip()
        producto = str(fila["DESCRIPCION"]).strip()
        cantidad = int(fila["CANTIDAD"])

        # Limpiar el precio (eliminar "$" y comas)
        precio_str = str(fila["PRECIO"]).replace("$", "").replace(",", "").strip()
        try:
            precio = int(float(precio_str))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Precio inválido en la clave {clave}: {fila['PRECIO']}")

        # Detectar tipo de producto automáticamente
        tipo_producto = (
            "telefono"
            if producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
            else "accesorios"
        )

        # Buscar si ya existe en el módulo
        producto_db = (
            db.query(models.InventarioModulo)
            .filter_by(clave=clave, modulo_id=modulo_id)
            .first()
        )

        if producto_db:
            # 🔁 Actualizar valores existentes
            producto_db.producto = producto
            producto_db.cantidad = cantidad
            producto_db.precio = precio
            producto_db.tipo_producto = tipo_producto
            actualizados += 1
        else:
            # ➕ Crear nuevo producto
            nuevo = models.InventarioModulo(
                cantidad=cantidad,
                clave=clave,
                producto=producto,
                precio=precio,
                modulo_id=modulo_id,
                tipo_producto=tipo_producto
            )
            db.add(nuevo)
            agregados += 1

    # 6️⃣ Guardar cambios
    db.commit()

    return {
        "message": (
            f"Inventario del módulo {modulo_id} actualizado correctamente. "
            f"{actualizados} productos actualizados y {agregados} nuevos agregados."
        )
    }




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



# Crear teléfono en inventario_general
@router.post("/inventario/telefonos", response_model=schemas.InventarioGeneralResponse)
def crear_telefono(
    datos: schemas.InventarioTelefonoGeneralCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    # Generar clave automática o esperar que venga de otro proceso
    clave_generada = f"{datos.marca[:3].upper()}-{datos.modelo[:3].upper()}"

    existente = db.query(models.InventarioGeneral).filter_by(clave=clave_generada).first()
    if existente:
        raise HTTPException(status_code=400, detail="El teléfono ya está registrado en inventario.")

    nuevo = models.InventarioGeneral(
        clave=clave_generada,
        producto=f"{datos.marca.upper()} {datos.modelo.upper()}",
        cantidad=datos.cantidad,
        precio=int(datos.precio),
        tipo="telefono"
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


# Obtener todos los teléfonos
@router.get("/inventario/telefonos", response_model=list[schemas.InventarioGeneralResponse])
def obtener_telefonos(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    return db.query(models.InventarioGeneral).filter_by(tipo="telefono").all()

@router.post("/inventario/fisico/upload")
def subir_inventario_fisico(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido([models.RolEnum.admin]))
):
    if not archivo.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="El archivo debe ser de Excel (.xlsx o .xls)")

    try:
        df = pd.read_excel(archivo.file)

        # Validar columnas esperadas
        columnas_necesarias = {"clave", "cantidad"}
        if not columnas_necesarias.issubset(df.columns):
            raise HTTPException(
                status_code=400,
                detail=f"El archivo debe contener las columnas: {', '.join(columnas_necesarias)}"
            )

        # Borrar registros previos del inventario físico (opcional, si solo hay un corte por mes)
        db.query(models.InventarioFisico).delete()

        # Insertar nuevos registros
        registros = []
        for _, row in df.iterrows():
            inventario = models.InventarioFisico(
                clave=row["clave"],
                producto=row.get("producto", ""),  # opcional si el excel trae nombre
                cantidad=int(row["cantidad"]),
                fecha=datetime.utcnow()
            )
            registros.append(inventario)

        db.bulk_save_objects(registros)
        db.commit()

        # Comparar contra inventario general
        inventario_sistema = db.query(models.InventarioGeneral).all()
        fisico_dict = {row["clave"]: row["cantidad"] for _, row in df.iterrows()}

        reporte = []
        for prod in inventario_sistema:
            cantidad_fisica = fisico_dict.get(prod.clave, 0)
            diferencia = cantidad_fisica - prod.cantidad
            reporte.append({
                "producto": prod.producto,
                "clave": prod.clave,
                "tipo": prod.tipo,  
                "sistema": prod.cantidad,
                "fisico": cantidad_fisica,
                "diferencia": diferencia
            })

        return reporte

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {str(e)}")


# Eliminar teléfono
@router.delete("/inventario/telefonos/{telefono_id}")
def eliminar_telefono(
    telefono_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
):
    telefono = db.query(models.InventarioGeneral).filter_by(id=telefono_id, tipo="telefono").first()
    if not telefono:
        raise HTTPException(status_code=404, detail="Teléfono no encontrado.")

    db.delete(telefono)
    db.commit()
    return {"mensaje": "Teléfono eliminado del inventario."}

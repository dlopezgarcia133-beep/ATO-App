import datetime
import pandas as pd
import os
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, Form
from fastapi.params import File
from sqlalchemy import func
from app import models, schemas
from app.config import get_current_user
from app.database import get_db
from app.utilidades import verificar_rol_requerido
from sqlalchemy.orm import Session
from app.models import InventarioModulo
from datetime import datetime
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from io import BytesIO



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




@router.get("/inventario/buscar-autocomplete")
def buscar_productos_autocomplete(
    modulo_id: int,
    q: str,
    db: Session = Depends(get_db)
):
    productos = (
        db.query(
            InventarioModulo.id,
            InventarioModulo.producto,
            InventarioModulo.clave
        )
        .filter(
            InventarioModulo.modulo_id == modulo_id,
            (
                InventarioModulo.clave.ilike(f"%{q}%") |
                InventarioModulo.producto.ilike(f"%{q}%")
            )
        )
        .order_by(InventarioModulo.producto.asc())
        .limit(20)
        .all()
    )

    return [
        {
            "id": p.id,
            "producto": p.producto,
            "clave": p.clave
        }
        for p in productos
    ]



@router.get("/inventario/descargar/{modulo_id}")
def descargar_inventario_modulo(
    modulo_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    # 🔒 SOLO ADMIN
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")

    productos = (
        db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .all()
    )

    if not productos:
        raise HTTPException(status_code=404, detail="Inventario vacío")



    data = [
        {
            "Clave": p.clave,
            "Producto": p.producto,
            "Cantidad": p.cantidad,
            "Precio": p.precio
        }
        for p in productos
    ]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=inventario_modulo_{modulo_id}.xlsx"
        }
    )



@router.get(
    "/inventario/general/productos-nombres",
    response_model=List[str]
)
def obtener_productos_nombres(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user)
):
    productos = (
        db.query(
            models.InventarioModulo.producto,
            func.min(models.InventarioModulo.precio).label("precio_min")
        )
        .group_by(models.InventarioModulo.producto)
        .order_by(func.min(models.InventarioModulo.precio).asc())
        .all()
    )

    return [p.producto for p in productos]

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



@router.post("/inventario/entrada_mercancia")
def entrada_mercancia(
    data: schemas.EntradaMercanciaRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    for item in data.productos:
        registro = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.id == item.producto_id,
                models.InventarioModulo.modulo_id == data.modulo_id
            )
            .first()
        )

        if not registro:
            continue

        registro.cantidad += item.cantidad  # 🔥 SUMA

    db.commit()

    return {"ok": True, "message": "Mercancía agregada correctamente"}



@router.post("/inventario/modulo", response_model=schemas.InventarioModuloResponse)
def crear_producto_modulo(
    datos: schemas.InventarioModuloCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(
        verificar_rol_requerido([models.RolEnum.admin])
    )
):
    # Buscar módulo por ID en lugar de nombre
    modulo_obj = db.query(models.Modulo).filter_by(id=datos.modulo_id).first()
    if not modulo_obj:
        raise HTTPException(status_code=404, detail="Módulo no encontrado")

    # Verificar si ya existe el producto en el módulo
    existente = db.query(models.InventarioModulo).filter_by(
        clave=datos.clave, modulo_id=modulo_obj.id
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail="El producto ya existe en el módulo")

    # Crear nuevo producto
    nuevo = models.InventarioModulo(
        producto=datos.producto,
        clave=datos.clave,
        cantidad=datos.cantidad,
        precio=datos.precio,
        modulo_id=modulo_obj.id,
        tipo_producto=datos.tipo_producto
    )

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




@router.get("/inventario/buscar")
def buscar_producto(
    modulo_id: int = Query(...),
    clave: str = Query(...),
    db: Session = Depends(get_db)
):
    producto = (
        db.query(models.InventarioModulo)
        .filter(models.InventarioModulo.modulo_id == modulo_id)
        .filter(models.InventarioModulo.clave.ilike(f"%{clave}%"))
        .first()
    )

    if not producto:
        return {"ok": False, "msg": "Producto no encontrado"}

    return {
        "ok": True,
        "producto": {
            "id": producto.id,              # ✅ OBLIGATORIO
            "producto": producto.producto,
            "clave": producto.clave,
            "cantidad_actual": producto.cantidad
        }
    }




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




@router.post("/preview_excel")
def preview_inventario_excel(
    modulo_id: int = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    df = pd.read_excel(archivo.file)

    # Normalizar columnas
    df.columns = [
        str(c).strip().upper()
        .replace("Á", "A").replace("É", "E")
        .replace("Í", "I").replace("Ó", "O")
        .replace("Ú", "U")
        for c in df.columns
    ]

    equivalencias = {
        "CANTIDAD": ["CANTIDAD", "QTY", "CANT", "CANTIDAD DISPONIBLE"],
        "CLAVE": ["CLAVE", "CODIGO", "CÓDIGO", "CODE"],
        "DESCRIPCION": ["DESCRIPCION", "PRODUCTO", "NOMBRE", "DESC"],
        "PRECIO": ["PRECIO", "PRECIO UNITARIO", "PRICE", "COSTO"],
    }

    columnas = {}
    for requerido, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas[requerido] = col
                break

    faltantes = [c for c in equivalencias if c not in columnas]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan columnas requeridas: {', '.join(faltantes)}"
        )

    filas_validas = []
    filas_error = []
    claves_en_excel = set()

    # 🔁 ESTE for ES CLAVE
    for index, fila in df.iterrows():
        errores = []

        clave = str(fila[columnas["CLAVE"]]).strip()
        producto = str(fila[columnas["DESCRIPCION"]]).strip()

        if not clave:
            errores.append("Clave vacía")

        if clave in claves_en_excel:
            errores.append("Clave duplicada en el archivo")
        claves_en_excel.add(clave)

        # 1️⃣ Detectar tipo PRIMERO
        tipo_producto = (
            "telefono"
            if producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
            else "accesorios"
        )

        # 2️⃣ Cantidad
        try:
            cantidad = int(fila[columnas["CANTIDAD"]])
            if cantidad < 0:
                errores.append("Cantidad negativa")
        except:
            errores.append("Cantidad inválida")

        # 3️⃣ Precio
        precio = 0
        precio_raw = str(fila[columnas["PRECIO"]]).replace("$", "").replace(",", "").strip()
        try:
            precio = int(float(precio_raw))
        except:
            if tipo_producto == "accesorios":
                errores.append("Precio inválido")

        # 4️⃣ Validación por tipo
        if tipo_producto == "accesorios" and precio <= 0:
            errores.append("Precio inválido para accesorio")

        existe = (
            db.query(models.InventarioModulo)
            .filter_by(clave=clave, modulo_id=modulo_id)
            .first()
        )

        if errores:
            filas_error.append({
                "fila": index + 2,
                "clave": clave,
                "errores": errores
            })
        else:
            filas_validas.append({
                "clave": clave,
                "producto": producto,
                "cantidad": cantidad,
                "precio": precio,
                "tipo_producto": tipo_producto,
                "accion": "actualizar" if existe else "agregar"
            })

    return {
        "validas": filas_validas,
        "errores": filas_error
    }



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

    # 2️⃣ Normalizar nombres de columnas (sin eliminar letras)
    df.columns = [str(c).strip().upper().replace("Á", "A").replace("É", "E")
                  .replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
                  for c in df.columns]

    # 3️⃣ Definir equivalencias de nombres posibles (muy flexible)
    equivalencias = {
        "CANTIDAD": ["CANTIDAD", "QTY", "CANT", "CANTIDAD DISPONIBLE"],
        "CLAVE": ["CLAVE", "CODIGO", "CÓDIGO", "CODE"],
        "DESCRIPCION": ["DESCRIPCION", "PRODUCTO", "NOMBRE", "DESC"],
        "PRECIO": ["PRECIO", "PRECIO UNITARIO", "PRICE", "COSTO"],
    }

    # 4️⃣ Buscar columnas requeridas sin importar el orden
    columnas_mapeadas = {}
    for requerido, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas_mapeadas[requerido] = col
                break

    # 5️⃣ Validar que estén todas las columnas requeridas
    faltantes = [r for r in equivalencias.keys() if r not in columnas_mapeadas]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"El archivo debe tener las columnas: {', '.join(equivalencias.keys())}. Faltan: {', '.join(faltantes)}"
        )

    # 6️⃣ Contadores
    actualizados = 0
    agregados = 0

    # 7️⃣ Procesar cada fila
    for _, fila in df.iterrows():
        clave = str(fila[columnas_mapeadas["CLAVE"]]).strip()
        producto = str(fila[columnas_mapeadas["DESCRIPCION"]]).strip()

        # Convertir cantidad
        try:
            cantidad = int(fila[columnas_mapeadas["CANTIDAD"]])
        except:
            raise HTTPException(status_code=400, detail=f"Cantidad inválida en {clave}")

        # Limpiar y convertir precio
        precio_str = str(fila[columnas_mapeadas["PRECIO"]]).replace("$", "").replace(",", "").strip()
        try:
            precio = int(float(precio_str))
        except:
            raise HTTPException(status_code=400, detail=f"Precio inválido en la clave {clave}: {precio_str}")

        # Detectar tipo de producto
        tipo_producto = (
            "telefono"
            if producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
            else "accesorios"
        )

# ✅ Validación coherente con preview
        if tipo_producto == "accesorios" and precio <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Precio inválido para accesorio en la clave {clave}"
            )


        # Buscar producto existente
        producto_db = (
            db.query(models.InventarioModulo)
            .filter_by(clave=clave, modulo_id=modulo_id)
            .first()
        )

        if producto_db:
            producto_db.producto = producto
            producto_db.cantidad = cantidad
            producto_db.precio = precio
            producto_db.tipo_producto = tipo_producto
            actualizados += 1
        else:
            nuevo = models.InventarioModulo(
                cantidad=cantidad,
                clave=clave,
                producto=producto,
                precio=precio,
                modulo_id=modulo_id,
                tipo_producto=tipo_producto,
            )
            db.add(nuevo)
            agregados += 1

    db.commit()

    return {
        "message": (
            f"Inventario del módulo {modulo_id} actualizado correctamente. "
            f"{actualizados} productos actualizados y {agregados} nuevos agregados."
        )
    }



@router.post("/preview_excel_general")
def preview_inventario_excel_general(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    try:
        df = pd.read_excel(archivo.file)
    except Exception as e:
        raise HTTPException(400, f"Error al leer Excel: {e}")

    # Normalizar columnas
    df.columns = [
        str(c).strip().upper()
        .replace("Á","A").replace("É","E")
        .replace("Í","I").replace("Ó","O")
        .replace("Ú","U")
        for c in df.columns
    ]

    equivalencias = {
        "CLAVE": ["CLAVE","CODIGO","CÓDIGO","CODE"],
        "DESCRIPCION": ["DESCRIPCION","PRODUCTO","NOMBRE","DESC"],
        "CANTIDAD": ["CANTIDAD","QTY","CANT"],
        "PRECIO": ["PRECIO","PRICE","COSTO"],
    }

    columnas = {}
    for req, posibles in equivalencias.items():
        for col in df.columns:
            if any(p in col for p in posibles):
                columnas[req] = col
                break

    faltantes = [k for k in equivalencias if k not in columnas]
    if faltantes:
        raise HTTPException(400, f"Faltan columnas: {', '.join(faltantes)}")

    validos = []
    errores = []
    claves_vistas = set()

    for i, fila in df.iterrows():
        errs = []

        clave = str(fila[columnas["CLAVE"]]).strip()
        producto = str(fila[columnas["DESCRIPCION"]]).strip()

        if not clave:
            errs.append("Clave vacía")

        if clave in claves_vistas:
            errs.append("Clave duplicada en Excel")
        claves_vistas.add(clave)

        tipo_producto = "telefono" if (
            producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
        ) else "accesorios"

        try:
            cantidad = int(fila[columnas["CANTIDAD"]])
            if cantidad < 0:
                errs.append("Cantidad negativa")
        except:
            errs.append("Cantidad inválida")

        precio_raw = str(fila[columnas["PRECIO"]]).replace("$","").replace(",","").strip()
        try:
            precio = int(float(precio_raw))
        except:
            precio = 0

        if tipo_producto == "accesorios" and precio <= 0:
            errs.append("Precio inválido para accesorio")

        existe = (
            db.query(models.InventarioGeneral)
            .filter_by(clave=clave)
            .first()
        )

        if errs:
            errores.append({
                "fila": i + 2,
                "clave": clave,
                "errores": errs
            })
        else:
            validos.append({
                "clave": clave,
                "producto": producto,
                "cantidad": cantidad,
                "precio": precio,
                "tipo_producto": tipo_producto,
                "accion": "actualizar" if existe else "agregar"
            })

    return {"validas": validos, "errores": errores}



@router.post("/actualizar_inventario_excel_general")
def actualizar_inventario_excel_general(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    import pandas as pd

    df = pd.read_excel(archivo.file)

    df.columns = [
        str(c).strip().upper()
        .replace("Á","A").replace("É","E")
        .replace("Í","I").replace("Ó","O")
        .replace("Ú","U")
        for c in df.columns
    ]

    claves_excel = set()  # 🔥 CLAVES QUE VIENEN EN EL EXCEL
    actualizados = 0
    agregados = 0
    eliminados = 0

    for _, fila in df.iterrows():
        clave = str(fila["CLAVE"]).strip()
        producto = str(fila["DESCRIPCION"]).strip()
        cantidad = int(fila["CANTIDAD"])
        precio = int(float(str(fila["PRECIO"]).replace("$","").replace(",","")))

        claves_excel.add(clave)

        tipo_producto = "telefono" if (
            producto.upper().startswith("TEL") or clave.upper().startswith("TEL")
        ) else "accesorios"

        existente = (
            db.query(models.InventarioGeneral)
            .filter_by(clave=clave)
            .first()
        )

        if existente:
            existente.producto = producto
            existente.cantidad = cantidad
            existente.precio = precio
            existente.tipo_producto = tipo_producto
            actualizados += 1
        else:
            db.add(models.InventarioGeneral(
                clave=clave,
                producto=producto,
                cantidad=cantidad,
                precio=precio,
                tipo_producto=tipo_producto
            ))
            agregados += 1

    # 🔥 ELIMINAR PRODUCTOS QUE NO VIENEN EN EL EXCEL
    productos_bd = db.query(models.InventarioGeneral).all()

    for prod in productos_bd:
        if prod.clave not in claves_excel:
            db.delete(prod)
            eliminados += 1

    db.commit()

    return {
        "message": (
            f"{actualizados} actualizados, "
            f"{agregados} agregados, "
            f"{eliminados} eliminados"
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





@router.post("/guardar_conteo")
def guardar_conteo(
    data: schemas.ConteoInventarioRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # 🔐 Solo admins
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="No autorizado")

    if not data.productos:
        raise HTTPException(status_code=400, detail="No hay productos para guardar")

    for item in data.productos:
        registro = (
            db.query(models.InventarioModulo)
            .filter(
                models.InventarioModulo.id == item.producto_id,
                models.InventarioModulo.modulo_id == data.modulo_id
            )
            .first()
        )

        if not registro:
            continue  # si no existe, lo ignoramos

        # ✅ Aquí se guarda el conteo físico REAL
        registro.cantidad = item.cantidad

    db.commit()

    return {
        "ok": True,
        "message": "Inventario actualizado correctamente con conteo físico"
    }



# # Crear teléfono en inventario_general
# @router.post("/inventario/telefonos", response_model=schemas.InventarioGeneralResponse)
# def crear_telefono(
#     datos: schemas.InventarioTelefonoGeneralCreate,
#     db: Session = Depends(get_db),
#     current_user: models.Usuario = Depends(verificar_rol_requerido(models.RolEnum.admin))
# ):
#     # Generar clave automática o esperar que venga de otro proceso
#     clave_generada = f"{datos.marca[:3].upper()}-{datos.modelo[:3].upper()}"

#     existente = db.query(models.InventarioGeneral).filter_by(clave=clave_generada).first()
#     if existente:
#         raise HTTPException(status_code=400, detail="El teléfono ya está registrado en inventario.")

#     nuevo = models.InventarioGeneral(
#         clave=clave_generada,
#         producto=f"{datos.marca.upper()} {datos.modelo.upper()}",
#         cantidad=datos.cantidad,
#         precio=int(datos.precio),
#         tipo="telefono"
#     )
#     db.add(nuevo)
#     db.commit()
#     db.refresh(nuevo)
#     return nuevo


# # Obtener todos los teléfonos
# @router.get("/inventario/telefonos", response_model=list[schemas.InventarioGeneralResponse])
# def obtener_telefonos(
#     db: Session = Depends(get_db),
#     current_user: models.Usuario = Depends(get_current_user)
# ):
#     return db.query(models.InventarioGeneral).filter_by(tipo="telefono").all()

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





@router.get("/inventario/congelar/{modulo_id}")
def congelar_inventario(modulo_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    """
    Genera un Excel con las cantidades actuales y luego pone a 0 las cantidades
    del módulo. Solo accesible para admins.
    """

    # --- 1) Validar permiso de admin ---
    # Ajusta la comprobación según tu modelo de usuario real.
    is_admin = False
    if hasattr(current_user, "is_admin"):
        is_admin = bool(getattr(current_user, "is_admin"))
    elif hasattr(current_user, "role"):
        is_admin = getattr(current_user, "role") in ("admin", "superadmin", "owner")
    # Si tu user tiene otro campo, reemplaza la lógica anterior.
    if not is_admin:
        raise HTTPException(status_code=403, detail="Solo administradores pueden congelar el inventario")

    # --- 2) Leer inventario del módulo ---
    inventario = (
        db.query(InventarioModulo)
        .filter(InventarioModulo.modulo_id == modulo_id)
        .all()
    )

    if not inventario:
        raise HTTPException(status_code=404, detail="No hay inventario para ese módulo")

    # --- 3) Preparar datos para Excel (tomar cantidades actuales) ---
    rows = []
    for item in inventario:
        rows.append({
            "inventario_id": item.id,
            "producto": getattr(item, "producto", ""),
            "clave": getattr(item, "clave", ""),
            "cantidad_anterior": item.cantidad
        })

    # --- 4) Generar Excel EN MEMORIA (bytes buffer) ---
    try:
        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="inventario_previo", index=False)
        output.seek(0)
    except Exception as e:
        # Si la generación del archivo falla, no tocamos la BD
        raise HTTPException(status_code=500, detail=f"Error generando Excel: {e}")

    # --- 5) Poner cantidades a 0 en la BD (dentro de try/except para rollback) ---
    try:
        for item in inventario:
            item.cantidad = 0
            db.add(item)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al setear cantidades a 0: {e}")

    # --- 6) Devolver el Excel como streaming response (descarga en cliente) ---
    filename = f"inventario_modulo_{modulo_id}_congelado_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router.get("/inventario/buscar")
def buscar_producto(modulo_id: int, clave: str, db: Session = Depends(get_db)):

    producto = (
        db.query(InventarioModulo)
        .filter(InventarioModulo.modulo_id == modulo_id)
        .filter(InventarioModulo.clave.ilike(f"%{clave}%"))
        .first()
    )

    if not producto:
        return {"ok": False, "msg": "Producto no encontrado"}

    return {
        "ok": True,
        "producto": {
            "producto": producto.producto,   # <-- CAMBIO AQUÍ
            "clave": producto.clave,
            "cantidad_actual": producto.cantidad
        }
    }

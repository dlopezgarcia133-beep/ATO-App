from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel
from datetime import date, datetime, time
from app.models import EstadoTraspasoEnum, RolEnum


class AsistenciaBase(BaseModel):
    nombre: str
    modulo: str
    turno: str

class AsistenciaCreate(AsistenciaBase):
    pass

class Asistencia(AsistenciaBase):
    id: int
    fecha: date
    hora: time
    hora_salida: time | None

    class Config:
        from_attributes = True
        

class RolEnum(str, Enum):
    admin = "admin"
    encargado = "encargado"
    asesor = "asesor"

# 👉 Este es el que se usa para crear un usuario
class UsuarioCreate(BaseModel):
    username: str
    rol: RolEnum
    password: str
    modulo_id: Optional[int] = None  # Cambiado de modulo:str a modulo_id:int
    is_admin: Optional[bool] = False

# 👉 Este es para actualizar un usuario
class UsuarioUpdate(BaseModel):
    username: Optional[str] = None
    rol: Optional[str] = None
    modulo_id: Optional[int] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = None 

# 👉 Este para devolver la respuesta
class ModuloOut(BaseModel):
    id: int
    nombre: str

    class Config:
       from_attributes = True

class UsuarioResponse(BaseModel):
    id: int
    username: str
    rol: RolEnum
    is_admin: bool
    modulo: Optional[ModuloOut] = None  

    class Config:
        from_attributes = True


class VentaCreate(BaseModel):
    producto: str
    precio_unitario: float
    cantidad: int
    correo_cliente: Optional[str] = None
     

class VentaResponse(VentaCreate):
    id: int
    empleado: Optional[UsuarioResponse] = None
    modulo: Optional[ModuloOut]
    producto: str
    cantidad: int
    precio_unitario: float
    total: Optional[float] = None
    comision: Optional[float] = None
    fecha: date
    hora: time

    class Config:
        
        from_attributes = True
        

class VentaCancelada(BaseModel):
    id: int
    cancelada: bool
    fecha_cancelacion: datetime

    class Config:
        from_attributes = True
        
        

class ProductoEnVenta(BaseModel):
    producto: str
    cantidad: int
    precio_unitario: float

class VentaMultipleCreate(BaseModel):
    productos: List[ProductoEnVenta]
    correo_cliente: Optional[str] = None
    metodo_pago: str

class VentaChipCreate(BaseModel):
    tipo_chip: str
    numero_telefono: str
    monto_recarga: float
  

class VentaChipResponse(VentaChipCreate):
    id: int
    empleado_id: Optional[int] = None
    empleado: Optional[UsuarioResponse] = None
    comision: Optional[float] = None
    fecha: date
    hora: time
    cancelada: bool
    validado: bool
    descripcion_rechazo: Optional[str] = None

    class Config:
        from_attributes = True




class ComisionCreate(BaseModel):
    producto: str
    cantidad: float

class ComisionUpdate(BaseModel):
    cantidad: float

class ComisionResponse(ComisionCreate):
    id: int

    class Config:
        from_attributes = True




        

class ModuloSelect(BaseModel):
    modulo: str
    
class ModuloResponse(BaseModel):
    id: int
    nombre: str

    class Config:
        from_attributes = True




class TraspasoBase(BaseModel):
    producto: str
    cantidad: int
    modulo_destino: str

class TraspasoCreate(TraspasoBase):
    pass

class TraspasoUpdate(BaseModel):
    estado: Literal["aprobado", "rechazado"]

class TraspasoResponse(TraspasoBase):
    id: int
    modulo_origen: str
    estado: str
    fecha: datetime
    solicitado_por: int
    aprobado_por: Optional[int] = None

    class Config:
        from_attributes = True




class InventarioGeneralCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int


class InventarioGeneralUpdate(BaseModel):
    cantidad: int


class InventarioGeneralResponse(BaseModel):
    id: int
    producto: str
    clave: str
    cantidad: int
    precio: int

    class Config:
        from_attributes = True




class InventarioModuloCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int
    modulo: str


class InventarioModuloUpdate(BaseModel):
    cantidad: Optional[int] = None 
    precio: Optional[int] = None
    modulo_id: Optional[int] = None

class InventarioModuloResponse(BaseModel):
    id: int
    producto: str
    clave : str
    cantidad: int
    precio: int
    modulo: ModuloOut

    class Config:
        from_attributes = True


class MovimientoInventarioModulo(BaseModel):
    producto_id: int
    modulo: str
    cantidad: int


class VentaTelefonoCreate(BaseModel):
    marca: str
    modelo: str
    tipo: str
    precio_venta: float
    metodo_pago: str

class VentaTelefonoResponse(BaseModel):
    id: int
    empleado_id: int
    fecha: date
    tipo: str
    hora: time
    cancelada: bool
    empleado: Optional[UsuarioResponse] = None

    class Config:
        from_attributes = True


class InventarioTelefonoGeneralCreate(BaseModel):
    marca: str
    modelo: str
    cantidad: int
    precio: float


class InventarioTelefonoGeneralResponse(BaseModel):
    id: int
    marca: str
    modelo: str
    cantidad: int
    precio: float
    modulo_id: int

    class Config:
        from_attributes = True

class MovimientoTelefonoRequest(BaseModel):
    marca: str
    modelo: str
    cantidad: int
    modulo_id: int


class VentaAccesorioConComision(BaseModel):
    producto: str
    cantidad: int
    comision: float
    fecha: date
    hora: time

class VentaTelefonoConComision(BaseModel):
    marca: str
    modelo: str
    tipo: str
    comision: float
    fecha: date
    hora: time
    

class VentaChipConComision(BaseModel):
    tipo_chip: str
    comision: float
    fecha: str
    hora: str


class ComisionesCicloResponse(BaseModel):
    inicio_ciclo: date
    fin_ciclo: date
    fecha_pago: date
    total_chips: float
    total_accesorios: float
    total_telefonos: float
    total_general: float
    ventas_accesorios: List[VentaAccesorioConComision]
    ventas_telefonos: List[VentaTelefonoConComision]
    ventas_chips: List[VentaChipConComision]

class CorteDiaCreate(BaseModel):
    fecha: date
    total_efectivo: float
    total_tarjeta: float
    adicional_recargas: float
    adicional_transporte: float
    adicional_otros: float
    total_sistema: float
    total_general: float
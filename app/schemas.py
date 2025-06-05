from typing import Literal, Optional
from pydantic import BaseModel
from datetime import date, datetime, time
from app.models import EstadoTraspasoEnum


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
        orm_mode = True


class VentaCreate(BaseModel):
    producto: str
    cantidad: int
    precio_unitario: float
    cliente_email: Optional[str] = None
     

class VentaResponse(VentaCreate):
    id: int
    empleado_id: int
    modulo: str
    producto: str
    cantidad: int
    precio_unitario: float
    total: Optional[float] = None
    comision: Optional[float] = None
    fecha: date
    hora: time

    class Config:
        orm_mode = True
        from_attributes = True



class ComisionCreate(BaseModel):
    producto: str
    cantidad: float

class ComisionUpdate(BaseModel):
    cantidad: float

class ComisionResponse(ComisionCreate):
    id: int

    class Config:
        orm_mode = True



class UsuarioCreate(BaseModel):
    username: str
    rol: str
    password: str
    modulo: str
    is_admin: Optional[bool] = False

class UsuarioResponse(BaseModel):
    id: int
    username: str
    rol: str
    modulo: str
    is_admin: bool

    class Config:
        orm_mode = True
        

class ModuloSelect(BaseModel):
    modulo: str



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
        orm_mode = True




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
    cantidad: int

    class Config:
        orm_mode = True




class InventarioModuloCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int


class InventarioModuloUpdate(BaseModel):
    cantidad: int


class InventarioModuloResponse(BaseModel):
    id: int
    producto: str
    cantidad: int
    modulo: str

    class Config:
        orm_mode = True

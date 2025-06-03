from typing import Optional
from pydantic import BaseModel
from datetime import date, time


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
    ident: str
    password: str
    modulo: str
    is_admin: Optional[bool] = False

class UsuarioResponse(BaseModel):
    id: int
    username: str
    ident: str
    modulo: str
    is_admin: bool

    class Config:
        orm_mode = True
        

class ModuloSelect(BaseModel):
    modulo: str

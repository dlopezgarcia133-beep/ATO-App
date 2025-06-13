import enum
from sqlalchemy import Boolean, Column, Date, Float, Integer, String, Enum, DateTime, Time, UniqueConstraint, func
import sqlalchemy
from .database import Base
from datetime import datetime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship


class RolEnum(str, enum.Enum):
    admin = "admin"
    encargado = "encargado"
    asesor = "asesor"

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    rol = Column(Enum(RolEnum), nullable=False, default=RolEnum.asesor)  
    password = Column(String, nullable=False)
    modulo = Column(String, nullable=True)  
    is_admin = Column(Boolean, default=False)

    ventas = relationship("Venta", back_populates="empleado")

class Asistencia(Base):
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    modulo = Column(String, nullable=False)
    turno = Column(String, nullable=False)
    fecha = Column(Date, default=func.current_date())
    hora = Column(Time, default=func.current_time())
    hora_salida = Column(Time, nullable=True)


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    modulo = Column(String, nullable=False)
    producto = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    comision = Column(Float, nullable=True)  
    fecha = Column(Date, default=func.current_date())
    hora = Column(Time, default=func.current_time())
    correo_cliente = Column(String, nullable=True)
    
    empleado = relationship("Usuario", back_populates="ventas")


class Comision(Base):
    __tablename__ = "comisions"

    id = Column(Integer, primary_key=True, index=True)
    producto = Column(String, unique=True, nullable=False)
    cantidad = Column(Float, nullable=False)  




class EstadoTraspasoEnum(str, enum.Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"

class Traspaso(Base):
    __tablename__ = "traspasos"

    id = Column(Integer, primary_key=True, index=True)
    producto = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    modulo_origen = Column(String, nullable=False)
    modulo_destino = Column(String, nullable=False)
    estado = Column(Enum(EstadoTraspasoEnum), default=EstadoTraspasoEnum.pendiente)
    fecha = Column(DateTime, default=datetime.utcnow)
    solicitado_por = Column(Integer, ForeignKey("usuarios.id"))
    aprobado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    solicitante = relationship("Usuario", foreign_keys=[solicitado_por])
    aprobador = relationship("Usuario", foreign_keys=[aprobado_por])



class InventarioGeneral(Base):
    __tablename__ = "inventario_general"

    id = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, nullable=False)
    clave = Column(String, unique=True, nullable=False) 
    producto = Column(String, unique=True, nullable=False)
    precio = Column(Integer, nullable=True)
    

class InventarioModulo(Base):
    __tablename__ = "inventario_modulo"

    id = Column(Integer, primary_key=True, index=True)
    modulo = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    clave = Column(String, unique=True, nullable=False) 
    producto = Column(String, unique=True, nullable=False)
    precio = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint('modulo', 'producto', name='modulo_producto_uc'),)
    
    
    
    
class CorreoPromocional(Base):
    __tablename__ = "correos_promocionales"

    id = Column(Integer, primary_key=True, index=True)
    correo = Column(String, unique=True, nullable=False)
    fecha_registro = Column(DateTime, default=datetime.utcnow)

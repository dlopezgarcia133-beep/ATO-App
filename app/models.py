from sqlalchemy import Boolean, Column, Date, Float, Integer, String, DateTime, Time, func
import sqlalchemy
from .database import Base
from datetime import datetime
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    ident = Column(String, unique=True, nullable=False, default="asesor, admin, encargado")  
    password = Column(String, nullable=False)
    modulo = Column(String, nullable=True)  
    is_admin = Column(Boolean, default=False)

    ventas = relationship("Venta", back_populates="empleado")

class Asistencia(Base):
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    modulo = Column(String, nullable=False)
    turno = Column(String, nullable=True)
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
    
    empleado = relationship("Usuario", back_populates="ventas")


class Comision(Base):
    __tablename__ = "comisions"

    id = Column(Integer, primary_key=True, index=True)
    producto = Column(String, unique=True, nullable=False)
    cantidad = Column(Float, nullable=False)  




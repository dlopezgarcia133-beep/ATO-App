import enum
from sqlalchemy import Boolean, Column, Date, Float, Integer, String, Enum, DateTime, Time, UniqueConstraint, func
import sqlalchemy
from .database import Base
from datetime import date, datetime
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
    modulo_id = Column(Integer, ForeignKey("modulos.id"), nullable=True)
    is_admin = Column(Boolean, default=False)

    ventas = relationship("Venta", back_populates="empleado")
    ventas_telefono = relationship("VentaTelefono", back_populates="empleado")
    ventas_chip = relationship("VentaChip", back_populates="empleado")
    modulo = relationship("Modulo", backref="usuarios")

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
    modulo_id = Column(Integer, ForeignKey("modulos.id"), nullable=False)
    producto = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    tipo_venta = Column(String, nullable=False)  
    total = Column(Float, nullable=True) 
    comision_id = Column(Integer, ForeignKey("comisions.id"), nullable=True)
    metodo_pago = Column(String)
    cancelada = Column(Boolean, default=False)
    fecha = Column(Date, default=func.current_date())
    hora = Column(Time, default=func.current_time())
    correo_cliente = Column(String, nullable=True)
    tipo_producto = Column(String, nullable=False)
    
    empleado = relationship("Usuario", back_populates="ventas")
    comision_obj = relationship("Comision")
    modulo = relationship("Modulo", back_populates="ventas")

class VentaChip(Base):
    __tablename__ = "venta_chips"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("usuarios.id"))
    tipo_chip = Column(String, nullable=False)
    numero_telefono = Column(String, nullable=False)
    monto_recarga = Column(Float, nullable=False)
    comision = Column(Float, nullable=True)
    fecha = Column(Date, nullable=False)
    hora = Column(Time, nullable=False)
    cancelada = Column(Boolean, default=False)
    validado = Column(Boolean, default=False)
    descripcion_rechazo = Column(String, nullable=True)


    empleado = relationship("Usuario")


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
    producto = Column(String, nullable=False)
    precio = Column(Integer, nullable=True)
    tipo = Column(String, nullable=False)  

class InventarioModulo(Base):
    __tablename__ = "inventario_modulo"

    id = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, nullable=False)
    clave = Column(String, nullable=False) 
    producto = Column(String, nullable=False)
    precio = Column(Integer, nullable=False)
    modulo_id = Column(Integer, ForeignKey("modulos.id"))
    
    modulo = relationship("Modulo")
    
    
    
    
class CorreoPromocional(Base):
    __tablename__ = "correos_promocionales"

    id = Column(Integer, primary_key=True, index=True)
    correo = Column(String, unique=True, nullable=False)
    fecha_registro = Column(DateTime, default=datetime.utcnow)



class Modulo(Base):
    __tablename__ = "modulos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)

    ventas = relationship("Venta", back_populates="modulo")
    cortes = relationship("CorteDia", back_populates="modulo")

class VentaTelefono(Base):
    __tablename__ = "venta_telefonos"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("usuarios.id"))
    marca = Column(String, nullable=False)
    modelo = Column(String, nullable=False)
    tipo = Column(String, nullable=False)
    precio_venta = Column(Float, nullable=False)
    metodo_pago = Column(String)
    fecha = Column(Date, default=date.today)
    hora = Column(Time, default=datetime.now().time)
    cancelada = Column(Boolean, default=False)
    modulo_id = Column(Integer, ForeignKey("modulos.id"))

    empleado = relationship("Usuario")


class InventarioTelefono(Base):
    __tablename__ = "inventario_telefonos"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String)
    modelo = Column(String)
    cantidad = Column(Integer)
    precio = Column(Float)
    modulo_id = Column(Integer, ForeignKey("modulos.id"))

    modulo = relationship("Modulo")
    

class InventarioTelefonoGeneral(Base):
    __tablename__ = "inventario_telefonos_general"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String)
    modelo = Column(String)
    cantidad = Column(Integer)
    precio = Column(Float)
    clave = Column(String, unique=True, nullable=False) 



class CorteDia(Base):
    __tablename__ = "cortes_dia"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, default=func.current_date())
    modulo_id = Column(Integer, ForeignKey("modulos.id"), nullable=False)

    # 🔹 Subtotales productos
    accesorios_efectivo = Column(Float, default=0)
    accesorios_tarjeta = Column(Float, default=0)
    accesorios_total = Column(Float, default=0)

    # 🔹 Subtotales teléfonos
    telefonos_efectivo = Column(Float, default=0)
    telefonos_tarjeta = Column(Float, default=0)
    telefonos_total = Column(Float, default=0)

    # 🔹 Totales globales
    total_efectivo = Column(Float, default=0)
    total_tarjeta = Column(Float, default=0)
    total_sistema = Column(Float, default=0)
    total_general = Column(Float, default=0)

    # 🔹 Adicionales
    adicional_recargas = Column(Float, default=0)
    adicional_transporte = Column(Float, default=0)
    adicional_otros = Column(Float, default=0)

    modulo = relationship("Modulo", back_populates="cortes")
    
    


class InventarioFisico(Base):
    __tablename__ = "inventario_fisico"

    id = Column(Integer, primary_key=True, index=True)
    producto = Column(String, index=True)
    clave = Column(String, index=True)
    cantidad = Column(Integer, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    

class InventarioTelefonoFisico(Base):
    __tablename__ = "inventario_telefonos_fisico"

    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String)
    modelo = Column(String)
    clave = Column(String)
    cantidad = Column(Integer)
    fecha = Column(DateTime, default=datetime.utcnow)
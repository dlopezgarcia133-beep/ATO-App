from enum import Enum
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel
from datetime import date, datetime, time
from app.models import EstadoTraspasoEnum, RolEnum
from typing import Literal


class AsistenciaLegacyBase(BaseModel):
    nombre: str
    modulo: str
    turno: str

class AsistenciaLegacyCreate(AsistenciaLegacyBase):
    pass

class AsistenciaLegacyResponse(AsistenciaLegacyBase):
    id: int
    fecha: date
    hora: time
    hora_salida: time | None

    class Config:
        from_attributes = True


# ── Schemas de Asistencia geolocalizada ──────────────────────────────────────

class AsistenciaCreate(BaseModel):
    tipo: Literal["entrada", "salida"]
    latitud: float
    longitud: float
    foto_base64: str


class AsistenciaResponse(BaseModel):
    id: int
    usuario_id: int
    username: str
    modulo_id: Optional[int] = None
    fecha: date
    tipo: str
    hora: Optional[datetime] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    foto_url: Optional[str] = None
    dentro_de_zona: Optional[bool] = None
    distancia_metros: Optional[float] = None
    creada_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AsistenciaResumenDia(BaseModel):
    fecha: date
    entrada: Optional[datetime] = None
    salida: Optional[datetime] = None
    horas_trabajadas: float = 0.0
    foto_entrada_url: Optional[str] = None
    foto_salida_url: Optional[str] = None
    dentro_de_zona_entrada: Optional[bool] = None
    dentro_de_zona_salida: Optional[bool] = None
    distancia_metros_entrada: Optional[float] = None
    distancia_metros_salida: Optional[float] = None
    username: Optional[str] = None
    modulo_id: Optional[int] = None
    modulo_nombre: Optional[str] = None
    lugar_trabajo: Optional[str] = None


class ModuloUbicacionUpdate(BaseModel):
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    radio_metros: int = 100


class NotificacionResponse(BaseModel):
    id: int
    asistencia_id: Optional[int] = None
    usuario_id: int
    username: str
    modulo_id: Optional[int] = None
    mensaje: str
    distancia_metros: Optional[float] = None
    leida: bool
    creada_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ModuloConUbicacion(BaseModel):
    id: int
    nombre: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    radio_metros: int = 100

    class Config:
        from_attributes = True


class PromotorUbicacionUpdate(BaseModel):
    lugar_trabajo: str
    latitud_promotor: float
    longitud_promotor: float
    radio_metros_promotor: int = 100


class PromotorConUbicacion(BaseModel):
    id: int
    username: str
    lugar_trabajo: Optional[str] = None
    latitud_promotor: Optional[float] = None
    longitud_promotor: Optional[float] = None
    radio_metros_promotor: Optional[int] = 100

    class Config:
        from_attributes = True



class RolEnum(str, Enum):
    admin = "admin"
    encargado = "encargado"
    asesor = "asesor"
    direccion = "direccion"

# 👉 Este es el que se usa para crear un usuario
class UsuarioCreate(BaseModel):
    nombre_completo: str
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
    tipo_producto: str 
    tipo_venta: str
    metodo_pago: str
    chip_casado: str
    telefono_cliente: Optional[str] = None



class SueldoBaseUpdate(BaseModel):
    sueldo_base: float
     

class VentaResponse(VentaCreate):
    id: int
    empleado: Optional[UsuarioResponse] = None
    modulo: Optional[ModuloOut]
    producto: str
    cantidad: int
    precio_unitario: float
    total: Optional[float] = None
    comision: Optional[float] = None
    tipo_producto: Optional[str] = None
    tipo_venta: Optional[str] = None
    metodo_pago: Optional[str] = None
    cancelada : Optional[bool] = None
    telefono_cliente: Optional[str] = None
    chip_casado: Optional[str] = None
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
    chip_casado: Optional[str] = None 
    tipo_producto: Optional[str] = None
    tipo_venta: Optional[str] = None
    metodo_pago: Optional[str] = None
    cancelada: Optional[bool] = False

class VentaMultipleCreate(BaseModel):
    productos: List[ProductoEnVenta]
    telefono_cliente: Optional[str] = None
    metodo_pago: str

class VentaChipCreate(BaseModel):
    tipo_chip: str
    numero_telefono: str
    monto_recarga: float
    cvip: bool
  

class VentaChipResponse(VentaChipCreate):
    id: int
    empleado_id: Optional[int] = None
    empleado: Optional[UsuarioResponse] = None
    comision: Optional[float] = None
    numero_telefono: str
    fecha: date
    hora: time
    cancelada: bool
    validado: bool
    comision_pagada: bool = False
    descripcion_rechazo: Optional[str] = None

    class Config:
        from_attributes = True


class PagarComisionesInput(BaseModel):
    numeros: list[str]

class PagarComisionesResponse(BaseModel):
    pagados: int
    no_encontrados: list[str]


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
    folio: Optional[str] = None


class TraspasoResponse(TraspasoBase):
    id: int
    modulo_origen: str
    estado: str
    fecha: datetime
    solicitado_por: int
    aprobado_por: Optional[int] = None
    visible_en_pendientes: bool 
    clave: Optional[str] = None
    precio: Optional[float] = None
    tipo_producto: Optional[str] = None
    folio: str | None

    class Config:
        from_attributes = True





class InventarioGeneralCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int
    tipo_producto: str


class InventarioGeneralUpdate(BaseModel):
    cantidad: int


class InventarioGeneralResponse(BaseModel):
    id: int
    producto: str
    clave: str
    cantidad: int
    precio: int
    tipo_producto: str

    class Config:
        from_attributes = True




class InventarioModuloCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int
    modulo_id: int
    tipo_producto: Optional[str] = None


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

class InventarioGlobalCreate(BaseModel):
    cantidad: int
    clave: str
    producto: str
    precio: int
    tipo_producto: str


class InventarioGlobalUpdate(BaseModel):
    cantidad: Optional[int] = None
    precio: Optional[int] = None
    clave: Optional[str] = None
    producto: Optional[str] = None
    tipo_producto: Optional[str] = None



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
    tipo_venta: Optional[str] = None
    comision_total: Optional[float] = None
    fecha: Optional[date] = None
    hora: Optional[time] = None


class VentaTelefonoConComision(BaseModel):
    producto: str
    cantidad: int
    tipo_venta: str
    comision: Optional[float] = None
    comision_total: float
    fecha: Optional[date] = None
    hora: Optional[time] = None


class VentaChipConComision(BaseModel):
    tipo_chip: str
    numero_telefono: Optional[str] = None
    comision: float
    es_incubadora: Optional[bool] = False
    fecha: Optional[date] = None
    hora: Optional[time] = None

class ComisionesCicloResponse(BaseModel):
    inicio_ciclo: date
    fin_ciclo: date
    fecha_pago: Optional[date] = None
    total_chips: float
    total_accesorios: float
    total_telefonos: float
    total_general: float
    ventas_accesorios: List[VentaAccesorioConComision]
    ventas_telefonos: List[VentaTelefonoConComision]
    ventas_chips: List[VentaChipConComision]

class CorteDiaCreate(BaseModel):
    fecha: date
    # accesorios
    accesorios_efectivo: float
    accesorios_tarjeta: float
    accesorios_total: float
    # teléfonos
    telefonos_efectivo: float
    telefonos_tarjeta: float
    telefonos_total: float
    # totales generales
    total_efectivo: float
    total_tarjeta: float
    total_sistema: float
    total_general: float
    # adicionales
    adicional_recargas: float
    adicional_transporte: float
    adicional_otros: float
    

class RecargasUpdate(BaseModel):
    adicional_recargas: float = 0
    adicional_transporte: float = 0
    adicional_otros: float = 0
    adicional_mayoreo: float = 0
    adicional_mayoreo_para: Optional[str] = None

class SalidaUpdate(BaseModel):
    salida_efectivo: float = 0
    nota_salida: Optional[str] = None

class CorteDiaResponse(BaseModel):
    id: int
    fecha: date
    modulo_id: int
    accesorios_efectivo: float
    accesorios_tarjeta: float
    accesorios_total: float
    telefonos_efectivo: float
    telefonos_tarjeta: float
    telefonos_total: float
    total_efectivo: float
    total_tarjeta: float
    total_sistema: float
    total_general: float
    adicional_recargas: float
    adicional_transporte: float
    adicional_otros: float
    adicional_mayoreo: float
    adicional_mayoreo_para: Optional[str]
    salida_efectivo: float
    nota_salida: Optional[str]
    enviado: bool
    revisado_direccion: bool = False
    revisado_por: Optional[str] = None
    revisado_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CortePendienteItem(BaseModel):
    id: int
    modulo_id: int
    modulo_nombre: str
    fecha: date
    total_efectivo: float
    total_tarjeta: float
    total_general: float


class CorteRevisarResponse(BaseModel):
    revisado_direccion: bool
    revisado_por: str
    revisado_at: datetime

class ComisionInput(BaseModel):
    comision_manual: Optional[float] = None
    
    
class ValidarChipIncubadoraRequest(BaseModel):
    comision_manual: Optional[float] = None

class InventarioFisicoBase(BaseModel):
    producto: str
    clave: str
    cantidad: int

class InventarioFisicoCreate(InventarioFisicoBase):
    pass

class InventarioFisicoResponse(InventarioFisicoBase):
    id: int
    fecha: datetime

    class Config:
        orm_mode = True



class ItemConteo(BaseModel):
    producto_id: int
    cantidad: int

class ConteoRequest(BaseModel):
    modulo_id: int
    productos: List[ItemConteo]


class ProductoConteo(BaseModel):
    clave: str
    cantidad: int

class ConteoInventarioRequest(BaseModel):
    modulo_id: int
    productos: List[ProductoConteo]


class EntradaItem(BaseModel):
    producto_id: int
    cantidad: int

class EntradaMercanciaRequest(BaseModel):
    modulo_id: int
    productos: list[EntradaItem]




class NominaPeriodoResponse(BaseModel):
    id: int
    fecha_inicio: date
    fecha_fin: date
    estado: str
    

    class Config:
        from_attributes = True

class NominaPeriodoCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    


class NominaEmpleadoResponse(BaseModel):
    usuario_id: int
    username: str
    comisiones: float
    comisiones_accesorios: float = 0
    comisiones_telefonos: float = 0
    comisiones_chips: float = 0
    sueldo_base: float
    horas_extra: int
    pago_hora_extra: float
    precio_hora_extra: float
    sanciones: float
    comisiones_pendientes: float
    total_pagar: float
    total_comisiones: float



class NominaEmpleadoUpdate(BaseModel):

    horas_extra: Optional[int] = None
    precio_hora_extra: Optional[float] = None
    sanciones: Optional[float] = None
    comisiones_pendientes: Optional[float] = None


class NominaPeriodoFechasUpdate(BaseModel):
    inicio_a: Optional[date] = None
    fin_a: Optional[date] = None
    inicio_c: Optional[date] = None
    fin_c: Optional[date] = None

class PlanCreate(BaseModel):
    tipo_tramite: str
    tipo_plan: str
    empleado_id: int
    modulo_id: int


class NominaHistorialEmpleado(BaseModel):
    usuario_id: int
    username: str
    grupo: str
    comisiones_accesorios: float = 0
    comisiones_telefonos: float = 0
    comisiones_chips: float = 0
    comisiones_total: float = 0
    sueldo_base: float = 0
    horas_extra: float = 0
    precio_hora_extra: float = 0
    pago_horas_extra: float = 0
    sanciones: float = 0
    comisiones_pendientes: float = 0
    horas_faltantes: float = 0
    total_pagar: float = 0


class NominaHistorialCreate(BaseModel):
    semana_inicio: date
    semana_fin: date
    comisiones_inicio_a: date
    comisiones_fin_a: date
    comisiones_inicio_c: date
    comisiones_fin_c: date
    empleados: list[NominaHistorialEmpleado]


class NominaHistorialResponse(BaseModel):
    id: int
    semana_inicio: date
    semana_fin: date
    comisiones_inicio: date
    comisiones_fin: date
    usuario_id: int
    username: str
    grupo: str
    comisiones_accesorios: float
    comisiones_telefonos: float
    comisiones_chips: float
    comisiones_total: float
    sueldo_base: float
    horas_extra: float
    precio_hora_extra: float
    pago_horas_extra: float
    sanciones: float
    comisiones_pendientes: float
    horas_faltantes: float = 0
    total_pagar: float
    guardado_at: datetime

    class Config:
        from_attributes = True


class VentaResumenItem(BaseModel):
    id: int
    producto: str
    tipo_producto: str
    tipo_venta: Optional[str] = None
    precio_unitario: float
    cantidad: int
    total: Optional[float] = None
    metodo_pago: Optional[str] = None
    empleado_username: Optional[str] = None
    cancelada: bool = False


class DireccionCorteResponse(CorteDiaResponse):
    chips_count: int = 0
    chips_por_tipo: Dict[str, int] = {}
    ventas: List[VentaResumenItem] = []


class ModuloStockItem(BaseModel):
    modulo: str
    cantidad: int


class ProductoBusquedaResult(BaseModel):
    producto: str
    total: int
    modulos: List[ModuloStockItem]


class StockPorModuloItem(BaseModel):
    modulo: str
    total_productos: int
    tipos_distintos: int


# ── Estadísticas del mes ──────────────────────────────────────────────────────

class CantidadMonto(BaseModel):
    cantidad: int
    monto: float

class TipoChipStatItem(BaseModel):
    tipo_chip: str
    cantidad: int

class MontoRecargaStatItem(BaseModel):
    monto: str
    cantidad: int

class TopProductoItem(BaseModel):
    producto: str
    cantidad: int
    monto: float

class TramiteStatItem(BaseModel):
    tramite: str
    cantidad: int

class PlanStatItem(BaseModel):
    plan: str
    cantidad: int

class ModuloEstadItem(BaseModel):
    modulo: str
    total_mxn: float
    telefonos_contado: int
    telefonos_payjoy: int
    telefonos_paguitos: int
    telefonos_total: int
    chips: int
    accesorios: int
    planes: int
    promedio_historico: float
    meta_proporcional: float
    productividad_pct: Optional[float] = None
    meses_considerados: int = 0

class VentaDiaItem(BaseModel):
    dia: int
    total: float

class ResumenGeneralStats(BaseModel):
    total_ventas_mxn: float
    total_telefonos: int
    total_chips: int
    total_accesorios: int
    total_planes: int

class TelefonosStats(BaseModel):
    total: int
    contado: CantidadMonto
    payjoy: CantidadMonto
    paguitos: CantidadMonto
    sin_clasificar: CantidadMonto

class AccesoriosStats(BaseModel):
    total_unidades: int
    monto_total: float
    top_5_productos: List[TopProductoItem]

class ChipsStats(BaseModel):
    total: int
    por_tipo: List[TipoChipStatItem]
    por_monto_recarga: List[MontoRecargaStatItem]

class PlanesStats(BaseModel):
    total: int
    por_tramite: List[TramiteStatItem]
    por_plan: List[PlanStatItem]

class TelefonoModuloItem(BaseModel):
    modulo: str
    total_telefonos: int
    monto_total: float
    contado: int
    payjoy: int
    paguitos: int

class EstadisticasMesResponse(BaseModel):
    mes: str
    periodo_texto: str
    resumen_general: ResumenGeneralStats
    telefonos: TelefonosStats
    accesorios: AccesoriosStats
    chips: ChipsStats
    planes: PlanesStats
    por_modulo: List[ModuloEstadItem]
    ventas_por_dia: List[VentaDiaItem]
    telefonos_por_modulo: List[TelefonoModuloItem]


# ── Tiempo Real ───────────────────────────────────────────────────────────────

class TiempoRealResumen(BaseModel):
    total_ventas_mxn: float
    total_telefonos: int
    total_chips: int
    total_accesorios: int

class TelefonoHoyItem(BaseModel):
    hora: str
    modulo: str
    asesor: str
    producto: str
    tipo_venta: str
    precio: float

class ModuloTiempoRealItem(BaseModel):
    modulo: str
    total_mxn: float
    telefonos_contado: int
    telefonos_payjoy: int
    telefonos_paguitos: int
    telefonos_total: int
    chips: int
    accesorios: int
    promedio_diario_historico: float
    meta_proporcional: float
    productividad_pct: Optional[float] = None
    dias_considerados: int = 0

class TiempoRealResponse(BaseModel):
    fecha: str
    fecha_texto: str
    hora_actual: str
    horas_transcurridas: float
    horas_totales: int
    porcentaje_dia: float
    resumen_general: TiempoRealResumen
    telefonos: TelefonosStats
    chips: ChipsStats
    accesorios: AccesoriosStats
    lista_telefonos_hoy: List[TelefonoHoyItem]
    por_modulo: List[ModuloTiempoRealItem]


from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from app import models
from app.config import get_current_user
from app.database import SessionLocal
from app.models import CorreoPromocional, RolEnum, Usuario
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv



def verificar_rol_requerido(roles_permitidos):
    if not isinstance(roles_permitidos, list):
        roles_permitidos = [roles_permitidos]

    def wrapper(current_user: models.Usuario = Depends(get_current_user)):
        if current_user.rol not in roles_permitidos:
            roles = ', '.join([r.value for r in roles_permitidos])
            raise HTTPException(status_code=403, detail=f"Acceso denegado. Se requiere rol: {roles}")
        return current_user
    return wrapper




load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

def enviar_ticket(destinatario: str, venta_data: dict):
    mensaje = MIMEMultipart("alternative")
    mensaje["Subject"] = "Tu ticket de compra"
    mensaje["From"] = EMAIL_USER
    mensaje["To"] = destinatario

    # Construir cuerpo del ticket
    cuerpo = f"""
    <h3>Gracias por tu compra</h3>
    <p><strong>Producto:</strong> {venta_data['producto']}</p>
    <p><strong>Cantidad:</strong> {venta_data['cantidad']}</p>
    <p><strong>Total:</strong> ${venta_data['total']}</p>
    """

    mensaje.attach(MIMEText(cuerpo, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
        servidor.login(EMAIL_USER, EMAIL_PASS)
        servidor.sendmail(EMAIL_USER, destinatario, mensaje.as_string())




def calcular_comision_telefono(v):
    # Comisión base (si no tiene, es 0)
    comision_base = v.comision_obj.cantidad if v.comision_obj else 0

    # Tabla de comisiones extra según tipo_venta
    comisiones_por_tipo = {
        "Contado": 10,
        "Paguitos": 110,
        "Pajoy": 100
    }

    # Extra según tipo_venta (si no está en el dict, devuelve 0)
    extra = comisiones_por_tipo.get(v.tipo_venta, 0)

    # Comisión final = base * cantidad + extra
    return (comision_base * v.cantidad) + extra



from sqlalchemy import func

def obtener_comisiones_por_empleado(db, inicio, fin):
    filas = (
        db.query(
            models.Venta.empleado_id,
            func.sum(models.Venta.comision).label("total_comisiones")
        )
        .filter(
            models.Venta.fecha >= inicio,
            models.Venta.fecha <= fin,
            models.Venta.cancelada == False
        )
        .group_by(models.Venta.empleado_id)
        .all()
    )

    return {f.empleado_id: f.total_comisiones or 0 for f in filas}


from datetime import datetime, timedelta
from unittest import case
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
from sqlalchemy import func, case as sql_case



def verificar_rol_requerido(roles_permitidos):
    if not isinstance(roles_permitidos, list):
        roles_permitidos = [roles_permitidos]

    def wrapper(current_user: models.Usuario = Depends(get_current_user)):
        if current_user.rol not in roles_permitidos:
            roles = ', '.join([r.value for r in roles_permitidos])
            raise HTTPException(status_code=403, detail=f"Acceso denegado. Se requiere rol: {roles}")
        return current_user
    return wrapper


def verificar_modulo_no_congelado(db, modulo_id):
    m = db.query(models.Modulo).filter(models.Modulo.id == modulo_id).first()
    if m and m.congelado:
        raise HTTPException(
            status_code=423,
            detail="Este modulo esta en conteo fisico. Las ventas y traspasos estan temporalmente bloqueados. Intenta mas tarde o contacta al administrador."
        )



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
    comision_base = v.comision_obj.cantidad if v.comision_obj else 0
    tipo = v.tipo_venta or ""
    # Contado con comisión especial: los $10 NO se suman
    if tipo == "Contado" and comision_base > 0:
        return comision_base * v.cantidad
    extra = {"Contado": 10, "Paguitos": 110, "Pajoy": 100}.get(tipo, 0)
    return (comision_base + extra) * v.cantidad



from sqlalchemy import func

from sqlalchemy import func

def obtener_comisiones_por_empleado(db, inicio, fin):
    rows = (
        db.query(
            models.Venta.empleado_id,
            func.coalesce(
                func.sum(
                    models.Comision.cantidad * models.Venta.cantidad
                ),
                0
            ).label("total_comisiones")
        )
        .join(
            models.Comision,
            models.Venta.comision_id == models.Comision.id
        )
        .filter(
            models.Venta.cancelada == False,
            models.Venta.fecha >= inicio,
            models.Venta.fecha <= fin
        )
        .group_by(models.Venta.empleado_id)
        .all()
    )

    return {r.empleado_id: float(r.total_comisiones) for r in rows}


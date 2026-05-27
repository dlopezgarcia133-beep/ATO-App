import re
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models
from app.config import get_current_user
from app.database import get_db

router = APIRouter()


def _get_nomina_publicada(db: Session) -> models.Nomina:
    nomina = db.query(models.Nomina).filter(models.Nomina.publicada == True).first()
    if not nomina:
        raise HTTPException(404, "No hay nómina publicada actualmente")
    return nomina


def _get_mi_fila(nomina: models.Nomina, current_user: models.Usuario) -> dict:
    fila = next(
        (item for item in nomina.datos if current_user.id in item.get("usuario_ids", [])),
        None,
    )
    if not fila:
        raise HTTPException(404, "No apareces en la nómina publicada")
    return fila


def _build_periodos(nomina: models.Nomina) -> dict:
    periodos: dict = {}
    if nomina.ciclo_horas_extras:
        periodos["horas_extras"] = {
            "inicio": str(nomina.ciclo_horas_extras.fecha_inicio),
            "fin": str(nomina.ciclo_horas_extras.fecha_fin),
        }
    if nomina.fecha_inicio_asesores:
        periodos["asesores"] = {
            "inicio": str(nomina.fecha_inicio_asesores),
            "fin": str(nomina.fecha_fin_asesores),
        }
    if nomina.fecha_inicio_encargados:
        periodos["encargados"] = {
            "inicio": str(nomina.fecha_inicio_encargados),
            "fin": str(nomina.fecha_fin_encargados),
        }
    if nomina.fecha_inicio_cadenas:
        periodos["cadenas"] = {
            "inicio": str(nomina.fecha_inicio_cadenas),
            "fin": str(nomina.fecha_fin_cadenas),
        }
    return periodos


@router.get("/mi-recibo")
def mi_recibo(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    nomina = _get_nomina_publicada(db)
    fila = _get_mi_fila(nomina, current_user)
    return {
        "etiqueta": nomina.etiqueta,
        "creado_en": nomina.creado_en.isoformat() if nomina.creado_en else None,
        "periodos": _build_periodos(nomina),
        "fila": fila,
    }


@router.get("/mi-recibo/pdf")
def mi_recibo_pdf(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    nomina = _get_nomina_publicada(db)
    fila = _get_mi_fila(nomina, current_user)
    periodos = _build_periodos(nomina)

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        HRFlowable, SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50,
    )
    styles = getSampleStyleSheet()
    ato_orange = colors.HexColor("#FF6600")

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=ato_orange, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=ato_orange, fontSize=11, spaceAfter=4)

    def fmt(v): return f"${float(v or 0):.2f}"

    he = fila.get("horas_extra")
    he_str = "—" if he is None else (f"+{float(he):.1f} hrs" if float(he) > 0 else f"{float(he):.1f} hrs")

    elements = []
    elements.append(Paragraph("ATO Sistema — Recibo de Nómina", h1))
    creado_str = nomina.creado_en.strftime("%d/%m/%Y %H:%M") if nomina.creado_en else ""
    elements.append(Paragraph(f"Nómina: <b>{nomina.etiqueta}</b>  |  Emitida: {creado_str}", styles["Normal"]))
    elements.append(Spacer(1, 10))

    # Employee info
    elements.append(Paragraph("EMPLEADO", h2))
    seccion_map = {"asesor": "Asesor", "encargado": "Encargado", "cadena": "Cadena Comercial"}
    seccion_label = seccion_map.get(fila.get("seccion", ""), fila.get("seccion", ""))
    emp_table = Table(
        [["Nombre:", fila.get("empleado", "")], ["Sección:", seccion_label]],
        colWidths=[110, 340],
    )
    emp_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(emp_table)
    elements.append(Spacer(1, 10))

    # Periodos
    if periodos:
        elements.append(Paragraph("PERIODOS DE PAGO", h2))
        periodo_labels = {
            "horas_extras": "Horas Extra:",
            "asesores": "Comisiones:",
            "encargados": "Com. Encargados:",
            "cadenas": "Com. Cadenas:",
        }
        period_rows = [
            [label, f"{p['inicio']}  →  {p['fin']}"]
            for key, label in periodo_labels.items()
            if (p := periodos.get(key))
        ]
        if period_rows:
            p_table = Table(period_rows, colWidths=[160, 290])
            p_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            elements.append(p_table)
        elements.append(Spacer(1, 10))

    # Desglose
    elements.append(Paragraph("DESGLOSE", h2))
    desglose_rows = [
        ["Sueldo base:", fmt(fila.get("sueldo", 0))],
        ["Horas extra:", he_str],
        ["Pago H. Extra:", fmt(fila.get("pago_he", 0))],
        ["Accesorios:", fmt(fila.get("accesorios", 0))],
        ["Teléfonos:", fmt(fila.get("telefonos", 0))],
        ["Chips:", fmt(fila.get("chips", 0))],
        ["Incubadora:", fmt(fila.get("incubadora", 0))],
        ["Planes tarifarios:", fmt(fila.get("planes", 0))],
        ["Com. pendientes:", fmt(fila.get("pendientes", 0))],
        ["Bonos:", fmt(fila.get("bonos", 0))],
        ["Subtotal:", fmt(fila.get("subtotal", 0))],
        ["Sanciones:", f"-{fmt(fila.get('sanciones', 0))}"],
    ]
    d_table = Table(desglose_rows, colWidths=[200, 250])
    d_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 10), (-1, 11), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 11), (1, 11), colors.HexColor("#dc2626")),
        ("LINEABOVE", (0, 10), (-1, 10), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(d_table)

    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=ato_orange))
    elements.append(Spacer(1, 6))

    total_table = Table(
        [["DEPÓSITO TOTAL:", fmt(fila.get("deposito", 0))]],
        colWidths=[200, 250],
    )
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 14),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (1, 0), (1, 0), colors.HexColor("#16a34a")),
    ]))
    elements.append(total_table)

    doc.build(elements)
    buf.seek(0)

    emp_name = re.sub(r"[^\w\-]", "_", fila.get("empleado", "recibo"))[:40]
    fname = f"recibo_{emp_name}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

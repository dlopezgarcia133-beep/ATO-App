from collections import defaultdict
from io import BytesIO
from typing import List, Optional
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_current_user
from app.database import get_db

router = APIRouter()

FORMAS_PAGO_VALIDAS = {"BBVA", "Banco Azteca", "Kids"}


class NominaGrupoUpdate(BaseModel):
    sueldo_base: float
    forma_pago: Optional[str] = None
    cuenta_clabe: Optional[str] = None
    cuenta_interbancaria: Optional[str] = None


class EnglobadoUpdate(BaseModel):
    nombre_englobado: Optional[str] = None


class JornadaFijaUpdate(BaseModel):
    jornada: float


class DiaTrabajo(BaseModel):
    dia: str
    entrada: Optional[str] = None
    salida: Optional[str] = None
    descanso: bool = False


class HorarioUpdate(BaseModel):
    horario_semanal: List[DiaTrabajo]
    dia_descanso: Optional[str] = None


def _calcular_horas(entrada: str, salida: str) -> float:
    """Misma fórmula que frontend: diff en minutos / 60."""
    eh, em = map(int, entrada.split(":"))
    sh, sm = map(int, salida.split(":"))
    diff_min = (sh * 60 + sm) - (eh * 60 + em)
    return 0.0 if diff_min <= 0 else diff_min / 60


def _solo_admin(user: models.Usuario) -> None:
    if user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")


@router.get("/nomina")
def get_nomina_consolidada(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuarios = db.query(models.Usuario).filter(models.Usuario.activo == True).all()

    groups: dict = defaultdict(list)
    for u in usuarios:
        key = u.nombre_englobado or u.username
        groups[key].append(u)

    result = []
    for group_name, perfiles in sorted(groups.items()):
        principal = next((p for p in perfiles if (p.sueldo_base or 0) > 0), perfiles[0])
        sueldo_total = sum(p.sueldo_base or 0 for p in perfiles)

        result.append({
            "nombre_englobado": group_name,
            "sueldo_base_total": sueldo_total,
            "forma_pago": principal.forma_pago,
            "cuenta_clabe": principal.cuenta_clabe,
            "cuenta_interbancaria": principal.cuenta_interbancaria,
            "perfiles_incluidos": [
                {
                    "id": p.id,
                    "codigo": p.username,
                    "modulo": p.modulo.nombre if p.modulo else None,
                    "sueldo": p.sueldo_base or 0,
                }
                for p in sorted(perfiles, key=lambda x: x.id)
            ],
        })

    return result


@router.put("/nomina/{nombre_englobado}")
def update_nomina_grupo(
    nombre_englobado: str,
    data: NominaGrupoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    if data.forma_pago and data.forma_pago not in FORMAS_PAGO_VALIDAS:
        raise HTTPException(400, f"forma_pago debe ser uno de: {', '.join(FORMAS_PAGO_VALIDAS)}")
    if data.sueldo_base < 0:
        raise HTTPException(400, "sueldo_base debe ser >= 0")
    if data.cuenta_clabe and not (18 <= len(data.cuenta_clabe) <= 20):
        raise HTTPException(400, "cuenta_clabe debe tener entre 18 y 20 caracteres")

    # Buscar por nombre_englobado
    perfiles = (
        db.query(models.Usuario)
        .filter(
            models.Usuario.nombre_englobado == nombre_englobado,
            models.Usuario.activo == True,
        )
        .all()
    )

    # Si no hay, asumir grupo de uno (clave == username, sin nombre_englobado)
    if not perfiles:
        perfiles = (
            db.query(models.Usuario)
            .filter(
                models.Usuario.username == nombre_englobado,
                models.Usuario.activo == True,
                models.Usuario.nombre_englobado.is_(None),
            )
            .all()
        )

    if not perfiles:
        raise HTTPException(404, "Grupo no encontrado")

    principal = next((p for p in perfiles if (p.sueldo_base or 0) > 0), perfiles[0])

    for p in perfiles:
        p.forma_pago = data.forma_pago or None
        p.cuenta_clabe = data.cuenta_clabe or None
        p.cuenta_interbancaria = data.cuenta_interbancaria or None
        p.sueldo_base = data.sueldo_base if p.id == principal.id else 0

    db.commit()
    return {"ok": True}


@router.put("/usuarios/{usuario_id}/englobado")
def assign_nombre_englobado(
    usuario_id: int,
    data: EnglobadoUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    usuario.nombre_englobado = data.nombre_englobado or None
    db.commit()
    return {"ok": True}


@router.put("/usuarios/{usuario_id}/jornada-fija")
def update_jornada_fija(
    usuario_id: int,
    data: JornadaFijaUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    usuario.jornada_fija = data.jornada
    db.commit()
    return {"ok": True}


@router.put("/usuarios/{usuario_id}/horario")
def update_horario(
    usuario_id: int,
    data: HorarioUpdate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    jornada_total = sum(
        _calcular_horas(d.entrada, d.salida)
        for d in data.horario_semanal
        if not d.descanso and d.entrada and d.salida
    )
    jornada_total = round(jornada_total, 2)

    usuario.horario_semanal = [d.model_dump() for d in data.horario_semanal]
    usuario.dia_descanso = data.dia_descanso or None
    usuario.jornada_fija = jornada_total

    db.commit()
    return {"ok": True, "jornada_fija": jornada_total}


@router.post("/ciclos-guardados", response_model=schemas.CicloGuardadoResponse)
def crear_ciclo_guardado(
    data: schemas.CicloGuardadoCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    if not data.etiqueta.strip():
        raise HTTPException(400, "La etiqueta no puede estar vacía")

    registro = models.CicloGuardado(
        concepto=data.concepto,
        etiqueta=data.etiqueta.strip(),
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        datos=data.datos,
        creado_por=current_user.username,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


@router.get("/ciclos-guardados", response_model=list[schemas.CicloGuardadoResponse])
def listar_ciclos_guardados(
    concepto: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    return (
        db.query(models.CicloGuardado)
        .filter(models.CicloGuardado.concepto == concepto)
        .order_by(models.CicloGuardado.creado_en.desc())
        .all()
    )


# ── Nóminas ───────────────────────────────────────────────────────────────────

def _safe_filename(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:60]


@router.post("/nominas", response_model=schemas.NominaResponse)
def crear_nomina(
    data: schemas.NominaCreate,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    if not data.etiqueta.strip():
        raise HTTPException(400, "La etiqueta no puede estar vacía")

    total = sum(float(item.get("pago_total", 0)) for item in data.datos)

    nomina = models.Nomina(
        etiqueta=data.etiqueta.strip(),
        ciclo_horas_extras_id=data.ciclo_horas_extras_id,
        total_pago=round(total, 2),
        datos=data.datos,
        creado_por=current_user.username,
    )
    db.add(nomina)
    db.commit()
    db.refresh(nomina)
    return nomina


@router.get("/nominas", response_model=list[schemas.NominaListItem])
def listar_nominas(
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    return (
        db.query(models.Nomina)
        .order_by(models.Nomina.creado_en.desc())
        .all()
    )


@router.get("/nominas/{nomina_id}", response_model=schemas.NominaResponse)
def detalle_nomina(
    nomina_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    nomina = db.query(models.Nomina).filter_by(id=nomina_id).first()
    if not nomina:
        raise HTTPException(404, "Nómina no encontrada")
    return nomina


@router.get("/nominas/{nomina_id}/excel")
def descargar_nomina_excel(
    nomina_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    nomina = db.query(models.Nomina).filter_by(id=nomina_id).first()
    if not nomina:
        raise HTTPException(404, "Nómina no encontrada")

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "Nómina"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="FF6600")
    total_font = Font(bold=True)

    headers = ["Empleado", "Nombre completo", "Pago H. Extras", "Total Pago"]
    col_widths = [20, 30, 18, 18]

    for col, (h, w) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for row_idx, item in enumerate(nomina.datos, start=2):
        ws.cell(row=row_idx, column=1, value=item.get("empleado", ""))
        ws.cell(row=row_idx, column=2, value=item.get("nombre_completo", ""))
        ws.cell(row=row_idx, column=3, value=round(float(item.get("pago_horas_extras", 0)), 2))
        ws.cell(row=row_idx, column=4, value=round(float(item.get("pago_total", 0)), 2))

    total_row = len(nomina.datos) + 2
    ws.cell(row=total_row, column=1, value="TOTAL").font = total_font
    ws.cell(row=total_row, column=4, value=float(nomina.total_pago)).font = total_font

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = f"nomina_{_safe_filename(nomina.etiqueta)}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/nominas/{nomina_id}/pdf")
def descargar_nomina_pdf(
    nomina_id: int,
    db: Session = Depends(get_db),
    current_user: models.Usuario = Depends(get_current_user),
):
    _solo_admin(current_user)

    nomina = db.query(models.Nomina).filter_by(id=nomina_id).first()
    if not nomina:
        raise HTTPException(404, "Nómina no encontrada")

    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    elements = []

    ato_orange = colors.HexColor("#FF6600")

    title_style = styles["Heading1"]
    title_style.textColor = ato_orange
    elements.append(Paragraph(f"NÓMINA — {nomina.etiqueta}", title_style))
    creado_str = nomina.creado_en.strftime("%d/%m/%Y %H:%M") if nomina.creado_en else ""
    elements.append(Paragraph(f"Creado por: {nomina.creado_por}  |  {creado_str}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    table_data = [["Empleado", "Nombre completo", "Pago H. Extras", "Total Pago"]]
    for item in nomina.datos:
        table_data.append([
            item.get("empleado", ""),
            item.get("nombre_completo", ""),
            f"${float(item.get('pago_horas_extras', 0)):.2f}",
            f"${float(item.get('pago_total', 0)):.2f}",
        ])
    table_data.append(["TOTAL", "", "", f"${float(nomina.total_pago):.2f}"])

    col_widths_pdf = [100, 180, 100, 100]
    t = Table(table_data, colWidths=col_widths_pdf)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ato_orange),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)

    fname = f"nomina_{_safe_filename(nomina.etiqueta)}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

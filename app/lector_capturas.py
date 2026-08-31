import base64
import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
from PIL import Image

MODELO = "claude-haiku-4-5"
MAX_LADO = 1000

PROMPT = """Eres un lector de capturas de pantalla de la app Telcel "Check In/Out".

Devuelve UNICAMENTE un objeto JSON, sin markdown, sin backticks, sin texto antes ni despues.

Campos:
{
  "legible": true/false,
  "clave": "codigo del encabezado, ej CPLCCCP01",
  "fecha": "YYYY-MM-DD",
  "entrada_hora": "HH:MM tal cual aparece, sin convertir",
  "entrada_meridiano": "am" o "pm",
  "salida_hora": "HH:MM tal cual aparece, sin convertir, o null",
  "salida_meridiano": "am" o "pm" o null,
  "duracion_texto": "texto de Duracion de Jornada tal cual, o null"
}

Reglas:
- La fecha viene como dd/mm/aa. El anio 26 significa 2026.
- NO conviertas las horas. Copialas exactamente como se ven.
  Si dice "01:47 p. m." entonces entrada_hora es "01:47" y entrada_meridiano es "pm".
- IGNORA por completo el titulo de la pantalla y el boton circular grande de
  color (rojo o verde). Ese boton es solo un boton, NO es un registro.
  Que diga "Check Out" arriba no significa que la hora de abajo sea una salida.
- Los unicos registros validos son los RECUADROS de abajo que tienen los
  encabezados "Fecha" y "Hora".
- Si hay UN SOLO recuadro con fecha y hora, esa hora SIEMPRE es la entrada.
  entrada_hora se llena con ella y los campos de salida quedan en null.
- Si hay DOS recuadros, el primero (icono verde) es la entrada y el segundo
  (icono rojo) es la salida.
- Si la imagen no es de esta app o no se alcanza a leer, pon "legible": false
  y el resto en null.
"""

def _preparar_imagen(contenido: bytes) -> str:
    img = Image.open(io.BytesIO(contenido))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > MAX_LADO:
        factor = MAX_LADO / max(img.size)
        nuevo = (int(img.width * factor), int(img.height * factor))
        img = img.resize(nuevo, Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _a_24h(hora: str, meridiano: str):
    if not hora or not meridiano:
        return None
    try:
        h, m = hora.strip().split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if not (1 <= h <= 12 and 0 <= m <= 59):
        return None
    mer = meridiano.strip().lower().replace(".", "").replace(" ", "")
    if mer in ("pm", "p.m", "pm."):
        if h != 12:
            h += 12
    elif mer in ("am", "a.m", "am."):
        if h == 12:
            h = 0
    else:
        return None
    return f"{h:02d}:{m:02d}"


def _normalizar(datos: dict) -> dict:
    if not datos.get("legible"):
        return datos

    entrada = _a_24h(datos.get("entrada_hora"), datos.get("entrada_meridiano"))
    salida = _a_24h(datos.get("salida_hora"), datos.get("salida_meridiano"))

    datos["hora_entrada"] = entrada
    datos["hora_salida"] = salida
    datos["duracion_minutos"] = None

    if entrada and salida:
        he, me = map(int, entrada.split(":"))
        hs, ms = map(int, salida.split(":"))
        minutos = (hs * 60 + ms) - (he * 60 + me)
        if minutos < 0:
            minutos += 1440
        datos["duracion_minutos"] = minutos

    if not entrada:
        datos["legible"] = False
        datos["error"] = "hora_entrada_invalida"

    return datos


def leer_captura(contenido: bytes) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY")

    imagen_b64 = _preparar_imagen(contenido)
    cliente = anthropic.Anthropic(api_key=api_key)

    respuesta = cliente.messages.create(
        model=MODELO,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": imagen_b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    texto = "".join(
        bloque.text for bloque in respuesta.content if bloque.type == "text"
    ).strip()
    texto = texto.replace("```json", "").replace("```", "").strip()

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return {"legible": False, "error": "respuesta_no_json", "crudo": texto[:200]}

    datos = _normalizar(datos)
    datos["_leido_at"] = datetime.now(
        ZoneInfo("America/Mexico_City")
    ).replace(tzinfo=None).isoformat()
    return datos

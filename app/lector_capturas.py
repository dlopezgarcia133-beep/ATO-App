import base64
import io
import json
import os
import re
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
  "fecha_cruda": "los caracteres de la fecha tal cual se ven, ej 01/09/26",
  "entrada_hora": "HH:MM tal cual aparece, sin convertir",
  "entrada_meridiano": "am" o "pm",
  "salida_hora": "HH:MM tal cual aparece, sin convertir, o null",
  "salida_meridiano": "am" o "pm" o null,
  "duracion_texto": "texto de Duracion de Jornada tal cual, o null",
  "formato_hora": "12h" o "24h"
}

Reglas:
- Los recuadros de abajo se leen SIEMPRE por posicion vertical.
  El recuadro de ARRIBA es la ENTRADA. El recuadro de ABAJO es la SALIDA.
  La posicion manda siempre. El color del icono es solo confirmacion.
- La ENTRADA siempre ocurre antes que la SALIDA en la misma jornada.
  Si al leerlas la salida te queda mas temprano que la entrada,
  las leiste al reves: vuelve a mirar cual recuadro esta arriba.
- Si hay UN SOLO recuadro con fecha y hora, esa hora SIEMPRE es la entrada
  y los campos de salida quedan en null.
- duracion_texto es el recuadro azul "Duracion de Jornada". Copialo tal cual.
  Es un dato independiente: debe ser coherente con la diferencia entre
  entrada y salida.
- fecha_cruda son los digitos de la fecha copiados EXACTAMENTE como aparecen,
  sin reordenar y sin interpretar. Si se ve "01/09/26" escribe "01/09/26".
- La app siempre usa dia/mes/anio. NO reordenes. "01/09/26" es 1 de septiembre.
- NO conviertas las horas. Copialas exactamente como se ven.
  Si dice "01:47 p. m." entonces entrada_hora es "01:47" y entrada_meridiano es "pm".
- Si las horas traen a.m. o p.m., formato_hora es "12h".
- Si las horas NO traen ningun a.m. ni p.m. (ej "14:08"), formato_hora es "24h"
  y los campos de meridiano quedan en null. Copia la hora tal cual.
- IGNORA por completo el titulo de la pantalla y el boton circular grande de
  color (rojo o verde). Ese boton es solo un boton, NO es un registro.
  Que diga "Check Out" arriba no significa que la hora de abajo sea una salida.
- Los unicos registros validos son los RECUADROS de abajo que tienen los
  encabezados "Fecha" y "Hora".
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


def _a_24h(hora: str, meridiano: str, formato: str = "12h"):
    if not hora:
        return None
    try:
        h, m = hora.strip().split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if not (0 <= m <= 59):
        return None

    es_24h = (formato or "").strip().lower().replace(" ", "") in ("24h", "24")

    if not meridiano:
        # Sin meridiano solo se acepta si la pantalla venia en formato 24 horas.
        # Si no, la hora es ambigua y se rechaza en vez de adivinar.
        if not es_24h or not (0 <= h <= 23):
            return None
        return f"{h:02d}:{m:02d}"

    if not (1 <= h <= 12):
        return None
    mer = meridiano.strip().lower().replace(".", "").replace(" ", "")
    if mer == "pm":
        if h != 12:
            h += 12
    elif mer == "am":
        if h == 12:
            h = 0
    else:
        return None
    return f"{h:02d}:{m:02d}"


def _duracion_texto_a_minutos(texto):
    """Convierte '6 Hrs. 7 Mins. 37 Segs.' o '10 hrs, 5 mins, 25 segs.'
    a minutos. Devuelve None si no se puede parsear."""
    if not texto:
        return None
    t = str(texto).lower()
    h = re.search(r"(\d+)\s*h", t)
    m = re.search(r"(\d+)\s*m", t)
    if not h and not m:
        return None
    horas = int(h.group(1)) if h else 0
    mins = int(m.group(1)) if m else 0
    return horas * 60 + mins


def _fecha_iso(cruda: str, respaldo: str):
    # La app de Telcel siempre muestra dd/mm/aa. Se arma aqui en vez de
    # confiar en la conversion del modelo, que con dias menores a 13
    # puede invertir dia y mes.
    if cruda:
        texto = str(cruda).strip().replace("-", "/").replace(".", "/")
        partes = [p for p in texto.split("/") if p]
        if len(partes) == 3:
            try:
                d, m, a = (int(p) for p in partes)
            except ValueError:
                d = m = a = 0
            if 1 <= d <= 31 and 1 <= m <= 12:
                if a < 100:
                    a += 2000
                if 2000 <= a <= 2100:
                    return f"{a:04d}-{m:02d}-{d:02d}"
    return respaldo


def _normalizar(datos: dict) -> dict:
    if not datos.get("legible"):
        return datos

    datos["fecha"] = _fecha_iso(datos.get("fecha_cruda"), datos.get("fecha"))

    formato = datos.get("formato_hora")
    entrada = _a_24h(datos.get("entrada_hora"), datos.get("entrada_meridiano"), formato)
    salida = _a_24h(datos.get("salida_hora"), datos.get("salida_meridiano"), formato)

    datos["hora_entrada"] = entrada
    datos["hora_salida"] = salida

    datos["duracion_texto_minutos"] = _duracion_texto_a_minutos(
        datos.get("duracion_texto")
    )

    # Sin correccion por medianoche: una diferencia negativa es la senal de que
    # la lectura vino invertida y debe llegar asi al router.
    if entrada and salida:
        he, me = map(int, entrada.split(":"))
        hs, ms = map(int, salida.split(":"))
        datos["duracion_calculada"] = (hs * 60 + ms) - (he * 60 + me)
    else:
        datos["duracion_calculada"] = None

    # La duracion final ya no se decide aqui, se resuelve en el router.
    datos["duracion_minutos"] = None

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

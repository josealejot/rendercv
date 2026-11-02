"""Núcleo sin interfaz de RenderCV Studio.

Todo lo que toca archivos de clientes pasa por aquí para garantizar tres cosas:

1. Nada inválido llega al disco: se valida con RenderCV antes de escribir.
2. Nada se pierde: cada escritura deja una versión en ``<cliente>/historial/``.
3. Los campos que el editor no conoce se conservan: el YAML se edita en sitio con
   el modo round-trip de ruamel, nunca se regenera desde cero.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

SCHEMA_HEADER = (
    "# yaml-language-server: $schema=https://raw.githubusercontent.com/"
    "rendercv/rendercv/refs/tags/v2.8/schema.json\n"
)
SUFIJOS_GENERADOS = {".pdf", ".png", ".html", ".md", ".typ"}
MAX_VERSIONES = 30
PREFIJO_BORRADOR = "borrador_"
UMBRAL_RECORTE = 40
CARPETA_HISTORIAL = "historial"
CARPETA_SALIDA = "rendercv_output"
TIMEOUT_RENDER_S = 180

REDES_DISPONIBLES = [
    "LinkedIn", "GitHub", "GitLab", "IMDB", "Instagram", "ORCID", "Mastodon",
    "StackOverflow", "ResearchGate", "YouTube", "Google Scholar", "Telegram",
    "WhatsApp", "Leetcode", "X", "Bluesky", "Reddit",
]

FUENTES_DISPONIBLES = [
    "DejaVu Sans Mono", "EB Garamond", "Fontin", "Gentium Book Plus", "Lato",
    "Libertinus Serif", "Mukta", "New Computer Modern", "Noto Sans", "Open Sans",
    "Open Sauce Sans", "Poppins", "Raleway", "Roboto", "Source Sans 3", "Ubuntu",
    "XCharter",
]

# Tipos de entrada de RenderCV. El orden de "campos" es el que muestra el formulario.
TIPOS_ENTRADA: dict[str, dict[str, Any]] = {
    "experiencia": {
        "nombre": "Experiencia laboral",
        "campos": ["position", "company", "location", "start_date", "end_date", "summary", "highlights"],
        "clave": "company",
        "titulo": ("position", "company"),
        "seccion_sugerida": "Experiencia Laboral",
    },
    "educacion": {
        "nombre": "Educación",
        "campos": ["institution", "area", "degree", "location", "start_date", "end_date", "summary", "highlights"],
        "clave": "institution",
        "titulo": ("area", "institution"),
        "seccion_sugerida": "Educación",
    },
    "normal": {
        "nombre": "Proyecto / logro con fechas",
        "campos": ["name", "location", "start_date", "end_date", "date", "summary", "highlights"],
        "clave": "name",
        "titulo": ("name",),
        "seccion_sugerida": "Proyectos Destacados",
    },
    "habilidad": {
        "nombre": "Habilidad (categoría y detalle)",
        "campos": ["label", "details"],
        "clave": "label",
        "titulo": ("label",),
        "seccion_sugerida": "Habilidades",
    },
    "viñeta": {
        "nombre": "Viñeta simple",
        "campos": ["bullet"],
        "clave": "bullet",
        "titulo": ("bullet",),
        "seccion_sugerida": "Certificaciones",
    },
    "texto": {
        "nombre": "Párrafo de texto",
        "campos": [],
        "clave": None,
        "titulo": (),
        "seccion_sugerida": "Perfil Profesional",
    },
    "publicacion": {
        "nombre": "Publicación",
        "campos": ["title", "authors", "journal", "date", "doi", "url", "summary"],
        "clave": "title",
        "titulo": ("title",),
        "seccion_sugerida": "Publicaciones",
    },
    "numerada": {
        "nombre": "Lista numerada",
        "campos": ["number"],
        "clave": "number",
        "titulo": ("number",),
        "seccion_sugerida": "Lista",
    },
    "numerada_inversa": {
        "nombre": "Lista numerada inversa",
        "campos": ["reversed_number"],
        "clave": "reversed_number",
        "titulo": ("reversed_number",),
        "seccion_sugerida": "Lista",
    },
}

ETIQUETAS_CAMPO = {
    "name": "Nombre",
    "headline": "Título profesional",
    "location": "Ciudad y país",
    "email": "Correo",
    "phone": "Teléfono",
    "website": "Sitio web",
    "photo": "Foto",
    "username": "Usuario",
    "network": "Red social",
    "position": "Cargo",
    "company": "Empresa",
    "institution": "Institución",
    "area": "Carrera o programa",
    "degree": "Título obtenido",
    "start_date": "Fecha de inicio",
    "end_date": "Fecha de fin",
    "date": "Fecha",
    "summary": "Resumen",
    "highlights": "Logros",
    "label": "Categoría",
    "details": "Detalle",
    "bullet": "Texto",
    "title": "Título",
    "authors": "Autores",
    "journal": "Revista o medio",
    "doi": "DOI",
    "url": "URL",
    "number": "Texto",
    "reversed_number": "Texto",
}

CAMPOS_FECHA = {"start_date", "end_date"}
CAMPOS_LISTA = {"highlights", "authors"}

# Textos que delatan datos de ejemplo o sin revisar y nunca deberían llegar al cliente.
DATOS_DE_EJEMPLO = [
    "[REVISAR]", "juan.perez@email.com", "juanperez", "juan pérez", "+57 300 123 4567",
    "TechNova Solutions", "Finanzas Digitales LATAM", "InnovaSoft", "CloudCostGuard",
    "DocuSmart", "cliente@email.com", "Empresa Principal", "Universidad / Institución",
    "Cargo Desempeñado", "Profesional Especialista",
]


# ---------------------------------------------------------------------------
# Nombres de clientes y archivos
# ---------------------------------------------------------------------------

def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def slugify(texto: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", "_", _sin_acentos(texto).lower().strip())
    return limpio.strip("_") or "cliente"


def nombre_archivo_yaml(nombre: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "", _sin_acentos(nombre.strip()).replace(" ", "_"))
    return f"{base or 'Cliente'}_CV.yaml"


def reservar_carpeta_cliente(clientes_dir: Path, nombre: str) -> Path:
    """Crea una carpeta nueva; jamás reutiliza la de otro cliente con el mismo nombre."""
    clientes_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(nombre)
    candidata = clientes_dir / slug
    n = 2
    while True:
        try:
            candidata.mkdir(exist_ok=False)
            return candidata
        except FileExistsError:
            candidata = clientes_dir / f"{slug}_{n}"
            n += 1


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def cargar_yaml(texto: str) -> CommentedMap:
    doc = _yaml().load(texto)
    if not isinstance(doc, dict):
        raise ValueError("El archivo no contiene un documento de hoja de vida.")
    if not isinstance(doc.get("cv"), dict):
        raise ValueError("Falta el bloque 'cv' con los datos de la persona.")
    return doc


def volcar_yaml(doc: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def a_plano(valor: Any) -> Any:
    """Convierte a tipos básicos para comparar contenido sin importar el formato.

    Los mapas pasan a lista de pares porque el orden importa: es el orden de las
    secciones en el PDF, y dos dict con distinto orden se consideran iguales.
    """
    if isinstance(valor, dict):
        return [(str(k), a_plano(v)) for k, v in valor.items()]
    if isinstance(valor, (list, tuple)):
        return [a_plano(v) for v in valor]
    if isinstance(valor, str):
        return str(valor)
    return valor


def documento_a_yaml(datos: dict) -> str:
    """Serializa un diccionario nuevo con la cabecera de esquema; escapa todo lo necesario."""
    return SCHEMA_HEADER + volcar_yaml(datos)


def limpiar_nombre(nombre: str) -> str:
    """RenderCV usa el nombre como nombre de archivo: Windows no admite estos caracteres."""
    return re.sub(r"\s+", " ", re.sub(r'[:*?"<>|/\\]', " ", str(nombre))).strip()


def documento_en_blanco(nombre: str, tema: str = "classic", idioma: str = "spanish") -> dict:
    nombre = limpiar_nombre(nombre)
    return {
        "cv": {"name": nombre},
        "design": {
            "theme": tema,
            "page": {
                "size": "a4",
                "top_margin": "0.6in",
                "bottom_margin": "0.6in",
                "left_margin": "0.6in",
                "right_margin": "0.6in",
                "show_footer": True,
                "show_top_note": False,
            },
            "sections": {"show_time_spans_in": ["Experiencia Laboral"]},
            # El valor por defecto (1 cm) parte «Magíster» o «Especialización» en dos líneas.
            "entries": {"degree_width": "2.8cm"},
        },
        "locale": {"language": idioma},
        "settings": {
            "current_date": "today",
            "render_command": {"output_folder": CARPETA_SALIDA},
            "bold_keywords": [],
            "pdf_title": f"{nombre} - Hoja de Vida",
        },
    }


def yaml_desde_plantilla(texto_plantilla: str, nombre: str, tema: str) -> str:
    """Rellena la plantilla por estructura para que nombres con ':' o '#' no rompan el YAML."""
    nombre = limpiar_nombre(nombre)
    doc = cargar_yaml(texto_plantilla)
    doc["cv"]["name"] = nombre
    doc.setdefault("design", CommentedMap())["theme"] = tema
    doc.setdefault("settings", CommentedMap())["pdf_title"] = f"{nombre} - Hoja de Vida"
    return volcar_yaml(doc)


# ---------------------------------------------------------------------------
# Normalización de lo que escribe una persona
# ---------------------------------------------------------------------------

_MESES = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1,
    "feb": 2, "febrero": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6, "june": 6,
    "jul": 7, "julio": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9, "september": 9,
    "oct": 10, "octubre": 10, "october": 10,
    "nov": 11, "noviembre": 11, "november": 11,
    "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
}
_PRESENTE = {"present", "presente", "actual", "actualmente", "hoy", "a la fecha", "vigente", "en curso", "current"}


def normalizar_fecha(texto: Any) -> str:
    """Acepta formas comunes (03/2022, marzo de 2022, actual) y devuelve el formato de RenderCV.

    Si no reconoce el texto lo deja igual, para que el validador explique el problema.
    """
    t = str(texto if texto is not None else "").strip()
    if not t:
        return ""
    bajo = _sin_acentos(t).lower().strip(" .")
    if bajo in _PRESENTE:
        return "present"
    if re.fullmatch(r"\d{4}", bajo):
        return bajo
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", bajo):
        if 1 <= int(m[2]) <= 12:
            return f"{m[1]}-{int(m[2]):02d}"
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", bajo):
        if 1 <= int(m[1]) <= 12:
            return f"{m[2]}-{int(m[1]):02d}"
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", bajo):
        if 1 <= int(m[2]) <= 12 and 1 <= int(m[3]) <= 31:
            return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", bajo):
        if 1 <= int(m[2]) <= 12 and 1 <= int(m[1]) <= 31:
            return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
    if m := re.fullmatch(r"([a-z]+)\.?(?:\s+de)?\s+(\d{4})", bajo):
        if m[1] in _MESES:
            return f"{m[2]}-{_MESES[m[1]]:02d}"
    return t


def normalizar_telefono(texto: Any, region: str = "CO") -> str:
    """Convierte 3001234567 en +57 300 1234567; si no lo reconoce lo deja igual."""
    t = str(texto if texto is not None else "").strip()
    if not t:
        return ""
    try:
        import phonenumbers

        numero = phonenumbers.parse(t, region)
        if phonenumbers.is_valid_number(numero):
            return phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        pass
    return t


def normalizar_web(texto: Any) -> str:
    t = str(texto if texto is not None else "").strip()
    if t and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t) and re.match(r"^[\w-]+(\.[\w-]+)+", t) and "@" not in t:
        return "https://" + t
    return t


def normalizar_usuario_red(texto: Any) -> str:
    """Si pegan la URL completa del perfil, se queda con el usuario."""
    t = str(texto if texto is not None else "").strip()
    if m := re.match(r"^(?:https?://)?(?:www\.)?[\w.-]+\.[a-z]{2,}/(?:in/|u/|user/)?([^/?#\s]+)/?(?:[?#].*)?$", t, re.IGNORECASE):
        return m[1]
    return t


def neutralizar_typst(texto: str) -> str:
    """Evita que un hashtag pegado en un texto se ejecute como comando de Typst.

    RenderCV deja pasar `#palabra` tal cual a Typst: «#tag» rompe la compilación con
    «unknown variable». Un carácter invisible (word joiner) tras el # hace que RenderCV
    lo escape; en el PDF se sigue viendo «#tag».
    """
    # El destino de un enlace markdown se respeta: un carácter invisible rompería el ancla.
    return re.sub(
        r"(\]\([^)]*\))|#(?=[A-Za-z])",
        lambda m: m.group(1) or "#⁠",
        texto,
    )


def neutralizar_datos(valor: Any) -> Any:
    """Aplica neutralizar_typst a todos los textos de una estructura recién creada."""
    if isinstance(valor, dict):
        return {k: neutralizar_datos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [neutralizar_datos(v) for v in valor]
    return neutralizar_typst(valor) if isinstance(valor, str) else valor


def lineas_a_lista(texto: str) -> list[str]:
    """Una línea por elemento; las líneas sangradas siguen siendo sub-viñetas del anterior."""
    items: list[str] = []
    for linea in str(texto).splitlines():
        if not linea.strip():
            continue
        if linea[:2] == "  " and items:
            items[-1] += "\n" + linea.rstrip()
            continue
        items.append(re.sub(r"^\s*[-•*·]\s+", "", linea).strip())
    return items


def lista_a_lineas(valor: Any) -> str:
    if not valor:
        return ""
    if isinstance(valor, (list, tuple)):
        return "\n".join(str(v) for v in valor)
    return str(valor)


# ---------------------------------------------------------------------------
# Modelo editable
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def detectar_tipo(entrada: Any) -> str:
    if isinstance(entrada, dict):
        for tipo, info in TIPOS_ENTRADA.items():
            if info["clave"] and info["clave"] in entrada:
                return tipo
        return "desconocido"
    return "texto"


def construir_modelo(doc: CommentedMap) -> dict:
    cv = doc["cv"]
    if not isinstance(cv.get("sections") or {}, dict):
        raise ValueError("El bloque 'sections' debe contener secciones con título.")
    redes_crudas = cv.get("social_networks") or []
    if not isinstance(redes_crudas, list) or not all(isinstance(r, dict) for r in redes_crudas):
        raise ValueError("El bloque 'social_networks' debe ser una lista con red y usuario.")
    secciones = []
    for titulo, entradas in (cv.get("sections") or {}).items():
        lista = entradas if isinstance(entradas, list) else ([entradas] if entradas is not None else [])
        tipo = detectar_tipo(lista[0]) if lista else "texto"
        secciones.append({
            "uid": _uid(),
            "titulo": str(titulo),
            "titulo_original": str(titulo),
            "tipo": tipo,
            "vacia_original": not lista,
            "entradas": [{"uid": _uid(), "valor": e} for e in lista],
        })
    redes = [{"uid": _uid(), "valor": r} for r in redes_crudas]
    return {"doc": doc, "secciones": secciones, "redes": redes}


def nueva_seccion(tipo: str, titulo: str = "") -> dict:
    return {
        "uid": _uid(),
        "titulo": titulo or TIPOS_ENTRADA[tipo]["seccion_sugerida"],
        "titulo_original": None,
        "tipo": tipo,
        "entradas": [],
    }


def nueva_entrada(tipo: str) -> dict:
    return {"uid": _uid(), "valor": "" if tipo == "texto" else CommentedMap()}


def nueva_red(red: str = "LinkedIn") -> dict:
    valor = CommentedMap()
    valor["network"] = red
    valor["username"] = ""
    return {"uid": _uid(), "valor": valor}


def mover(lista: list, uid: str, delta: int) -> None:
    for i, item in enumerate(lista):
        if item["uid"] == uid:
            j = i + delta
            if 0 <= j < len(lista):
                lista[i], lista[j] = lista[j], lista[i]
            return


def eliminar(lista: list, uid: str) -> None:
    lista[:] = [item for item in lista if item["uid"] != uid]


def _esta_vacio(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, (list, tuple, dict)):
        return len(valor) == 0
    return False


def entrada_vacia(valor: Any) -> bool:
    if isinstance(valor, dict):
        return all(_esta_vacio(v) for v in valor.values())
    return _esta_vacio(valor)


def titulo_entrada(tipo: str, valor: Any) -> str:
    if tipo == "texto":
        texto = str(valor or "").strip()
    elif isinstance(valor, dict):
        partes = [str(valor.get(c) or "").strip() for c in TIPOS_ENTRADA.get(tipo, {}).get("titulo", ())]
        texto = " · ".join(p for p in partes if p)
    else:
        texto = str(valor or "")
    texto = texto.replace("**", "").replace("\n", " ")
    return (texto[:77] + "…" if len(texto) > 78 else texto) or "(sin completar)"


def fijar_campo(mapa: dict, campo: str, texto: Any) -> None:
    """Escribe un campo de formulario sin alterar el valor si en realidad no cambió."""
    if campo in CAMPOS_LISTA:
        nueva = lineas_a_lista(texto or "")
        viejas = lineas_a_lista(lista_a_lineas(mapa.get(campo)))
        if viejas == nueva:
            return
        if nueva:
            # Solo se neutraliza lo que cambió: una línea intacta puede usar Typst a propósito.
            mapa[campo] = CommentedSeq([n if n in viejas else neutralizar_typst(n) for n in nueva])
        else:
            mapa.pop(campo, None)
        return
    limpio = normalizar_fecha(texto) if campo in CAMPOS_FECHA else str(texto if texto is not None else "").strip()
    if not limpio:
        mapa.pop(campo, None)
    elif str(mapa.get(campo, "")).strip() != limpio:
        mapa[campo] = limpio if campo in CAMPOS_FECHA | {"url", "doi"} else neutralizar_typst(limpio)


def texto_contacto(valor: Any) -> str:
    return ", ".join(str(v) for v in valor) if isinstance(valor, (list, tuple)) else str(valor or "")


def fijar_contacto(cv: dict, campo: str, texto: Any) -> None:
    """Contacto admite listas en RenderCV: 'a@x.com, b@x.com' se conserva como lista."""
    bruto = str(texto if texto is not None else "").strip()
    normaliza = {"phone": normalizar_telefono, "website": normalizar_web, "name": limpiar_nombre}.get(campo, lambda v: v)
    if texto_contacto(cv.get(campo)).strip() == bruto:
        return
    if campo in {"email", "phone", "website"} and "," in bruto:
        partes = [normaliza(p.strip()) for p in bruto.split(",") if p.strip()]
        if len(partes) > 1:
            cv[campo] = CommentedSeq(partes)
            return
        bruto = partes[0] if partes else ""
    limpio = normaliza(bruto)
    if limpio:
        cv[campo] = neutralizar_typst(limpio) if campo in {"name", "headline", "location"} else limpio
    else:
        cv.pop(campo, None)


def errores_modelo(modelo: dict) -> list[str]:
    errores = []
    vistos: set[str] = set()
    for s in modelo["secciones"]:
        tiene_datos = any(not entrada_vacia(e["valor"]) for e in s["entradas"])
        titulo = s["titulo"].strip()
        if not titulo and tiene_datos:
            errores.append("Hay una sección con contenido pero sin título.")
        clave = titulo.casefold()
        if clave and clave in vistos:
            errores.append(f"Hay dos secciones llamadas «{titulo}». Cambia el título de una.")
        vistos.add(clave)
    return errores


def _mismos_elementos(lista: Any, elementos: list) -> bool:
    if not elementos and not lista:
        return True
    return (
        isinstance(lista, list)
        and len(lista) == len(elementos)
        and all(a is b for a, b in zip(lista, elementos))
    )


def sincronizar_doc(modelo: dict) -> None:
    """Vuelca secciones y redes al documento. Omite lo que sigue totalmente vacío."""
    doc = modelo["doc"]
    cv = doc["cv"]

    previas = cv.get("sections")
    previas = previas if isinstance(previas, dict) else {}
    pares: list[tuple[str, Any]] = []
    renombres: dict[str, str] = {}
    for s in modelo["secciones"]:
        titulo = s["titulo"].strip()
        original = s["titulo_original"]
        if original and titulo and original != titulo:
            renombres[original] = titulo
        entradas = [e["valor"] for e in s["entradas"] if not entrada_vacia(e["valor"])]
        if titulo and entradas:
            # Reutilizar la lista existente conserva sus comentarios.
            existente = previas.get(original) if original else None
            pares.append((titulo, existente if _mismos_elementos(existente, entradas) else CommentedSeq(entradas)))
        elif titulo and original and s.get("vacia_original"):
            pares.append((titulo, previas.get(original)))

    if [str(k) for k in previas] == [t for t, _ in pares]:
        for titulo, lista in pares:
            if previas[titulo] is not lista:
                previas[titulo] = lista
    elif pares:
        nuevas = CommentedMap()
        for titulo, lista in pares:
            nuevas[titulo] = lista
        cv["sections"] = nuevas
    else:
        cv.pop("sections", None)

    redes = [r["valor"] for r in modelo["redes"] if str(r["valor"].get("username", "")).strip()]
    if not _mismos_elementos(cv.get("social_networks"), redes):
        if redes:
            cv["social_networks"] = CommentedSeq(redes)
        else:
            cv.pop("social_networks", None)

    # Un renombre no debe romper los ajustes de diseño que apuntan a la sección por nombre.
    if renombres:
        diseno_secciones = (doc.get("design") or {}).get("sections") or {}
        spans = diseno_secciones.get("show_time_spans_in")
        if isinstance(spans, list):
            spans[:] = [renombres.get(str(t), t) for t in spans]
        for s in modelo["secciones"]:
            if s["titulo"].strip() in renombres.values():
                s["titulo_original"] = s["titulo"].strip()


def obtener_ruta(doc: dict, ruta: tuple[str, ...], defecto: Any = None) -> Any:
    actual: Any = doc
    for parte in ruta:
        if not isinstance(actual, dict) or parte not in actual:
            return defecto
        actual = actual[parte]
    return actual


def fijar_ruta(doc: dict, ruta: tuple[str, ...], valor: Any) -> None:
    """valor=None elimina la clave y limpia los padres que queden vacíos."""
    if valor is None:
        padres = [doc]
        for parte in ruta[:-1]:
            siguiente = padres[-1].get(parte) if isinstance(padres[-1], dict) else None
            if not isinstance(siguiente, dict):
                return
            padres.append(siguiente)
        padres[-1].pop(ruta[-1], None)
        for i in range(len(padres) - 1, 0, -1):
            if not padres[i]:
                padres[i - 1].pop(ruta[i - 1], None)
        return
    actual = doc
    for parte in ruta[:-1]:
        if not isinstance(actual.get(parte), dict):
            actual[parte] = CommentedMap()
        actual = actual[parte]
    if actual.get(ruta[-1]) != valor:
        actual[ruta[-1]] = valor


def dimension_a_cm(valor: Any, defecto: float = 1.5) -> float:
    m = re.fullmatch(r"\s*([\d.]+)\s*(cm|mm|in|pt)\s*", str(valor or ""))
    if not m:
        return defecto
    factor = {"cm": 1, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72}[m[2]]
    return round(float(m[1]) * factor, 1)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

@dataclass
class ErrorCV:
    ubicacion: str
    mensaje: str

    def __str__(self) -> str:
        return f"{self.ubicacion}: {self.mensaje}" if self.ubicacion else self.mensaje


def _traducir_mensaje(mensaje: str, campo: str) -> str:
    if campo == "email" or "email address" in mensaje or "@-sign" in mensaje:
        return "Correo no válido. Revisa que tenga el formato nombre@dominio.com."
    if "phone number" in mensaje:
        return "Teléfono no válido. Incluye el indicativo del país, por ejemplo +57 300 123 4567."
    if "valid URL" in mensaje:
        return "Dirección no válida. Debe ser una web completa, como https://misitio.com."
    if "valid date" in mensaje:
        return "Fecha no válida. Usa año y mes, como 2022-03, o solo el año."
    if "field is required" in mensaje:
        return "Este campo es obligatorio."
    if "does not exist" in mensaje and campo == "photo":
        return "No se encontró el archivo de la foto."
    if "not a valid YAML" in mensaje:
        return "El texto YAML tiene un error de sintaxis (comillas, sangría o dos puntos)."
    if "cannot be after" in mensaje or "must be" in mensaje and "end_date" in mensaje:
        return "La fecha de inicio no puede ser posterior a la fecha de fin."
    return mensaje


def _ubicacion_legible(loc: tuple[str, ...] | None, linea: int | None) -> str:
    if not loc:
        return f"Línea {linea}" if linea else ""
    partes = list(loc)
    salida = []
    if partes[:2] == ["cv", "sections"]:
        partes = partes[2:]
        if partes:
            salida.append(partes.pop(0))
        if partes and partes[0].isdigit():
            salida.append(f"Entrada {int(partes.pop(0)) + 1}")
    elif partes[:2] == ["cv", "social_networks"]:
        partes = partes[2:]
        salida.append("Redes sociales")
        if partes and partes[0].isdigit():
            salida.append(f"Red {int(partes.pop(0)) + 1}")
    elif partes and partes[0] == "cv":
        partes = partes[1:]
        salida.append("Datos personales")
    elif partes and partes[0] == "design":
        partes = partes[1:]
        salida.append("Diseño")
    salida.extend(ETIQUETAS_CAMPO.get(p, p) for p in partes)
    return " › ".join(salida)


def validar_yaml(texto: str, ruta: Path | None = None) -> list[ErrorCV]:
    """Valida con el propio esquema de RenderCV, sin escribir ni compilar nada."""
    try:
        from rendercv.exception import RenderCVUserValidationError
        from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model
    except ImportError:
        return []  # Otra versión de RenderCV: decidirá el render.

    try:
        build_rendercv_dictionary_and_model(texto, input_file_path=ruta)
    except RenderCVUserValidationError as e:
        crudos = e.validation_errors
        ubicaciones = [v.schema_location for v in crudos if v.schema_location]
        errores = []
        for v in crudos:
            loc = tuple(v.schema_location) if v.schema_location else None
            # El aviso genérico de sección sobra si hay un error concreto dentro de ella.
            if loc and any(tuple(o)[: len(loc)] == loc and len(o) > len(loc) for o in ubicaciones):
                continue
            linea = v.yaml_location[0][0] if v.yaml_location else None
            campo = loc[-1] if loc else ""
            errores.append(ErrorCV(_ubicacion_legible(loc, linea), _traducir_mensaje(v.message, campo)))
        return errores
    except Exception as e:  # RenderCV puede lanzar otros errores con entradas muy atípicas.
        return [ErrorCV("", f"El contenido no se pudo validar ({type(e).__name__}: {e}).")]
    return []


# ---------------------------------------------------------------------------
# Archivos y versiones
# ---------------------------------------------------------------------------

def _reemplazar_con_reintentos(origen: Path, destino: Path, intentos: int = 5) -> None:
    """OneDrive y los antivirus bloquean archivos por instantes; un bloqueo real sí se reporta."""
    for i in range(intentos):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if i == intentos - 1:
                raise
            time.sleep(0.15 * (i + 1))


def leer_texto(ruta: Path) -> str:
    """Lee un YAML en UTF-8; un archivo guardado en Windows-1252 no debe tumbar la app."""
    datos = ruta.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def yamls_cliente(carpeta: Path) -> list[Path]:
    """Primero los *_CV.yaml; siempre en el mismo orden para que la elección sea estable."""
    return sorted(carpeta.glob("*.yaml"), key=lambda p: (not p.name.endswith("_CV.yaml"), p.name.casefold()))


def fijar_nombre_yaml(texto: str, nombre: str) -> str:
    """Impone el nombre indicado por el usuario. Si el YAML no se puede leer lo deja igual."""
    limpio = limpiar_nombre(nombre)
    try:
        doc = cargar_yaml(texto)
    except Exception:
        return texto
    doc["cv"]["name"] = neutralizar_typst(limpio)
    doc.setdefault("settings", CommentedMap())["pdf_title"] = f"{limpio} - Hoja de Vida"
    return volcar_yaml(doc)


def causa_error(log: str) -> str:
    return next((l.strip() for l in reversed(log.splitlines()) if "Error" in l), "")


def escribir_atomico(ruta: Path, texto: str) -> None:
    temporal = ruta.with_name(f".{ruta.name}.{_uid()}.tmp")
    try:
        temporal.write_text(texto, encoding="utf-8", newline="\n")
        _reemplazar_con_reintentos(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def listar_versiones(ruta_yaml: Path) -> list[Path]:
    carpeta = ruta_yaml.parent / CARPETA_HISTORIAL
    if not carpeta.exists():
        return []
    # Cada versión lleva el nombre de su archivo: si una carpeta tiene varios YAML no se mezclan.
    patron = re.compile(r"\d{8}-\d{6}-\d{6}_(?:" + PREFIJO_BORRADOR + r")?" + re.escape(ruta_yaml.name))
    return sorted((p for p in carpeta.glob("*.yaml") if patron.fullmatch(p.name)), key=lambda p: p.name, reverse=True)


def guardar_texto_version(ruta_yaml: Path, texto: str) -> Path:
    """Rescata en el historial un borrador sin guardar, aunque todavía no sea válido."""
    carpeta = ruta_yaml.parent / CARPETA_HISTORIAL
    carpeta.mkdir(exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destino = carpeta / f"{sello}_{PREFIJO_BORRADOR}{ruta_yaml.name}"
    destino.write_text(texto, encoding="utf-8", newline="\n")
    return destino


def guardar_version(ruta_yaml: Path, intervalo_minimo_s: float = 0) -> Path | None:
    """Copia el archivo actual al historial. Con autoguardado, el intervalo evita una versión por tecla."""
    if not ruta_yaml.exists():
        return None
    versiones = [v for v in listar_versiones(ruta_yaml) if PREFIJO_BORRADOR not in v.name]
    if versiones:
        if versiones[0].read_bytes() == ruta_yaml.read_bytes():
            return versiones[0]
        if intervalo_minimo_s and time.time() - versiones[0].stat().st_mtime < intervalo_minimo_s:
            return versiones[0]
    carpeta = ruta_yaml.parent / CARPETA_HISTORIAL
    carpeta.mkdir(exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destino = carpeta / f"{sello}_{ruta_yaml.name}"
    shutil.copy2(ruta_yaml, destino)
    os.utime(destino)
    for vieja in listar_versiones(ruta_yaml)[MAX_VERSIONES:]:
        vieja.unlink(missing_ok=True)
    return destino


def etiqueta_version(ruta: Path) -> str:
    try:
        fecha = datetime.strptime(ruta.name[:15], "%Y%m%d-%H%M%S").strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return ruta.name
    return f"{fecha} (borrador sin guardar)" if PREFIJO_BORRADOR in ruta.name else fecha


def guardar_foto(carpeta: Path, contenido: bytes) -> str:
    """Guarda la foto solo si de verdad es una imagen. Devuelve el nombre relativo al YAML."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(contenido)) as img:
            img.verify()
            formato = (img.format or "").upper()
    except Exception as e:
        raise ValueError("El archivo no es una imagen válida.") from e
    extension = {"JPEG": "jpg", "PNG": "png"}.get(formato)
    if not extension:
        raise ValueError("Usa una foto en formato JPG o PNG.")
    # Nombre por contenido: una foto nueva nunca reemplaza la que usan las versiones anteriores.
    nombre = f"foto_{hashlib.sha256(contenido).hexdigest()[:12]}.{extension}"
    if (carpeta / nombre).exists():
        return nombre
    temporal = carpeta / f".{nombre}.{_uid()}.tmp"
    try:
        temporal.write_bytes(contenido)
        _reemplazar_con_reintentos(temporal, carpeta / nombre)
    finally:
        temporal.unlink(missing_ok=True)
    return nombre


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

@dataclass
class ResultadoRender:
    ok: bool
    log: str = ""
    pdf: Path | None = None
    pngs: list[Path] = field(default_factory=list)
    errores: list[ErrorCV] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def archivos_salida(carpeta_cliente: Path) -> tuple[Path | None, list[Path]]:
    salida = carpeta_cliente / CARPETA_SALIDA
    if not salida.exists():
        return None, []
    pdfs = sorted(salida.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    pngs = sorted(salida.glob("*.png"), key=lambda p: _orden_pagina(p.name))
    return (pdfs[0] if pdfs else None), pngs


def _orden_pagina(nombre: str) -> tuple[str, int]:
    m = re.match(r"^(.*)_(\d+)\.png$", nombre)
    return (m[1], int(m[2])) if m else (nombre, 0)


def _publicar_salida(temporal: Path, salida: Path) -> list[str]:
    """Pasa lo recién generado a la carpeta final y borra lo que ya no corresponde,
    como las páginas de un nombre anterior o de una versión más larga del CV."""
    salida.mkdir(parents=True, exist_ok=True)
    avisos = []
    nuevos = {p.name for p in temporal.iterdir() if p.is_file()}
    for archivo in temporal.iterdir():
        if not archivo.is_file():
            continue
        intermedio = salida / f".{archivo.name}.{_uid()}.tmp"
        try:
            shutil.copy2(archivo, intermedio)
            _reemplazar_con_reintentos(intermedio, salida / archivo.name)
        except PermissionError:
            avisos.append(
                f"«{archivo.name}» está abierto en otro programa y no se pudo actualizar. "
                "Ciérralo y vuelve a guardar."
            )
        finally:
            intermedio.unlink(missing_ok=True)
    for viejo in salida.iterdir():
        if viejo.is_file() and viejo.suffix.lower() in SUFIJOS_GENERADOS and viejo.name not in nuevos:
            try:
                viejo.unlink()
            except PermissionError:
                avisos.append(f"«{viejo.name}» es de una versión anterior, pero está abierto y no se pudo borrar.")
    return avisos


def renderizar(ruta_yaml: Path, tema_override: str | None = None) -> ResultadoRender:
    """Compila en una carpeta temporal: si algo falla, el último PDF bueno sigue intacto."""
    temporal = Path(tempfile.mkdtemp(prefix="rendercv_"))
    try:
        cmd = [sys.executable, "-m", "rendercv", "render", str(ruta_yaml), "--output-folder", str(temporal)]
        if tema_override:
            cmd.extend(["--design.theme", tema_override])
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ruta_yaml.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONUTF8": "1"},
                timeout=TIMEOUT_RENDER_S,
            )
        except subprocess.TimeoutExpired:
            return ResultadoRender(False, f"RenderCV no terminó en {TIMEOUT_RENDER_S} segundos.")
        log = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
        if proc.returncode != 0 or not any(temporal.glob("*.pdf")):
            return ResultadoRender(False, log)
        avisos = _publicar_salida(temporal, ruta_yaml.parent / CARPETA_SALIDA)
        pdf, pngs = archivos_salida(ruta_yaml.parent)
        return ResultadoRender(True, log, pdf, pngs, avisos=avisos)
    finally:
        shutil.rmtree(temporal, ignore_errors=True)


def guardar_y_renderizar(ruta_yaml: Path, texto: str, intervalo_version_s: float = 0) -> ResultadoRender:
    """Único camino de escritura: valida, respalda, escribe y compila.

    Si la compilación falla, se restaura el contenido anterior: en disco siempre queda
    un CV que compila.
    """
    errores = validar_yaml(texto, ruta_yaml)
    if errores:
        return ResultadoRender(False, "\n".join(str(e) for e in errores), errores=errores)

    try:
        previo = leer_texto(ruta_yaml) if ruta_yaml.exists() else None
        # Un recorte de contenido siempre deja versión: es lo que no se puede volver a escribir.
        recorta = previo is not None and len(texto) < len(previo) - UMBRAL_RECORTE
        guardar_version(ruta_yaml, 0 if recorta else intervalo_version_s)
        escribir_atomico(ruta_yaml, texto)
    except OSError as e:
        mensaje = "No se pudo guardar: otro programa (editor u OneDrive) tiene el archivo bloqueado. Inténtalo de nuevo."
        return ResultadoRender(False, str(e), errores=[ErrorCV("", mensaje)])
    resultado = renderizar(ruta_yaml)
    if not resultado.ok:
        if previo is not None:
            escribir_atomico(ruta_yaml, previo)
        detalle = causa_error(resultado.log)
        mensaje = "RenderCV no pudo compilar este contenido. Se conservó la versión anterior."
        resultado.errores = [ErrorCV("", f"{mensaje} Causa: {detalle}" if detalle else mensaje)]
    return resultado


# ---------------------------------------------------------------------------
# Revisión antes de entregar
# ---------------------------------------------------------------------------

def _textos(valor: Any):
    if isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            yield from _textos(v)
    elif valor is not None:
        yield str(valor)


def _fecha_comparable(valor: Any) -> str | None:
    t = str(valor or "").strip().lower()
    if t == "present":
        return "9999"
    return t if re.match(r"^\d{4}", t) else None


def revisar_entrega(doc: dict, paginas: int = 0) -> list[dict]:
    """Lista de comprobaciones: nivel 'bloqueante', 'mejora' u 'ok', sin impedir el guardado."""
    cv = doc.get("cv") or {}
    secciones = cv.get("sections") or {}
    salida: list[dict] = []

    def agregar(nivel: str, texto: str) -> None:
        salida.append({"nivel": nivel, "texto": texto})

    corpus = "\n".join(_textos(cv)).casefold()
    restos = [p for p in DATOS_DE_EJEMPLO if p.casefold() in corpus]
    # Si el cliente real se llama igual que un dato de ejemplo, no es un resto de plantilla.
    nombre = str(cv.get("name", "")).casefold()
    restos = [p for p in restos if p.casefold() not in nombre]
    if restos:
        muestra = ", ".join(f"«{r}»" for r in restos[:4])
        agregar("bloqueante", f"Quedan datos de ejemplo o sin revisar: {muestra}.")
    else:
        agregar("ok", "No quedan datos de ejemplo.")

    faltantes = [ETIQUETAS_CAMPO[c].lower() for c in ("email", "phone", "location") if not cv.get(c)]
    if not cv.get("name"):
        faltantes.insert(0, "nombre")
    if faltantes:
        agregar("bloqueante", "Faltan datos de contacto: " + ", ".join(faltantes) + ".")
    else:
        agregar("ok", "Datos de contacto completos.")

    tipos = {t: [] for t in ("experiencia", "educacion", "texto")}
    for entradas in secciones.values():
        for e in entradas or []:
            t = detectar_tipo(e)
            if t in tipos:
                tipos[t].append(e)

    if tipos["texto"]:
        agregar("ok", "Tiene perfil profesional.")
    else:
        agregar("mejora", "Agrega un perfil profesional: es lo primero que leen.")
    if tipos["experiencia"]:
        agregar("ok", f"{len(tipos['experiencia'])} experiencia(s) laboral(es).")
    else:
        agregar("mejora", "No hay experiencia laboral registrada.")
    if tipos["educacion"]:
        agregar("ok", "Tiene educación registrada.")
    else:
        agregar("mejora", "No hay educación registrada.")

    sin_logros, sin_fecha, fechas_mal = [], [], []
    logros: list[str] = []
    for e in tipos["experiencia"]:
        etiqueta = str(e.get("company") or "sin empresa")
        if not e.get("highlights"):
            sin_logros.append(etiqueta)
        logros.extend(str(h) for h in e.get("highlights") or [])
        if not (e.get("start_date") or e.get("date")):
            sin_fecha.append(etiqueta)
    for e in tipos["experiencia"] + tipos["educacion"]:
        ini, fin = _fecha_comparable(e.get("start_date")), _fecha_comparable(e.get("end_date"))
        if ini and fin and ini > fin:
            fechas_mal.append(str(e.get("company") or e.get("institution")))
    if sin_logros:
        agregar("mejora", "Sin logros en: " + ", ".join(sin_logros) + ".")
    if sin_fecha:
        agregar("mejora", "Sin fechas en: " + ", ".join(sin_fecha) + ".")
    if fechas_mal:
        agregar("bloqueante", "El inicio es posterior al fin en: " + ", ".join(fechas_mal) + ".")

    if logros:
        con_cifras = sum(1 for h in logros if re.search(r"\d", h))
        if con_cifras / len(logros) >= 0.5:
            agregar("ok", f"{con_cifras} de {len(logros)} logros incluyen cifras.")
        else:
            agregar("mejora", f"Solo {con_cifras} de {len(logros)} logros incluyen cifras. Lo medible convence más.")
        largos = sum(1 for h in logros if len(h) > 260)
        if largos:
            agregar("mejora", f"{largos} logro(s) muy largos: intenta dejarlos en dos líneas.")

    if paginas > 2:
        agregar("mejora", f"El CV ocupa {paginas} páginas. Lo habitual son una o dos.")
    elif paginas:
        agregar("ok", f"Extensión adecuada ({paginas} página{'s' if paginas != 1 else ''}).")

    titulos_largos = [str(e["degree"]) for e in tipos["educacion"] if len(str(e.get("degree") or "")) > 4]
    if titulos_largos and not obtener_ruta(doc, ("design", "entries", "degree_width")):
        agregar("mejora", f"«{titulos_largos[0]}» puede partirse en dos líneas. Ajusta la columna del título académico en Diseño.")

    if cv.get("photo"):
        agregar("mejora", "Lleva foto: algunos sistemas ATS y empresas internacionales prefieren CV sin foto.")
    return salida


# ---------------------------------------------------------------------------
# Importación local sin IA
# ---------------------------------------------------------------------------

def parser_heuristico_a_yaml(texto: str, tema: str = "classic", idioma: str = "spanish") -> str:
    """Pasa el texto de un CV antiguo a YAML válido sin usar IA.

    Solo escribe datos encontrados en el texto. Lo que no se puede deducir queda marcado
    con [REVISAR], y la revisión de entrega avisa si alguien lo olvida: nunca se inventan
    teléfonos, ciudades ni habilidades.
    """
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    nombre = ""
    for linea in lineas[:6]:
        candidata = re.sub(r"^(nombres?(\s+completos?)?|name)\s*[:\-]\s*", "", linea, flags=re.IGNORECASE)
        if re.match(r"^(curriculum|currículum|hoja de vida|resume|cv)\b", candidata, re.IGNORECASE):
            continue
        if "@" in candidata or re.search(r"\d{3}", candidata):
            continue
        nombre = neutralizar_typst(candidata[:60].strip())
        break
    nombre = nombre or "[REVISAR] Nombre del cliente"

    email_m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+", texto)
    email = email_m.group(0) if email_m else ""

    telefono = ""
    if m := re.search(r"(\+\d{1,3}[\s-]?)?(\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}|\d{10})", texto):
        candidato = normalizar_telefono(m.group(0))
        if candidato.startswith("+"):
            telefono = candidato

    linkedin = re.search(r"linkedin\.com/in/([a-zA-Z0-9_-]+)", texto, re.IGNORECASE)
    github = re.search(r"github\.com/([a-zA-Z0-9_-]+)", texto, re.IGNORECASE)

    puntos = []
    for linea in lineas[1:35]:
        limpia = neutralizar_typst(linea.lstrip("•-*· ").strip())
        if len(limpia) > 20 and "@" not in limpia:
            puntos.append(limpia)

    doc = documento_en_blanco(nombre, tema, idioma)
    cv = doc["cv"]
    if email:
        cv["email"] = email
    if telefono:
        cv["phone"] = telefono
    redes = []
    if linkedin:
        redes.append({"network": "LinkedIn", "username": linkedin.group(1)})
    if github:
        redes.append({"network": "GitHub", "username": github.group(1)})
    if redes:
        cv["social_networks"] = redes

    experiencia = {"company": "[REVISAR] Empresa", "position": "[REVISAR] Cargo"}
    if len(puntos) > 1:
        experiencia["highlights"] = puntos[1:7]
    cv["sections"] = {
        "Perfil Profesional": [puntos[0] if puntos else "[REVISAR] Escribe aquí el perfil profesional."],
        "Experiencia Laboral": [experiencia],
        "Educación": [{"institution": "[REVISAR] Institución", "area": "[REVISAR] Programa"}],
    }
    return documento_a_yaml(doc)

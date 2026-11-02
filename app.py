import os
import re
import io
import sys
import hashlib
import subprocess
from pathlib import Path

import streamlit as st
from ruamel.yaml import YAML
from pypdf import PdfReader
import docx

import cv_core as core
from cv_core import parser_heuristico_a_yaml
from editor_visual import asegurar_previa, mostrar_entregables, mostrar_paginas, render_editor_visual

# Configuración de entorno UTF-8 para Windows y RenderCV
os.environ["PYTHONUTF8"] = "1"

BASE_DIR = Path(__file__).parent.resolve()
CLIENTES_DIR = BASE_DIR / "clientes"
PLANTILLAS_DIR = BASE_DIR / "plantillas"
CATALOGO_DIR = BASE_DIR / "catalogo_temas"

CLIENTES_DIR.mkdir(exist_ok=True)
PLANTILLAS_DIR.mkdir(exist_ok=True)

TEMAS_DISPONIBLES = {
    "classic": "Classic — Equilibrado, limpio y universal",
    "moderncv": "ModernCV — Ejecutivo con barra lateral de fechas",
    "harvard": "Harvard — Académico y corporativo tradicional (100% ATS)",
    "engineeringresumes": "Engineering Resumes — Estándar de oro compacto para Tech/ATS",
    "engineeringclassic": "Engineering Classic — Técnico con acentos de color",
    "sb2nov": "Sb2nov — Clásico de Ingeniería de Software",
    "ember": "Ember — Tipografía cálida y moderna",
    "ink": "Ink — Editorial de alto contraste",
    "opal": "Opal — Minimalista con espaciado amplio",
}

st.set_page_config(
    page_title="RenderCV Studio Pro | Creador de Hojas de Vida ATS",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="auto",
)

# Estilos personalizados
st.markdown(
    """
    <style>
    .main-header {
        background: linear-gradient(90deg, #0f172a 0%, #1e3a8a 100%);
        color: white;
        padding: 0.45rem 1rem;
        border-radius: 8px;
        margin-bottom: 0.25rem;
    }
    .main-header h1 {
        color: white !important;
        margin: 0;
        padding: 0;
        font-size: 1.05rem;
        line-height: 1.4;
    }
    /* Aprovecha toda la ventana: en una laptop el editor debe verse sin bajar */
    [data-testid="stMainBlockContainer"] {
        padding: 2.5rem 1.25rem 2rem 1.25rem;
        max-width: 100%;
    }
    [data-testid="stHeader"] {
        height: 2.5rem;
        background: transparent;
    }
    [data-testid="stSidebarHeader"] {
        height: 2.25rem;
        padding-top: 0.25rem;
        padding-bottom: 0;
    }
    [data-testid="stSidebarUserContent"] {
        padding-top: 0;
    }
    /* Editor y vista previa lado a lado si ambos caben en el espacio real, que crece al
       plegar la barra lateral; si no, uno debajo del otro. */
    [data-testid="stMain"] {
        container-type: inline-size;
    }
    @container (min-width: 700px) {
        [data-testid="stColumn"]:has(.st-key-ve_previa) {
            position: sticky;
            top: 2.5rem;
            align-self: flex-start;
        }
        .st-key-ve_previa {
            max-height: calc(100vh - 3rem);
            overflow-y: auto;
            padding-right: 0.4rem;
        }
    }
    @container (max-width: 699.98px) {
        [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-ve_previa) {
            flex-direction: column;
        }
        [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-ve_previa) > [data-testid="stColumn"] {
            width: 100%;
            flex: 1 1 auto;
        }
    }
    .status-box {
        padding: 0.8rem 1rem;
        border-radius: 8px;
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def extraer_texto_archivo(uploaded_file) -> str:
    nombre = uploaded_file.name.lower()
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    if nombre.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(raw_bytes))
        paginas = []
        for p in reader.pages:
            txt = p.extract_text()
            if txt:
                paginas.append(txt)
        return "\n\n".join(paginas).strip()

    elif nombre.endswith(".docx"):
        doc = docx.Document(io.BytesIO(raw_bytes))
        bloques = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                celdas = [c.text.strip() for c in row.cells if c.text.strip()]
                if celdas:
                    bloques.append(" | ".join(celdas))
        return "\n".join(bloques).strip()

    else:
        return raw_bytes.decode("utf-8", errors="ignore").strip()


def construir_prompt_ia(texto_cv: str, oferta_laboral: str, tema: str, idioma: str) -> str:
    instruccion_oferta = ""
    if oferta_laboral.strip():
        instruccion_oferta = f"""
ADEMÁS, ADAPTA EL CV PARA ESTA OFERTA LABORAL ESPECÍFICA (priorizando palabras clave ATS, perfil profesional y logros relevantes sin inventar experiencia falsa):
--- OFERTA LABORAL ---
{oferta_laboral.strip()}
----------------------
"""

    return f"""Eres un experto redactor de Hojas de Vida (CVs) formato Harvard / ATS y especialista en RenderCV v2.8.
Convierte el siguiente texto de Hoja de Vida de un cliente en un archivo YAML 100% válido para RenderCV v2.8.

REGLAS ESTRICTAS DE FORMATO RENDERCV v2.8:
1. Devuelve ÚNICAMENTE el bloque de código YAML válido (sin explicaciones ni texto adicional antes o después).
2. La primera línea debe ser: `# yaml-language-server: $schema=https://raw.githubusercontent.com/rendercv/rendercv/refs/tags/v2.8/schema.json`
3. En `cv:`, incluye `name`, `headline`, `location`, `email`, `phone` (formato internacional con código de país, ej. `+57 300 123 4567`, o déjalo vacío si no es válido), `website` (URL completa con https:// o elimínalo si no tiene), y `social_networks` (solo si tiene usuario real de LinkedIn o GitHub).
4. En `cv.sections:`, usa exactamente los tipos de entrada soportados por RenderCV:
   - `Perfil Profesional:` lista simple de strings con 1 o 2 párrafos de alto impacto.
   - `Experiencia Laboral:` lista de objetos con `company`, `position`, `start_date` (formato YYYY-MM o YYYY), `end_date` (formato YYYY-MM, YYYY o `present`), `location`, y `highlights` (lista de strings).
   - `Educación:` lista de objetos con `institution`, `area`, `degree`, `start_date`, `end_date`, `location`, `highlights`.
   - `Habilidades:` lista de objetos con `label` y `details`.
   - `Certificaciones:` lista de objetos con `bullet: 'Texto de la certificación (Año)'`.
5. IMPORTANTE EN YAML: Cualquier string dentro de `highlights` o textos que contenga dos puntos (`:`) DEBE ir entre comillas simples `'...'` para evitar errores de sintaxis YAML.
6. Mejora la redacción de los `highlights` usando verbos de acción fuertes e impacto medible (método STAR/Harvard).
7. Usa `design.theme: {tema}` y `locale.language: {idioma}`.
8. En `settings.bold_keywords`, incluye entre 5 y 8 palabras clave técnicas o competencias esenciales del candidato.
{instruccion_oferta}
--- TEXTO DEL CV DEL CLIENTE ---
{texto_cv}
"""


def convertir_con_gemini(api_key: str, texto_cv: str, oferta_laboral: str, tema: str, idioma: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key.strip())
    prompt = construir_prompt_ia(texto_cv, oferta_laboral, tema, idioma)
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        system_instruction="Eres un generador experto de archivos YAML para RenderCV v2.8. Responde únicamente con código YAML puro y válido.",
        input=prompt,
    )
    respuesta = (interaction.output_text or "").strip()
    # Limpiar bloques markdown ```yaml ... ``` si el modelo los incluye
    respuesta = re.sub(r"^```(?:yaml|yml)?\s*\n", "", respuesta, flags=re.IGNORECASE)
    respuesta = re.sub(r"\n```\s*$", "", respuesta)
    return respuesta.strip()


def ejecutar_rendercv(ruta_yaml: Path, tema_override: str = None) -> tuple[bool, str, Path | None, list[Path]]:
    """Ejecuta RenderCV sobre el YAML y devuelve (exito, log, ruta_pdf, rutas_png)."""
    resultado = core.renderizar(ruta_yaml, tema_override)
    return resultado.ok, resultado.log, resultado.pdf, resultado.pngs


def mostrar_errores(resultado: core.ResultadoRender) -> None:
    if resultado.errores:
        st.error("No se guardó el cambio. Revisa esto:\n\n" + "\n".join(f"- {e}" for e in resultado.errores))
    if not resultado.ok and resultado.log and not resultado.errores:
        st.code(resultado.log)
    for aviso in resultado.avisos:
        st.warning(aviso)


def crear_cliente_con_yaml(nombre: str, texto_yaml: str) -> tuple[str, Path]:
    """Crea siempre una carpeta nueva: dos clientes homónimos no se pisan."""
    carpeta = core.reservar_carpeta_cliente(CLIENTES_DIR, nombre)
    ruta = carpeta / core.nombre_archivo_yaml(nombre)
    core.escribir_atomico(ruta, texto_yaml)
    return carpeta.name, ruta


def avisar_y_recargar(mensaje: str) -> None:
    st.session_state["aviso_global"] = mensaje
    st.rerun()


def generar_yaml_desde_formulario(datos: dict) -> str:
    redes = []
    if datos.get("linkedin"):
        redes.append({"network": "LinkedIn", "username": core.normalizar_usuario_red(datos["linkedin"])})
    if datos.get("github"):
        redes.append({"network": "GitHub", "username": core.normalizar_usuario_red(datos["github"])})

    secciones = {}
    if datos.get("perfil"):
        secciones["Perfil Profesional"] = [datos["perfil"].strip()]

    if datos.get("experiencias"):
        secciones["Experiencia Laboral"] = datos["experiencias"]

    if datos.get("educacion"):
        secciones["Educación"] = datos["educacion"]

    if datos.get("proyectos"):
        secciones["Proyectos Destacados"] = datos["proyectos"]

    if datos.get("habilidades"):
        secciones["Habilidades Técnicas"] = datos["habilidades"]

    if datos.get("certificaciones"):
        secciones["Certificaciones y Reconocimientos"] = [{"bullet": c} for c in datos["certificaciones"] if c.strip()]

    secciones = core.neutralizar_datos(secciones)
    nombre_limpio = core.limpiar_nombre(datos["nombre"])
    cv_dict = {"name": core.neutralizar_typst(nombre_limpio)}
    if datos.get("headline"):
        cv_dict["headline"] = core.neutralizar_typst(datos["headline"])
    if datos.get("ubicacion"):
        cv_dict["location"] = core.neutralizar_typst(datos["ubicacion"])
    if datos.get("email"):
        cv_dict["email"] = datos["email"]
    if datos.get("telefono"):
        cv_dict["phone"] = core.normalizar_telefono(datos["telefono"])
    if datos.get("website"):
        cv_dict["website"] = core.normalizar_web(datos["website"])
    if redes:
        cv_dict["social_networks"] = redes
    cv_dict["sections"] = secciones

    doc_yaml = {
        "cv": cv_dict,
        "design": {
            "theme": datos.get("tema", "classic"),
            "page": {
                "size": "a4",
                "top_margin": "0.6in",
                "bottom_margin": "0.6in",
                "left_margin": "0.6in",
                "right_margin": "0.6in",
                "show_footer": True,
                "show_top_note": False,
            },
            "sections": {
                "show_time_spans_in": ["Experiencia Laboral"]
            },
        },
        "locale": {
            "language": datos.get("idioma", "spanish")
        },
        "settings": {
            "current_date": "today",
            "render_command": {
                "output_folder": "rendercv_output"
            },
            "bold_keywords": datos.get("keywords", []),
            "pdf_title": f"{nombre_limpio} - Hoja de Vida",
        },
    }

    yaml_writer = YAML()
    yaml_writer.indent(mapping=2, sequence=4, offset=2)
    buf = io.StringIO()
    buf.write("# yaml-language-server: $schema=https://raw.githubusercontent.com/rendercv/rendercv/refs/tags/v2.8/schema.json\n")
    yaml_writer.dump(doc_yaml, buf)
    return buf.getvalue()


def listar_clientes() -> list[Path]:
    if not CLIENTES_DIR.exists():
        return []
    return sorted([d for d in CLIENTES_DIR.iterdir() if d.is_dir()])


def obtener_yaml_cliente(carpeta_cliente: Path) -> Path | None:
    """Mantiene el archivo elegido: si aparece otro YAML en la carpeta, no se cambia solo."""
    yamls = core.yamls_cliente(carpeta_cliente)
    if not yamls:
        return None
    fijados = st.session_state.setdefault("yaml_fijado", {})
    elegido = fijados.get(str(carpeta_cliente))
    if elegido not in [str(y) for y in yamls]:
        elegido = fijados[str(carpeta_cliente)] = str(yamls[0])
    return Path(elegido)


def al_cambiar_cliente() -> None:
    st.session_state["cliente_actual"] = st.session_state["sb_cliente"]


# ==================== CABECERA ====================
st.markdown(
    """
    <div class="main-header">
        <h1>📄 RenderCV Studio Pro</h1>
    </div>
    """,
    unsafe_allow_html=True,
)

aviso_global = st.session_state.pop("aviso_global", None)
if aviso_global:
    st.success(aviso_global)

# ==================== BARRA LATERAL ====================
with st.sidebar:
    st.header("👥 Gestión de Clientes")

    clientes = listar_clientes()
    nombres_clientes = [c.name for c in clientes]

    if "cliente_actual" not in st.session_state:
        st.session_state["cliente_actual"] = "ejemplo_juan_perez" if "ejemplo_juan_perez" in nombres_clientes else (nombres_clientes[0] if nombres_clientes else "")

    if nombres_clientes and st.session_state["cliente_actual"] not in nombres_clientes:
        st.session_state["cliente_actual"] = nombres_clientes[0]
    # Clave fija: con un índice variable, el selector ignoraba un cambio sí y otro no.
    if nombres_clientes:
        st.session_state["sb_cliente"] = st.session_state["cliente_actual"]
    st.selectbox("Cliente Activo:", options=nombres_clientes, key="sb_cliente", on_change=al_cambiar_cliente)

    if st.session_state["cliente_actual"]:
        carpeta_activa = CLIENTES_DIR / st.session_state["cliente_actual"]
        yamls_activos = core.yamls_cliente(carpeta_activa)
        if len(yamls_activos) > 1:
            actual_yaml = obtener_yaml_cliente(carpeta_activa)
            elegido_yaml = st.selectbox(
                "⚠️ Esta carpeta tiene varios archivos. Editando:",
                options=[y.name for y in yamls_activos],
                index=[y.name for y in yamls_activos].index(actual_yaml.name),
                key=f"sb_yaml_{st.session_state['cliente_actual']}",
            )
            st.session_state["yaml_fijado"][str(carpeta_activa)] = str(carpeta_activa / elegido_yaml)

    with st.expander("➕ Crear Nuevo Cliente", expanded=False):
        nuevo_nombre = st.text_input("Nombre completo del cliente:", placeholder="Ej: Laura Sofía Martínez")
        nuevo_tema = st.selectbox("Diseño inicial:", options=list(TEMAS_DISPONIBLES.keys()), format_func=lambda x: TEMAS_DISPONIBLES[x], key="sb_nuevo_tema")
        con_ejemplo = st.checkbox(
            "Partir de la plantilla con datos de ejemplo",
            value=False,
            help="Por defecto se empieza en blanco, para que ningún dato de ejemplo termine en el CV de un cliente.",
        )
        if st.button("Crear Cliente", type="primary", width="stretch"):
            if nuevo_nombre.strip():
                plantilla_base = PLANTILLAS_DIR / "plantilla_base_es.yaml"
                if con_ejemplo and plantilla_base.exists():
                    contenido = core.yaml_desde_plantilla(plantilla_base.read_text(encoding="utf-8"), nuevo_nombre, nuevo_tema)
                else:
                    contenido = core.documento_a_yaml(core.documento_en_blanco(nuevo_nombre, nuevo_tema))
                slug, destino_yaml = crear_cliente_con_yaml(nuevo_nombre, contenido)
                ejecutar_rendercv(destino_yaml)
                st.session_state["cliente_actual"] = slug
                avisar_y_recargar(f"Cliente «{nuevo_nombre.strip()}» creado. Complétalo en la pestaña Editor.")
            else:
                st.warning("Escribe el nombre del cliente.")

    st.divider()
    st.subheader("🎨 Cambio Rápido de Diseño")
    tema_rapido = st.selectbox(
        "Aplicar tema al cliente activo:",
        options=list(TEMAS_DISPONIBLES.keys()),
        format_func=lambda x: TEMAS_DISPONIBLES[x],
    )
    if st.button("⚡ Re-generar PDF con este Diseño", width="stretch"):
        if st.session_state.get("cliente_actual"):
            carpeta_c = CLIENTES_DIR / st.session_state["cliente_actual"]
            yaml_c = obtener_yaml_cliente(carpeta_c)
            if yaml_c and yaml_c.exists():
                try:
                    # Por estructura: una línea del CV que empiece con «theme:» no es el tema.
                    doc_tema = core.cargar_yaml(core.leer_texto(yaml_c))
                    core.fijar_ruta(doc_tema, ("design", "theme"), tema_rapido)
                    resultado = core.guardar_y_renderizar(yaml_c, core.volcar_yaml(doc_tema))
                except Exception:
                    resultado = core.ResultadoRender(False)
                if resultado.ok:
                    st.toast("¡Diseño actualizado con éxito!", icon="✅")
                else:
                    st.error("Hubo un error al renderizar. Revisa la pestaña YAML y Kit.")

    st.divider()
    st.subheader("🤖 Configuración IA (Opcional)")
    gemini_key = st.text_input(
        "Gemini API Key (Google AI Studio):",
        value=os.environ.get("GEMINI_API_KEY", ""),
        type="password",
        help="Opcional: si pegas tu clave gratuita de Google AI Studio, la conversión de CVs viejos y la adaptación a ofertas laborales se hará automáticamente con Gemini 3.8 Flash.",
    )
    if gemini_key:
        st.caption("✅ IA lista para estructurar y redactar CVs automáticamente.")
        st.caption("🔒 Al usar la IA, los datos del cliente se envían a Google. En el plan gratuito pueden usarse para mejorar sus productos: conviene contar con la autorización del cliente.")
    else:
        st.caption("ℹ️ Sin API Key: usará el extractor inteligente local + generador de Prompt para ChatGPT/Gemini.")


# ==================== PESTAÑAS PRINCIPALES ====================
tab_visual, tab_importar, tab_formulario, tab_editor, tab_catalogo = st.tabs([
    "🖌️ Editor",
    "📥 Importar",
    "📝 Formulario",
    "🧾 YAML y Kit",
    "🎨 Catálogo",
])

# -------------------------------------------------------------------------
# EDITOR VISUAL
# -------------------------------------------------------------------------
with tab_visual:
    cliente_visual = st.session_state.get("cliente_actual")
    yaml_visual = obtener_yaml_cliente(CLIENTES_DIR / cliente_visual) if cliente_visual else None
    if not cliente_visual:
        st.info("Crea tu primer cliente desde el menú izquierdo, o importa un CV en la pestaña **Importar**.")
    elif not yaml_visual:
        st.warning(f"La carpeta `{cliente_visual}` no tiene un archivo YAML.")
    else:
        try:
            render_editor_visual(yaml_visual, cliente_visual, TEMAS_DISPONIBLES, CATALOGO_DIR)
        except Exception as error_editor:
            # Un archivo atípico no debe dejar sin las demás pestañas, desde donde se puede corregir.
            st.error("El editor no pudo abrir este archivo. Corrígelo en la pestaña **YAML y Kit** o restaura una versión anterior.")
            st.caption(f"Detalle técnico: {type(error_editor).__name__}: {error_editor}")

# -------------------------------------------------------------------------
# ARRASTRAR Y SOLTAR CV ACTUAL (DRAG & DROP)
# -------------------------------------------------------------------------
with tab_importar:
    st.subheader("📥 Arrastra el CV antiguo de tu cliente (PDF, Word `.docx` o TXT)")
    st.write("Sube la hoja de vida desordenada o antigua de tu cliente. El sistema extraerá toda su información y la transformará al formato **ATS de RenderCV**.")

    col_up1, col_up2 = st.columns([1.2, 1])

    with col_up1:
        archivo_subido = st.file_uploader(
            "Arrastra y suelta aquí el archivo del cliente:",
            type=["pdf", "docx", "txt"],
            help="Soporta archivos PDF, Microsoft Word (.docx) y texto plano.",
        )
        texto_pegado = st.text_area(
            "O pega directamente el texto del CV o perfil de LinkedIn aquí:",
            height=150,
            placeholder="Si el cliente te mandó sus datos por WhatsApp o correo, pégalos aquí...",
        )

    with col_up2:
        nombre_cliente_import = st.text_input("Nombre del Cliente (para guardar su carpeta):", placeholder="Ej: Andrés Felipe Castro")
        tema_import = st.selectbox("Diseño ATS de salida:", options=list(TEMAS_DISPONIBLES.keys()), format_func=lambda x: TEMAS_DISPONIBLES[x], key="imp_tema")
        idioma_import = st.selectbox("Idioma de la Hoja de Vida:", options=["spanish", "english"], format_func=lambda x: "Español" if x == "spanish" else "Inglés")
        oferta_laboral = st.text_area(
            "🎯 (Opcional) Pega la Oferta Laboral / Vacante objetivo:",
            height=110,
            placeholder="Pega aquí los requisitos de la vacante si quieres adaptar el CV específicamente para ese puesto...",
        )

    texto_fuente = ""
    if archivo_subido is not None:
        try:
            texto_fuente = extraer_texto_archivo(archivo_subido)
            with st.expander("🔍 Ver texto extraído del documento subido", expanded=False):
                st.text_area("Texto detectado:", value=texto_fuente, height=200)
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")

    if texto_pegado.strip():
        texto_fuente = (texto_fuente + "\n\n" + texto_pegado.strip()).strip()

    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        if st.button("🚀 Convertir a Formato ATS y Generar PDF Ahora", type="primary", width="stretch"):
            if not texto_fuente:
                st.warning("Por favor arrastra un archivo PDF/Word o pega el texto del cliente primero.")
            else:
                with st.spinner("Transformando CV al estándar ATS y compilando PDF..."):
                    try:
                        if gemini_key.strip():
                            yaml_resultado = convertir_con_gemini(gemini_key, texto_fuente, oferta_laboral, tema_import, idioma_import)
                        else:
                            yaml_resultado = parser_heuristico_a_yaml(texto_fuente, tema_import, idioma_import)

                        # Determinar nombre del cliente
                        nombre_final = nombre_cliente_import.strip()
                        if nombre_final:
                            yaml_resultado = core.fijar_nombre_yaml(yaml_resultado, nombre_final)
                        else:
                            m_name = re.search(r"^\s*name:\s*(.+)$", yaml_resultado, flags=re.MULTILINE)
                            nombre_final = m_name.group(1).strip().strip("'\"") if m_name else "Cliente_Importado"

                        slug, ruta_yaml_dest = crear_cliente_con_yaml(nombre_final, yaml_resultado)
                        ok, log, pdf_gen, pngs_gen = ejecutar_rendercv(ruta_yaml_dest)
                        st.session_state["cliente_actual"] = slug

                        if ok:
                            avisar_y_recargar(f"Hoja de vida de {nombre_final} generada. Revisa en la pestaña Editor los campos marcados con [REVISAR].")
                        else:
                            st.warning("Se creó el archivo del cliente, pero requiere un ajuste en la pestaña YAML y Kit:")
                            st.code(log)
                    except Exception as err:
                        st.error(f"Ocurrió un problema durante la conversión: {err}")

    with col_btn2:
        if st.button("📋 Generar Súper-Prompt para ChatGPT / Gemini Web (Gratis sin API Key)", width="stretch"):
            if not texto_fuente:
                st.warning("Primero arrastra el archivo del cliente o pega sus datos.")
            else:
                st.session_state["prompt_generado"] = construir_prompt_ia(texto_fuente, oferta_laboral, tema_import, idioma_import)

    if st.session_state.get("prompt_generado"):
        st.info("💡 **¿No tienes API Key?** Copia este bloque, pégalo en ChatGPT o Gemini gratis en el navegador, y pega la respuesta en la pestaña **YAML y Kit**:")
        st.code(st.session_state["prompt_generado"], language="markdown")


# -------------------------------------------------------------------------
# FORMULARIO RÁPIDO POR CAMPOS
# -------------------------------------------------------------------------
with tab_formulario:
    st.subheader("📝 Captura Rápida de Datos Relevantes del Cliente")
    st.write("Completa los datos esenciales del cliente sin tocar ni una sola línea de código YAML.")

    with st.form("form_creacion_rapida"):
        c1, c2, c3 = st.columns(3)
        with c1:
            f_nombre = st.text_input("Nombre Completo *", placeholder="María Fernanda López")
            f_headline = st.text_input("Título / Especialidad (Headline)", placeholder="Especialista en Marketing Digital & Growth")
            f_ubicacion = st.text_input("Ciudad y País", placeholder="Medellín, Colombia")
        with c2:
            f_email = st.text_input("Correo Electrónico", placeholder="maria.lopez@email.com")
            f_telefono = st.text_input("Teléfono (con indicativo de país)", placeholder="+57 310 987 6543")
            f_website = st.text_input("Sitio Web / Portafolio (opcional)", placeholder="misitio.com")
        with c3:
            f_linkedin = st.text_input("Usuario de LinkedIn (sin URL)", placeholder="marialopez-growth")
            f_github = st.text_input("Usuario de GitHub (opcional)", placeholder="marialopez")
            f_tema = st.selectbox("Diseño del CV", options=list(TEMAS_DISPONIBLES.keys()), format_func=lambda x: TEMAS_DISPONIBLES[x])

        f_perfil = st.text_area(
            "Perfil Profesional (Resumen Ejecutivo)",
            placeholder="Especialista en Marketing Digital con más de 6 años de experiencia liderando estrategias de adquisición...",
            height=90,
        )

        st.markdown("#### 💼 Experiencia Laboral (hasta 3 cargos — agrega más luego en la pestaña Editor)")
        experiencias_form = []
        for i in range(1, 4):
            with st.expander(f"Cargo #{i}", expanded=(i == 1)):
                ec1, ec2, ec3 = st.columns(3)
                emp = ec1.text_input(f"Empresa #{i}", key=f"emp_{i}")
                pos = ec2.text_input(f"Cargo #{i}", key=f"pos_{i}")
                loc = ec3.text_input(f"Ubicación #{i}", key=f"loc_{i}")
                ed1, ed2 = st.columns(2)
                ini = ed1.text_input(f"Fecha Inicio #{i}", placeholder="03/2021", key=f"ini_{i}")
                fin = ed2.text_input(f"Fecha Fin #{i}", placeholder="12/2024 o actual", key=f"fin_{i}")
                logros_txt = st.text_area(
                    f"Logros principales #{i} (escribe uno por línea):",
                    placeholder="Incrementé el retorno de inversión publicitaria (ROAS) de 2.8x a 5.4x en 12 meses.",
                    height=80,
                    key=f"log_{i}",
                )
                if emp.strip() and pos.strip():
                    exp = {"company": emp.strip(), "position": pos.strip()}
                    if ini.strip():
                        exp["start_date"] = core.normalizar_fecha(ini)
                    if fin.strip():
                        exp["end_date"] = core.normalizar_fecha(fin)
                    if loc.strip():
                        exp["location"] = loc.strip()
                    logros_lista = core.lineas_a_lista(logros_txt)
                    if logros_lista:
                        exp["highlights"] = logros_lista
                    experiencias_form.append(exp)

        st.markdown("#### 🎓 Educación")
        ed_c1, ed_c2, ed_c3 = st.columns(3)
        edu_inst = ed_c1.text_input("Universidad / Institución", placeholder="Universidad EAFIT")
        edu_area = ed_c2.text_input("Carrera / Programa", placeholder="Administración de Negocios")
        edu_deg = ed_c3.text_input("Título (Pregrado, Magíster, etc.)", placeholder="Pregrado")
        ed_d1, ed_d2, ed_d3 = st.columns(3)
        edu_ini = ed_d1.text_input("Inicio Estudios", placeholder="01/2014")
        edu_fin = ed_d2.text_input("Fin Estudios", placeholder="12/2018")
        edu_loc = ed_d3.text_input("Ciudad Estudios", placeholder="Medellín, Colombia")

        st.markdown("#### 🛠️ Habilidades, Palabras Clave ATS y Certificaciones")
        hc1, hc2 = st.columns(2)
        with hc1:
            hab_texto = st.text_area(
                "Habilidades por categoría (Formato `Categoría: detalle 1, detalle 2` por línea):",
                placeholder="Marketing & Growth: Google Ads, Meta Ads, SEO Técnico\nIdiomas: Español (Nativo), Inglés (Avanzado C1)",
                height=100,
            )
        with hc2:
            cert_texto = st.text_area(
                "Certificaciones y Reconocimientos (una por línea):",
                placeholder="Google Ads Search Professional Certification (2024)",
                height=100,
            )
            keywords_txt = st.text_input("Palabras clave para resaltar en negrita (separadas por coma):", placeholder="ROAS, SEO, SEM, HubSpot")

        submitted = st.form_submit_button("✨ Crear Cliente y Generar Hoja de Vida PDF", type="primary", width="stretch")

        if submitted:
            habilidades_lista = []
            for linea in hab_texto.splitlines():
                if ":" in linea:
                    etiqueta, detalles = linea.split(":", 1)
                    habilidades_lista.append({"label": etiqueta.strip(), "details": detalles.strip()})
                elif linea.strip():
                    habilidades_lista.append({"label": "Competencias", "details": linea.strip()})

            educacion_lista = []
            if edu_inst.strip():
                edu = {"institution": edu_inst.strip(), "area": edu_area.strip()}
                if edu_deg.strip():
                    edu["degree"] = edu_deg.strip()
                if edu_ini.strip():
                    edu["start_date"] = core.normalizar_fecha(edu_ini)
                if edu_fin.strip():
                    edu["end_date"] = core.normalizar_fecha(edu_fin)
                if edu_loc.strip():
                    edu["location"] = edu_loc.strip()
                educacion_lista.append(edu)

            datos_form = {
                "nombre": f_nombre.strip(),
                "headline": f_headline.strip(),
                "ubicacion": f_ubicacion.strip(),
                "email": f_email.strip(),
                "telefono": f_telefono.strip(),
                "website": f_website.strip(),
                "linkedin": f_linkedin.strip(),
                "github": f_github.strip(),
                "tema": f_tema,
                "idioma": "spanish",
                "perfil": f_perfil.strip(),
                "experiencias": experiencias_form,
                "educacion": educacion_lista,
                "habilidades": habilidades_lista,
                "certificaciones": [c.strip() for c in cert_texto.splitlines() if c.strip()],
                "keywords": [k.strip() for k in keywords_txt.split(",") if k.strip()],
            }

            if not f_nombre.strip():
                st.error("Escribe el nombre del cliente.")
            elif edu_inst.strip() and not edu_area.strip():
                st.error("Indica la carrera o programa de la educación.")
            else:
                yaml_str = generar_yaml_desde_formulario(datos_form)
                errores_form = core.validar_yaml(yaml_str, CLIENTES_DIR / "x.yaml")
                if errores_form:
                    st.error("Revisa estos datos antes de crear el cliente:\n\n" + "\n".join(f"- {e}" for e in errores_form))
                else:
                    slug, ruta_yaml_c = crear_cliente_con_yaml(f_nombre, yaml_str)
                    ok, log, _, _ = ejecutar_rendercv(ruta_yaml_c)
                    st.session_state["cliente_actual"] = slug
                    if ok:
                        avisar_y_recargar(f"Hoja de vida de {f_nombre.strip()} generada. Sigue editándola en la pestaña Editor.")
                    else:
                        st.error("Se guardó el cliente, pero no se pudo compilar:")
                        st.code(log)


# -------------------------------------------------------------------------
# YAML AVANZADO, VISTA PREVIA Y KIT DE ENTREGA
# -------------------------------------------------------------------------
with tab_editor:
    cliente_act = st.session_state.get("cliente_actual")
    if not cliente_act:
        st.info("Selecciona o crea un cliente en el menú izquierdo.")
    else:
        carpeta_cliente = CLIENTES_DIR / cliente_act
        archivo_yaml = obtener_yaml_cliente(carpeta_cliente)
        error_lectura = None
        try:
            contenido_actual = core.leer_texto(archivo_yaml) if archivo_yaml else ""
        except OSError as e:
            error_lectura = e

        if error_lectura:
            st.error(f"No se pudo abrir el archivo: otro programa lo tiene bloqueado ({error_lectura}).")
        elif not archivo_yaml or not archivo_yaml.exists():
            st.warning(f"No se encontró un archivo YAML en `{carpeta_cliente}`.")
        else:
            st.markdown(f"### 👤 Cliente Activo: `{cliente_act}` — Archivo: `{archivo_yaml.name}`")

            col_ed, col_prev = st.columns([1.05, 1])

            with col_ed:
                clave_caja = f"editor_yaml_{cliente_act}_{archivo_yaml.name}_{hashlib.md5(contenido_actual.encode('utf-8')).hexdigest()}"
                # La caja se renueva si el archivo cambia por otra vía. Si tenía texto sin
                # guardar, se rescata en el historial en vez de perderlo.
                caja_previa = st.session_state.get("yaml_caja")
                if caja_previa and caja_previa["clave"] != clave_caja:
                    sin_guardar = st.session_state.get(caja_previa["clave"])
                    if sin_guardar is not None and sin_guardar != caja_previa["base"]:
                        core.guardar_texto_version(Path(caja_previa["ruta"]), sin_guardar)
                        st.warning("Tu texto YAML sin guardar quedó como borrador en **Editor › Revisión › Versiones anteriores**.")
                st.session_state["yaml_caja"] = {"clave": clave_caja, "base": contenido_actual, "ruta": str(archivo_yaml)}
                nuevo_contenido = st.text_area(
                    "📝 Código YAML del Cliente (puedes editar cualquier texto y hacer clic en Guardar y Renderizar):",
                    value=contenido_actual,
                    height=620,
                    key=clave_caja,
                )

                b_ed1, b_ed2 = st.columns(2)
                with b_ed1:
                    if st.button("💾 Guardar y Actualizar PDF Ahora", type="primary", width="stretch"):
                        with st.spinner("Compilando PDF con RenderCV..."):
                            resultado_yaml = core.guardar_y_renderizar(archivo_yaml, nuevo_contenido)
                        if resultado_yaml.ok:
                            st.session_state.pop("yaml_caja", None)
                            st.session_state["aviso_global"] = "¡PDF actualizado correctamente!"
                            st.rerun()
                        else:
                            mostrar_errores(resultado_yaml)

                with b_ed2:
                    if st.button("🎁 Generar Pack con los 9 Diseños (ZIP para el Cliente)", width="stretch"):
                        resultado_pack = core.guardar_y_renderizar(archivo_yaml, nuevo_contenido)
                        if not resultado_pack.ok:
                            mostrar_errores(resultado_pack)
                        else:
                            st.session_state.pop("yaml_caja", None)
                            carpeta_var = carpeta_cliente / "variantes_temas"
                            carpeta_var.mkdir(exist_ok=True)
                            progreso = st.progress(0, text="Generando los 9 diseños...")
                            temas_keys = list(TEMAS_DISPONIBLES.keys())
                            fallidos = []
                            for idx, t_key in enumerate(temas_keys):
                                proc_tema = subprocess.run(
                                    [
                                        sys.executable, "-m", "rendercv", "render", str(archivo_yaml),
                                        "--design.theme", t_key,
                                        "-typ", f"variantes_temas/CV_{t_key}.typ",
                                        "-pdf", f"variantes_temas/CV_{t_key}.pdf",
                                        "-png", f"variantes_temas/CV_{t_key}.png",
                                        "-nomd", "-nohtml", "-q",
                                    ],
                                    cwd=str(carpeta_cliente),
                                    env={**os.environ, "PYTHONUTF8": "1"},
                                    capture_output=True,
                                    timeout=core.TIMEOUT_RENDER_S,
                                )
                                if proc_tema.returncode != 0:
                                    fallidos.append(t_key)
                                progreso.progress((idx + 1) / len(temas_keys), text=f"Diseño {t_key} generado ({idx + 1}/9)...")
                            if fallidos:
                                st.error("No se pudieron generar estos diseños: " + ", ".join(fallidos))
                            else:
                                st.success("¡Los 9 diseños fueron creados! Ya puedes descargar el archivo ZIP a la derecha.")

            with col_prev:
                causa_previa_yaml = asegurar_previa(archivo_yaml)
                if causa_previa_yaml:
                    st.error(f"No se pudo generar el PDF. {causa_previa_yaml}")
                mostrar_entregables(carpeta_cliente, cliente_act, "yaml")
                mostrar_paginas(carpeta_cliente)


# -------------------------------------------------------------------------
# CATÁLOGO VISUAL DE LOS 9 DISEÑOS
# -------------------------------------------------------------------------
with tab_catalogo:
    st.subheader("🎨 Catálogo Visual de los 9 Diseños Oficiales")
    st.write("Muéstrale esta galería a tus clientes para que elijan el estilo de su Hoja de Vida.")

    cols_cat = st.columns(3)
    for idx, (t_code, t_desc) in enumerate(TEMAS_DISPONIBLES.items()):
        with cols_cat[idx % 3]:
            st.markdown(f"#### `{t_code}`")
            st.caption(t_desc)
            img_muestra = CATALOGO_DIR / f"Muestra_Tema_{t_code}_1.png"
            pdf_muestra = CATALOGO_DIR / f"Muestra_Tema_{t_code}.pdf"
            if img_muestra.exists():
                st.image(str(img_muestra), width="stretch")
            if pdf_muestra.exists():
                st.download_button(
                    label=f"📄 Ver PDF `{t_code}`",
                    data=pdf_muestra.read_bytes(),
                    file_name=pdf_muestra.name,
                    mime="application/pdf",
                    key=f"dl_cat_{t_code}",
                    width="stretch",
                )


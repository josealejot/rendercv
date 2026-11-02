import os
import re
import io
import zipfile
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st
from ruamel.yaml import YAML
from pypdf import PdfReader
import docx

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
    initial_sidebar_state="expanded",
)

# Estilos personalizados
st.markdown(
    """
    <style>
    .main-header {
        background: linear-gradient(90deg, #0f172a 0%, #1e3a8a 100%);
        color: white;
        padding: 1.4rem 1.8rem;
        border-radius: 12px;
        margin-bottom: 1.2rem;
    }
    .main-header h1 {
        color: white !important;
        margin: 0;
        font-size: 1.8rem;
    }
    .main-header p {
        color: #cbd5e1;
        margin: 0.3rem 0 0 0;
        font-size: 0.98rem;
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


def slugify(texto: str) -> str:
    limpio = texto.lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}
    for k, v in reemplazos.items():
        limpio = limpio.replace(k, v)
    limpio = re.sub(r"[^a-z0-9]+", "_", limpio)
    return limpio.strip("_") or "cliente"


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


def parser_heuristico_a_yaml(texto: str, tema: str = "classic", idioma: str = "spanish") -> str:
    """Convierte el texto extraído de un CV antiguo en una estructura YAML válida para RenderCV sin requerir API Key."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    nombre_detectado = lineas[0][:60] if lineas else "Nombre del Cliente"
    # Limpiar posibles títulos como "CURRICULUM VITAE" o "HOJA DE VIDA"
    if re.search(r"^(curriculum|currículum|hoja de vida|resume|cv)\b", nombre_detectado, re.IGNORECASE) and len(lineas) > 1:
        nombre_detectado = lineas[1][:60]

    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", texto)
    email = email_match.group(0) if email_match else "cliente@email.com"

    phone_match = re.search(r"(\+\d{1,3}[\s-]?)?(\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}|\d{10})", texto)
    phone = phone_match.group(0).strip() if phone_match else "+57 300 123 4567"
    if not phone.startswith("+"):
        phone = "+57 " + re.sub(r"[^\d]", "", phone)

    linkedin_match = re.search(r"linkedin\.com/in/([a-zA-Z0-9_-]+)", texto, re.IGNORECASE)
    linkedin_user = linkedin_match.group(1) if linkedin_match else ""

    github_match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", texto, re.IGNORECASE)
    github_user = github_match.group(1) if github_match else ""

    # Tomar líneas relevantes como puntos de resumen/experiencia para facilitar la edición rápida
    puntos_extraidos = []
    for l in lineas[1:35]:
        l_clean = l.lstrip("•-*· ").strip().replace("'", "")
        if len(l_clean) > 20 and email not in l_clean:
            puntos_extraidos.append(l_clean)

    perfil_texto = puntos_extraidos[0] if puntos_extraidos else "Profesional con sólida experiencia y orientación a resultados."
    highlights_exp = puntos_extraidos[1:7] if len(puntos_extraidos) > 1 else [
        "Logro o responsabilidad principal extraída del CV del cliente.",
        "Optimización de procesos y cumplimiento de metas estratégicas."
    ]

    redes_yaml = ""
    if linkedin_user or github_user:
        redes_yaml = "  social_networks:\n"
        if linkedin_user:
            redes_yaml += f"    - network: LinkedIn\n      username: {linkedin_user}\n"
        if github_user:
            redes_yaml += f"    - network: GitHub\n      username: {github_user}\n"

    highlights_yaml = "\n".join([f"          - '{h.replace(':', ' -')}'" for h in highlights_exp])

    yaml_generado = f"""# yaml-language-server: $schema=https://raw.githubusercontent.com/rendercv/rendercv/refs/tags/v2.8/schema.json
cv:
  name: {nombre_detectado}
  headline: Profesional Especialista
  location: Bogotá, Colombia
  email: {email}
  phone: {phone}
{redes_yaml}  sections:
    Perfil Profesional:
      - '{perfil_texto.replace(":", " -")}'
    Experiencia Laboral:
      - company: Empresa Principal (Revisar y ajustar)
        position: Cargo Desempeñado
        start_date: 2021-01
        end_date: present
        location: Colombia
        highlights:
{highlights_yaml}
    Educación:
      - institution: Universidad / Institución
        area: Carrera o Especialidad
        degree: Profesional
        start_date: 2016-01
        end_date: 2020-12
        location: Colombia
    Habilidades Técnicas:
      - label: Competencias Clave
        details: Gestión de Proyectos, Liderazgo, Análisis de Datos, Trabajo en Equipo
      - label: Idiomas
        details: Español (Nativo), Inglés (Intermedio/Avanzado)
design:
  theme: {tema}
  page:
    size: a4
    top_margin: 0.6in
    bottom_margin: 0.6in
    left_margin: 0.6in
    right_margin: 0.6in
    show_footer: true
    show_top_note: false
  sections:
    show_time_spans_in:
      - Experiencia Laboral
locale:
  language: {idioma}
settings:
  current_date: today
  render_command:
    output_folder: rendercv_output
  bold_keywords: []
  pdf_title: {nombre_detectado} - Hoja de Vida
"""
    return yaml_generado


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
    """Ejecuta python -m rendercv render sobre el archivo YAML dado y devuelve (exito, log, ruta_pdf, rutas_png)."""
    cmd = ["python", "-m", "rendercv", "render", str(ruta_yaml)]
    if tema_override:
        cmd.extend(["--design.theme", tema_override])

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    proc = subprocess.run(
        cmd,
        cwd=str(ruta_yaml.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    salida = (proc.stdout or "") + "\n" + (proc.stderr or "")
    out_dir = ruta_yaml.parent / "rendercv_output"
    pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if out_dir.exists() else []
    pngs = sorted(out_dir.glob("*.png"), key=lambda p: p.name) if out_dir.exists() else []
    exito = proc.returncode == 0 and len(pdfs) > 0
    return exito, salida.strip(), (pdfs[0] if pdfs else None), pngs


def generar_yaml_desde_formulario(datos: dict) -> str:
    redes = []
    if datos.get("linkedin"):
        redes.append({"network": "LinkedIn", "username": datos["linkedin"].strip()})
    if datos.get("github"):
        redes.append({"network": "GitHub", "username": datos["github"].strip()})

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

    cv_dict = {
        "name": datos["nombre"],
        "headline": datos.get("headline") or None,
        "location": datos.get("ubicacion") or None,
        "email": datos.get("email") or None,
        "phone": datos.get("telefono") or None,
    }
    if datos.get("website"):
        cv_dict["website"] = datos["website"]
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
            "pdf_title": f"{datos['nombre']} - Hoja de Vida",
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
    yamls = list(carpeta_cliente.glob("*_CV.yaml")) + list(carpeta_cliente.glob("*.yaml"))
    return yamls[0] if yamls else None


# ==================== CABECERA ====================
st.markdown(
    """
    <div class="main-header">
        <h1>📄 RenderCV Studio Pro — Tu Agencia de Hojas de Vida ATS</h1>
        <p>Arrastra el CV antiguo de tu cliente, llena el formulario rápido o adapta su perfil a una oferta laboral con un clic.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ==================== BARRA LATERAL ====================
with st.sidebar:
    st.header("👥 Gestión de Clientes")

    clientes = listar_clientes()
    nombres_clientes = [c.name for c in clientes]

    if "cliente_actual" not in st.session_state:
        st.session_state["cliente_actual"] = "ejemplo_juan_perez" if "ejemplo_juan_perez" in nombres_clientes else (nombres_clientes[0] if nombres_clientes else "")

    idx_sel = nombres_clientes.index(st.session_state["cliente_actual"]) if st.session_state["cliente_actual"] in nombres_clientes else 0
    cliente_seleccionado = st.selectbox(
        "Cliente Activo:",
        options=nombres_clientes,
        index=idx_sel if nombres_clientes else 0,
    )
    if cliente_seleccionado:
        st.session_state["cliente_actual"] = cliente_seleccionado

    with st.expander("➕ Crear Nuevo Cliente", expanded=False):
        nuevo_nombre = st.text_input("Nombre completo del cliente:", placeholder="Ej: Laura Sofía Martínez")
        nuevo_tema = st.selectbox("Diseño inicial:", options=list(TEMAS_DISPONIBLES.keys()), format_func=lambda x: TEMAS_DISPONIBLES[x], key="sb_nuevo_tema")
        if st.button("Crear Cliente", type="primary", use_container_width=True):
            if nuevo_nombre.strip():
                slug = slugify(nuevo_nombre)
                ruta_c = CLIENTES_DIR / slug
                ruta_c.mkdir(parents=True, exist_ok=True)
                plantilla_base = PLANTILLAS_DIR / "plantilla_base_es.yaml"
                nombre_archivo = re.sub(r"[^a-zA-Z0-9_]", "", nuevo_nombre.strip().replace(" ", "_")) or "Cliente"
                destino_yaml = ruta_c / f"{nombre_archivo}_CV.yaml"
                if plantilla_base.exists():
                    contenido = plantilla_base.read_text(encoding="utf-8")
                    contenido = contenido.replace("name: Juan Pérez Gómez", f"name: {nuevo_nombre.strip()}")
                    contenido = contenido.replace("theme: classic", f"theme: {nuevo_tema}")
                    contenido = contenido.replace("pdf_title: Juan Pérez Gómez - Hoja de Vida", f"pdf_title: {nuevo_nombre.strip()} - Hoja de Vida")
                    destino_yaml.write_text(contenido, encoding="utf-8")
                ejecutar_rendercv(destino_yaml)
                st.session_state["cliente_actual"] = slug
                st.success(f"Cliente '{nuevo_nombre}' creado.")
                st.rerun()
            else:
                st.warning("Escribe el nombre del cliente.")

    st.divider()
    st.subheader("🎨 Cambio Rápido de Diseño")
    tema_rapido = st.selectbox(
        "Aplicar tema al cliente activo:",
        options=list(TEMAS_DISPONIBLES.keys()),
        format_func=lambda x: TEMAS_DISPONIBLES[x],
    )
    if st.button("⚡ Re-generar PDF con este Diseño", use_container_width=True):
        if st.session_state.get("cliente_actual"):
            carpeta_c = CLIENTES_DIR / st.session_state["cliente_actual"]
            yaml_c = obtener_yaml_cliente(carpeta_c)
            if yaml_c and yaml_c.exists():
                txt_y = yaml_c.read_text(encoding="utf-8")
                txt_y = re.sub(r"(^\s*theme:\s*).*$", f"\\g<1>{tema_rapido}", txt_y, flags=re.MULTILINE)
                yaml_c.write_text(txt_y, encoding="utf-8")
                ok, log, _, _ = ejecutar_rendercv(yaml_c)
                if ok:
                    st.toast("¡Diseño actualizado con éxito!", icon="✅")
                else:
                    st.error("Hubo un error al renderizar. Revisa la pestaña Editor.")

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
    else:
        st.caption("ℹ️ Sin API Key: usará el extractor inteligente local + generador de Prompt para ChatGPT/Gemini.")


# ==================== PESTAÑAS PRINCIPALES ====================
tab_importar, tab_formulario, tab_editor, tab_catalogo = st.tabs([
    "📥 1. Arrastrar CV Actual y Adaptar a ATS",
    "📝 2. Formulario Rápido por Campos",
    "👁️ 3. Editor en Vivo, Vista Previa y Kit de Entrega",
    "🎨 4. Catálogo Visual de los 9 Diseños",
])

# -------------------------------------------------------------------------
# PESTAÑA 1: ARRASTRAR Y SOLTAR CV ACTUAL (DRAG & DROP)
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
        if st.button("🚀 Convertir a Formato ATS y Generar PDF Ahora", type="primary", use_container_width=True):
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
                        if not nombre_final:
                            m_name = re.search(r"^\s*name:\s*(.+)$", yaml_resultado, flags=re.MULTILINE)
                            nombre_final = m_name.group(1).strip().strip("'\"") if m_name else "Cliente_Importado"

                        slug = slugify(nombre_final)
                        carpeta_destino = CLIENTES_DIR / slug
                        carpeta_destino.mkdir(parents=True, exist_ok=True)
                        nombre_arch = re.sub(r"[^a-zA-Z0-9_]", "", nombre_final.replace(" ", "_")) or "Cliente"
                        ruta_yaml_dest = carpeta_destino / f"{nombre_arch}_CV.yaml"
                        ruta_yaml_dest.write_text(yaml_resultado, encoding="utf-8")

                        ok, log, pdf_gen, pngs_gen = ejecutar_rendercv(ruta_yaml_dest)
                        st.session_state["cliente_actual"] = slug

                        if ok:
                            st.success(f"¡Hoja de Vida de **{nombre_final}** generada exitosamente! Ve a la pestaña **3. Editor en Vivo y Vista Previa** para verla o descargarla.")
                        else:
                            st.warning("Se creó el archivo YAML del cliente, pero requiere un pequeño ajuste en la pestaña 3 (Editor en Vivo):")
                            st.code(log)
                    except Exception as err:
                        st.error(f"Ocurrió un problema durante la conversión: {err}")

    with col_btn2:
        if st.button("📋 Generar Súper-Prompt para ChatGPT / Gemini Web (Gratis sin API Key)", use_container_width=True):
            if not texto_fuente:
                st.warning("Primero arrastra el archivo del cliente o pega sus datos.")
            else:
                st.session_state["prompt_generado"] = construir_prompt_ia(texto_fuente, oferta_laboral, tema_import, idioma_import)

    if st.session_state.get("prompt_generado"):
        st.info("💡 **¿No tienes API Key?** Copia este bloque, pégalo en ChatGPT o Gemini gratis en el navegador, y pega la respuesta en la pestaña **3. Editor en Vivo**:")
        st.code(st.session_state["prompt_generado"], language="markdown")


# -------------------------------------------------------------------------
# PESTAÑA 2: FORMULARIO RÁPIDO POR CAMPOS
# -------------------------------------------------------------------------
with tab_formulario:
    st.subheader("📝 Captura Rápida de Datos Relevantes del Cliente")
    st.write("Completa los datos esenciales del cliente sin tocar ni una sola línea de código YAML.")

    with st.form("form_creacion_rapida"):
        c1, c2, c3 = st.columns(3)
        with c1:
            f_nombre = st.text_input("Nombre Completo *", value="María Fernanda López")
            f_headline = st.text_input("Título / Especialidad (Headline)", value="Especialista en Marketing Digital & Growth")
            f_ubicacion = st.text_input("Ciudad y País", value="Medellín, Colombia")
        with c2:
            f_email = st.text_input("Correo Electrónico", value="maria.lopez@email.com")
            f_telefono = st.text_input("Teléfono (con indicativo de país)", value="+57 310 987 6543")
            f_website = st.text_input("Sitio Web / Portafolio (opcional)", value="")
        with c3:
            f_linkedin = st.text_input("Usuario de LinkedIn (sin URL)", value="marialopez-growth")
            f_github = st.text_input("Usuario de GitHub (opcional)", value="")
            f_tema = st.selectbox("Diseño del CV", options=list(TEMAS_DISPONIBLES.keys()), format_func=lambda x: TEMAS_DISPONIBLES[x])

        f_perfil = st.text_area(
            "Perfil Profesional (Resumen Ejecutivo)",
            value="Especialista en Marketing Digital con más de 6 años de experiencia liderando estrategias de adquisición B2B y B2C, optimización de embudos de conversión y gestión de presupuestos publicitarios superiores a USD $150k anuales.",
            height=90,
        )

        st.markdown("#### 💼 Experiencia Laboral (hasta 3 cargos principales — puedes añadir más luego)")
        experiencias_form = []
        for i in range(1, 4):
            with st.expander(f"Cargo #{i}", expanded=(i == 1)):
                ec1, ec2, ec3 = st.columns(3)
                emp = ec1.text_input(f"Empresa #{i}", value="GrowthLab LATAM" if i == 1 else "", key=f"emp_{i}")
                pos = ec2.text_input(f"Cargo #{i}", value="Head of Digital Marketing" if i == 1 else "", key=f"pos_{i}")
                loc = ec3.text_input(f"Ubicación #{i}", value="Medellín, Colombia" if i == 1 else "", key=f"loc_{i}")
                ed1, ed2 = st.columns(2)
                ini = ed1.text_input(f"Fecha Inicio (YYYY-MM) #{i}", value="2021-04" if i == 1 else "", key=f"ini_{i}")
                fin = ed2.text_input(f"Fecha Fin (YYYY-MM o present) #{i}", value="present" if i == 1 else "", key=f"fin_{i}")
                logros_txt = st.text_area(
                    f"Logros principales #{i} (escribe uno por línea):",
                    value="Incrementé el retorno de inversión publicitaria (ROAS) de 2.8x a 5.4x en 12 meses.\nLideré un equipo de 6 especialistas en SEO, SEM y automatización de CRM." if i == 1 else "",
                    height=80,
                    key=f"log_{i}",
                )
                if emp.strip() and pos.strip():
                    logros_lista = [l.strip().lstrip("-•* ") for l in logros_txt.splitlines() if l.strip()]
                    experiencias_form.append({
                        "company": emp.strip(),
                        "position": pos.strip(),
                        "start_date": ini.strip() or "2020-01",
                        "end_date": fin.strip() or "present",
                        "location": loc.strip(),
                        "highlights": logros_lista,
                    })

        st.markdown("#### 🎓 Educación")
        ed_c1, ed_c2, ed_c3 = st.columns(3)
        edu_inst = ed_c1.text_input("Universidad / Institución", value="Universidad EAFIT")
        edu_area = ed_c2.text_input("Carrera / Programa", value="Administración de Negocios")
        edu_deg = ed_c3.text_input("Título (Pregrado, Magíster, etc.)", value="Pregrado")
        ed_d1, ed_d2, ed_d3 = st.columns(3)
        edu_ini = ed_d1.text_input("Inicio Estudios (YYYY-MM)", value="2014-01")
        edu_fin = ed_d2.text_input("Fin Estudios (YYYY-MM)", value="2018-12")
        edu_loc = ed_d3.text_input("Ciudad Estudios", value="Medellín, Colombia")

        st.markdown("#### 🛠️ Habilidades, Palabras Clave ATS y Certificaciones")
        hc1, hc2 = st.columns(2)
        with hc1:
            hab_texto = st.text_area(
                "Habilidades por categoría (Formato `Categoría: detalle 1, detalle 2` por línea):",
                value="Marketing & Growth: Google Ads, Meta Ads, SEO Técnico, Google Analytics 4, HubSpot\nAnalítica & Datos: Looker Studio, SQL Básico, Excel Avanzado, A/B Testing\nIdiomas: Español (Nativo), Inglés (Avanzado C1)",
                height=100,
            )
        with hc2:
            cert_texto = st.text_area(
                "Certificaciones y Reconocimientos (una por línea):",
                value="Google Ads Search & Display Professional Certification (2024)\nHubSpot Inbound Marketing Certified (2023)",
                height=100,
            )
            keywords_txt = st.text_input("Palabras clave para resaltar en negrita (separadas por coma):", value="ROAS, SEO, SEM, HubSpot, Google Ads")

        submitted = st.form_submit_button("✨ Crear Cliente y Generar Hoja de Vida PDF", type="primary", use_container_width=True)

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
                educacion_lista.append({
                    "institution": edu_inst.strip(),
                    "area": edu_area.strip(),
                    "degree": edu_deg.strip(),
                    "start_date": edu_ini.strip() or "2015-01",
                    "end_date": edu_fin.strip() or "2019-12",
                    "location": edu_loc.strip(),
                })

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

            yaml_str = generar_yaml_desde_formulario(datos_form)
            slug = slugify(f_nombre)
            carpeta_c = CLIENTES_DIR / slug
            carpeta_c.mkdir(parents=True, exist_ok=True)
            nombre_arch = re.sub(r"[^a-zA-Z0-9_]", "", f_nombre.strip().replace(" ", "_")) or "Cliente"
            ruta_yaml_c = carpeta_c / f"{nombre_arch}_CV.yaml"
            ruta_yaml_c.write_text(yaml_str, encoding="utf-8")

            ok, log, _, _ = ejecutar_rendercv(ruta_yaml_c)
            st.session_state["cliente_actual"] = slug
            if ok:
                st.success(f"¡Hoja de Vida de **{f_nombre}** compilada en PDF! Abre la pestaña **3. Editor en Vivo y Vista Previa** para visualizarla y descargarla.")
            else:
                st.error("Se guardó el YAML pero hubo un detalle de validación:")
                st.code(log)


# -------------------------------------------------------------------------
# PESTAÑA 3: EDITOR EN VIVO, VISTA PREVIA Y KIT DE ENTREGA
# -------------------------------------------------------------------------
with tab_editor:
    cliente_act = st.session_state.get("cliente_actual")
    if not cliente_act:
        st.info("Selecciona o crea un cliente en el menú izquierdo.")
    else:
        carpeta_cliente = CLIENTES_DIR / cliente_act
        archivo_yaml = obtener_yaml_cliente(carpeta_cliente)

        if not archivo_yaml or not archivo_yaml.exists():
            st.warning(f"No se encontró un archivo YAML en `{carpeta_cliente}`.")
        else:
            st.markdown(f"### 👤 Cliente Activo: `{cliente_act}` — Archivo: `{archivo_yaml.name}`")

            col_ed, col_prev = st.columns([1.05, 1])

            with col_ed:
                contenido_actual = archivo_yaml.read_text(encoding="utf-8")
                nuevo_contenido = st.text_area(
                    "📝 Código YAML del Cliente (puedes editar cualquier texto y hacer clic en Guardar y Renderizar):",
                    value=contenido_actual,
                    height=620,
                    key=f"editor_yaml_{cliente_act}",
                )

                b_ed1, b_ed2 = st.columns(2)
                with b_ed1:
                    if st.button("💾 Guardar y Actualizar PDF Ahora", type="primary", use_container_width=True):
                        archivo_yaml.write_text(nuevo_contenido, encoding="utf-8")
                        with st.spinner("Compilando PDF con RenderCV..."):
                            ok, log, _, _ = ejecutar_rendercv(archivo_yaml)
                            if ok:
                                st.success("¡PDF actualizado correctamente!")
                            else:
                                st.error("Error de validación en el YAML:")
                                st.code(log)

                with b_ed2:
                    if st.button("🎁 Generar Pack con los 9 Diseños (ZIP para el Cliente)", use_container_width=True):
                        archivo_yaml.write_text(nuevo_contenido, encoding="utf-8")
                        carpeta_var = carpeta_cliente / "variantes_temas"
                        carpeta_var.mkdir(exist_ok=True)
                        progreso = st.progress(0, text="Generando los 9 diseños...")
                        temas_keys = list(TEMAS_DISPONIBLES.keys())
                        for idx, t_key in enumerate(temas_keys):
                            subprocess.run(
                                [
                                    "python", "-m", "rendercv", "render", str(archivo_yaml),
                                    "--design.theme", t_key,
                                    "-pdf", f"variantes_temas/CV_{t_key}.pdf",
                                    "-png", f"variantes_temas/CV_{t_key}.png",
                                    "-nomd", "-nohtml", "-q",
                                ],
                                cwd=str(carpeta_cliente),
                                env={**os.environ, "PYTHONUTF8": "1"},
                            )
                            progreso.progress((idx + 1) / len(temas_keys), text=f"Diseño {t_key} generado ({idx + 1}/9)...")
                        st.success("¡Los 9 diseños fueron creados! Ya puedes descargar el archivo ZIP a la derecha.")

            with col_prev:
                out_dir = carpeta_cliente / "rendercv_output"
                pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if out_dir.exists() else []
                pngs = sorted(out_dir.glob("*.png"), key=lambda p: p.name) if out_dir.exists() else []

                if not pdfs:
                    ok, log, _, pngs = ejecutar_rendercv(archivo_yaml)
                    pdfs = sorted(out_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if out_dir.exists() else []

                if pdfs:
                    pdf_actual = pdfs[0]
                    dl1, dl2 = st.columns(2)
                    with dl1:
                        st.download_button(
                            label=f"⬇️ Descargar PDF ({pdf_actual.name})",
                            data=pdf_actual.read_bytes(),
                            file_name=pdf_actual.name,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                        )
                    with dl2:
                        # Crear paquete ZIP con todos los entregables del cliente
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                            for f_out in out_dir.glob("*"):
                                if f_out.suffix.lower() in [".pdf", ".png", ".html", ".md"]:
                                    zf.write(f_out, arcname=f"Principal/{f_out.name}")
                            carpeta_var = carpeta_cliente / "variantes_temas"
                            if carpeta_var.exists():
                                for f_var in carpeta_var.glob("*"):
                                    zf.write(f_var, arcname=f"Catalogo_9_Disenos/{f_var.name}")
                        st.download_button(
                            label="📦 Descargar Kit Completo (.ZIP)",
                            data=zip_buffer.getvalue(),
                            file_name=f"Kit_Hoja_de_Vida_{cliente_act}.zip",
                            mime="application/zip",
                            use_container_width=True,
                        )

                if pngs:
                    st.markdown(f"**👁️ Vista Previa en Alta Definición ({len(pngs)} página(s)):**")
                    for idx_p, png_path in enumerate(pngs, start=1):
                        st.image(str(png_path), caption=f"Página {idx_p} — {png_path.name}", use_container_width=True)
                else:
                    st.info("Haz clic en 'Guardar y Actualizar PDF Ahora' para ver la vista previa aquí.")


# -------------------------------------------------------------------------
# PESTAÑA 4: CATÁLOGO VISUAL DE LOS 9 DISEÑOS
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
                st.image(str(img_muestra), use_container_width=True)
            if pdf_muestra.exists():
                st.download_button(
                    label=f"📄 Ver PDF `{t_code}`",
                    data=pdf_muestra.read_bytes(),
                    file_name=pdf_muestra.name,
                    mime="application/pdf",
                    key=f"dl_cat_{t_code}",
                    use_container_width=True,
                )


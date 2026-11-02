"""Editor visual: hojas de vida sin tocar YAML, con vista previa al lado."""

from __future__ import annotations

import hashlib
import io
import re
import time
import zipfile
from pathlib import Path

import streamlit as st

import cv_core as core

SECCIONES_TIPICAS = ["texto", "experiencia", "educacion", "habilidad", "viñeta"]
TAMANOS_PAGINA = {"a4": "A4", "us-letter": "Carta", "a5": "A5", "us-executive": "Ejecutivo"}
IDIOMAS = {"spanish": "Español", "english": "Inglés"}
COLOR_INICIAL = "#1e3a8a"
RUTAS_COLOR = [("design", "colors", c) for c in ("name", "section_titles", "links")]
INTERVALO_VERSION_AUTO_S = 300

OBLIGATORIOS = {
    "position", "company", "institution", "area", "name", "label", "details", "bullet", "title", "authors",
    "number", "reversed_number",
}
AYUDAS = {
    "highlights": "Uno por línea. Usa **dos asteriscos** para resaltar una cifra en negrita.",
    "authors": "Un autor por línea.",
    "summary": "Una frase corta sobre el rol o el proyecto.",
    "date": "Texto libre, por ejemplo «2023» o «Verano 2023».",
}
PLACEHOLDERS = {
    "position": "Ej: Analista de Datos Senior",
    "company": "Ej: Bancolombia",
    "institution": "Ej: Universidad Nacional de Colombia",
    "area": "Ej: Ingeniería de Sistemas",
    "degree": "Ej: Pregrado, Maestría",
    "location": "Ej: Medellín, Colombia",
    "start_date": "Ej: 03/2022, marzo 2022 o 2022",
    "end_date": "Ej: 12/2024",
    "highlights": "Reduje los tiempos de entrega en un **30%** al automatizar...\nLideré un equipo de 5 personas...",
    "label": "Ej: Idiomas",
    "details": "Ej: Español (nativo), Inglés (B2)",
    "bullet": "Ej: Certificación PMP (2023)",
    "name": "Ej: Plataforma de pagos",
}


def _clave(ve: dict, *partes: str) -> str:
    return "ve_" + "_".join([str(ve["gen"]), *map(str, partes)])


def _cargar_estado(ruta: Path) -> dict | None:
    """Mantiene un borrador por archivo, así cambiar de cliente no descarta lo pendiente.

    Si el archivo cambió por fuera (otra pestaña, OneDrive), manda el disco; lo que estaba
    pendiente se rescata en el historial antes de recargar.
    """
    try:
        texto = core.leer_texto(ruta)
    except OSError as e:
        st.error(f"No se pudo abrir el archivo: otro programa lo tiene bloqueado ({e}).")
        return None
    borradores = st.session_state.setdefault("ve_borradores", {})
    ve = borradores.get(str(ruta))
    if ve and ve["texto"] == texto:
        st.session_state["ve"] = ve
        return ve
    if ve and ve.get("pendiente"):
        _rescatar_pendiente(ve, ruta)
        st.warning(
            "El archivo cambió fuera del editor mientras tenías cambios sin guardar. Se muestra la versión "
            "actual; tus cambios quedaron como borrador en **Revisión › Versiones anteriores**."
        )
    st.session_state["ve_contador"] = gen = st.session_state.get("ve_contador", 0) + 1
    pedido = st.session_state.pop("ve_cargar_version", None)
    try:
        doc = core.cargar_yaml(pedido if pedido is not None else texto)
        plano_disco = core.a_plano(core.cargar_yaml(texto))
        modelo = core.construir_modelo(doc)
    except Exception as e:
        borradores.pop(str(ruta), None)
        st.session_state.pop("ve", None)
        st.error(
            "Este archivo tiene un error de escritura y no se puede abrir en el editor visual. "
            "Corrígelo en la pestaña **YAML y Kit** o restaura una versión anterior."
        )
        st.caption(f"Detalle técnico: {str(e).splitlines()[0]}")
        return None
    ve = {
        "ruta": str(ruta),
        "texto": texto,
        "plano": plano_disco,
        "modelo": modelo,
        "gen": gen,
        "abierta": None,
        "pendiente": False,
        "forzar_version": False,
        "errores": [],
        "avisos": [],
        "guardado": None,
        "fallo_plano": None,
        "foto_hash": None,
        "foto_gen": 0,
    }
    borradores[str(ruta)] = ve
    st.session_state["ve"] = ve
    return ve


def _rescatar_pendiente(ve: dict, ruta: Path) -> None:
    core.sincronizar_doc(ve["modelo"])
    core.guardar_texto_version(ruta, core.volcar_yaml(ve["modelo"]["doc"]))


def asegurar_previa(ruta: Path) -> str | None:
    """Genera el PDF si falta. Recuerda un fallo para no recompilar en cada interacción."""
    if core.archivos_salida(ruta.parent)[0]:
        return None
    fallos = st.session_state.setdefault("ve_fallos_previa", {})
    huella = ruta.stat().st_mtime_ns
    fallo = fallos.get(str(ruta))
    if fallo and fallo[0] == huella:
        return fallo[1]
    resultado = core.renderizar(ruta)
    if resultado.ok:
        fallos.pop(str(ruta), None)
        return None
    causa = core.causa_error(resultado.log) or "RenderCV no pudo compilar este archivo."
    fallos[str(ruta)] = (huella, causa)
    return causa


# ---------------------------------------------------------------------------
# Acciones (callbacks: corren antes de redibujar, así la lista nunca queda a medias)
# ---------------------------------------------------------------------------

def _ve() -> dict:
    return st.session_state["ve"]


def _accion_mover(lista: list, uid: str, delta: int) -> None:
    core.mover(lista, uid, delta)


def _accion_eliminar(lista: list, uid: str) -> None:
    core.eliminar(lista, uid)
    _ve()["forzar_version"] = True
    if _ve()["abierta"] == uid:
        _ve()["abierta"] = None


def _accion_alternar(uid: str) -> None:
    _ve()["abierta"] = None if _ve()["abierta"] == uid else uid


def _accion_agregar_entrada(seccion: dict) -> None:
    entrada = core.nueva_entrada(seccion["tipo"])
    seccion["entradas"].append(entrada)
    _ve()["abierta"] = entrada["uid"]


def _accion_agregar_seccion(claves: tuple[str, str]) -> None:
    tipo = st.session_state[claves[0]]
    titulo = st.session_state.get(claves[1], "").strip()
    seccion = core.nueva_seccion(tipo, titulo)
    entrada = core.nueva_entrada(tipo)
    seccion["entradas"].append(entrada)
    _ve()["modelo"]["secciones"].append(seccion)
    _ve()["abierta"] = entrada["uid"]
    st.session_state[claves[1]] = ""


def _accion_estructura_tipica() -> None:
    modelo = _ve()["modelo"]
    for tipo in SECCIONES_TIPICAS:
        seccion = core.nueva_seccion(tipo)
        seccion["entradas"].append(core.nueva_entrada(tipo))
        modelo["secciones"].append(seccion)
    _ve()["abierta"] = modelo["secciones"][-len(SECCIONES_TIPICAS)]["entradas"][0]["uid"]


def _accion_agregar_red() -> None:
    _ve()["modelo"]["redes"].append(core.nueva_red())


def _accion_tema(tema: str) -> None:
    core.fijar_ruta(_ve()["modelo"]["doc"], ("design", "theme"), tema)


def _accion_quitar_foto() -> None:
    ve = _ve()
    ve["modelo"]["doc"]["cv"].pop("photo", None)
    ve["foto_gen"] += 1
    ve["foto_hash"] = None


# ---------------------------------------------------------------------------
# Datos personales
# ---------------------------------------------------------------------------

def _panel_datos(ve: dict, carpeta: Path) -> None:
    modelo = ve["modelo"]
    doc = modelo["doc"]
    cv = doc["cv"]

    nombre_previo = str(cv.get("name") or "")
    nombre = st.text_input(
        "Nombre completo *", value=nombre_previo, placeholder="Ej: Laura Sofía Martínez", key=_clave(ve, "name")
    )
    core.fijar_contacto(cv, "name", nombre)
    nombre_nuevo = str(cv.get("name") or "")
    if nombre_nuevo != nombre_previo and core.obtener_ruta(doc, ("settings", "pdf_title")) == f"{nombre_previo} - Hoja de Vida":
        core.fijar_ruta(doc, ("settings", "pdf_title"), f"{nombre_nuevo} - Hoja de Vida")

    core.fijar_contacto(cv, "headline", st.text_input(
        "Título profesional", value=str(cv.get("headline") or ""),
        placeholder="Ej: Especialista en Marketing Digital", key=_clave(ve, "headline"),
    ))
    c1, c2 = st.columns(2)
    core.fijar_contacto(cv, "email", c1.text_input(
        "Correo", value=core.texto_contacto(cv.get("email")), placeholder="nombre@correo.com", key=_clave(ve, "email"),
    ))
    core.fijar_contacto(cv, "phone", c2.text_input(
        "Teléfono", value=core.texto_contacto(cv.get("phone")), placeholder="300 123 4567",
        help="Si no pones indicativo se asume Colombia (+57).", key=_clave(ve, "phone"),
    ))
    c3, c4 = st.columns(2)
    core.fijar_contacto(cv, "location", c3.text_input(
        "Ciudad y país", value=str(cv.get("location") or ""), placeholder="Medellín, Colombia", key=_clave(ve, "location"),
    ))
    core.fijar_contacto(cv, "website", c4.text_input(
        "Sitio web (opcional)", value=core.texto_contacto(cv.get("website")), placeholder="misitio.com", key=_clave(ve, "website"),
    ))

    st.markdown("**Redes sociales**")
    for red in modelo["redes"]:
        valor = red["valor"]
        r1, r2, r3 = st.columns([1.1, 2, 0.35], vertical_alignment="bottom")
        actual = str(valor.get("network", "LinkedIn"))
        opciones = core.REDES_DISPONIBLES if actual in core.REDES_DISPONIBLES else [actual, *core.REDES_DISPONIBLES]
        elegida = r1.selectbox(
            "Red", opciones, index=opciones.index(actual), key=_clave(ve, red["uid"], "red"), label_visibility="collapsed",
        )
        if elegida != actual:
            valor["network"] = elegida
        usuario = r2.text_input(
            "Usuario", value=str(valor.get("username") or ""), placeholder="Usuario o enlace del perfil",
            key=_clave(ve, red["uid"], "usuario"), label_visibility="collapsed",
        )
        limpio = core.normalizar_usuario_red(usuario)
        if limpio != str(valor.get("username") or ""):
            valor["username"] = limpio
        r3.button(
            "", icon=":material/delete:", key=_clave(ve, red["uid"], "quitar"), help="Quitar red",
            on_click=_accion_eliminar, args=(modelo["redes"], red["uid"]),
        )
    st.button("Agregar red social", icon=":material/add:", key=_clave(ve, "agregar_red"), on_click=_accion_agregar_red)

    st.markdown("**Foto (opcional)**")
    foto_actual = str(cv.get("photo") or "")
    ruta_foto = carpeta / foto_actual if foto_actual else None
    if ruta_foto and ruta_foto.exists():
        f1, f2 = st.columns([1, 3], vertical_alignment="center")
        f1.image(str(ruta_foto), width=90)
        f2.button("Quitar foto", icon=":material/delete:", key=_clave(ve, "quitar_foto"), on_click=_accion_quitar_foto)
    else:
        subida = st.file_uploader(
            "Foto", type=["jpg", "jpeg", "png"], key=_clave(ve, "foto", ve["foto_gen"]), label_visibility="collapsed",
            help="En Colombia es habitual; algunos sistemas ATS y empresas internacionales la prefieren ausente.",
        )
        if subida is not None:
            contenido = subida.getvalue()
            huella = hashlib.md5(contenido).hexdigest()
            if huella != ve["foto_hash"]:
                try:
                    cv["photo"] = core.guardar_foto(carpeta, contenido)
                    ve["foto_hash"] = huella
                except ValueError as e:
                    st.error(str(e))


# ---------------------------------------------------------------------------
# Secciones y entradas
# ---------------------------------------------------------------------------

def _campo_texto(ve: dict, uid: str, valor: dict, campo: str, contenedor) -> None:
    etiqueta = core.ETIQUETAS_CAMPO.get(campo, campo)
    if campo in OBLIGATORIOS:
        etiqueta += " *"
    core.fijar_campo(valor, campo, contenedor.text_input(
        etiqueta, value=str(valor.get(campo) or ""), placeholder=PLACEHOLDERS.get(campo),
        help=AYUDAS.get(campo), key=_clave(ve, uid, campo),
    ))


def _campo_area(ve: dict, uid: str, valor: dict, campo: str) -> None:
    etiqueta = core.ETIQUETAS_CAMPO.get(campo, campo)
    if campo in OBLIGATORIOS:
        etiqueta += " *"
    actual = core.lista_a_lineas(valor.get(campo))
    alto = max(90, min(260, 34 * (actual.count("\n") + 2) + (len(actual) // 3)))
    core.fijar_campo(valor, campo, st.text_area(
        etiqueta, value=actual, placeholder=PLACEHOLDERS.get(campo), help=AYUDAS.get(campo),
        height=alto, key=_clave(ve, uid, campo),
    ))


def _campos_fecha(ve: dict, uid: str, valor: dict, tipo: str) -> None:
    c1, c2 = st.columns(2)
    _campo_texto(ve, uid, valor, "start_date", c1)
    texto_actual = "Trabajo aquí actualmente" if tipo == "experiencia" else "En curso"
    en_curso = st.checkbox(
        texto_actual, value=str(valor.get("end_date") or "") == "present", key=_clave(ve, uid, "en_curso"),
    )
    if en_curso:
        valor["end_date"] = "present"
        c2.text_input(core.ETIQUETAS_CAMPO["end_date"], value="Actualidad", disabled=True, key=_clave(ve, uid, "fin_fijo"))
    else:
        if str(valor.get("end_date") or "") == "present":
            valor.pop("end_date", None)
        _campo_texto(ve, uid, valor, "end_date", c2)
        if valor.get("start_date") and not valor.get("end_date"):
            st.caption(":material/info: Sin fecha de fin, el PDF mostrará «presente». Escribe cuándo terminó.")


def _form_entrada(ve: dict, tipo: str, entrada: dict) -> None:
    uid = entrada["uid"]
    if tipo == "texto":
        actual = str(entrada["valor"] or "")
        nuevo = st.text_area(
            "Texto", value=actual, height=max(110, min(260, 90 + len(actual) // 3)),
            placeholder="Profesional con 6 años de experiencia en...", key=_clave(ve, uid, "texto"),
            help="Usa **dos asteriscos** para resaltar en negrita.",
        ).strip()
        if nuevo != actual.strip():
            entrada["valor"] = core.neutralizar_typst(nuevo)
        return

    valor = entrada["valor"]
    if tipo == "desconocido":
        st.info("Esta entrada usa campos que el editor visual no reconoce. Se conserva tal cual; edítala en **YAML y Kit**.")
        st.code(core.volcar_yaml(valor), language="yaml")
        return

    campos = list(core.TIPOS_ENTRADA[tipo]["campos"])
    cortos = [c for c in campos if c not in core.CAMPOS_LISTA and c not in core.CAMPOS_FECHA and c not in {"summary", "details", "bullet"}]
    for i in range(0, len(cortos), 2):
        pareja = cortos[i:i + 2]
        for campo, columna in zip(pareja, st.columns(2)):
            _campo_texto(ve, uid, valor, campo, columna)
    if "start_date" in campos:
        _campos_fecha(ve, uid, valor, tipo)
    for campo in ("details", "bullet", "summary"):
        if campo in campos:
            _campo_area(ve, uid, valor, campo)
    for campo in core.CAMPOS_LISTA:
        if campo in campos:
            _campo_area(ve, uid, valor, campo)


def _panel_secciones(ve: dict) -> None:
    modelo = ve["modelo"]
    secciones = modelo["secciones"]

    if not secciones:
        st.info("Esta hoja de vida aún no tiene secciones.")
        st.button(
            "Crear estructura típica", icon=":material/auto_awesome:", type="primary",
            help="Perfil, experiencia, educación, habilidades y certificaciones, listas para llenar.",
            key=_clave(ve, "tipica"), on_click=_accion_estructura_tipica,
        )

    for i, seccion in enumerate(secciones):
        suid = seccion["uid"]
        tipo = seccion["tipo"]
        with st.container(border=True):
            t1, t2, t3, t4 = st.columns([4, 0.5, 0.5, 0.5], vertical_alignment="center", gap="small")
            titulo_previo = seccion["titulo"]
            titulo_nuevo = t1.text_input(
                "Título de la sección", value=titulo_previo, key=_clave(ve, suid, "titulo"), label_visibility="collapsed",
                placeholder="Título de la sección",
            )
            if titulo_nuevo != titulo_previo:
                seccion["titulo"] = core.neutralizar_typst(titulo_nuevo)
            t2.button(
                "", icon=":material/arrow_upward:", key=_clave(ve, suid, "subir"), help="Subir sección", disabled=i == 0,
                on_click=_accion_mover, args=(secciones, suid, -1),
            )
            t3.button(
                "", icon=":material/arrow_downward:", key=_clave(ve, suid, "bajar"), help="Bajar sección",
                disabled=i == len(secciones) - 1, on_click=_accion_mover, args=(secciones, suid, 1),
            )
            with t4.popover("", icon=":material/delete:", help="Eliminar sección"):
                st.write(f"¿Eliminar «{seccion['titulo']}» y todo su contenido?")
                st.button(
                    "Sí, eliminar", type="primary", key=_clave(ve, suid, "eliminar"),
                    on_click=_accion_eliminar, args=(secciones, suid),
                )

            entradas = seccion["entradas"]
            for j, entrada in enumerate(entradas):
                euid = entrada["uid"]
                abierta = ve["abierta"] == euid
                e1, e2, e3, e4 = st.columns([4, 0.5, 0.5, 0.5], vertical_alignment="center", gap="small")
                e2.button(
                    "", icon=":material/arrow_upward:", key=_clave(ve, euid, "subir"), help="Subir", disabled=j == 0,
                    on_click=_accion_mover, args=(entradas, euid, -1),
                )
                e3.button(
                    "", icon=":material/arrow_downward:", key=_clave(ve, euid, "bajar"), help="Bajar",
                    disabled=j == len(entradas) - 1, on_click=_accion_mover, args=(entradas, euid, 1),
                )
                e4.button(
                    "", icon=":material/close:", key=_clave(ve, euid, "quitar"), help="Quitar entrada",
                    on_click=_accion_eliminar, args=(entradas, euid),
                )
                if abierta:
                    with st.container(border=True):
                        _form_entrada(ve, tipo, entrada)
                # Va después del formulario para que el título refleje lo recién escrito.
                e1.button(
                    core.titulo_entrada(tipo, entrada["valor"]),
                    icon=":material/expand_less:" if abierta else ":material/expand_more:",
                    type="tertiary", key=_clave(ve, euid, "abrir"), on_click=_accion_alternar, args=(euid,),
                )

            if tipo != "desconocido":
                st.button(
                    "Agregar", icon=":material/add:", key=_clave(ve, suid, "agregar"),
                    on_click=_accion_agregar_entrada, args=(seccion,),
                )

    with st.expander("Agregar otra sección", icon=":material/library_add:"):
        clave_tipo, clave_titulo = _clave(ve, "nueva_tipo"), _clave(ve, "nueva_titulo")
        tipos_ofrecidos = [t for t in core.TIPOS_ENTRADA if t not in {"numerada", "numerada_inversa"}]
        n1, n2 = st.columns(2)
        n1.selectbox(
            "Tipo de contenido", tipos_ofrecidos,
            format_func=lambda t: core.TIPOS_ENTRADA[t]["nombre"], key=clave_tipo,
        )
        n2.text_input("Título (opcional)", placeholder="Ej: Voluntariado", key=clave_titulo)
        st.button(
            "Agregar sección", icon=":material/add:", key=_clave(ve, "agregar_seccion"),
            on_click=_accion_agregar_seccion, args=((clave_tipo, clave_titulo),),
        )


# ---------------------------------------------------------------------------
# Diseño
# ---------------------------------------------------------------------------

def _color_a_hex(valor: object) -> str | None:
    t = str(valor or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", t):
        return t.lower()
    if m := re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", t):
        return "#" + "".join(f"{min(int(x), 255):02x}" for x in m.groups())
    return None


def _panel_diseno(ve: dict, temas: dict, catalogo_dir: Path) -> None:
    doc = ve["modelo"]["doc"]
    tema_actual = str(core.obtener_ruta(doc, ("design", "theme"), "classic"))

    st.markdown("**Plantilla**")
    columnas = st.columns(3)
    for i, (codigo, descripcion) in enumerate(temas.items()):
        with columnas[i % 3]:
            imagen = catalogo_dir / f"Muestra_Tema_{codigo}_1.png"
            if imagen.exists():
                st.image(str(imagen), width="stretch")
            en_uso = codigo == tema_actual
            st.button(
                descripcion.split(" — ")[0].replace("Engineering", "Eng."),
                icon=":material/check:" if en_uso else None, disabled=en_uso,
                type="primary" if en_uso else "secondary", help=descripcion,
                key=_clave(ve, "tema", codigo), width="stretch", on_click=_accion_tema, args=(codigo,),
            )

    st.markdown("**Apariencia**")
    d1, d2 = st.columns(2)

    color_guardado = _color_a_hex(core.obtener_ruta(doc, ("design", "colors", "name")))
    tenia_color = core.obtener_ruta(doc, ("design", "colors", "name")) is not None
    usar_color = d1.toggle("Color de acento propio", value=tenia_color, key=_clave(ve, "usar_color"))
    if usar_color:
        inicial = color_guardado or COLOR_INICIAL
        elegido = d1.color_picker("Color", value=inicial, key=_clave(ve, "color"), label_visibility="collapsed")
        if not tenia_color or elegido != inicial:
            for ruta in RUTAS_COLOR:
                core.fijar_ruta(doc, ruta, elegido)
    elif tenia_color:
        for ruta in RUTAS_COLOR:
            core.fijar_ruta(doc, ruta, None)

    fuente_actual = core.obtener_ruta(doc, ("design", "typography", "font_family"))
    if isinstance(fuente_actual, dict):
        d2.caption("Esta hoja de vida combina varias fuentes. Cámbialas en **YAML y Kit**.")
    else:
        predeterminada = "Predeterminada de la plantilla"
        opciones = [predeterminada, *core.FUENTES_DISPONIBLES]
        if fuente_actual and fuente_actual not in opciones:
            opciones.append(str(fuente_actual))
        elegida = d2.selectbox(
            "Tipografía", opciones, index=opciones.index(fuente_actual) if fuente_actual else 0, key=_clave(ve, "fuente"),
        )
        if elegida == predeterminada:
            if fuente_actual:
                core.fijar_ruta(doc, ("design", "typography", "font_family"), None)
        elif elegida != fuente_actual:
            core.fijar_ruta(doc, ("design", "typography", "font_family"), elegida)

    d3, d4 = st.columns(2)
    tam_actual = str(core.obtener_ruta(doc, ("design", "page", "size"), "us-letter"))
    opciones_tam = list(TAMANOS_PAGINA) if tam_actual in TAMANOS_PAGINA else [tam_actual, *TAMANOS_PAGINA]
    tam = d3.selectbox(
        "Tamaño de página", opciones_tam, index=opciones_tam.index(tam_actual),
        format_func=lambda t: TAMANOS_PAGINA.get(t, t), key=_clave(ve, "tam"),
    )
    if tam != tam_actual:
        core.fijar_ruta(doc, ("design", "page", "size"), tam)

    # Sin bloque locale, RenderCV genera el PDF en inglés: el selector debe decir lo mismo.
    idioma_actual = str(core.obtener_ruta(doc, ("locale", "language"), "english"))
    opciones_idioma = list(IDIOMAS) if idioma_actual in IDIOMAS else [idioma_actual, *IDIOMAS]
    idioma = d4.selectbox(
        "Idioma de fechas y títulos", opciones_idioma, index=opciones_idioma.index(idioma_actual),
        format_func=lambda t: IDIOMAS.get(t, t), key=_clave(ve, "idioma"),
    )
    if idioma != idioma_actual:
        core.fijar_ruta(doc, ("locale", "language"), idioma)

    margen_actual = max(0.5, min(3.0, core.dimension_a_cm(core.obtener_ruta(doc, ("design", "page", "top_margin")))))
    margen = st.slider("Márgenes (cm)", 0.5, 3.0, value=margen_actual, step=0.1, key=_clave(ve, "margen"))
    if round(margen, 1) != round(margen_actual, 1):
        for lado in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            core.fijar_ruta(doc, ("design", "page", lado), f"{round(margen, 1)}cm")

    grado_actual = max(1.0, min(4.0, core.dimension_a_cm(core.obtener_ruta(doc, ("design", "entries", "degree_width")), 1.0)))
    grado = st.slider(
        "Columna del título académico (cm)", 1.0, 4.0, value=grado_actual, step=0.1, key=_clave(ve, "grado"),
        help="Súbela si «Magíster» o «Pregrado» se parten en dos líneas.",
    )
    if round(grado, 1) != round(grado_actual, 1):
        core.fijar_ruta(doc, ("design", "entries", "degree_width"), f"{round(grado, 1)}cm")

    pie_actual = bool(core.obtener_ruta(doc, ("design", "page", "show_footer"), True))
    pie = st.toggle("Mostrar pie de página", value=pie_actual, key=_clave(ve, "pie"))
    if pie != pie_actual:
        core.fijar_ruta(doc, ("design", "page", "show_footer"), pie)

    claves_actuales = [str(k) for k in (core.obtener_ruta(doc, ("settings", "bold_keywords")) or [])]
    texto_claves = st.text_input(
        "Palabras para resaltar en negrita", value=", ".join(claves_actuales), key=_clave(ve, "claves"),
        placeholder="Python, SQL, Liderazgo", help="Separadas por comas. Se resaltan en todo el documento.",
    )
    if texto_claves.strip() != ", ".join(claves_actuales):
        core.fijar_ruta(doc, ("settings", "bold_keywords"), [k.strip() for k in texto_claves.split(",") if k.strip()])


# ---------------------------------------------------------------------------
# Revisión
# ---------------------------------------------------------------------------

def _accion_restaurar(ruta_yaml: Path, clave_version: str) -> None:
    version = st.session_state.get(clave_version)
    if not version:
        return
    ve = _ve()
    if ve.get("pendiente"):
        _rescatar_pendiente(ve, ruta_yaml)
    texto = core.leer_texto(Path(version))
    resultado = core.guardar_y_renderizar(ruta_yaml, texto)
    # Siempre se recarga: lo que se ve debe ser lo restaurado, no el borrador anterior.
    st.session_state["ve_borradores"].pop(str(ruta_yaml), None)
    st.session_state.pop("ve", None)
    if resultado.ok:
        st.session_state["ve_restaurado"] = "Versión restaurada."
    else:
        # Un borrador puede no ser válido todavía: se abre en el editor para terminar de corregirlo.
        st.session_state["ve_cargar_version"] = texto
        st.session_state["ve_restaurado"] = "Esta versión tiene datos por corregir: se abrió en el editor sin guardarla."


def _panel_revision(ve: dict, ruta_yaml: Path) -> None:
    _, pngs = core.archivos_salida(ruta_yaml.parent)
    revision = core.revisar_entrega(ve["modelo"]["doc"], len(pngs))
    aprobadas = sum(1 for r in revision if r["nivel"] == "ok")
    st.progress(aprobadas / max(len(revision), 1), text=f"{aprobadas} de {len(revision)} comprobaciones superadas")

    orden = {"bloqueante": 0, "mejora": 1, "ok": 2}
    iconos = {"bloqueante": ":material/error:", "mejora": ":material/lightbulb:", "ok": ":material/check_circle:"}
    colores = {"bloqueante": "red", "mejora": "orange", "ok": "green"}
    for r in sorted(revision, key=lambda x: orden[x["nivel"]]):
        st.markdown(f":{colores[r['nivel']]}[{iconos[r['nivel']]}] {r['texto']}")

    st.divider()
    st.markdown("**Versiones anteriores**")
    versiones = core.listar_versiones(ruta_yaml)
    if not versiones:
        st.caption("Aquí aparecerán las versiones guardadas a medida que edites.")
        return
    clave_version = _clave(ve, "version")
    st.selectbox(
        "Versión", [str(v) for v in versiones], format_func=lambda v: core.etiqueta_version(Path(v)),
        key=clave_version, label_visibility="collapsed",
    )
    st.button(
        "Restaurar esta versión", icon=":material/history:", key=_clave(ve, "restaurar"),
        help="La versión actual también queda guardada, así que puedes volver a ella.",
        on_click=_accion_restaurar, args=(ruta_yaml, clave_version),
    )


# ---------------------------------------------------------------------------
# Entregables y vista previa (compartido con la pestaña YAML)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, max_entries=8)
def _construir_zip(_archivos: tuple[tuple[str, str], ...], firma: tuple) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for origen, destino in _archivos:
            zf.write(origen, arcname=destino)
    return buffer.getvalue()


def _variantes_vigentes(carpeta_cliente: Path) -> tuple[list[Path], bool]:
    """Separa las variantes del Pack al día de las generadas antes de la última edición."""
    variantes = carpeta_cliente / "variantes_temas"
    if not variantes.exists():
        return [], False
    archivos = [f for f in sorted(variantes.iterdir()) if f.suffix.lower() in {".pdf", ".png"}]
    yamls = list(carpeta_cliente.glob("*.yaml"))
    ultimo_cambio = max((y.stat().st_mtime for y in yamls), default=0)
    vigentes = [f for f in archivos if f.stat().st_mtime >= ultimo_cambio]
    return vigentes, len(vigentes) < len(archivos)


def bytes_kit(carpeta_cliente: Path) -> bytes:
    archivos = []
    salida = carpeta_cliente / core.CARPETA_SALIDA
    if salida.exists():
        archivos += [
            (str(f), f"Principal/{f.name}") for f in sorted(salida.iterdir())
            if f.suffix.lower() in {".pdf", ".png", ".html", ".md"}
        ]
    archivos += [(str(f), f"Catalogo_9_Disenos/{f.name}") for f in _variantes_vigentes(carpeta_cliente)[0]]
    firma = tuple((o, Path(o).stat().st_mtime_ns) for o, _ in archivos)
    return _construir_zip(tuple(archivos), firma)


def mostrar_entregables(carpeta_cliente: Path, cliente: str, prefijo: str) -> None:
    pdf, _ = core.archivos_salida(carpeta_cliente)
    if not pdf:
        return
    d1, d2 = st.columns(2)
    d1.download_button(
        "PDF", data=pdf.read_bytes(), file_name=pdf.name, mime="application/pdf", type="primary",
        icon=":material/download:", width="stretch", key=f"{prefijo}_pdf", on_click="ignore",
    )
    d2.download_button(
        "Kit .zip", data=bytes_kit(carpeta_cliente), file_name=f"Kit_Hoja_de_Vida_{cliente}.zip",
        mime="application/zip", icon=":material/folder_zip:", width="stretch", key=f"{prefijo}_zip", on_click="ignore",
    )
    if _variantes_vigentes(carpeta_cliente)[1]:
        st.caption(":material/info: El Kit no incluye el Pack de 9 diseños porque el CV cambió después de generarlo. Regenéralo en **YAML y Kit**.")


def mostrar_paginas(carpeta_cliente: Path) -> None:
    _, pngs = core.archivos_salida(carpeta_cliente)
    if not pngs:
        st.info("Aún no hay vista previa. Guarda para generarla.")
        return
    for numero, png in enumerate(pngs, start=1):
        st.image(str(png), caption=f"Página {numero} de {len(pngs)}", width="stretch")


# ---------------------------------------------------------------------------
# Pantalla completa
# ---------------------------------------------------------------------------

def _persistir(ve: dict, ruta_yaml: Path, auto: bool, forzar: bool) -> None:
    modelo = ve["modelo"]
    ve["errores"] = [core.ErrorCV("", m) for m in core.errores_modelo(modelo)]
    if ve["errores"]:
        ve["pendiente"] = True
        return

    core.sincronizar_doc(modelo)
    plano = core.a_plano(modelo["doc"])
    cambiado = plano != ve["plano"]
    ve["pendiente"] = cambiado

    if not cambiado:
        if forzar:
            resultado = core.renderizar(ruta_yaml)
            ve["avisos"] = resultado.avisos
            if resultado.ok:
                ve["guardado"] = time.strftime("%H:%M:%S")
            else:
                ve["errores"] = [core.ErrorCV("", "RenderCV no pudo compilar este contenido.")]
        return

    texto = core.volcar_yaml(modelo["doc"])
    if not (auto or forzar):
        ve["errores"] = core.validar_yaml(texto, ruta_yaml)
        return
    if plano == ve["fallo_plano"] and not forzar:
        ve["errores"] = ve.get("errores_fallo", [])
        return

    resultado = core.guardar_y_renderizar(
        ruta_yaml, texto, intervalo_version_s=0 if forzar or ve["forzar_version"] else INTERVALO_VERSION_AUTO_S
    )
    if resultado.ok:
        ve.update(texto=texto, plano=plano, pendiente=False, fallo_plano=None, avisos=resultado.avisos, forzar_version=False)
        ve["guardado"] = time.strftime("%H:%M:%S")
    else:
        ve["errores"] = resultado.errores or [core.ErrorCV("", "No se pudo compilar.")]
        ve["fallo_plano"] = plano
        ve["errores_fallo"] = ve["errores"]


def render_editor_visual(ruta_yaml: Path, cliente: str, temas: dict, catalogo_dir: Path) -> None:
    aviso = st.session_state.pop("ve_restaurado", None)
    if aviso:
        st.toast(aviso, icon=":material/history:")

    ve = _cargar_estado(ruta_yaml)
    if ve is None:
        return

    carpeta = ruta_yaml.parent
    col_editor, col_previa = st.columns([1.1, 1], gap="large")

    with col_previa:
        contenedor_previa = st.container(key="ve_previa")
    with contenedor_previa:
        c1, c2 = st.columns([1.5, 1], vertical_alignment="center")
        auto = c1.toggle(
            "Autoguardado", value=st.session_state.get("ve_auto_preferencia", True), key="ve_auto",
            help="Guarda y actualiza el PDF cada vez que terminas de editar un campo.",
        )
        st.session_state["ve_auto_preferencia"] = auto
        forzar = c2.button("Guardar", icon=":material/save:", key="ve_forzar", width="stretch")

    with col_editor:
        tab_datos, tab_secciones, tab_diseno, tab_revision = st.tabs(
            ["Datos personales", "Contenido", "Diseño", "Revisión"]
        )
        with tab_datos:
            _panel_datos(ve, carpeta)
        with tab_secciones:
            _panel_secciones(ve)
        with tab_diseno:
            _panel_diseno(ve, temas, catalogo_dir)

    _persistir(ve, ruta_yaml, auto, forzar)

    causa_previa = None
    if not ve["errores"]:
        with contenedor_previa:
            causa_previa = asegurar_previa(ruta_yaml)

    otros_pendientes = [
        Path(r).parent.name for r, b in st.session_state.get("ve_borradores", {}).items()
        if r != str(ruta_yaml) and b.get("pendiente")
    ]

    with contenedor_previa:
        if otros_pendientes:
            st.warning("Cambios sin guardar en: " + ", ".join(otros_pendientes) + ". Siguen ahí al volver a ese cliente.")
        if causa_previa:
            st.error(f"No se pudo generar el PDF de este archivo. {causa_previa}")
        if ve["errores"]:
            st.warning(
                "**Falta ajustar esto para actualizar el PDF.** La vista previa muestra la última versión válida.\n\n"
                + "\n".join(f"- {e}" for e in ve["errores"])
            )
        elif ve.get("pendiente"):
            st.caption(":material/edit: Cambios sin guardar")
        elif ve["guardado"]:
            st.caption(f":material/cloud_done: Guardado a las {ve['guardado']}")
        for aviso_render in ve["avisos"]:
            st.warning(aviso_render)
        mostrar_entregables(carpeta, cliente, "ve")
        mostrar_paginas(carpeta)

    with col_editor, tab_revision:
        _panel_revision(ve, ruta_yaml)

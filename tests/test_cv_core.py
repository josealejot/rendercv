"""Pruebas del núcleo. Corren sobre carpetas temporales, nunca sobre clientes reales.

    python -m unittest discover -s tests -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import cv_core as core  # noqa: E402

PLANTILLA = (RAIZ / "plantillas" / "plantilla_base_es.yaml").read_text(encoding="utf-8")


class BaseTemporal(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rcv_test_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.yaml = self.dir / "Ana_CV.yaml"
        self.yaml.write_text(PLANTILLA, encoding="utf-8")


class TestNombres(BaseTemporal):
    def test_acentos_no_mutilan_el_nombre(self):
        self.assertEqual(core.nombre_archivo_yaml("José Muñoz"), "Jose_Munoz_CV.yaml")
        self.assertEqual(core.slugify("José Ñandú Pérez"), "jose_nandu_perez")

    def test_nombre_sin_letras_validas(self):
        self.assertEqual(core.slugify("!!!"), "cliente")
        self.assertEqual(core.nombre_archivo_yaml("!!!"), "Cliente_CV.yaml")

    def test_homonimos_no_comparten_carpeta(self):
        a = core.reservar_carpeta_cliente(self.dir, "Ana Ruiz")
        b = core.reservar_carpeta_cliente(self.dir, "Ana Ruiz")
        c = core.reservar_carpeta_cliente(self.dir, "ANA RUIZ")
        self.assertEqual({a.name, b.name, c.name}, {"ana_ruiz", "ana_ruiz_2", "ana_ruiz_3"})

    def test_slug_no_permite_salir_de_clientes(self):
        carpeta = core.reservar_carpeta_cliente(self.dir, "../../etc/passwd")
        self.assertEqual(carpeta.parent, self.dir)


class TestNormalizacion(unittest.TestCase):
    def test_fechas(self):
        casos = {
            "03/2022": "2022-03", "3-2022": "2022-03", "2022/3": "2022-03", "2022-03": "2022-03", "2022": "2022",
            "marzo de 2022": "2022-03", "Marzo 2022": "2022-03", "sept. 2021": "2021-09", "Dic 2020": "2020-12",
            "actual": "present", "Actualmente": "present", "PRESENTE": "present", "a la fecha": "present",
            "15/03/2022": "2022-03-15", "2022-03-15": "2022-03-15", "": "",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(core.normalizar_fecha(entrada), esperado, entrada)

    def test_fecha_no_reconocible_queda_igual_para_que_avise_el_validador(self):
        for entrada in ("13/2022", "ayer", "2022-13", "32/01/2020"):
            self.assertEqual(core.normalizar_fecha(entrada), entrada)

    def test_telefono(self):
        self.assertEqual(core.normalizar_telefono("300 123 4567").replace(" ", ""), "+573001234567")
        self.assertEqual(core.normalizar_telefono("123"), "123")
        self.assertEqual(core.normalizar_telefono("+1 415 555 2671").replace(" ", "").replace("-", ""), "+14155552671")

    def test_web_y_usuario(self):
        self.assertEqual(core.normalizar_web("misitio.com"), "https://misitio.com")
        self.assertEqual(core.normalizar_web("https://a.co/x"), "https://a.co/x")
        self.assertEqual(core.normalizar_web("a@b.com"), "a@b.com")
        self.assertEqual(core.normalizar_usuario_red("https://www.linkedin.com/in/ana-ruiz/?x=1"), "ana-ruiz")
        self.assertEqual(core.normalizar_usuario_red("ana-ruiz"), "ana-ruiz")

    def test_lineas(self):
        self.assertEqual(core.lineas_a_lista("- uno\n\n• dos\n  - sub\ntres"), ["uno", "dos\n  - sub", "tres"])
        self.assertEqual(core.lineas_a_lista(core.lista_a_lineas(["a", "b\n  - c"])), ["a", "b\n  - c"])


class TestIdaYVuelta(BaseTemporal):
    def test_abrir_sin_editar_no_cambia_el_contenido(self):
        doc = core.cargar_yaml(PLANTILLA)
        antes = core.a_plano(doc)
        modelo = core.construir_modelo(doc)
        core.sincronizar_doc(modelo)
        self.assertEqual(core.a_plano(modelo["doc"]), antes)

    def test_conserva_cabecera_y_campos_desconocidos(self):
        doc = core.cargar_yaml(PLANTILLA)
        modelo = core.construir_modelo(doc)
        modelo["secciones"][1]["entradas"][0]["valor"]["campo_propio"] = "conservar"
        core.sincronizar_doc(modelo)
        modelo2 = core.construir_modelo(core.cargar_yaml(core.volcar_yaml(modelo["doc"])))
        texto = core.volcar_yaml(modelo2["doc"])
        self.assertTrue(texto.startswith("# yaml-language-server"))
        self.assertIn("campo_propio: conservar", texto)
        self.assertIn("dont_generate_typst: false", texto)

    def test_caracteres_peligrosos_quedan_escapados(self):
        doc = core.cargar_yaml(PLANTILLA)
        peligroso = "Tesis: C# & 100% 'ok' \"x\" #1 - {a} [b]"
        modelo = core.construir_modelo(doc)
        core.fijar_campo(modelo["secciones"][1]["entradas"][0]["valor"], "position", peligroso)
        core.sincronizar_doc(modelo)
        recargado = core.cargar_yaml(core.volcar_yaml(modelo["doc"]))
        self.assertEqual(recargado["cv"]["sections"]["Experiencia Laboral"][0]["position"], peligroso)

    def test_entradas_vacias_no_se_escriben(self):
        doc = core.cargar_yaml(PLANTILLA)
        modelo = core.construir_modelo(doc)
        nueva = core.nueva_seccion("experiencia", "Voluntariado")
        nueva["entradas"].append(core.nueva_entrada("experiencia"))
        modelo["secciones"].append(nueva)
        core.sincronizar_doc(modelo)
        self.assertNotIn("Voluntariado", modelo["doc"]["cv"]["sections"])

    def test_renombrar_seccion_mantiene_ajustes_de_diseno(self):
        doc = core.cargar_yaml(PLANTILLA)
        modelo = core.construir_modelo(doc)
        modelo["secciones"][1]["titulo"] = "Trayectoria"
        core.sincronizar_doc(modelo)
        self.assertEqual(list(modelo["doc"]["design"]["sections"]["show_time_spans_in"]), ["Trayectoria"])

    def test_secciones_duplicadas_se_rechazan_antes_de_perder_datos(self):
        modelo = core.construir_modelo(core.cargar_yaml(PLANTILLA))
        modelo["secciones"][1]["titulo"] = modelo["secciones"][2]["titulo"].upper()
        self.assertTrue(core.errores_modelo(modelo))

    def test_mover_y_eliminar(self):
        lista = [{"uid": "a"}, {"uid": "b"}, {"uid": "c"}]
        core.mover(lista, "a", -1)
        self.assertEqual([x["uid"] for x in lista], ["a", "b", "c"])
        core.mover(lista, "c", 1)
        self.assertEqual([x["uid"] for x in lista], ["a", "b", "c"])
        core.mover(lista, "b", 1)
        self.assertEqual([x["uid"] for x in lista], ["a", "c", "b"])
        core.eliminar(lista, "c")
        self.assertEqual([x["uid"] for x in lista], ["a", "b"])

    def test_fijar_campo_no_altera_tipo_si_no_cambio(self):
        doc = core.cargar_yaml("cv:\n  name: A\n  sections:\n    E:\n      - company: X\n        position: Y\n        start_date: 2020\n")
        entrada = doc["cv"]["sections"]["E"][0]
        core.fijar_campo(entrada, "start_date", "2020")
        self.assertIsInstance(entrada["start_date"], int)

    def test_lista_de_correos_se_conserva(self):
        doc = core.cargar_yaml("cv:\n  email:\n    - a@x.com\n    - b@x.com\n")
        core.fijar_contacto(doc["cv"], "email", "a@x.com, b@x.com")
        self.assertEqual(list(doc["cv"]["email"]), ["a@x.com", "b@x.com"])
        core.fijar_contacto(doc["cv"], "email", "a@x.com, c@x.com")
        self.assertEqual(list(doc["cv"]["email"]), ["a@x.com", "c@x.com"])

    def test_plantilla_con_nombre_peligroso(self):
        texto = core.yaml_desde_plantilla(PLANTILLA, "Ana: #1 'Ruiz'", "ink")
        doc = core.cargar_yaml(texto)
        self.assertEqual(doc["cv"]["name"], "Ana #1 'Ruiz'")
        self.assertEqual(doc["design"]["theme"], "ink")
        self.assertTrue(core.guardar_y_renderizar(self.yaml, texto).ok)

    def test_nombre_con_caracteres_prohibidos_en_windows_compila(self):
        for nombre in ('Ana: Ruiz', 'A/B\\C', 'Ana*?"<>|'):
            doc = core.documento_en_blanco(nombre)
            r = core.guardar_y_renderizar(self.yaml, core.documento_a_yaml(doc))
            self.assertTrue(r.ok, f"{nombre}: {r.log} {r.errores}")

    def test_fijar_ruta_limpia_padres_vacios(self):
        doc = core.cargar_yaml("cv:\n  name: A\n")
        core.fijar_ruta(doc, ("design", "colors", "name"), "#112233")
        self.assertEqual(core.obtener_ruta(doc, ("design", "colors", "name")), "#112233")
        core.fijar_ruta(doc, ("design", "colors", "name"), None)
        self.assertNotIn("design", doc)


class TestValidacion(BaseTemporal):
    def _ubicaciones(self, texto):
        return core.validar_yaml(texto, self.yaml)

    def test_plantilla_valida(self):
        self.assertEqual(self._ubicaciones(PLANTILLA), [])

    def test_errores_en_espanol_y_ubicados(self):
        errores = self._ubicaciones(
            "cv:\n  name: A\n  sections:\n    Exp:\n      - position: B\n        start_date: ayer\n"
        )
        textos = [str(e) for e in errores]
        self.assertTrue(any("Exp › Entrada 1 › Empresa" in t and "obligatorio" in t for t in textos), textos)
        self.assertTrue(any("Fecha de inicio" in t and "no válida" in t for t in textos), textos)
        self.assertFalse(any("There are problems" in t for t in textos), textos)

    def test_los_nueve_temas_aceptan_los_ajustes_del_editor(self):
        for tema in ("classic", "moderncv", "harvard", "engineeringresumes", "engineeringclassic", "sb2nov", "ember", "ink", "opal"):
            doc = core.documento_en_blanco("Ana", tema)
            for ruta in (("design", "colors", "name"), ("design", "colors", "section_titles"), ("design", "colors", "links")):
                core.fijar_ruta(doc, ruta, "#112233")
            core.fijar_ruta(doc, ("design", "typography", "font_family"), "Lato")
            self.assertEqual(self._ubicaciones(core.documento_a_yaml(doc)), [], tema)

    def test_yaml_roto_no_lanza_excepcion(self):
        self.assertTrue(self._ubicaciones("cv: [roto"))

    def test_sin_tema_no_lanza_excepcion(self):
        self.assertTrue(isinstance(self._ubicaciones("cv:\n  name: A\ndesign:\n  typography:\n    font_family:\n      body: Lato\n"), list))


class TestGuardado(BaseTemporal):
    def test_yaml_invalido_no_toca_el_archivo(self):
        r = core.guardar_y_renderizar(self.yaml, "cv: [roto")
        self.assertFalse(r.ok)
        self.assertEqual(self.yaml.read_text(encoding="utf-8"), PLANTILLA)
        self.assertEqual(core.listar_versiones(self.yaml), [])

    def test_guardar_deja_version_recuperable(self):
        doc = core.cargar_yaml(PLANTILLA)
        doc["cv"]["name"] = "Ana Ruiz"
        r = core.guardar_y_renderizar(self.yaml, core.volcar_yaml(doc))
        self.assertTrue(r.ok, r.log)
        versiones = core.listar_versiones(self.yaml)
        self.assertEqual(len(versiones), 1)
        self.assertEqual(versiones[0].read_text(encoding="utf-8"), PLANTILLA)

    def test_autoguardado_no_crea_una_version_por_tecla(self):
        for nombre in ("A", "B", "C"):
            self.yaml.write_text(PLANTILLA + f"# {nombre}\n", encoding="utf-8")
            core.guardar_version(self.yaml, intervalo_minimo_s=300)
        self.assertEqual(len(core.listar_versiones(self.yaml)), 1)

    def test_el_historial_tiene_tope(self):
        for i in range(core.MAX_VERSIONES + 5):
            self.yaml.write_text(PLANTILLA + f"# {i}\n", encoding="utf-8")
            core.guardar_version(self.yaml)
        self.assertEqual(len(core.listar_versiones(self.yaml)), core.MAX_VERSIONES)

    def test_el_historial_no_se_confunde_con_el_cv(self):
        core.guardar_version(self.yaml)
        self.assertEqual(list(self.dir.glob("*.yaml")), [self.yaml])

    def test_renombrar_no_mezcla_paginas_antiguas(self):
        self.assertTrue(core.renderizar(self.yaml).ok)
        doc = core.cargar_yaml(PLANTILLA)
        doc["cv"]["name"] = "Ana Ruiz"
        r = core.guardar_y_renderizar(self.yaml, core.volcar_yaml(doc))
        self.assertTrue(r.ok)
        nombres = [p.name for p in (self.dir / "rendercv_output").iterdir()]
        self.assertTrue(all(n.startswith("Ana_Ruiz") for n in nombres), nombres)

    def test_render_fallido_conserva_el_ultimo_pdf(self):
        self.assertTrue(core.renderizar(self.yaml).ok)
        pdf, _ = core.archivos_salida(self.dir)
        antes = pdf.read_bytes()
        self.yaml.write_text("cv: [roto", encoding="utf-8")
        self.assertFalse(core.renderizar(self.yaml).ok)
        self.assertEqual(core.archivos_salida(self.dir)[0].read_bytes(), antes)

    @unittest.skipUnless(sys.platform == "win32", "El bloqueo de archivos abiertos es propio de Windows")
    def test_pdf_abierto_avisa_y_actualiza_lo_demas(self):
        self.assertTrue(core.renderizar(self.yaml).ok)
        pdf, _ = core.archivos_salida(self.dir)
        with open(pdf, "rb"):
            r = core.renderizar(self.yaml)
        self.assertTrue(r.ok)
        self.assertTrue(any("abierto" in a for a in r.avisos), r.avisos)

    def test_contenido_con_simbolos_compila(self):
        doc = core.cargar_yaml(PLANTILLA)
        modelo = core.construir_modelo(doc)
        entrada = modelo["secciones"][1]["entradas"][0]["valor"]
        core.fijar_campo(entrada, "highlights", "C# & $100 <b>x</b> _y_ @user #tag 100% ~a ^b\n[REVISAR] Dato: ñandú 日本語 🚀")
        core.sincronizar_doc(modelo)
        r = core.guardar_y_renderizar(self.yaml, core.volcar_yaml(modelo["doc"]))
        self.assertTrue(r.ok, r.log + str(r.errores))

    def test_hashtag_compila_y_se_lee_igual_en_el_pdf(self):
        from pypdf import PdfReader

        doc = core.cargar_yaml(PLANTILLA)
        modelo = core.construir_modelo(doc)
        core.fijar_campo(modelo["secciones"][1]["entradas"][0]["valor"], "highlights", 'Campaña #MeToo y #read("x")')
        core.sincronizar_doc(modelo)
        r = core.guardar_y_renderizar(self.yaml, core.volcar_yaml(modelo["doc"]))
        self.assertTrue(r.ok, r.log + str(r.errores))
        texto = " ".join(p.extract_text() for p in PdfReader(r.pdf).pages).replace("\u2060", "")
        self.assertIn("#MeToo", texto)

    def test_comando_typst_existente_no_se_altera_si_no_se_edita(self):
        doc = core.cargar_yaml("cv:\n  sections:\n    E:\n      - company: X\n        position: Y\n        highlights:\n          - '#strong[a]'\n")
        entrada = doc["cv"]["sections"]["E"][0]
        core.fijar_campo(entrada, "highlights", "#strong[a]")
        self.assertEqual(list(entrada["highlights"]), ["#strong[a]"])

    def test_error_de_compilacion_explica_la_causa(self):
        texto = PLANTILLA.replace("- Graduado con honores (Cum Laude)", "- '#noexiste'")
        r = core.guardar_y_renderizar(self.yaml, texto)
        self.assertFalse(r.ok)
        self.assertIn("noexiste", str(r.errores[0]))
        self.assertEqual(self.yaml.read_text(encoding="utf-8"), PLANTILLA)

    def test_foto_valida_y_falsa(self):
        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (200, 260), "navy").save(buf, "PNG")
        nombre_foto = core.guardar_foto(self.dir, buf.getvalue())
        self.assertRegex(nombre_foto, r"^foto_[0-9a-f]{12}\.png$")
        with self.assertRaises(ValueError):
            core.guardar_foto(self.dir, b"esto no es una imagen")
        doc = core.cargar_yaml(PLANTILLA)
        doc["cv"]["photo"] = nombre_foto
        self.assertTrue(core.guardar_y_renderizar(self.yaml, core.volcar_yaml(doc)).ok)


class TestImportacionLocal(BaseTemporal):
    def _doc(self, texto):
        salida = core.parser_heuristico_a_yaml(texto)
        self.assertEqual(core.validar_yaml(salida, self.yaml), [], salida)
        return core.cargar_yaml(salida)

    def test_no_inventa_datos(self):
        cv = self._doc("Ana Ruiz\nLideré un equipo comercial de ventas regional")["cv"]
        self.assertEqual(cv["name"], "Ana Ruiz")
        for campo in ("email", "phone", "location", "headline"):
            self.assertNotIn(campo, cv)
        self.assertNotIn("Habilidades Técnicas", cv["sections"])
        self.assertNotIn("start_date", cv["sections"]["Experiencia Laboral"][0])

    def test_entrada_con_caracteres_que_rompian_el_yaml(self):
        cv = self._doc("Nombre: Ana #1 Ruiz\nana@x.com\nLogro: subí ventas 'mucho' en 20% durante 2021")["cv"]
        self.assertEqual(cv["name"], "Ana #1 Ruiz")
        self.assertEqual(cv["email"], "ana@x.com")
        self.assertIn("Logro: subí ventas 'mucho' en 20% durante 2021", cv["sections"]["Perfil Profesional"])

    def test_salta_titulos_y_lineas_de_contacto(self):
        cv = self._doc("HOJA DE VIDA\nana@x.com\n310 555 1234\nAna Ruiz\nProfesional en administración de empresas")["cv"]
        self.assertEqual(cv["name"], "Ana Ruiz")

    def test_detecta_contacto(self):
        cv = self._doc("Ana Ruiz\n300 123 4567\nlinkedin.com/in/ana-r\ngithub.com/anar\nProfesional en administración")["cv"]
        self.assertEqual(cv["phone"].replace(" ", ""), "+573001234567")
        self.assertEqual({r["network"] for r in cv["social_networks"]}, {"LinkedIn", "GitHub"})

    def test_texto_vacio(self):
        self.assertIn("[REVISAR]", self._doc("")["cv"]["name"])

    def test_lo_marcado_se_detecta_antes_de_entregar(self):
        doc = self._doc("Ana Ruiz\nProfesional en administración de empresas")
        self.assertTrue(any(r["nivel"] == "bloqueante" and "[REVISAR]" in r["texto"] for r in core.revisar_entrega(doc)))


class TestRevision(unittest.TestCase):
    def _niveles(self, doc, paginas=1):
        return core.revisar_entrega(doc, paginas)

    def test_detecta_restos_de_la_plantilla_en_cliente_real(self):
        doc = core.cargar_yaml(PLANTILLA)
        doc["cv"]["name"] = "Rosa Quintero"
        self.assertTrue(any(r["nivel"] == "bloqueante" and "juan.perez" in r["texto"] for r in self._niveles(doc)))

    def test_cv_completo_sin_bloqueantes(self):
        doc = core.cargar_yaml(
            "cv:\n  name: Ana\n  email: a@x.com\n  phone: '+573001234567'\n  location: Cali\n  sections:\n"
            "    Perfil:\n      - Texto\n    Exp:\n      - company: X\n        position: Y\n        start_date: 2020\n"
            "        highlights:\n          - Subí 20%\n    Edu:\n      - institution: U\n        area: Z\n"
        )
        self.assertEqual([r for r in self._niveles(doc) if r["nivel"] == "bloqueante"], [])

    def test_fechas_invertidas(self):
        doc = core.cargar_yaml("cv:\n  sections:\n    E:\n      - company: X\n        position: Y\n        start_date: 2022-03\n        end_date: 2020-01\n")
        self.assertTrue(any("posterior" in r["texto"] for r in self._niveles(doc)))

    def test_documento_vacio_no_falla(self):
        self.assertTrue(self._niveles({"cv": {}}, 0))


if __name__ == "__main__":
    unittest.main()

"""Pruebas de la app completa sobre una COPIA en carpeta temporal: los clientes reales no se tocan."""

import shutil
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = (RAIZ / "plantillas" / "plantilla_base_es.yaml").read_text(encoding="utf-8")


class BaseApp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rcv_app_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        for nombre in ("app.py", "cv_core.py", "editor_visual.py"):
            shutil.copy(RAIZ / nombre, self.dir / nombre)
        shutil.copytree(RAIZ / "plantillas", self.dir / "plantillas")
        (self.dir / "catalogo_temas").mkdir()
        self.carpeta = self.dir / "clientes" / "demo"
        self.carpeta.mkdir(parents=True)
        self.yaml = self.carpeta / "Demo_CV.yaml"
        self.yaml.write_text(PLANTILLA, encoding="utf-8")
        self.at = AppTest.from_file(str(self.dir / "app.py"), default_timeout=120).run()
        self.assertEqual([e.value for e in self.at.exception], [])

    def texto(self):
        return self.yaml.read_text(encoding="utf-8")

    def por_etiqueta(self, coleccion, etiqueta):
        return [w for w in coleccion if etiqueta in w.label]

    def boton(self, etiqueta):
        return self.por_etiqueta(self.at.button, etiqueta)[0]

    def correr(self):
        self.at.run()
        self.assertEqual([e.value for e in self.at.exception], [])


class TestEditorVisual(BaseApp):
    def test_abrir_no_modifica_el_archivo(self):
        self.assertEqual(self.texto(), PLANTILLA)
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.assertFalse((self.carpeta / "historial").exists())

    def test_editar_guarda_y_actualiza_el_pdf(self):
        # Los dos puntos no pueden ir en un nombre de archivo de Windows: se limpian.
        self.por_etiqueta(self.at.text_input, "Nombre completo")[0].set_value("Ana: #1 Ruiz")
        self.correr()
        self.assertIn("name: 'Ana #1 Ruiz'", self.texto())
        self.assertIn("pdf_title: 'Ana #1 Ruiz - Hoja de Vida'", self.texto())
        nombres = [p.name for p in (self.carpeta / "rendercv_output").glob("*.pdf")]
        self.assertEqual(len(nombres), 1, nombres)
        self.assertIn("Ana", nombres[0])

    def test_dato_invalido_no_se_escribe_y_se_explica(self):
        self.por_etiqueta(self.at.text_input, "Correo")[0].set_value("no-es-un-correo")
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.assertTrue(any("Correo no válido" in w.value for w in self.at.warning))
        self.por_etiqueta(self.at.text_input, "Correo")[0].set_value("ana@correo.com")
        self.correr()
        self.assertIn("email: ana@correo.com", self.texto())
        self.assertFalse(any("Correo no válido" in w.value for w in self.at.warning))

    def test_telefono_colombiano_sin_indicativo(self):
        self.por_etiqueta(self.at.text_input, "Teléfono")[0].set_value("3109876543")
        self.correr()
        self.assertIn("phone: +57 310 9876543", self.texto())

    def test_agregar_red_y_pegar_url(self):
        antes = self.texto().count("network:")
        self.boton("Agregar red social").click()
        self.correr()
        self.assertEqual(self.texto().count("network:"), antes)
        fila = [t for t in self.at.text_input if t.placeholder == "Usuario o enlace del perfil"][-1]
        fila.set_value("https://www.linkedin.com/in/ana-ruiz/")
        self.correr()
        self.assertIn("username: ana-ruiz", self.texto())

    def _abrir(self, inicio):
        boton = [b for b in self.at.button if b.label.startswith(inicio)][0]
        boton.click()
        self.correr()

    def test_editar_experiencia_con_fecha_natural_y_logros(self):
        self._abrir("Arquitecto de Software Líder")
        self.por_etiqueta(self.at.text_input, "Fecha de inicio")[0].set_value("marzo de 2021")
        self.por_etiqueta(self.at.text_area, "Logros")[0].set_value("- Primer logro: con dos puntos\n• Segundo logro")
        self.correr()
        texto = self.texto()
        self.assertIn("start_date: 2021-03", texto)
        self.assertIn("- 'Primer logro: con dos puntos'", texto)
        self.assertIn("- Segundo logro", texto)
        self.assertNotIn("Diseñé y lideré la migración", texto)

    def test_marcar_y_desmarcar_trabajo_actual(self):
        self._abrir("Ingeniero Backend Senior")
        iniciales = PLANTILLA.count("end_date: present")
        self.por_etiqueta(self.at.checkbox, "Trabajo aquí")[0].check()
        self.correr()
        self.assertEqual(self.texto().count("end_date: present"), iniciales + 1)
        self.por_etiqueta(self.at.checkbox, "Trabajo aquí")[0].uncheck()
        self.correr()
        self.assertEqual(self.texto().count("end_date: present"), iniciales)
        self.assertNotIn("2022-02", self.texto().split("InnovaSoft")[0].split("Finanzas Digitales")[1])

    def test_agregar_entrada_incompleta_avisa_y_no_escribe(self):
        self.por_etiqueta(self.at.button, "Agregar")
        agregar = [b for b in self.at.button if b.label == "Agregar"][1]  # Experiencia
        agregar.click()
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.por_etiqueta(self.at.text_input, "Empresa *")[0].set_value("Solo empresa")
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.assertTrue(any("Cargo" in w.value and "obligatorio" in w.value for w in self.at.warning))
        self.por_etiqueta(self.at.text_input, "Cargo *")[0].set_value("Analista")
        self.correr()
        self.assertIn("company: Solo empresa", self.texto())

    def test_mover_y_eliminar_entrada(self):
        pos = lambda t: self.texto().index(t)
        self.assertLess(pos("TechNova"), pos("Finanzas Digitales"))
        # Fila de la primera experiencia: abrir, subir, bajar, quitar
        indice = next(i for i, b in enumerate(self.at.button) if b.label.startswith("Arquitecto de Software"))
        self.at.button[indice + 2].click()
        self.correr()
        self.assertGreater(pos("TechNova"), pos("Finanzas Digitales"))
        indice = next(i for i, b in enumerate(self.at.button) if b.label.startswith("Arquitecto de Software"))
        self.at.button[indice + 3].click()
        self.correr()
        self.assertNotIn("TechNova", self.texto())
        self.assertIn("Finanzas Digitales", self.texto())

    def test_eliminar_todas_las_secciones_y_restaurar(self):
        while True:
            botones = self.por_etiqueta(self.at.button, "Sí, eliminar")
            if not botones:
                break
            botones[0].click()
            self.correr()
        self.assertNotIn("sections:\n    Perfil", self.texto())
        self.assertTrue(self.por_etiqueta(self.at.button, "Crear estructura típica"))
        self.boton("Restaurar esta versión").click()
        self.correr()
        self.assertIn("TechNova", self.texto())

    def test_titulos_duplicados_bloquean_el_guardado(self):
        titulos = [t for t in self.at.text_input if t.label == "Título de la sección"]
        titulos[1].set_value(titulos[2].value)
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.assertTrue(any("dos secciones" in w.value for w in self.at.warning))

    def test_cambios_de_diseno(self):
        self.boton("Harvard").click()
        self.correr()
        self.assertIn("theme: harvard", self.texto())
        self.por_etiqueta(self.at.selectbox, "Tipografía")[0].set_value("Lato")
        self.por_etiqueta(self.at.selectbox, "Tamaño de página")[0].set_value("us-letter")
        self.correr()
        self.assertIn("font_family: Lato", self.texto())
        self.assertIn("size: us-letter", self.texto())
        self.por_etiqueta(self.at.toggle, "Color de acento")[0].set_value(True)
        self.correr()
        self.assertIn("section_titles: '#1e3a8a'", self.texto())
        self.por_etiqueta(self.at.toggle, "Color de acento")[0].set_value(False)
        self.correr()
        self.assertNotIn("section_titles", self.texto())
        self.por_etiqueta(self.at.slider, "Márgenes")[0].set_value(2.0)
        self.correr()
        self.assertEqual(self.texto().count("2.0cm"), 4)

    def test_cliente_en_blanco_con_estructura_tipica(self):
        self.yaml.write_text("cv:\n  name: Ana\n", encoding="utf-8")
        self.correr()
        self.boton("Crear estructura típica").click()
        self.correr()
        self.assertEqual(self.texto(), "cv:\n  name: Ana\n")
        self.por_etiqueta(self.at.text_area, "Texto")[0].set_value("Mi perfil profesional")
        self.correr()
        self.assertIn("Perfil Profesional:", self.texto())
        self.assertNotIn("Experiencia Laboral:", self.texto())

    def test_sin_guardado_automatico_exige_boton(self):
        self.at.toggle(key="ve_auto").set_value(False)
        self.correr()
        self.por_etiqueta(self.at.text_input, "Ciudad y país")[0].set_value("Cali")
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.at.button(key="ve_forzar").click()
        self.correr()
        self.assertIn("location: Cali", self.texto())

    def test_archivo_roto_no_tumba_la_app_y_se_puede_arreglar(self):
        self.yaml.write_text("cv: [roto", encoding="utf-8")
        self.correr()
        self.assertTrue(any("YAML y Kit" in e.value for e in self.at.error))


class TestYamlAvanzado(BaseApp):
    def _area(self):
        return self.por_etiqueta(self.at.text_area, "Código YAML")[0]

    def test_tema_rapido_no_se_revierte_al_guardar(self):
        self.at.sidebar.selectbox[2].set_value("harvard")
        self.por_etiqueta(self.at.sidebar.button, "Re-generar")[0].click()
        self.correr()
        self.assertIn("theme: harvard", self.texto())
        self.boton("Guardar y Actualizar").click()
        self.correr()
        self.assertIn("theme: harvard", self.texto())

    def test_yaml_invalido_no_destruye_el_archivo(self):
        self._area().set_value("cv: [roto")
        self.boton("Guardar y Actualizar").click()
        self.correr()
        self.assertEqual(self.texto(), PLANTILLA)
        self.assertTrue(self.at.error)

    def test_cambio_en_yaml_se_refleja_en_el_editor_visual(self):
        self._area().set_value(PLANTILLA.replace("headline: Ingeniero de Software Senior & Arquitecto Cloud", "headline: Nuevo titulo"))
        self.boton("Guardar y Actualizar").click()
        self.correr()
        self.assertEqual(self.por_etiqueta(self.at.text_input, "Título profesional")[0].value, "Nuevo titulo")

    def test_cambio_visual_se_refleja_en_yaml(self):
        self.por_etiqueta(self.at.text_input, "Ciudad y país")[0].set_value("Pasto, Colombia")
        self.correr()
        self.assertIn("location: Pasto, Colombia", self._area().value)

    def test_pack_de_disenos(self):
        self.boton("Generar Pack").click()
        self.correr()
        pdfs = list((self.carpeta / "variantes_temas").glob("*.pdf"))
        self.assertEqual(len(pdfs), 9)
        self.assertFalse(self.at.error)
        self.assertEqual(len(list((self.carpeta / "rendercv_output").glob("*.typ"))), 1)


class TestCreacion(BaseApp):
    def test_cliente_nuevo_en_blanco_y_homonimo_no_se_pisa(self):
        for _ in range(2):
            self.at.sidebar.text_input[0].set_value("José Muñoz")
            self.por_etiqueta(self.at.sidebar.button, "Crear Cliente")[0].click()
            self.correr()
        primero = self.dir / "clientes" / "jose_munoz" / "Jose_Munoz_CV.yaml"
        segundo = self.dir / "clientes" / "jose_munoz_2" / "Jose_Munoz_CV.yaml"
        self.assertTrue(primero.exists() and segundo.exists())
        self.assertNotIn("juan.perez", primero.read_text(encoding="utf-8"))
        self.assertEqual(self.at.session_state["cliente_actual"], "jose_munoz_2")
        self.assertEqual(self.por_etiqueta(self.at.text_input, "Nombre completo")[0].value, "José Muñoz")

    def test_formulario_vacio_no_crea_cliente_falso(self):
        self.por_etiqueta(self.at.button, "Crear Cliente y Generar")[0].click()
        self.correr()
        self.assertEqual([d.name for d in (self.dir / "clientes").iterdir()], ["demo"])
        self.assertTrue(any("nombre" in e.value for e in self.at.error))

    def test_formulario_con_datos_minimos(self):
        self.por_etiqueta(self.at.text_input, "Nombre Completo")[0].set_value("Ana Ruiz")
        self.por_etiqueta(self.at.text_input, "Empresa #1")[0].set_value("Acme")
        self.por_etiqueta(self.at.text_input, "Cargo #1")[0].set_value("Analista")
        self.por_etiqueta(self.at.text_input, "Fecha Inicio #1")[0].set_value("marzo 2021")
        self.por_etiqueta(self.at.button, "Crear Cliente y Generar")[0].click()
        self.correr()
        creado = (self.dir / "clientes" / "ana_ruiz" / "Ana_Ruiz_CV.yaml").read_text(encoding="utf-8")
        self.assertIn("start_date: 2021-03", creado)
        self.assertNotIn("end_date", creado)
        self.assertNotIn("2020-01", creado)
        self.assertEqual(self.at.session_state["cliente_actual"], "ana_ruiz")

    def test_importar_texto_sin_ia(self):
        self.por_etiqueta(self.at.text_area, "pega directamente")[0].set_value(
            "Nombre: Ana Ruiz\nana@x.com\nLogro: subí ventas 20% en la región andina\nCoordiné un equipo de 8 personas en campo"
        )
        self.por_etiqueta(self.at.button, "Convertir a Formato ATS")[0].click()
        self.correr()
        creado = (self.dir / "clientes" / "ana_ruiz" / "Ana_Ruiz_CV.yaml").read_text(encoding="utf-8")
        self.assertIn("email: ana@x.com", creado)
        self.assertNotIn("+57 300", creado)
        self.assertEqual(self.at.session_state["cliente_actual"], "ana_ruiz")


if __name__ == "__main__":
    unittest.main()

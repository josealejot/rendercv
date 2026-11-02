"""Regresiones de la auditoría independiente: una prueba por defecto reproducido (D1...D21)."""

import io
import os
import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv_core as core  # noqa: E402
from test_app_flujos import BaseApp  # noqa: E402


def yaml_cliente(nombre):
    return (
        f"cv:\n  name: {nombre}\n  email: a@x.com\n  location: Lima\n  sections:\n"
        "    Perfil:\n      - Texto del perfil\n"
        "    Experiencia:\n      - company: Acme\n        position: Analista\n        start_date: 2020-01\n"
        "    Educacion:\n      - institution: U\n        area: Z\n"
        "locale:\n  language: spanish\n"
    )


class BaseVarios(BaseApp):
    def setUp(self):
        super().setUp()
        self.rutas = {}
        for nombre in ("aaa", "bbb", "ccc"):
            carpeta = self.dir / "clientes" / nombre
            carpeta.mkdir()
            self.rutas[nombre] = carpeta / f"{nombre}_CV.yaml"
            self.rutas[nombre].write_text(yaml_cliente(nombre), encoding="utf-8")
        self.correr()

    def elegir(self, cliente):
        self.at.sidebar.selectbox[0].set_value(cliente)
        self.correr()

    def campo(self, etiqueta):
        return self.por_etiqueta(self.at.text_input, etiqueta)[0]


class TestAltas(BaseVarios):
    def test_d1_reordenar_secciones_se_guarda(self):
        self.elegir("aaa")
        titulos = [t for t in self.at.text_input if t.label == "Título de la sección"]
        self.assertEqual(titulos[0].value, "Perfil")
        baja = next(b for b in self.at.button if b.key and b.key.endswith("_bajar") and b.help == "Bajar sección")
        baja.click()
        self.correr()
        doc = core.cargar_yaml(self.rutas["aaa"].read_text(encoding="utf-8"))
        self.assertEqual(list(doc["cv"]["sections"]), ["Experiencia", "Perfil", "Educacion"])
        self.assertTrue(core.listar_versiones(self.rutas["aaa"]))

    def test_d2_cambiar_de_cliente_conserva_lo_pendiente(self):
        self.elegir("aaa")
        self.campo("Ciudad y país").set_value("Cali")
        self.campo("Correo").set_value("malo")
        self.correr()
        self.elegir("bbb")
        self.assertEqual(self.at.session_state["cliente_actual"], "bbb")
        self.assertTrue(any("aaa" in w.value for w in self.at.warning), "debe avisar del pendiente en aaa")
        self.elegir("aaa")
        self.assertEqual(self.campo("Ciudad y país").value, "Cali")
        self.assertEqual(self.campo("Correo").value, "malo")

    def test_d2_cambio_externo_rescata_lo_pendiente(self):
        self.elegir("aaa")
        self.campo("Correo").set_value("malo")
        self.campo("Ciudad y país").set_value("Cali")
        self.correr()
        self.rutas["aaa"].write_text(yaml_cliente("aaa").replace("Lima", "Quito"), encoding="utf-8")
        self.correr()
        self.assertTrue(any("cambió fuera del editor" in w.value for w in self.at.warning))
        self.assertEqual(self.campo("Ciudad y país").value, "Quito")
        borrador = core.listar_versiones(self.rutas["aaa"])[0]
        self.assertIn("borrador", borrador.name)
        self.assertIn("Cali", borrador.read_text(encoding="utf-8"))

    def test_d2_borrador_invalido_se_puede_retomar(self):
        self.elegir("aaa")
        self.campo("Correo").set_value("malo")
        self.correr()
        self.rutas["aaa"].write_text(yaml_cliente("aaa").replace("Lima", "Quito"), encoding="utf-8")
        self.correr()
        self.boton("Restaurar esta versión").click()
        self.correr()
        self.assertEqual(self.campo("Correo").value, "malo")
        self.assertNotIn("malo", self.rutas["aaa"].read_text(encoding="utf-8"))

    def test_d3_borrar_tras_editar_deja_version_con_el_dato(self):
        self.elegir("aaa")
        self.campo("Ciudad y país").set_value("Primera edición")
        self.correr()
        abrir = next(b for b in self.at.button if b.label.startswith("Texto del perfil"))
        abrir.click()
        self.correr()
        self.por_etiqueta(self.at.text_area, "Texto")[0].set_value("Perfil corto")
        self.correr()
        self.assertIn("Perfil corto", self.rutas["aaa"].read_text(encoding="utf-8"))
        self.assertTrue(any(b.label.startswith("Perfil corto") for b in self.at.button), "el título debe actualizarse")
        next(b for b in self.at.button if b.help == "Quitar entrada").click()
        self.correr()
        self.assertNotIn("Perfil corto", self.rutas["aaa"].read_text(encoding="utf-8"))
        contenidos = [v.read_text(encoding="utf-8") for v in core.listar_versiones(self.rutas["aaa"])]
        self.assertTrue(any("Perfil corto" in c for c in contenidos))

    def test_d4_selector_obedece_todos_los_cambios(self):
        for pedido in ("bbb", "ccc", "aaa", "ccc", "bbb", "aaa"):
            self.elegir(pedido)
            self.assertEqual(self.at.session_state["cliente_actual"], pedido)
            self.assertEqual(self.campo("Nombre completo").value, pedido)

    def test_d5_archivo_nuevo_en_la_carpeta_no_cambia_el_que_se_edita(self):
        self.elegir("ccc")
        ruta = self.rutas["ccc"]
        otro = ruta.parent / "Ana_CV.yaml"
        otro.write_text(yaml_cliente("otra_persona"), encoding="utf-8")
        self.correr()
        self.assertEqual(self.campo("Nombre completo").value, "ccc")
        self.campo("Ciudad y país").set_value("Pasto")
        self.correr()
        self.assertIn("Pasto", ruta.read_text(encoding="utf-8"))
        self.assertNotIn("Pasto", otro.read_text(encoding="utf-8"))
        self.assertTrue(any("varios archivos" in s.label for s in self.at.sidebar.selectbox))

    def test_d5_historiales_separados_por_archivo(self):
        carpeta = self.rutas["aaa"].parent
        otro = carpeta / "Ana_CV.yaml"
        otro.write_text(yaml_cliente("otra"), encoding="utf-8")
        core.guardar_version(self.rutas["aaa"])
        self.assertEqual(core.listar_versiones(otro), [])
        self.assertEqual(len(core.listar_versiones(self.rutas["aaa"])), 1)


class TestMedias(BaseVarios):
    def test_d6_no_rompe_enlaces_ni_logros_no_editados(self):
        self.assertEqual(core.neutralizar_typst("[a](https://x.org/#p) y #tag"), "[a](https://x.org/#p) y #\u2060tag")
        entrada = core.cargar_yaml(
            "cv:\n  sections:\n    E:\n      - company: X\n        position: Y\n        highlights:\n"
            "          - '#emph[propio]'\n          - otro\n"
        )["cv"]["sections"]["E"][0]
        core.fijar_campo(entrada, "highlights", "#emph[propio]\notro cambiado")
        self.assertEqual(list(entrada["highlights"]), ["#emph[propio]", "otro cambiado"])
        publicacion = {"title": "T"}
        core.fijar_campo(publicacion, "url", "https://x.org/doc#otra")
        self.assertEqual(publicacion["url"], "https://x.org/doc#otra")

    def _pestana_yaml_viva(self):
        self.assertTrue(self.por_etiqueta(self.at.text_area, "Código YAML"))

    def test_d7_estructura_atipica_no_tumba_las_demas_pestanas(self):
        for texto in ("cv:\n  name: A\n  social_networks:\n    - texto\n", "cv:\n  name: A\n  sections:\n    - Perfil\n"):
            self.rutas["aaa"].write_text(texto, encoding="utf-8")
            self.elegir("aaa")
            self.assertTrue(self.at.error)
            self._pestana_yaml_viva()

    def test_d7_archivo_en_cp1252_se_abre(self):
        self.rutas["aaa"].write_bytes("cv:\n  name: José Ñandú\n".encode("cp1252"))
        self.elegir("aaa")
        self.assertEqual(self.campo("Nombre completo").value, "José Ñandú")
        self._pestana_yaml_viva()

    def test_d8_tema_rapido_no_altera_el_texto(self):
        texto = yaml_cliente("aaa").replace(
            "      - Texto del perfil\n", "      - |-\n        Mi lema\n        theme: liderazgo y estrategia\n"
        )
        self.rutas["aaa"].write_text(texto, encoding="utf-8")
        self.elegir("aaa")
        self.at.sidebar.selectbox[2].set_value("harvard")
        self.por_etiqueta(self.at.sidebar.button, "Re-generar")[0].click()
        self.correr()
        final = self.rutas["aaa"].read_text(encoding="utf-8")
        self.assertIn("theme: liderazgo y estrategia", final)
        self.assertEqual(core.cargar_yaml(final)["design"]["theme"], "harvard")

    def test_d9_kit_no_entrega_variantes_desactualizadas(self):
        import editor_visual
        import zipfile

        self.elegir("aaa")
        carpeta = self.rutas["aaa"].parent
        variantes = carpeta / "variantes_temas"
        variantes.mkdir()
        (variantes / "CV_ink.pdf").write_bytes(b"%PDF vieja")
        antiguo = time.time() - 100
        os.utime(variantes / "CV_ink.pdf", (antiguo, antiguo))
        nombres = zipfile.ZipFile(io.BytesIO(editor_visual.bytes_kit(carpeta))).namelist()
        self.assertFalse(any("CV_ink" in n for n in nombres))
        os.utime(variantes / "CV_ink.pdf")
        nombres = zipfile.ZipFile(io.BytesIO(editor_visual.bytes_kit(carpeta))).namelist()
        self.assertTrue(any("CV_ink" in n for n in nombres))

    def test_d10_conserva_comentarios(self):
        texto = yaml_cliente("aaa").replace("      - company: Acme", "      # NIT empresa 123\n      - company: Acme")
        texto = texto.replace("    Educacion:", "    # Revisar fechas\n    Educacion:")
        self.rutas["aaa"].write_text(texto, encoding="utf-8")
        self.elegir("aaa")
        self.campo("Ciudad y país").set_value("Cali")
        self.correr()
        final = self.rutas["aaa"].read_text(encoding="utf-8")
        self.assertIn("location: Cali", final)
        self.assertIn("# NIT empresa 123", final)
        self.assertIn("# Revisar fechas", final)

    def test_d11_abrir_sin_editar_no_reescribe(self):
        texto = (
            "cv:\n  name: A\n  sections:\n    Vacia:\n    E:\n      - company: X\n        position: Y\n"
            "        summary: |\n          Resumen en bloque\n        highlights:\n          - |\n            Logro en bloque\n"
            "settings:\n  bold_keywords:\n    - Ventas, Marketing\n"
        )
        self.rutas["aaa"].write_text(texto, encoding="utf-8")
        self.elegir("aaa")
        abrir = next(b for b in self.at.button if b.label.startswith("Y · X"))
        abrir.click()
        self.correr()
        self.correr()
        self.assertEqual(self.rutas["aaa"].read_text(encoding="utf-8"), texto)
        self.assertEqual(core.listar_versiones(self.rutas["aaa"]), [])

    def test_d12_texto_yaml_sin_guardar_se_rescata(self):
        self.elegir("aaa")
        caja = self.por_etiqueta(self.at.text_area, "Código YAML")[0]
        caja.set_value(yaml_cliente("aaa") + "# nota sin guardar\n")
        self.correr()
        self.campo("Ciudad y país").set_value("Cali")
        self.correr()
        contenidos = [v.read_text(encoding="utf-8") for v in core.listar_versiones(self.rutas["aaa"])]
        self.assertTrue(any("nota sin guardar" in c for c in contenidos))
        self.assertTrue(any("sin guardar" in w.value for w in self.at.warning))

    def test_d13_foto_nueva_no_pisa_la_anterior(self):
        from PIL import Image

        def png(color):
            b = io.BytesIO()
            Image.new("RGB", (50, 60), color).save(b, "PNG")
            return b.getvalue()

        carpeta = self.rutas["aaa"].parent
        a = core.guardar_foto(carpeta, png("red"))
        b = core.guardar_foto(carpeta, png("blue"))
        self.assertNotEqual(a, b)
        self.assertTrue((carpeta / a).exists() and (carpeta / b).exists())

    def test_d14_sin_fecha_de_fin_se_explica(self):
        self.elegir("aaa")
        next(b for b in self.at.button if b.label.startswith("Analista")).click()
        self.correr()
        self.assertTrue(any("presente" in c.value for c in self.at.caption))

    def test_d15_formulario_limpia_nombre_y_hashtags(self):
        self.por_etiqueta(self.at.text_input, "Nombre Completo")[0].set_value("Ana: #Ruiz")
        self.por_etiqueta(self.at.text_area, "Perfil Profesional")[0].set_value("Experta en #marketing")
        self.por_etiqueta(self.at.button, "Crear Cliente y Generar")[0].click()
        self.correr()
        self.assertFalse(self.at.error, [e.value for e in self.at.error])
        carpeta = self.dir / "clientes" / self.at.session_state["cliente_actual"]
        self.assertTrue(list((carpeta / "rendercv_output").glob("*.pdf")))


class TestBajas(BaseVarios):
    def test_d16_autoguardado_no_se_reactiva(self):
        self.at.toggle(key="ve_auto").set_value(False)
        self.correr()
        sin_yaml = self.dir / "clientes" / "ddd"
        sin_yaml.mkdir()
        self.correr()
        self.elegir("ddd")
        self.elegir("aaa")
        self.assertFalse(self.at.toggle(key="ve_auto").value)

    def test_d17_no_recompila_en_cada_interaccion_y_muestra_la_causa(self):
        self.rutas["aaa"].write_text("cv:\n  name: A\n  sections:\n    P:\n      - '#noexiste'\n", encoding="utf-8")
        self.elegir("aaa")
        self.assertTrue(any("noexiste" in e.value for e in self.at.error))
        inicio = time.perf_counter()
        self.correr()
        self.assertLess(time.perf_counter() - inicio, 1.2, "no debe volver a compilar")

    def test_d18_idioma_refleja_el_predeterminado(self):
        self.rutas["aaa"].write_text("cv:\n  name: A\n", encoding="utf-8")
        self.elegir("aaa")
        self.assertEqual(self.por_etiqueta(self.at.selectbox, "Idioma de fechas")[0].value, "english")

    def test_d19_importar_respeta_el_nombre_indicado(self):
        self.por_etiqueta(self.at.text_area, "pega directamente")[0].set_value(
            "Ingeniera de Sistemas\nana@x.com\nProfesional en administración de empresas"
        )
        self.por_etiqueta(self.at.text_input, "Nombre del Cliente")[0].set_value("Laura Ruiz")
        self.por_etiqueta(self.at.button, "Convertir a Formato ATS")[0].click()
        self.correr()
        creado = (self.dir / "clientes" / "laura_ruiz" / "Laura_Ruiz_CV.yaml").read_text(encoding="utf-8")
        self.assertEqual(core.cargar_yaml(creado)["cv"]["name"], "Laura Ruiz")

    def test_d20_restaurar_siempre_muestra_lo_restaurado(self):
        self.elegir("aaa")
        self.campo("Ciudad y país").set_value("Cali")
        self.correr()
        self.campo("Correo").set_value("malo")
        self.correr()
        versiones = core.listar_versiones(self.rutas["aaa"])
        self.assertTrue(versiones)
        self.boton("Restaurar esta versión").click()
        self.correr()
        self.assertEqual(self.campo("Correo").value, "a@x.com")
        self.assertFalse(any("Correo no válido" in w.value for w in self.at.warning))

    def test_d21_lanzadores_fijan_localhost(self):
        for nombre in ("iniciar_app.bat", "iniciar_app.ps1"):
            self.assertIn("--server.address localhost", (RAIZ / nombre).read_text(encoding="utf-8"), nombre)


if __name__ == "__main__":
    unittest.main()

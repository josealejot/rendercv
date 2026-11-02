# 🚀 Emprendimiento de Hojas de Vida Profesionales (RenderCV Studio)

Bienvenido al espacio de trabajo configurado según el flujo del video oficial de **RenderCV**, optimizado para gestionar múltiples clientes y generar Hojas de Vida (CVs) de calidad editorial y compatibles con sistemas **ATS** (Applicant Tracking Systems) en cuestión de segundos.

---

## 🖌️ RenderCV Studio: la forma recomendada de trabajar

Abre `iniciar_app.bat` (o `.\iniciar_app.ps1`) y trabaja desde el navegador, sin tocar YAML. La app solo responde en este equipo; el motivo y cómo cambiarlo están en `.streamlit/config.toml`.

1. **Crea o importa el cliente** desde el menú izquierdo o la pestaña *Importar*. Un cliente homónimo crea una carpeta nueva (`ana_ruiz_2`): nunca reemplaza a otro.
2. **Edita en la pestaña *Editor*** con el PDF al lado:
   - **Datos personales:** contacto, redes y foto. `3001234567` pasa a `+57 300 1234567`, y si pegas el enlace de LinkedIn se queda con el usuario.
   - **Contenido:** secciones y entradas sin límite, para agregar, reordenar y eliminar. Acepta fechas como `03/2022`, `marzo de 2022` o `actual`.
   - **Diseño:** plantilla, color, tipografía, tamaño de página, márgenes y columna del título académico.
   - **Revisión:** avisa de datos de ejemplo o marcados `[REVISAR]`, contacto incompleto, fechas invertidas y logros sin cifras. Desde aquí también se restauran versiones anteriores.
3. **Entrega** con *PDF* o *Kit .zip*. El pack con los 9 diseños sigue en *YAML y Kit*.

**Qué protege tus datos:**

- Nada inválido se guarda: si un dato falla, el archivo y el último PDF siguen intactos y la app explica qué corregir.
- Antes de cada guardado queda una copia en `clientes/<cliente>/historial/` (las 30 más recientes; con autoguardado, una cada 5 minutos, y siempre que se borre contenido).
- El editor conserva los campos que no conoce.
- Si el PDF está abierto en otro programa no se puede actualizar; la app lo avisa: ciérralo y guarda de nuevo.

**Para desarrollo:**

```powershell
python -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"; python -m unittest discover -s tests
```

Las pruebas corren sobre copias temporales y no tocan `clientes/`. La lógica está en `cv_core.py`, la interfaz del editor en `editor_visual.py` y la integración en `app.py`.

---

## 🛠️ Herramientas y Extensiones Instaladas

Ya se han descargado, instalado y configurado en tu sistema:
1. **Motor Principal (`rendercv[full]` v2.8)**: Incluye el motor tipográfico **Typst**, colección completa de fuentes profesionales (`rendercv-fonts`), generador de PDF, PNG, HTML y Markdown, y el monitor en tiempo real (`watchdog`).
2. **Extensión `redhat.vscode-yaml`**: Autocompletado inteligente y validación en vivo del esquema de RenderCV mientras escribes los datos del cliente.
3. **Extensiones `wytheglobal.pdfmore` y `tomoki1207.pdf`**: Visores de PDF integrados dentro de VS Code / Antigravity IDE para ver la hoja de vida lado a lado mientras editas el YAML.
4. **Configuración Automática (`.vscode/settings.json`)**:
   - Auto-guardado activado (`afterDelay: 500ms`) para que el PDF se actualice instantáneamente al escribir sin necesidad de presionar `Ctrl+S`.
   - Validación automática contra el esquema oficial de RenderCV v2.8.
   - Codificación `PYTHONUTF8=1` configurada en Windows para soporte total de tildes y eñes.

---

## 📂 Estructura del Proyecto

```text
RENDER CV/
├── .vscode/                     # Configuración de auto-guardado, validación YAML y tareas rápidas
├── catalogo_temas/              # Muestras en PDF e imagen (PNG) de los 9 diseños disponibles
├── plantillas/
│   └── plantilla_base_es.yaml   # Plantilla maestra en español lista para clonar
├── clientes/
│   └── ejemplo_juan_perez/      # Cliente de ejemplo con su YAML y sus PDFs generados
├── app.py, editor_visual.py     # RenderCV Studio: la interfaz gráfica
├── cv_core.py                   # Lógica: validar, guardar con historial y compilar
├── tests/                       # Pruebas automáticas
├── respaldos/                   # Código previo al editor visual
├── nuevo_cliente.ps1            # Script para crear la carpeta y CV de un nuevo cliente en 1 comando
└── generar_todos_los_temas.ps1  # Script para generar el CV de un cliente en los 9 diseños a la vez
```

---

## ⚡ Flujo por Terminal (alternativa a la app)

### Paso 1: Crear un nuevo cliente
Abre la terminal en esta carpeta y ejecuta el script `nuevo_cliente.ps1` pasando el nombre de tu cliente y el tema deseado:

```powershell
.\nuevo_cliente.ps1 -Nombre "Maria Fernanda Lopez" -Tema "moderncv"
```
*(Si quieres que de inmediato quede actualizando en tiempo real mientras editas, agrégale `-ModoEnVivo` al final).*

Esto creará automáticamente:
- La carpeta `clientes/maria_fernanda_lopez/`
- El archivo `Maria_Fernanda_Lopez_CV.yaml` pre-configurado en español.
- La carpeta `rendercv_output/` con el primer PDF compilado.

### Paso 2: Edición en Tiempo Real (Lado a Lado) — Como en el Video
1. Abre el archivo `.yaml` del cliente en el editor.
2. Abre el archivo `.pdf` generado dentro de `rendercv_output/` y arrástralo al panel derecho del editor (dividir pantalla).
3. Activa el modo en vivo ejecutando en la terminal:
   ```powershell
   python -m rendercv render --watch "clientes/maria_fernanda_lopez/Maria_Fernanda_Lopez_CV.yaml"
   ```
   *(O presiona `Ctrl+Shift+B` desde el archivo YAML abierto para lanzar la tarea **RenderCV: Vista Previa en Vivo**).*
4. ¡Escribe cualquier cambio en el YAML y verás cómo el PDF se actualiza solo en milisegundos!

---

## 🎨 Catálogo de 9 Diseños (Temas Incluidos)

En la carpeta [`catalogo_temas/`](./catalogo_temas/) ya tienes generados los 9 diseños con el mismo perfil para que puedas mostrárselos a tus clientes y elijan su favorito:

| Código del Tema (`theme:`) | Estilo / Perfil Recomendado |
| :--- | :--- |
| `classic` | Clásico, limpio y equilibrado para todo tipo de profesionales. |
| `moderncv` | Diseño moderno con columna lateral de fechas e íconos elegantes. |
| `harvard` | Estilo ejecutivo y académico tradicional tipo Ivy League. |
| `engineeringresumes` | Ultra compacto y directo, estándar de oro para ingenieros y desarrolladores (ATS 100%). |
| `engineeringclassic` | Variante con acentos de color para perfiles técnicos y gerenciales. |
| `sb2nov` | Basado en la famosa plantilla de LaTeX para Software Engineers. |
| `ember` | Tipografía moderna y cálida para perfiles creativos o de producto. |
| `ink` | Alto contraste y sobriedad editorial. |
| `opal` | Minimalista y espaciado moderno. |

### 💡 Tip de Negocio: Ofrece un "Pack Multi-Diseño" a tus clientes
Si quieres sorprender a un cliente entregándole su Hoja de Vida en los **9 diseños diferentes** con un solo clic, ejecuta:

```powershell
.\generar_todos_los_temas.ps1 -ArchivoYaml "clientes\ejemplo_juan_perez\Juan_Perez_CV.yaml"
```
Esto creará una subcarpeta `variantes_temas/` dentro de la carpeta del cliente con los 9 PDFs y sus imágenes de vista previa listas para enviar por WhatsApp o correo.


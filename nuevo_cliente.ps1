param(
    [Parameter(Mandatory=$true, HelpMessage="Nombre completo del cliente, ej: 'Maria Rodriguez'")]
    [string]$Nombre,

    [ValidateSet("classic", "ember", "engineeringclassic", "engineeringresumes", "harvard", "ink", "moderncv", "opal", "sb2nov")]
    [string]$Tema = "classic",

    [ValidateSet("spanish", "english")]
    [string]$Idioma = "spanish",

    [switch]$ModoEnVivo
)

$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Crear slug limpio para la carpeta del cliente
$carpetaNombre = $Nombre.ToLower() -replace '[^a-z0-9áéíóúñ]+', '_' -replace '^_|_$', ''
$carpetaNombre = $carpetaNombre.Normalize([Text.NormalizationForm]::FormD) -replace '\p{Mn}', ''
$rutaCliente = Join-Path $PSScriptRoot "clientes\$carpetaNombre"

if (-not (Test-Path $rutaCliente)) {
    New-Item -ItemType Directory -Force -Path $rutaCliente | Out-Null
    Write-Host "✔ Carpeta de cliente creada: $rutaCliente" -ForegroundColor Green
}

$nombreArchivo = ($Nombre -replace '\s+', '_') -replace '[^a-zA-Z0-9_]', ''
$rutaYaml = Join-Path $rutaCliente "${nombreArchivo}_CV.yaml"

if (-not (Test-Path $rutaYaml)) {
    if ($Idioma -eq "spanish" -and (Test-Path "$PSScriptRoot\plantillas\plantilla_base_es.yaml")) {
        $contenido = Get-Content "$PSScriptRoot\plantillas\plantilla_base_es.yaml" -Raw -Encoding UTF8
        $contenido = $contenido -replace 'name: Juan Pérez Gómez', "name: $Nombre"
        $contenido = $contenido -replace 'theme: classic', "theme: $Tema"
        $contenido = $contenido -replace 'pdf_title: Juan Pérez Gómez - Hoja de Vida', "pdf_title: $Nombre - Hoja de Vida"
        Set-Content -Path $rutaYaml -Value $contenido -Encoding UTF8
    } else {
        Push-Location $rutaCliente
        python -m rendercv new "$Nombre" --theme $Tema --locale $Idioma
        Pop-Location
    }
    Write-Host "✔ Archivo YAML creado: $rutaYaml" -ForegroundColor Green
} else {
    Write-Host "ℹ El archivo YAML ya existe: $rutaYaml" -ForegroundColor Yellow
}

Write-Host "⏳ Generando Hoja de Vida inicial en PDF..." -ForegroundColor Cyan
python -m rendercv render "$rutaYaml"

if ($ModoEnVivo) {
    Write-Host "👀 Iniciando modo en vivo (--watch). Presiona Ctrl+C para detener..." -ForegroundColor Magenta
    python -m rendercv render --watch "$rutaYaml"
} else {
    Write-Host "`n✨ ¡Listo! Abre el archivo YAML y el PDF lado a lado en tu editor:" -ForegroundColor Green
    Write-Host "   YAML: $rutaYaml"
    Write-Host "   PDF:  $rutaCliente\rendercv_output\"
    Write-Host "   Para edición en tiempo real ejecuta: python -m rendercv render --watch `"$rutaYaml`""
}


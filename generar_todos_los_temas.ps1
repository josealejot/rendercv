param(
    [Parameter(Mandatory=$true, HelpMessage="Ruta al archivo YAML del cliente")]
    [string]$ArchivoYaml
)

$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Test-Path $ArchivoYaml)) {
    Write-Error "No se encontró el archivo: $ArchivoYaml"
    exit 1
}

$item = Get-Item $ArchivoYaml
$carpetaCliente = $item.DirectoryName
$carpetaVariantes = Join-Path $carpetaCliente "variantes_temas"
New-Item -ItemType Directory -Force -Path $carpetaVariantes | Out-Null

$temas = @("classic", "ember", "engineeringclassic", "engineeringresumes", "harvard", "ink", "moderncv", "opal", "sb2nov")

Write-Host "🎨 Generando los 9 diseños disponibles para: $($item.Name)..." -ForegroundColor Cyan

foreach ($t in $temas) {
    Write-Host "   -> Renderizando tema: $t..." -NoNewline
    python -m rendercv render "$ArchivoYaml" --design.theme $t -pdf "variantes_temas/CV_Tema_$t.pdf" -png "variantes_temas/CV_Tema_$t.png" -nomd -nohtml -q
    Write-Host " ✔" -ForegroundColor Green
}

Write-Host "`n✨ ¡Todos los 9 temas fueron generados en: $carpetaVariantes!" -ForegroundColor Green


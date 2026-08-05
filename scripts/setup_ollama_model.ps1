# One-time setup: imports the already-downloaded LM Studio GGUF into Ollama
# as "qwen3.5-4b-ec" (no re-download). Skip if `ollama list` already shows it.
# ASCII-only on purpose: Windows PowerShell 5.1 misparses BOM-less UTF-8 scripts.

$ErrorActionPreference = "Stop"

$gguf = "$env:USERPROFILE\.lmstudio\models\lmstudio-community\Qwen3.5-4B-GGUF\Qwen3.5-4B-Q4_K_M.gguf"
if (-not (Test-Path $gguf)) {
    throw "GGUF not found at $gguf - adjust the path, or run: ollama pull qwen3.5:4b"
}

$modelfileDir = Join-Path $PSScriptRoot "..\ollama"
New-Item -ItemType Directory -Force -Path $modelfileDir | Out-Null
$modelfile = Join-Path $modelfileDir "Modelfile.qwen35"

$ggufFwd = $gguf -replace '\\', '/'
$lines = @(
    "FROM $ggufFwd",
    "PARAMETER temperature 0.1",
    "PARAMETER num_ctx 8192"
)
$lines -join "`n" | Out-File -FilePath $modelfile -Encoding utf8

ollama create qwen3.5-4b-ec -f $modelfile
ollama list

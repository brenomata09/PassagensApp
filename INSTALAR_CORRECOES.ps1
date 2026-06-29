$ErrorActionPreference = "Stop"
$ROOT = "C:\Users\breno\PROJETOS\voos\PassagensApp"
$PYTHON = "$ROOT\venv\Scripts\python.exe"
$PIP    = "$ROOT\venv\Scripts\pip.exe"

Write-Host "PassagensApp - Instalando correcoes" -ForegroundColor Cyan
Write-Host "Pasta: $ROOT"

if (-not (Test-Path $ROOT)) {
    Write-Host "ERRO: Pasta nao encontrada: $ROOT" -ForegroundColor Red
    exit 1
}
Set-Location $ROOT

if (-not (Test-Path $PYTHON)) {
    Write-Host "ERRO: venv nao encontrado. Crie com: python -m venv venv" -ForegroundColor Red
    exit 1
}
Write-Host "OK - venv encontrado" -ForegroundColor Green

Write-Host "Instalando dependencias..."
& $PIP install -q --upgrade flights requests python-dotenv
Write-Host "OK - dependencias instaladas" -ForegroundColor Green

$lockFile = "$ROOT\data\sweep.lock"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force
    Write-Host "OK - lock antigo removido" -ForegroundColor Green
}

if (-not (Test-Path "$ROOT\data")) {
    New-Item -ItemType Directory -Path "$ROOT\data" | Out-Null
    Write-Host "OK - pasta data criada" -ForegroundColor Green
}

Write-Host "Testando imports..."

$testScript = @"
import sys
sys.path.insert(0, r'$ROOT')
errors = []

try:
    from core.sources import enabled_sources
    sources = enabled_sources()
    print('  OK sources: ' + str([s.name for s in sources]))
except Exception as e:
    errors.append('  ERRO sources: ' + str(e))

try:
    from core.sweep_lock import acquire_sweep_lock
    print('  OK sweep_lock')
except Exception as e:
    errors.append('  ERRO sweep_lock: ' + str(e))

try:
    from core.ceilings import MIN_SOURCES_FOR_CEILING
    print('  OK ceilings MIN_SOURCES=' + str(MIN_SOURCES_FOR_CEILING))
except Exception as e:
    errors.append('  ERRO ceilings: ' + str(e))

try:
    from core.alerts import process
    print('  OK alerts')
except Exception as e:
    errors.append('  ERRO alerts: ' + str(e))

try:
    from core.source_check import verify_snapshot
    print('  OK source_check')
except Exception as e:
    errors.append('  ERRO source_check: ' + str(e))

if errors:
    for err in errors:
        print(err)
    sys.exit(1)
else:
    print('  Todos os imports OK')
"@

& $PYTHON -c $testScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: imports falharam" -ForegroundColor Red
    exit 1
}

Write-Host "Correcoes aplicadas com sucesso!" -ForegroundColor Green
Write-Host ""
Write-Host "Rodar sweep agora:"
Write-Host "  .\venv\Scripts\python.exe run_sweep.py"
Write-Host ""
Write-Host "Rodar scheduler continuo (a cada 4h):"
Write-Host "  .\venv\Scripts\python.exe run_scheduler.py"

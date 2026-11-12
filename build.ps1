# Baut die portable Pausenpilot.exe (eine Datei, keine Installation nötig).
# Voraussetzung: python -m pip install PySide6 pyinstaller
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python tools/make_icon.py build/pausenpilot.ico
python tests/test_schedule.py
if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen" }

$excludes = @(
  "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtWebEngineCore",
  "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts",
  "PySide6.QtDataVisualization", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql",
  "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtBluetooth", "PySide6.QtPositioning",
  "PySide6.QtSerialPort", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtXml",
  "tkinter", "unittest", "pydoc", "numpy"
) | ForEach-Object { "--exclude-module"; $_ }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name Pausenpilot `
  --icon "$PSScriptRoot\build\pausenpilot.ico" `
  --version-file "$PSScriptRoot\tools\version_info.txt" `
  --distpath dist --workpath build/pyi --specpath build `
  @excludes `
  run.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }
Get-Item dist/Pausenpilot.exe | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}

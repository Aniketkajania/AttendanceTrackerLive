# Run in an ELEVATED PowerShell on the Windows app server.
# Prereqs: Python 3.10+ on PATH, NSSM (https://nssm.cc) on PATH, project copied to $App, .env filled in.
$App  = "C:\attendance\app"
$Venv = "C:\attendance\venv"
$Logs = "C:\attendance\logs"
New-Item -ItemType Directory -Force -Path $Logs, "C:\attendance\data" | Out-Null

python -m venv $Venv
& "$Venv\Scripts\pip.exe" install -r "$App\requirements.txt"
# GPU box:  & "$Venv\Scripts\pip.exe" uninstall onnxruntime -y; & "$Venv\Scripts\pip.exe" install onnxruntime-gpu
# No NVIDIA but Intel/AMD GPU:  pip install onnxruntime-directml  (engine auto-detects it)

# --- API ---
nssm install AttendanceAPI "$Venv\Scripts\python.exe" "-m uvicorn main:app --host 127.0.0.1 --port 8000"
nssm set AttendanceAPI AppDirectory $App
nssm set AttendanceAPI AppStdout "$Logs\api.log"
nssm set AttendanceAPI AppStderr "$Logs\api.err.log"
nssm set AttendanceAPI AppRotateFiles 1
nssm set AttendanceAPI Start SERVICE_AUTO_START

# --- Recognition engine (exactly ONE instance) ---
nssm install AttendanceEngine "$Venv\Scripts\python.exe" "server_engine.py"
nssm set AttendanceEngine AppDirectory $App
nssm set AttendanceEngine AppStdout "$Logs\engine.log"
nssm set AttendanceEngine AppStderr "$Logs\engine.err.log"
nssm set AttendanceEngine AppRotateFiles 1
nssm set AttendanceEngine AppExit Default Restart
nssm set AttendanceEngine AppRestartDelay 5000
nssm set AttendanceEngine Start SERVICE_AUTO_START

# If you use Windows authentication to SQL Server (DB_TRUSTED=true), run both services as a domain/service account:
# nssm set AttendanceAPI    ObjectName "DOMAIN\svc_attendance" "<password>"
# nssm set AttendanceEngine ObjectName "DOMAIN\svc_attendance" "<password>"

Start-Service AttendanceAPI, AttendanceEngine
Get-Service AttendanceAPI, AttendanceEngine

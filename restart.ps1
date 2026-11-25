# Restart both backend and frontend servers
# Usage: .\restart.ps1

Write-Host "🔄 Restarting Joshu application..." -ForegroundColor Cyan

# Kill all Python processes
$pythonProcs = @(Get-Process python -ErrorAction SilentlyContinue)
if ($pythonProcs.Count -gt 0) {
    Write-Host "Stopping $($pythonProcs.Count) Python process(es)..."
    foreach ($proc in $pythonProcs) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Write-Host "✅ Stopped" -ForegroundColor Green
}

Start-Sleep -Seconds 2

# Start UI server
Write-Host "`nStarting UI server on port 3000..." -ForegroundColor Yellow
Push-Location C:\Users\bhaga\Desktop\joshu\.open-design
Start-Process python -ArgumentList "-m http.server 3000" -WindowStyle Hidden
Pop-Location

Start-Sleep -Seconds 2

# Start backend  
Write-Host "Starting backend on port 8000..." -ForegroundColor Yellow
Push-Location C:\Users\bhaga\Desktop\joshu\backend
Start-Process python -ArgumentList "-m uvicorn main:app --host 0.0.0.0 --port 8000" -WindowStyle Hidden
Pop-Location

Start-Sleep -Seconds 3

Write-Host "`n✅ Application restarted!" -ForegroundColor Green
Write-Host "   📱 UI: http://localhost:3000/auth.html" -ForegroundColor Cyan
Write-Host "   🔙 Backend: http://localhost:8000" -ForegroundColor Cyan
Write-Host "`n💡 Tip: Run this script anytime you need to restart the servers" -ForegroundColor Magenta

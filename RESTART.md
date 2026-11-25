# 🚀 Quick Start & Restart Guide

## Running the Application

### Option 1: Double-Click (Easiest)
Simply double-click `restart.bat` in the project root folder. This will:
- Stop all running Python processes
- Start the UI server on port 3000
- Start the backend on port 8000

### Option 2: PowerShell
Open PowerShell in the project root and run:
```powershell
.\restart.ps1
```

### Option 3: Manual Commands
```powershell
# Terminal 1 - UI Server
cd .open-design
python -m http.server 3000

# Terminal 2 - Backend
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Accessing the Application

- **Frontend**: http://localhost:3000/auth.html
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Troubleshooting

### Port Already in Use
If you get "Address already in use" error:
1. Run `restart.bat` to kill all processes
2. Wait 5 seconds for ports to free up
3. Run the script again

### Need to Kill Processes Manually
```powershell
Get-Process python | Stop-Process -Force
```

### Check What's Running
```powershell
Get-Process python | Select-Object Id, ProcessName, Handles
```

## OAuth Setup

The application is configured for Google OAuth with these redirect URIs:
- `http://localhost:3000/auth.html` (for local testing)
- `http://localhost:8000/auth/callback` (backend)

Credentials are stored in `.env` file (do not commit to git).

# 🚀 Flutter Web App - Startup Guide

**Current Status**: Flutter downloading in background  
**Expected Time**: 5-10 more minutes  
**Once Ready**: Follow these steps

---

## 📋 **Automatic Setup (Once Download Completes)**

### **Step 1: Extract Flutter**
Once download is complete (~2-3 GB), I'll automatically:
```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\flutter.zip" `
  -DestinationPath "C:\" -Force
```

This will create: `C:\flutter`

### **Step 2: Add to System PATH**

```powershell
# Add Flutter to PATH
$flutterPath = "C:\flutter\bin"
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")

if ($currentPath -notlike "*$flutterPath*") {
  [Environment]::SetEnvironmentVariable(
    "PATH",
    "$currentPath;$flutterPath",
    "Machine"
  )
  Write-Host "✓ Flutter added to PATH"
}
```

This makes `flutter` command available everywhere.

### **Step 3: Verify Installation**

```bash
flutter --version
flutter doctor
```

Should output Flutter version and check environment.

### **Step 4: Run Flutter Web App**

```bash
cd C:\Users\bhaga\Desktop\joshu\app
flutter pub get
flutter run -d web
```

This will:
1. ✅ Install dependencies
2. ✅ Compile Dart to JavaScript
3. ✅ Start local web server
4. ✅ Open browser to `http://localhost:####` (some port)

---

## 🌐 **What You'll See**

```
Launching lib/main.dart on Chrome in debug mode...
Building flutter app to web...
Waiting for connection from debug service on Chrome...
...
The Dart VM service is listening on http://127.0.0.1:####/####
The Flutter DevTools debugger is listening on http://127.0.0.1:####

🔥  To hot reload changes while running, press "r" or "R".
To quit the app, press "q".
```

Then your browser opens with the app!

---

## 📱 **What You'll See in Browser**

```
┌─────────────────────────────────────────┐
│  My Approval App                        │
├─────────────────────────────────────────┤
│                                         │
│         [Sign in with Google]           │
│                                         │
│  Connecting to: http://localhost:8000   │
│  Status: Backend connection OK ✓        │
│                                         │
└─────────────────────────────────────────┘
```

---

## 🔐 **Testing Steps After App Loads**

### **Step 1: Click "Sign in with Google"**
- Opens Google login in popup
- Sign in with your Gmail account

### **Step 2: Approve Gmail Scope**
- Google asks for permissions
- **IMPORTANT**: Check the box for "Gmail read-only"
- Click "Allow"

### **Step 3: Dashboard Loads**
- App navigates to home/tasks screen
- Should show extracted meeting tasks

### **Step 4: Check Task List**
- Look for tasks extracted from your Gmail
- Each should show:
  - Meeting title
  - Date & time
  - Organizer
  - Attendees
  - Meeting link

---

## ✅ **Success Indicators**

After signing in, you should see:
```
✓ Dashboard loads
✓ Tasks are displayed
✓ Meeting titles are correct
✓ Times are accurate
✓ No loading errors
✓ Backend connection shows "OK"
```

If you see any red errors, we'll troubleshoot.

---

## ⏱️ **Timeline**

| Step | Time | Status |
|------|------|--------|
| Flutter download | 10-15 min | ⏳ IN PROGRESS |
| Extract & setup | 2-3 min | ⏳ PENDING |
| Add to PATH | 1 min | ⏳ PENDING |
| Verify flutter | 1 min | ⏳ PENDING |
| Run web app | 2-3 min | ⏳ PENDING |
| Browser opens | 1 min | ⏳ PENDING |
| Sign in | 2-3 min | ⏳ PENDING |
| **TOTAL** | **~20-25 min** | 🎯 |

---

## 🎯 **What You Should Do Now**

1. ✅ Keep this guide open
2. ✅ Monitor the Flutter download progress
3. ✅ Once download completes, I'll notify you
4. ✅ I'll extract and add to PATH automatically
5. ✅ You run the startup command
6. ✅ Follow sign-in steps

---

## 🔧 **Troubleshooting**

### **If browser doesn't open automatically**
```bash
# Browser might not open in background
# Just go to: http://localhost:####
# (The port number is shown in terminal)
```

### **If you see "Failed to reach backend"**
```bash
# Make sure backend is still running:
curl http://localhost:8000/health
# Should return: {"status":"ok"}
```

### **If Flutter web app is very slow**
```bash
# This is normal in debug mode
# Production build is much faster
# It's fine for testing
```

### **If you get "Port already in use"**
```bash
# Flutter runs on random port each time
# Just wait, next run will use different port
```

---

## 📚 **Files Reference**

- **Flutter startup script**: `C:\Users\bhaga\Desktop\joshu\start_flutter_web.bat`
- **Testing guide**: `C:\Users\bhaga\Desktop\joshu\GMAIL_POLLING_LOCAL_TESTING.md`
- **Phase 3 prompt**: `C:\Users\bhaga\Desktop\joshu\PHASE_3_APPROVAL_UI_PROMPT.md`
- **Project status**: `C:\Users\bhaga\Desktop\joshu\PROJECT_STATUS.md`

---

## 💾 **Automatic Setup Commands**

Once download completes, I'll run:

```powershell
# 1. Extract
Expand-Archive -Path "$env:USERPROFILE\Downloads\flutter.zip" `
  -DestinationPath "C:\" -Force

# 2. Add to PATH
$flutterPath = "C:\flutter\bin"
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
[Environment]::SetEnvironmentVariable(
  "PATH",
  "$currentPath;$flutterPath",
  "Machine"
)

# 3. Reload environment
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")

# 4. Verify
flutter --version
```

Then you just run:
```bash
cd C:\Users\bhaga\Desktop\joshu\app
flutter run -d web
```

---

🎉 **Ready when Flutter download completes!**

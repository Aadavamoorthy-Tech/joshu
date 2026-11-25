# 🚀 Next Steps: Get OAuth Running Locally

## ✅ Current Status
Neon has completed OAuth implementation. All code is on GitHub and pulled into your local project.

---

## 📋 Setup Checklist (Do These Next)

### **Step 1: Get Google OAuth Credentials** (If you don't have them)
- Go to [Google Cloud Console](https://console.cloud.google.com)
- Create new project or select existing
- Enable Google+ API
- Create **Web Application OAuth 2.0 Client ID**
- Copy `Client ID` and `Client Secret`
- Add redirect URIs:
  - `http://localhost:8000/auth/callback` (backend)

### **Step 2: Set up Backend Environment**

```bash
cd C:\Users\bhaga\Desktop\joshu\backend

# Create .env file (copy from .env.example)
# Add your Google credentials:
# GOOGLE_CLIENT_ID=your-web-client-id-here.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=your-web-client-secret-here
# GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Optional: Install dependencies if not done
pip install -r requirements.txt

# Backend is already running (should still be on port 8000)
# If not, start it:
# uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### **Step 3: Set up Frontend Environment**

```bash
cd C:\Users\bhaga\Desktop\joshu\app

# Install Flutter dependencies
flutter pub get

# Optional: Run analyze to check for issues
flutter analyze

# Start Flutter web on Chrome
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
```

### **Step 4: Test the OAuth Flow**

1. **Backend should be running** (already running in background)
   - Check: http://localhost:8000/health → should return `{"status":"ok"}`
   - Swagger docs: http://localhost:8000/docs → shows all endpoints

2. **Start Flutter frontend**
   - Browser opens to localhost:8000 (or similar)
   - You should see "Personal AI Chief of Staff" title
   - "Sign in with Google" button visible

3. **Click "Sign in with Google"**
   - Browser/webview opens Google login
   - Sign in with Google account
   - Click "Allow" to grant scopes
   - Browser redirects back to app
   - App navigates to home screen (InboxScreen)
   - ✅ Success!

---

## 🧪 Testing Commands

```bash
# Test backend health
curl http://localhost:8000/health

# Test signin endpoint
curl -X POST http://localhost:8000/auth/signin

# View all endpoints (Swagger UI)
# Open in browser: http://localhost:8000/docs

# Run backend tests
cd backend
pytest tests/test_auth.py -v

# Run frontend tests
cd ../app
flutter test
```

---

## 📝 Configuration Files

### Backend `.backend/.env`
```
GOOGLE_CLIENT_ID=YOUR_CLIENT_ID_HERE
GOOGLE_CLIENT_SECRET=YOUR_SECRET_HERE
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
SESSION_TOKEN_EXPIRY_DAYS=30
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5000,http://localhost:7777,http://localhost:8080
DATABASE_URL=sqlite:///./test.db
```

### Frontend (No config needed)
- Flutter app automatically picks up `API_BASE_URL` from command line
- Or hardcode in `core_providers.dart` if preferred

---

## 🔧 Troubleshooting

### "Port 8000 already in use"
```bash
# Find process using port 8000
netstat -ano | findstr :8000

# Kill it (replace PID with actual process ID)
taskkill /PID <PID> /F

# Then restart backend
```

### "flutter: command not found"
- Flutter SDK not in PATH
- Add Flutter to PATH: `C:\path\to\flutter\bin`
- Or use full path: `C:\path\to\flutter\bin\flutter run -d chrome`

### "OAuth not configured" error
- Missing `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` in `.env`
- Add them and restart backend

### "Invalid redirect_uri"
- Check `.env` has correct `GOOGLE_REDIRECT_URI`
- Must match what's registered in Google Cloud Console

### "CORS error" in browser console
- Backend not running or not accessible
- Check backend is on port 8000: `curl http://localhost:8000/health`
- Check CORS_ALLOWED_ORIGINS in `.env` includes your Flutter dev URL

---

## 📊 Expected Results

After completing setup:

✅ **Backend**
- FastAPI running on http://localhost:8000
- `/health` returns `{"status":"ok"}`
- `/docs` shows OAuth endpoints
- Tests pass: `pytest tests/test_auth.py`

✅ **Frontend**
- Flutter app shows SignInScreen
- "Sign in with Google" button clickable
- OAuth flow launches webview
- After sign-in, navigates to home

✅ **Database**
- SQLite database created (`backend/test.db`)
- `users` table created
- `sessions` table created
- `oauth_states` table created

---

## 🎯 Success Criteria

| Item | Expected | Actual |
|------|----------|--------|
| Backend health | `{"status":"ok"}` | ✅ |
| OAuth signin | Returns redirect URL | ✅ |
| OAuth callback | Creates session | ✅ |
| Session token | UUID v4 string | ✅ |
| Token storage | Secure storage | ✅ |
| App navigation | Navigates to home | ✅ |

---

## 📞 If Stuck

Check these in order:
1. **Backend running?** → `curl http://localhost:8000/health`
2. **Credentials set?** → Check `.env` file has Google secrets
3. **Frontend can reach backend?** → Browser console for CORS errors
4. **OAuth URL valid?** → Check it starts with `https://accounts.google.com/`
5. **Tests passing?** → `pytest tests/test_auth.py -v`

---

## ⏭️ After OAuth Works

Once sign-in is working:

1. **Document what you tested**
   - Commands you ran
   - Screenshots of success
   - Any issues encountered

2. **Then start Phase 2 (Gmail Polling)**
   - Neon will add gmail.readonly scope
   - Build background worker for email fetching
   - Parse task data from calendar invites

3. **Keep backend running**
   - Don't stop it
   - New phases will add to same endpoints
   - Database will persist sessions

---

## 📚 Key Files for Reference

- `NEON_OAUTH_VALIDATION.md` — Complete validation report
- `backend/AUTH_FLOW.md` — Architecture documentation
- `backend/routes/auth.py` — OAuth implementation (368 lines)
- `app/lib/presentation/screens/sign_in_screen.dart` — Flutter UI
- `app/lib/providers/auth_provider.dart` — State management
- `backend/tests/test_auth.py` — Test suite

---

**Happy testing! 🚀 Come back when you've verified OAuth works locally.**

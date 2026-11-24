# OAuth Setup Checklist

## Current Status
- ✅ Backend state management working (state tokens are stored and retrieved correctly)
- ✅ Frontend OAuth callback handler implemented
- ⚠️ Authorization code exchange failing (likely due to redirect URI mismatch in Google Console)

## What You Need to Do

### 1. Verify Google OAuth Client Configuration
Your OAuth Client ID: `296503647002-84pv7q1aj73bt94uae2r7v08c6oc44lp.apps.googleusercontent.com`

**Steps:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Find and click on your OAuth 2.0 Client ID credential
3. Under "Authorized redirect URIs", verify these URIs are listed:
   - `http://localhost:3000/auth.html`
   - `http://localhost:8000/auth/callback`
   - If not listed, add them and click "Save"

### 2. Backend Environment Variables
Verify your `.env` file has these correct values:
```
GOOGLE_CLIENT_ID=296503647002-84pv7q1aj73bt94uae2r7v08c6oc44lp.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
ALLOWED_OAUTH_REDIRECT_URIS=http://localhost:3000/auth.html,http://localhost:8000/auth/callback
```

### 3. Test the OAuth Flow
1. Open `http://localhost:3000/auth.html` in your browser
2. Click "Sign In with Google"
3. You should be redirected to Google's login
4. After logging in, you should be redirected back to the app
5. Check browser console for detailed logs

## Troubleshooting

### "Authorization code is invalid, expired, or already used"
- This means the code from Google was rejected
- Likely cause: redirect_uri not registered in Google Console
- Fix: Add the redirect URIs to Google Console as described above

### "State token is invalid, expired, or already used"
- This means the backend couldn't find the state token
- Likely cause: state storage failed or expired (10 minute TTL)
- Fix: Check backend logs for state storage errors

### Browser console shows errors
- Check the browser's Developer Tools (F12)
- Look at the Console tab for detailed error messages
- Look at Network tab to see the actual API requests/responses

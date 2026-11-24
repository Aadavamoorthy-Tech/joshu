import os
import uuid
from datetime import datetime, timedelta
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import Flow

from database import init_db, get_db, engine
from models import Base, User, OAuthToken, Session as SessionModel
from encryption import encrypt_token, decrypt_token

load_dotenv()

app = FastAPI(title="Personal AI Chief of Staff API")

# Initialize database tables on startup
Base.metadata.create_all(bind=engine)

google_client_id = os.getenv("GOOGLE_CLIENT_ID")
google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

if not google_client_id or not google_client_secret:
    print("WARNING: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set. OAuth will not work.")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def get_oauth_flow() -> Flow:
    """Create a Google OAuth flow."""
    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )
    
    # Redirect URI: local dev or production
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    flow.redirect_uri = f"{base_url}/oauth/callback"
    
    return flow


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/oauth/authorize")
def oauth_authorize():
    """Redirect user to Google OAuth consent screen."""
    flow = get_oauth_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    
    # Store state in session for CSRF validation (in production, use Redis or secure session storage)
    # For now, we'll validate on callback
    return RedirectResponse(url=authorization_url)


@app.get("/oauth/callback")
def oauth_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None), db: Session = Depends(get_db)):
    """Handle Google OAuth callback, exchange code for tokens."""
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    
    try:
        flow = get_oauth_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Get user info from ID token
        id_token = credentials.id_token
        google_id = id_token.get("sub")
        email = id_token.get("email")
        name = id_token.get("name", email)
        picture_url = id_token.get("picture")
        
        # Upsert user
        user = db.query(User).filter_by(google_id=google_id).first()
        if not user:
            user = User(
                google_id=google_id,
                email=email,
                name=name,
                picture_url=picture_url
            )
            db.add(user)
        else:
            user.email = email
            user.name = name
            user.picture_url = picture_url
            user.updated_at = datetime.utcnow()
        
        db.flush()
        
        # Store encrypted tokens
        oauth_token = db.query(OAuthToken).filter_by(google_id=google_id).first()
        if not oauth_token:
            oauth_token = OAuthToken(google_id=google_id)
            db.add(oauth_token)
        
        oauth_token.access_token_encrypted = encrypt_token(credentials.token)
        oauth_token.refresh_token_encrypted = encrypt_token(credentials.refresh_token) if credentials.refresh_token else None
        oauth_token.access_token_expires_at = credentials.expiry or datetime.utcnow() + timedelta(hours=1)
        oauth_token.updated_at = datetime.utcnow()
        
        db.flush()
        
        # Create Flutter session token
        session_token = str(uuid.uuid4())
        session = SessionModel(
            session_token=session_token,
            google_id=google_id,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.add(session)
        db.commit()
        
        # Return session token to Flutter (via redirect with query param)
        # In production, this would be a deep link or secure redirect
        redirect_uri = os.getenv("FLUTTER_REDIRECT_URI", "http://localhost:3000/auth/callback")
        return RedirectResponse(url=f"{redirect_uri}?session_token={session_token}&user_email={email}")
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {str(e)}")


@app.post("/oauth/token")
def validate_session_token(session_token: str, db: Session = Depends(get_db)):
    """Validate Flutter session token."""
    session = db.query(SessionModel).filter_by(session_token=session_token).first()
    
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    if session.expires_at < datetime.utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")
    
    user = session.user
    return {
        "valid": True,
        "google_id": user.google_id,
        "email": user.email,
        "name": user.name,
        "expires_at": session.expires_at.isoformat()
    }

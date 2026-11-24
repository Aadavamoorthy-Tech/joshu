# Personal AI Chief of Staff

A planned, event-driven application that helps users manage everyday administrative tasks. It will monitor connected services, prepare suggested actions, and present them in the application for review.

## Status

Development has started with a FastAPI health endpoint and a Flutter app that checks its connection. Google sign-in, Gmail monitoring, approvals, and Calendar integration are not implemented yet.

## How it will work

The assistant can read and analyze information, check for conflicts, draft responses, and prepare actions. Sending email, creating or changing calendar events, submitting forms, and initiating payments must wait for explicit user approval in the application.

Approval, tenant isolation, spend limits, payee allowlists, and other security rules must be enforced by backend code, not solely by LLM instructions. Actions and decisions should be recorded in an audit log.

## Planned first release

- Onboard multiple users and connect their Google accounts through OAuth.
- Monitor Gmail for bills and meeting invitations and extract structured details.
- Show tasks, notifications, and approval requests in the application.
- Create Google Calendar events only after approval.
- Persist workflow state so tasks can pause for a decision and resume afterward.

An initial end-to-end slice is a meeting invitation detected in Gmail, presented in the app for approval or rejection, and added to Calendar only if approved.

## Later phases

1. Draft refund follow-up emails and send them only after approval; store user profile information securely and prepare forms for approved submission.
2. Stage bill payments through supported portals or payment APIs, enforce spend and payee rules, and require approval before payment execution.

## Intended architecture

- **Application interface:** A shared Flutter app targeting web, Android, and Windows, with in-app notifications, task status, and approval cards.
- **Backend:** Python and FastAPI, with a stateful workflow engine or persistent state machine.
- **Integrations:** Google APIs, an LLM for extraction and drafting, and potentially Playwright and payment providers in later phases.
- **Data and background work:** PostgreSQL for hosted multi-user data, plus a worker for polling and task processing. Local development may use SQLite.
- **Hosting:** Render web service, managed PostgreSQL, and a background worker; a separate frontend may be hosted as a static site if appropriate.

OAuth credentials and user data must be protected, and Google API permissions should be limited to those required by enabled features. Hosting and integrations are planned, not configured.

## Run the backend locally

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

The health endpoint is available at `http://127.0.0.1:8000/health`. Run the backend tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
```

The default browser origin allowed by CORS is `http://localhost:3000`. Set the `CORS_ALLOWED_ORIGINS` environment variable to a comma-separated list when using different frontend origins.

## Run the Flutter app

Install the Flutter SDK and the platform prerequisites described in the [Flutter setup guide](https://docs.flutter.dev/get-started/install). The Android SDK is needed for Android builds; Windows builds require the Visual Studio C++ desktop workload. The generated Android application ID is a placeholder and must be replaced before configuring Google OAuth or publishing.

If Flutter is installed at `%LOCALAPPDATA%\flutter-sdk` but is not on your PATH, add it for the current PowerShell session with:

```powershell
$env:PATH = "$env:LOCALAPPDATA\flutter-sdk\bin;$env:PATH"
```

With the backend running, use a second terminal:

```powershell
cd app
flutter pub get
flutter run -d chrome --web-port 3000
```

For Windows, use `flutter run -d windows`. To run on an Android emulator with the backend on the host machine, use `flutter run -d android --dart-define=API_BASE_URL=http://10.0.2.2:8000` and select the emulator if prompted. Debug Android builds allow local HTTP; deployed builds should use an HTTPS API URL supplied with `--dart-define=API_BASE_URL=https://your-api.example`. Configure the backend's `CORS_ALLOWED_ORIGINS` to include the deployed web app's origin.

Run Flutter checks from the `app` directory with `flutter analyze` and `flutter test`.

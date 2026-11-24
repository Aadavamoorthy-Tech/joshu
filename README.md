# Personal AI Chief of Staff

A planned, event-driven application that helps users manage everyday administrative tasks. It will monitor connected services, prepare suggested actions, and present them in the application for review.

## Status

The application has not been built yet.

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

- **Application interface:** In-app notifications, task status, and approval cards. The platform and frontend technology are yet to be decided.
- **Backend:** Python and FastAPI, with a stateful workflow engine or persistent state machine.
- **Integrations:** Google APIs, an LLM for extraction and drafting, and potentially Playwright and payment providers in later phases.
- **Data and background work:** PostgreSQL for hosted multi-user data, plus a worker for polling and task processing. Local development may use SQLite.
- **Hosting:** Render web service, managed PostgreSQL, and a background worker; a separate frontend may be hosted as a static site if appropriate.

OAuth credentials and user data must be protected, and Google API permissions should be limited to those required by enabled features. Hosting and integrations are planned, not configured.

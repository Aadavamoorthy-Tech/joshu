"""Executive SaaS HTML/CSS/JS application template for Joshu (Personal AI Chief of Staff).

Zero demo data: opens directly to real mailbox sign-in (Google OAuth 2.0 Account
Chooser via Google Cloud Console credentials + Universal IMAP TLS 993 for any email
provider). All untrusted email fields are rendered via textContent (zero innerHTML),
and session tokens are held strictly in JS memory.
"""

from __future__ import annotations

import html
import json


def build_oauth_callback_html(
    exchange_code: str | None = None,
    error_message: str | None = None,
    redirect_origin: str = "",
) -> str:
    """Render a safe, minimal OAuth callback completion page."""
    if error_message:
        safe_err = html.escape(error_message)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sign-In Error — Joshu</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      font-family: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f8fafc;
      color: #0f172a;
    }}
    .box {{
      max-width: 460px;
      width: 100%;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 28px;
    }}
    h1 {{ margin: 0 0 10px; font-size: 20px; }}
    p {{ margin: 0 0 20px; color: #475569; font-size: 14px; line-height: 1.6; }}
    a {{
      display: inline-block;
      padding: 10px 18px;
      background: #0f172a;
      color: #ffffff;
      text-decoration: none;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="box" role="alert">
    <h1>Google Sign-In Could Not Complete</h1>
    <p>{safe_err}</p>
    <a href="/">Return to Joshu Sign In</a>
  </div>
</body>
</html>
"""

    code_json = json.dumps(exchange_code or "").replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Completing Sign-In — Joshu</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f8fafc;
      color: #0f172a;
    }}
    p {{ font-size: 15px; color: #475569; }}
  </style>
</head>
<body>
  <p>Connecting your mailbox and loading your inbox…</p>
  <script>
    (function() {{
      const code = {code_json};
      if (code) {{
        window.location.replace("/#oauth_code=" + encodeURIComponent(code));
      }} else {{
        window.location.replace("/");
      }}
    }})();
  </script>
</body>
</html>
"""


APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Joshu — Executive Mail &amp; Approval Inbox</title>
  <meta name="description" content="Sign in with any email account to poll incoming meeting invitations and inbox requests for one-click approval." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --canvas: #f8fafc;
      --surface: #ffffff;
      --surface-subtle: #f1f5f9;
      --slate-950: #0b1220;
      --slate-900: #0f172a;
      --slate-800: #1e293b;
      --slate-700: #334155;
      --slate-600: #475569;
      --slate-500: #64748b;
      --slate-400: #94a3b8;
      --border: #e2e8f0;
      --border-strong: #cbd5e1;
      --accent: #1d4ed8;
      --accent-hover: #1e40af;
      --accent-tint: #eff6ff;
      --approve: #15803d;
      --approve-hover: #166534;
      --approve-tint: #f0fdf4;
      --approve-border: #bbf7d0;
      --reject: #b91c1c;
      --reject-hover: #991b1b;
      --reject-tint: #fef2f2;
      --reject-border: #fecaca;
      --pending: #b45309;
      --font-display: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-body: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
      --radius-md: 8px;
      --radius-lg: 12px;
      --ease: cubic-bezier(0.16, 1, 0.3, 1);
    }

    *, *::before, *::after { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: var(--font-body);
      background: var(--canvas);
      color: var(--slate-900);
      font-size: 15px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }

    h1, h2, h3, h4 {
      font-family: var(--font-display);
      text-wrap: balance;
    }
    h1 { letter-spacing: -0.025em; }
    h2 { letter-spacing: -0.015em; }

    .mono {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
    }
    .tabular { font-variant-numeric: tabular-nums; }
    .hidden { display: none !important; }

    button:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible,
    a:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    /* ── SIGN-IN VIEW (2-COLUMN FULL VIEWPORT) ─────────────────────────── */
    .auth-shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(380px, 46%) 1fr;
      background: var(--surface);
    }

    .auth-brand-col {
      background: var(--slate-900);
      color: #f8fafc;
      padding: 36px 48px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      border-right: 1px solid var(--slate-800);
    }

    .wordmark {
      font-family: var(--font-display);
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: inherit;
      text-decoration: none;
      white-space: nowrap;
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }

    .wordmark-glyph {
      width: 28px;
      height: 28px;
      border-radius: 7px;
      background: var(--accent);
      color: #ffffff;
      display: grid;
      place-items: center;
      font-size: 14px;
      font-weight: 700;
      flex-shrink: 0;
    }

    .auth-pitch {
      max-width: 460px;
      margin: 28px 0;
    }

    .auth-pitch h1 {
      margin: 0 0 14px;
      font-size: clamp(28px, 2.7vw, 36px);
      line-height: 1.18;
      font-weight: 700;
      color: #ffffff;
    }

    .auth-pitch p {
      margin: 0 0 28px;
      font-size: 15px;
      line-height: 1.62;
      color: #cbd5e1;
      letter-spacing: 0.005em;
    }

    .steps-list {
      list-style: none;
      margin: 0;
      padding: 0;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
    }

    .steps-list li {
      padding: 15px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }

    .step-title {
      font-family: var(--font-display);
      font-size: 14.5px;
      font-weight: 600;
      letter-spacing: 0.005em;
      color: #ffffff;
      margin: 0 0 4px;
    }

    .step-desc {
      font-size: 13.5px;
      color: #94a3b8;
      margin: 0;
      line-height: 1.5;
    }

    .auth-security-note {
      font-size: 12.5px;
      color: #94a3b8;
      line-height: 1.55;
      max-width: 440px;
      margin: 0;
    }

    .auth-form-col {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 40px 32px;
      background: var(--surface);
    }

    .auth-card {
      width: 100%;
      max-width: 460px;
    }

    .auth-card h2 {
      margin: 0 0 6px;
      font-size: 24px;
      font-weight: 700;
      color: var(--slate-900);
    }

    .auth-subtitle {
      margin: 0 0 24px;
      font-size: 14.5px;
      color: var(--slate-600);
    }

    /* Official Google Sign-In Button */
    .btn-google {
      width: 100%;
      min-height: 44px;
      padding: 10px 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      background: #ffffff;
      color: #1f1f1f;
      border: 1px solid #cbd5e1;
      border-radius: var(--radius-md);
      font-family: var(--font-display);
      font-size: 14.5px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: background 150ms var(--ease), border-color 150ms var(--ease), transform 150ms var(--ease);
    }

    .btn-google:hover:not(:disabled) {
      background: #f8fafc;
      border-color: #94a3b8;
    }

    .btn-google:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .google-help-box {
      margin-top: 12px;
      padding: 14px 16px;
      background: var(--canvas);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      font-size: 13px;
      color: var(--slate-700);
      line-height: 1.55;
    }

    .google-help-box p { margin: 0 0 8px; }
    .google-help-box p:last-child { margin-bottom: 0; }
    .google-help-box code {
      font-family: var(--font-mono);
      font-size: 11.5px;
      background: #e2e8f0;
      color: var(--slate-900);
      padding: 2px 5px;
      border-radius: 4px;
      white-space: nowrap;
    }
    .google-help-box code.uri-code {
      display: block;
      margin-top: 6px;
      padding: 7px 10px;
      white-space: normal;
      word-break: break-all;
    }

    .google-external-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-top: 10px;
      padding: 9px 16px;
      background: var(--accent);
      color: #ffffff;
      border-radius: var(--radius-md);
      text-decoration: none;
      font-family: var(--font-display);
      font-size: 13.5px;
      font-weight: 600;
      white-space: nowrap;
    }
    .google-external-link:hover { background: var(--accent-hover); }

    .divider {
      display: flex;
      align-items: center;
      gap: 14px;
      margin: 24px 0;
      color: var(--slate-500);
      font-size: 12.5px;
    }
    .divider::before,
    .divider::after {
      content: "";
      flex: 1;
      height: 1px;
      background: var(--border);
    }

    .field { margin-bottom: 16px; }
    .field label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: var(--slate-800);
      margin-bottom: 6px;
    }

    .input-wrap {
      position: relative;
      display: flex;
      align-items: center;
    }

    .field input,
    .field select {
      width: 100%;
      min-height: 42px;
      padding: 9px 13px;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      font-family: var(--font-body);
      font-size: 14.5px;
      color: var(--slate-900);
      background: var(--surface);
      transition: border-color 150ms var(--ease);
    }

    .field input:focus,
    .field select:focus {
      border-color: var(--accent);
    }

    .input-with-toggle { padding-right: 68px !important; }

    .toggle-visibility {
      position: absolute;
      right: 8px;
      background: transparent;
      border: 0;
      padding: 6px 8px;
      font-family: var(--font-body);
      font-size: 12.5px;
      font-weight: 600;
      color: var(--slate-600);
      cursor: pointer;
      white-space: nowrap;
    }
    .toggle-visibility:hover { color: var(--slate-900); }

    .field-hint {
      margin-top: 6px;
      font-size: 12.5px;
      color: var(--slate-600);
      line-height: 1.45;
    }

    .field-hint strong { color: var(--slate-800); font-weight: 600; }

    .disclosure-btn {
      background: transparent;
      border: 0;
      padding: 4px 0;
      margin: 2px 0 12px;
      font-family: var(--font-body);
      font-size: 13px;
      font-weight: 600;
      color: var(--accent);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .disclosure-btn:hover { color: var(--accent-hover); text-decoration: underline; }

    .advanced-panel {
      padding: 14px 16px;
      margin-bottom: 16px;
      background: var(--canvas);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }

    .form-error {
      margin: 0 0 16px;
      padding: 12px 14px;
      border-radius: var(--radius-md);
      background: var(--reject-tint);
      border: 1px solid var(--reject-border);
      color: var(--reject-hover);
      font-size: 13.5px;
      line-height: 1.5;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 40px;
      padding: 8px 16px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border-strong);
      background: var(--surface);
      color: var(--slate-800);
      font-family: var(--font-display);
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background 150ms var(--ease), border-color 150ms var(--ease), color 150ms var(--ease);
    }

    .btn:hover:not(:disabled) {
      background: var(--surface-subtle);
      border-color: var(--slate-400);
    }

    .btn:disabled { opacity: 0.55; cursor: not-allowed; }

    .btn-primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }
    .btn-primary:hover:not(:disabled) {
      background: var(--accent-hover);
      border-color: var(--accent-hover);
    }

    .btn-block { width: 100%; min-height: 44px; font-size: 14.5px; }

    .btn-approve {
      background: var(--approve);
      border-color: var(--approve);
      color: #ffffff;
    }
    .btn-approve:hover:not(:disabled) {
      background: var(--approve-hover);
      border-color: var(--approve-hover);
    }

    .btn-reject {
      background: var(--surface);
      border-color: var(--reject-border);
      color: var(--reject);
    }
    .btn-reject:hover:not(:disabled) {
      background: var(--reject-tint);
      border-color: var(--reject);
    }

    .btn-reject-solid {
      background: var(--reject);
      border-color: var(--reject);
      color: #ffffff;
    }
    .btn-reject-solid:hover:not(:disabled) {
      background: var(--reject-hover);
      border-color: var(--reject-hover);
    }

    /* ── WORKSPACE SHELL (SIDEBAR + TOPBAR + MAIN) ─────────────────────── */
    .workspace-shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 268px 1fr;
      background: var(--canvas);
    }

    .sidebar {
      background: var(--surface);
      border-right: 1px solid var(--border);
      padding: 20px 18px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }

    .sidebar-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 6px 18px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 18px;
    }

    .nav-section-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--slate-500);
      padding: 0 10px;
      margin: 0 0 8px;
    }

    .side-nav {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-bottom: 24px;
    }

    .nav-item {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 9px 10px;
      border: 0;
      border-radius: var(--radius-md);
      background: transparent;
      color: var(--slate-700);
      font-family: var(--font-body);
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      text-align: left;
      transition: background 140ms var(--ease), color 140ms var(--ease);
    }

    .nav-item:hover {
      background: var(--surface-subtle);
      color: var(--slate-900);
    }

    .nav-item.active {
      background: var(--accent-tint);
      color: var(--accent);
      font-weight: 600;
    }

    .nav-count {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 12px;
      color: var(--slate-500);
    }
    .nav-item.active .nav-count { color: var(--accent); }

    .mailbox-panel {
      padding-top: 18px;
      border-top: 1px solid var(--border);
    }

    .mailbox-email {
      font-size: 13.5px;
      font-weight: 600;
      color: var(--slate-900);
      word-break: break-all;
      margin: 0 0 4px;
    }

    .mailbox-meta {
      font-size: 12px;
      color: var(--slate-500);
      margin: 0 0 14px;
      line-height: 1.45;
    }

    .poll-control-row {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }

    .poll-control-row label {
      font-size: 12px;
      font-weight: 600;
      color: var(--slate-600);
    }

    .poll-control-row select {
      width: 100%;
      min-height: 36px;
      padding: 6px 10px;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      background: var(--surface);
      font-family: var(--font-body);
      font-size: 13px;
      color: var(--slate-800);
    }

    .poll-timestamps {
      font-size: 12px;
      color: var(--slate-500);
      margin: 0 0 14px;
      line-height: 1.6;
    }

    .poll-error-inline {
      font-size: 12px;
      color: var(--reject);
      margin: 0 0 12px;
      line-height: 1.45;
    }

    .sidebar-footer {
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }

    .main-column {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .topbar {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 20;
      min-height: 60px;
    }

    .topbar-left {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .mobile-menu-btn {
      display: none;
      min-height: 38px;
      padding: 6px 10px;
    }

    .breadcrumb {
      font-family: var(--font-display);
      font-size: 14.5px;
      font-weight: 600;
      color: var(--slate-900);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .breadcrumb span {
      color: var(--slate-400);
      font-weight: 500;
      margin: 0 6px;
    }

    .workspace-content {
      max-width: 1120px;
      width: 100%;
      margin: 0 auto;
      padding: 28px 32px 64px;
    }

    /* 4-column flat summary strip with hairline dividers */
    .summary-strip {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      margin-bottom: 24px;
      overflow: hidden;
    }

    .summary-cell {
      padding: 18px 22px;
      border-right: 1px solid var(--border);
    }
    .summary-cell:last-child { border-right: 0; }

    .summary-label {
      font-size: 12.5px;
      color: var(--slate-500);
      font-weight: 500;
      margin-bottom: 6px;
    }

    .summary-value {
      font-family: var(--font-mono);
      font-variant-numeric: tabular-nums;
      font-size: 26px;
      font-weight: 600;
      color: var(--slate-900);
      line-height: 1.15;
    }

    .summary-value.pending { color: var(--pending); }
    .summary-value.approved { color: var(--approve); }
    .summary-value.rejected { color: var(--reject); }

    /* Toolbar: segmented status filter + live search */
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }

    .segmented {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px;
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }

    .seg-btn {
      border: 0;
      background: transparent;
      color: var(--slate-600);
      padding: 7px 14px;
      border-radius: 6px;
      font-family: var(--font-display);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background 140ms var(--ease), color 140ms var(--ease);
    }

    .seg-btn:hover { color: var(--slate-900); }

    .seg-btn.active {
      background: var(--surface);
      color: var(--slate-900);
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
    }

    .search-box {
      flex: 1;
      min-width: 240px;
      max-width: 380px;
    }

    .search-box input {
      width: 100%;
      min-height: 40px;
      padding: 8px 13px;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      background: var(--surface);
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--slate-900);
    }

    /* Task list: single-elevation flat items */
    .task-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .task-item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px 24px;
      transition: border-color 150ms var(--ease);
    }

    .task-item:hover { border-color: var(--border-strong); }
    .task-item.approved { background: var(--approve-tint); border-color: var(--approve-border); }
    .task-item.rejected { background: var(--reject-tint); border-color: var(--reject-border); }

    .task-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }

    .task-title {
      margin: 0 0 6px;
      font-size: 16px;
      font-weight: 600;
      color: var(--slate-900);
      line-height: 1.35;
    }

    .task-meta {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 13px;
      color: var(--slate-600);
    }

    .meta-sep { color: var(--slate-400); }

    .task-status {
      font-family: var(--font-display);
      font-size: 12.5px;
      font-weight: 700;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .task-status.pending { color: var(--pending); }
    .task-status.approved { color: var(--approve); }
    .task-status.rejected { color: var(--reject); }

    .task-snippet {
      margin: 12px 0 0;
      font-size: 14px;
      color: var(--slate-700);
      line-height: 1.55;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .task-note {
      margin: 12px 0 0;
      padding: 10px 14px;
      border-radius: var(--radius-md);
      background: rgba(185, 28, 28, 0.06);
      border: 1px solid var(--reject-border);
      font-size: 13px;
      color: var(--reject-hover);
    }

    .task-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
    }

    .task-action-group {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .meeting-link {
      font-size: 13.5px;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
      white-space: nowrap;
    }
    .meeting-link:hover { text-decoration: underline; }

    .empty-state {
      background: var(--surface);
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius-lg);
      padding: 52px 24px;
      text-align: center;
    }

    .empty-state h3 {
      margin: 0 0 8px;
      font-size: 17px;
      color: var(--slate-900);
    }

    .empty-state p {
      margin: 0 auto 20px;
      max-width: 440px;
      font-size: 14px;
      color: var(--slate-600);
    }

    /* Loading skeleton */
    .skeleton-item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px 24px;
    }
    .skeleton-bar {
      height: 14px;
      border-radius: 4px;
      background: var(--surface-subtle);
      margin-bottom: 10px;
    }

    /* Modals */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      z-index: 50;
    }

    .modal-dialog {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      max-width: 560px;
      width: 100%;
      max-height: 85vh;
      overflow-y: auto;
      padding: 24px 28px;
    }

    .modal-dialog h2 {
      margin: 0 0 8px;
      font-size: 19px;
      color: var(--slate-900);
    }

    .modal-copy {
      margin: 0 0 16px;
      font-size: 14px;
      color: var(--slate-600);
    }

    .quick-reasons {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }

    .quick-reason-btn {
      padding: 6px 12px;
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      background: var(--canvas);
      color: var(--slate-700);
      font-family: var(--font-body);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
    }
    .quick-reason-btn:hover { background: var(--surface-subtle); color: var(--slate-900); }

    .modal-dialog textarea {
      width: 100%;
      min-height: 88px;
      padding: 10px 12px;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--slate-900);
      resize: vertical;
    }

    .detail-grid {
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 10px 16px;
      font-size: 14px;
      margin: 16px 0;
    }

    .detail-label {
      color: var(--slate-500);
      font-weight: 600;
    }

    .detail-value {
      color: var(--slate-900);
      word-break: break-word;
      white-space: pre-wrap;
    }

    .modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 20px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }

    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--slate-900);
      color: #ffffff;
      padding: 12px 18px;
      border-radius: var(--radius-md);
      font-size: 13.5px;
      font-weight: 500;
      z-index: 60;
      max-width: 380px;
    }

    /* Mobile drawer backdrop */
    .drawer-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.45);
      z-index: 35;
    }

    .mobile-brand-bar {
      display: none;
      align-items: center;
      padding: 16px 20px;
      background: var(--slate-900);
      color: #ffffff;
    }

    @media (max-width: 960px) {
      .auth-shell {
        grid-template-columns: 1fr;
      }
      .mobile-brand-bar {
        display: flex;
      }
      .auth-form-col {
        order: 1;
        padding: 28px 20px 36px;
        align-items: flex-start;
      }
      .auth-brand-col {
        order: 2;
        padding: 32px 20px 40px;
        border-right: 0;
        border-top: 1px solid var(--slate-800);
      }
      .auth-brand-col > .wordmark { display: none; }
      .auth-pitch { margin: 0 0 24px; }

      .workspace-shell { grid-template-columns: 1fr; }
      .sidebar {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: 280px;
        z-index: 40;
        transform: translateX(-100%);
        transition: transform 200ms var(--ease);
      }
      .sidebar.open { transform: translateX(0); }
      .drawer-backdrop.open { display: block; }
      .mobile-menu-btn { display: inline-flex; }
      .topbar { padding: 10px 16px; }
      .workspace-content { padding: 20px 16px 48px; }
      .summary-strip { grid-template-columns: repeat(2, 1fr); }
      .summary-cell:nth-child(2) { border-right: 0; }
      .summary-cell:nth-child(1),
      .summary-cell:nth-child(2) { border-bottom: 1px solid var(--border); }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; animation: none !important; }
    }
  </style>
</head>
<body>
  <!-- ── SIGN-IN SCREEN ────────────────────────────────────────────────── -->
  <div id="auth-view" class="auth-shell">
    <div class="mobile-brand-bar">
      <a href="/" class="wordmark">
        <span class="wordmark-glyph" aria-hidden="true">J</span>
        <span>Joshu</span>
      </a>
    </div>
    <aside class="auth-brand-col">
      <a href="/" class="wordmark">
        <span class="wordmark-glyph" aria-hidden="true">J</span>
        <span>Joshu</span>
      </a>

      <div class="auth-pitch">
        <h1>Connect any inbox. Approve every commitment.</h1>
        <p>
          Sign in with any Google account or IMAP mailbox. Joshu polls that specific
          mailbox on your chosen schedule, parses incoming calendar invitations and
          messages, and queues every item for your approval.
        </p>

        <ol class="steps-list">
          <li>
            <h2 class="step-title">01. Choose the exact mailbox to poll</h2>
            <p class="step-desc">
              Sign in with Google Account Chooser or connect any Gmail, Outlook,
              Yahoo, iCloud, Fastmail, Zoho, or custom domain mailbox over TLS.
            </p>
          </li>
          <li>
            <h2 class="step-title">02. Live read-only inbox polling</h2>
            <p class="step-desc">
              Fetches real messages and .ics meeting invites from the signed-in account
              without altering, marking read, or deleting mail.
            </p>
          </li>
          <li>
            <h2 class="step-title">03. Executive approval workflow</h2>
            <p class="step-desc">
              Review attendees, schedule times, and verified meeting links before
              approving or rejecting with a recorded reason.
            </p>
          </li>
        </ol>
      </div>

      <p class="auth-security-note">
        Read-only access only. Session tokens stay in browser memory and server-side
        mailbox credentials are cleared immediately when you sign out.
      </p>
    </aside>

    <main class="auth-form-col">
      <section class="auth-card" aria-labelledby="signin-heading">
        <h2 id="signin-heading">Sign in to your mailbox</h2>
        <p class="auth-subtitle">
          Select which email account Joshu should read and poll.
        </p>

        <div id="auth-error" class="form-error hidden" role="alert"></div>

        <!-- Primary Google Cloud Console OAuth Sign-In -->
        <button id="google-signin-btn" type="button" class="btn-google">
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          <span>Sign in with Google</span>
        </button>

        <div id="google-help" class="google-help-box hidden" aria-live="polite"></div>

        <div class="divider">or sign in with any email via IMAP</div>

        <!-- Universal IMAP Sign-In Form -->
        <form id="imap-form" novalidate>
          <div class="field">
            <label for="imap-email">Email address</label>
            <input
              id="imap-email"
              name="email"
              type="email"
              autocomplete="email"
              placeholder="name@company.com"
              required
            />
            <div id="provider-hint" class="field-hint">
              Auto-detects Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Zoho, or custom domains.
            </div>
          </div>

          <div class="field">
            <label for="imap-password">App Password or Mail Password</label>
            <div class="input-wrap">
              <input
                id="imap-password"
                name="password"
                type="password"
                autocomplete="current-password"
                placeholder="Enter your mailbox App Password"
                class="input-with-toggle"
                required
              />
              <button
                id="toggle-password-btn"
                type="button"
                class="toggle-visibility"
                aria-label="Show password"
              >
                Show
              </button>
            </div>
          </div>

          <div class="field">
            <label for="poll-interval">Background polling cadence</label>
            <select id="poll-interval" name="poll_interval_minutes">
              <option value="5">Every 5 minutes</option>
              <option value="15" selected>Every 15 minutes</option>
              <option value="30">Every 30 minutes</option>
              <option value="60">Every 60 minutes</option>
            </select>
          </div>

          <button
            id="advanced-toggle"
            type="button"
            class="disclosure-btn"
            aria-expanded="false"
            aria-controls="advanced-panel"
          >
            Custom IMAP Server settings
          </button>

          <div id="advanced-panel" class="advanced-panel hidden">
            <div class="field" style="margin-bottom: 8px;">
              <label for="imap-host">IMAP server hostname (optional override)</label>
              <input
                id="imap-host"
                name="imap_host"
                type="text"
                placeholder="imap.company.com"
                autocomplete="off"
              />
            </div>
            <div class="field-hint mono">
              Security: IMAPS over verified TLS · Port 993 enforced · Read-only INBOX
            </div>
          </div>

          <button id="imap-submit-btn" type="submit" class="btn btn-primary btn-block">
            Sign In &amp; Start Polling
          </button>
        </form>
      </section>
    </main>
  </div>

  <!-- ── AUTHENTICATED WORKSPACE ───────────────────────────────────────── -->
  <div id="workspace-view" class="workspace-shell hidden">
    <div id="drawer-backdrop" class="drawer-backdrop"></div>

    <aside id="sidebar" class="sidebar" aria-label="Mailbox navigation">
      <div>
        <div class="sidebar-head">
          <span class="wordmark">
            <span class="wordmark-glyph" aria-hidden="true">J</span>
            <span>Joshu</span>
          </span>
        </div>

        <p class="nav-section-label">Inbox Views</p>
        <nav class="side-nav" aria-label="Message source filters">
          <button type="button" class="nav-item active" data-source="all">
            <span>All Inbox Items</span>
            <span id="nav-count-all" class="nav-count">0</span>
          </button>
          <button type="button" class="nav-item" data-source="calendar">
            <span>Calendar Invites</span>
            <span id="nav-count-calendar" class="nav-count">0</span>
          </button>
          <button type="button" class="nav-item" data-source="email">
            <span>General Emails</span>
            <span id="nav-count-email" class="nav-count">0</span>
          </button>
        </nav>

        <section class="mailbox-panel" aria-label="Connected mailbox">
          <p class="nav-section-label" style="padding:0;margin-bottom:10px;">Connected Mailbox</p>
          <p id="sb-email" class="mailbox-email"></p>
          <p id="sb-connection" class="mailbox-meta"></p>

          <div class="poll-control-row">
            <label for="sb-poll-interval">Auto-poll schedule</label>
            <select id="sb-poll-interval">
              <option value="5">Every 5 minutes</option>
              <option value="15">Every 15 minutes</option>
              <option value="30">Every 30 minutes</option>
              <option value="60">Every 60 minutes</option>
            </select>
            <button id="sb-poll-toggle" type="button" class="btn" style="width:100%;min-height:36px;">
              Pause Auto-Polling
            </button>
          </div>

          <div id="sb-poll-error" class="poll-error-inline hidden" role="alert"></div>
          <div id="sb-timestamps" class="poll-timestamps mono"></div>
        </section>
      </div>

      <div class="sidebar-footer">
        <button id="signout-btn" type="button" class="btn" style="width:100%;">
          Switch Account / Sign Out
        </button>
      </div>
    </aside>

    <div class="main-column">
      <header class="topbar">
        <div class="topbar-left">
          <button
            id="mobile-menu-btn"
            type="button"
            class="btn mobile-menu-btn"
            aria-label="Open mailbox navigation"
          >
            Menu
          </button>
          <div class="breadcrumb">
            Joshu<span>/</span><strong id="breadcrumb-view">All Inbox Items</strong>
          </div>
        </div>
        <button id="sync-btn" type="button" class="btn btn-primary">
          Sync Inbox Now
        </button>
      </header>

      <main class="workspace-content">
        <section class="summary-strip" aria-label="Inbox summary metrics">
          <div class="summary-cell">
            <div class="summary-label">Total Polled</div>
            <div id="metric-all" class="summary-value">0</div>
          </div>
          <div class="summary-cell">
            <div class="summary-label">Pending Review</div>
            <div id="metric-pending" class="summary-value pending">0</div>
          </div>
          <div class="summary-cell">
            <div class="summary-label">Approved</div>
            <div id="metric-approved" class="summary-value approved">0</div>
          </div>
          <div class="summary-cell">
            <div class="summary-label">Rejected</div>
            <div id="metric-rejected" class="summary-value rejected">0</div>
          </div>
        </section>

        <div class="toolbar">
          <div class="segmented" role="group" aria-label="Filter by approval status" id="status-filters"></div>
          <div class="search-box">
            <label for="search-input" class="hidden">Search inbox items</label>
            <input
              id="search-input"
              type="search"
              placeholder="Search by subject, sender, or notes…"
              aria-label="Search by subject, sender, or notes"
            />
          </div>
        </div>

        <div id="task-list" class="task-list" aria-live="polite"></div>
      </main>
    </div>
  </div>

  <!-- ── REJECT MODAL ──────────────────────────────────────────────────── -->
  <div id="reject-modal" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="reject-modal-title">
    <div class="modal-dialog">
      <h2 id="reject-modal-title">Reject Inbox Item</h2>
      <p id="reject-modal-copy" class="modal-copy"></p>
      <div class="quick-reasons">
        <button type="button" class="quick-reason-btn" data-quick="Already scheduled">Already scheduled</button>
        <button type="button" class="quick-reason-btn" data-quick="Not relevant">Not relevant</button>
        <button type="button" class="quick-reason-btn" data-quick="Declined elsewhere">Declined elsewhere</button>
      </div>
      <label for="reject-reason" class="hidden">Optional rejection reason</label>
      <textarea id="reject-reason" maxlength="500" placeholder="Optional reason for rejecting this item…"></textarea>
      <div class="modal-footer">
        <button id="reject-cancel" type="button" class="btn">Cancel</button>
        <button id="reject-confirm" type="button" class="btn btn-reject-solid">Confirm Reject</button>
      </div>
    </div>
  </div>

  <!-- ── DETAIL MODAL ──────────────────────────────────────────────────── -->
  <div id="detail-modal" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="detail-title">
    <div class="modal-dialog">
      <h2 id="detail-title"></h2>
      <div id="detail-grid" class="detail-grid"></div>
      <div class="modal-footer">
        <button id="detail-close" type="button" class="btn">Close</button>
      </div>
    </div>
  </div>

  <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>

  <script>
    (function () {
      // Session token is held strictly in memory (never localStorage or sessionStorage).
      let sessionToken = null;
      let currentSession = null;
      let allTasks = [];
      let taskCounts = { all: 0, pending: 0, approved: 0, rejected: 0, calendar: 0, email: 0 };
      let activeStatus = "all";
      let activeSource = "all";
      let searchQuery = "";
      let pendingRejectId = null;
      let refreshTimer = null;
      let detectTimer = null;
      let serverConfig = { google_oauth_configured: false, redirect_uri: "" };

      const authView = document.getElementById("auth-view");
      const workspaceView = document.getElementById("workspace-view");
      const authError = document.getElementById("auth-error");
      const googleBtn = document.getElementById("google-signin-btn");
      const googleHelp = document.getElementById("google-help");
      const imapForm = document.getElementById("imap-form");
      const imapEmailInput = document.getElementById("imap-email");
      const imapPasswordInput = document.getElementById("imap-password");
      const imapHostInput = document.getElementById("imap-host");
      const pollIntervalSelect = document.getElementById("poll-interval");
      const imapSubmitBtn = document.getElementById("imap-submit-btn");
      const providerHint = document.getElementById("provider-hint");
      const togglePasswordBtn = document.getElementById("toggle-password-btn");
      const advancedToggle = document.getElementById("advanced-toggle");
      const advancedPanel = document.getElementById("advanced-panel");

      const sidebar = document.getElementById("sidebar");
      const drawerBackdrop = document.getElementById("drawer-backdrop");
      const mobileMenuBtn = document.getElementById("mobile-menu-btn");
      const breadcrumbView = document.getElementById("breadcrumb-view");
      const syncBtn = document.getElementById("sync-btn");
      const signoutBtn = document.getElementById("signout-btn");
      const searchInput = document.getElementById("search-input");
      const statusFilters = document.getElementById("status-filters");
      const taskList = document.getElementById("task-list");

      const sbEmail = document.getElementById("sb-email");
      const sbConnection = document.getElementById("sb-connection");
      const sbPollInterval = document.getElementById("sb-poll-interval");
      const sbPollToggle = document.getElementById("sb-poll-toggle");
      const sbPollError = document.getElementById("sb-poll-error");
      const sbTimestamps = document.getElementById("sb-timestamps");

      const rejectModal = document.getElementById("reject-modal");
      const rejectCopy = document.getElementById("reject-modal-copy");
      const rejectReason = document.getElementById("reject-reason");
      const detailModal = document.getElementById("detail-modal");
      const detailTitle = document.getElementById("detail-title");
      const detailGrid = document.getElementById("detail-grid");
      const toastEl = document.getElementById("toast");

      function showToast(msg) {
        toastEl.textContent = msg;
        toastEl.classList.remove("hidden");
        clearTimeout(window.__joshuToastTimer);
        window.__joshuToastTimer = setTimeout(() => {
          toastEl.classList.add("hidden");
        }, 3200);
      }

      function showAuthError(msg) {
        if (!msg) {
          authError.classList.add("hidden");
          authError.textContent = "";
          return;
        }
        authError.textContent = msg;
        authError.classList.remove("hidden");
      }

      function formatDateTime(iso) {
        if (!iso) return "Time not specified";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString(undefined, {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit"
        });
      }

      function formatShortTime(iso) {
        if (!iso) return "—";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return "—";
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      }

      async function apiFetch(url, options) {
        const opts = Object.assign({ headers: {} }, options || {});
        if (sessionToken) {
          opts.headers["Authorization"] = "Bearer " + sessionToken;
        }
        const res = await fetch(url, opts);
        let data = {};
        try {
          data = await res.json();
        } catch (_) {
          data = {};
        }
        if (res.status === 401 && sessionToken) {
          clearClientSession("Your mailbox session expired. Please sign in again.");
        }
        return { ok: res.ok, status: res.status, data };
      }

      function clearClientSession(reasonMsg) {
        sessionToken = null;
        currentSession = null;
        allTasks = [];
        taskCounts = { all: 0, pending: 0, approved: 0, rejected: 0, calendar: 0, email: 0 };
        if (refreshTimer) {
          clearInterval(refreshTimer);
          refreshTimer = null;
        }
        workspaceView.classList.add("hidden");
        authView.classList.remove("hidden");
        sidebar.classList.remove("open");
        drawerBackdrop.classList.remove("open");
        imapPasswordInput.value = "";
        if (reasonMsg) {
          showAuthError(reasonMsg);
        }
      }

      function enterWorkspace(token, sessionObj, initialSynced) {
        sessionToken = token;
        currentSession = sessionObj;
        activeStatus = "all";
        activeSource = "all";
        searchQuery = "";
        searchInput.value = "";
        showAuthError("");
        googleHelp.classList.add("hidden");
        authView.classList.add("hidden");
        workspaceView.classList.remove("hidden");
        renderSessionSidebar();
        loadTasks();

        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(() => {
          if (sessionToken) loadTasks({ silent: true });
        }, 30000);

        if (typeof initialSynced === "number") {
          showToast(
            initialSynced > 0
              ? "Signed in as " + sessionObj.email + " · Loaded " + initialSynced + " inbox items"
              : "Signed in as " + sessionObj.email + " · Inbox is connected and polling"
          );
        }
      }

      function renderSessionSidebar() {
        if (!currentSession) return;
        sbEmail.textContent = currentSession.email;
        sbConnection.textContent = currentSession.provider + " · " + currentSession.connection_label;
        sbPollInterval.value = String(currentSession.poll_interval_minutes || 15);
        sbPollToggle.textContent = currentSession.auto_poll_enabled
          ? "Pause Auto-Polling"
          : "Resume Auto-Polling";

        if (currentSession.last_poll_error) {
          sbPollError.textContent = "Last poll error: " + currentSession.last_poll_error;
          sbPollError.classList.remove("hidden");
        } else {
          sbPollError.classList.add("hidden");
          sbPollError.textContent = "";
        }

        sbTimestamps.replaceChildren();
        const line1 = document.createElement("div");
        line1.textContent = "Last sync: " + formatShortTime(currentSession.last_polled_at);
        const line2 = document.createElement("div");
        line2.textContent = currentSession.auto_poll_enabled
          ? "Next poll: " + formatShortTime(currentSession.next_poll_at)
          : "Auto-polling paused";
        const line3 = document.createElement("div");
        line3.textContent = "Polls completed: " + (currentSession.poll_count || 1);
        sbTimestamps.append(line1, line2, line3);
      }

      function renderMetricsAndNav() {
        document.getElementById("metric-all").textContent = String(taskCounts.all || 0);
        document.getElementById("metric-pending").textContent = String(taskCounts.pending || 0);
        document.getElementById("metric-approved").textContent = String(taskCounts.approved || 0);
        document.getElementById("metric-rejected").textContent = String(taskCounts.rejected || 0);

        document.getElementById("nav-count-all").textContent = String(taskCounts.all || 0);
        document.getElementById("nav-count-calendar").textContent = String(taskCounts.calendar || 0);
        document.getElementById("nav-count-email").textContent = String(taskCounts.email || 0);

        document.querySelectorAll(".nav-item").forEach((btn) => {
          const src = btn.getAttribute("data-source");
          btn.classList.toggle("active", src === activeSource);
        });

        const labelMap = {
          all: "All Inbox Items",
          calendar: "Calendar Invites",
          email: "General Emails"
        };
        breadcrumbView.textContent = labelMap[activeSource] || "All Inbox Items";
      }

      function renderStatusFilters() {
        statusFilters.replaceChildren();
        const defs = [
          ["all", "All"],
          ["pending", "Pending"],
          ["approved", "Approved"],
          ["rejected", "Rejected"]
        ];
        for (const [key, label] of defs) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "seg-btn" + (activeStatus === key ? " active" : "");
          btn.setAttribute("aria-pressed", activeStatus === key ? "true" : "false");
          btn.textContent = label + " (" + (taskCounts[key] || 0) + ")";
          btn.addEventListener("click", () => {
            activeStatus = key;
            renderWorkspace();
          });
          statusFilters.appendChild(btn);
        }
      }

      function getFilteredTasks() {
        const q = searchQuery.trim().toLowerCase();
        return allTasks.filter((t) => {
          if (activeSource !== "all" && t.source !== activeSource) return false;
          if (activeStatus !== "all" && t.status !== activeStatus) return false;
          if (q) {
            const hay = [
              t.title || "",
              t.organizer || "",
              t.description || "",
              (t.attendees || []).join(" ")
            ].join(" ").toLowerCase();
            if (!hay.includes(q)) return false;
          }
          return true;
        });
      }

      function renderTaskList() {
        taskList.replaceChildren();
        const items = getFilteredTasks();

        if (items.length === 0) {
          const empty = document.createElement("div");
          empty.className = "empty-state";
          const h3 = document.createElement("h3");
          const p = document.createElement("p");

          if (searchQuery.trim()) {
            h3.textContent = "No matching messages";
            p.textContent = 'No inbox items matched "' + searchQuery.trim() + '".';
            const clearBtn = document.createElement("button");
            clearBtn.type = "button";
            clearBtn.className = "btn";
            clearBtn.textContent = "Clear Search";
            clearBtn.addEventListener("click", () => {
              searchQuery = "";
              searchInput.value = "";
              renderWorkspace();
            });
            empty.append(h3, p, clearBtn);
          } else if (activeStatus === "pending" && (taskCounts.all || 0) > 0) {
            h3.textContent = "All polled items reviewed";
            p.textContent = "You have reviewed every pending item from " + (currentSession ? currentSession.email : "this mailbox") + ".";
            empty.append(h3, p);
          } else {
            h3.textContent = "No items in this view";
            p.textContent =
              "Joshu is polling " +
              (currentSession ? currentSession.email : "your mailbox") +
              ". New messages and calendar invitations will appear here automatically.";
            const syncAgainBtn = document.createElement("button");
            syncAgainBtn.type = "button";
            syncAgainBtn.className = "btn btn-primary";
            syncAgainBtn.textContent = "Sync Inbox Now";
            syncAgainBtn.addEventListener("click", triggerManualSync);
            empty.append(h3, p, syncAgainBtn);
          }

          taskList.appendChild(empty);
          return;
        }

        for (const task of items) {
          const article = document.createElement("article");
          article.className = "task-item " + task.status;

          const header = document.createElement("div");
          header.className = "task-header";

          const left = document.createElement("div");
          const title = document.createElement("h3");
          title.className = "task-title";
          title.textContent = task.title || "(No Subject)";

          const meta = document.createElement("div");
          meta.className = "task-meta";
          const metaPieces = [
            task.source === "calendar" ? "Calendar Invite" : "Inbox Email",
            task.organizer ? "From " + task.organizer : null,
            formatDateTime(task.scheduled_for),
            Array.isArray(task.attendees) && task.attendees.length > 0
              ? task.attendees.length + (task.attendees.length === 1 ? " recipient" : " recipients")
              : null
          ].filter(Boolean);

          metaPieces.forEach((piece, idx) => {
            if (idx > 0) {
              const sep = document.createElement("span");
              sep.className = "meta-sep";
              sep.setAttribute("aria-hidden", "true");
              sep.textContent = "·";
              meta.appendChild(sep);
            }
            const span = document.createElement("span");
            span.textContent = piece;
            meta.appendChild(span);
          });

          left.append(title, meta);

          const statusEl = document.createElement("span");
          statusEl.className = "task-status " + task.status;
          statusEl.textContent =
            task.status === "pending"
              ? "Pending review"
              : task.status === "approved"
              ? "Approved"
              : "Rejected";

          header.append(left, statusEl);
          article.appendChild(header);

          if (task.snippet) {
            const snippet = document.createElement("p");
            snippet.className = "task-snippet";
            snippet.textContent = task.snippet;
            article.appendChild(snippet);
          }

          if (task.status === "rejected" && task.rejection_reason) {
            const note = document.createElement("div");
            note.className = "task-note";
            note.textContent = "Rejection reason: " + task.rejection_reason;
            article.appendChild(note);
          }

          const actionsRow = document.createElement("div");
          actionsRow.className = "task-actions";

          const actionGroup = document.createElement("div");
          actionGroup.className = "task-action-group";

          if (task.status === "pending") {
            const approveBtn = document.createElement("button");
            approveBtn.type = "button";
            approveBtn.className = "btn btn-approve";
            approveBtn.textContent = "Approve";
            approveBtn.setAttribute("aria-label", 'Approve "' + task.title + '"');
            approveBtn.addEventListener("click", () => approveTask(task.id));

            const rejectBtn = document.createElement("button");
            rejectBtn.type = "button";
            rejectBtn.className = "btn btn-reject";
            rejectBtn.textContent = "Reject";
            rejectBtn.setAttribute("aria-label", 'Reject "' + task.title + '"');
            rejectBtn.addEventListener("click", () => openRejectModal(task));

            actionGroup.append(approveBtn, rejectBtn);
          }

          const detailsBtn = document.createElement("button");
          detailsBtn.type = "button";
          detailsBtn.className = "btn";
          detailsBtn.textContent = "Details";
          detailsBtn.setAttribute("aria-label", 'View details for "' + task.title + '"');
          detailsBtn.addEventListener("click", () => openDetailModal(task));
          actionGroup.appendChild(detailsBtn);

          actionsRow.appendChild(actionGroup);

          if (task.calendar_event_link && task.calendar_event_link.startsWith("https://")) {
            const a = document.createElement("a");
            a.className = "meeting-link";
            a.href = task.calendar_event_link;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = task.source === "calendar" ? "Open Meeting Link" : "Open Link";
            actionsRow.appendChild(a);
          }

          article.appendChild(actionsRow);
          taskList.appendChild(article);
        }
      }

      function renderWorkspace() {
        renderSessionSidebar();
        renderMetricsAndNav();
        renderStatusFilters();
        renderTaskList();
      }

      function renderLoadingSkeleton() {
        taskList.replaceChildren();
        for (let i = 0; i < 3; i++) {
          const sk = document.createElement("div");
          sk.className = "skeleton-item";
          const b1 = document.createElement("div");
          b1.className = "skeleton-bar";
          b1.style.width = "52%";
          const b2 = document.createElement("div");
          b2.className = "skeleton-bar";
          b2.style.width = "78%";
          sk.append(b1, b2);
          taskList.appendChild(sk);
        }
      }

      async function loadTasks(opts) {
        if (!sessionToken) return;
        if (!opts || !opts.silent) {
          if (allTasks.length === 0) renderLoadingSkeleton();
        }
        const res = await apiFetch("/api/tasks");
        if (res.ok) {
          allTasks = res.data.tasks || [];
          taskCounts = res.data.counts || taskCounts;
          if (res.data.session) currentSession = res.data.session;
          renderWorkspace();
        }
      }

      async function triggerManualSync() {
        if (!sessionToken) return;
        syncBtn.disabled = true;
        syncBtn.textContent = "Polling Inbox…";
        try {
          const res = await apiFetch("/api/tasks/sync", { method: "POST" });
          if (res.ok) {
            if (res.data.session) currentSession = res.data.session;
            await loadTasks({ silent: true });
            const added = res.data.created_tasks || 0;
            showToast(
              added > 0
                ? "Synced " + added + " new message" + (added === 1 ? "" : "s") + " from " + currentSession.email
                : "Inbox is up to date for " + currentSession.email
            );
          } else {
            showToast(res.data.message || "Could not poll mailbox right now.");
          }
        } finally {
          syncBtn.disabled = false;
          syncBtn.textContent = "Sync Inbox Now";
        }
      }

      async function approveTask(taskId) {
        const res = await apiFetch("/api/tasks/" + encodeURIComponent(taskId) + "/approve", {
          method: "POST"
        });
        if (res.ok) {
          await loadTasks({ silent: true });
          showToast("Approved item");
        } else {
          showToast(res.data.message || "Could not approve item.");
        }
      }

      function openRejectModal(task) {
        pendingRejectId = task.id;
        rejectCopy.textContent = 'Confirm rejection for "' + task.title + '".';
        rejectReason.value = "";
        rejectModal.classList.remove("hidden");
        rejectReason.focus();
      }

      function closeRejectModal() {
        pendingRejectId = null;
        rejectModal.classList.add("hidden");
      }

      function openDetailModal(task) {
        detailTitle.textContent = task.title || "(No Subject)";
        detailGrid.replaceChildren();
        const rows = [
          ["Type", task.source === "calendar" ? "Calendar Invitation" : "Inbox Email"],
          ["Status", task.status],
          ["Mailbox", task.account_email || (currentSession ? currentSession.email : "")],
          ["Date / Time", formatDateTime(task.scheduled_for)],
          ["From", task.organizer || "Unknown"],
          ["Recipients", Array.isArray(task.attendees) && task.attendees.length ? task.attendees.join(", ") : "None"],
          ["Details", task.description || "No additional content."]
        ];
        if (task.approved_at) rows.push(["Approved at", formatDateTime(task.approved_at)]);
        if (task.rejected_at) rows.push(["Rejected at", formatDateTime(task.rejected_at)]);
        if (task.rejection_reason) rows.push(["Reason", task.rejection_reason]);

        for (const [label, value] of rows) {
          const dt = document.createElement("div");
          dt.className = "detail-label";
          dt.textContent = label;
          const dd = document.createElement("div");
          dd.className = "detail-value";
          dd.textContent = String(value);
          detailGrid.append(dt, dd);
        }

        if (task.calendar_event_link && task.calendar_event_link.startsWith("https://")) {
          const dt = document.createElement("div");
          dt.className = "detail-label";
          dt.textContent = "Link";
          const dd = document.createElement("div");
          dd.className = "detail-value";
          const a = document.createElement("a");
          a.className = "meeting-link";
          a.href = task.calendar_event_link;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = task.calendar_event_link;
          dd.appendChild(a);
          detailGrid.append(dt, dd);
        }

        detailModal.classList.remove("hidden");
      }

      function closeDetailModal() {
        detailModal.classList.add("hidden");
      }

      function renderGoogleSetupGuide(redirectUri) {
        googleHelp.replaceChildren();
        const p1 = document.createElement("p");
        p1.append(
          document.createTextNode("Google OAuth is ready once "),
          Object.assign(document.createElement("code"), { textContent: "GOOGLE_CLIENT_ID" }),
          document.createTextNode(" and "),
          Object.assign(document.createElement("code"), { textContent: "GOOGLE_CLIENT_SECRET" }),
          document.createTextNode(" are set in "),
          Object.assign(document.createElement("code"), { textContent: ".env" }),
          document.createTextNode(" or "),
          Object.assign(document.createElement("code"), { textContent: "backend/.env" }),
          document.createTextNode(" (for local VS Code runs) or Settings → Secrets.")
        );
        const p2 = document.createElement("p");
        p2.append(
          document.createTextNode("Authorized Redirect URI to add in Google Cloud Console:"),
          Object.assign(document.createElement("code"), {
            className: "uri-code",
            textContent: redirectUri || window.location.origin + "/auth/google/callback"
          })
        );
        googleHelp.append(p1, p2);
        googleHelp.classList.remove("hidden");
      }

      // ── Event Wiring ────────────────────────────────────────────────────

      googleBtn.addEventListener("click", async () => {
        showAuthError("");
        googleHelp.classList.add("hidden");
        googleBtn.disabled = true;
        try {
          const res = await fetch("/api/auth/google/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              poll_interval_minutes: Number(pollIntervalSelect.value || 15)
            })
          });
          const data = await res.json();
          if (!res.ok) {
            if (data.error === "google_oauth_not_configured") {
              renderGoogleSetupGuide(data.redirect_uri || serverConfig.redirect_uri, data.message);
            } else {
              showAuthError(data.message || "Could not start Google sign-in.");
            }
            return;
          }

          const isEmbedded = window.self !== window.top;
          if (isEmbedded) {
            googleHelp.replaceChildren();
            const p = document.createElement("p");
            p.textContent =
              "Google Account Chooser opens in a dedicated browser tab so you can choose which mail ID to poll:";
            const a = document.createElement("a");
            a.className = "google-external-link";
            a.href = data.auth_url;
            a.target = "_blank";
            a.rel = "noopener";
            a.textContent = "Continue to Google Account Chooser";
            googleHelp.append(p, a);
            googleHelp.classList.remove("hidden");
          } else {
            window.location.assign(data.auth_url);
          }
        } catch (_) {
          showAuthError("Network error while starting Google sign-in.");
        } finally {
          googleBtn.disabled = false;
        }
      });

      togglePasswordBtn.addEventListener("click", () => {
        const isPassword = imapPasswordInput.type === "password";
        imapPasswordInput.type = isPassword ? "text" : "password";
        togglePasswordBtn.textContent = isPassword ? "Hide" : "Show";
        togglePasswordBtn.setAttribute("aria-label", isPassword ? "Hide password" : "Show password");
      });

      advancedToggle.addEventListener("click", () => {
        const expanded = advancedToggle.getAttribute("aria-expanded") === "true";
        advancedToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
        advancedPanel.classList.toggle("hidden", expanded);
      });

      imapEmailInput.addEventListener("input", () => {
        clearTimeout(detectTimer);
        const raw = imapEmailInput.value.trim();
        if (!raw.includes("@")) {
          providerHint.textContent =
            "Auto-detects Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Zoho, or custom domains.";
          return;
        }
        detectTimer = setTimeout(async () => {
          try {
            const res = await fetch("/api/providers/detect?email=" + encodeURIComponent(raw));
            if (!res.ok) return;
            const info = await res.json();
            providerHint.replaceChildren();
            const strong = document.createElement("strong");
            strong.textContent = info.provider + (info.host ? " · " + info.host + ":993" : "");
            providerHint.append(strong, document.createTextNode(" — " + info.hint));
            if (!info.detected && info.host && !imapHostInput.value.trim()) {
              imapHostInput.placeholder = info.host;
            }
          } catch (_) {
            // Keep default hint on transient errors.
          }
        }, 180);
      });

      imapForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        showAuthError("");
        const emailVal = imapEmailInput.value.trim();
        const passwordVal = imapPasswordInput.value;
        const customHostVal = imapHostInput.value.trim();
        const intervalVal = Number(pollIntervalSelect.value || 15);

        if (!emailVal || !emailVal.includes("@")) {
          showAuthError("Please enter a valid email address.");
          imapEmailInput.focus();
          return;
        }
        if (!passwordVal.trim()) {
          showAuthError("Please enter your App Password or Mail Password.");
          imapPasswordInput.focus();
          return;
        }

        imapSubmitBtn.disabled = true;
        imapSubmitBtn.textContent = "Connecting to mailbox…";
        try {
          const res = await fetch("/api/auth/imap/signin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email: emailVal,
              password: passwordVal,
              imap_host: customHostVal || null,
              imap_port: 993,
              poll_interval_minutes: intervalVal
            })
          });
          const data = await res.json();
          if (!res.ok) {
            showAuthError(data.message || "Could not sign in to this mailbox.");
            return;
          }
          enterWorkspace(data.session_token, data.session, data.initial_synced);
        } catch (_) {
          showAuthError("Unable to reach the Joshu server. Confirm it is running and try again.");
        } finally {
          imapSubmitBtn.disabled = false;
          imapSubmitBtn.textContent = "Sign In & Start Polling";
        }
      });

      document.querySelectorAll(".nav-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          activeSource = btn.getAttribute("data-source") || "all";
          sidebar.classList.remove("open");
          drawerBackdrop.classList.remove("open");
          renderWorkspace();
        });
      });

      mobileMenuBtn.addEventListener("click", () => {
        sidebar.classList.add("open");
        drawerBackdrop.classList.add("open");
      });

      drawerBackdrop.addEventListener("click", () => {
        sidebar.classList.remove("open");
        drawerBackdrop.classList.remove("open");
      });

      searchInput.addEventListener("input", () => {
        searchQuery = searchInput.value;
        renderTaskList();
      });

      syncBtn.addEventListener("click", triggerManualSync);

      sbPollInterval.addEventListener("change", async () => {
        const res = await apiFetch("/api/polling/config", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ poll_interval_minutes: Number(sbPollInterval.value) })
        });
        if (res.ok && res.data.session) {
          currentSession = res.data.session;
          renderSessionSidebar();
          showToast("Polling schedule updated to every " + currentSession.poll_interval_minutes + " minutes");
        }
      });

      sbPollToggle.addEventListener("click", async () => {
        if (!currentSession) return;
        const nextEnabled = !currentSession.auto_poll_enabled;
        const res = await apiFetch("/api/polling/config", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auto_poll_enabled: nextEnabled })
        });
        if (res.ok && res.data.session) {
          currentSession = res.data.session;
          renderSessionSidebar();
          showToast(nextEnabled ? "Background polling resumed" : "Background polling paused");
        }
      });

      signoutBtn.addEventListener("click", async () => {
        if (sessionToken) {
          await apiFetch("/api/auth/signout", { method: "POST" });
        }
        clearClientSession("");
        showToast("Signed out and cleared mailbox credentials");
      });

      document.querySelectorAll("[data-quick]").forEach((btn) => {
        btn.addEventListener("click", () => {
          rejectReason.value = btn.getAttribute("data-quick") || "";
          rejectReason.focus();
        });
      });

      document.getElementById("reject-cancel").addEventListener("click", closeRejectModal);
      document.getElementById("reject-confirm").addEventListener("click", async () => {
        if (!pendingRejectId) return;
        const id = pendingRejectId;
        const reason = rejectReason.value.trim();
        closeRejectModal();
        const res = await apiFetch("/api/tasks/" + encodeURIComponent(id) + "/reject", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason || null })
        });
        if (res.ok) {
          await loadTasks({ silent: true });
          showToast("Item rejected");
        } else {
          showToast(res.data.message || "Could not reject item.");
        }
      });

      document.getElementById("detail-close").addEventListener("click", closeDetailModal);

      rejectModal.addEventListener("click", (e) => {
        if (e.target === rejectModal) closeRejectModal();
      });
      detailModal.addEventListener("click", (e) => {
        if (e.target === detailModal) closeDetailModal();
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          closeRejectModal();
          closeDetailModal();
          sidebar.classList.remove("open");
          drawerBackdrop.classList.remove("open");
        }
      });

      // ── Boot: fetch non-secret config & check OAuth handoff hash ────────
      async function bootstrap() {
        try {
          const cfgRes = await fetch("/api/config");
          if (cfgRes.ok) {
            serverConfig = await cfgRes.json();
          }
        } catch (_) {
          // Ignore transient boot check failure.
        }

        const hash = window.location.hash || "";
        const match = hash.match(/oauth_code=([^&]+)/);
        if (match && match[1]) {
          const exchangeCode = decodeURIComponent(match[1]);
          window.history.replaceState(null, "", window.location.pathname);
          try {
            const res = await fetch("/api/auth/google/exchange", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ exchange_code: exchangeCode })
            });
            const data = await res.json();
            if (res.ok && data.session_token) {
              enterWorkspace(data.session_token, data.session, data.initial_synced);
            } else {
              showAuthError(data.message || "Google sign-in handoff expired. Please sign in again.");
            }
          } catch (_) {
            showAuthError("Could not finalize Google sign-in. Please try again.");
          }
        }
      }

      bootstrap();
    })();
  </script>
</body>
</html>
"""

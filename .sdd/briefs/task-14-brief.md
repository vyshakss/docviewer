# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 14: Frontend — login page

**Files:**
- Create: `app/static/login.html`
- Create: `app/static/login.js`
- Modify: `app/main.py` (mount `/static`, serve login page at `/`)

**Interfaces:**
- Consumes: `POST /login`, `POST /login/verify` (Task 7).
- Produces: a working login UI at `/`.

- [ ] **Step 1: Write `app/static/login.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>docviewer — sign in</title>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body class="auth-page">
  <main class="auth-card">
    <h1>docviewer</h1>

    <form id="password-form">
      <label>Username <input type="text" name="username" autocomplete="username" required /></label>
      <label>Password <input type="password" name="password" autocomplete="current-password" required /></label>
      <button type="submit">Continue</button>
      <p class="error" id="password-error"></p>
    </form>

    <form id="totp-form" hidden>
      <label>Authenticator code <input type="text" name="code" inputmode="numeric" autocomplete="one-time-code" required /></label>
      <button type="submit">Sign in</button>
      <p class="error" id="totp-error"></p>
    </form>
  </main>
  <script src="/static/login.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app/static/login.js`**

```javascript
const passwordForm = document.getElementById("password-form");
const totpForm = document.getElementById("totp-form");
const passwordError = document.getElementById("password-error");
const totpError = document.getElementById("totp-error");

passwordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  passwordError.textContent = "";
  const formData = new FormData(passwordForm);

  const resp = await fetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: formData.get("username"),
      password: formData.get("password"),
    }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    passwordError.textContent = body.detail || "Login failed";
    return;
  }

  passwordForm.hidden = true;
  totpForm.hidden = false;
});

totpForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  totpError.textContent = "";
  const formData = new FormData(totpForm);

  const resp = await fetch("/login/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: formData.get("code") }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    totpError.textContent = body.detail || "Invalid code";
    return;
  }

  window.location.href = "/app";
});
```

- [ ] **Step 3: Wire up static file serving in `app/main.py`**

```python
# add imports at top
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# add after app.include_router(preview_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def login_page():
    return FileResponse("app/static/login.html")
```

- [ ] **Step 4: Manual verification**

Run the app locally: `uvicorn app.main:app --reload` (with `.env` pointing at a scratch `FILES_ROOT`/`DB_PATH`/`CACHE_DIR`, and a user already created via Task 5's script).

In a browser, open `http://127.0.0.1:8000/`, submit the password form, then the TOTP form with a code from an authenticator app (or `pyotp.TOTP(secret).now()` in a REPL). Confirm it redirects to `/app` (which will 404 until Task 15 — that 404 is expected here) and that the `session_token` cookie is set (check browser devtools).


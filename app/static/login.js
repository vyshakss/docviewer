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

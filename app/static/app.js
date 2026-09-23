const tokenKey = "edokumenti_access_token";
const loginCard = document.querySelector("#login-card");
const dashboard = document.querySelector("#dashboard");
const logout = document.querySelector("#logout");

async function api(path, options = {}) {
  const token = sessionStorage.getItem(tokenKey);
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Zahtev nije uspeo");
  }
  return response.json();
}

async function showDashboard() {
  try {
    const organizations = await api("/api/v1/organizations");
    document.querySelector("#organizations").innerHTML = organizations.map(org => `
      <article class="org" data-id="${org.id}">
        <strong>${escapeHtml(org.name)}</strong>
        <p>PIB: ${escapeHtml(org.tax_id)}</p>
        <p>Uloga: ${escapeHtml(org.role)}</p>
      </article>`).join("");
    loginCard.hidden = true;
    dashboard.hidden = false;
    logout.hidden = false;
  } catch (_) {
    sessionStorage.removeItem(tokenKey);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

document.querySelector("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const result = await api("/api/v1/auth/login", {method: "POST", body: JSON.stringify(data)});
    sessionStorage.setItem(tokenKey, result.access_token);
    document.querySelector("#login-error").textContent = "";
    await showDashboard();
  } catch (error) {
    document.querySelector("#login-error").textContent = error.message;
  }
});

logout.addEventListener("click", () => { sessionStorage.removeItem(tokenKey); location.reload(); });
if (sessionStorage.getItem(tokenKey)) showDashboard();


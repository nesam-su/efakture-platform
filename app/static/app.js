const tokenKey = "edokumenti_access_token";
const organizationKey = "edokumenti_organization_id";
const state = {organizations: [], organization: null, documents: [], jobs: [], events: [], members: [], sessions: [], integrations: []};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const inviteFormMarkup = $("#invite-form").innerHTML;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? escapeHtml(value) : new Intl.DateTimeFormat("sr-Latn-RS", {dateStyle: "medium", timeStyle: value.includes("T") ? "short" : undefined}).format(date);
}

function formatAmount(value, currency = "RSD") {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat("sr-Latn-RS", {style: "currency", currency: currency || "RSD"}).format(Number(value));
}

const statusNames = {draft:"Nacrt",queued:"Na čekanju",sent:"Poslato",delivered:"Isporučeno",accepted:"Prihvaćeno",rejected:"Odbijeno",cancelled:"Stornirano",error:"Greška",running:"U toku",retrying:"Ponovni pokušaj",succeeded:"Uspešno",failed:"Neuspešno"};
const roleNames = {owner:"Vlasnik",admin:"Administrator",accountant:"Knjigovođa",operator:"Operater",viewer:"Pregled"};
const documentTypeNames = {sales_invoice:"Izlazna faktura",purchase_invoice:"Ulazna faktura",despatch_advice:"Otpremnica",receipt_advice:"Prijemnica"};

function showToast(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 4200);
}

function clearSession() {
  sessionStorage.removeItem(tokenKey);
  sessionStorage.removeItem(organizationKey);
  location.reload();
}

async function api(path, options = {}) {
  const token = sessionStorage.getItem(tokenKey);
  const headers = {...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (state.organization && options.tenant !== false) headers["X-Organization-Id"] = state.organization.id;
  if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  if (response.status === 401 && path !== "/api/v1/auth/login") clearSession();
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).join("; ") : body.detail;
    throw new Error(detail || `Zahtev nije uspeo (${response.status})`);
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response;
}

function canEdit() {
  return state.organization && ["owner", "admin", "accountant", "operator"].includes(state.organization.role);
}

function canAdminister() {
  return state.organization && ["owner", "admin"].includes(state.organization.role);
}

async function initializeApp() {
  try {
    state.organizations = await api("/api/v1/organizations", {tenant: false});
    if (!state.organizations.length) throw new Error("Korisnik nema pristup nijednoj firmi");
    const savedId = sessionStorage.getItem(organizationKey);
    state.organization = state.organizations.find(item => item.id === savedId) || state.organizations[0];
    const select = $("#organization-select");
    select.innerHTML = state.organizations.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(roleNames[item.role] || item.role)}</option>`).join("");
    select.value = state.organization.id;
    sessionStorage.setItem(organizationKey, state.organization.id);
    $("#auth-view").hidden = true;
    $("#app-view").hidden = false;
    $("#new-document-button").hidden = !canEdit();
    $("#invite-button").hidden = !canAdminister();
    await loadWorkspace();
  } catch (error) {
    if (sessionStorage.getItem(tokenKey)) showToast(error.message, true);
  }
}

async function loadWorkspace() {
  const loaders = [loadDocuments(), loadJobs(), loadEvents(), loadMembers(), loadSessions(), loadIntegrations()];
  const results = await Promise.allSettled(loaders);
  const failed = results.find(result => result.status === "rejected");
  if (failed) showToast(failed.reason.message, true);
}

async function loadDocuments() {
  state.documents = await api("/api/v1/documents?limit=200");
  renderDocuments();
}

function renderDocuments() {
  const search = $("#document-search").value.trim().toLowerCase();
  const provider = $("#provider-filter").value;
  const status = $("#status-filter").value;
  const filtered = state.documents.filter(doc => {
    const text = `${doc.document_number || ""} ${doc.counterparty_name || ""} ${doc.counterparty_tax_id || ""}`.toLowerCase();
    return (!search || text.includes(search)) && (!provider || doc.provider === provider) && (!status || doc.status === status);
  });
  $("#document-rows").innerHTML = filtered.map(doc => `<tr>
    <td><strong>${escapeHtml(doc.document_number || documentTypeNames[doc.document_type] || doc.document_type)}</strong><small>${escapeHtml(documentTypeNames[doc.document_type] || doc.document_type)} · ${doc.direction === "outbound" ? "izlazni" : "ulazni"}</small></td>
    <td><span class="service ${doc.provider}">${doc.provider === "sef" ? "SEF" : "eOtpremnice"}</span></td>
    <td><strong>${escapeHtml(doc.counterparty_name || "—")}</strong><small>${escapeHtml(doc.counterparty_tax_id || "")}</small></td>
    <td>${formatDate(doc.issue_date || doc.created_at)}</td><td>${formatAmount(doc.total_amount, doc.currency)}</td>
    <td><span class="status ${doc.status}">${escapeHtml(statusNames[doc.status] || doc.status)}</span><small>${escapeHtml(doc.remote_status || "")}</small></td>
    <td><button class="row-action" data-document-id="${doc.id}">Detalji</button></td></tr>`).join("");
  $("#documents-empty").hidden = filtered.length > 0;
  $("#metric-total").textContent = state.documents.length;
  $("#metric-active").textContent = state.documents.filter(doc => ["queued", "sent"].includes(doc.status)).length;
  $("#metric-success").textContent = state.documents.filter(doc => ["delivered", "accepted"].includes(doc.status)).length;
  $("#metric-errors").textContent = state.documents.filter(doc => ["rejected", "error"].includes(doc.status)).length;
  $$("[data-document-id]").forEach(button => button.addEventListener("click", () => showDocument(button.dataset.documentId)));
}

async function showDocument(documentId) {
  const doc = state.documents.find(item => item.id === documentId);
  if (!doc) return;
  let artifacts = [];
  try { artifacts = await api(`/api/v1/documents/${documentId}/artifacts`); } catch (error) { showToast(error.message, true); }
  $("#document-detail").innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">DETALJI DOKUMENTA</p><h2>${escapeHtml(doc.document_number || documentTypeNames[doc.document_type] || doc.document_type)}</h2></div><button class="icon-button" id="close-detail" aria-label="Zatvori">×</button></div>
    <span class="status ${doc.status}">${escapeHtml(statusNames[doc.status] || doc.status)}</span>
    <div class="detail-grid"><div class="detail-item"><span>Servis</span><strong>${doc.provider === "sef" ? "SEF" : "eOtpremnice"}</strong></div><div class="detail-item"><span>Udaljeni status</span><strong>${escapeHtml(doc.remote_status || "—")}</strong></div><div class="detail-item"><span>Partner</span><strong>${escapeHtml(doc.counterparty_name || "—")}</strong></div><div class="detail-item"><span>Iznos</span><strong>${formatAmount(doc.total_amount, doc.currency)}</strong></div></div>
    <h3>Prilozi</h3><div class="artifact-list">${artifacts.length ? artifacts.map(file => `<div class="artifact"><div><strong>${escapeHtml(file.kind)}</strong><small>${Math.ceil(file.size_bytes / 1024)} KB · ${escapeHtml(file.sha256.slice(0, 12))}…</small></div><button class="secondary artifact-download" data-artifact-id="${file.id}">Preuzmi</button></div>`).join("") : '<p class="muted">Nema priloga.</p>'}</div>
    ${doc.last_error ? `<p class="form-error">${escapeHtml(doc.last_error)}</p>` : ""}
    <div class="dialog-actions"><button class="secondary" id="close-detail-bottom">Zatvori</button>${canEdit() && doc.direction === "outbound" && ["draft", "error"].includes(doc.status) ? `<button class="primary" id="queue-detail">Pošalji u red</button>` : ""}</div>`;
  const dialog = $("#detail-dialog"); dialog.showModal();
  $("#close-detail").onclick = () => dialog.close(); $("#close-detail-bottom").onclick = () => dialog.close();
  const queue = $("#queue-detail"); if (queue) queue.onclick = async () => { try { await api(`/api/v1/documents/${doc.id}/queue`, {method:"POST"}); dialog.close(); showToast("Dokument je dodat u red."); await loadDocuments(); await loadJobs(); } catch (error) { showToast(error.message, true); } };
  $$(".artifact-download").forEach(button => button.onclick = () => downloadArtifact(doc.id, button.dataset.artifactId));
}

async function downloadArtifact(documentId, artifactId) {
  try {
    const response = await api(`/api/v1/documents/${documentId}/artifacts/${artifactId}/download`);
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = "dokument"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { showToast(error.message, true); }
}

async function loadJobs() {
  state.jobs = await api("/api/v1/jobs?limit=100");
  $("#jobs-list").innerHTML = state.jobs.length ? state.jobs.map(job => `<div class="list-row"><div><strong>${escapeHtml(job.kind)}</strong><small>${escapeHtml(job.document_id)}</small></div><div><strong>Pokušaj ${job.attempts}/${job.max_attempts}</strong><small>${formatDate(job.updated_at)}</small></div><div><small>${escapeHtml(job.last_error || "Bez greške")}</small></div><span class="status ${job.status}">${escapeHtml(statusNames[job.status] || job.status)}</span></div>`).join("") : '<div class="empty-state"><strong>Nema poslova</strong><p>Poslovi će se pojaviti nakon slanja dokumenta.</p></div>';
}

async function loadEvents() {
  state.events = await api("/api/v1/external-events?limit=100");
  $("#events-list").innerHTML = state.events.length ? state.events.map(event => `<div class="list-row"><div><strong>${escapeHtml(event.event_type)}</strong><small>${escapeHtml(event.stream)}</small></div><div><strong>${event.provider === "sef" ? "SEF" : "eOtpremnice"}</strong><small>${escapeHtml(event.external_event_id)}</small></div><div><small>${escapeHtml(event.request_id || "Bez requestId")}</small></div><time>${formatDate(event.occurred_at || event.created_at)}</time></div>`).join("") : '<div class="empty-state"><strong>Nema događaja</strong><p>Sinhronizovani događaji će se pojaviti ovde.</p></div>';
}

async function loadMembers() {
  state.members = await api("/api/v1/members");
  $("#members-list").innerHTML = state.members.map(member => `<div class="list-row"><div><strong>${escapeHtml(member.full_name)}</strong><small>${escapeHtml(member.email)}</small></div><div><strong>${escapeHtml(roleNames[member.role] || member.role)}</strong><small>Uloga u firmi</small></div><div><small>${member.is_active ? "Aktivan nalog" : "Neaktivan nalog"}</small></div><span class="status ${member.is_active ? "accepted" : "error"}">${member.is_active ? "Aktivan" : "Neaktivan"}</span></div>`).join("");
}

async function loadSessions() {
  state.sessions = await api("/api/v1/auth/sessions", {tenant:false});
  const active = state.sessions.filter(session => !session.revoked_at);
  $("#sessions-list").innerHTML = active.length ? active.map(session => `<div class="list-row"><div><strong>${session.current ? "Trenutna sesija" : "Drugi uređaj"}</strong><small>${escapeHtml(session.user_agent || "Nepoznat pregledač")}</small></div><div><strong>${escapeHtml(session.ip_address || "Nepoznata IP adresa")}</strong><small>Prijava ${formatDate(session.created_at)}</small></div><div><small>Važi do ${formatDate(session.expires_at)}</small></div>${session.current ? '<span class="status accepted">Aktivna</span>' : `<button class="secondary revoke-session" data-session-id="${session.id}">Opozovi</button>`}</div>`).join("") : '<div class="empty-state"><strong>Nema aktivnih sesija</strong></div>';
  $$(".revoke-session").forEach(button => button.onclick = async () => { try { await api(`/api/v1/auth/sessions/${button.dataset.sessionId}`, {method:"DELETE", tenant:false}); showToast("Sesija je opozvana."); await loadSessions(); } catch (error) { showToast(error.message, true); } });
}

async function loadIntegrations() {
  state.integrations = await api("/api/v1/integrations");
  const definitions = [{provider:"sef", name:"SEF eFakture", base_url:"https://efaktura.mfin.gov.rs"},{provider:"eotpremnice", name:"eOtpremnice", base_url:"https://api.eotpremnica.mfin.gov.rs"}];
  $("#integration-list").innerHTML = definitions.map(item => {
    const existing = state.integrations.find(value => value.provider === item.provider); const disabled = canAdminister() ? "" : "disabled";
    return `<article class="panel integration-card"><h3>${item.name}</h3><span class="integration-state ${existing ? "connected" : ""}">${existing ? "Povezano" : "Nije povezano"}</span><form class="integration-form" data-provider="${item.provider}"><label>API adresa<input name="base_url" type="url" value="${escapeHtml(existing?.base_url || item.base_url)}" required ${disabled}></label><label>${existing ? "Novi API ključ (za zamenu)" : "API ključ"}<input name="api_key" type="password" autocomplete="new-password" required ${disabled}></label><button class="primary" ${disabled}>${existing ? "Zameni ključ" : "Poveži servis"}</button></form></article>`;
  }).join("");
  $$(".integration-form").forEach(form => form.addEventListener("submit", saveIntegration));
}

async function saveIntegration(event) {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  try { await api("/api/v1/integrations", {method:"PUT", body:JSON.stringify({provider:form.dataset.provider, base_url:data.base_url, api_key:data.api_key, settings:{}})}); form.reset(); showToast("Povezivanje je sačuvano."); await loadIntegrations(); } catch (error) { showToast(error.message, true); }
}

function showView(name) {
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item[data-view]").forEach(item => item.classList.toggle("active", item.dataset.view === name));
  $(".sidebar").classList.remove("open");
}

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
  if (!data.mfa_code) delete data.mfa_code;
  try { const result = await api("/api/v1/auth/login", {method:"POST", body:JSON.stringify(data), tenant:false}); sessionStorage.setItem(tokenKey, result.access_token); $("#login-error").textContent = ""; await initializeApp(); } catch (error) { $("#login-error").textContent = error.message; }
});

$("#forgot-password").onclick = () => {
  $("#reset-request-error").textContent = "";
  $("#reset-request-dialog").showModal();
};

$("#reset-request-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await api("/api/v1/auth/password-reset/request", {method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(form))), tenant:false});
    $("#reset-request-dialog").close();
    form.reset();
    showToast(result.message);
  } catch (error) { $("#reset-request-error").textContent = error.message; }
});

$("#reset-confirm-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  try {
    const result = await api("/api/v1/auth/password-reset/confirm", {method:"POST", body:JSON.stringify(data), tenant:false});
    $("#reset-confirm-dialog").close();
    history.replaceState({}, "", location.pathname);
    form.reset();
    showToast(result.message);
  } catch (error) { $("#reset-confirm-error").textContent = error.message; }
});

$("#mfa-setup-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await api("/api/v1/auth/mfa/setup", {method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(form))), tenant:false});
    $("#mfa-secret").innerHTML = `<strong>Ručni ključ:</strong> ${escapeHtml(result.secret)}<br><small>URI: ${escapeHtml(result.provisioning_uri)}</small>`;
    $("#mfa-confirm-form").hidden = false;
    $("#mfa-result").innerHTML = "";
    form.reset();
  } catch (error) { showToast(error.message, true); }
});

$("#mfa-confirm-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await api("/api/v1/auth/mfa/confirm", {method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(form))), tenant:false});
    $("#mfa-result").innerHTML = `<p><strong>MFA je uključen. Sačuvajte rezervne kodove:</strong></p><div class="recovery-codes">${result.recovery_codes.map(code => `<code>${escapeHtml(code)}</code>`).join("")}</div>`;
    form.hidden = true;
    showToast("Dvofaktorska prijava je uključena.");
  } catch (error) { showToast(error.message, true); }
});

$("#organization-select").addEventListener("change", async event => {
  state.organization = state.organizations.find(item => item.id === event.target.value); sessionStorage.setItem(organizationKey, state.organization.id);
  $("#new-document-button").hidden = !canEdit(); $("#invite-button").hidden = !canAdminister(); await loadWorkspace();
});

$("#document-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const formData = new FormData(form); const file = formData.get("xml_file");
  const issueDate = formData.get("issue_date"); const payload = {provider:formData.get("provider"), direction:formData.get("direction"), document_type:formData.get("document_type"), document_number:formData.get("document_number") || null, idempotency_key:`ui-${Date.now()}-${crypto.randomUUID()}`, issue_date:issueDate ? new Date(`${issueDate}T00:00:00`).toISOString() : null, counterparty_name:formData.get("counterparty_name") || null, counterparty_tax_id:formData.get("counterparty_tax_id") || null, currency:formData.get("currency") || null, total_amount:formData.get("total_amount") || null, payload:{source:"web_ui"}};
  try {
    const doc = await api("/api/v1/documents", {method:"POST", body:JSON.stringify(payload)});
    if (file && file.size) { const upload = new FormData(); upload.append("kind", "source_xml"); upload.append("file", file); await api(`/api/v1/documents/${doc.id}/artifacts`, {method:"POST", body:upload}); if (formData.get("queue_after_upload") && payload.direction === "outbound") await api(`/api/v1/documents/${doc.id}/queue`, {method:"POST"}); }
    $("#document-dialog").close(); form.reset(); form.elements.currency.value = "RSD"; form.elements.document_type.value = "sales_invoice"; showToast("Dokument je sačuvan."); await loadDocuments(); await loadJobs();
  } catch (error) { $("#document-error").textContent = error.message; }
});

$("#invite-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  try { const invitation = await api("/api/v1/invitations", {method:"POST", body:JSON.stringify({...data, expires_in_hours:72})}); form.innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">POZIV JE KREIRAN</p><h2>Jednokratni token</h2></div><button type="button" class="icon-button" id="close-invite-result">×</button></div><p class="muted">Bezbedno ga dostavite korisniku. Posle zatvaranja se više neće prikazati.</p><div class="token-box">${escapeHtml(invitation.invitation_token)}</div><div class="dialog-actions"><button type="button" class="primary" id="copy-invite-token">Kopiraj token</button></div>`; $("#close-invite-result").onclick = () => $("#invite-dialog").close(); $("#copy-invite-token").onclick = async () => { await navigator.clipboard.writeText(invitation.invitation_token); showToast("Token je kopiran."); }; } catch (error) { $("#invite-error").textContent = error.message; }
});

$("#document-form [name=provider]").addEventListener("change", event => { $("#document-form [name=document_type]").value = event.target.value === "sef" ? "sales_invoice" : "despatch_advice"; });
$("#new-document-button").onclick = () => { $("#document-error").textContent = ""; $("#document-dialog").showModal(); };
$("#invite-button").onclick = () => {
  const form = $("#invite-form");
  form.innerHTML = inviteFormMarkup;
  form.querySelector(".close-dialog").onclick = () => $("#invite-dialog").close();
  $("#invite-dialog").showModal();
};
$("#refresh-button").onclick = async () => { await loadWorkspace(); showToast("Podaci su osveženi."); };
$("#logout").onclick = async () => { try { await api("/api/v1/auth/logout", {method:"POST", tenant:false}); } finally { clearSession(); } };
$("#menu-button").onclick = () => $(".sidebar").classList.toggle("open");
$$('.close-dialog').forEach(button => button.onclick = () => button.closest("dialog").close());
$$('.nav-item[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
[$("#document-search"), $("#provider-filter"), $("#status-filter")].forEach(control => control.addEventListener("input", renderDocuments));

const resetToken = new URLSearchParams(location.search).get("reset_token");
if (resetToken) {
  $("#reset-confirm-form [name=token]").value = resetToken;
  $("#reset-confirm-dialog").showModal();
}

if (sessionStorage.getItem(tokenKey)) initializeApp();

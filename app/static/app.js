const tokenKey = "edokumenti_access_token";
const organizationKey = "edokumenti_organization_id";
const state = {organizations: [], organization: null, documents: [], customers: [], items: [], jobs: [], events: [], members: [], sessions: [], integrations: []};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const inviteFormMarkup = $("#invite-form").innerHTML;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function refreshRequiredMarkers(root = document) {
  root.querySelectorAll("label").forEach(label => {
    const controls = [...label.querySelectorAll("input, select, textarea")].filter(control => control.closest("label") === label);
    if (!controls.length) return;
    if (["checkbox", "radio"].includes(controls[0].type)) return;
    let caption = [...label.children].find(child => child.classList?.contains("field-label"));
    if (!caption) {
      caption = document.createElement("span"); caption.className = "field-label";
      [...label.childNodes].filter(node => node !== controls[0] && !controls[0].contains(node)).forEach(node => caption.append(node));
      label.insertBefore(caption, controls[0]);
    }
    const required = controls.some(control => control.required && !control.disabled && control.type !== "hidden");
    let marker = caption.querySelector(".required-marker");
    if (required && !marker) {
      marker = document.createElement("span"); marker.className = "required-marker"; marker.textContent = " *"; marker.title = "Obavezno polje"; marker.setAttribute("aria-hidden", "true");
      caption.append(marker);
    } else if (!required && marker) marker.remove();
  });
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
const unitNames = {H87:"Komad",KGM:"Kilogram",LTR:"Litar",MTR:"Metar",MTK:"m²",MTQ:"m³",HUR:"Sat",DAY:"Dan",XPK:"Paket"};
const vatNames = {"20:S":"20%","10:S":"10%","0:Z":"0%","0:O":"Nije u PDV sistemu","0:E":"Oslobođeno PDV-a"};

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
  const publicAuthPaths = ["/api/v1/auth/login", "/api/v1/auth/invitations/accept"];
  if (response.status === 401 && !publicAuthPaths.includes(path)) clearSession();
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

function renderOrganizationSelect(preferredId = null) {
  const savedId = preferredId || sessionStorage.getItem(organizationKey);
  state.organization = state.organizations.find(item => item.id === savedId) || state.organizations[0];
  const select = $("#organization-select");
  select.innerHTML = state.organizations.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(roleNames[item.role] || item.role)}</option>`).join("");
  select.value = state.organization.id;
  sessionStorage.setItem(organizationKey, state.organization.id);
}

async function initializeApp() {
  try {
    state.organizations = await api("/api/v1/organizations", {tenant: false});
    if (!state.organizations.length) throw new Error("Korisnik nema pristup nijednoj firmi");
    renderOrganizationSelect();
    $("#auth-view").hidden = true;
    $("#app-view").hidden = false;
    $("#new-document-button").hidden = !canEdit();
    $("#new-customer-button").hidden = !canEdit();
    $("#new-item-button").hidden = !canEdit();
    $("#invite-button").hidden = !canAdminister();
    await loadWorkspace();
  } catch (error) {
    if (sessionStorage.getItem(tokenKey)) showToast(error.message, true);
  }
}

async function loadWorkspace() {
  renderOrganizationProfile();
  const loaders = [loadDocuments(), loadCustomers(), loadCatalogItems(), loadJobs(), loadEvents(), loadMembers(), loadSessions(), loadIntegrations()];
  const results = await Promise.allSettled(loaders);
  const failed = results.find(result => result.status === "rejected");
  if (failed) showToast(failed.reason.message, true);
}

function renderOrganizationProfile() {
  const form = $("#organization-profile-form"); const profile = state.organization?.profile || {};
  form.reset();
  ["name", "tax_id", "registration_number"].forEach(name => { form.elements[name].value = state.organization?.[name] || ""; });
  Object.entries(profile).forEach(([name, value]) => { if (form.elements[name]) form.elements[name].value = value || ""; });
  form.elements.country_code.value = profile.country_code || "RS";
  form.querySelectorAll("input,button").forEach(control => { control.disabled = !canAdminister(); });
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

async function loadCustomers() {
  state.customers = await api("/api/v1/customers");
  renderCustomers();
  populateCustomerSelector();
}

function renderCustomers() {
  const search = $("#customer-search").value.trim().toLowerCase();
  const customers = state.customers.filter(customer => `${customer.name} ${customer.tax_id} ${customer.city}`.toLowerCase().includes(search));
  $("#customer-rows").innerHTML = customers.map(customer => `<tr><td><strong>${escapeHtml(customer.name)}</strong><small>${escapeHtml(customer.street)}</small></td><td>${escapeHtml(customer.tax_id)}<small>${escapeHtml(customer.registration_number || "")}</small></td><td><strong>${escapeHtml(customer.city)}</strong><small>${escapeHtml(customer.postal_code)}</small></td><td>${escapeHtml(customer.email || "—")}<small>${escapeHtml(customer.phone || "")}</small></td><td>${canEdit() ? `<button class="row-action edit-customer" data-id="${customer.id}">Izmeni</button>` : ""}</td></tr>`).join("");
  $("#customers-empty").hidden = customers.length > 0;
  $$(".edit-customer").forEach(button => button.onclick = () => openCustomerDialog(state.customers.find(customer => customer.id === button.dataset.id)));
}

function populateCustomerSelector() {
  const select = $("#document-customer-select");
  const selected = select.value;
  select.innerHTML = '<option value="">Ručni unos / novi kupac</option>' + state.customers.map(customer => `<option value="${customer.id}">${escapeHtml(customer.name)} · ${escapeHtml(customer.tax_id)}</option>`).join("");
  if (state.customers.some(customer => customer.id === selected)) select.value = selected;
}

function fillCustomer(customer) {
  if (!customer) return;
  const form = $("#document-form");
  const values = {customer_name:customer.name,customer_tax_id:customer.tax_id,customer_registration_number:customer.registration_number,customer_street:customer.street,customer_city:customer.city,customer_postal_code:customer.postal_code,customer_country_code:customer.country_code,customer_email:customer.email,customer_jbkjs:customer.jbkjs};
  Object.entries(values).forEach(([name, value]) => { form.elements[name].value = value || ""; });
}

function openCustomerDialog(customer = null) {
  const form = $("#customer-form"); form.reset(); form.elements.country_code.value = "RS";
  $("#customer-dialog-title").textContent = customer ? "Izmena kupca" : "Novi kupac";
  if (customer) Object.keys(customer).forEach(name => { if (form.elements[name]) form.elements[name].value = customer[name] ?? ""; });
  $("#customer-error").textContent = ""; $("#customer-dialog").showModal();
}

async function loadCatalogItems() {
  state.items = await api("/api/v1/catalog-items");
  renderCatalogItems();
}

function renderCatalogItems() {
  const search = $("#item-search").value.trim().toLowerCase();
  const items = state.items.filter(item => `${item.name} ${item.sku} ${item.gtin || ""}`.toLowerCase().includes(search));
  $("#item-rows").innerHTML = items.map(item => `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description || "")}</small></td><td>${escapeHtml(item.sku)}<small>${escapeHtml(item.gtin || "")}</small></td><td>${escapeHtml(unitNames[item.unit_code] || item.unit_code)}</td><td>${formatAmount(item.unit_price)}</td><td>${escapeHtml(vatNames[`${Number(item.vat_rate)}:${item.vat_category}`] || `${item.vat_rate}%`)}</td><td>${canEdit() ? `<button class="row-action edit-item" data-id="${item.id}">Izmeni</button>` : ""}</td></tr>`).join("");
  $("#items-empty").hidden = items.length > 0;
  $$(".edit-item").forEach(button => button.onclick = () => openItemDialog(state.items.find(item => item.id === button.dataset.id)));
}

function openItemDialog(item = null) {
  const form = $("#item-form"); form.reset();
  $("#item-dialog-title").textContent = item ? "Izmena artikla ili usluge" : "Novi artikal ili usluga";
  if (item) {
    Object.keys(item).forEach(name => { if (form.elements[name]) form.elements[name].value = item[name] ?? ""; });
    form.elements.vat_choice.value = `${Number(item.vat_rate)}:${item.vat_category}`;
  }
  $("#item-error").textContent = ""; $("#item-dialog").showModal();
}

async function showDocument(documentId) {
  const doc = state.documents.find(item => item.id === documentId);
  if (!doc) return;
  const editable = canEdit() && doc.direction === "outbound" && ["draft", "error"].includes(doc.status) && !doc.external_id && doc.payload?.source === "business_form";
  const deletable = canEdit() && doc.direction === "outbound" && doc.status === "draft" && !doc.external_id;
  let artifacts = [];
  try { artifacts = await api(`/api/v1/documents/${documentId}/artifacts`); } catch (error) { showToast(error.message, true); }
  $("#document-detail").innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">DETALJI DOKUMENTA</p><h2>${escapeHtml(doc.document_number || documentTypeNames[doc.document_type] || doc.document_type)}</h2></div><button class="icon-button" id="close-detail" aria-label="Zatvori">×</button></div>
    <span class="status ${doc.status}">${escapeHtml(statusNames[doc.status] || doc.status)}</span>
    <div class="detail-grid"><div class="detail-item"><span>Servis</span><strong>${doc.provider === "sef" ? "SEF" : "eOtpremnice"}</strong></div><div class="detail-item"><span>Udaljeni status</span><strong>${escapeHtml(doc.remote_status || "—")}</strong></div><div class="detail-item"><span>Partner</span><strong>${escapeHtml(doc.counterparty_name || "—")}</strong></div><div class="detail-item"><span>Iznos</span><strong>${formatAmount(doc.total_amount, doc.currency)}</strong></div></div>
    <h3>Prilozi</h3><div class="artifact-list">${artifacts.length ? artifacts.map(file => `<div class="artifact"><div><strong>${escapeHtml(file.kind)}</strong><small>${Math.ceil(file.size_bytes / 1024)} KB · ${escapeHtml(file.sha256.slice(0, 12))}…</small></div><button class="secondary artifact-download" data-artifact-id="${file.id}">Preuzmi</button></div>`).join("") : '<p class="muted">Nema priloga.</p>'}</div>
    ${doc.last_error ? `<p class="form-error">${escapeHtml(doc.last_error)}</p>` : ""}
    <div class="dialog-actions">${deletable ? '<button class="danger-button" id="delete-detail">Obriši nacrt</button>' : ""}<button class="secondary" id="close-detail-bottom">Zatvori</button>${editable ? '<button class="secondary" id="edit-detail">Izmeni</button>' : ""}${canEdit() && doc.direction === "outbound" && doc.status === "draft" ? '<button class="primary" id="queue-detail">Pošalji u red</button>' : ""}</div>`;
  const dialog = $("#detail-dialog"); dialog.showModal();
  $("#close-detail").onclick = () => dialog.close(); $("#close-detail-bottom").onclick = () => dialog.close();
  const queue = $("#queue-detail"); if (queue) queue.onclick = async () => { try { await api(`/api/v1/documents/${doc.id}/queue`, {method:"POST"}); dialog.close(); showToast("Dokument je dodat u red."); await loadDocuments(); await loadJobs(); } catch (error) { showToast(error.message, true); } };
  const edit = $("#edit-detail"); if (edit) edit.onclick = () => openDocumentEditor(doc);
  const remove = $("#delete-detail"); if (remove) remove.onclick = async () => {
    if (!confirm(`Obrisati nacrt ${doc.document_number || "bez broja"}? Ova radnja se ne može poništiti.`)) return;
    try { await api(`/api/v1/documents/${doc.id}`, {method:"DELETE"}); dialog.close(); showToast("Nacrt je obrisan."); await loadDocuments(); await loadJobs(); } catch (error) { showToast(error.message, true); }
  };
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
  const definitions = [{provider:"sef", name:"SEF eFakture"},{provider:"eotpremnice", name:"eOtpremnice"}];
  $("#integration-list").innerHTML = definitions.map(item => {
    const existing = state.integrations.find(value => value.provider === item.provider); const disabled = canAdminister() ? "" : "disabled";
    const environment = existing?.settings?.environment || (existing?.base_url.includes("demo") ? "demo" : "production");
    return `<article class="panel integration-card"><h3>${item.name}</h3><span class="integration-state ${existing ? "connected" : ""}" data-integration-state="${item.provider}">${existing ? `${environment === "demo" ? "Demo" : "Produkcija"} povezano` : "Nije povezano"}</span><form class="integration-form" data-provider="${item.provider}"><label>Okruženje<select name="environment" ${disabled}><option value="demo" ${environment === "demo" ? "selected" : ""}>Demo - bez produkcionih dokumenata</option><option value="production" ${environment === "production" ? "selected" : ""}>Produkcija - stvarni dokumenti</option></select></label><p class="environment-warning">Za lokalno testiranje koristi Demo. API ključ mora biti generisan u istom demo portalu.</p><label>${existing ? "Novi API ključ (za zamenu)" : "API ključ"}<input name="api_key" type="password" autocomplete="new-password" required ${disabled}></label><div class="integration-actions"><button class="primary" ${disabled}>${existing ? "Sačuvaj povezivanje" : "Poveži servis"}</button>${existing ? `<button class="secondary test-integration" type="button" data-provider="${item.provider}" ${disabled}>Proveri vezu</button>` : ""}</div></form></article>`;
  }).join("");
  $$(".integration-form").forEach(form => form.addEventListener("submit", saveIntegration));
  $$(".test-integration").forEach(button => button.addEventListener("click", testIntegration));
  refreshRequiredMarkers($("#integration-list"));
}

async function testIntegration(event) {
  const button = event.currentTarget; const provider = button.dataset.provider; button.disabled = true;
  try { const result = await api(`/api/v1/integrations/${provider}/test`, {method:"POST"}); const badge = $(`[data-integration-state="${provider}"]`); badge.textContent = "Veza proverena"; badge.classList.add("connected"); showToast(result.message); } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
}

async function saveIntegration(event) {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  if (data.environment === "production" && !confirm("Povezujete PRODUKCIONO okruženje. Dokumenti mogu imati pravno dejstvo. Nastaviti?")) return;
  try { await api("/api/v1/integrations", {method:"PUT", body:JSON.stringify({provider:form.dataset.provider, environment:data.environment, api_key:data.api_key, settings:{}})}); form.reset(); showToast(`${data.environment === "demo" ? "Demo" : "Produkcijsko"} povezivanje je sačuvano.`); await loadIntegrations(); } catch (error) { showToast(error.message, true); }
}

$("#organization-profile-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  ["registration_number", "bank_account", "phone", "jbkjs"].forEach(name => { if (!data[name]) data[name] = null; });
  data.country_code = data.country_code.toUpperCase();
  try {
    const updated = await api("/api/v1/organizations/current", {method:"PATCH", body:JSON.stringify(data)});
    state.organizations = state.organizations.map(item => item.id === updated.id ? updated : item);
    renderOrganizationSelect(updated.id); renderOrganizationProfile(); showToast("Podaci firme su sačuvani.");
  } catch (error) { showToast(error.message, true); }
});

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
  $("#new-document-button").hidden = !canEdit(); $("#new-customer-button").hidden = !canEdit(); $("#new-item-button").hidden = !canEdit(); $("#invite-button").hidden = !canAdminister(); await loadWorkspace();
});

$("#organization-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  if (!data.registration_number) data.registration_number = null;
  try {
    const organization = await api("/api/v1/organizations", {method:"POST", body:JSON.stringify(data), tenant:false});
    state.organizations = await api("/api/v1/organizations", {tenant:false});
    renderOrganizationSelect(organization.id);
    $("#organization-dialog").close();
    form.reset();
    $("#new-document-button").hidden = !canEdit();
    $("#invite-button").hidden = !canAdminister();
    await loadWorkspace();
    showToast("Firma je kreirana.");
  } catch (error) { $("#organization-error").textContent = error.message; }
});

const plannedDespatchLabel = $("#document-form [name=planned_despatch_at]").closest("label");
const actualDespatchLabel = document.createElement("label");
actualDespatchLabel.innerHTML = 'Stvarni polazak<input name="actual_despatch_at" type="datetime-local">';
plannedDespatchLabel.after(actualDespatchLabel);

let documentLineSequence = 0;
let editingDocumentId = null;

function addDocumentLine(line = null) {
  documentLineSequence += 1;
  const row = document.createElement("div"); row.className = "document-line";
  const itemOptions = state.items.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(item.sku)}</option>`).join("");
  row.innerHTML = `<div class="line-heading"><strong>Stavka ${documentLineSequence}</strong><button type="button" class="icon-button remove-line" aria-label="Ukloni stavku">×</button></div><div class="form-grid"><label class="span-2">Izaberite artikal ili uslugu<select class="line-item-picker"><option value="">Ručni unos</option>${itemOptions}</select></label><label class="span-2">Naziv<input name="line_name" required maxlength="300"></label><label>Šifra artikla<input name="line_sku" maxlength="100"></label><label>GTIN<input name="line_gtin" maxlength="30"></label><label>Količina<input name="line_quantity" type="number" min="0.000001" step="0.000001" value="1" required></label><label>Jedinica mere<select name="line_unit" required><option value="H87">Komad</option><option value="KGM">Kilogram</option><option value="LTR">Litar</option><option value="MTR">Metar</option><option value="MTK">m²</option><option value="MTQ">m³</option><option value="HUR">Sat</option><option value="DAY">Dan</option><option value="XPK">Paket</option></select></label><label class="invoice-line-field">Cena bez PDV<input name="line_price" type="number" min="0" step="0.01" required></label><label class="invoice-line-field">PDV<select name="line_vat_choice"><option value="20:S">20%</option><option value="10:S">10%</option><option value="0:Z">0%</option><option value="0:O">Nije u PDV sistemu</option><option value="0:E">Oslobođeno PDV-a</option></select></label><label class="span-2">Opis <span class="optional">(opciono)</span><input name="line_description" maxlength="1000"></label></div>`;
  row.querySelector(".remove-line").onclick = () => { if ($$(".document-line").length > 1) row.remove(); };
  row.querySelector(".line-item-picker").onchange = event => {
    const item = state.items.find(candidate => candidate.id === event.target.value);
    if (!item) return;
    const values = {line_name:item.name,line_sku:item.sku,line_gtin:item.gtin,line_quantity:"1",line_unit:item.unit_code,line_price:item.unit_price,line_vat_choice:`${Number(item.vat_rate)}:${item.vat_category}`,line_description:item.description};
    Object.entries(values).forEach(([name, value]) => { const control = row.querySelector(`[name=${name}]`); if (control) control.value = value ?? ""; });
  };
  if (line) {
    const values = {line_name:line.name,line_sku:line.seller_item_id,line_gtin:line.gtin,line_quantity:line.quantity,line_unit:line.unit_code,line_price:line.unit_price,line_vat_choice:`${Number(line.vat_rate || 0)}:${line.vat_category || "S"}`,line_description:line.description};
    Object.entries(values).forEach(([name, value]) => { const control = row.querySelector(`[name=${name}]`); if (control) control.value = value ?? ""; });
  }
  $("#document-lines").append(row); toggleDocumentType();
}

function toggleDocumentType() {
  const provider = $("#document-form [name=provider]").value; const invoice = provider === "sef";
  $("#invoice-fields").hidden = !invoice; $("#invoice-fields").disabled = !invoice;
  $("#despatch-fields").hidden = invoice; $("#despatch-fields").disabled = invoice;
  $$(".invoice-line-field").forEach(field => {
    field.hidden = !invoice;
    field.querySelectorAll("input,select").forEach(control => { control.disabled = !invoice; });
  });
  ["shipment_id", "planned_despatch_at", "actual_despatch_at", "planned_delivery_at", "despatch_street", "despatch_city", "despatch_postal_code", "despatch_country_code", "delivery_street", "delivery_city", "delivery_postal_code", "delivery_country_code"].forEach(name => { $("#document-form").elements[name].required = !invoice; });
  refreshRequiredMarkers($("#document-form"));
}

function documentLines(provider) {
  return $$(".document-line").map(row => {
    const value = name => row.querySelector(`[name=${name}]`).value.trim();
    const line = {name:value("line_name"), description:value("line_description") || null, seller_item_id:value("line_sku") || null, gtin:value("line_gtin") || null, quantity:Number(value("line_quantity")), unit_code:value("line_unit")};
    if (provider === "sef") { const [rate, category] = value("line_vat_choice").split(":"); line.unit_price = Number(value("line_price")); line.vat_rate = Number(rate); line.vat_category = category; }
    return line;
  });
}

function resetDocumentForm() {
  const form = $("#document-form"); form.reset(); editingDocumentId = null; documentLineSequence = 0; $("#document-lines").innerHTML = ""; addDocumentLine();
  $("#document-dialog-eyebrow").textContent = "NOVI POSLOVNI DOKUMENT"; $("#document-dialog-title").textContent = "Unos bez XML-a"; $("#document-submit-button").textContent = "Generiši dokument";
  const today = new Date().toISOString().slice(0, 10); form.elements.issue_date.value = today; form.elements.delivery_date.value = today;
  const due = new Date(); due.setDate(due.getDate() + 15); form.elements.due_date.value = due.toISOString().slice(0, 10); toggleDocumentType();
}

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value); if (Number.isNaN(date.valueOf())) return String(value).slice(0, 16);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function openDocumentEditor(doc) {
  const data = doc.payload?.form; if (!data) return;
  resetDocumentForm(); editingDocumentId = doc.id;
  $("#document-dialog-eyebrow").textContent = doc.status === "error" ? "ISPRAVKA NEUSPEŠNOG DOKUMENTA" : "IZMENA NACRTA";
  $("#document-dialog-title").textContent = doc.document_number || "Izmena dokumenta"; $("#document-submit-button").textContent = "Sačuvaj izmene";
  const form = $("#document-form");
  ["provider", "document_number", "issue_date", "note"].forEach(name => { form.elements[name].value = data[name] || ""; });
  const customer = data.customer || {}; const address = customer.address || {};
  const customerValues = {customer_name:customer.name,customer_tax_id:customer.tax_id,customer_registration_number:customer.registration_number,customer_street:address.street,customer_city:address.city,customer_postal_code:address.postal_code,customer_country_code:address.country_code,customer_email:customer.email,customer_jbkjs:customer.jbkjs};
  Object.entries(customerValues).forEach(([name, value]) => { form.elements[name].value = value || ""; });
  const savedCustomer = state.customers.find(item => item.tax_id === customer.tax_id); $("#document-customer-select").value = savedCustomer?.id || "";
  if (data.provider === "sef") {
    ["delivery_date", "due_date", "currency", "payment_account", "payment_reference"].forEach(name => { form.elements[name].value = data[name] || ""; });
  } else {
    const values = {despatch_type:data.despatch_type,shipment_id:data.shipment_id,shipment_method:data.shipment_method,order_reference:data.order_reference,planned_despatch_at:localDateTimeValue(data.planned_despatch_at),actual_despatch_at:localDateTimeValue(data.actual_despatch_at),planned_delivery_at:localDateTimeValue(data.planned_delivery_at),despatch_street:data.despatch_address?.street,despatch_city:data.despatch_address?.city,despatch_postal_code:data.despatch_address?.postal_code,despatch_country_code:data.despatch_address?.country_code,delivery_street:data.delivery_address?.street,delivery_city:data.delivery_address?.city,delivery_postal_code:data.delivery_address?.postal_code,delivery_country_code:data.delivery_address?.country_code,gross_weight:data.gross_weight,package_count:data.package_count,carrier_name:data.carrier_name,carrier_tax_id:data.carrier_tax_id,carrier_registration_number:data.carrier_registration_number,vehicle_plate:data.vehicle_plate,driver_name:data.driver_name,driver_email:data.driver_email};
    Object.entries(values).forEach(([name, value]) => { if (form.elements[name]) form.elements[name].value = value ?? ""; });
  }
  documentLineSequence = 0; $("#document-lines").innerHTML = ""; (data.lines || []).forEach(line => addDocumentLine(line)); if (!data.lines?.length) addDocumentLine();
  form.elements.queue_after_create.checked = false; toggleDocumentType(); $("#document-error").textContent = ""; $("#detail-dialog").close(); $("#document-dialog").showModal();
}

$("#document-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const provider = data.provider;
  const customer = {name:data.customer_name, tax_id:data.customer_tax_id, registration_number:data.customer_registration_number || null, email:data.customer_email || null, jbkjs:data.customer_jbkjs || null, address:{street:data.customer_street, city:data.customer_city, postal_code:data.customer_postal_code, country_code:data.customer_country_code.toUpperCase()}};
  const payload = {provider, document_number:data.document_number, issue_date:data.issue_date, note:data.note || null, customer, lines:documentLines(provider), queue_after_create:Boolean(data.queue_after_create)};
  if (provider === "sef") Object.assign(payload, {delivery_date:data.delivery_date, due_date:data.due_date, currency:data.currency, payment_account:data.payment_account || null, payment_reference:data.payment_reference || null});
  else Object.assign(payload, {despatch_type:data.despatch_type, shipment_id:data.shipment_id, shipment_method:data.shipment_method, order_reference:data.order_reference || null, planned_despatch_at:new Date(data.planned_despatch_at).toISOString(), actual_despatch_at:new Date(data.actual_despatch_at).toISOString(), planned_delivery_at:new Date(data.planned_delivery_at).toISOString(), despatch_address:{street:data.despatch_street, city:data.despatch_city, postal_code:data.despatch_postal_code, country_code:data.despatch_country_code.toUpperCase()}, delivery_address:{street:data.delivery_street, city:data.delivery_city, postal_code:data.delivery_postal_code, country_code:data.delivery_country_code.toUpperCase()}, gross_weight:data.gross_weight ? Number(data.gross_weight) : null, package_count:data.package_count ? Number(data.package_count) : null, carrier_name:data.carrier_name || null, carrier_tax_id:data.carrier_tax_id || null, carrier_registration_number:data.carrier_registration_number || null, vehicle_plate:data.vehicle_plate || null, driver_name:data.driver_name || null, driver_email:data.driver_email || null});
  const path = editingDocumentId ? `/api/v1/documents/${editingDocumentId}/from-form` : "/api/v1/documents/from-form";
  try { await api(path, {method:editingDocumentId ? "PUT" : "POST", body:JSON.stringify(payload)}); $("#document-dialog").close(); showToast(editingDocumentId ? "Izmene su sačuvane i XML je ponovo generisan." : (data.queue_after_create ? "Dokument je generisan i dodat u red." : "Dokument i UBL XML su sačuvani.")); editingDocumentId = null; await loadDocuments(); await loadJobs(); } catch (error) { $("#document-error").textContent = error.message; }
});

$("#customer-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const id = data.id; delete data.id;
  ["registration_number", "email", "phone", "jbkjs", "notes"].forEach(name => { if (!data[name]) data[name] = null; });
  data.country_code = data.country_code.toUpperCase();
  try {
    const customer = await api(id ? `/api/v1/customers/${id}` : "/api/v1/customers", {method:id ? "PUT" : "POST", body:JSON.stringify(data)});
    $("#customer-dialog").close(); await loadCustomers();
    if ($("#document-dialog").open) { $("#document-customer-select").value = customer.id; fillCustomer(customer); }
    showToast(id ? "Podaci kupca su izmenjeni." : "Kupac je sačuvan u imenik.");
  } catch (error) { $("#customer-error").textContent = error.message; }
});

$("#item-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const id = data.id; delete data.id;
  const [vatRate, vatCategory] = data.vat_choice.split(":"); delete data.vat_choice;
  data.vat_rate = Number(vatRate); data.vat_category = vatCategory; data.unit_price = Number(data.unit_price);
  ["gtin", "description"].forEach(name => { if (!data[name]) data[name] = null; });
  try {
    await api(id ? `/api/v1/catalog-items/${id}` : "/api/v1/catalog-items", {method:id ? "PUT" : "POST", body:JSON.stringify(data)});
    $("#item-dialog").close(); await loadCatalogItems(); showToast(id ? "Artikal je izmenjen." : "Artikal je sačuvan u šifarnik.");
  } catch (error) { $("#item-error").textContent = error.message; }
});

$("#invite-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
  try { const invitation = await api("/api/v1/invitations", {method:"POST", body:JSON.stringify({...data, expires_in_hours:72})}); const invitationLink = `${location.origin}/?invitation_token=${encodeURIComponent(invitation.invitation_token)}`; form.innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">POZIV JE KREIRAN</p><h2>Link je spreman</h2></div><button type="button" class="icon-button" id="close-invite-result">×</button></div><p class="muted">Poziv je dodat u email red. Link možete i ručno dostaviti korisniku.</p><div class="token-box">${escapeHtml(invitationLink)}</div><div class="dialog-actions"><button type="button" class="primary" id="copy-invite-token">Kopiraj link</button></div>`; $("#close-invite-result").onclick = () => $("#invite-dialog").close(); $("#copy-invite-token").onclick = async () => { await navigator.clipboard.writeText(invitationLink); showToast("Link je kopiran."); }; } catch (error) { $("#invite-error").textContent = error.message; }
});

$("#accept-invitation-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  if (!data.full_name) data.full_name = null;
  try {
    const result = await api("/api/v1/auth/invitations/accept", {method:"POST", body:JSON.stringify(data), tenant:false});
    sessionStorage.setItem(tokenKey, result.access_token);
    history.replaceState({}, "", location.pathname);
    $("#accept-invitation-dialog").close();
    form.reset();
    await initializeApp();
    showToast("Poziv je prihvaćen.");
  } catch (error) { $("#accept-invitation-error").textContent = error.message; }
});

$("#document-form [name=provider]").addEventListener("change", toggleDocumentType);
$("#document-customer-select").addEventListener("change", event => fillCustomer(state.customers.find(customer => customer.id === event.target.value)));
$("#add-document-line").onclick = addDocumentLine;
$("#new-customer-button").onclick = () => openCustomerDialog();
$("#document-new-customer").onclick = () => openCustomerDialog();
$("#new-item-button").onclick = () => openItemDialog();
$("#new-document-button").onclick = () => {
  const requiredProfile = ["street", "city", "postal_code", "country_code", "email"];
  const validTaxId = /^\d{9}$/.test(state.organization?.tax_id || "");
  if (!validTaxId || requiredProfile.some(field => !state.organization?.profile?.[field])) { showView("settings"); showToast("Prvo unesite važeće pravne i poslovne podatke izabrane firme.", true); return; }
  $("#document-error").textContent = ""; resetDocumentForm(); $("#document-dialog").showModal();
};
$("#new-organization-button").onclick = () => { $("#organization-error").textContent = ""; refreshRequiredMarkers($("#organization-form")); $("#organization-dialog").showModal(); };
$("#invite-button").onclick = () => {
  const form = $("#invite-form");
  form.innerHTML = inviteFormMarkup;
  form.querySelector(".close-dialog").onclick = () => $("#invite-dialog").close();
  refreshRequiredMarkers(form);
  $("#invite-dialog").showModal();
};
$("#refresh-button").onclick = async () => { await loadWorkspace(); showToast("Podaci su osveženi."); };
$("#logout").onclick = async () => { try { await api("/api/v1/auth/logout", {method:"POST", tenant:false}); } finally { clearSession(); } };
$("#menu-button").onclick = () => $(".sidebar").classList.toggle("open");
$$('.close-dialog').forEach(button => button.onclick = () => button.closest("dialog").close());
$$('.nav-item[data-view]').forEach(button => button.onclick = () => showView(button.dataset.view));
[$("#document-search"), $("#provider-filter"), $("#status-filter")].forEach(control => control.addEventListener("input", renderDocuments));
$("#customer-search").addEventListener("input", renderCustomers);
$("#item-search").addEventListener("input", renderCatalogItems);

const resetToken = new URLSearchParams(location.search).get("reset_token");
if (resetToken) {
  $("#reset-confirm-form [name=token]").value = resetToken;
  $("#reset-confirm-dialog").showModal();
}

const invitationToken = new URLSearchParams(location.search).get("invitation_token");
if (invitationToken) {
  $("#accept-invitation-form [name=invitation_token]").value = invitationToken;
  $("#accept-invitation-dialog").showModal();
}

refreshRequiredMarkers();
if (sessionStorage.getItem(tokenKey)) initializeApp();

const tokenKey = "edokumenti_access_token";
const organizationKey = "edokumenti_organization_id";
const documentScopeKey = "edokumenti_document_scope";
const savedDocumentScope = sessionStorage.getItem(documentScopeKey);
const state = {organizations: [], organization: null, documents: [], documentAttentionCounts: {inbound:0,outbound:0,receipt:0,despatch:0}, documentTemplates: [], customers: [], items: [], jobs: [], events: [], members: [], sessions: [], integrations: [], documentScope: ["inbound", "outbound", "receipt", "despatch"].includes(savedDocumentScope) ? savedDocumentScope : "inbound"};
const autoRefreshIntervalMs = 5000;
let autoRefreshBusy = false;
let documentDraftTimer = null;
let suspendDocumentAutosave = false;

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
const remoteStatusNames = {new:"Novo",draft:"Nacrt",seen:"Pregledano",renotified:"Ponovo obavešteno",approved:"Odobreno",accepted:"Prihvaćeno",rejected:"Odbijeno",cancelled:"Otkazano",canceled:"Otkazano",storno:"Stornirano",sent:"Poslato",received:"Primljeno",paid:"Plaćeno",mistake:"Greška",overdue:"Dospelo",archived:"Arhivirano",sending:"Slanje",sendinginprogress:"Slanje u toku",deleted:"Obrisano",unknown:"Nepoznato",fulfilled:"Usaglašeno",delivered:"Fizički prijem",seized:"Zaplenjeno",deliveryconfirmed:"Fizički prijem potvrđen",transportationstarted:"Prevoz započet"};
const roleNames = {owner:"Vlasnik",admin:"Administrator",accountant:"Knjigovođa",operator:"Operater",viewer:"Pregled"};
const documentTypeNames = {sales_invoice:"Izlazna faktura",purchase_invoice:"Ulazna faktura",despatch_advice:"Otpremnica",receipt_advice:"Prijemnica"};
const unitNames = {H87:"Komad",KGM:"Kilogram",LTR:"Litar",MTR:"Metar",MTK:"m²",MTQ:"m³",HUR:"Sat",DAY:"Dan",XPK:"Paket"};
const vatNames = {"20:S":"20%","10:S":"10%","0:Z":"0%","0:O":"Nije u PDV sistemu","0:E":"Oslobođeno PDV-a"};

function providerDestination(provider) {
  return provider === "sef" ? "SEF" : "eOtpremnice";
}

function sendButtonLabel(provider) {
  return `Pošalji u ${providerDestination(provider)}`;
}

function remoteStatusName(value) {
  if (!value) return "";
  return remoteStatusNames[String(value).replace(/[^a-z]/gi, "").toLowerCase()] || value;
}

const terminalRemoteStatuses = new Set(["approved", "accepted", "fulfilled", "paid", "rejected", "cancelled", "canceled", "storno", "deleted", "archived", "seized"]);

function normalizedRemoteStatus(doc) {
  return String(doc.remote_status || "").replace(/[^a-z]/gi, "").toLowerCase();
}

function documentNeedsAttention(doc) {
  const remote = normalizedRemoteStatus(doc);
  if (["accepted", "rejected", "cancelled"].includes(doc.status)) return false;
  return !remote || !terminalRemoteStatuses.has(remote);
}

function documentCompletedSuccessfully(doc) {
  const remote = normalizedRemoteStatus(doc);
  return ["approved", "accepted", "fulfilled", "paid"].includes(remote) || (!remote && doc.status === "accepted");
}

function documentNeedsCorrection(doc) {
  const remote = normalizedRemoteStatus(doc);
  return doc.status === "error" || doc.status === "rejected" || ["mistake", "rejected"].includes(remote);
}

function documentMatchesStatusFilter(doc, filter) {
  if (!filter) return true;
  if (filter === "workflow:open") return documentNeedsAttention(doc);
  if (filter === "workflow:completed") return !documentNeedsAttention(doc);
  if (filter === "workflow:attention") return documentNeedsCorrection(doc);
  const remote = normalizedRemoteStatus(doc);
  return remote ? remote === filter : doc.status === filter;
}

function documentStatusName(doc) {
  if (doc.remote_status) return remoteStatusName(doc.remote_status);
  if (doc.document_type === "purchase_invoice" && doc.status === "sent") return "Primljena";
  if (doc.document_type === "sales_invoice" && doc.status === "sent") return "Poslata";
  return statusNames[doc.status] || doc.status;
}

function documentWorkflowStateName(doc) {
  if (doc.status === "error") return "Potrebna pažnja";
  if (documentNeedsAttention(doc)) return "U postupku";
  return "Završeno";
}

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

function validationMessage(item) {
  return String(item?.msg || "Neispravan unos").replace(/^Value error,\s*/i, "");
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
    const detail = Array.isArray(body.detail) ? body.detail.map(validationMessage).join("; ") : body.detail;
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
  const loaders = [loadDocuments(), loadDocumentTemplates(), loadCustomers(), loadCatalogItems(), loadJobs(), loadEvents(), loadMembers(), loadSessions(), loadIntegrations()];
  const results = await Promise.allSettled(loaders);
  const failed = results.find(result => result.status === "rejected");
  if (failed) showToast(failed.reason.message, true);
}

async function autoRefreshActiveView() {
  if (autoRefreshBusy || document.hidden || !sessionStorage.getItem(tokenKey) || !state.organization || document.querySelector("dialog[open]")) return;
  const view = $(".view.active")?.id.replace("view-", "") || "documents";
  const refreshers = {
    documents: [loadDocuments],
    customers: [loadCustomers],
    items: [loadCatalogItems],
    jobs: [loadJobs],
    events: [loadEvents],
    members: [loadMembers, loadSessions],
  }[view];
  if (!refreshers) return;
  autoRefreshBusy = true;
  try { await Promise.allSettled(refreshers.map(refresh => refresh())); } finally { autoRefreshBusy = false; }
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
  const [documents, counts] = await Promise.all([
    api("/api/v1/documents?limit=200"),
    api("/api/v1/documents/attention-counts"),
  ]);
  state.documents = documents;
  state.documentAttentionCounts = counts;
  renderDocuments();
}

async function loadDocumentTemplates() {
  state.documentTemplates = await api("/api/v1/document-templates");
  populateDocumentTemplateSelector();
}

function populateDocumentTemplateSelector(preferredId = "") {
  const select = $("#document-template-select");
  if (!select) return;
  const provider = $("#document-form").elements.provider.value;
  const templates = state.documentTemplates.filter(item => item.provider === provider);
  select.innerHTML = '<option value="">Bez šablona</option>' + templates.map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
  if (templates.some(item => item.id === preferredId)) select.value = preferredId;
  updateDocumentTemplateActions();
}

function updateDocumentTemplateActions() {
  const selected = Boolean($("#document-template-select")?.value);
  $("#apply-document-template").disabled = !selected;
  $("#update-document-template").hidden = !selected;
  $("#delete-document-template").hidden = !selected;
}

function renderDocuments() {
  const search = $("#document-search").value.trim().toLowerCase();
  const status = $("#status-filter").value;
  const scoped = state.documents.filter(doc => {
    if (state.documentScope === "inbound") return doc.provider === "sef" && doc.direction === "inbound" && doc.document_type === "purchase_invoice";
    if (state.documentScope === "outbound") return doc.provider === "sef" && doc.direction === "outbound" && doc.document_type === "sales_invoice";
    if (state.documentScope === "receipt") return doc.provider === "eotpremnice" && ((doc.document_type === "despatch_advice" && doc.direction === "inbound") || (doc.document_type === "receipt_advice" && doc.direction === "outbound"));
    return doc.provider === "eotpremnice" && ((doc.document_type === "despatch_advice" && doc.direction === "outbound") || (doc.document_type === "receipt_advice" && doc.direction === "inbound"));
  });
  const filtered = scoped.filter(doc => {
    const text = `${doc.document_number || ""} ${doc.counterparty_name || ""} ${doc.counterparty_tax_id || ""}`.toLowerCase();
    return (!search || text.includes(search)) && documentMatchesStatusFilter(doc, status);
  });
  const headings = {
    inbound: ["Primljene fakture", "Fakture dobavljača automatski preuzete sa SEF-a."],
    outbound: ["Poslate fakture", "Fakture kupcima kreirane i poslate kroz SEF."],
    receipt: ["Prijemnice", "Ulazni tok robe: primljene eOtpremnice i prijemnice koje šaljete kao odgovor."],
    despatch: ["Otpremnice", "Izlazni tok robe: poslate eOtpremnice i prijemnice koje primate od kupca."],
  };
  $("#documents-heading").textContent = headings[state.documentScope][0];
  $("#documents-description").textContent = headings[state.documentScope][1];
  $("#document-rows").innerHTML = filtered.map(doc => `<tr>
    <td><strong>${escapeHtml(doc.document_number || documentTypeNames[doc.document_type] || doc.document_type)}</strong><small>${escapeHtml(documentTypeNames[doc.document_type] || doc.document_type)} · ${doc.document_type === "purchase_invoice" ? "primljena" : doc.document_type === "sales_invoice" ? "poslata" : doc.direction === "outbound" ? "izlazna" : "ulazna"}</small></td>
    <td><strong>${escapeHtml(doc.counterparty_name || "—")}</strong><small>${escapeHtml(doc.counterparty_tax_id || "")}</small></td>
    <td>${formatDate(doc.issue_date || doc.created_at)}</td><td>${formatAmount(doc.total_amount, doc.currency)}</td>
    <td><span class="status ${doc.status}">${escapeHtml(documentStatusName(doc))}</span><small>${escapeHtml(documentWorkflowStateName(doc))}</small></td>
    <td><div class="row-actions"><button class="row-action" data-document-id="${doc.id}">Otvori</button><button class="row-action print-action" data-print-document-id="${doc.id}">Štampaj</button></div></td></tr>`).join("");
  $("#documents-empty").hidden = filtered.length > 0;
  $("#metric-total").textContent = scoped.length;
  $("#metric-active").textContent = scoped.filter(documentNeedsAttention).length;
  $("#metric-success").textContent = scoped.filter(documentCompletedSuccessfully).length;
  $("#metric-errors").textContent = scoped.filter(documentNeedsCorrection).length;
  $("#inbound-document-count").textContent = state.documentAttentionCounts.inbound || 0;
  $("#outbound-document-count").textContent = state.documentAttentionCounts.outbound || 0;
  $("#receipt-document-count").textContent = state.documentAttentionCounts.receipt || 0;
  $("#despatch-document-count").textContent = state.documentAttentionCounts.despatch || 0;
  $$("[data-document-scope]").forEach(item => item.classList.toggle("scope-active", item.dataset.documentScope === state.documentScope));
  $$("[data-document-id]").forEach(button => button.addEventListener("click", () => showDocument(button.dataset.documentId)));
  $$("[data-print-document-id]").forEach(button => button.addEventListener("click", () => showPrintPreview(button.dataset.printDocumentId)));
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

function xmlElement(node, localName) {
  return node ? [...node.getElementsByTagNameNS("*", localName)][0] || null : null;
}

function xmlText(node, localName) {
  return xmlElement(node, localName)?.textContent?.trim() || "";
}

function xmlParty(root, roleNames) {
  const wrapper = roleNames.map(name => xmlElement(root, name)).find(Boolean);
  if (!wrapper) return {name:"—", taxId:"", address:""};
  const name = xmlText(xmlElement(wrapper, "PartyLegalEntity"), "RegistrationName") || xmlText(xmlElement(wrapper, "PartyName"), "Name") || "—";
  let taxId = xmlText(wrapper, "EndpointID") || xmlText(xmlElement(wrapper, "PartyTaxScheme"), "CompanyID");
  if (/^RS\d+$/i.test(taxId)) taxId = taxId.slice(2);
  const addressNode = xmlElement(wrapper, "PostalAddress") || xmlElement(wrapper, "DeliveryAddress") || xmlElement(wrapper, "DespatchAddress");
  const address = [xmlText(addressNode, "StreetName"), xmlText(addressNode, "PostalZone"), xmlText(addressNode, "CityName")].filter(Boolean).join(", ");
  return {name, taxId, address};
}

function parseBusinessXml(xmlSource, doc) {
  const parsed = new DOMParser().parseFromString(xmlSource, "application/xml");
  if (parsed.getElementsByTagName("parsererror").length) throw new Error("XML dokument nije moguće prikazati");
  const root = ["Invoice", "DespatchAdvice", "ReceiptAdvice"].map(name => parsed.documentElement.localName === name ? parsed.documentElement : xmlElement(parsed, name)).find(Boolean);
  if (!root) throw new Error("Format dokumenta nije podržan za pregled");
  const invoice = root.localName === "Invoice";
  const issuer = xmlParty(root, invoice ? ["AccountingSupplierParty"] : ["DespatchSupplierParty", "DeliveryCustomerParty"]);
  const recipient = xmlParty(root, invoice ? ["AccountingCustomerParty"] : ["DeliveryCustomerParty", "DespatchSupplierParty"]);
  const lineName = invoice ? "InvoiceLine" : "DespatchLine";
  const lines = [...root.getElementsByTagNameNS("*", lineName)].map((line, index) => {
    const quantityNode = xmlElement(line, invoice ? "InvoicedQuantity" : "DeliveredQuantity");
    const quantity = quantityNode?.textContent?.trim() || "";
    return {
      number: xmlText(line, "ID") || String(index + 1),
      name: xmlText(xmlElement(line, "Item"), "Name") || "Stavka",
      description: xmlText(xmlElement(line, "Item"), "Description"),
      quantity,
      unit: quantityNode?.getAttribute("unitCode") || "",
      unitPrice: xmlText(xmlElement(line, "Price"), "PriceAmount"),
      netAmount: xmlText(line, "LineExtensionAmount"),
      vatRate: xmlText(xmlElement(line, "ClassifiedTaxCategory"), "Percent"),
      vatCategory: xmlText(xmlElement(line, "ClassifiedTaxCategory"), "ID"),
    };
  });
  return {
    number: xmlText(root, "ID") || doc.document_number || "—",
    issueDate: xmlText(root, "IssueDate") || doc.issue_date,
    dueDate: xmlText(root, "DueDate"),
    currency: xmlText(root, "DocumentCurrencyCode") || doc.currency || "RSD",
    issuer,
    recipient,
    lines,
    total: xmlText(xmlElement(root, "LegalMonetaryTotal"), "PayableAmount") || doc.total_amount,
    note: xmlText(root, "Note"),
    paymentAccount: xmlText(xmlElement(root, "PayeeFinancialAccount"), "ID"),
    paymentReference: xmlText(xmlElement(root, "PaymentMeans"), "PaymentID"),
  };
}

function previewFromStoredForm(doc) {
  const form = doc.payload?.form;
  if (!form) return null;
  const profile = state.organization?.profile || {};
  const customer = form.customer || {};
  return {
    number: form.document_number || doc.document_number || "—",
    issueDate: form.issue_date || doc.issue_date,
    dueDate: form.due_date || form.planned_delivery_at || "",
    currency: form.currency || doc.currency || "RSD",
    issuer: {name:state.organization?.name || "—", taxId:state.organization?.tax_id || "", address:[profile.street, profile.postal_code, profile.city].filter(Boolean).join(", ")},
    recipient: {name:customer.name || doc.counterparty_name || "—", taxId:customer.tax_id || doc.counterparty_tax_id || "", address:customer.address ? [customer.address.street, customer.address.postal_code, customer.address.city].filter(Boolean).join(", ") : ""},
    lines: (form.lines || []).map((line, index) => ({number:String(index + 1), name:line.name || "Stavka", description:line.description || "", quantity:line.quantity, unit:line.unit_code || "", unitPrice:line.unit_price, netAmount:Number(line.quantity || 0) * Number(line.unit_price || 0), vatRate:line.vat_rate, vatCategory:line.vat_category || "S"})),
    total: doc.total_amount,
    note: form.note || "",
    paymentAccount: form.payment_account || profile.bank_account || "",
    paymentReference: form.payment_reference || "",
  };
}

async function loadDocumentPreview(doc, artifacts) {
  const stored = previewFromStoredForm(doc);
  if (stored) return stored;
  const xmlArtifact = [...artifacts].reverse().find(file => ["application/xml", "text/xml"].includes(file.content_type));
  if (xmlArtifact) {
    try {
      const response = await api(`/api/v1/documents/${doc.id}/artifacts/${xmlArtifact.id}/download`);
      return parseBusinessXml(await response.text(), doc);
    } catch (error) { showToast(error.message, true); }
  }
  const organization = state.organization || {};
  const counterparty = {name:doc.counterparty_name || "—", taxId:doc.counterparty_tax_id || "", address:""};
  const own = {name:organization.name || "—", taxId:organization.tax_id || "", address:""};
  return {number:doc.document_number || "—",issueDate:doc.issue_date,currency:doc.currency || "RSD",issuer:doc.direction === "inbound" ? counterparty : own,recipient:doc.direction === "inbound" ? own : counterparty,lines:[],total:doc.total_amount,note:""};
}

function documentPreviewMarkup(preview) {
  const lines = preview.lines.length ? `<div class="preview-lines"><table><thead><tr><th>R.br.</th><th>Artikal / usluga</th><th>Količina</th><th>Cena</th><th>PDV</th><th>Iznos</th></tr></thead><tbody>${preview.lines.map(line => `<tr><td>${escapeHtml(line.number)}</td><td><strong>${escapeHtml(line.name)}</strong><small>${escapeHtml(line.description)}</small></td><td>${escapeHtml(line.quantity)} ${escapeHtml(unitNames[line.unit] || line.unit)}</td><td>${line.unitPrice === "" || line.unitPrice == null ? "—" : formatAmount(line.unitPrice, preview.currency)}</td><td>${line.vatRate === "" || line.vatRate == null ? "—" : `${escapeHtml(line.vatRate)}%`}</td><td>${line.netAmount === "" || line.netAmount == null ? "—" : formatAmount(line.netAmount, preview.currency)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">Dokument nema stavke dostupne za prikaz.</p>';
  return `<section class="document-preview"><div class="detail-grid"><div class="detail-item"><span>Datum dokumenta</span><strong>${formatDate(preview.issueDate)}</strong></div><div class="detail-item"><span>Datum dospeća / isporuke</span><strong>${formatDate(preview.dueDate)}</strong></div></div><div class="preview-parties"><div class="preview-party"><span>Izdavalac / pošiljalac</span><strong>${escapeHtml(preview.issuer.name)}</strong><small>PIB: ${escapeHtml(preview.issuer.taxId || "—")}</small><small>${escapeHtml(preview.issuer.address)}</small></div><div class="preview-party"><span>Primalac</span><strong>${escapeHtml(preview.recipient.name)}</strong><small>PIB: ${escapeHtml(preview.recipient.taxId || "—")}</small><small>${escapeHtml(preview.recipient.address)}</small></div></div><h3>Stavke dokumenta</h3>${lines}<div class="detail-grid"><div class="detail-item"><span>Ukupno za plaćanje</span><strong>${formatAmount(preview.total, preview.currency)}</strong></div><div class="detail-item"><span>Valuta</span><strong>${escapeHtml(preview.currency || "—")}</strong></div></div>${preview.note ? `<p class="preview-note"><strong>Napomena:</strong> ${escapeHtml(preview.note)}</p>` : ""}</section>`;
}

function printDocument(doc, preview, existingPopup = null) {
  const popup = existingPopup || window.open("", "_blank", "width=1000,height=760");
  if (!popup) { showToast("Pregledač je blokirao prozor za štampu.", true); return; }
  const invoice = doc.provider === "sef";
  const currency = preview.currency || "RSD";
  const numericLines = preview.lines.map(line => ({...line, net:Number(line.netAmount), rate:Number(line.vatRate)}));
  const subtotal = numericLines.reduce((sum, line) => sum + (Number.isFinite(line.net) ? line.net : 0), 0);
  const vatGroups = numericLines.reduce((groups, line) => {
    if (!Number.isFinite(line.net)) return groups;
    const rate = Number.isFinite(line.rate) ? line.rate : 0;
    const category = line.vatCategory || "S";
    const key = `${rate}:${category}`;
    groups[key] ||= {rate, category, base:0, vat:0};
    groups[key].base += line.net;
    groups[key].vat += line.net * rate / 100;
    return groups;
  }, {});
  const vatRows = Object.values(vatGroups).sort((left, right) => left.rate - right.rate);
  const vatTotal = vatRows.reduce((sum, group) => sum + group.vat, 0);
  const documentLabel = doc.document_type === "despatch_advice" ? "OTPREMNICA" : doc.document_type === "receipt_advice" ? "PRIJEMNICA" : doc.direction === "inbound" ? "ULAZNA FAKTURA" : "FAKTURA";
  const partyLabel = invoice ? "Izdavalac" : "Pošiljalac";
  const recipientLabel = invoice ? "Kupac / primalac" : "Primalac robe";
  const itemHeader = invoice
    ? '<th class="num">R.br.</th><th>Artikal / usluga</th><th class="right">Količina</th><th class="right">Jed. cena</th><th class="right">PDV</th><th class="right">Osnovica</th>'
    : '<th class="num">R.br.</th><th>Artikal / opis robe</th><th class="right">Količina</th><th>Jedinica mere</th>';
  const itemRows = preview.lines.map(line => `<tr><td class="num">${escapeHtml(line.number)}</td><td><strong>${escapeHtml(line.name)}</strong>${line.description ? `<span class="description">${escapeHtml(line.description)}</span>` : ""}</td><td class="right nowrap">${escapeHtml(line.quantity)}</td>${invoice ? `<td class="right nowrap">${line.unitPrice === "" || line.unitPrice == null ? "—" : formatAmount(line.unitPrice, currency)}</td><td class="right nowrap">${line.vatRate === "" || line.vatRate == null ? "—" : `${escapeHtml(line.vatRate)}%`}</td><td class="right nowrap"><strong>${line.netAmount === "" || line.netAmount == null ? "—" : formatAmount(line.netAmount, currency)}</strong></td>` : `<td>${escapeHtml(unitNames[line.unit] || line.unit || "—")}</td>`}</tr>`).join("");
  const vatSummary = vatRows.length ? `<table class="vat-table"><thead><tr><th>PDV stopa</th><th class="right">Osnovica</th><th class="right">PDV iznos</th></tr></thead><tbody>${vatRows.map(group => `<tr><td>${escapeHtml(vatNames[`${group.rate}:${group.category}`] || `${group.rate}%`)}</td><td class="right">${formatAmount(group.base, currency)}</td><td class="right">${formatAmount(group.vat, currency)}</td></tr>`).join("")}</tbody></table>` : "";
  const paymentBlock = preview.paymentAccount || preview.paymentReference ? `<section class="section payment"><h2>Podaci za plaćanje</h2><div class="payment-grid">${preview.paymentAccount ? `<div><span>Račun za uplatu</span><strong>${escapeHtml(preview.paymentAccount)}</strong></div>` : ""}${preview.paymentReference ? `<div><span>Poziv na broj</span><strong>${escapeHtml(preview.paymentReference)}</strong></div>` : ""}</div></section>` : "";
  popup.document.open();
  popup.document.write(`<!doctype html><html lang="sr-Latn"><head><meta charset="utf-8"><title>${escapeHtml(documentLabel)} ${escapeHtml(preview.number)}</title><link rel="stylesheet" href="${escapeHtml(location.origin)}/static/print.css?v=0.8.22"></head><body><div class="print-toolbar"><strong>Pregled štampe · ${escapeHtml(documentLabel)} ${escapeHtml(preview.number)}</strong><div class="print-actions"><button id="close-print" type="button">Zatvori</button><button class="primary" id="print-now" type="button">Štampaj dokument</button></div></div>
    <header class="document-header"><div class="brand"><p class="eyebrow">IZDAVALAC DOKUMENTA</p><strong>${escapeHtml(preview.issuer.name)}</strong><span class="muted">PIB: ${escapeHtml(preview.issuer.taxId || "—")}</span></div><div class="document-id"><h1>${escapeHtml(documentLabel)}</h1><span class="number">Broj: ${escapeHtml(preview.number)}</span><span class="status">${escapeHtml(documentStatusName(doc))}</span></div></header>
    <table class="meta-table"><tr><td><span>Datum izdavanja</span><strong>${formatDate(preview.issueDate)}</strong></td><td><span>${invoice ? "Datum dospeća" : "Datum isporuke"}</span><strong>${formatDate(preview.dueDate)}</strong></td><td><span>Valuta</span><strong>${escapeHtml(currency)}</strong></td><td><span>Servis</span><strong>${escapeHtml(doc.provider === "sef" ? "SEF" : "eOtpremnice")}</strong></td></tr></table>
    <section class="parties"><div class="party"><span>${partyLabel}</span><strong>${escapeHtml(preview.issuer.name)}</strong><small>PIB: ${escapeHtml(preview.issuer.taxId || "—")}</small><small>${escapeHtml(preview.issuer.address || "Adresa nije navedena")}</small></div><div class="party"><span>${recipientLabel}</span><strong>${escapeHtml(preview.recipient.name)}</strong><small>PIB: ${escapeHtml(preview.recipient.taxId || "—")}</small><small>${escapeHtml(preview.recipient.address || "Adresa nije navedena")}</small></div></section>
    <section class="section"><h2>Stavke dokumenta</h2>${preview.lines.length ? `<table class="items"><thead><tr>${itemHeader}</tr></thead><tbody>${itemRows}</tbody></table>` : '<p class="muted">Nema stavki dostupnih za prikaz.</p>'}</section>
    ${invoice ? `<section class="calculation"><div><h2>Pregled PDV-a</h2>${vatSummary || '<p class="muted">PDV obračun nije dostupan.</p>'}</div><div class="totals"><div class="totals-row"><span>Osnovica</span><span>${formatAmount(subtotal, currency)}</span></div><div class="totals-row"><span>PDV</span><span>${formatAmount(vatTotal, currency)}</span></div><div class="totals-row"><span>UKUPNO ZA PLAĆANJE</span><span>${formatAmount(preview.total, currency)}</span></div></div></section>${paymentBlock}` : ""}
    ${preview.note ? `<section class="section note"><h2>Napomena</h2><p>${escapeHtml(preview.note)}</p></section>` : ""}
    <footer class="footer"><span>Dokument pripremljen u aplikaciji eDokumenti · šablon 0.8.22</span><span>${escapeHtml(documentLabel)} · ${escapeHtml(preview.number)}</span></footer>
  </body></html>`);
  popup.document.close();
  popup.document.querySelector("#print-now").onclick = () => popup.print();
  popup.document.querySelector("#close-print").onclick = () => popup.close();
  popup.focus();
}

async function showPrintPreview(documentId) {
  const doc = state.documents.find(item => item.id === documentId);
  if (!doc) return;
  const popup = window.open("", "_blank", "width=1000,height=760");
  if (!popup) { showToast("Pregledač je blokirao prozor za štampu.", true); return; }
  popup.document.write('<!doctype html><html lang="sr-Latn"><head><meta charset="utf-8"><title>Priprema štampe</title></head><body><p>Pripremam pregled štampe…</p></body></html>');
  popup.document.close();
  let artifacts = [];
  try { artifacts = await api(`/api/v1/documents/${documentId}/artifacts`); } catch (error) { showToast(error.message, true); }
  try {
    const preview = await loadDocumentPreview(doc, artifacts);
    printDocument(doc, preview, popup);
  } catch (error) {
    popup.close();
    showToast(error.message, true);
  }
}

async function showDocument(documentId) {
  const doc = state.documents.find(item => item.id === documentId);
  if (!doc) return;
  const editable = canEdit() && doc.direction === "outbound" && ["draft", "error"].includes(doc.status) && !doc.external_id && doc.payload?.source === "business_form";
  const deletable = canEdit() && doc.direction === "outbound" && doc.status === "draft" && !doc.external_id;
  let artifacts = [];
  try { artifacts = await api(`/api/v1/documents/${documentId}/artifacts`); } catch (error) { showToast(error.message, true); }
  const preview = await loadDocumentPreview(doc, artifacts);
  const sortedArtifacts = [...artifacts].sort((left, right) => Number(["application/xml", "text/xml"].includes(left.content_type)) - Number(["application/xml", "text/xml"].includes(right.content_type)));
  $("#document-detail").innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">DETALJI DOKUMENTA</p><h2>${escapeHtml(doc.document_number || documentTypeNames[doc.document_type] || doc.document_type)}</h2></div><button class="icon-button" id="close-detail" aria-label="Zatvori">×</button></div>
    <span class="status ${doc.status}">${escapeHtml(documentStatusName(doc))}</span>
    <div class="detail-grid"><div class="detail-item"><span>Servis</span><strong>${doc.provider === "sef" ? "SEF" : "eOtpremnice"}</strong></div><div class="detail-item"><span>Status servisa</span><strong>${escapeHtml(remoteStatusName(doc.remote_status) || "—")}</strong></div></div>
    ${documentPreviewMarkup(preview)}
    ${doc.last_error ? `<p class="form-error">${escapeHtml(doc.last_error)}</p>` : ""}
    <section class="technical-files"><h3>Tehničke datoteke</h3><p class="muted small">XML je namenjen razmeni sa državnim servisom i nije potreban za svakodnevni pregled.</p><div class="artifact-list">${sortedArtifacts.length ? sortedArtifacts.map(file => `<div class="artifact"><div><strong>${["application/xml", "text/xml"].includes(file.content_type) ? "XML dokument" : file.content_type === "application/pdf" ? "PDF dokument" : escapeHtml(file.kind)}</strong><small>${Math.ceil(file.size_bytes / 1024)} KB · ${escapeHtml(file.sha256.slice(0, 12))}…</small></div><button class="secondary artifact-download" data-artifact-id="${file.id}">Preuzmi ${["application/xml", "text/xml"].includes(file.content_type) ? "XML" : "datoteku"}</button></div>`).join("") : '<p class="muted">Nema tehničkih datoteka.</p>'}</div></section>
    <div class="dialog-actions">${deletable ? '<button class="danger-button" id="delete-detail">Obriši nacrt</button>' : ""}<button class="secondary" id="close-detail-bottom">Zatvori</button>${editable ? '<button class="secondary" id="edit-detail">Izmeni</button>' : ""}${canEdit() && doc.direction === "outbound" && doc.status === "draft" ? `<button class="primary" id="queue-detail">${sendButtonLabel(doc.provider)}</button>` : ""}</div>`;
  const dialog = $("#detail-dialog"); dialog.showModal();
  $("#close-detail").onclick = () => dialog.close(); $("#close-detail-bottom").onclick = () => dialog.close();
  const queue = $("#queue-detail"); if (queue) queue.onclick = async () => { try { await api(`/api/v1/documents/${doc.id}/queue`, {method:"POST"}); dialog.close(); showToast(`Slanje u ${providerDestination(doc.provider)} je pokrenuto.`); await loadDocuments(); await loadJobs(); } catch (error) { showToast(error.message, true); } };
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
  $$(".nav-item[data-view]").forEach(item => item.classList.toggle("active", item.dataset.view === name && (name !== "documents" || item.dataset.documentScope === state.documentScope)));
  $(".sidebar").classList.remove("open");
}

function showDocumentScope(scope) {
  state.documentScope = scope;
  sessionStorage.setItem(documentScopeKey, scope);
  showView("documents");
  renderDocuments();
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
const despatchDateHint = document.createElement("p");
despatchDateHint.className = "muted small";
despatchDateHint.textContent = "Datum izdavanja je današnji datum Srbije. Polasci ne mogu biti ranije, a planirani prijem mora biti posle oba polaska.";
$("#despatch-fields .form-grid").before(despatchDateHint);

let documentLineSequence = 0;
let editingDocumentId = null;

function addDocumentLine(line = null) {
  documentLineSequence += 1;
  const row = document.createElement("div"); row.className = "document-line";
  const itemOptions = state.items.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(item.sku)}</option>`).join("");
  row.innerHTML = `<div class="line-heading"><strong>Stavka ${documentLineSequence}</strong><button type="button" class="icon-button remove-line" aria-label="Ukloni stavku">×</button></div><div class="form-grid"><label class="span-2">Izaberite artikal ili uslugu<select class="line-item-picker"><option value="">Ručni unos</option>${itemOptions}</select></label><label class="span-2">Naziv<input name="line_name" required maxlength="300"></label><label>Šifra artikla<input name="line_sku" maxlength="100"></label><label>GTIN<input name="line_gtin" maxlength="30"></label><label>Količina<input name="line_quantity" type="number" min="0.000001" step="0.000001" value="1" required></label><label>Jedinica mere<select name="line_unit" required><option value="H87">Komad</option><option value="KGM">Kilogram</option><option value="LTR">Litar</option><option value="MTR">Metar</option><option value="MTK">m²</option><option value="MTQ">m³</option><option value="HUR">Sat</option><option value="DAY">Dan</option><option value="XPK">Paket</option></select></label><label class="invoice-line-field">Cena bez PDV<input name="line_price" type="number" min="0" step="0.01" required></label><label class="invoice-line-field">PDV<select name="line_vat_choice"><option value="20:S">20%</option><option value="10:S">10%</option><option value="0:Z">0%</option><option value="0:O">Nije u PDV sistemu</option><option value="0:E">Oslobođeno PDV-a</option></select></label><label class="span-2">Opis <span class="optional">(opciono)</span><input name="line_description" maxlength="1000"></label></div>`;
  row.querySelector(".remove-line").onclick = () => { if ($$(".document-line").length > 1) { row.remove(); scheduleAutomaticDocumentDraft(); } };
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
  const form = $("#document-form"); const provider = form.elements.provider.value; const invoice = provider === "sef";
  const issueDate = form.elements.issue_date; const profile = state.organization?.profile || {};
  issueDate.readOnly = !invoice;
  issueDate.min = invoice ? "" : serbianCalendarDate(); issueDate.max = invoice ? "" : serbianCalendarDate();
  if (!invoice) issueDate.value = serbianCalendarDate();
  $("#queue-after-create-label").textContent = `${sendButtonLabel(provider)} odmah nakon kreiranja`;
  $("#invoice-fields").hidden = !invoice; $("#invoice-fields").disabled = !invoice;
  $("#despatch-fields").hidden = invoice; $("#despatch-fields").disabled = invoice;
  $$(".invoice-line-field").forEach(field => {
    field.hidden = !invoice;
    field.querySelectorAll("input,select").forEach(control => { control.disabled = !invoice; });
  });
  ["shipment_id", "planned_despatch_at", "actual_despatch_at", "planned_delivery_at", "despatch_street", "despatch_city", "despatch_postal_code", "despatch_country_code", "delivery_street", "delivery_city", "delivery_postal_code", "delivery_country_code"].forEach(name => { $("#document-form").elements[name].required = !invoice; });
  if (invoice && !form.elements.payment_account.value && profile.bank_account) form.elements.payment_account.value = profile.bank_account;
  if (!invoice) {
    const defaults = {despatch_street:profile.street,despatch_city:profile.city,despatch_postal_code:profile.postal_code,despatch_country_code:profile.country_code || "RS"};
    Object.entries(defaults).forEach(([name, value]) => { if (!form.elements[name].value && value) form.elements[name].value = value; });
  }
  ensureDespatchDateDefaults(); syncDespatchDateConstraints();
  toggleCarrierRequirements();
  populateDocumentTemplateSelector($("#document-template-select")?.value || "");
}

function toggleCarrierRequirements() {
  const form = $("#document-form");
  const isDespatch = form.elements.provider.value === "eotpremnice";
  const method = form.elements.shipment_method.value;
  const externalCarrier = isDespatch && method === "2";
  ["carrier_name", "carrier_tax_id", "carrier_registration_number"].forEach(name => {
    const control = form.elements[name];
    control.required = externalCarrier;
    control.disabled = isDespatch && !externalCarrier;
    control.closest("label").hidden = isDespatch && !externalCarrier;
  });
  const recipientCarrier = isDespatch && method === "3";
  form.elements.customer_registration_number.required = recipientCarrier;
  const help = $("#carrier-help");
  if (help) help.textContent = ({
    "1":"Prevoznik se automatski preuzima iz podataka vaše firme.",
    "2":"Unesite naziv, PIB i matični broj angažovanog prevoznika.",
    "3":"Prevoznik se automatski preuzima iz podataka primaoca. PIB i matični broj primaoca su obavezni.",
    "4":"Za lično preuzimanje podaci prevoznika nisu potrebni.",
    "5":"Za ličnu dostavu podaci prevoznika nisu potrebni."
  })[method] || "";
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

function documentDraftOwner() {
  try {
    const encoded = sessionStorage.getItem(tokenKey)?.split(".")[1] || "";
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=")));
    return payload.sub || "unknown";
  } catch { return "unknown"; }
}

function documentDraftKey(provider) {
  return `edokumenti_form_draft:${documentDraftOwner()}:${state.organization?.id || "none"}:${provider}`;
}

function daysBetween(first, second) {
  if (!first || !second) return null;
  const start = new Date(`${first}T00:00:00`); const end = new Date(`${second}T00:00:00`);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return null;
  return Math.max(0, Math.round((end - start) / 86400000));
}

function captureDocumentFormState({forTemplate = false} = {}) {
  const form = $("#document-form"); const values = {};
  const templateExcluded = new Set(["document_number", "issue_date", "delivery_date", "due_date", "shipment_id", "order_reference", "planned_despatch_at", "actual_despatch_at", "planned_delivery_at", "queue_after_create"]);
  form.querySelectorAll("[name]").forEach(control => {
    if (control.closest(".document-line") || ["BUTTON", "FIELDSET"].includes(control.tagName)) return;
    if (forTemplate && templateExcluded.has(control.name)) return;
    values[control.name] = control.type === "checkbox" ? control.checked : control.value;
  });
  const lines = $$(".document-line").map(row => Object.fromEntries(
    [...row.querySelectorAll("[name]")].map(control => [control.name, control.value])
  ));
  return {
    version: 1,
    provider: form.elements.provider.value,
    values,
    lines,
    customer_id: $("#document-customer-select").value || null,
    due_days: forTemplate ? daysBetween(form.elements.issue_date.value, form.elements.due_date.value) : null,
    delivery_days: forTemplate ? daysBetween(form.elements.issue_date.value, form.elements.delivery_date.value) : null,
  };
}

function addDays(dateValue, days) {
  const date = new Date(`${dateValue}T12:00:00`);
  date.setDate(date.getDate() + Number(days || 0));
  return date.toISOString().slice(0, 10);
}

function applyDocumentFormState(snapshot, {fromTemplate = false} = {}) {
  if (!snapshot?.values) return false;
  const form = $("#document-form"); suspendDocumentAutosave = true;
  try {
    form.elements.provider.value = snapshot.provider || form.elements.provider.value;
    toggleDocumentType();
    Object.entries(snapshot.values).forEach(([name, value]) => {
      const control = form.elements[name]; if (!control) return;
      if (control.type === "checkbox") control.checked = Boolean(value);
      else control.value = value ?? "";
    });
    if (fromTemplate) {
      const today = serbianCalendarDate();
      form.elements.issue_date.value = today;
      if (form.elements.provider.value === "sef") {
        form.elements.delivery_date.value = addDays(today, snapshot.delivery_days);
        form.elements.due_date.value = addDays(today, snapshot.due_days ?? 15);
      } else {
        ensureDespatchDateDefaults();
      }
    }
    documentLineSequence = 0; $("#document-lines").innerHTML = "";
    (snapshot.lines || []).forEach(line => {
      addDocumentLine(); const row = $$(".document-line").at(-1);
      Object.entries(line).forEach(([name, value]) => {
        const control = row.querySelector(`[name=${name}]`); if (control) control.value = value ?? "";
      });
    });
    if (!snapshot.lines?.length) addDocumentLine();
    $("#document-customer-select").value = snapshot.customer_id || "";
    toggleDocumentType(); syncDespatchDateConstraints();
    return true;
  } finally { suspendDocumentAutosave = false; }
}

function saveAutomaticDocumentDraft() {
  if (suspendDocumentAutosave || editingDocumentId || !$("#document-dialog").open) return;
  const snapshot = captureDocumentFormState();
  localStorage.setItem(documentDraftKey(snapshot.provider), JSON.stringify(snapshot));
  $("#document-autosave-status").textContent = `Automatski nacrt sačuvan u ${new Intl.DateTimeFormat("sr-Latn-RS", {hour:"2-digit",minute:"2-digit"}).format(new Date())}.`;
}

function scheduleAutomaticDocumentDraft() {
  clearTimeout(documentDraftTimer);
  documentDraftTimer = setTimeout(saveAutomaticDocumentDraft, 500);
}

function restoreAutomaticDocumentDraft(provider) {
  try {
    const snapshot = JSON.parse(localStorage.getItem(documentDraftKey(provider)) || "null");
    if (!snapshot || !applyDocumentFormState(snapshot)) return false;
    $("#document-autosave-status").textContent = "Vraćen je poslednji automatski nacrt.";
    return true;
  } catch {
    localStorage.removeItem(documentDraftKey(provider));
    return false;
  }
}

function clearAutomaticDocumentDraft(provider) {
  localStorage.removeItem(documentDraftKey(provider));
}

function selectedDocumentTemplate() {
  const id = $("#document-template-select").value;
  return state.documentTemplates.find(item => item.id === id);
}

function documentTemplatePayload(name) {
  const provider = $("#document-form").elements.provider.value;
  return {
    name,
    provider,
    document_type: provider === "sef" ? "sales_invoice" : "despatch_advice",
    template_data: captureDocumentFormState({forTemplate:true}),
  };
}

async function saveNewDocumentTemplate() {
  const name = prompt("Naziv novog šablona:", "");
  if (!name?.trim()) return;
  try {
    const created = await api("/api/v1/document-templates", {method:"POST", body:JSON.stringify(documentTemplatePayload(name.trim()))});
    await loadDocumentTemplates(); populateDocumentTemplateSelector(created.id);
    showToast("Šablon je sačuvan i dostupan korisnicima firme.");
  } catch (error) { showToast(error.message, true); }
}

async function updateSelectedDocumentTemplate() {
  const template = selectedDocumentTemplate(); if (!template) return;
  try {
    await api(`/api/v1/document-templates/${template.id}`, {method:"PUT", body:JSON.stringify(documentTemplatePayload(template.name))});
    await loadDocumentTemplates(); populateDocumentTemplateSelector(template.id);
    showToast("Šablon je ažuriran trenutnim unosom.");
  } catch (error) { showToast(error.message, true); }
}

async function deleteSelectedDocumentTemplate() {
  const template = selectedDocumentTemplate(); if (!template || !confirm(`Obrisati šablon „${template.name}“?`)) return;
  try {
    await api(`/api/v1/document-templates/${template.id}`, {method:"DELETE"});
    await loadDocumentTemplates();
    showToast("Šablon je obrisan.");
  } catch (error) { showToast(error.message, true); }
}

function resetDocumentForm() {
  const form = $("#document-form"); suspendDocumentAutosave = true; form.reset(); editingDocumentId = null; documentLineSequence = 0; $("#document-lines").innerHTML = ""; addDocumentLine();
  $("#document-dialog-eyebrow").textContent = "NOVI POSLOVNI DOKUMENT"; $("#document-dialog-title").textContent = "Unos bez XML-a"; $("#document-submit-button").textContent = "Generiši dokument";
  const today = new Date().toISOString().slice(0, 10); form.elements.issue_date.value = today; form.elements.delivery_date.value = today;
  const due = new Date(); due.setDate(due.getDate() + 15); form.elements.due_date.value = due.toISOString().slice(0, 10); $("#document-template-select").value = ""; $("#document-autosave-status").textContent = "Automatski nacrt je uključen."; toggleDocumentType(); suspendDocumentAutosave = false;
}

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value); if (Number.isNaN(date.valueOf())) return String(value).slice(0, 16);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function serbianCalendarDate() {
  const parts = new Intl.DateTimeFormat("en-US", {timeZone:"Europe/Belgrade", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function serbianDateTimeValue(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {timeZone:"Europe/Belgrade", year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"}).formatToParts(date);
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}`;
}

function ensureDespatchDateDefaults() {
  const form = $("#document-form"); if (form.elements.provider.value !== "eotpremnice") return;
  const issueDate = serbianCalendarDate(); const now = serbianDateTimeValue();
  const planned = form.elements.planned_despatch_at; const actual = form.elements.actual_despatch_at; const delivery = form.elements.planned_delivery_at;
  if (!planned.value || planned.value.slice(0, 10) < issueDate) planned.value = now;
  if (!actual.value || actual.value.slice(0, 10) < issueDate) actual.value = now;
  const earliestDelivery = [planned.value, actual.value, `${issueDate}T00:00`].sort().at(-1);
  if (!delivery.value || delivery.value < earliestDelivery) delivery.value = serbianDateTimeValue(new Date(Date.now() + 60 * 60 * 1000));
  if (delivery.value < earliestDelivery) delivery.value = earliestDelivery;
}

function syncDespatchDateConstraints() {
  const form = $("#document-form"); const issueDate = form.elements.issue_date.value;
  const minimum = issueDate ? `${issueDate}T00:00` : "";
  const planned = form.elements.planned_despatch_at; const actual = form.elements.actual_despatch_at; const delivery = form.elements.planned_delivery_at;
  planned.min = minimum; actual.min = minimum;
  delivery.min = [minimum, planned.value, actual.value].filter(Boolean).sort().at(-1) || "";
  planned.setCustomValidity(planned.value && planned.value < minimum ? "Planirani polazak ne može biti pre datuma izdavanja." : "");
  actual.setCustomValidity(actual.value && actual.value < minimum ? "Stvarni polazak ne može biti pre datuma izdavanja." : "");
  delivery.setCustomValidity(delivery.value && delivery.value < delivery.min ? "Planirani prijem mora biti posle planiranog i stvarnog polaska." : "");
}

function openDocumentEditor(doc) {
  const data = doc.payload?.form; if (!data) return;
  resetDocumentForm(); editingDocumentId = doc.id;
  $("#document-dialog-eyebrow").textContent = doc.status === "error" ? "ISPRAVKA NEUSPEŠNOG DOKUMENTA" : "IZMENA NACRTA";
  $("#document-dialog-title").textContent = doc.document_number || "Izmena dokumenta"; $("#document-submit-button").textContent = "Sačuvaj izmene";
  const form = $("#document-form");
  ["provider", "document_number", "issue_date", "note"].forEach(name => { form.elements[name].value = data[name] || ""; });
  if (data.provider === "eotpremnice") form.elements.issue_date.value = serbianCalendarDate();
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
  form.elements.queue_after_create.checked = false; toggleDocumentType(); syncDespatchDateConstraints(); $("#document-error").textContent = ""; $("#detail-dialog").close(); $("#document-dialog").showModal();
}

$("#document-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form)); const provider = data.provider;
  const customer = {name:data.customer_name, tax_id:data.customer_tax_id, registration_number:data.customer_registration_number || null, email:data.customer_email || null, jbkjs:data.customer_jbkjs || null, address:{street:data.customer_street, city:data.customer_city, postal_code:data.customer_postal_code, country_code:data.customer_country_code.toUpperCase()}};
  const payload = {provider, document_number:data.document_number, issue_date:data.issue_date, note:data.note || null, customer, lines:documentLines(provider), queue_after_create:Boolean(data.queue_after_create)};
  if (provider === "sef") Object.assign(payload, {delivery_date:data.delivery_date, due_date:data.due_date, currency:data.currency, payment_account:data.payment_account || null, payment_reference:data.payment_reference || null});
  else Object.assign(payload, {despatch_type:data.despatch_type, shipment_id:data.shipment_id, shipment_method:data.shipment_method, order_reference:data.order_reference || null, planned_despatch_at:new Date(data.planned_despatch_at).toISOString(), actual_despatch_at:new Date(data.actual_despatch_at).toISOString(), planned_delivery_at:new Date(data.planned_delivery_at).toISOString(), despatch_address:{street:data.despatch_street, city:data.despatch_city, postal_code:data.despatch_postal_code, country_code:data.despatch_country_code.toUpperCase()}, delivery_address:{street:data.delivery_street, city:data.delivery_city, postal_code:data.delivery_postal_code, country_code:data.delivery_country_code.toUpperCase()}, gross_weight:data.gross_weight ? Number(data.gross_weight) : null, package_count:data.package_count ? Number(data.package_count) : null, carrier_name:data.carrier_name || null, carrier_tax_id:data.carrier_tax_id || null, carrier_registration_number:data.carrier_registration_number || null, vehicle_plate:data.vehicle_plate || null, driver_name:data.driver_name || null, driver_email:data.driver_email || null});
  const path = editingDocumentId ? `/api/v1/documents/${editingDocumentId}/from-form` : "/api/v1/documents/from-form";
  try {
    await api(path, {method:editingDocumentId ? "PUT" : "POST", body:JSON.stringify(payload)});
    clearAutomaticDocumentDraft(provider);
    $("#document-dialog").close();
    showToast(editingDocumentId ? "Izmene su sačuvane i XML je ponovo generisan." : (data.queue_after_create ? `Dokument je pripremljen i slanje u ${providerDestination(provider)} je pokrenuto.` : "Dokument i UBL XML su sačuvani."));
    editingDocumentId = null;
    state.documentScope = provider === "eotpremnice" ? "despatch" : "outbound";
    sessionStorage.setItem(documentScopeKey, state.documentScope);
    $("#document-search").value = ""; $("#status-filter").value = "";
    showView("documents");
    await loadDocuments(); await loadJobs();
  } catch (error) { $("#document-error").textContent = error.message; }
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
$("#document-form [name=shipment_method]").addEventListener("change", toggleCarrierRequirements);
$("#document-form [name=issue_date]").addEventListener("change", syncDespatchDateConstraints);
$("#document-form [name=planned_despatch_at]").addEventListener("input", syncDespatchDateConstraints);
$("#document-form [name=actual_despatch_at]").addEventListener("input", syncDespatchDateConstraints);
$("#document-form [name=planned_delivery_at]").addEventListener("input", syncDespatchDateConstraints);
$("#document-form").addEventListener("input", scheduleAutomaticDocumentDraft);
$("#document-form").addEventListener("change", scheduleAutomaticDocumentDraft);
$("#document-template-select").addEventListener("change", updateDocumentTemplateActions);
$("#apply-document-template").onclick = () => {
  const template = selectedDocumentTemplate(); if (!template) return;
  applyDocumentFormState(template.template_data, {fromTemplate:true});
  $("#document-template-select").value = template.id; updateDocumentTemplateActions();
  scheduleAutomaticDocumentDraft(); showToast(`Primenjen je šablon „${template.name}“.`);
};
$("#save-document-template").onclick = saveNewDocumentTemplate;
$("#update-document-template").onclick = updateSelectedDocumentTemplate;
$("#delete-document-template").onclick = deleteSelectedDocumentTemplate;
$("#clear-document-draft").onclick = () => {
  const provider = $("#document-form").elements.provider.value;
  clearAutomaticDocumentDraft(provider); resetDocumentForm();
  $("#document-form").elements.provider.value = provider; toggleDocumentType();
  $("#document-autosave-status").textContent = "Unos je očišćen. Automatski nacrt je uključen.";
};
$("#document-customer-select").addEventListener("change", event => fillCustomer(state.customers.find(customer => customer.id === event.target.value)));
$("#add-document-line").onclick = () => { addDocumentLine(); scheduleAutomaticDocumentDraft(); };
$("#new-customer-button").onclick = () => openCustomerDialog();
$("#document-new-customer").onclick = () => openCustomerDialog();
$("#new-item-button").onclick = () => openItemDialog();
$("#new-document-button").onclick = () => {
  const requiredProfile = ["street", "city", "postal_code", "country_code", "email"];
  const validTaxId = /^\d{9}$/.test(state.organization?.tax_id || "");
  if (!validTaxId || requiredProfile.some(field => !state.organization?.profile?.[field])) { showView("settings"); showToast("Prvo unesite važeće pravne i poslovne podatke izabrane firme.", true); return; }
  $("#document-error").textContent = ""; resetDocumentForm();
  const provider = ["receipt", "despatch"].includes(state.documentScope) ? "eotpremnice" : "sef";
  $("#document-form").elements.provider.value = provider;
  toggleDocumentType();
  const restored = restoreAutomaticDocumentDraft(provider);
  $("#document-dialog").showModal();
  if (restored) showToast("Vraćen je nezavršeni automatski nacrt.");
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
$$('.close-dialog').forEach(button => button.onclick = () => { if (button.closest("dialog")?.id === "document-dialog") saveAutomaticDocumentDraft(); button.closest("dialog").close(); });
$$('.nav-item[data-view]').forEach(button => button.onclick = () => button.dataset.documentScope ? showDocumentScope(button.dataset.documentScope) : showView(button.dataset.view));
[$("#document-search"), $("#status-filter")].forEach(control => control.addEventListener("input", renderDocuments));
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
setInterval(autoRefreshActiveView, autoRefreshIntervalMs);
document.addEventListener("visibilitychange", () => { if (!document.hidden) autoRefreshActiveView(); });
if (sessionStorage.getItem(tokenKey)) initializeApp();

let parkingLots = [];

const loginScreen = document.getElementById("login-screen");
const appShell = document.getElementById("app-shell");
const loginMessage = document.getElementById("login-message");
const loginTitle = document.getElementById("login-title");
const loginIntro = document.querySelector(".login-intro");
const loginForm = document.getElementById("login-form");
const customerRegister = document.getElementById("customer-register");
const customerRecovery = document.getElementById("customer-recovery");
const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const parkingList = document.getElementById("parking-list");
const parkingSearch = document.getElementById("parking-search");
const selectedTitle = document.getElementById("selected-title");
const selectedStatus = document.getElementById("selected-status");
const selectedDetails = document.getElementById("selected-details");
const mapStatus = document.getElementById("map-status");
const reservationForm = document.getElementById("reservation-form");
const reservationStart = document.getElementById("reservation-start");
const reservationEnd = document.getElementById("reservation-end");
const reservationEstimate = document.getElementById("reservation-estimate");
const reservationMessage = document.getElementById("reservation-message");
const reservationList = document.getElementById("reservation-list");
const reserveButton = document.getElementById("reserve-button");
const continueToReservation = document.getElementById("continue-to-reservation");
const reservationParkingName = document.getElementById("reservation-parking-name");
const reservationParkingAddress = document.getElementById("reservation-parking-address");
const reservationParkingStatus = document.getElementById("reservation-parking-status");
const dashboardTitle = document.querySelector(".topbar h1");

let selectedParkingId = null;
let currentUser = null;
let reservations = [];
const markers = {};

function formatCurrency(value) {
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL"
  });
}

function formatDateTime(value) {
  return new Date(value).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  });
}

function toLocalDateTimeValue(date) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function setDefaultReservationTimes() {
  const start = new Date();
  start.setSeconds(0, 0);
  start.setMinutes(Math.ceil((start.getMinutes() + 1) / 15) * 15);

  const end = new Date(start.getTime() + 60 * 60 * 1000);
  reservationStart.value = toLocalDateTimeValue(start);
  reservationEnd.value = toLocalDateTimeValue(end);
}

function renderSummary() {
  const total = parkingLots.reduce((sum, lot) => sum + lot.totalSpaces, 0);
  const occupied = parkingLots.reduce((sum, lot) => sum + lot.occupiedSpaces, 0);
  const available = parkingLots.reduce((sum, lot) => sum + lot.availableSpaces, 0);

  document.getElementById("total-lots").textContent = parkingLots.length;
  document.getElementById("available-spaces").textContent = available;
  document.getElementById("occupied-spaces").textContent = occupied;
}

async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers
      }
    });
  } catch {
    throw new Error(
      "Não foi possível conectar ao backend. Inicie o servidor SmartPark e tente novamente."
    );
  }

  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`O backend retornou uma resposta inválida (HTTP ${response.status}).`);
  }

  if (!response.ok) {
    const error = new Error(result.message || `A solicitação falhou (HTTP ${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return result;
}

async function loadParkingLots() {
  const result = await apiRequest("/api/parking-lots");
  if (!Array.isArray(result.parking_lots)) {
    throw new Error("O backend retornou uma lista de estacionamentos inválida.");
  }

  parkingLots = result.parking_lots.map((lot) => {
    if (
      typeof lot.id !== "string"
      || typeof lot.name !== "string"
      || typeof lot.address !== "string"
      || !Number.isFinite(lot.latitude)
      || !Number.isFinite(lot.longitude)
      || !Number.isFinite(lot.hourly_rate)
      || !Number.isInteger(lot.total_spaces)
      || !Number.isInteger(lot.available_spaces)
      || !Array.isArray(lot.spaces)
    ) {
      throw new Error("O backend retornou dados inválidos de estacionamento.");
    }

    return {
      id: lot.id,
      name: lot.name,
      address: lot.address,
      latitude: lot.latitude,
      longitude: lot.longitude,
      hourlyRate: lot.hourly_rate,
      totalSpaces: lot.total_spaces,
      availableSpaces: lot.available_spaces,
      occupiedSpaces: lot.occupied_spaces,
      openingHours: lot.opening_hours,
      spaces: lot.spaces.map((space) => ({
        label: space.label,
        occupied: space.status === "OCCUPIED",
        status: space.status
      }))
    };
  });

  Object.values(markers).forEach((marker) => map.removeLayer(marker));
  Object.keys(markers).forEach((id) => delete markers[id]);

  parkingLots.forEach((parking) => {
    const marker = L.marker([parking.latitude, parking.longitude]).addTo(map);
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    const address = document.createElement("p");
    const availability = document.createElement("p");
    const price = document.createElement("p");

    title.textContent = parking.name;
    address.textContent = parking.address;
    availability.textContent = `${parking.availableSpaces} vagas livres`;
    price.textContent = `${formatCurrency(parking.hourlyRate)}/hora`;
    popup.append(title, address, availability, price);
    marker.bindPopup(popup, { autoPanPadding: [24, 64] });
    marker.on("click", () => selectParking(parking.id));
    markers[parking.id] = marker;
  });

  if (parkingLots.length > 0) {
    map.invalidateSize();
    map.fitBounds(
      L.latLngBounds(parkingLots.map((parking) => [parking.latitude, parking.longitude])),
      { padding: [40, 40], maxZoom: 14 }
    );
  }

  renderSummary();
  renderParkingList();
}

function renderParkingList() {
  parkingList.replaceChildren();
  const query = parkingSearch.value.trim().toLocaleLowerCase("pt-BR");
  let visibleLots = 0;

  parkingLots.forEach((parking) => {
    const matches = `${parking.name} ${parking.address}`
      .toLocaleLowerCase("pt-BR")
      .includes(query);
    const marker = markers[parking.id];

    if (marker) {
      if (matches && !map.hasLayer(marker)) marker.addTo(map);
      if (!matches && map.hasLayer(marker)) map.removeLayer(marker);
    }

    if (!matches) return;
    visibleLots += 1;

    const card = document.createElement("button");
    const title = document.createElement("h3");
    const address = document.createElement("p");
    const meta = document.createElement("div");
    const price = document.createElement("span");
    const availability = document.createElement("span");

    card.type = "button";
    card.className = `parking-card ${
      selectedParkingId === parking.id ? "selected" : ""
    }`;
    card.setAttribute("aria-pressed", String(selectedParkingId === parking.id));
    title.textContent = parking.name;
    address.textContent = parking.address;
    meta.className = "parking-meta";
    price.className = "parking-price";
    price.textContent = `${formatCurrency(parking.hourlyRate)}/hora`;
    availability.className = "spaces-free";
    availability.textContent = `${parking.availableSpaces} vagas livres`;
    meta.append(price, availability);
    card.append(title, address, meta);

    card.addEventListener("click", () => selectParking(parking.id, true));
    parkingList.appendChild(card);
  });

  if (visibleLots === 0) {
    const emptyMessage = document.createElement("p");
    emptyMessage.className = "empty-state";
    emptyMessage.textContent = parkingLots.length === 0
      ? "Nenhum estacionamento ativo foi encontrado."
      : "Nenhum estacionamento encontrado para essa busca.";
    parkingList.appendChild(emptyMessage);
  }
}

function renderParkingDetails(parking) {
  const available = parking.availableSpaces;

  selectedTitle.textContent = parking.name;
  selectedStatus.textContent = available > 0 ? "Disponível" : "Lotado";
  selectedStatus.classList.toggle("unavailable", available === 0);
  reservationParkingName.textContent = parking.name;
  reservationParkingAddress.textContent = parking.address;
  reservationParkingStatus.textContent = available > 0
    ? `${available} vagas disponíveis`
    : "Estacionamento lotado";
  reservationParkingStatus.classList.toggle("unavailable", available === 0);
  continueToReservation.disabled = available === 0;
  reservationStart.disabled = available === 0;
  reservationEnd.disabled = available === 0;
  reserveButton.disabled = available === 0;

  const detailGrid = document.createElement("div");
  detailGrid.className = "detail-grid";

  [
    ["Tarifa por hora", formatCurrency(parking.hourlyRate)],
    ["Vagas disponíveis", `${available} de ${parking.totalSpaces}`],
    ["Funcionamento", parking.openingHours]
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    const caption = document.createElement("span");
    const detail = document.createElement("strong");

    item.className = "detail-item";
    caption.textContent = label;
    detail.textContent = value;
    item.append(caption, detail);
    detailGrid.appendChild(item);
  });

  const spaceList = document.createElement("div");
  spaceList.className = "space-list";

  parking.spaces.forEach((space) => {
    const chip = document.createElement("span");
    const unavailable = ["OCCUPIED", "RESERVED", "MAINTENANCE"].includes(space.status);
    chip.className = `space-chip ${unavailable ? "occupied" : ""}`;
    const status = {
      OCCUPIED: "Ocupada",
      RESERVED: "Reservada",
      MAINTENANCE: "Manutenção",
      FREE: "Livre"
    }[space.status] || "Indisponível";
    chip.textContent = `${space.label} · ${status}`;
    spaceList.appendChild(chip);
  });

  selectedDetails.replaceChildren(detailGrid, spaceList);
  reservationMessage.textContent = "";
  updateEstimate();
}

function selectParking(id, focusMap = false) {
  const parking = parkingLots.find((lot) => lot.id === id);
  if (!parking) return;

  selectedParkingId = id;
  renderParkingList();
  renderParkingDetails(parking);

  const marker = markers[id];
  if (marker) {
    if (focusMap) {
      map.once("moveend", () => marker.openPopup());
      map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 14), {
        duration: 0.5
      });
      return;
    }

    marker.openPopup();
  }
}

function showDashboardView(viewName) {
  const views = [...document.querySelectorAll("[data-view]")];
  if (!views.some((view) => view.dataset.view === viewName)) return;

  views.forEach((view) => {
    view.hidden = view.dataset.view !== viewName;
  });
  document.querySelectorAll("[data-view-link]").forEach((link) => {
    const active = link.dataset.viewLink === viewName;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });

  const headings = {
    "visao-geral": "Visão geral",
    encontrar: "Encontrar vaga",
    reservar: "Pré-reservar",
    reservas: "Minhas reservas",
    administracao: "Administração"
  };
  dashboardTitle.textContent = headings[viewName];
  if (window.location.hash !== `#${viewName}`) {
    window.history.replaceState(null, "", `#${viewName}`);
  }
  if (viewName === "encontrar") {
    requestAnimationFrame(() => map.invalidateSize());
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll("[data-view-link]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    showDashboardView(link.dataset.viewLink);
  });
});

continueToReservation.addEventListener("click", () => {
  if (selectedParkingId) showDashboardView("reservar");
});

function getSelectedParking() {
  return parkingLots.find((parking) => parking.id === selectedParkingId) || null;
}

function getReservationPeriod() {
  const start = new Date(reservationStart.value);
  const end = new Date(reservationEnd.value);

  if (!reservationStart.value || !reservationEnd.value
      || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return null;
  }

  return { start, end };
}

let estimateTimer = null;

function updateEstimate() {
  const parking = getSelectedParking();
  const period = getReservationPeriod();

  if (!parking) {
    reservationEstimate.textContent = "Estimativa: selecione um estacionamento.";
    return;
  }

  if (!period || period.end <= period.start) {
    reservationEstimate.textContent = "Informe um horário de saída posterior à entrada.";
    return;
  }

  // O valor vem do servidor: o navegador não é fonte confiável do preço.
  reservationEstimate.textContent = "Calculando estimativa...";
  clearTimeout(estimateTimer);
  estimateTimer = setTimeout(async () => {
    try {
      const query = new URLSearchParams({
        arrival: period.start.toISOString(),
        departure: period.end.toISOString()
      });
      const data = await apiRequest(
        `/api/parking-lots/${encodeURIComponent(parking.id)}/availability?${query}`
      );
      reservationEstimate.textContent =
        `Estimativa: ${data.hours} h · ${formatCurrency(data.estimated_price)} · ${data.available_spaces} vaga(s) livre(s) no período`;
    } catch (error) {
      reservationEstimate.textContent = error.message;
    }
  }, 400);
}

async function loadReservations() {
  const result = await apiRequest("/api/reservations");
  if (!Array.isArray(result.reservations)) {
    throw new Error("O backend retornou um histórico de reservas inválido.");
  }
  reservations = result.reservations;
  renderReservations();
}

async function startCheckout(reservationId, button) {
  button.disabled = true;
  button.textContent = "Abrindo o Mercado Pago...";
  try {
    const result = await apiRequest(
      `/api/reservations/${encodeURIComponent(reservationId)}/checkout`,
      { method: "POST" }
    );
    const target = new URL(result.init_point);
    if (target.protocol !== "https:" || !target.hostname.endsWith("mercadopago.com.br")
        && !target.hostname.endsWith("mercadopago.com")) {
      throw new Error("O servidor devolveu um endereço de pagamento inesperado.");
    }
    window.location.assign(target.href);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Pagar com Mercado Pago";
    document.getElementById("dashboard-message").hidden = false;
    document.getElementById("dashboard-message").textContent = error.message;
  }
}

async function cancelReservation(reservationId, button) {
  button.disabled = true;
  button.textContent = "Cancelando...";
  try {
    await apiRequest(`/api/reservations/${encodeURIComponent(reservationId)}/cancel`, {
      method: "POST"
    });
    await Promise.all([loadReservations(), loadParkingLots()]);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Cancelar reserva pendente";
    document.getElementById("reservation-message").textContent = error.message;
  }
}

function renderReservations() {
  reservationList.replaceChildren();
  const visibleReservations = reservations;

  if (visibleReservations.length === 0) {
    reservationList.classList.add("empty-state");
    const message = document.createElement("p");
    const link = document.createElement("button");

    message.textContent = currentUser?.role === "admin"
      ? "Ainda não há reservas cadastradas."
      : "Você ainda não possui reservas.";
    link.className = "text-button";
    link.type = "button";
    link.textContent = "Encontrar uma vaga";
    link.addEventListener("click", () => showDashboardView("encontrar"));
    reservationList.append(message, link);
    renderAdminSummary();
    return;
  }

  reservationList.classList.remove("empty-state");

  visibleReservations.forEach((reservation) => {
    const card = document.createElement("article");
    const heading = document.createElement("div");
    const title = document.createElement("h3");
    const status = document.createElement("span");
    const details = document.createElement("p");
    const estimate = document.createElement("strong");
    const cancelButton = document.createElement("button");
    const payButton = document.createElement("button");

    card.className = "reservation-card";
    heading.className = "reservation-card-heading";
    title.textContent = reservation.parking_lot_name || "Estacionamento indisponível";
    status.className = "reservation-status";
    const reservationStatuses = {
      PENDING_PAYMENT: "Aguardando pagamento",
      CONFIRMED: "Confirmada",
      CHECKED_IN: "Em andamento",
      COMPLETED: "Concluída",
      EXPIRED: "Expirada",
      CANCELLED: "Cancelada"
    };
    status.textContent = reservationStatuses[reservation.status] || "Status indisponível";
    details.textContent =
      `${reservation.code || reservation.id} · ${formatDateTime(reservation.arrival_expected)} – ${formatDateTime(reservation.departure_expected)}`;
    estimate.className = "reservation-estimate";
    estimate.textContent = `Estimativa: ${formatCurrency(reservation.estimated_price)}`;
    cancelButton.className = "text-button";
    cancelButton.type = "button";
    cancelButton.textContent = "Cancelar reserva pendente";
    cancelButton.hidden = reservation.status !== "PENDING_PAYMENT";
    cancelButton.setAttribute("aria-label", `Cancelar reserva ${reservation.code || reservation.id}`);
    cancelButton.addEventListener("click", () => {
      cancelReservation(reservation.id, cancelButton);
    });

    payButton.className = "primary-button";
    payButton.type = "button";
    payButton.textContent = "Pagar com Mercado Pago";
    payButton.addEventListener("click", () => startCheckout(reservation.id, payButton));

    heading.append(title, status);
    card.append(heading, details, estimate);
    if (reservation.status === "PENDING_PAYMENT") {
      card.append(payButton, cancelButton);
    }
    reservationList.appendChild(card);
  });

  renderAdminSummary();
}

let adminLoadedAt = 0;

function renderAdminSummary() {
  const adminSummary = document.getElementById("admin-summary");
  if (currentUser?.role !== "admin" || !adminSummary) return;

  adminSummary.replaceChildren();
  [
    ["Estacionamentos cadastrados", String(parkingLots.length)],
    ["Vagas totais", String(parkingLots.reduce((sum, lot) => sum + lot.totalSpaces, 0))],
    ["Reservas registradas", String(reservations.length)]
  ].forEach(([label, value]) => {
    const item = document.createElement("article");
    const caption = document.createElement("p");
    const detail = document.createElement("strong");

    item.className = "stat-card admin-stat";
    caption.textContent = label;
    detail.textContent = value;
    item.append(caption, detail);
    adminSummary.appendChild(item);
  });
  if (Date.now() - adminLoadedAt > 10000) {
    adminLoadedAt = Date.now();
    loadAdminOverview();
  }
}

function adminTable(headers, rows) {
  const table = document.createElement("table");
  table.className = "admin-table";
  const head = table.createTHead().insertRow();
  headers.forEach((text) => { const th = document.createElement("th"); th.textContent = text; head.appendChild(th); });
  const body = table.createTBody();
  rows.forEach((cells) => {
    const row = body.insertRow();
    cells.forEach((text) => { row.insertCell().textContent = text ?? "-"; });
  });
  return table;
}

async function loadAdminOverview() {
  const box = document.getElementById("admin-details");
  if (!box) return;
  try {
    const data = await apiRequest("/api/admin/overview");
    const sections = [];
    const add = (heading, node) => {
      const h = document.createElement("h3");
      h.textContent = heading;
      sections.push(h, node);
    };
    add("Ocupação por estacionamento", adminTable(
      ["Local", "Vagas", "Ocupadas", "Reservadas", "Manutenção"],
      data.parking_lots.map((lot) => [lot.name, lot.total, lot.occupied, lot.reserved, lot.maintenance])));
    add("Últimas reservas", adminTable(
      ["Código", "Local", "Status", "Valor"],
      data.reservations.map((r) => [r.code, r.parking_lot_name, r.status, formatCurrency(r.estimated_price)])));
    const alerts = document.createElement("ul");
    alerts.className = "admin-alerts";
    (data.alerts.length ? data.alerts : [{ type: "OK", message: "Nenhum alerta no momento." }]).forEach((alert) => {
      const li = document.createElement("li");
      li.textContent = `${alert.type}: ${alert.message}`;
      alerts.appendChild(li);
    });
    add("Alertas", alerts);
    box.replaceChildren(...sections);
  } catch (error) {
    box.textContent = error.message;
  }
}

async function enterDashboard(user) {
  currentUser = user;
  loginScreen.hidden = true;
  appShell.hidden = false;
  document.getElementById("user-name").textContent = user.name;
  document.getElementById("user-role").textContent =
    user.role === "admin" ? "Administrador" : "Cliente";
  document.getElementById("user-avatar").textContent = user.name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toLocaleUpperCase("pt-BR");

  const isAdmin = user.role === "admin";
  document.querySelector(".admin-nav-link").hidden = !isAdmin;
  document.querySelector('[data-view-link="reservar"]').hidden = isAdmin;
  document.getElementById("administracao").hidden = !isAdmin;
  continueToReservation.hidden = isAdmin;
  setDefaultReservationTimes();
  showDashboardView("visao-geral");
  document.title = "SmartPark IoT | Visão geral";
  const dashboardMessage = document.getElementById("dashboard-message");
  dashboardMessage.hidden = true;
  try {
    await Promise.all([loadParkingLots(), loadReservations()]);
  } catch (error) {
    dashboardMessage.textContent = error.message;
    dashboardMessage.hidden = false;
  }
  renderAdminSummary();
}

async function restoreSession() {
  try {
    const user = await apiRequest("/api/auth/me");
    await enterDashboard(user);
  } catch (error) {
    if (error.status !== 401) showLoginMessage(error.message);
  }
}

function showLoginMessage(message) {
  loginMessage.textContent = message;
}

function showAuthView(viewName) {
  const views = {
    login: loginForm,
    register: customerRegister,
    recover: customerRecovery
  };
  if (!views[viewName]) return;

  Object.entries(views).forEach(([name, form]) => {
    form.hidden = name !== viewName;
  });

  const copy = {
    login: ["Bem-vindo ao SmartPark", "Entre ou crie sua conta para continuar."],
    register: ["Crie sua conta", "Cadastre-se para consultar estacionamentos e vagas."],
    recover: ["Recuperar senha", "Solicite instruções para redefinir sua senha."]
  };
  [loginTitle.textContent, loginIntro.textContent] = copy[viewName];
  document.getElementById("login-notice").textContent =
    "Clientes e administradores usam o mesmo formulário; o perfil é identificado pelo servidor.";
  showLoginMessage("");
}

document.querySelectorAll("[data-auth-view]").forEach((button) => {
  button.addEventListener("click", () => showAuthView(button.dataset.authView));
});

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  showLoginMessage("");
  apiRequest("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({
      email: loginEmail.value.trim(),
      password: loginPassword.value
    })
  }).then((user) => {
    loginPassword.value = "";
    return enterDashboard(user);
  }).catch((error) => {
    loginPassword.value = "";
    showLoginMessage(error.message);
  });
});

customerRegister.addEventListener("submit", (event) => {
  event.preventDefault();
  const name = document.getElementById("register-name").value.trim();
  const email = document.getElementById("register-email").value.trim().toLocaleLowerCase("pt-BR");
  const password = document.getElementById("register-password").value;
  const passwordConfirm = document.getElementById("register-password-confirm").value;

  if (name.length < 2) {
    showLoginMessage("Informe seu nome completo.");
    return;
  }

  if (password.length < 8) {
    showLoginMessage("A senha precisa ter pelo menos 8 caracteres.");
    return;
  }

  if (password !== passwordConfirm) {
    showLoginMessage("As senhas não conferem.");
    return;
  }

  showLoginMessage("");
  apiRequest("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password })
  }).then((user) => {
    document.getElementById("register-password").value = "";
    document.getElementById("register-password-confirm").value = "";
    return enterDashboard(user);
  }).catch((error) => {
    document.getElementById("register-password").value = "";
    document.getElementById("register-password-confirm").value = "";
    showLoginMessage(error.message);
  });
});

customerRecovery.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("recovery-email").value.trim();
  try {
    await apiRequest("/api/auth/password-reset", {
      method: "POST",
      body: JSON.stringify({ email })
    });
    showLoginMessage("Se a conta existir, serão enviadas instruções para redefinir a senha.");
  } catch (error) {
    showLoginMessage(error.message);
  }
});

document.getElementById("logout-button").addEventListener("click", async () => {
  let logoutError = "";
  try {
    await apiRequest("/api/auth/logout", { method: "POST" });
  } catch (error) {
    logoutError = error.message;
  }
  currentUser = null;
  reservations = [];
  selectedParkingId = null;
  parkingSearch.value = "";
  reservationForm.reset();
  reservationStart.disabled = true;
  reservationEnd.disabled = true;
  reserveButton.disabled = true;
  selectedTitle.textContent = "Selecione um estacionamento";
  selectedStatus.textContent = "Aguardando seleção";
  selectedStatus.classList.remove("unavailable");
  reservationParkingName.textContent = "Nenhum estacionamento selecionado";
  reservationParkingAddress.textContent =
    "Volte a “Encontrar vaga” para escolher um estacionamento.";
  reservationParkingStatus.textContent = "Selecione um local";
  reservationParkingStatus.classList.remove("unavailable");
  continueToReservation.disabled = true;
  selectedDetails.className = "empty-state";
  selectedDetails.textContent =
    "Escolha um estacionamento no mapa ou na lista para consultar vagas e tarifa.";
  document.querySelector('[data-view-link="reservar"]').hidden = false;
  document.querySelector(".admin-nav-link").hidden = true;
  document.getElementById("administracao").hidden = true;
  continueToReservation.hidden = false;
  reservationEstimate.textContent = "Estimativa: selecione um estacionamento.";
  map.closePopup();
  loginScreen.hidden = false;
  appShell.hidden = true;
  document.getElementById("dashboard-message").hidden = true;
  loginForm.reset();
  customerRegister.reset();
  customerRecovery.reset();
  showAuthView("login");
  if (logoutError) showLoginMessage(logoutError);
  document.title = "SmartPark IoT | Acesso";
});

parkingSearch.addEventListener("input", renderParkingList);
reservationStart.addEventListener("input", updateEstimate);
reservationEnd.addEventListener("input", updateEstimate);

reservationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  reservationMessage.textContent = "";

  const parking = getSelectedParking();
  const period = getReservationPeriod();

  if (!currentUser || currentUser.role !== "customer") {
    reservationMessage.textContent = "Entre como cliente para registrar uma pré-reserva.";
    return;
  }

  if (!parking || !period) {
    reservationMessage.textContent = "Selecione um estacionamento e informe os horários.";
    return;
  }

  if (period.end <= period.start) {
    reservationMessage.textContent = "O horário de saída precisa ser posterior à entrada.";
    return;
  }

  if (parking.availableSpaces <= 0) {
    reservationMessage.textContent = "Este estacionamento está lotado.";
    return;
  }

  reserveButton.disabled = true;
  reserveButton.textContent = "Validando disponibilidade...";
  try {
    const result = await apiRequest("/api/reservations", {
      method: "POST",
      body: JSON.stringify({
        parking_lot_id: parking.id,
        arrival_expected: period.start.toISOString(),
        departure_expected: period.end.toISOString()
      })
    });
    if (!result.reservation || result.reservation.status !== "PENDING_PAYMENT") {
      throw new Error("O backend não confirmou a criação da reserva pendente.");
    }

    await Promise.all([loadReservations(), loadParkingLots()]);
    reservationMessage.textContent =
      `Reserva ${result.reservation.code} criada. Clique em “Pagar com Mercado Pago” para confirmar; a vaga só é garantida após o pagamento aprovado.`;
    showDashboardView("reservas");
  } catch (error) {
    reservationMessage.textContent = error.message;
    reserveButton.disabled = parking.availableSpaces <= 0;
  } finally {
    reserveButton.textContent = "Registrar pré-reserva";
  }
});

// O mapa é inicializado no carregamento e redimensionado quando o painel aparece.
const map = L.map("map").setView([-12.247, -38.957], 13);

const tileLayer = L.tileLayer("https://tile.openstreetmap.de/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
});

let mapTilesLoaded = false;

tileLayer.on("tileload", () => {
  mapTilesLoaded = true;
  mapStatus.textContent = "Mapa carregado.";
});

tileLayer.on("tileerror", () => {
  if (!mapTilesLoaded) {
    mapStatus.textContent =
      "Não foi possível carregar o mapa. Verifique sua conexão com a internet.";
  }
});
tileLayer.addTo(map);

renderSummary();
setDefaultReservationTimes();
showAuthView("login");
restoreSession();

// Páginas de retorno do Mercado Pago. O retorno do navegador NÃO prova pagamento:
// aqui apenas pedimos ao backend que consulte o Mercado Pago e mostramos o status real.
(function () {
  const result = document.currentScript.dataset.result;
  const reservationId = new URLSearchParams(window.location.search).get("reserva");
  const title = document.getElementById("payment-title");
  const text = document.getElementById("payment-text");
  const status = document.getElementById("payment-status");

  async function call(path, method) {
    const response = await fetch(path, { method, credentials: "same-origin" });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) throw new Error("Sua sessão não foi encontrada. Abra o SmartPark pelo mesmo endereço público e entre novamente.");
    if (!response.ok) throw new Error(body.message || "Não foi possível consultar a reserva.");
    return body;
  }

  function show(state) {
    if (state === "CONFIRMED" || state === "CHECKED_IN" || state === "COMPLETED") {
      title.textContent = "Reserva confirmada";
      text.textContent = "Pagamento aprovado e verificado pelo servidor. A cancela liberará a entrada no horário da reserva.";
      return true;
    }
    if (state === "EXPIRED" || state === "CANCELLED") {
      title.textContent = "Reserva encerrada";
      text.textContent = "A reserva expirou ou foi cancelada. Crie uma nova pré-reserva.";
      return true;
    }
    return false;
  }

  async function run() {
    if (!reservationId) { status.textContent = "Reserva não informada."; return; }
    for (let attempt = 0; attempt < 12; attempt += 1) {
      try {
        const sync = await call(`/api/reservations/${encodeURIComponent(reservationId)}/sync-payment`, "POST");
        status.textContent = "Status da reserva: " + sync.status;
        if (show(sync.status) || result === "falha") return;
      } catch (error) { status.textContent = error.message; return; }
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    status.textContent = "Ainda aguardando o Mercado Pago. Volte a Minhas reservas em instantes.";
  }
  run();
})();

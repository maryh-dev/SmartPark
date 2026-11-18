"""
Telegram - SmartPark IoT.

Funções públicas (cada uma devolve "SENT", "FAILED" ou "PENDING_RETRY"):
    send_reservation_confirmation(reservation)   chamada pelo webhook do Mercado Pago
    send_operational_alert(alert_key, message)   dispositivo sem comunicação, falha repetida...
    send_final_ticket(ticket)                    chamada quando a saída gera o ticket
    retry_pending()                              reenvia o que ficou em PENDING_RETRY

Cada envio vira um documento em `notifications` (id fixo, criado com create()) => sem duplicação.
Teste isolado (sem Firestore):  python telegram_service.py
O código NUNCA registra exceções de rede: a URL da API contém o token.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

BRT = timezone(timedelta(hours=-3))
MAX_ATTEMPTS = 3


def _fmt(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.astimezone(BRT).strftime("%d/%m/%Y %H:%M")
    return "-" if value is None else str(value)


def _money(value):
    return f"R$ {float(value or 0):.2f}".replace(".", ",")


def _db():
    try:
        from firebase_admin import firestore
        return firestore.client()
    except Exception:  # sem app Firebase inicializado (teste isolado)
        return None


def _post(chat_id, text):
    """Devolve ('ok'|'retry'|'fail', espera_em_segundos)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return "fail", 0
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": chat_id, "text": text}, timeout=10)  # texto puro
    except requests.RequestException:
        return "retry", 2
    if resp.status_code == 200:
        return "ok", 0
    if resp.status_code == 429:
        try:
            return "retry", int(resp.json()["parameters"]["retry_after"])
        except (KeyError, ValueError, TypeError):
            return "retry", 5
    if resp.status_code >= 500:
        return "retry", 2
    return "fail", 0  # 400/401/403: erro definitivo, não insiste


def _attempt(ref, data):
    chat_id = data.get("chat_id") or os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
    attempts = int(data.get("attempts", 0))
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        outcome, wait = _post(chat_id, data["message"])
        if outcome == "ok":
            status = "SENT"
            break
        if outcome == "fail":
            status = "FAILED"
            break
        status = "PENDING_RETRY"
        if attempts < MAX_ATTEMPTS:
            time.sleep(min(wait or 2 * attempts, 30))
    update = {"status": status, "attempts": attempts, "updated_at": datetime.now(timezone.utc)}
    if status == "SENT":
        update["sent_at"] = update["updated_at"]
    if ref is not None:
        ref.update(update)
    return status


def _deliver(notification_id, kind, text, reservation_id=None):
    chat_id = os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
    data = {"channel": "telegram", "type": kind, "reservation_id": reservation_id,
            "message": text, "status": "PENDING_RETRY", "attempts": 0,
            "created_at": datetime.now(timezone.utc)}
    db = _db()
    if db is None:
        return _attempt(None, {**data, "chat_id": chat_id})
    from google.api_core.exceptions import AlreadyExists
    ref = db.collection("notifications").document(notification_id)
    try:
        ref.create(data)  # falha se já existir => idempotência
    except AlreadyExists:
        existing = ref.get().to_dict() or {}
        if existing.get("status") != "PENDING_RETRY":
            return existing.get("status", "SENT")  # já enviada: não duplica
        data = existing
    return _attempt(ref, {**data, "chat_id": chat_id})


def send_reservation_confirmation(reservation):
    text = (f"SMARTPARK IoT - RESERVA CONFIRMADA\n"
            f"Reserva: {reservation.get('code')}\n"
            f"Estacionamento: {reservation.get('parking_lot_name')}\n"
            f"Período: {_fmt(reservation.get('arrival_expected'))} até {_fmt(reservation.get('departure_expected'))}\n"
            f"Valor: {_money(reservation.get('estimated_price'))}\n"
            f"Pagamento: aprovado")
    return _deliver(f"reservation:{reservation.get('code')}", "RESERVATION_CONFIRMED", text,
                    reservation.get("id"))


def send_operational_alert(alert_key, message):
    """alert_key deve incluir o contexto, ex.: 'device-offline:esp32_01:2026-11-18T10'."""
    return _deliver(f"alert:{alert_key}", "OPERATIONAL_ALERT", f"SMARTPARK IoT - ALERTA\n{message}")


def send_final_ticket(ticket):
    minutes = int(ticket.get("duration_minutes") or 0)
    text = (f"SMARTPARK IoT - COMPROVANTE\n"
            f"Ticket: {ticket.get('code')}\n"
            f"Estacionamento: {ticket.get('parking_lot_name')}\n"
            f"Vaga: {ticket.get('space_code') or '-'}\n"
            f"Chegada real: {_fmt(ticket.get('entry_at'))}\n"
            f"Saída real: {_fmt(ticket.get('exit_at'))}\n"
            f"Duração: {minutes // 60}h{minutes % 60:02d}min\n"
            f"Valor final: {_money(ticket.get('total_amount'))}\n"
            f"Pagamento: {ticket.get('payment_status', 'aprovado')}")
    return _deliver(f"ticket:{ticket.get('code')}", "FINAL_TICKET", text, ticket.get("reservation_id"))


def retry_pending():
    db = _db()
    if db is None:
        return 0
    sent = 0
    for snap in db.collection("notifications").where("status", "==", "PENDING_RETRY").stream():
        data = snap.to_dict() or {}
        data["attempts"] = 0  # nova rodada de tentativas
        if _attempt(snap.reference, data) == "SENT":
            sent += 1
    return sent


if __name__ == "__main__":
    outcome, _ = _post(os.getenv("TELEGRAM_DEFAULT_CHAT_ID"), "SmartPark IoT: mensagem de teste.")
    print({"ok": "Mensagem enviada.", "fail": "Falhou: confira token, chat_id e se enviou /start ao bot.",
           "retry": "Erro temporário: tente de novo."}[outcome])

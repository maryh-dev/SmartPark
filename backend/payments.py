"""
Pagamento com Mercado Pago (Checkout Pro) - SmartPark IoT.

Rotas registradas:
    POST /api/reservations/<id>/checkout      cria a preferência e devolve init_point
    POST /api/reservations/<id>/sync-payment  consulta o MP e aplica o resultado (apoio ao retorno do navegador)
    POST /webhooks/mercadopago                notificação do MP (valida assinatura + consulta a API)

Regras do roteiro respeitadas:
  * o preço vem sempre do Firestore, nunca do navegador;
  * a reserva só vira CONFIRMED depois que o BACKEND consulta o pagamento na API do MP;
  * eventos duplicados / fora de ordem / pagamento após expiração são tratados.

Variáveis (.env, nunca no Git): MERCADOPAGO_ACCESS_TOKEN, MERCADOPAGO_WEBHOOK_SECRET, APP_BASE_URL.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import requests
from firebase_admin import firestore
from flask import jsonify, request

MP_API = "https://api.mercadopago.com"
BRT = timezone(timedelta(hours=-3))
FINAL_STATUS = {"approved", "refunded", "charged_back"}
PENDING_LIKE = {"pending", "in_process", "authorized", "in_mediation"}


def register_payments(app, get_db, require_user, APIError, notify_confirmation):
    def mp_headers():
        return {"Authorization": f"Bearer {os.getenv('MERCADOPAGO_ACCESS_TOKEN', '')}"}

    def base_url():
        return os.getenv("APP_BASE_URL", "").rstrip("/")

    def owned_reservation(reservation_id, user):
        ref = get_db().collection("reservations").document(reservation_id)
        snap = ref.get()
        data = snap.to_dict() if snap.exists else None
        if not data or (user.get("role") != "admin" and data.get("user_id") != user["id"]):
            raise APIError("Reserva não encontrada.", 404)
        return ref, data

    # ------------------------------------------------------------------ transação
    @firestore.transactional
    def apply_payment(tx, res_ref, pay_ref, pay):
        """Idempotente. Devolve a reserva se ela foi confirmada AGORA, senão None."""
        res_snap = res_ref.get(transaction=tx)  # leituras antes das escritas
        pay_snap = pay_ref.get(transaction=tx)
        status = pay.get("status")
        old = pay_snap.to_dict() if pay_snap.exists else {}

        # evento fora de ordem: um "pending" atrasado não desfaz um "approved"
        if old.get("status") in FINAL_STATUS and status in PENDING_LIKE:
            return None

        now = datetime.now(timezone.utc)
        data = {
            "reservation_id": res_ref.id,
            "provider": "mercadopago",
            "mp_payment_id": str(pay["id"]),
            "payment_id": str(pay["id"]),
            "external_reference": res_ref.id,
            "status": status,
            "amount": float(pay.get("transaction_amount") or 0),
            "currency": pay.get("currency_id") or "BRL",
            "updated_at": now,
        }
        if not pay_snap.exists:
            data["created_at"] = now

        confirmed = None
        if status == "approved":
            data["verified_at"] = now
            if not res_snap.exists:
                data.update(needs_review=True, note="Reserva não encontrada")
            else:
                r = res_snap.to_dict()
                if abs(data["amount"] - float(r.get("estimated_price", 0))) > 0.01:
                    data.update(needs_review=True, note="Valor pago diferente do esperado")
                elif r.get("status") == "PENDING_PAYMENT":
                    try:
                        paid_at = datetime.fromisoformat(pay["date_approved"])
                    except (KeyError, TypeError, ValueError):
                        paid_at = now
                    expires_at = r.get("expires_at")
                    if expires_at and paid_at > expires_at:
                        data.update(refund_needed=True, note="Pagamento após a expiração")
                    else:
                        tx.update(res_ref, {"status": "CONFIRMED", "payment_id": data["mp_payment_id"],
                                            "updated_at": now})
                        confirmed = {**r, "id": res_ref.id, "status": "CONFIRMED"}
                elif r.get("status") in ("EXPIRED", "CANCELLED"):
                    data.update(refund_needed=True, note="Pagamento após a expiração/cancelamento")
                # CONFIRMED / CHECKED_IN / COMPLETED: evento duplicado, nada a fazer
        tx.set(pay_ref, data, merge=True)
        return confirmed

    def process_payment(pay):
        reservation_id = pay.get("external_reference")
        if not reservation_id:
            return None
        db = get_db()
        res_ref = db.collection("reservations").document(reservation_id)
        pay_ref = db.collection("payments").document(f"mp_{pay['id']}")
        confirmed = apply_payment(db.transaction(), res_ref, pay_ref, pay)
        if confirmed:  # notifica só na primeira confirmação
            notify_confirmation(confirmed)
        return confirmed

    # ------------------------------------------------------------------ checkout
    @app.post("/api/reservations/<reservation_id>/checkout")
    def checkout(reservation_id):
        user = require_user({"customer", "admin"})
        ref, r = owned_reservation(reservation_id, user)
        if r.get("status") != "PENDING_PAYMENT":
            raise APIError("A reserva não está aguardando pagamento.", 409)
        now = datetime.now(timezone.utc)
        expires_at = r.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= now:
            raise APIError("A reserva expirou. Crie uma nova.", 409)
        if not os.getenv("MERCADOPAGO_ACCESS_TOKEN"):
            raise APIError("Pagamento não configurado no servidor.", 503)

        base = base_url()
        body = {
            "items": [{
                "id": reservation_id,
                "title": f"Reserva {r.get('code')} - {r.get('parking_lot_name')}",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(r["estimated_price"]),  # SEMPRE do banco
            }],
            "external_reference": reservation_id,
            "statement_descriptor": "SMARTPARK",
            "back_urls": {
                "success": f"{base}/pagamento-sucesso.html?reserva={reservation_id}",
                "pending": f"{base}/pagamento-pendente.html?reserva={reservation_id}",
                "failure": f"{base}/pagamento-falha.html?reserva={reservation_id}",
            },
        }
        if base.startswith("https://"):  # MP exige HTTPS para auto_return e webhook
            body["auto_return"] = "approved"
            body["notification_url"] = f"{base}/webhooks/mercadopago"
        if isinstance(expires_at, datetime):
            body["expires"] = True
            body["expiration_date_from"] = now.astimezone(BRT).strftime("%Y-%m-%dT%H:%M:%S.000-03:00")
            body["expiration_date_to"] = expires_at.astimezone(BRT).strftime("%Y-%m-%dT%H:%M:%S.000-03:00")

        try:
            resp = requests.post(f"{MP_API}/checkout/preferences", json=body,
                                 headers=mp_headers(), timeout=15)
        except requests.RequestException as error:
            raise APIError("Falha ao falar com o Mercado Pago.", 502) from error
        if resp.status_code not in (200, 201):
            app.logger.error("Mercado Pago preferência: HTTP %s %s", resp.status_code, resp.text[:300])
            raise APIError("O Mercado Pago recusou a preferência de pagamento.", 502)
        pref = resp.json()
        ref.update({"preference_id": pref["id"], "updated_at": now})
        return jsonify({"preference_id": pref["id"], "init_point": pref["init_point"]})

    # ------------------------------------------------------------------ sync (retorno do navegador)
    @app.post("/api/reservations/<reservation_id>/sync-payment")
    def sync_payment(reservation_id):
        """O navegador NÃO prova pagamento: aqui o backend pergunta ao MP e aplica o resultado."""
        user = require_user({"customer", "admin"})
        ref, _ = owned_reservation(reservation_id, user)
        try:
            resp = requests.get(f"{MP_API}/v1/payments/search", headers=mp_headers(), timeout=15,
                                params={"external_reference": reservation_id,
                                        "sort": "date_created", "criteria": "asc"})
        except requests.RequestException as error:
            raise APIError("Falha ao consultar o Mercado Pago.", 502) from error
        if resp.status_code != 200:
            raise APIError("Não foi possível consultar o pagamento agora.", 502)
        for pay in resp.json().get("results", []):
            process_payment(pay)
        status = ref.get().to_dict().get("status")
        return jsonify({"status": status})

    # ------------------------------------------------------------------ webhook
    def valid_signature(secret):
        header = request.headers.get("x-signature", "")
        parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
        ts, received = parts.get("ts"), parts.get("v1")
        if not ts or not received:
            return False
        manifest = ""
        data_id = request.args.get("data.id")
        request_id = request.headers.get("x-request-id")
        if data_id:
            manifest += f"id:{data_id.lower()};"
        if request_id:
            manifest += f"request-id:{request_id};"
        manifest += f"ts:{ts};"
        expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)

    @app.post("/webhooks/mercadopago")
    def mercadopago_webhook():
        secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET")
        if not secret:
            return jsonify({"message": "Webhook não configurado."}), 500
        if not valid_signature(secret):
            return jsonify({"message": "Assinatura inválida."}), 401

        body = request.get_json(silent=True) or {}
        if (request.args.get("type") or body.get("type")) != "payment":
            return "", 200
        payment_id = request.args.get("data.id") or (body.get("data") or {}).get("id")
        if not payment_id:
            return "", 200

        # nunca confia no corpo do webhook: consulta o pagamento na API
        try:
            resp = requests.get(f"{MP_API}/v1/payments/{payment_id}", headers=mp_headers(), timeout=15)
        except requests.RequestException:
            return jsonify({"message": "Falha ao consultar pagamento."}), 500  # MP tenta de novo
        if resp.status_code == 404:
            return "", 200
        if resp.status_code != 200:
            return jsonify({"message": "Falha ao consultar pagamento."}), 500
        process_payment(resp.json())
        return "", 200

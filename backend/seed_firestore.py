"""
Seed do Firestore - SmartPark IoT.

Uso:
    pip install firebase-admin python-dotenv
    # .env (NUNCA no Git):
    # GOOGLE_APPLICATION_CREDENTIALS=caminho/para/service-account.json
    python seed_firestore.py

IDs fixos: rodar de novo sobrescreve os mesmos documentos (sem duplicar).

Coleções (snake_case, datas em Timestamp do Firestore, fuso America/Bahia):

parking_lots/{lot_id}
    name, address, latitude, longitude, hourly_rate, opening_hours,
    total_spaces, active, created_at

spaces/{space_id}
    parking_lot_id, code, status (FREE | RESERVED | OCCUPIED | MAINTENANCE), active

reservations/{reservation_id}
    code, user_id, parking_lot_id, parking_lot_name, space_id,
    arrival_expected, departure_expected, hours_reserved, hourly_rate,
    estimated_price, status (PENDING_PAYMENT | CONFIRMED | CHECKED_IN |
    COMPLETED | EXPIRED | CANCELLED), expires_at (só PENDING_PAYMENT),
    checked_in_at, checked_out_at, created_at, updated_at

payments/{payment_id}
    reservation_id, mp_payment_id, external_reference, status, amount,
    created_at, updated_at   (só o backend escreve)

access_events/{event_id}          <- event_id vem do ESP32 (idempotência)
    device_id, parking_lot_id, direction (ENTRY | EXIT), reservation_id,
    result (GRANTED | DENIED), reason, created_at

tickets/{reservation_id}          <- ID = reserva: só pode existir um (RF08)
    code, reservation_id, entry_at, exit_at, total_amount, created_at

devices/{device_id}
    parking_lot_id, name, status (ONLINE | OFFLINE | MAINTENANCE), last_seen
    (o segredo DEVICE_SHARED_SECRET fica no .env, nunca aqui)

notifications/{tipo:chave}        <- ex.: ticket:SP-000123 (criado com create())
    type, status (SENT | FAILED | PENDING_RETRY), attempts, created_at
"""
from datetime import datetime, timedelta, timezone

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

cred = credentials.ApplicationDefault()  # lê GOOGLE_APPLICATION_CREDENTIALS
firebase_admin.initialize_app(cred)
db = firestore.client()

TZ = timezone(timedelta(hours=-3))
now = datetime.now(TZ)

LOTS = [
    {
        "id": "lot_pelourinho",
        "name": "SmartPark Pelourinho",
        "address": "Largo do Pelourinho, Salvador - BA (fictício)",
        "latitude": -12.9714,
        "longitude": -38.5108,
        "hourly_rate": 8.00,
        "opening_hours": "06:00 às 22:00",
        "spaces": 6,
        "device": "esp32_pelourinho_01",
    },
    {
        "id": "lot_barra",
        "name": "SmartPark Farol da Barra",
        "address": "Av. Oceânica, Barra, Salvador - BA (fictício)",
        "latitude": -13.0105,
        "longitude": -38.5330,
        "hourly_rate": 12.00,
        "opening_hours": "08:00 às 23:00",
        "spaces": 4,
        "device": "esp32_barra_01",
    },
]


def seed():
    batch = db.batch()

    for lot in LOTS:
        batch.set(db.collection("parking_lots").document(lot["id"]), {
            "name": lot["name"],
            "address": lot["address"],
            "latitude": lot["latitude"],
            "longitude": lot["longitude"],
            "hourly_rate": lot["hourly_rate"],
            "opening_hours": lot["opening_hours"],
            "total_spaces": lot["spaces"],
            "active": True,
            "created_at": now,
        })

        for i in range(1, lot["spaces"] + 1):
            space_id = f"{lot['id']}_v{i:02d}"
            batch.set(db.collection("spaces").document(space_id), {
                "parking_lot_id": lot["id"],
                "code": f"V{i:02d}",
                "status": "FREE",
                "active": True,
            })

        batch.set(db.collection("devices").document(lot["device"]), {
            "parking_lot_id": lot["id"],
            "name": f"Cancela {lot['name']}",
            "status": "ONLINE",  # o backend só aceita dispositivos ONLINE
            "last_seen": None,
        })

    # Reserva de teste já paga (para testar entrada no Wokwi / telemetria)
    arrival = now  # dentro da janela de tolerância: a entrada de teste funciona já
    departure = arrival + timedelta(hours=2)
    batch.set(db.collection("reservations").document("res_teste_001"), {
        "code": "SP-000001",
        "user_id": "user_teste",
        "parking_lot_id": "lot_pelourinho",
        "parking_lot_name": "SmartPark Pelourinho",
        "space_id": "lot_pelourinho_v01",
        "arrival_expected": arrival,
        "departure_expected": departure,
        "hours_reserved": 2,
        "hourly_rate": 8.00,
        "estimated_price": 16.00,
        "payment_id": "TESTE-0001",
        "status": "CONFIRMED",
        "expires_at": None,
        "checked_in_at": None,
        "checked_out_at": None,
        "created_at": now,
        "updated_at": now,
    })
    batch.set(db.collection("spaces").document("lot_pelourinho_v01"), {
        "status": "RESERVED",
    }, merge=True)
    batch.set(db.collection("payments").document("pay_teste_001"), {
        "reservation_id": "res_teste_001",
        "mp_payment_id": "TESTE-0001",
        "external_reference": "res_teste_001",
        "status": "approved",
        "amount": 16.00,
        "created_at": now,
        "updated_at": now,
    })

    batch.commit()
    print("Seed concluído: 2 estacionamentos, 10 vagas, 2 dispositivos, 1 reserva de teste.")


if __name__ == "__main__":
    seed()

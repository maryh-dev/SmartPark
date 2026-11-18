"""SmartPark API: autenticação, estacionamentos e pré-reservas via Firestore."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import math
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from flask import Flask, jsonify, request, send_from_directory, session
from google.api_core.exceptions import AlreadyExists, GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from werkzeug.security import check_password_hash, generate_password_hash


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

ACTIVE_RESERVATION_STATUSES = {"PENDING_PAYMENT", "CONFIRMED", "CHECKED_IN"}
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$")
EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_JSON_BYTES = 16 * 1024
# Política de tarifa (Opção A): paga-se antecipadamente o intervalo reservado.
ENTRY_TOLERANCE_MINUTES = int(os.getenv("ENTRY_TOLERANCE_MINUTES", "15"))  # +/- sobre a chegada prevista
EXIT_GRACE_MINUTES = int(os.getenv("EXIT_GRACE_MINUTES", "10"))            # folga antes de cobrar hora excedente
DEVICE_STALE_MINUTES = 5


def load_module(name: str) -> Any:
    """Importa módulos irmãos tanto com `python backend/app.py` quanto como `backend.app` (Vercel)."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return importlib.import_module(f"backend.{name}")


class APIError(Exception):
    """Erro de regra de negócio que pode ser retornado ao cliente."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_email(value: Any) -> str:
    if not isinstance(value, str):
        raise APIError("Informe um e-mail válido.")
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise APIError("Informe um e-mail válido.")
    return email


def parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise APIError(f"Informe {field_name} com data e horário.")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise APIError(f"O valor de {field_name} é inválido.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise APIError(f"{field_name.capitalize()} precisa incluir o fuso horário.")
    return parsed.astimezone(timezone.utc)


def overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and end_a > start_b


def reservation_is_active(data: dict[str, Any], now: datetime) -> bool:
    if data.get("status") not in ACTIVE_RESERVATION_STATUSES:
        return False
    expires_at = data.get("expires_at")
    return not (
        data.get("status") == "PENDING_PAYMENT"
        and isinstance(expires_at, datetime)
        and expires_at <= now
    )


def user_document_id(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def get_firestore_client(app: Flask) -> Any:
    existing = app.extensions.get("firestore_client")
    if existing is not None:
        return existing

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    service_account_info = None
    if service_account_json:
        try:
            parsed_service_account = json.loads(service_account_json)
        except json.JSONDecodeError as error:
            raise APIError(
                "FIREBASE_SERVICE_ACCOUNT_JSON não contém um JSON válido.",
                503,
            ) from error
        if not isinstance(parsed_service_account, dict):
            raise APIError(
                "FIREBASE_SERVICE_ACCOUNT_JSON deve conter um objeto JSON.",
                503,
            )
        service_account_info = parsed_service_account
    else:
        credential_path_value = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credential_path_value:
            credential_path = Path(credential_path_value)
            if not credential_path.is_absolute():
                backend_relative_path = BACKEND_DIR / credential_path
                project_relative_path = PROJECT_DIR / credential_path
                credential_path = (
                    backend_relative_path
                    if backend_relative_path.is_file()
                    else project_relative_path
                )
            if not credential_path.is_file():
                raise APIError(
                    "O arquivo de credenciais do Firebase não foi encontrado. "
                    "Confira GOOGLE_APPLICATION_CREDENTIALS no backend/.env.",
                    503,
                )
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credential_path)
        firebase_credentials = credentials.ApplicationDefault()

    try:
        try:
            firebase_app = firebase_admin.get_app()
        except ValueError:
            firebase_credentials = (
                credentials.Certificate(service_account_info)
                if service_account_info is not None
                else credentials.ApplicationDefault()
            )
            firebase_app = firebase_admin.initialize_app(firebase_credentials)
        client = firestore.client(firebase_app)
    except (GoogleAPIError, GoogleAuthError, ValueError) as error:
        app.logger.error("Falha ao inicializar o Firebase Admin: %s", type(error).__name__)
        raise APIError(
            "Não foi possível conectar ao Firebase. Confira as credenciais e o projeto.",
            503,
        ) from error

    app.extensions["firestore_client"] = client
    return client


def request_json() -> dict[str, Any]:
    if request.content_length is not None and request.content_length > MAX_JSON_BYTES:
        raise APIError("A requisição excede o tamanho permitido.", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise APIError("Envie um objeto JSON válido.")
    return payload


def make_reservation_response(snapshot: Any) -> dict[str, Any]:
    data = snapshot.to_dict() or {}
    return {
        "id": snapshot.id,
        "code": data.get("code"),
        "parking_lot_id": data.get("parking_lot_id"),
        "parking_lot_name": data.get("parking_lot_name"),
        "space_id": data.get("space_id"),
        "arrival_expected": data.get("arrival_expected").isoformat()
        if data.get("arrival_expected")
        else None,
        "departure_expected": data.get("departure_expected").isoformat()
        if data.get("departure_expected")
        else None,
        "hours_reserved": data.get("hours_reserved"),
        "hourly_rate": data.get("hourly_rate"),
        "estimated_price": data.get("estimated_price"),
        "status": data.get("status"),
        "expires_at": data.get("expires_at").isoformat()
        if data.get("expires_at")
        else None,
        "created_at": data.get("created_at").isoformat()
        if data.get("created_at")
        else None,
    }


def create_app(database: Any = None, test_config: dict[str, Any] | None = None) -> Flask:
    configured_secret = os.getenv("FLASK_SECRET_KEY")
    if os.getenv("FLASK_ENV", "").lower() == "production" and not configured_secret:
        raise RuntimeError("Configure FLASK_SECRET_KEY antes de iniciar em produção.")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=configured_secret or secrets.token_urlsafe(48),
        MAX_CONTENT_LENGTH=MAX_JSON_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    if database is not None:
        app.extensions["firestore_client"] = database

    def db() -> Any:
        return get_firestore_client(app)

    def current_user() -> dict[str, Any] | None:
        user_id = session.get("user_id")
        if not isinstance(user_id, str):
            return None
        snapshot = db().collection("users").document(user_id).get()
        if not snapshot.exists:
            session.clear()
            return None
        user = snapshot.to_dict() or {}
        if user.get("active") is not True:
            session.clear()
            return None
        user["id"] = snapshot.id
        return user

    def require_user(roles: set[str] | None = None) -> dict[str, Any]:
        user = current_user()
        if user is None:
            raise APIError("Faça login para continuar.", 401)
        if roles is not None and user.get("role") not in roles:
            raise APIError("Você não tem permissão para esta ação.", 403)
        return user

    @app.errorhandler(APIError)
    def handle_api_error(error: APIError) -> tuple[Any, int]:
        return jsonify({"message": error.message}), error.status

    @app.errorhandler(GoogleAPIError)
    def handle_firestore_error(error: GoogleAPIError) -> tuple[Any, int]:
        app.logger.error("Falha do Firestore: %s", type(error).__name__)
        return jsonify({"message": "O Firestore está indisponível. Tente novamente."}), 503

    @app.errorhandler(413)
    def handle_payload_too_large(error: Any) -> tuple[Any, int]:
        app.logger.warning("Requisição rejeitada por tamanho excedido: %s", error)
        return jsonify({"message": "A requisição excede o tamanho permitido."}), 413

    @app.get("/")
    def index() -> Any:
        return send_from_directory(PROJECT_DIR / "public", "index.html")

    @app.get("/style.css")
    def style() -> Any:
        return send_from_directory(PROJECT_DIR / "public", "style.css")

    @app.get("/script.js")
    def script() -> Any:
        return send_from_directory(PROJECT_DIR / "public", "script.js")

    @app.get("/api/health")
    def health() -> Any:
        client = db()
        list(client.collection("parking_lots").limit(1).stream())
        return jsonify({"status": "ok", "firebase": "connected"})

    @app.post("/api/auth/register")
    def register() -> Any:
        payload = request_json()
        name = payload.get("name")
        password = payload.get("password")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 60:
            raise APIError("O nome precisa ter entre 2 e 60 caracteres.")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise APIError("A senha precisa ter entre 8 e 128 caracteres.")
        email = normalize_email(payload.get("email"))
        user_id = user_document_id(email)
        user_ref = db().collection("users").document(user_id)
        created_at = datetime.now(timezone.utc)
        user_data = {
            "name": name.strip(),
            "email": email,
            "role": "customer",
            "password_hash": generate_password_hash(password, method="scrypt"),
            "active": True,
            "created_at": created_at,
            "updated_at": created_at,
        }
        try:
            user_ref.create(user_data)
        except AlreadyExists as error:
            raise APIError("Já existe uma conta com este e-mail.", 409) from error

        session.clear()
        session["user_id"] = user_id
        session.permanent = True
        return jsonify({"id": user_id, "name": user_data["name"], "email": email, "role": "customer"}), 201

    @app.post("/api/auth/login")
    def login() -> Any:
        payload = request_json()
        email = normalize_email(payload.get("email"))
        password = payload.get("password")
        if not isinstance(password, str) or not password or len(password) > 128:
            raise APIError("E-mail ou senha inválidos.", 401)
        user_ref = db().collection("users").document(user_document_id(email))
        snapshot = user_ref.get()
        user = snapshot.to_dict() if snapshot.exists else None
        password_hash = user.get("password_hash") if user else None
        if (
            not isinstance(password_hash, str)
            or user.get("active") is not True
            or not check_password_hash(password_hash, password)
        ):
            raise APIError("E-mail ou senha inválidos.", 401)
        if user.get("role") not in {"customer", "admin"}:
            raise APIError("A conta não possui um perfil autorizado.", 403)

        session.clear()
        session["user_id"] = snapshot.id
        session.permanent = True
        return jsonify({"id": snapshot.id, "name": user["name"], "email": email, "role": user["role"]})

    @app.get("/api/auth/me")
    def me() -> Any:
        user = require_user()
        return jsonify({
            "id": user["id"],
            "name": user.get("name"),
            "email": user.get("email"),
            "role": user.get("role"),
        })

    @app.post("/api/auth/logout")
    def logout() -> Any:
        session.clear()
        return jsonify({"status": "ok"})

    @app.post("/api/auth/password-reset")
    def password_reset() -> Any:
        raise APIError(
            "A recuperação de senha precisa de um provedor de e-mail configurado no backend.",
            503,
        )

    @app.get("/api/parking-lots")
    def list_parking_lots() -> Any:
        active_lots = [
            lot for lot in db().collection("parking_lots").stream()
            if (lot.to_dict() or {}).get("active") is True
        ]
        now = datetime.now(timezone.utc)
        result = []
        for lot_snapshot in active_lots:
            lot = lot_snapshot.to_dict() or {}
            spaces = list(
                db().collection("spaces")
                .where("parking_lot_id", "==", lot_snapshot.id)
                .where("active", "==", True)
                .stream()
            )
            reservations = list(
                db().collection("reservations")
                .where("parking_lot_id", "==", lot_snapshot.id)
                .stream()
            )
            reservation_data = [
                (reservation, reservation.to_dict() or {})
                for reservation in reservations
            ]
            reserved_space_ids = {
                data.get("space_id")
                for _, data in reservation_data
                if reservation_is_active(data, now)
                and isinstance(data.get("arrival_expected"), datetime)
                and data["arrival_expected"] <= now
                and isinstance(data.get("departure_expected"), datetime)
                and data["departure_expected"] > now
            }
            occupied = sum(
                1 for space in spaces
                if (space.to_dict() or {}).get("status") == "OCCUPIED"
            )
            available = sum(
                1 for space in spaces
                if (space.to_dict() or {}).get("status") not in {"OCCUPIED", "MAINTENANCE"}
                and space.id not in reserved_space_ids
            )
            result.append({
                "id": lot_snapshot.id,
                "name": lot.get("name"),
                "address": lot.get("address"),
                "latitude": lot.get("latitude"),
                "longitude": lot.get("longitude"),
                "hourly_rate": lot.get("hourly_rate"),
                "total_spaces": len(spaces),
                "occupied_spaces": occupied,
                "available_spaces": available,
                "opening_hours": lot.get("opening_hours", "Não informado"),
                "spaces": [
                    {
                        "label": (space.to_dict() or {}).get("code"),
                        "occupied": (space.to_dict() or {}).get("status") == "OCCUPIED",
                        "status": (space.to_dict() or {}).get("status", "MAINTENANCE"),
                    }
                    for space in spaces
                ],
            })
        return jsonify({"parking_lots": result})

    @app.get("/api/parking-lots/<lot_id>")
    def get_parking_lot(lot_id: str) -> Any:
        lot_snapshot = db().collection("parking_lots").document(lot_id).get()
        if not lot_snapshot.exists or (lot_snapshot.to_dict() or {}).get("active") is not True:
            raise APIError("Estacionamento não encontrado.", 404)
        lot = lot_snapshot.to_dict() or {}
        spaces = list(
            db().collection("spaces")
            .where("parking_lot_id", "==", lot_id)
            .where("active", "==", True)
            .stream()
        )
        reservations = list(
            db().collection("reservations")
            .where("parking_lot_id", "==", lot_id)
            .stream()
        )
        now = datetime.now(timezone.utc)
        reservation_data = [
            (reservation, reservation.to_dict() or {})
            for reservation in reservations
        ]
        reserved_space_ids = {
            data.get("space_id")
            for _, data in reservation_data
            if reservation_is_active(data, now)
            and isinstance(data.get("arrival_expected"), datetime)
            and data["arrival_expected"] <= now
            and isinstance(data.get("departure_expected"), datetime)
            and data["departure_expected"] > now
        }
        space_list = []
        for space in spaces:
            data = space.to_dict() or {}
            status = data.get("status", "MAINTENANCE")
            if status not in {"OCCUPIED", "MAINTENANCE"} and space.id in reserved_space_ids:
                status = "RESERVED"
            space_list.append({
                "id": space.id,
                "code": data.get("code"),
                "status": status,
            })
        return jsonify({
            "parking_lot": {
                "id": lot_snapshot.id,
                "name": lot.get("name"),
                "address": lot.get("address"),
                "latitude": lot.get("latitude"),
                "longitude": lot.get("longitude"),
                "hourly_rate": lot.get("hourly_rate"),
                "total_spaces": len(spaces),
                "available_spaces": sum(
                    1 for space in space_list
                    if space["status"] not in {"OCCUPIED", "MAINTENANCE", "RESERVED"}
                ),
                "opening_hours": lot.get("opening_hours", "Não informado"),
                "spaces": space_list,
            }
        })

    @app.get("/api/reservations")
    def list_reservations() -> Any:
        user = require_user()
        query = db().collection("reservations")
        if user.get("role") != "admin":
            query = query.where("user_id", "==", user["id"])
        reservations = [
            make_reservation_response(snapshot)
            for snapshot in query.stream()
        ]
        reservations.sort(
            key=lambda reservation: reservation.get("created_at") or "",
            reverse=True,
        )
        return jsonify({"reservations": reservations})

    @app.post("/api/reservations")
    def create_reservation() -> Any:
        user = require_user({"customer"})
        payload = request_json()
        lot_id = payload.get("parking_lot_id")
        if not isinstance(lot_id, str) or not 1 <= len(lot_id) <= 128:
            raise APIError("Selecione um estacionamento válido.")
        arrival = parse_datetime(payload.get("arrival_expected"), "horário de entrada")
        departure = parse_datetime(payload.get("departure_expected"), "horário de saída")
        now = datetime.now(timezone.utc)
        if arrival < now:
            raise APIError("O horário de entrada não pode estar no passado.")
        if departure <= arrival:
            raise APIError("O horário de saída precisa ser posterior à entrada.")

        db_client = db()
        lot_ref = db_client.collection("parking_lots").document(lot_id)
        reservations_ref = db_client.collection("reservations")
        spaces_query = (
            db_client.collection("spaces")
            .where("parking_lot_id", "==", lot_id)
            .where("active", "==", True)
        )
        transaction = db_client.transaction()

        @firestore.transactional
        def reserve(transaction_obj: Any) -> dict[str, Any]:
            lot_snapshot = lot_ref.get(transaction=transaction_obj)
            lot = lot_snapshot.to_dict() if lot_snapshot.exists else None
            if not lot or lot.get("active") is not True:
                raise APIError("Estacionamento não encontrado.", 404)
            try:
                rate = Decimal(str(lot.get("hourly_rate"))).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            except (InvalidOperation, TypeError) as error:
                raise APIError("A tarifa do estacionamento está inválida.", 503) from error
            if not rate.is_finite() or rate <= 0:
                raise APIError("A tarifa do estacionamento está inválida.", 503)

            space_snapshots = list(spaces_query.stream(transaction=transaction_obj))
            reservation_snapshots = list(
                reservations_ref.where("parking_lot_id", "==", lot_id)
                .stream(transaction=transaction_obj)
            )
            active_bookings: list[dict[str, Any]] = []
            writes: list[tuple[Any, dict[str, Any]]] = []
            transaction_now = datetime.now(timezone.utc)

            for snapshot in reservation_snapshots:
                data = snapshot.to_dict() or {}
                status = data.get("status")
                expires_at = data.get("expires_at")
                if (
                    status == "PENDING_PAYMENT"
                    and isinstance(expires_at, datetime)
                    and expires_at <= transaction_now
                ):
                    writes.append((snapshot.reference, {
                        "status": "EXPIRED",
                        "updated_at": transaction_now,
                    }))
                    continue
                if status in ACTIVE_RESERVATION_STATUSES:
                    active_bookings.append(data)

            occupied_statuses = {"OCCUPIED", "MAINTENANCE"}
            candidate_spaces = [
                space for space in space_snapshots
                if (space.to_dict() or {}).get("status") not in occupied_statuses
            ]
            selected_space = None
            for space in candidate_spaces:
                conflicts = any(
                    booking.get("space_id") == space.id
                    and isinstance(booking.get("arrival_expected"), datetime)
                    and isinstance(booking.get("departure_expected"), datetime)
                    and overlap(
                        arrival,
                        departure,
                        booking["arrival_expected"],
                        booking["departure_expected"],
                    )
                    for booking in active_bookings
                )
                if not conflicts:
                    selected_space = space
                    break

            if selected_space is None:
                raise APIError("Não há vaga disponível nesse período.", 409)

            duration_seconds = (departure - arrival).total_seconds()
            hours = math.ceil(duration_seconds / 3600)
            total = (rate * hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            reservation_id = uuid.uuid4().hex
            reservation_code = f"SP-{secrets.randbelow(900000) + 100000}"
            expires_at = transaction_now + timedelta(minutes=15)
            reservation_data = {
                "code": reservation_code,
                "user_id": user["id"],
                "parking_lot_id": lot_id,
                "parking_lot_name": lot.get("name"),
                "space_id": selected_space.id,
                "arrival_expected": arrival,
                "departure_expected": departure,
                "hours_reserved": hours,
                "hourly_rate": float(rate),
                "estimated_price": float(total),
                "status": "PENDING_PAYMENT",
                "expires_at": expires_at,
                "checked_in_at": None,
                "checked_out_at": None,
                "created_at": transaction_now,
                "updated_at": transaction_now,
            }
            reservation_ref = reservations_ref.document(reservation_id)
            transaction_obj.set(reservation_ref, reservation_data)
            transaction_obj.update(selected_space.reference, {"status": "RESERVED"})
            for reference, update in writes:
                transaction_obj.update(reference, update)
            return {"id": reservation_id, **reservation_data}

        reservation = reserve(transaction)
        return jsonify({
            "reservation": {
                "id": reservation["id"],
                "code": reservation["code"],
                "parking_lot_id": reservation["parking_lot_id"],
                "parking_lot_name": reservation["parking_lot_name"],
                "space_id": reservation["space_id"],
                "arrival_expected": arrival.isoformat(),
                "departure_expected": departure.isoformat(),
                "hours_reserved": reservation["hours_reserved"],
                "hourly_rate": reservation["hourly_rate"],
                "estimated_price": reservation["estimated_price"],
                "status": reservation["status"],
                "expires_at": reservation["expires_at"].isoformat(),
                "payment_required": True,
            }
        }), 201

    @app.post("/api/reservations/<reservation_id>/cancel")
    def cancel_reservation(reservation_id: str) -> Any:
        user = require_user()
        reservation_ref = db().collection("reservations").document(reservation_id)
        transaction = db().transaction()

        @firestore.transactional
        def cancel(transaction_obj: Any) -> dict[str, Any]:
            snapshot = reservation_ref.get(transaction=transaction_obj)
            if not snapshot.exists:
                raise APIError("Reserva não encontrada.", 404)
            reservation = snapshot.to_dict() or {}
            if user.get("role") != "admin" and reservation.get("user_id") != user["id"]:
                raise APIError("Você não tem permissão para cancelar esta reserva.", 403)
            if reservation.get("status") != "PENDING_PAYMENT":
                raise APIError("Somente uma reserva aguardando pagamento pode ser cancelada.", 409)
            now = datetime.now(timezone.utc)
            space_id = reservation.get("space_id")
            lot_id = reservation.get("parking_lot_id")
            space_ref = None
            space_snapshot = None
            still_reserved = False
            if isinstance(space_id, str) and isinstance(lot_id, str):
                space_ref = db().collection("spaces").document(space_id)
                space_snapshot = space_ref.get(transaction=transaction_obj)
                other_reservations = list(
                    db().collection("reservations")
                    .where("parking_lot_id", "==", lot_id)
                    .stream(transaction=transaction_obj)
                )
                still_reserved = any(
                    other.id != reservation_id
                    and reservation_is_active(other.to_dict() or {}, now)
                    and (other.to_dict() or {}).get("space_id") == space_id
                    and isinstance((other.to_dict() or {}).get("departure_expected"), datetime)
                    and (other.to_dict() or {}).get("departure_expected") > now
                    for other in other_reservations
                )
            transaction_obj.update(reservation_ref, {
                "status": "CANCELLED",
                "updated_at": now,
            })
            if space_ref is not None and space_snapshot is not None:
                if space_snapshot.exists and not still_reserved:
                    transaction_obj.update(space_ref, {"status": "FREE"})
            return {"id": reservation_id, "status": "CANCELLED"}

        return jsonify({"reservation": cancel(transaction)})

    def authenticate_device(payload: dict[str, Any]) -> tuple[str, str, float]:
        configured_secret = os.getenv("DEVICE_SHARED_SECRET")
        supplied_secret = request.headers.get("X-Device-Secret", "")
        if not configured_secret:
            raise APIError("A autenticação do dispositivo não está configurada.", 503)
        if not supplied_secret or not hmac.compare_digest(supplied_secret, configured_secret):
            raise APIError("Dispositivo não autorizado.", 401)

        device_id = payload.get("device_id")
        event_id = payload.get("event_id")
        event_type = payload.get("event_type")
        distance = payload.get("distance_cm")
        if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", device_id):
            raise APIError("Identificador de dispositivo inválido.")
        if not isinstance(event_id, str) or not EVENT_ID_PATTERN.fullmatch(event_id):
            raise APIError("Identificador de evento inválido.")
        if event_type not in {"ENTRY", "EXIT"}:
            raise APIError("Tipo de evento inválido.")
        if (
            isinstance(distance, bool)
            or not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or not 0 < distance <= 500
        ):
            raise APIError("A distância do sensor é inválida.")
        return device_id, event_id, float(distance)

    def get_device_and_lot(
        transaction_obj: Any,
        device_id: str,
    ) -> tuple[Any, dict[str, Any]]:
        db_client = db()
        device_ref = db_client.collection("devices").document(device_id)
        device_snapshot = device_ref.get(transaction=transaction_obj)
        device = device_snapshot.to_dict() if device_snapshot.exists else None
        if not device or device.get("status") != "ONLINE":
            raise APIError("Dispositivo inexistente, offline ou em manutenção.", 403)
        lot_id = device.get("parking_lot_id")
        if not isinstance(lot_id, str):
            raise APIError("Dispositivo sem estacionamento associado.", 503)
        lot_ref = db_client.collection("parking_lots").document(lot_id)
        lot_snapshot = lot_ref.get(transaction=transaction_obj)
        lot = lot_snapshot.to_dict() if lot_snapshot.exists else None
        if not lot or lot.get("active") is not True:
            raise APIError("Estacionamento do dispositivo indisponível.", 503)
        return device_ref, device

    @app.post("/api/iot/access-request")
    def iot_access_request() -> Any:
        payload = request_json()
        device_id, event_id, _distance = authenticate_device(payload)
        if payload.get("event_type") != "ENTRY":
            raise APIError("A rota de autorização aceita somente eventos ENTRY.")

        db_client = db()
        event_ref = db_client.collection("access_events").document(event_id)
        transaction = db_client.transaction()

        @firestore.transactional
        def authorize(transaction_obj: Any) -> dict[str, Any]:
            existing_event = event_ref.get(transaction=transaction_obj)
            if existing_event.exists:
                existing = existing_event.to_dict() or {}
                return {
                    "allowed": existing.get("result") == "GRANTED",
                    "reason": existing.get("reason", "Evento já processado."),
                    "duplicate": True,
                }

            device_ref, device = get_device_and_lot(
                transaction_obj,
                device_id,
            )
            lot_id = device["parking_lot_id"]
            now = datetime.now(timezone.utc)
            reservations = list(
                db_client.collection("reservations")
                .where("parking_lot_id", "==", lot_id)
                .stream(transaction=transaction_obj)
            )
            eligible = []
            no_shows = []
            tolerance = timedelta(minutes=ENTRY_TOLERANCE_MINUTES)
            for snapshot in reservations:
                reservation = snapshot.to_dict() or {}
                arrival = reservation.get("arrival_expected")
                departure = reservation.get("departure_expected")
                if reservation.get("status") != "CONFIRMED" or not isinstance(arrival, datetime):
                    continue
                if not isinstance(departure, datetime):
                    continue
                if arrival - tolerance <= now <= arrival + tolerance and now < departure:
                    eligible.append((snapshot, reservation))
                elif now > arrival + tolerance:
                    no_shows.append(snapshot.reference)  # passou da tolerância: expira
            eligible.sort(key=lambda item: item[1]["arrival_expected"])

            allowed = bool(eligible)
            reason = "Reserva confirmada validada." if allowed else "Não há reserva confirmada dentro da janela de tolerância."
            reservation_id = None
            space_ref = None
            space_snapshot = None
            if allowed:
                reservation_snapshot, reservation = eligible[0]
                reservation_id = reservation_snapshot.id
                space_id = reservation.get("space_id")
                if isinstance(space_id, str):
                    space_ref = db_client.collection("spaces").document(space_id)
                    space_snapshot = space_ref.get(transaction=transaction_obj)
                if space_snapshot is None or not space_snapshot.exists:
                    allowed = False
                    reason = "A vaga vinculada à reserva não está disponível."
                    reservation_id = None

            now = datetime.now(timezone.utc)
            transaction_obj.set(event_ref, {
                "device_id": device_id,
                "parking_lot_id": lot_id,
                "direction": "ENTRY",
                "reservation_id": reservation_id,
                "result": "GRANTED" if allowed else "DENIED",
                "reason": reason,
                "created_at": now,
            })
            transaction_obj.update(device_ref, {
                "status": "ONLINE",
                "last_seen": now,
            })
            for stale_ref in no_shows:  # no-show após a tolerância => EXPIRED (reembolso é tratado à parte)
                transaction_obj.update(stale_ref, {"status": "EXPIRED", "refund_needed": True,
                                                   "note": "Não compareceu dentro da tolerância",
                                                   "updated_at": now})
            if allowed and reservation_id and space_ref and space_snapshot:
                reservation_ref = db_client.collection("reservations").document(reservation_id)
                transaction_obj.update(reservation_ref, {
                    "status": "CHECKED_IN",
                    "checked_in_at": now,
                    "updated_at": now,
                })
                transaction_obj.update(space_ref, {"status": "OCCUPIED"})
            return {"allowed": allowed, "reason": reason, "duplicate": False}

        result = authorize(transaction)
        return jsonify(result)

    @app.post("/api/iot/telemetry")
    def iot_telemetry() -> Any:
        payload = request_json()
        device_id, event_id, _distance = authenticate_device(payload)
        if payload.get("event_type") != "EXIT":
            raise APIError("A rota de telemetria de saída aceita somente eventos EXIT.")

        db_client = db()
        event_ref = db_client.collection("access_events").document(event_id)
        transaction = db_client.transaction()

        @firestore.transactional
        def register_exit(transaction_obj: Any) -> dict[str, Any]:
            existing_event = event_ref.get(transaction=transaction_obj)
            if existing_event.exists:
                existing = existing_event.to_dict() or {}
                return {
                    "registered": existing.get("result") == "GRANTED",
                    "reason": existing.get("reason", "Evento já processado."),
                    "duplicate": True,
                }

            device_ref, device = get_device_and_lot(
                transaction_obj,
                device_id,
            )
            lot_id = device["parking_lot_id"]
            reservations = list(
                db_client.collection("reservations")
                .where("parking_lot_id", "==", lot_id)
                .stream(transaction=transaction_obj)
            )
            checked_in = [
                (snapshot, snapshot.to_dict() or {})
                for snapshot in reservations
                if (snapshot.to_dict() or {}).get("status") == "CHECKED_IN"
                and isinstance((snapshot.to_dict() or {}).get("checked_in_at"), datetime)
                and (snapshot.to_dict() or {}).get("checked_out_at") is None
            ]
            checked_in.sort(key=lambda item: item[1]["checked_in_at"])
            now = datetime.now(timezone.utc)

            if not checked_in:
                reason = "Não há entrada ativa para registrar."
                transaction_obj.set(event_ref, {
                    "device_id": device_id,
                    "parking_lot_id": lot_id,
                    "direction": "EXIT",
                    "reservation_id": None,
                    "result": "DENIED",
                    "reason": reason,
                    "created_at": now,
                })
                transaction_obj.update(device_ref, {"status": "ONLINE", "last_seen": now})
                return {"registered": False, "reason": reason, "duplicate": False}

            reservation_snapshot, reservation = checked_in[0]
            reservation_id = reservation_snapshot.id
            space_id = reservation.get("space_id")
            space_ref = db_client.collection("spaces").document(space_id)
            space_snapshot = space_ref.get(transaction=transaction_obj)
            ticket_ref = db_client.collection("tickets").document(reservation_id)
            ticket_snapshot = ticket_ref.get(transaction=transaction_obj)

            if ticket_snapshot.exists:
                reason = "O ticket desta reserva já foi criado."
                transaction_obj.set(event_ref, {
                    "device_id": device_id,
                    "parking_lot_id": lot_id,
                    "direction": "EXIT",
                    "reservation_id": reservation_id,
                    "result": "GRANTED",
                    "reason": reason,
                    "created_at": now,
                })
                return {"registered": True, "reason": reason, "duplicate": False}

            checked_in_at = reservation["checked_in_at"]
            hourly_rate = Decimal(str(reservation.get("hourly_rate", 0)))
            prepaid = (hourly_rate * int(reservation.get("hours_reserved") or 1)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            departure_expected = reservation.get("departure_expected")
            extra_hours = 0
            if isinstance(departure_expected, datetime) and now > departure_expected + timedelta(minutes=EXIT_GRACE_MINUTES):
                extra_hours = math.ceil((now - departure_expected).total_seconds() / 3600)
            extra = (hourly_rate * extra_hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            space_code = (space_snapshot.to_dict() or {}).get("code") if space_snapshot.exists else None
            ticket = {
                "code": f"T-{reservation.get('code', reservation_id)}",
                "reservation_id": reservation_id,
                "parking_lot_name": reservation.get("parking_lot_name"),
                "space_code": space_code,
                "entry_at": checked_in_at,
                "exit_at": now,
                "duration_minutes": int((now - checked_in_at).total_seconds() // 60),
                "prepaid_amount": float(prepaid),
                "extra_hours": extra_hours,
                "extra_amount": float(extra),
                "extra_payment_status": "DUE" if extra_hours else "NONE",
                "total_amount": float(prepaid + extra),
                "payment_status": "aprovado",
                "telegram_status": "PENDING_RETRY",
                "created_at": now,
            }
            transaction_obj.set(ticket_ref, ticket)
            transaction_obj.update(reservation_snapshot.reference, {
                "status": "COMPLETED",
                "checked_out_at": now,
                "updated_at": now,
            })
            still_occupied = any(
                other.id != reservation_id
                and (other.to_dict() or {}).get("space_id") == space_id
                and (other.to_dict() or {}).get("status") == "CHECKED_IN"
                and (other.to_dict() or {}).get("checked_out_at") is None
                for other in reservations
            )
            if space_snapshot.exists and not still_occupied:
                transaction_obj.update(space_ref, {"status": "FREE"})
            transaction_obj.set(event_ref, {
                "device_id": device_id,
                "parking_lot_id": lot_id,
                "direction": "EXIT",
                "reservation_id": reservation_id,
                "result": "GRANTED",
                "reason": "Saída registrada e ticket criado.",
                "created_at": now,
            })
            transaction_obj.update(device_ref, {"status": "ONLINE", "last_seen": now})
            return {
                "registered": True,
                "reason": "Saída registrada e ticket criado.",
                "duplicate": False,
                "ticket": {
                    "code": ticket["code"],
                    "total_amount": ticket["total_amount"],
                },
                "_ticket_full": ticket,
            }

        result = register_exit(transaction)
        full_ticket = result.pop("_ticket_full", None)
        if full_ticket:  # fora da transação: se o Telegram falhar, o ticket já está salvo
            try:
                status = load_module("telegram_service").send_final_ticket(full_ticket)
            except Exception:
                status = "PENDING_RETRY"
            db_client.collection("tickets").document(full_ticket["reservation_id"]).update(
                {"telegram_status": status})
            result["ticket"]["telegram_status"] = status
        return jsonify(result)

    # ------------------------------------------------------------------ páginas de retorno do pagamento
    for page in ("pagamento-sucesso.html", "pagamento-pendente.html", "pagamento-falha.html", "pagamento.js"):
        app.add_url_rule(f"/{page}", endpoint=f"static_{page}",
                         view_func=lambda page=page: send_from_directory(PROJECT_DIR / "public", page))

    # ------------------------------------------------------------------ consultas
    @app.get("/api/reservations/<reservation_id>")
    def get_reservation(reservation_id: str) -> Any:
        user = require_user()
        snapshot = db().collection("reservations").document(reservation_id).get()
        data = snapshot.to_dict() if snapshot.exists else None
        # 404 também quando é de outro usuário: não revela que o código existe (T14)
        if not data or (user.get("role") != "admin" and data.get("user_id") != user["id"]):
            raise APIError("Reserva não encontrada.", 404)
        return jsonify({"reservation": make_reservation_response(snapshot)})

    @app.get("/api/parking-lots/<lot_id>/availability")
    def lot_availability(lot_id: str) -> Any:
        arrival = parse_datetime(request.args.get("arrival"), "horário de entrada")
        departure = parse_datetime(request.args.get("departure"), "horário de saída")
        if departure <= arrival:
            raise APIError("O horário de saída precisa ser posterior à entrada.")
        lot_snapshot = db().collection("parking_lots").document(lot_id).get()
        lot = lot_snapshot.to_dict() if lot_snapshot.exists else None
        if not lot or lot.get("active") is not True:
            raise APIError("Estacionamento não encontrado.", 404)
        now = datetime.now(timezone.utc)
        spaces = list(db().collection("spaces").where("parking_lot_id", "==", lot_id)
                      .where("active", "==", True).stream())
        bookings = [
            data for data in (r.to_dict() or {} for r in db().collection("reservations")
                              .where("parking_lot_id", "==", lot_id).stream())
            if reservation_is_active(data, now)
            and isinstance(data.get("arrival_expected"), datetime)
            and isinstance(data.get("departure_expected"), datetime)
        ]
        free = [
            space for space in spaces
            if (space.to_dict() or {}).get("status") not in {"OCCUPIED", "MAINTENANCE"}
            and not any(b.get("space_id") == space.id and overlap(
                arrival, departure, b["arrival_expected"], b["departure_expected"]) for b in bookings)
        ]
        rate = Decimal(str(lot.get("hourly_rate"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        hours = math.ceil((departure - arrival).total_seconds() / 3600)
        return jsonify({
            "parking_lot_id": lot_id,
            "available_spaces": len(free),
            "hours": hours,
            "hourly_rate": float(rate),
            "estimated_price": float((rate * hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    # ------------------------------------------------------------------ administração
    @app.post("/api/admin/parking-lots")
    def admin_create_parking_lot() -> Any:
        require_user({"admin"})
        payload = request_json()
        name, address = payload.get("name"), payload.get("address")
        hours_text = payload.get("opening_hours", "Não informado")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 80:
            raise APIError("Nome inválido (2 a 80 caracteres).")
        if not isinstance(address, str) or not 2 <= len(address.strip()) <= 160:
            raise APIError("Endereço inválido (2 a 160 caracteres).")
        if not isinstance(hours_text, str) or len(hours_text) > 60:
            raise APIError("Horário de funcionamento inválido.")
        try:
            latitude, longitude = float(payload.get("latitude")), float(payload.get("longitude"))
            rate = Decimal(str(payload.get("hourly_rate"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total = int(payload.get("total_spaces"))
        except (TypeError, ValueError, InvalidOperation) as error:
            raise APIError("Latitude, longitude, tarifa e número de vagas precisam ser numéricos.") from error
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise APIError("Coordenadas fora do intervalo válido.")
        if not rate.is_finite() or not 0 < rate <= 1000:
            raise APIError("A tarifa precisa ser maior que zero.")
        if not 1 <= total <= 200:
            raise APIError("O número de vagas deve estar entre 1 e 200.")
        lot_id = f"lot_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        batch = db().batch()
        batch.set(db().collection("parking_lots").document(lot_id), {
            "name": name.strip(), "address": address.strip(), "latitude": latitude,
            "longitude": longitude, "hourly_rate": float(rate), "opening_hours": hours_text,
            "total_spaces": total, "active": True, "created_at": now})
        for index in range(1, total + 1):
            batch.set(db().collection("spaces").document(f"{lot_id}_v{index:02d}"), {
                "parking_lot_id": lot_id, "code": f"V{index:02d}", "status": "FREE", "active": True})
        batch.commit()
        return jsonify({"id": lot_id, "name": name.strip(), "total_spaces": total}), 201

    @app.get("/api/admin/overview")
    def admin_overview() -> Any:
        require_user({"admin"})
        now = datetime.now(timezone.utc)
        lots = []
        spaces = [(s.id, s.to_dict() or {}) for s in db().collection("spaces").stream()]
        for lot in db().collection("parking_lots").stream():
            data = lot.to_dict() or {}
            lot_spaces = [d for _, d in spaces if d.get("parking_lot_id") == lot.id and d.get("active")]
            lots.append({
                "id": lot.id, "name": data.get("name"), "total": len(lot_spaces),
                "occupied": sum(1 for d in lot_spaces if d.get("status") == "OCCUPIED"),
                "reserved": sum(1 for d in lot_spaces if d.get("status") == "RESERVED"),
                "maintenance": sum(1 for d in lot_spaces if d.get("status") == "MAINTENANCE"),
            })
        reservations = sorted(
            (make_reservation_response(r) for r in db().collection("reservations").stream()),
            key=lambda item: item.get("created_at") or "", reverse=True)[:20]

        alerts = []
        for device in db().collection("devices").stream():
            d = device.to_dict() or {}
            last_seen = d.get("last_seen")
            if d.get("status") != "ONLINE":
                alerts.append({"type": "DEVICE", "message": f"Dispositivo {device.id} está {d.get('status')}."})
            elif isinstance(last_seen, datetime) and now - last_seen > timedelta(minutes=DEVICE_STALE_MINUTES):
                alerts.append({"type": "DEVICE", "message": f"Dispositivo {device.id} sem comunicação há mais de {DEVICE_STALE_MINUTES} min."})
        for pay in db().collection("payments").stream():
            d = pay.to_dict() or {}
            if d.get("needs_review") or d.get("refund_needed"):
                alerts.append({"type": "PAYMENT", "message": f"Pagamento {pay.id}: {d.get('note', 'revisar')}."})
        for note in db().collection("notifications").where("status", "in", ["PENDING_RETRY", "FAILED"]).stream():
            d = note.to_dict() or {}
            alerts.append({"type": "NOTIFICATION", "message": f"Notificação {note.id} em {d.get('status')}."})
        return jsonify({"parking_lots": lots, "reservations": reservations, "alerts": alerts})

    @app.post("/api/admin/expire-pending")
    def admin_expire_pending() -> Any:
        """Expira PENDING_PAYMENT vencidas. Admin logado ou agendador com X-Cron-Secret."""
        cron_secret = os.getenv("CRON_SECRET")
        supplied = request.headers.get("X-Cron-Secret", "")
        if not (cron_secret and supplied and hmac.compare_digest(supplied, cron_secret)):
            require_user({"admin"})
        now = datetime.now(timezone.utc)
        expired = 0
        for snapshot in db().collection("reservations").where("status", "==", "PENDING_PAYMENT").stream():
            expires_at = (snapshot.to_dict() or {}).get("expires_at")
            if isinstance(expires_at, datetime) and expires_at <= now:
                snapshot.reference.update({"status": "EXPIRED", "updated_at": now})
                expired += 1
        return jsonify({"expired": expired})

    @app.post("/api/admin/notifications/retry")
    def admin_retry_notifications() -> Any:
        require_user({"admin"})
        return jsonify({"sent": load_module("telegram_service").retry_pending()})

    # ------------------------------------------------------------------ pagamento (Mercado Pago)
    def notify_confirmation(reservation: dict[str, Any]) -> None:
        try:
            load_module("telegram_service").send_reservation_confirmation(reservation)
        except Exception:  # nunca derruba o webhook por causa do Telegram
            app.logger.warning("Notificação de confirmação falhou")

    load_module("payments").register_payments(app, db, require_user, APIError, notify_confirmation)

    return app


def create_admin() -> None:
    """Cria um administrador pelo terminal sem receber senha em argumento ou log."""
    app = create_app()
    with app.app_context():
        db_client = get_firestore_client(app)
        email = normalize_email(input("E-mail do administrador: "))
        name = input("Nome do administrador: ").strip()
        if not 2 <= len(name) <= 60:
            raise SystemExit("O nome precisa ter entre 2 e 60 caracteres.")
        import getpass

        password = getpass.getpass("Senha do administrador (mínimo 12 caracteres): ")
        if len(password) < 12:
            raise SystemExit("A senha do administrador precisa ter pelo menos 12 caracteres.")
        user_id = user_document_id(email)
        now = datetime.now(timezone.utc)
        try:
            db_client.collection("users").document(user_id).create({
                "name": name,
                "email": email,
                "role": "admin",
                "password_hash": generate_password_hash(password, method="scrypt"),
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
        except AlreadyExists as error:
            raise SystemExit("Já existe uma conta cadastrada com esse e-mail.") from error
        print("Administrador cadastrado com sucesso.")


app = create_app()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        create_admin()
    else:
        app.run(
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG", "").lower() == "true",
        )

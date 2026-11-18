# Estrutura do Firestore e da API

Nomes em `snake_case`. Datas são `Timestamp`. Só o backend (Admin SDK) escreve; `firestore.rules` nega acesso direto.

| Coleção | Campos principais | Quem escreve |
|---|---|---|
| `users/{sha256(email)}` | name, email, role (customer/admin), password_hash (scrypt), active | backend |
| `parking_lots/{id}` | name, address, latitude, longitude, hourly_rate, opening_hours, total_spaces, active | admin |
| `spaces/{id}` | parking_lot_id, code, status (FREE/RESERVED/OCCUPIED/MAINTENANCE), active | backend/IoT |
| `reservations/{id}` | code, user_id, parking_lot_id, parking_lot_name, space_id, arrival_expected, departure_expected, hours_reserved, hourly_rate, estimated_price, status, expires_at, preference_id, payment_id, checked_in_at, checked_out_at | backend |
| `payments/mp_{payment_id}` | reservation_id, provider, mp_payment_id, status, amount, currency, verified_at, needs_review, refund_needed, note | webhook/sync |
| `access_events/{event_id}` | device_id, parking_lot_id, direction (ENTRY/EXIT), reservation_id, result (GRANTED/DENIED), reason | rotas IoT |
| `tickets/{reservation_id}` | code, entry_at, exit_at, duration_minutes, prepaid_amount, extra_hours, extra_amount, extra_payment_status, total_amount, payment_status, telegram_status | saída |
| `devices/{id}` | parking_lot_id, name, status (ONLINE/OFFLINE/MAINTENANCE), last_seen | seed/IoT |
| `notifications/{tipo:chave}` | channel, type, reservation_id, message, status (SENT/FAILED/PENDING_RETRY), attempts, sent_at | telegram_service |

**Status da reserva:** `PENDING_PAYMENT → CONFIRMED → CHECKED_IN → COMPLETED`; saídas laterais: `EXPIRED`, `CANCELLED`.

## Política de tarifa (Opção A, versão escolar)
- Preço = `ceil(horas reservadas) × hourly_rate`, calculado no servidor.
- Entrada permitida de **15 min antes até 15 min depois** da chegada prevista (`ENTRY_TOLERANCE_MINUTES`). Depois disso a reserva vira `EXPIRED` (marcada `refund_needed`).
- `PENDING_PAYMENT` expira em **15 min**.
- Saída após `departure_expected` + 10 min de folga (`EXIT_GRACE_MINUTES`): registra **hora excedente** (`ceil(horas) × tarifa`) no ticket com `extra_payment_status: DUE` e avisa pelo Telegram; a cobrança extra é apenas registrada nesta versão.
- Cancelamento: só enquanto `PENDING_PAYMENT`. Reembolso: manual no painel do Mercado Pago.

## Rotas
| Rota | Proteção |
|---|---|
| `GET /api/parking-lots`, `GET /api/parking-lots/<id>`, `GET /api/parking-lots/<id>/availability?arrival&departure` | pública (campos públicos) |
| `POST /api/auth/register|login|logout`, `GET /api/auth/me` | sessão |
| `POST /api/reservations`, `GET /api/reservations`, `GET /api/reservations/<id>`, `POST .../cancel` | cliente dono (404 para outro usuário) |
| `POST /api/reservations/<id>/checkout`, `POST .../sync-payment` | cliente dono |
| `POST /webhooks/mercadopago` | assinatura HMAC + consulta à API do MP |
| `POST /api/iot/access-request`, `POST /api/iot/telemetry` | `X-Device-Secret` + `event_id` idempotente |
| `GET /api/admin/overview`, `POST /api/admin/parking-lots`, `POST /api/admin/notifications/retry` | administrador |
| `POST /api/admin/expire-pending` | administrador ou `X-Cron-Secret` |

# EVA AI — Flask Backend

REST, WebSocket, MQTT, and OTA API server for the EVA AI voice assistant platform.

**API Version:** v1 · **Status:** Stable

---

## Overview

EVA is an ESP32-based smart speaker that pairs with a Flutter mobile app and a Flask cloud backend to deliver real-time conversational AI (Speech-to-Text → LLM → Text-to-Speech). This repository is the Flask backend that exposes five API surfaces:

| Surface | Protocol | Consumed By | Purpose |
|---|---|---|---|
| App REST API | HTTPS / JSON | Flutter app | Auth, device registry, claim, history, commands |
| Device REST API | HTTPS mTLS | EVA device | Bootstrap, audio session, heartbeat, log upload |
| WebSocket API | WSS / JSON | Flutter app | Live transcripts, device online/offline events |
| MQTT Topics | MQTT over TLS | EVA device | Device state, events, commands, audio metadata |
| OTA API | HTTPS mTLS | EVA device | Firmware update check and signed blob download |

---

## Project Structure

```
EvaV1/
├── run.py                        # Entry point
├── requirements.txt
├── .env.example
└── app/
    ├── __init__.py               # App factory
    ├── config.py                 # Config class (env-driven)
    ├── extensions.py             # db, jwt, socketio, limiter singletons
    ├── models/
    │   ├── user.py
    │   ├── device.py
    │   ├── conversation.py
    │   ├── message.py
    │   ├── ota_release.py
    │   └── subscription.py
    ├── api/v1/
    │   ├── auth.py               # /v1/auth/*
    │   ├── devices.py            # /v1/devices/*
    │   ├── conversations.py      # /v1/conversations/*
    │   ├── subscriptions.py      # /v1/subscriptions/*
    │   ├── device_api.py         # /v1/device/*  (mTLS — hardware only)
    │   └── ota.py                # /v1/ota/*     (mTLS — hardware only)
    ├── utils/
    │   ├── errors.py             # Standard error envelope
    │   ├── auth.py               # @require_scope decorator
    │   └── mtls.py               # @require_device_cert decorator
    └── websocket/
        └── handlers.py           # SocketIO events + push_* helpers
```

---

## Getting Started

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd EvaV1
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your values
```

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key` | Flask secret key |
| `JWT_SECRET_KEY` | `dev-jwt-secret` | JWT signing key |
| `DATABASE_URL` | `sqlite:///eva.db` | SQLAlchemy database URI |
| `MQTT_BROKER_HOST` | `mqtt.eva.ai` | MQTT broker hostname |
| `MQTT_BROKER_PORT` | `8883` | MQTT broker port |
| `REDIS_URL` | `memory://` | Rate limiter storage (use Redis in production) |

### 3. Run the server

```bash
python run.py
```

The server starts on `http://0.0.0.0:5000`. The database tables are created automatically on first run.

---

## Authentication

### App endpoints — JWT Bearer

The Flutter app authenticates with a short-lived access token (15 min) and a long-lived refresh token (30 days), both issued at login.

```
Authorization: Bearer <access_token>
```

On a `401 TOKEN_EXPIRED` response, refresh once via `POST /v1/auth/refresh` and retry. A second `401` forces re-login.

### Device endpoints — mTLS

Device REST and OTA endpoints require a client X.509 certificate. In production, the TLS-terminating proxy (nginx / ALB) performs the handshake and forwards the fingerprint as a header:

```
X-SSL-Client-Fingerprint: <sha256-hex>
```

In development, set this header manually with the `cert_fp` value of a device record in the database.

---

## API Endpoints

### Authentication — `/v1/auth`

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/auth/register` | Create account; returns token pair |
| `POST` | `/v1/auth/login` | Verify credentials; returns token pair |
| `POST` | `/v1/auth/refresh` | Rotate refresh token; returns new pair |
| `POST` | `/v1/auth/logout` | Revoke refresh token |

### Devices — `/v1/devices`

Requires `devices:read` or `devices:write` scope.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/devices/claim` | Bind an unclaimed device to the caller's account |
| `GET` | `/v1/devices` | List all owned devices |
| `GET` | `/v1/devices/<id>` | Get a single device |
| `PATCH` | `/v1/devices/<id>` | Update device name |
| `DELETE` | `/v1/devices/<id>` | Unclaim a device |
| `POST` | `/v1/devices/<id>/commands` | Dispatch a command (set_volume, reboot, mute, …) |
| `GET` | `/v1/devices/<id>/conversations` | List voice sessions for a device |

### Conversations — `/v1/conversations`

Requires `conversations:read` scope.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/conversations/<id>/messages` | Get messages for a conversation |

### Subscriptions — `/v1/subscriptions`

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/subscriptions/me` | Get the caller's active subscription |
| `POST` | `/v1/subscriptions/change` | Change plan (free / plus / pro) |

### Device REST (hardware only, mTLS) — `/v1/device`

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/device/bootstrap` | Register device and receive MQTT config |
| `POST` | `/v1/device/audio/session` | Request an audio session token |
| `POST` | `/v1/device/heartbeat` | Report health; refresh `last_seen` |
| `POST` | `/v1/device/logs` | Upload diagnostic log batch |

### OTA (hardware only, mTLS) — `/v1/ota`

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/ota/check` | Check for a newer firmware release |
| `GET` | `/v1/ota/blob/<version>` | Download firmware binary |

---

## WebSocket API

Connect to `ws://localhost:5000/` with a valid access token:

```
?token=<access_token>
```

### Client → Server

| type | data | Description |
|---|---|---|
| `subscribe` | `{ device_ids: [] }` | Subscribe to events for owned devices |
| `unsubscribe` | `{ device_ids: [] }` | Unsubscribe from devices |
| `pong` | `{}` | Reply to server heartbeat ping |

### Server → Client events

| type | Description |
|---|---|
| `transcript.partial` | Interim STT fragment during a voice session |
| `transcript.final` | Finalised transcript line (persisted as a message) |
| `device.online` | Device connected |
| `device.offline` | Device disconnected (LWT fired) |
| `command.ack` | Device acknowledged a dispatched command |
| `ota.progress` | Firmware update progress |
| `error` | Subscription or protocol error |

---

## MQTT Topics

Devices communicate over `mqtts://mqtt.eva.ai:8883` using their X.509 client certificate.

| Topic | Direction | Retained | Description |
|---|---|---|---|
| `eva/v1/d/<id>/state` | Device → Cloud | Yes | Full device state snapshot |
| `eva/v1/d/<id>/event` | Device → Cloud | No | Discrete events (button, wakeword, error) |
| `eva/v1/d/<id>/audio/meta` | Device → Cloud | No | Voice session metadata |
| `eva/v1/d/<id>/cmd` | Cloud → Device | No | Commands from backend |
| `eva/v1/d/<id>/cmd/ack` | Device → Cloud | No | Command acknowledgement |

---

## Error Format

All error responses use a consistent envelope:

```json
{
  "error": {
    "code": "DEVICE_ALREADY_CLAIMED",
    "message": "This device is already claimed by another account.",
    "status": 409,
    "request_id": "req_8f2a1c",
    "details": { "device_id": "eva-7G4K2P" }
  }
}
```

Branch client logic on `code`, not `message`. Error codes are stable across versions.

---

## Rate Limits

| Category | Limit | Window |
|---|---|---|
| Auth endpoints (login, register, refresh) | 10 requests | per minute / IP |
| Read endpoints | 120 requests | per minute / token |
| Write endpoints (claim, command) | 30 requests | per minute / token |
| OTA check | 6 requests | per hour / device |

On a `429` response, honour the `Retry-After` header.

---

## Production Checklist

- [ ] Set strong `SECRET_KEY` and `JWT_SECRET_KEY` in environment
- [ ] Switch `DATABASE_URL` to PostgreSQL
- [ ] Set `REDIS_URL` for distributed rate limiting and token revocation
- [ ] Configure nginx / ALB to terminate mTLS and forward `X-SSL-Client-Fingerprint`
- [ ] Enable HTTPS on all app-facing routes
- [ ] Connect MQTT broker with real device certificates
- [ ] Replace Stripe checkout URL placeholder in `subscriptions.py`
- [ ] Wire `/v1/ota/blob/<version>` to signed S3/GCS URLs instead of direct redirect
- [ ] Plug log ingestion pipeline into `device_api.py` → `upload_logs`

---

## Tech Stack

| Layer | Library |
|---|---|
| Web framework | Flask 3 |
| ORM | Flask-SQLAlchemy |
| Auth | Flask-JWT-Extended |
| WebSocket | Flask-SocketIO + eventlet |
| Rate limiting | Flask-Limiter |
| MQTT publish | paho-mqtt |
| Password hashing | bcrypt |
| Database | SQLite (dev) / PostgreSQL (prod) |

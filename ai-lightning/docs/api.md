# AI Lightning API Documentation

## Base URL
```
http://localhost:5000/api
```

## Authentication

All protected endpoints require a JWT token in the Authorization header:
```
Authorization: Bearer <token>
```

---

## Auth Endpoints

### Register User
```http
POST /api/register
Content-Type: application/json

{
    "username": "string (3-80 chars, alphanumeric + underscore)",
    "password": "string (min 8 chars)"
}
```

**Response:**
```json
{
    "message": "Registered successfully"
}
```

**Errors:**
- `400` - Username already taken / Invalid input

---

### Login
```http
POST /api/login
Content-Type: application/json

{
    "username": "string",
    "password": "string"
}
```

**Response:**
```json
{
    "access_token": "eyJ..."
}
```

**Errors:**
- `401` - Invalid credentials

---

## Session Endpoints

### Create New Session
```http
POST /api/new_session
Authorization: Bearer <token>
Content-Type: application/json

{
    "model": "tiny | base | large",
    "minutes": 1-120
}
```

**Response:**
```json
{
    "invoice": "lnbc...",
    "session_id": 123,
    "amount": 5000,
    "expires_at": "2026-02-01T12:00:00"
}
```

**Errors:**
- `400` - Invalid model / Invalid minutes

---

## Node Endpoints

### Register Node
```http
POST /api/register_node
Authorization: Bearer <token>
Content-Type: application/json

{
    "models": {
        "tiny": {"path": "/models/tiny.gguf"},
        "base": {"path": "/models/base.gguf"}
    }
}
```

**Response:**
```json
{
    "node_id": "node-abc12345",
    "registration_fee": 1000
}
```

**Errors:**
- `400` - Invalid models
- `402` - Insufficient balance

---

### Node Heartbeat
```http
POST /api/node_heartbeat
Content-Type: application/json

{
    "node_id": "node-abc12345",
    "load": 2,
    "models": ["tiny", "base"]
}
```

**Response:**
```json
{
    "status": "ok"
}
```

---

## WebSocket Events

Connect via Socket.IO to the server root.

### Client → Server

#### start_session
```json
{
    "session_id": 123
}
```

#### chat_message
```json
{
    "session_id": 123,
    "prompt": "Hello, AI!",
    "max_tokens": 256,
    "temperature": 0.7
}
```

#### end_session
```json
{
    "session_id": 123
}
```

### Server → Client

#### session_started
```json
{
    "node_id": "node-abc12345",
    "expires_at": "2026-02-01T12:00:00"
}
```

#### ai_response
```json
{
    "response": "Hello! How can I help?",
    "model": "base"
}
```

#### error
```json
{
    "message": "Error description"
}
```

#### session_ended
Emitted when session is terminated.

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/api/register` | 5 req/min |
| `/api/login` | 10 req/min |
| `/api/new_session` | 20 req/min |

**Response when exceeded:**
```json
{
    "error": "Rate limit exceeded",
    "retry_after": 60
}
```
Status: `429 Too Many Requests`

---

## Models & Pricing

| Model | Context | Price/min |
|-------|---------|-----------|
| tiny | 2048 tokens | 500 sats |
| base | 4096 tokens | 1000 sats |
| large | 8192 tokens | 2000 sats |
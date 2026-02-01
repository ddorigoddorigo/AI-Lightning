# Deployment Guide

## Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Redis 7+
- LND (Lightning Network Daemon) or CLN
- llama.cpp (for nodes)

---

## Server Deployment

### 1. Clone & Setup

```bash
git clone https://github.com/your-repo/ai-lightning.git
cd ai-lightning/server
```

### 2. Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

Required variables:
```env
SECRET_KEY=<random-secret-key>
DATABASE_URL=postgresql://user:pass@localhost/ailightning
REDIS_URL=redis://localhost:6379
LND_DIR=/path/to/.lnd
```

### 3. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 4. Initialize Database

```bash
flask init-db
flask create-admin admin your-password
```

### 5. Run (Development)

```bash
flask run --host=0.0.0.0 --port=5000
```

### 6. Run (Production)

```bash
gunicorn --bind 0.0.0.0:5000 \
         --workers 4 \
         --worker-class eventlet \
         --timeout 120 \
         "server.app:app"
```

---

## Docker Deployment

### Using Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  server:
    build: ./docker/server
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db/ailightning
      - REDIS_URL=redis://redis:6379
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - db
      - redis

  db:
    image: postgres:14
    environment:
      - POSTGRES_DB=ailightning
      - POSTGRES_PASSWORD=postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

```bash
docker-compose up -d
```

---

## Node Deployment

### 1. Setup

```bash
cd ai-lightning/node
cp config.ini.example config.ini
# Edit config.ini
```

### 2. Install llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make -j
# or: cmake -B build && cmake --build build --config Release
```

### 3. Download Models

Download GGUF models from HuggingFace:
- TinyLlama: `tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`
- Llama 2 7B: `llama-2-7b-chat.Q4_K_M.gguf`

### 4. Configure

```ini
# config.ini
[Server]
URL = https://your-server.com

[LLM]
bin = /path/to/llama.cpp/build/bin/llama-server

[Model:tiny]
path = /path/to/models/tinyllama.gguf
context = 2048
```

### 5. Run

```bash
python -m node.node_server
```

---

## HTTPS / Reverse Proxy

### Nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name ai.example.com;

    ssl_certificate /etc/letsencrypt/live/ai.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ai.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

---

## Lightning Network Setup

### LND

1. Install LND: https://github.com/lightningnetwork/lnd
2. Sync with Bitcoin node
3. Create wallet and fund channels
4. Set `LND_DIR` in server config

### Core Lightning (CLN)

1. Install CLN: https://github.com/ElementsProject/lightning
2. Configure `pyln-client` settings

---

## Monitoring

### Health Check

```bash
curl http://localhost:5000/api/health
```

### Logs

```bash
# Server logs (JSON format in production)
tail -f /var/log/ailightning/server.log

# Node logs
journalctl -u ailightning-node -f
```

### Systemd Service

```ini
# /etc/systemd/system/ailightning.service
[Unit]
Description=AI Lightning Server
After=network.target postgresql.service redis.service

[Service]
User=ailightning
WorkingDirectory=/opt/ai-lightning/server
Environment=PATH=/opt/ai-lightning/venv/bin
ExecStart=/opt/ai-lightning/venv/bin/gunicorn \
    --bind 127.0.0.1:5000 \
    --workers 4 \
    --worker-class eventlet \
    "server.app:app"
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable ailightning
sudo systemctl start ailightning
```
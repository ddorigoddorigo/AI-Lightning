# Dockerfile per il server
FROM python:3.12-slim

# Installa dipendenze sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Copia applicazione
WORKDIR /app
COPY ../server/ .

# Installa dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir eventlet

# Configurazione
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Esegui con eventlet per supporto WebSocket
CMD ["gunicorn", "--worker-class", "eventlet", "--workers", "1", "--bind", "0.0.0.0:5000", "app:app"]
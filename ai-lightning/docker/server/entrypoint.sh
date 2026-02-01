#!/bin/bash
set -e

echo "AI Lightning Server starting..."

# Wait for database to be ready
echo "Waiting for PostgreSQL..."
while ! nc -z ${DB_HOST:-db} ${DB_PORT:-5432}; do
    sleep 1
done
echo "PostgreSQL is ready!"

# Wait for Redis
echo "Waiting for Redis..."
while ! nc -z ${REDIS_HOST:-redis} ${REDIS_PORT:-6379}; do
    sleep 1
done
echo "Redis is ready!"

# Initialize database if needed
echo "Initializing database..."
flask init-db || true

# Run migrations if using Flask-Migrate
# flask db upgrade || true

# Start the server
echo "Starting Gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:${PORT:-5000} \
    --workers ${WORKERS:-4} \
    --worker-class eventlet \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    "server.app:app"
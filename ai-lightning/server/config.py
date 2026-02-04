"""
Configurazione del server principale.

Questo file contiene tutte le configurazioni dell'applicazione,
caricate da variabili d'ambiente o valori di default.
"""
import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

# Carica variabili d'ambiente da .env
load_dotenv()

class Config:
    # Flask config
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-ChangeMe!'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or os.environ.get('SECRET_KEY') or 'jwt-secret-key-ChangeMe!'
    DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
    PORT = os.environ.get('PORT', '5000')
    
    # Test mode (no real Lightning payments)
    TEST_MODE = os.environ.get('TEST_MODE', 'false')

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql:///ailightning'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Lightning Network
    LND_NETWORK = os.environ.get('LND_NETWORK', 'testnet')  # 'bitcoin' for mainnet
    LND_DIR = os.environ.get('LND_DIR', '/home/ubuntu/.lnd')  # Path assoluto per il server
    LND_REST_HOST = os.environ.get('LND_REST_HOST', 'https://localhost:8080')
    LND_CERT_PATH = os.path.join(LND_DIR, 'tls.cert')
    LND_MACAROON_PATH = os.path.join(LND_DIR, 'data/chain/bitcoin', LND_NETWORK, 'admin.macaroon')

    # LLM Models
    AVAILABLE_MODELS = {
        'tiny': {
            'path': str(Path.home() / 'llama.cpp' / 'models' / '3B' / 'ggml-model-q4_0.bin'),
            'context': 2048,
            'price_per_minute': 500  # satoshis
        },
        'base': {
            'path': str(Path.home() / 'llama.cpp' / 'models' / '7B' / 'ggml-model-q4_0.bin'),
            'context': 4096,
            'price_per_minute': 1000
        },
        'large': {
            'path': str(Path.home() / 'llama.cpp' / 'models' / '13B' / 'ggml-model-q4_0.bin'),
            'context': 8192,
            'price_per_minute': 2000
        }
    }

    # Redis
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')

    # Node management
    NODE_REGISTRATION_FEE = 1000  # satoshis
    NODE_PAYMENT_RATIO = 0.7  # % del pagamento che va al nodo
    MIN_NODE_PAYMENT = 20  # satoshis minimi per sessione

    # Security / JWT
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)  # Token valido 24 ore
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'
    
    # Email configuration
    SMTP_SERVER = os.environ.get('SMTP_SERVER', 'mail.lightphon.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 465))
    SMTP_USER = os.environ.get('SMTP_USER', 'noreply@lightphon.com')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_FROM = os.environ.get('SMTP_FROM', 'noreply@lightphon.com')
    SMTP_USE_SSL = os.environ.get('SMTP_USE_SSL', 'true').lower() == 'true'
    
    # Alert thresholds
    DISK_CRITICAL_PERCENT = int(os.environ.get('DISK_CRITICAL_PERCENT', 90))  # Send email when disk > 90%
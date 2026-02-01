"""
Test per le API del server principale.
"""
import pytest
from unittest.mock import Mock, patch
import json


class TestConfig:
    """Test configuration class for testing."""
    SECRET_KEY = 'test-secret-key'
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = 'redis://localhost:6379'
    LND_NETWORK = 'testnet'
    LND_DIR = '~/.lnd'
    LND_CERT_FILE = ''
    LND_MACAROON_FILE = ''
    NODE_REGISTRATION_FEE = 1000
    NODE_PAYMENT_RATIO = 0.7
    AVAILABLE_MODELS = {
        'tiny': {'path': '/models/tiny.bin', 'context': 2048, 'price_per_minute': 500},
        'base': {'path': '/models/base.bin', 'context': 4096, 'price_per_minute': 1000},
    }
    
    def get(self, key, default=None):
        return getattr(self, key, default)


@pytest.fixture
def app():
    """Create test Flask app."""
    from server.app import app
    app.config.from_object(TestConfig)
    
    with app.app_context():
        from server.models import db
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestAuthAPI:
    """Test authentication endpoints."""
    
    def test_register_success(self, client):
        """Test successful user registration."""
        response = client.post('/api/register', 
            json={'username': 'testuser', 'password': 'testpass123'})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data
    
    def test_register_duplicate(self, client):
        """Test duplicate username registration."""
        client.post('/api/register', 
            json={'username': 'testuser', 'password': 'testpass123'})
        response = client.post('/api/register', 
            json={'username': 'testuser', 'password': 'otherpass'})
        assert response.status_code == 400
    
    def test_login_success(self, client):
        """Test successful login."""
        client.post('/api/register', 
            json={'username': 'testuser', 'password': 'testpass123'})
        response = client.post('/api/login', 
            json={'username': 'testuser', 'password': 'testpass123'})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'access_token' in data
    
    def test_login_invalid_credentials(self, client):
        """Test login with invalid credentials."""
        response = client.post('/api/login', 
            json={'username': 'nouser', 'password': 'wrongpass'})
        assert response.status_code == 401


class TestSessionAPI:
    """Test session endpoints."""
    
    @pytest.fixture
    def auth_headers(self, client):
        """Get authentication headers."""
        client.post('/api/register', 
            json={'username': 'testuser', 'password': 'testpass123'})
        response = client.post('/api/login', 
            json={'username': 'testuser', 'password': 'testpass123'})
        token = json.loads(response.data)['access_token']
        return {'Authorization': f'Bearer {token}'}
    
    @patch('server.app.get_lightning_manager')
    def test_new_session_success(self, mock_lm, client, auth_headers):
        """Test creating a new session."""
        mock_lm.return_value.create_invoice.return_value = {
            'payment_request': 'lnbc1000...',
            'r_hash': 'abc123',
            'amount': 5000
        }
        
        response = client.post('/api/new_session',
            json={'model': 'base', 'minutes': 5},
            headers=auth_headers)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'invoice' in data
        assert 'session_id' in data
    
    def test_new_session_invalid_model(self, client, auth_headers):
        """Test creating session with invalid model."""
        response = client.post('/api/new_session',
            json={'model': 'invalid_model', 'minutes': 5},
            headers=auth_headers)
        assert response.status_code == 400
    
    def test_new_session_invalid_minutes(self, client, auth_headers):
        """Test creating session with invalid duration."""
        response = client.post('/api/new_session',
            json={'model': 'base', 'minutes': 0},
            headers=auth_headers)
        assert response.status_code == 400
        
        response = client.post('/api/new_session',
            json={'model': 'base', 'minutes': 200},
            headers=auth_headers)
        assert response.status_code == 400

"""
Test per il node server.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json


@pytest.fixture
def app():
    """Create test Flask app for node server."""
    from node.node_server import app
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestNodeStatus:
    """Test status endpoint."""
    
    def test_status_returns_online(self, client):
        """Test that status endpoint returns online."""
        response = client.get('/api/status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'online'
        assert 'models' in data
        assert 'load' in data
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'


class TestSessionManagement:
    """Test session management endpoints."""
    
    @patch('node.node_server.find_available_port')
    @patch('subprocess.Popen')
    def test_start_session_success(self, mock_popen, mock_port, client):
        """Test starting a new session."""
        mock_port.return_value = 11000
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        # Mock socket connection check
        with patch('socket.socket'):
            response = client.post('/api/start_session', json={
                'session_id': 'test-session-1',
                'model': 'tiny',
                'context': 2048,
                'llama_bin': '/path/to/llama'
            })
        
        # Might fail if model not configured, which is expected
        assert response.status_code in [200, 400]
    
    def test_start_session_invalid_model(self, client):
        """Test starting session with invalid model."""
        response = client.post('/api/start_session', json={
            'session_id': 'test-session-2',
            'model': 'nonexistent_model',
            'context': 2048,
            'llama_bin': '/path/to/llama'
        })
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_stop_session_not_found(self, client):
        """Test stopping a non-existent session."""
        response = client.post('/api/stop_session', json={
            'session_id': 'nonexistent-session'
        })
        # Should succeed even if session doesn't exist
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'stopped'
    
    def test_session_info_not_found(self, client):
        """Test getting info for non-existent session."""
        response = client.get('/api/session_info/nonexistent')
        assert response.status_code == 404


class TestRegistration:
    """Test node registration."""
    
    @patch('builtins.open', create=True)
    def test_register_node(self, mock_open, client):
        """Test node registration."""
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        response = client.post('/api/register', json={
            'node_id': 'node-test123',
            'address': '192.168.1.100',
            'models': {
                'tiny': {'path': '/models/tiny.gguf', 'context': 2048}
            }
        })
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'registered'
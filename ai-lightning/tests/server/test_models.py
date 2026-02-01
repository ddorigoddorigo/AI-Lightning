"""
Test per i modelli database.
"""
import pytest
from datetime import datetime, timedelta


class TestConfig:
    """Test configuration for testing."""
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture
def app():
    """Create test Flask app."""
    from flask import Flask
    from server.models import db
    
    app = Flask(__name__)
    app.config.from_object(TestConfig)
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def db_session(app):
    """Get database session."""
    from server.models import db
    with app.app_context():
        yield db.session


class TestUserModel:
    """Test User model."""
    
    def test_create_user(self, app, db_session):
        """Test creating a new user."""
        from server.models import User
        
        with app.app_context():
            user = User(username='testuser')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()
            
            assert user.id is not None
            assert user.username == 'testuser'
            assert user.balance == 0
            assert user.is_admin == False
    
    def test_password_hashing(self, app, db_session):
        """Test password is hashed correctly."""
        from server.models import User
        
        with app.app_context():
            user = User(username='testuser2')
            user.set_password('mypassword')
            
            assert user.password_hash != 'mypassword'
            assert user.check_password('mypassword') == True
            assert user.check_password('wrongpassword') == False
    
    def test_user_repr(self, app, db_session):
        """Test user string representation."""
        from server.models import User
        
        with app.app_context():
            user = User(username='testuser3')
            assert 'testuser3' in repr(user)


class TestSessionModel:
    """Test Session model."""
    
    def test_create_session(self, app, db_session):
        """Test creating a new session."""
        from server.models import User, Session
        
        with app.app_context():
            # Create user first
            user = User(username='sessionuser')
            user.set_password('pass')
            db_session.add(user)
            db_session.commit()
            
            # Create session
            session = Session(
                user_id=user.id,
                node_id='node-123',
                model='base',
                payment_hash='abc123',
                expires_at=datetime.utcnow() + timedelta(minutes=5)
            )
            db_session.add(session)
            db_session.commit()
            
            assert session.id is not None
            assert session.active == True
    
    def test_session_expired(self, app, db_session):
        """Test session expiration check."""
        from server.models import User, Session
        
        with app.app_context():
            user = User(username='expireuser')
            user.set_password('pass')
            db_session.add(user)
            db_session.commit()
            
            # Create expired session
            session = Session(
                user_id=user.id,
                node_id='node-123',
                model='base',
                payment_hash='def456',
                expires_at=datetime.utcnow() - timedelta(minutes=5)
            )
            db_session.add(session)
            db_session.commit()
            
            assert session.expired == True
    
    def test_session_not_expired(self, app, db_session):
        """Test session not expired."""
        from server.models import User, Session
        
        with app.app_context():
            user = User(username='activeuser')
            user.set_password('pass')
            db_session.add(user)
            db_session.commit()
            
            session = Session(
                user_id=user.id,
                node_id='node-123',
                model='base',
                payment_hash='ghi789',
                expires_at=datetime.utcnow() + timedelta(minutes=30)
            )
            db_session.add(session)
            db_session.commit()
            
            assert session.expired == False


class TestTransactionModel:
    """Test Transaction model."""
    
    def test_create_transaction(self, app, db_session):
        """Test creating a transaction."""
        from server.models import User, Transaction
        
        with app.app_context():
            user = User(username='txuser')
            user.set_password('pass')
            db_session.add(user)
            db_session.commit()
            
            tx = Transaction(
                type='deposit',
                user_id=user.id,
                amount=10000,
                description='Test deposit'
            )
            db_session.add(tx)
            db_session.commit()
            
            assert tx.id is not None
            assert tx.amount == 10000
            assert tx.type == 'deposit'
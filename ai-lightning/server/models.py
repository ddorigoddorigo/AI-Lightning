"""
Database models for the main server.

Uses SQLAlchemy for PostgreSQL interaction.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    """System user."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)  # Required email
    password_hash = db.Column(db.String(256), nullable=False)  # Increased for scrypt hash
    balance = db.Column(db.Integer, default=0)  # Balance in satoshis
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), nullable=True)
    verification_token_expires = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        """Set the hashed password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify the password."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Session(db.Model):
    """Active chat session."""
    __tablename__ = 'sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    node_id = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(256), nullable=False)  # Increased to support HuggingFace repo names
    payment_hash = db.Column(db.String(64), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=True)  # Amount in satoshis
    expires_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)  # When node confirmed session ready
    ended_at = db.Column(db.DateTime, nullable=True)  # When session ended
    refunded = db.Column(db.Boolean, default=False)  # True if user was refunded
    refund_amount = db.Column(db.Integer, default=0)  # Amount refunded in satoshis
    context_length = db.Column(db.Integer, default=4096)  # Context length for the model

    user = db.relationship('User', backref='sessions')

    @property
    def expired(self):
        """True if session is expired."""
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f'<Session {self.id} for {self.user.username}>'

class Node(db.Model):
    """Registered host node."""
    __tablename__ = 'nodes'

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    address = db.Column(db.String(45), nullable=False)
    models = db.Column(db.JSON, nullable=False)  # Dict of offered models
    payment_address = db.Column(db.String(256), nullable=True)  # Lightning address (LNURL, BOLT12, or node pubkey)
    online = db.Column(db.Boolean, default=True)
    last_ping = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_earned = db.Column(db.Integer, default=0)  # Total satoshis earned

    owner = db.relationship('User', backref='owned_nodes')

    def __repr__(self):
        return f'<Node {self.id} at {self.address}>'


class NodeStats(db.Model):
    """Host node statistics."""
    __tablename__ = 'node_stats'

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.String(64), db.ForeignKey('nodes.id'), nullable=False, unique=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Owner user
    
    # Session counters
    total_sessions = db.Column(db.Integer, default=0)
    completed_sessions = db.Column(db.Integer, default=0)
    failed_sessions = db.Column(db.Integer, default=0)
    
    # Usage counters
    total_requests = db.Column(db.Integer, default=0)  # Number of inference requests
    total_tokens_generated = db.Column(db.Integer, default=0)
    total_minutes_active = db.Column(db.Float, default=0.0)  # Total minutes of activity
    
    # Earnings
    total_earned_sats = db.Column(db.Integer, default=0)
    
    # Performance
    avg_tokens_per_second = db.Column(db.Float, default=0.0)
    avg_response_time_ms = db.Column(db.Float, default=0.0)
    
    # Uptime
    first_online = db.Column(db.DateTime, default=datetime.utcnow)
    last_online = db.Column(db.DateTime, default=datetime.utcnow)
    total_uptime_hours = db.Column(db.Float, default=0.0)
    
    # Timestamps
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node = db.relationship('Node', backref=db.backref('stats', uselist=False))
    owner = db.relationship('User', backref=db.backref('owned_node_stats', lazy='dynamic'))

    def to_dict(self):
        """Convert to dictionary for API."""
        return {
            'node_id': self.node_id,
            'owner_user_id': self.owner_user_id,
            'total_sessions': self.total_sessions,
            'completed_sessions': self.completed_sessions,
            'failed_sessions': self.failed_sessions,
            'total_requests': self.total_requests,
            'total_tokens_generated': self.total_tokens_generated,
            'total_minutes_active': round(self.total_minutes_active, 2),
            'total_earned_sats': self.total_earned_sats,
            'avg_tokens_per_second': round(self.avg_tokens_per_second, 2),
            'avg_response_time_ms': round(self.avg_response_time_ms, 2),
            'first_online': self.first_online.isoformat() if self.first_online else None,
            'last_online': self.last_online.isoformat() if self.last_online else None,
            'total_uptime_hours': round(self.total_uptime_hours, 2),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Transaction(db.Model):
    """Financial transaction."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # 'deposit', 'withdrawal', 'session_payment', 'node_earning', 'commission'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # In satoshis (positivo = entrata, negativo = uscita)
    fee = db.Column(db.Integer, default=0)  # Commissione applicata
    balance_after = db.Column(db.Integer, default=0)  # Saldo dopo transazione
    payment_hash = db.Column(db.String(64), nullable=True)  # Hash pagamento Lightning
    status = db.Column(db.String(20), default='pending')  # 'pending', 'completed', 'failed', 'expired'
    description = db.Column(db.String(200))
    reference_id = db.Column(db.String(64), nullable=True)  # ID sessione o altro riferimento
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='transactions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type or 'unknown',
            'amount': self.amount or 0,
            'fee': self.fee or 0,
            'balance_after': self.balance_after or 0,
            'status': self.status or 'completed',
            'description': self.description or '',
            'created_at': (self.created_at.isoformat() + 'Z') if self.created_at else None,
            'completed_at': (self.completed_at.isoformat() + 'Z') if self.completed_at else None
        }


class DepositInvoice(db.Model):
    """Invoice for wallet deposit."""
    __tablename__ = 'deposit_invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    payment_hash = db.Column(db.String(64), unique=True, nullable=False)
    payment_request = db.Column(db.Text, nullable=False)  # Invoice BOLT11
    amount = db.Column(db.Integer, nullable=False)  # Satoshis
    status = db.Column(db.String(20), default='pending')  # 'pending', 'paid', 'expired'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='deposit_invoices')


class PlatformStats(db.Model):
    """Statistiche della piattaforma (singleton)."""
    __tablename__ = 'platform_stats'
    
    id = db.Column(db.Integer, primary_key=True, default=1)
    total_commissions = db.Column(db.Integer, default=0)  # Commissioni totali raccolte
    total_sessions = db.Column(db.Integer, default=0)
    total_users = db.Column(db.Integer, default=0)
    total_nodes = db.Column(db.Integer, default=0)
    total_volume = db.Column(db.Integer, default=0)  # Volume totale transazioni
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
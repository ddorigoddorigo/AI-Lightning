"""
Modelli database per il server principale.

Usa SQLAlchemy per l'interazione con PostgreSQL.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    """Utente del sistema."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    balance = db.Column(db.Integer, default=0)  # Saldo in satoshis
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        """Imposta la password hashata."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica la password."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Session(db.Model):
    """Sessione di chat attiva."""
    __tablename__ = 'sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    node_id = db.Column(db.String(64), nullable=False)
    model = db.Column(db.String(20), nullable=False)
    payment_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='sessions')

    @property
    def expired(self):
        """True se la sessione è scaduta."""
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f'<Session {self.id} for {self.user.username}>'

class Node(db.Model):
    """Nodo host registrato."""
    __tablename__ = 'nodes'

    id = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    address = db.Column(db.String(45), nullable=False)
    models = db.Column(db.JSON, nullable=False)  # Dict di modelli offerti
    online = db.Column(db.Boolean, default=True)
    last_ping = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', backref='owned_nodes')

    def __repr__(self):
        return f'<Node {self.id} at {self.address}>'

class Transaction(db.Model):
    """Transazione finanziaria."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # 'deposit', 'withdrawal', 'fee', 'payment'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # In satoshis
    description = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')
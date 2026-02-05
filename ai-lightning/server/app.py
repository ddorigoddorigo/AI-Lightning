"""
Main Flask Application.

Handles authentication, API, WebSocket and business logic.
"""
from functools import wraps
from flask import Flask, render_template, request, jsonify, current_app
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity,
    decode_token
)
from config import Config
from models import db, User, Session, Node, Transaction, DepositInvoice, PlatformStats
from lightning import LightningManager
from nodemanager import NodeManager
from utils.helpers import validate_model, get_model_price
from utils.decorators import rate_limit, validate_json, validate_model_param
from datetime import datetime, timedelta
import httpx
import click
import logging
import json

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure paths for templates and static files
import os
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(base_dir, 'web-client')
static_dir = os.path.join(base_dir, 'web-client')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir, static_url_path='')
app.config.from_object(Config)
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
jwt = JWTManager(app)

# JWT Error handlers
@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Token expired', 'code': 'token_expired'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(error):
    return jsonify({'error': 'Invalid token', 'code': 'token_invalid'}), 401

@jwt.unauthorized_loader
def missing_token_callback(error):
    return jsonify({'error': 'Authorization required', 'code': 'token_missing'}), 401

# Lazy initialization - will be set up in app context
lm = None
node_manager = None

# Socket user tracking
socket_users = {}  # sid -> user_id

def get_socket_user_id():
    """Get user ID from socket connection."""
    sid = request.sid
    return socket_users.get(sid)

def get_lightning_manager():
    """Get or create LightningManager instance."""
    global lm
    if lm is None:
        lm = LightningManager(app.config)
    return lm

def get_node_manager():
    """Get or create NodeManager instance."""
    global node_manager
    if node_manager is None:
        node_manager = NodeManager(app.config)
    return node_manager

def validate_model_list(models):
    """Validate that all models in the list are valid."""
    if not models or not isinstance(models, dict):
        return False
    for name, info in models.items():
        if not isinstance(info, dict):
            return False
        if 'path' not in info:
            return False
    return True

@app.route('/')
def index():
    """Main page (web client)."""
    return render_template('index.html')

# ============================================
# Auto-Update API
# ============================================

# Current node-client version
NODE_CLIENT_VERSION = "1.0.0"
NODE_CLIENT_CHANGELOG = """
## v1.0.0 (2026-02-04)
- Initial release
- HuggingFace model support
- Disk space monitoring
- Auto-update functionality
"""

@app.route('/api/version', methods=['GET'])
def get_version():
    """
    Return current node-client version info for auto-update.
    The download_url should point to the latest compiled .exe
    """
    # Base URL for downloads (GitHub releases or server)
    base_url = request.host_url.rstrip('/')
    
    return jsonify({
        'version': NODE_CLIENT_VERSION,
        'changelog': NODE_CLIENT_CHANGELOG.strip(),
        'download_url': f'{base_url}/static/releases/LightPhon-Node-{NODE_CLIENT_VERSION}.exe',
        'checksum': None,  # SHA256 checksum (optional, set after build)
        'release_date': '2026-02-04',
        'min_version': '0.9.0'  # Minimum version required (for forced updates)
    })

# Auth routes
@app.route('/api/register', methods=['POST'])
@rate_limit(max_requests=5, window_seconds=60)  # 5 registrations/minute per IP
@validate_json('username', 'password')
def register():
    """User registration."""
    data = request.get_json()
    
    # Input validation
    username = data['username'].strip()
    password = data['password']
    email = data.get('email', '').strip() or None  # Optional email
    
    if len(username) < 3 or len(username) > 80:
        return jsonify({'error': 'Username must be 3-80 characters'}), 400
    
    if not username.replace('_', '').isalnum():
        return jsonify({'error': 'Username can only contain letters, numbers and underscores'}), 400
    
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 400
    
    # Verify email if provided
    if email and User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 400

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'Registered successfully'}), 201

@app.route('/api/login', methods=['POST'])
@rate_limit(max_requests=10, window_seconds=60)  # 10 logins/minute per IP
@validate_json('username', 'password')
def login():
    """User login."""
    data = request.get_json()
    user = User.query.filter_by(username=data['username'].strip()).first()
    if not user or not user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401

    access_token = create_access_token(identity=str(user.id))
    logger.info(f"User {user.username} logged in, token created for id={user.id}")
    return jsonify({
        'token': access_token,
        'access_token': access_token,  # For compatibility
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'balance': user.balance,
        'is_admin': user.is_admin
    })


@app.route('/api/me', methods=['GET'])
@jwt_required()
def get_user_profile():
    """Returns information about the current user including balance."""
    user_id = get_jwt_identity()
    logger.info(f"/api/me called with identity: {user_id} (type: {type(user_id).__name__})")
    
    # Convert to int if necessary
    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        logger.error(f"Invalid user_id format: {user_id}")
        return jsonify({'error': 'Invalid token identity'}), 401
    
    user = User.query.get(user_id_int)
    
    if not user:
        logger.error(f"User not found for id: {user_id_int}")
        return jsonify({'error': 'User not found'}), 404
    
    logger.info(f"Profile loaded for user: {user.username}")
    
    # Count active sessions
    active_sessions = Session.query.filter_by(
        user_id=user_id_int, 
        active=True
    ).filter(Session.expires_at > datetime.utcnow()).count()
    
    return jsonify({
        'id': user.id,
        'username': user.username,
        'balance': user.balance,
        'balance_btc': user.balance / 100_000_000,
        'is_admin': user.is_admin,
        'active_sessions': active_sessions,
        'created_at': (user.created_at.isoformat() + 'Z') if user.created_at else None
    })


@app.route('/api/add_test_balance', methods=['POST'])
@jwt_required()
def add_test_balance():
    """
    Add test balance (only for development/testnet).
    In production this endpoint should be disabled or protected.
    """
    try:
        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        amount = data.get('amount', 10000)  # Default 10000 sats
        
        # Limit to prevent abuse
        if amount > 1000000:  # Max 1M sats per request
            amount = 1000000
        
        user.balance += amount
        db.session.commit()
        
        logger.info(f"Added {amount} sats to user {user.username} (new balance: {user.balance})")
        
        return jsonify({
            'message': f'Added {amount} sats to your balance',
            'new_balance': user.balance
        })
    except Exception as e:
        logger.error(f"Error adding test balance: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ============================================
# Wallet API
# ============================================

PLATFORM_COMMISSION_RATE = 0.10  # 10% commission

@app.route('/api/wallet/balance', methods=['GET'])
@jwt_required()
def get_wallet_balance():
    """Returns user wallet balance."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'balance_sats': user.balance,
        'balance_btc': user.balance / 100_000_000,
        'balance_usd': user.balance * 0.0004  # Approximate, update with real rate
    })


@app.route('/api/wallet/deposit', methods=['POST'])
@jwt_required()
@rate_limit(max_requests=10, window_seconds=60)
def create_deposit_invoice():
    """Create an invoice to deposit funds into wallet."""
    try:
        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        amount = data.get('amount', 10000)  # Default 10000 sats
        
        # Validation
        if amount < 1000:
            return jsonify({'error': 'Minimum deposit is 1000 sats'}), 400
        if amount > 10_000_000:
            return jsonify({'error': 'Maximum deposit is 10,000,000 sats'}), 400
        
        # Create Lightning invoice
        invoice = get_lightning_manager().create_invoice(
            amount,
            f"Deposit to LightPhon wallet for {user.username}"
        )
        
        # Save to database
        from models import DepositInvoice
        deposit = DepositInvoice(
            user_id=user.id,
            payment_hash=invoice['r_hash'],
            payment_request=invoice['payment_request'],
            amount=amount,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.session.add(deposit)
        db.session.commit()
        
        logger.info(f"Deposit invoice created: {amount} sats for user {user.username}")
        
        return jsonify({
            'invoice': invoice['payment_request'],
            'payment_hash': invoice['r_hash'],
            'amount': amount,
            'expires_at': deposit.expires_at.isoformat() + 'Z'
        })
        
    except Exception as e:
        logger.error(f"Error creating deposit invoice: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to create invoice'}), 500


@app.route('/api/wallet/deposit/check/<payment_hash>', methods=['GET'])
@jwt_required()
def check_deposit_status(payment_hash):
    """Check deposit status."""
    try:
        user_id = get_jwt_identity()
        
        from models import DepositInvoice, Transaction
        deposit = DepositInvoice.query.filter_by(
            payment_hash=payment_hash,
            user_id=int(user_id)
        ).first()
        
        if not deposit:
            return jsonify({'error': 'Deposit not found'}), 404
        
        # If already paid
        if deposit.status == 'paid':
            return jsonify({'status': 'paid', 'amount': deposit.amount})
        
        # Check payment
        if get_lightning_manager().check_payment(deposit.payment_hash):
            # Update deposit
            deposit.status = 'paid'
            deposit.paid_at = datetime.utcnow()
            
            # Add to user balance
            user = User.query.get(int(user_id))
            old_balance = user.balance
            user.balance += deposit.amount
            
            # Record transaction
            tx = Transaction(
                type='deposit',
                user_id=user.id,
                amount=deposit.amount,
                balance_after=user.balance,
                payment_hash=deposit.payment_hash,
                status='completed',
                description=f'Deposit of {deposit.amount} sats',
                completed_at=datetime.utcnow()
            )
            db.session.add(tx)
            db.session.commit()
            
            logger.info(f"Deposit completed: {deposit.amount} sats for user {user.username}")
            
            return jsonify({
                'status': 'paid',
                'amount': deposit.amount,
                'new_balance': user.balance
            })
        
        # Check if expired
        if datetime.utcnow() > deposit.expires_at:
            deposit.status = 'expired'
            db.session.commit()
            return jsonify({'status': 'expired'})
        
        return jsonify({'status': 'pending'})
        
    except Exception as e:
        logger.error(f"Error checking deposit: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallet/transactions', methods=['GET'])
@jwt_required()
def get_wallet_transactions():
    """Returns user transaction history."""
    try:
        user_id = get_jwt_identity()
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        per_page = min(per_page, 100)  # Max 100 per page
        
        from models import Transaction
        transactions = Transaction.query.filter_by(user_id=int(user_id))\
            .order_by(Transaction.created_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'transactions': [tx.to_dict() for tx in transactions.items],
            'total': transactions.total,
            'pages': transactions.pages,
            'current_page': page
        })
        
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallet/withdraw', methods=['POST'])
@jwt_required()
@rate_limit(max_requests=5, window_seconds=60)
def withdraw_to_lightning():
    """Withdraw funds from wallet to a Lightning invoice."""
    try:
        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        invoice = data.get('invoice', '').strip()
        
        if not invoice:
            return jsonify({'error': 'Lightning invoice required'}), 400
        
        # Validate invoice format (basic check)
        if not invoice.lower().startswith('ln'):
            return jsonify({'error': 'Invalid Lightning invoice format'}), 400
        
        # Decode invoice to get amount
        lm = get_lightning_manager()
        
        try:
            decoded = lm.decode_invoice(invoice)
            amount = decoded.get('num_satoshis') or decoded.get('amount')
            if amount:
                amount = int(amount)
            else:
                return jsonify({'error': 'Could not decode invoice amount'}), 400
        except Exception as e:
            logger.error(f"Error decoding invoice: {e}")
            return jsonify({'error': 'Failed to decode invoice'}), 400
        
        # Validation
        if amount < 1000:
            return jsonify({'error': 'Minimum withdrawal is 1000 sats'}), 400
        
        # Check balance (include small fee buffer for routing)
        routing_fee_buffer = max(10, int(amount * 0.01))  # 1% or min 10 sats
        total_needed = amount + routing_fee_buffer
        
        if user.balance < amount:
            return jsonify({
                'error': 'Insufficient balance',
                'required': amount,
                'available': user.balance
            }), 400
        
        # Pay the invoice
        result = lm.pay_invoice(invoice)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Payment failed')
            logger.error(f"Withdrawal failed for user {user_id}: {error_msg}")
            return jsonify({'error': f'Payment failed: {error_msg}'}), 400
        
        # Deduct from balance
        user.balance -= amount
        
        # Record transaction
        from models import Transaction
        tx = Transaction(
            type='withdrawal',
            user_id=user.id,
            amount=-amount,
            fee=0,
            balance_after=user.balance,
            status='completed',
            description=f'Withdrawal to Lightning invoice',
            reference_id=result.get('preimage', '')[:64] if result.get('preimage') else None,
            completed_at=datetime.utcnow()
        )
        db.session.add(tx)
        db.session.commit()
        
        logger.info(f"Withdrawal completed: {amount} sats for user {user.username}")
        
        return jsonify({
            'success': True,
            'amount': amount,
            'new_balance': user.balance,
            'preimage': result.get('preimage', '')
        })
        
    except Exception as e:
        logger.error(f"Error processing withdrawal: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/wallet/pay_session', methods=['POST'])
@jwt_required()
def pay_session_from_wallet():
    """Pay a session from wallet balance instead of external invoice."""
    try:
        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        session_id = data.get('session_id')
        
        session = Session.query.get(session_id)
        if not session or session.user_id != user.id:
            return jsonify({'error': 'Session not found'}), 404
        
        if session.node_id != 'pending':
            return jsonify({'error': 'Session already paid'}), 400
        
        # Use amount saved in session
        original_amount = session.amount
        if not original_amount:
            # Fallback to lightning manager (for old sessions)
            original_amount = get_lightning_manager().get_invoice_amount(session.payment_hash)
        if not original_amount:
            return jsonify({'error': 'Could not determine session cost'}), 400
        
        # Verify balance
        if user.balance < original_amount:
            return jsonify({
                'error': 'Insufficient balance',
                'required': original_amount,
                'available': user.balance
            }), 400
        
        # Calculate commission (10%)
        commission = int(original_amount * PLATFORM_COMMISSION_RATE)
        node_payment = original_amount - commission
        
        # Deduct from balance
        user.balance -= original_amount
        
        # Record transaction
        from models import Transaction, PlatformStats
        tx = Transaction(
            type='session_payment',
            user_id=user.id,
            amount=-original_amount,
            fee=commission,
            balance_after=user.balance,
            status='completed',
            description=f'Payment for session {session_id} ({session.model})',
            reference_id=str(session_id),
            completed_at=datetime.utcnow()
        )
        db.session.add(tx)
        
        # Update platform stats
        stats = PlatformStats.query.get(1)
        if not stats:
            stats = PlatformStats(id=1)
            db.session.add(stats)
        stats.total_commissions += commission
        stats.total_volume += original_amount
        
        db.session.commit()
        
        logger.info(f"Session {session_id} paid from wallet: {original_amount} sats (commission: {commission})")
        
        return jsonify({
            'success': True,
            'amount_paid': original_amount,
            'commission': commission,
            'new_balance': user.balance
        })
        
    except Exception as e:
        logger.error(f"Error paying session from wallet: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<int:session_id>/status', methods=['GET'])
@jwt_required()
def get_session_status(session_id):
    """Get session status for restoring UI after page refresh."""
    try:
        user_id = get_jwt_identity()
        
        session = Session.query.get(session_id)
        if not session or session.user_id != int(user_id):
            return jsonify({'error': 'Session not found'}), 404
        
        return jsonify({
            'session_id': session.id,
            'model': session.model,
            'node_id': session.node_id,
            'active': session.active,
            'expires_at': session.expires_at.isoformat() + 'Z' if session.expires_at else None,
            'expired': session.expired if hasattr(session, 'expired') else False
        })
        
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/<int:session_id>/check_payment', methods=['GET'])
@jwt_required()
def check_session_payment(session_id):
    """Check if Lightning payment for a session has been received."""
    try:
        user_id = get_jwt_identity()
        user = User.query.get(int(user_id))
        
        session = Session.query.get(session_id)
        if not session or session.user_id != int(user_id):
            return jsonify({'error': 'Session not found'}), 404
        
        # If already marked as wallet paid, return immediately
        if session.payment_hash and session.payment_hash.startswith('WALLET_PAID'):
            logger.info(f"Session {session_id} already marked as WALLET_PAID")
            return jsonify({'paid': True})
        
        # If already assigned to a node, it's already paid
        if session.node_id and session.node_id != 'pending':
            return jsonify({'paid': True})
        
        # Get session amount
        session_amount = session.amount or 0
        
        logger.info(f"check_payment: session {session_id}, amount={session_amount}, user.balance={user.balance if user else 'None'}")
        
        # Auto-pay from wallet if user has sufficient balance
        if user and user.balance >= session_amount and session_amount > 0:
            # Auto-pay from wallet
            logger.info(f"Auto-paying session {session_id} from wallet: {session_amount} sats")
            
            # Calculate commission (10%)
            commission = int(session_amount * 0.1)  # PLATFORM_COMMISSION_RATE
            node_payment = session_amount - commission
            
            # Deduct from balance
            user.balance -= session_amount
            
            # Record transaction
            from models import Transaction, PlatformStats
            tx = Transaction(
                type='session_payment',
                user_id=user.id,
                amount=-session_amount,
                fee=commission,
                balance_after=user.balance,
                status='completed',
                description=f'Auto-payment for session {session_id} ({session.model})',
                reference_id=str(session_id),
                completed_at=datetime.utcnow()
            )
            db.session.add(tx)
            
            # Update platform stats
            stats = PlatformStats.query.get(1)
            if not stats:
                stats = PlatformStats(id=1)
                db.session.add(stats)
            stats.total_commissions += commission
            stats.total_volume += session_amount
            
            # Mark session as paid from wallet (use unique value to avoid constraint violation)
            session.payment_hash = f'WALLET_PAID_{session_id}'
            
            db.session.commit()
            
            logger.info(f"Session {session_id} auto-paid from wallet: {session_amount} sats")
            return jsonify({'paid': True, 'auto_paid': True, 'new_balance': user.balance})
        
        # If no wallet balance, check Lightning payment
        payment_verified = get_lightning_manager().check_payment(session.payment_hash)
        
        if payment_verified:
            logger.info(f"Lightning payment verified for session {session_id}")
            return jsonify({'paid': True})
        
        return jsonify({'paid': False})
        
    except Exception as e:
        logger.error(f"Error checking session payment: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================
# Admin API
# ============================================

def admin_required():
    """Decorator to verify user is admin."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = get_jwt_identity()
            user = User.query.get(int(user_id))
            if not user or not user.is_admin:
                return jsonify({'error': 'Admin access required'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route('/api/admin/stats', methods=['GET'])
@jwt_required()
def get_admin_stats():
    """Platform statistics (admin only)."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    logger.info(f"Admin stats requested by user {user_id}, is_admin: {user.is_admin if user else 'None'}")
    
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from models import PlatformStats, Transaction
        
        # Try to get or create platform stats
        try:
            stats = PlatformStats.query.get(1)
            if not stats:
                stats = PlatformStats(id=1)
                db.session.add(stats)
                db.session.commit()
                logger.info("Created new PlatformStats record")
        except Exception as e:
            logger.error(f"Error getting PlatformStats: {e}")
            # If table doesn't exist, use defaults
            stats = None
        
        total_commissions = stats.total_commissions if stats else 0
        total_volume = stats.total_volume if stats else 0
        
        # Calculate real-time statistics
        total_users = User.query.count()
        total_nodes = Node.query.count()
        online_nodes = len(connected_nodes)
        active_sessions = Session.query.filter(
            Session.active == True,
            Session.expires_at > datetime.utcnow()
        ).count()
        
        # Volume ultimi 30 giorni
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        try:
            recent_volume = db.session.query(db.func.sum(Transaction.amount))\
                .filter(Transaction.type == 'session_payment')\
                .filter(Transaction.created_at > thirty_days_ago)\
                .scalar() or 0
        except Exception as e:
            logger.error(f"Error calculating recent volume: {e}")
            recent_volume = 0
        
        result = {
            'total_commissions': total_commissions,
            'total_commissions_btc': total_commissions / 100_000_000,
            'total_volume': total_volume,
            'total_users': total_users,
            'total_nodes': total_nodes,
            'online_nodes': online_nodes,
            'active_sessions': active_sessions,
            'volume_30d': abs(recent_volume)
        }
        
        logger.info(f"Admin stats: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users', methods=['GET'])
@jwt_required()
def get_admin_users():
    """User list (admin only)."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        users = User.query.order_by(User.created_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'users': [{
                'id': u.id,
                'username': u.username,
                'balance': u.balance,
                'is_admin': u.is_admin,
                'created_at': (u.created_at.isoformat() + 'Z') if u.created_at else None,
                'sessions_count': Session.query.filter_by(user_id=u.id).count()
            } for u in users.items],
            'total': users.total,
            'pages': users.pages
        })
        
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/transactions', methods=['GET'])
@jwt_required()
def get_admin_transactions():
    """All transactions (admin only)."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from models import Transaction
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        tx_type = request.args.get('type')  # Filter by type
        
        query = Transaction.query
        if tx_type:
            query = query.filter_by(type=tx_type)
        
        transactions = query.order_by(Transaction.created_at.desc())\
            .paginate(page=page, per_page=per_page, error_out=False)
        
        return jsonify({
            'transactions': [{
                **tx.to_dict(),
                'username': User.query.get(tx.user_id).username if User.query.get(tx.user_id) else 'Unknown'
            } for tx in transactions.items],
            'total': transactions.total,
            'pages': transactions.pages
        })
        
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/commissions', methods=['GET'])
@jwt_required()
def get_admin_commissions():
    """Commission report (admin only)."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from models import Transaction
        
        # Commissions per day (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        commissions = db.session.query(
            db.func.date(Transaction.created_at).label('date'),
            db.func.sum(Transaction.fee).label('total_fee'),
            db.func.count(Transaction.id).label('count')
        ).filter(
            Transaction.type == 'session_payment',
            Transaction.created_at > thirty_days_ago
        ).group_by(db.func.date(Transaction.created_at))\
         .order_by(db.func.date(Transaction.created_at).desc())\
         .all()
        
        return jsonify({
            'daily_commissions': [{
                'date': str(c.date),
                'total_fee': c.total_fee or 0,
                'transactions_count': c.count
            } for c in commissions],
            'total_30d': sum(c.total_fee or 0 for c in commissions)
        })
        
    except Exception as e:
        logger.error(f"Error getting commissions: {e}")
        return jsonify({'error': str(e)}), 500


def get_busy_node_ids():
    """
    Returns the set of node IDs that are currently in use (with active sessions).
    A node is considered "in use" if it has at least one active non-expired session.
    """
    busy_nodes = set()
    
    # Query for active sessions
    active_sessions = Session.query.filter(
        Session.active == True,
        Session.node_id != None,
        Session.node_id != 'pending',
        Session.expires_at > datetime.utcnow()
    ).all()
    
    for session in active_sessions:
        busy_nodes.add(session.node_id)
    
    return busy_nodes


def get_busy_nodes_info():
    """
    Returns a dictionary with info about busy nodes, including remaining time.
    Returns: {node_id: {'expires_at': datetime, 'seconds_remaining': int, 'model': str}}
    """
    busy_info = {}
    
    # Query for active sessions
    active_sessions = Session.query.filter(
        Session.active == True,
        Session.node_id != None,
        Session.node_id != 'pending',
        Session.expires_at > datetime.utcnow()
    ).all()
    
    now = datetime.utcnow()
    for session in active_sessions:
        seconds_remaining = int((session.expires_at - now).total_seconds())
        busy_info[session.node_id] = {
            'expires_at': session.expires_at.isoformat() + 'Z',
            'seconds_remaining': max(0, seconds_remaining),
            'model': session.model
        }
    
    return busy_info


@app.route('/api/models/available', methods=['GET'])
def get_available_models():
    """
    Returns aggregated list of all available models from online nodes.
    Includes both available models and those on busy nodes (with timer).
    Does not require authentication.
    """
    available_models = {}  # model_id -> model_info for available models
    busy_models = {}  # model_id -> model_info for models on busy nodes
    
    # Get info about busy nodes (with remaining time)
    busy_nodes_info = get_busy_nodes_info()
    busy_node_ids = set(busy_nodes_info.keys())
    available_nodes_count = 0
    
    # Collect models from ALL connected WebSocket nodes
    for node_id, info in connected_nodes.items():
        is_busy = node_id in busy_node_ids
        
        if not is_busy:
            available_nodes_count += 1
            
        node_models = info.get('models', [])
        hardware = info.get('hardware', {})
        node_name = info.get('name', node_id)
        
        # Choose which dictionary to use
        target_map = busy_models if is_busy else available_models
        
        for model in node_models:
            if isinstance(model, dict):
                # New format with complete info
                model_id = model.get('id', model.get('name', 'unknown'))
                
                # For display name, use hf_repo or filename to show full GGUF name
                display_name = model.get('hf_repo') or model.get('filename') or model.get('name', model_id)
                
                if model_id not in target_map:
                    target_map[model_id] = {
                        'id': model_id,
                        'name': display_name,
                        'parameters': model.get('parameters', 'Unknown'),
                        'quantization': model.get('quantization', 'Unknown'),
                        'context_length': model.get('context_length', 100000),
                        'architecture': model.get('architecture', 'unknown'),
                        'size_gb': model.get('size_gb', 0),
                        'min_vram_mb': model.get('min_vram_mb', 0),
                        'available': not is_busy,
                        'nodes_count': 0,
                        'nodes': [],
                        'hf_repo': model.get('hf_repo'),
                        'is_huggingface': model.get('is_huggingface', False)
                    }
                
                target_map[model_id]['nodes_count'] += 1
                node_info = {
                    'node_id': node_id,
                    'node_name': node_name,
                    'vram_available': hardware.get('total_vram_mb', 0)
                }
                
                # Add timer info if busy
                if is_busy and node_id in busy_nodes_info:
                    node_info['busy'] = True
                    node_info['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    node_info['expires_at'] = busy_nodes_info[node_id]['expires_at']
                    # Also add to model itself for easy access
                    target_map[model_id]['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    target_map[model_id]['expires_at'] = busy_nodes_info[node_id]['expires_at']
                
                target_map[model_id]['nodes'].append(node_info)
            else:
                # Old format - model name only
                model_name = str(model)
                if model_name not in target_map:
                    target_map[model_name] = {
                        'id': model_name,
                        'name': model_name,
                        'parameters': 'Unknown',
                        'quantization': 'Unknown',
                        'context_length': 100000,
                        'architecture': 'unknown',
                        'available': not is_busy,
                        'nodes_count': 0,
                        'nodes': []
                    }
                
                target_map[model_name]['nodes_count'] += 1
                node_info = {'node_id': node_id, 'node_name': node_name}
                
                if is_busy and node_id in busy_nodes_info:
                    node_info['busy'] = True
                    node_info['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    target_map[model_name]['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    target_map[model_name]['expires_at'] = busy_nodes_info[node_id]['expires_at']
                
                target_map[model_name]['nodes'].append(node_info)
    
    # Convert to lists and sort
    available_list = list(available_models.values())
    available_list.sort(key=lambda x: (-x['nodes_count'], x['name']))
    
    busy_list = list(busy_models.values())
    busy_list.sort(key=lambda x: (x.get('seconds_remaining', 0), x['name']))
    
    return jsonify({
        'models': available_list,  # Available models (backwards compatibility)
        'busy_models': busy_list,  # Models on busy nodes with timer
        'total_nodes_online': len(connected_nodes),
        'available_nodes': available_nodes_count,
        'busy_nodes': len(busy_node_ids),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })


@app.route('/api/nodes/online', methods=['GET'])
def get_online_nodes():
    """
    Returns list of online nodes with their hardware info.
    Also indicates if the node is currently in use.
    Does not require authentication.
    """
    nodes = []
    busy_nodes_info = get_busy_nodes_info()
    busy_node_ids = set(busy_nodes_info.keys())
    
    for node_id, info in connected_nodes.items():
        hardware = info.get('hardware', {})
        models = info.get('models', [])
        is_busy = node_id in busy_node_ids
        
        # Extract RAM info
        ram_info = hardware.get('ram', {})
        ram_gb = ram_info.get('total_gb', 0)
        ram_speed = ram_info.get('speed_mhz', 0)
        ram_type = ram_info.get('type', '')
        
        # Extract disk info
        disk_info = hardware.get('disk', {})
        
        node_data = {
            'node_id': node_id,
            'name': info.get('name', node_id),
            'models': models,  # Full model list
            'models_count': len(models),
            'status': 'busy' if is_busy else 'available',
            'price_per_minute': info.get('price_per_minute', 100),  # Price in satoshi/minute
            'hardware': {
                'cpu': hardware.get('cpu', {}).get('name', 'Unknown'),
                'cpu_cores': hardware.get('cpu', {}).get('cores_logical', 0),
                'ram_gb': ram_gb,
                'ram_speed_mhz': ram_speed,
                'ram_type': ram_type,
                'gpus': [
                    {
                        'name': gpu.get('name', 'Unknown'),
                        'vram_mb': gpu.get('vram_total_mb', 0),
                        'type': gpu.get('type', 'unknown')
                    }
                    for gpu in hardware.get('gpus', [])
                ],
                'total_vram_mb': hardware.get('total_vram_mb', 0),
                'disk_total_gb': disk_info.get('total_gb', 0),
                'disk_free_gb': disk_info.get('free_gb', 0),
                'disk_percent_used': disk_info.get('percent_used', 0)
            }
        }
        
        # Se occupato, aggiungi info sul tempo rimanente
        if is_busy:
            busy_info = busy_nodes_info.get(node_id, {})
            node_data['busy_info'] = {
                'seconds_remaining': busy_info.get('seconds_remaining', 0),
                'model': busy_info.get('model', 'Unknown')
            }
        
        nodes.append(node_data)
    
    return jsonify({
        'nodes': nodes,
        'count': len(nodes),
        'available': len(nodes) - len(busy_node_ids),
        'busy': len(busy_node_ids),
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

# Session routes
@app.route('/api/new_session', methods=['POST'])
@jwt_required()
@rate_limit(max_requests=20, window_seconds=60)  # 20 sessions/minute per user
@validate_json('model', 'minutes')
@validate_model_param
def new_session():
    """Create a new session."""
    try:
        user_id = get_jwt_identity()
        
        # Converti user_id a int
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid token'}), 401
            
        data = request.get_json()
        model_requested = data['model']
        requested_node_id = data.get('node_id')  # Specific node requested
        hf_repo = data.get('hf_repo')  # HuggingFace repo for custom models
        
        logger.info(f"New session request: user={user_id}, model={model_requested}, node_id={requested_node_id}, hf_repo={hf_repo}")

        # If node_id is specified, verify it's online
        node_with_model = None
        model_price = None
        
        if requested_node_id:
            # Specific node requested
            if requested_node_id in connected_nodes:
                info = connected_nodes[requested_node_id]
                
                # Get node price
                node_price = info.get('price_per_minute', 100)
                
                # If it's a custom HuggingFace model, always accept (will be downloaded)
                if hf_repo:
                    node_with_model = requested_node_id
                    model_price = node_price  # Use node price
                else:
                    # Verify node has the model
                    node_models = info.get('models', [])
                    for model in node_models:
                        model_id = None
                        
                        if isinstance(model, dict):
                            model_id = model.get('id') or model.get('name')
                        else:
                            model_id = str(model)
                        
                        if model_id == model_requested:
                            node_with_model = requested_node_id
                            model_price = node_price  # Use node price
                            break
                    
                    if not node_with_model:
                        logger.warning(f"Requested node {requested_node_id} doesn't have model {model_requested}")
                        return jsonify({'error': f'Selected node does not have model: {model_requested}'}), 404
            else:
                logger.warning(f"Requested node {requested_node_id} is not online")
                return jsonify({'error': 'Selected node is not online'}), 404
        else:
            # No specific node: search automatically
            for node_id, info in connected_nodes.items():
                node_models = info.get('models', [])
                node_price = info.get('price_per_minute', 100)  # Node price
                
                for model in node_models:
                    model_id = None
                    
                    if isinstance(model, dict):
                        model_id = model.get('id') or model.get('name')
                    else:
                        model_id = str(model)
                    
                    if model_id == model_requested:
                        node_with_model = node_id
                        model_price = node_price  # Use node price
                        break
                
                if node_with_model:
                    break
        
        if not node_with_model:
            logger.warning(f"No node with model {model_requested}")
            return jsonify({'error': f'No node available with model: {model_requested}'}), 404

        # Validate minutes
        try:
            minutes = int(data['minutes'])
        except (ValueError, TypeError):
            return jsonify({'error': 'Minutes must be a number'}), 400
        
        if minutes < 1 or minutes > 120:
            return jsonify({'error': 'Minutes must be between 1 and 120'}), 400

        # Context length (default 4096)
        context_length = data.get('context_length', 4096)
        try:
            context_length = int(context_length)
            context_length = max(512, min(context_length, 131072))  # Clamp between 512 and 128k
        except (ValueError, TypeError):
            context_length = 4096

        # Create invoice (use node price if available)
        amount = get_model_price(model_requested, model_price) * minutes
        
        try:
            invoice = get_lightning_manager().create_invoice(
                amount,
                f"AI access: {model_requested} for {minutes} minutes"
            )
        except Exception as e:
            logger.error(f"Lightning invoice creation failed: {e}")
            return jsonify({'error': 'Lightning Network unavailable. Please try again later.'}), 503

        # Create session in DB (pending payment)
        # Save target node for assignment after payment
        session = Session(
            user_id=user_id,
            node_id='pending',
            model=model_requested,
            payment_hash=invoice['r_hash'],
            amount=amount,  # Save amount for wallet payment
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
            context_length=context_length
        )
        
        # Store target node in pending_sessions for assignment
        # after payment
        pending_sessions[invoice['r_hash']] = {
            'session_id': None,  # Will be updated after commit
            'target_node_id': node_with_model,
            'hf_repo': hf_repo
        }
        
        db.session.add(session)
        db.session.commit()
        
        # Update pending_sessions with session_id
        pending_sessions[invoice['r_hash']]['session_id'] = session.id
        
        logger.info(f"Session {session.id} created, invoice amount: {amount} sats, target_node: {node_with_model}")

        return jsonify({
            'invoice': invoice['payment_request'],
            'session_id': session.id,
            'amount': invoice['amount'],
            'expires_at': session.expires_at.isoformat() + 'Z'
        })
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to create session'}), 500

@app.route('/api/register_node', methods=['POST'])
@jwt_required()
def register_node():
    """Host node registration."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if user.balance < Config.NODE_REGISTRATION_FEE:
        return jsonify({'error': 'Insufficient balance'}), 402

    data = request.get_json()
    if not validate_model_list(data['models']):
        return jsonify({'error': 'Invalid models'}), 400

    # Register node
    node_id = get_node_manager().register_node(
        user_id,
        request.remote_addr,
        data['models']
    )

    # Save to DB
    node = Node(
        id=node_id,
        user_id=user_id,
        address=request.remote_addr,
        models=data['models']
    )
    db.session.add(node)

    # Charge fee
    user.balance -= Config.NODE_REGISTRATION_FEE
    db.session.add(Transaction(
        type='withdrawal',
        user_id=user_id,
        amount=Config.NODE_REGISTRATION_FEE,
        description='Node registration fee'
    ))
    db.session.commit()

    return jsonify({
        'node_id': node_id,
        'registration_fee': Config.NODE_REGISTRATION_FEE
    })

# WebSocket routes
@socketio.on('connect')
def handle_connect(auth=None):
    """WebSocket connection handling."""
    sid = request.sid
    logger.info(f"Socket connect: sid={sid}, auth={auth}")
    
    # Try to get token from auth parameter
    token = None
    if auth and 'token' in auth:
        token = auth['token']
        logger.info(f"Token from auth: {token[:20] if token else 'None'}...")
    
    # Try to get from query params
    if not token:
        token = request.args.get('token')
        if token:
            logger.info(f"Token from query: {token[:20]}...")
    
    if token:
        try:
            decoded = decode_token(token)
            user_id = decoded.get('sub')
            logger.info(f"Decoded token for sid {sid}: user_id={user_id}")
            if user_id:
                socket_users[sid] = int(user_id) if isinstance(user_id, str) else user_id
                logger.info(f'Client {sid} authenticated as user {user_id}')
        except Exception as e:
            logger.warning(f'Failed to decode token for {sid}: {e}')
    else:
        logger.warning(f"No token provided for socket {sid}")
    
    logger.info(f'Client connected: {sid}, authenticated: {sid in socket_users}')

@socketio.on('disconnect')
def handle_disconnect():
    """Disconnection handling."""
    sid = request.sid
    if sid in socket_users:
        del socket_users[sid]
    if Config.DEBUG:
        current_app.logger.info(f'Client disconnected: {sid}')

@socketio.on('start_session')
def start_session(data):
    """Start a session after payment."""
    logger.info(f"start_session called with data: {data}")
    
    user_id = get_socket_user_id()
    logger.info(f"start_session user_id: {user_id}")
    
    if not user_id:
        logger.warning("start_session: Authentication required")
        emit('error', {'message': 'Authentication required'})
        return
    session = Session.query.get(data['session_id'])
    
    logger.info(f"start_session: Found session: {session}, node_id: {session.node_id if session else 'None'}")

    # Validazioni
    if not session or session.user_id != user_id:
        logger.warning(f"start_session: Invalid session - session={session}, session.user_id={session.user_id if session else 'None'}, user_id={user_id}")
        emit('error', {'message': 'Invalid session'})
        return

    if session.node_id != 'pending':
        logger.warning(f"start_session: Session already started, node_id={session.node_id}")
        emit('error', {'message': 'Session already started'})
        return

    # Check payment: wallet auto-pay, DEBUG mode, or Lightning payment
    if session.payment_hash and session.payment_hash.startswith('WALLET_PAID'):
        payment_verified = True
        logger.info(f"Session {session.id} was paid from wallet")
    elif Config.DEBUG:
        payment_verified = True
    else:
        payment_verified = get_lightning_manager().check_payment(session.payment_hash)
    
    if not payment_verified:
        logger.warning("start_session: Payment not received")
        emit('error', {'message': 'Payment not received'})
        return

    if session.expired:
        logger.warning("start_session: Session expired")
        emit('error', {'message': 'Session expired'})
        return

    # Check if there's a specific target node in pending_sessions
    target_node_id = None
    hf_repo = None
    if session.payment_hash in pending_sessions:
        pending_info = pending_sessions[session.payment_hash]
        target_node_id = pending_info.get('target_node_id')
        hf_repo = pending_info.get('hf_repo')
        # Remove from pending_sessions
        del pending_sessions[session.payment_hash]
    
    # If there's a specific target node, use it
    ws_node_id = None
    ws_sid = None
    
    if target_node_id and target_node_id in connected_nodes:
        # Verify target node is still available (not busy)
        busy_nodes = get_busy_node_ids()
        if target_node_id not in busy_nodes:
            ws_node_id = target_node_id
            ws_sid = connected_nodes[target_node_id]['sid']
        else:
            emit('error', {'message': 'Selected node is currently busy'})
            return
    else:
        # Fallback: search for available WebSocket node (behind NAT)
        ws_node_id, ws_sid = get_websocket_node(session.model)
    
    if ws_node_id:
        # Use WebSocket node
        try:
            session.node_id = ws_node_id
            session.active = True
            db.session.commit()
            
            # Pay the node owner
            if ws_node_id in connected_nodes:
                owner_user_id = connected_nodes[ws_node_id].get('owner_user_id')
                if owner_user_id and session.amount:
                    # Calculate node payment (total - commission)
                    commission = int(session.amount * PLATFORM_COMMISSION_RATE)
                    node_payment = session.amount - commission
                    
                    # Credit node owner's balance
                    owner = User.query.get(owner_user_id)
                    if owner:
                        owner.balance += node_payment
                        
                        # Record transaction for node owner
                        from models import Transaction
                        owner_tx = Transaction(
                            type='node_earnings',
                            user_id=owner.id,
                            amount=node_payment,
                            fee=0,
                            balance_after=owner.balance,
                            status='completed',
                            description=f'Earnings from session {session.id} ({session.model})',
                            reference_id=str(session.id),
                            completed_at=datetime.utcnow()
                        )
                        db.session.add(owner_tx)
                        
                        logger.info(f"Paid {node_payment} sats to node owner (user #{owner_user_id}) for session {session.id}")
                    
                    # Credit commission to admin wallet
                    admin_user = User.query.filter_by(is_admin=True).first()
                    if admin_user:
                        admin_user.balance += commission
                        
                        # Record transaction for admin
                        admin_tx = Transaction(
                            type='platform_commission',
                            user_id=admin_user.id,
                            amount=commission,
                            fee=0,
                            balance_after=admin_user.balance,
                            status='completed',
                            description=f'Commission from session {session.id} ({session.model})',
                            reference_id=str(session.id),
                            completed_at=datetime.utcnow()
                        )
                        db.session.add(admin_tx)
                        
                        logger.info(f"Credited {commission} sats commission to admin (user #{admin_user.id})")
                    
                    db.session.commit()
                    
                    # Update node stats with earnings
                    update_node_stats_internal(ws_node_id, add_earned=node_payment)
            
            # Get context and hf_repo from model registered by node
            context = 4096  # Default
            model_hf_repo = None  # HuggingFace repo from registered model
            if ws_node_id in connected_nodes:
                node_models = connected_nodes[ws_node_id].get('models', [])
                for m in node_models:
                    if isinstance(m, dict):
                        model_id = m.get('id', m.get('name', ''))
                        if model_id == session.model or m.get('name') == session.model:
                            context = m.get('context_length', m.get('context', 4096))
                            # Retrieve hf_repo from model if HuggingFace
                            if m.get('is_huggingface') or m.get('hf_repo'):
                                model_hf_repo = m.get('hf_repo')
                            break
            
            # Use session context_length (chosen by user) if available
            if hasattr(session, 'context_length') and session.context_length:
                context = session.context_length
            
            # Send request to node
            start_data = {
                'session_id': session.id,
                'model': session.model,
                'model_id': session.model,  # For the new system
                'model_name': session.model,
                'context': context
            }
            
            # If it's a custom HuggingFace model, add the repo
            # Priority: hf_repo from request > hf_repo from registered model
            final_hf_repo = hf_repo or model_hf_repo
            if final_hf_repo:
                start_data['hf_repo'] = final_hf_repo
                logger.info(f"Session {session.id} will use HF model: {final_hf_repo}")
            
            logger.info(f"Sending start_session to node room 'node_{ws_node_id}': {start_data}")
            socketio.emit('start_session', start_data, room=f"node_{ws_node_id}")
            
            join_room(str(session.id))
            emit('session_started', {
                'session_id': session.id,
                'node_id': ws_node_id,
                'expires_at': session.expires_at.isoformat() + 'Z'
            })
            
            logger.info(f"Session {session.id} started on WebSocket node {ws_node_id}, client notified")
            return
            
        except Exception as e:
            current_app.logger.error(f"Failed to start session on WS node: {e}")
            # Try with HTTP node

    # Fallback: search for traditional HTTP node
    nm = get_node_manager()
    node = nm.get_available_node(session.model)
    if not node:
        emit('error', {'message': 'No available nodes'})
        return

    # Start session on HTTP node
    try:
        node_id_str = node[b'id'].decode() if isinstance(node[b'id'], bytes) else node[b'id']
        node_info = nm.start_remote_session(
            node_id_str,
            session.id,
            session.model,
            Config.AVAILABLE_MODELS[session.model]['context']
        )

        # Update session
        session.node_id = node_id_str
        session.active = True
        db.session.commit()

        # Calculate minutes from expiration
        minutes_purchased = (session.expires_at - session.created_at).total_seconds() / 60
        
        # Pay the node
        amount = int(get_model_price(session.model) * minutes_purchased * Config.NODE_PAYMENT_RATIO)
        nm.pay_node(
            session.node_id,
            amount,
            f"Payment for session {session.id}"
        )

        join_room(str(session.id))
        emit('session_started', {
            'session_id': session.id,
            'node_id': node_id_str,
            'expires_at': session.expires_at.isoformat() + 'Z'
        })

    except Exception as e:
        current_app.logger.error(f"Failed to start session: {e}")
        emit('error', {'message': 'Failed to start session'})

@socketio.on('chat_message')
def handle_message(data):
    """Chat message handling."""
    user_id = get_socket_user_id()
    if not user_id:
        emit('error', {'message': 'Authentication required'})
        return
    
    session = Session.query.get(data['session_id'])

    if not session or not session.active or session.expired:
        emit('error', {'message': 'Invalid session'})
        return

    # Check if the node is connected via WebSocket
    if session.node_id in connected_nodes:
        # Forward to WebSocket node with streaming enabled and all LLM parameters
        socketio.emit('inference_request', {
            'session_id': session.id,
            'prompt': data['prompt'],
            # Basic parameters
            'max_tokens': data.get('max_tokens', -1),
            'temperature': data.get('temperature', 0.7),
            'top_k': data.get('top_k', 40),
            'top_p': data.get('top_p', 0.95),
            'seed': data.get('seed', -1),
            'stop': data.get('stop', []),
            'stream': True,
            # Extended sampling parameters
            'min_p': data.get('min_p', 0.05),
            'typical_p': data.get('typical_p', 1.0),
            'dynatemp_range': data.get('dynatemp_range', 0.0),
            'dynatemp_exponent': data.get('dynatemp_exponent', 1.0),
            # Penalties
            'repeat_last_n': data.get('repeat_last_n', 64),
            'repeat_penalty': data.get('repeat_penalty', 1.0),
            'presence_penalty': data.get('presence_penalty', 0.0),
            'frequency_penalty': data.get('frequency_penalty', 0.0),
            # DRY parameters
            'dry_multiplier': data.get('dry_multiplier', 0.0),
            'dry_base': data.get('dry_base', 1.75),
            'dry_allowed_length': data.get('dry_allowed_length', 2),
            'dry_penalty_last_n': data.get('dry_penalty_last_n', -1),
            # XTC parameters
            'xtc_threshold': data.get('xtc_threshold', 0.1),
            'xtc_probability': data.get('xtc_probability', 0.5),
            # Sampler order
            'samplers': data.get('samplers', None)
        }, room=f"node_{session.node_id}")
        return

    # Otherwise use HTTP (traditional node)
    nm = get_node_manager()
    if not nm.check_node_status(session.node_id):
        emit('error', {'message': 'Node not available'})
        return

    # Forward request to node via proxy endpoint
    try:
        node_data = nm.redis.hgetall(f"node:{session.node_id}")
        if not node_data:
            emit('error', {'message': 'Node not found'})
            return
        
        node_address = node_data[b'address'].decode()
        
        # Use the new proxy endpoint on node (port 9000)
        # This internally handles communication with llama.cpp
        llama_response = httpx.post(
            f"http://{node_address}:9000/api/completion/{session.id}",
            json={
                'prompt': data['prompt'],
                'max_tokens': data.get('max_tokens', 2048),
                'temperature': data.get('temperature', 0.7),
                'top_k': data.get('top_k', 40),
                'top_p': data.get('top_p', 0.95),
                'repeat_penalty': data.get('repeat_penalty', 1.1),
                'stop': data.get('stop', [])
            },
            timeout=180  # 3 minutes for long generations
        )
        
        if llama_response.status_code == 404:
            emit('error', {'message': 'Session not found on node'})
            return
        
        if llama_response.status_code != 200:
            error_msg = llama_response.json().get('error', 'Unknown error')
            emit('error', {'message': f'LLM error: {error_msg}'})
            return
        
        result = llama_response.json()
        response = result.get('content', '')
        
    except httpx.TimeoutException:
        emit('error', {'message': 'Request timed out - try a shorter prompt'})
        return
    except httpx.ConnectError:
        current_app.logger.error(f"Cannot connect to node {session.node_id}")
        emit('error', {'message': 'Cannot connect to node'})
        return
    except Exception as e:
        current_app.logger.error(f"Error forwarding to node: {e}")
        emit('error', {'message': 'Failed to get response'})
        return

    emit('ai_response', {
        'response': response,
        'model': session.model,
        'tokens_generated': result.get('tokens_generated', 0)
    }, room=data['session_id'])

@socketio.on('end_session')
def end_session(data):
    """End session manually."""
    user_id = get_socket_user_id()
    if not user_id:
        emit('error', {'message': 'Authentication required'})
        return
    
    session_id = data.get('session_id')
    session = Session.query.get(session_id)
    
    if session and session.user_id == user_id:
        logger.info(f"Ending session {session.id}, node_id={session.node_id}")
        
        # Stop session on node
        if session.node_id and session.node_id != 'pending':
            node_id = session.node_id
            
            # Debug: show connected nodes
            logger.info(f"Connected nodes: {list(connected_nodes.keys())}")
            
            # Check if it's a WebSocket node
            if node_id in connected_nodes:
                node_info = connected_nodes[node_id]
                node_sid = node_info.get('sid')
                
                # Send stop_session directly to node socket
                logger.info(f"Sending stop_session to node {node_id} (sid: {node_sid})")
                
                # Use to= instead of room= to send directly to node sid
                socketio.emit('stop_session', {
                    'session_id': str(session.id)
                }, to=node_sid)
                
                logger.info(f"Sent stop_session to WebSocket node {node_id} for session {session.id}")
            else:
                # Use HTTP for traditional nodes
                logger.info(f"Node {node_id} not in connected_nodes, trying HTTP")
                get_node_manager().stop_remote_session(node_id, session.id)
        
        # Save node_id before marking inactive
        freed_node_id = session.node_id
        
        session.active = False
        db.session.commit()
        
        # Update node stats (session completed)
        if freed_node_id and freed_node_id != 'pending' and freed_node_id in connected_nodes:
            # Calculate active minutes (if we have start time)
            minutes_active = 0
            if session.created_at:
                delta = datetime.utcnow() - session.created_at
                minutes_active = delta.total_seconds() / 60
            
            update_node_stats_internal(
                freed_node_id, 
                add_completed=True,
                add_minutes=minutes_active
            )
        
        leave_room(str(session.id))
        emit('session_ended', room=str(session.id))
        
        # Notify ALL clients that the node is now available
        # This immediately updates the models list for everyone
        socketio.emit('node_freed', {
            'node_id': freed_node_id,
            'message': 'Node is now available'
        })
        
        logger.info(f"Session {session.id} ended by user {user_id}, node {freed_node_id} freed")

# Admin routes
@app.route('/admin/nodes')
@jwt_required()
def list_nodes():
    """List all nodes (admin only)."""
    user_id = get_jwt_identity()
    if not User.query.get(user_id).is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    nodes = get_node_manager().get_all_nodes()
    # Convert bytes to strings for JSON serialization
    result = []
    for n in nodes:
        node_dict = {}
        for k, v in n.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            node_dict[key] = val
        result.append(node_dict)
    return jsonify(result)


# Node heartbeat endpoint
@app.route('/api/node_heartbeat', methods=['POST'])
def node_heartbeat():
    """Receive heartbeat from a node."""
    data = request.get_json()
    node_id = data.get('node_id')
    
    if not node_id:
        return jsonify({'error': 'Missing node_id'}), 400
    
    nm = get_node_manager()
    nm.node_heartbeat(node_id)
    
    # Also update load if provided
    if 'load' in data:
        nm.redis.hset(f"node:{node_id}", 'load', data['load'])
    
    return jsonify({'status': 'ok'})


# ============================================
# Node Statistics API
# ============================================

@app.route('/api/node/stats/<node_id>', methods=['GET'])
def get_node_stats(node_id):
    """Get statistics for a node."""
    from models import NodeStats
    
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        # Create empty stats if they don't exist
        return jsonify({
            'node_id': node_id,
            'total_sessions': 0,
            'completed_sessions': 0,
            'failed_sessions': 0,
            'total_requests': 0,
            'total_tokens_generated': 0,
            'total_minutes_active': 0,
            'total_earned_sats': 0,
            'avg_tokens_per_second': 0,
            'avg_response_time_ms': 0,
            'first_online': None,
            'last_online': None,
            'total_uptime_hours': 0
        })
    
    return jsonify(stats.to_dict())


@app.route('/api/node/stats/<node_id>/update', methods=['POST'])
def update_node_stats(node_id):
    """Update statistics for a node (called internally)."""
    from models import NodeStats
    
    data = request.get_json()
    
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        stats = NodeStats(node_id=node_id)
        db.session.add(stats)
    
    # Update fields if present
    if 'add_session' in data:
        stats.total_sessions += 1
    if 'add_completed' in data:
        stats.completed_sessions += 1
    if 'add_failed' in data:
        stats.failed_sessions += 1
    if 'add_request' in data:
        stats.total_requests += 1
    if 'add_tokens' in data:
        stats.total_tokens_generated += data['add_tokens']
    if 'add_minutes' in data:
        stats.total_minutes_active += data['add_minutes']
    if 'add_earned' in data:
        stats.total_earned_sats += data['add_earned']
    if 'update_performance' in data:
        perf = data['update_performance']
        # Moving average for performance
        if perf.get('tokens_per_second'):
            if stats.avg_tokens_per_second == 0:
                stats.avg_tokens_per_second = perf['tokens_per_second']
            else:
                stats.avg_tokens_per_second = (stats.avg_tokens_per_second + perf['tokens_per_second']) / 2
        if perf.get('response_time_ms'):
            if stats.avg_response_time_ms == 0:
                stats.avg_response_time_ms = perf['response_time_ms']
            else:
                stats.avg_response_time_ms = (stats.avg_response_time_ms + perf['response_time_ms']) / 2
    
    stats.last_online = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'status': 'ok', 'stats': stats.to_dict()})


def process_session_refund(session, reason='node_disconnect'):
    """
    Calculate and process refund for a session interrupted before expiry.
    
    Args:
        session: Session object
        reason: Reason for refund (node_disconnect, node_error, etc.)
        
    Returns:
        int: Amount refunded in satoshis, or 0 if no refund
    """
    try:
        if not session or not session.active:
            return 0
        
        if session.refunded:
            logger.info(f"Session {session.id} already refunded")
            return 0
        
        if not session.amount or session.amount <= 0:
            logger.info(f"Session {session.id} has no payment amount")
            return 0
        
        now = datetime.utcnow()
        
        # Calculate time used vs time paid
        if session.started_at:
            # Session actually started - calculate used time
            time_used = (now - session.started_at).total_seconds()
            total_time = (session.expires_at - session.started_at).total_seconds()
        else:
            # Session never started (node crashed before ready) - full refund
            time_used = 0
            total_time = (session.expires_at - session.created_at).total_seconds()
        
        if total_time <= 0:
            logger.error(f"Session {session.id} has invalid total_time: {total_time}")
            return 0
        
        # Calculate remaining time percentage
        time_remaining = max(0, total_time - time_used)
        refund_percentage = time_remaining / total_time
        
        # Calculate refund amount (round down)
        refund_amount = int(session.amount * refund_percentage)
        
        if refund_amount <= 0:
            logger.info(f"Session {session.id} no refund needed (used {time_used:.0f}s of {total_time:.0f}s)")
            return 0
        
        # Credit refund to user's balance
        user = session.user
        if user:
            user.balance += refund_amount
            logger.info(f"Refunded {refund_amount} sats to user {user.username} (session {session.id}, reason: {reason})")
        
        # Mark session as refunded and ended
        session.refunded = True
        session.refund_amount = refund_amount
        session.active = False
        session.ended_at = now
        
        db.session.commit()
        
        # Notify user via socket if connected
        try:
            socketio.emit('session_refunded', {
                'session_id': session.id,
                'refund_amount': refund_amount,
                'reason': reason,
                'new_balance': user.balance if user else 0
            }, room=str(session.id))
        except Exception as e:
            logger.error(f"Error notifying user of refund: {e}")
        
        return refund_amount
        
    except Exception as e:
        logger.error(f"Error processing refund for session {session.id}: {e}")
        db.session.rollback()
        return 0


def refund_active_sessions_for_node(node_id, reason='node_disconnect'):
    """
    Refund all active sessions for a node that disconnected.
    
    Args:
        node_id: Node ID that disconnected
        reason: Reason for refund
        
    Returns:
        list: List of (session_id, refund_amount) tuples
    """
    refunds = []
    try:
        # Find all active sessions for this node
        active_sessions = Session.query.filter_by(
            node_id=node_id, 
            active=True,
            refunded=False
        ).all()
        
        logger.info(f"Found {len(active_sessions)} active sessions for disconnected node {node_id}")
        
        for session in active_sessions:
            refund_amount = process_session_refund(session, reason)
            if refund_amount > 0:
                refunds.append((session.id, refund_amount))
        
        return refunds
        
    except Exception as e:
        logger.error(f"Error refunding sessions for node {node_id}: {e}")
        return refunds


def update_node_stats_internal(node_id, **kwargs):
    """Helper to update statistics internally."""
    from models import NodeStats
    
    try:
        stats = NodeStats.query.filter_by(node_id=node_id).first()
        if not stats:
            stats = NodeStats(node_id=node_id)
            db.session.add(stats)
        
        if kwargs.get('add_session'):
            stats.total_sessions += 1
        if kwargs.get('add_completed'):
            stats.completed_sessions += 1
        if kwargs.get('add_failed'):
            stats.failed_sessions += 1
        if kwargs.get('add_request'):
            stats.total_requests += 1
        if kwargs.get('add_tokens'):
            stats.total_tokens_generated += kwargs['add_tokens']
        if kwargs.get('add_minutes'):
            stats.total_minutes_active += kwargs['add_minutes']
        if kwargs.get('add_earned'):
            stats.total_earned_sats += kwargs['add_earned']
        
        stats.last_online = datetime.utcnow()
        db.session.commit()
        
        return stats
    except Exception as e:
        logger.error(f"Error updating node stats: {e}")
        return None


@app.route('/api/node/stats/<node_id>/reset', methods=['POST'])
def reset_node_stats(node_id):
    """Reset statistics for a node."""
    from models import NodeStats
    
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        return jsonify({'error': 'Node not found'}), 404
    
    # Reset all counters but keep dates
    stats.total_sessions = 0
    stats.completed_sessions = 0
    stats.failed_sessions = 0
    stats.total_requests = 0
    stats.total_tokens_generated = 0
    stats.total_minutes_active = 0
    stats.total_earned_sats = 0
    stats.avg_tokens_per_second = 0
    stats.avg_response_time_ms = 0
    
    db.session.commit()
    
    logger.info(f"Reset statistics for node {node_id}")
    return jsonify({'status': 'ok', 'message': 'Statistics reset successfully'})


# ============================================
# WebSocket handlers for nodes behind NAT
# ============================================

# Dictionary to map node_id -> socket_id and info
# node_id -> {'sid': socket_id, 'models': [...], 'hardware': {...}, 'name': str}
connected_nodes = {}  
pending_requests = {}  # request_id -> {'session_id': ..., 'user_sid': ...}
pending_sessions = {}  # payment_hash -> {'session_id': ..., 'target_node_id': ..., 'hf_repo': ...}


@socketio.on('node_register')
def handle_node_register(data):
    """Register a node connected via WebSocket."""
    token = data.get('token', '')
    models = data.get('models', [])
    hardware = data.get('hardware', {})
    node_name = data.get('name', '')
    price_per_minute = data.get('price_per_minute', 100)  # Default 100 sats/min
    auth_token = data.get('auth_token')  # User's JWT token
    user_id = data.get('user_id')  # Owner user ID
    
    # Verify user authentication if provided
    owner_user_id = None
    if auth_token:
        try:
            from flask_jwt_extended import decode_token
            decoded = decode_token(auth_token)
            owner_user_id = decoded.get('sub')  # user_id from token
            logger.info(f"Node authenticated as user {owner_user_id}")
        except Exception as e:
            logger.warning(f"Invalid auth_token for node: {e}")
    elif user_id:
        owner_user_id = user_id
    
    # Generate or validate node_id
    node_id = None
    if token:
        # Search existing node with this token
        nm = get_node_manager()
        for nid in nm.redis.smembers(nm.nodes_set_key):
            nid_str = nid.decode() if isinstance(nid, bytes) else nid
            node_data = nm.redis.hgetall(f"node:{nid_str}")
            if node_data.get(b'token', b'').decode() == token:
                node_id = nid_str
                break
    
    if not node_id:
        # New node
        import uuid
        node_id = f"node-ws-{uuid.uuid4().hex[:8]}"
        token = uuid.uuid4().hex
        
        nm = get_node_manager()
        node_data_redis = {
            'id': node_id,
            'token': token,
            'name': node_name or node_id,
            'models': json.dumps(models) if models else '[]',
            'hardware': json.dumps(hardware) if hardware else '{}',
            'price_per_minute': price_per_minute,
            'status': 'online',
            'type': 'websocket',
            'last_ping': datetime.utcnow().timestamp(),
            'load': 0
        }
        # Save owner if authenticated
        if owner_user_id:
            node_data_redis['owner_user_id'] = owner_user_id
        
        nm.redis.hset(f"node:{node_id}", mapping=node_data_redis)
        nm.redis.sadd(nm.nodes_set_key, node_id)
    else:
        # Update existing node
        nm = get_node_manager()
        update_data = {
            'status': 'online',
            'last_ping': datetime.utcnow().timestamp(),
            'price_per_minute': price_per_minute,
        }
        # Update owner if authenticated
        if owner_user_id:
            update_data['owner_user_id'] = owner_user_id
        if models:
            update_data['models'] = json.dumps(models)
        if hardware:
            update_data['hardware'] = json.dumps(hardware)
        if node_name:
            update_data['name'] = node_name
        nm.redis.hset(f"node:{node_id}", mapping=update_data)
    
    # Register in connections map
    connected_nodes[node_id] = {
        'sid': request.sid,
        'models': models,
        'hardware': hardware,
        'name': node_name or node_id,
        'price_per_minute': price_per_minute,
        'owner_user_id': owner_user_id  # Owner user ID
    }
    
    join_room(f"node_{node_id}")
    
    # Calculate total VRAM
    total_vram = hardware.get('total_vram_mb', 0) if hardware else 0
    gpu_count = len(hardware.get('gpus', [])) if hardware else 0
    
    # Update node stats (first_online, last_online) and owner
    from models import NodeStats
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        stats = NodeStats(node_id=node_id, first_online=datetime.utcnow())
        db.session.add(stats)
    stats.last_online = datetime.utcnow()
    if owner_user_id:
        stats.owner_user_id = owner_user_id
    db.session.commit()
    
    owner_str = f", owner: user#{owner_user_id}" if owner_user_id else ""
    logger.info(f"Node {node_id} ({node_name}) registered via WebSocket - {len(models)} models, {gpu_count} GPUs, {total_vram}MB VRAM{owner_str}")
    
    # Clear offline alert cooldown since node is now online
    from utils.email_service import clear_alert_cooldown
    clear_alert_cooldown(node_id, 'offline')
    
    emit('node_registered', {
        'node_id': node_id,
        'token': token,
        'owner_user_id': owner_user_id  # Return to client
    })
    
    # Check disk space and send alert if critical
    if hardware and owner_user_id:
        disk_info = hardware.get('disk', {})
        disk_percent = disk_info.get('percent_used', 0)
        disk_free_gb = disk_info.get('free_gb', 100)
        
        if disk_percent >= Config.DISK_CRITICAL_PERCENT:
            # Get owner's email
            owner = User.query.get(owner_user_id)
            if owner and owner.email:
                from utils.email_service import send_disk_full_alert
                send_disk_full_alert(
                    user_email=owner.email,
                    node_id=node_id,
                    node_name=node_name or node_id,
                    disk_percent=disk_percent,
                    disk_free_gb=disk_free_gb
                )
                logger.warning(f"Disk critical alert sent for node {node_id}: {disk_percent}% used")
        else:
            # Clear disk alert cooldown if disk is now OK
            from utils.email_service import clear_alert_cooldown
            clear_alert_cooldown(node_id, 'disk')


@socketio.on('disconnect')
def handle_disconnect():
    """Disconnect handling - updated for nodes."""
    # Remove node from map if it was connected
    for node_id, info in list(connected_nodes.items()):
        if info['sid'] == request.sid:
            node_name = info.get('name', node_id)
            owner_user_id = info.get('owner_user_id')
            
            del connected_nodes[node_id]
            
            # Mark node offline
            nm = get_node_manager()
            nm.redis.hset(f"node:{node_id}", 'status', 'offline')
            
            logger.info(f"Node {node_id} disconnected")
            
            # Refund active sessions for this node
            try:
                refunds = refund_active_sessions_for_node(node_id, reason='node_disconnect')
                if refunds:
                    logger.info(f"Processed {len(refunds)} refunds for node {node_id}: {refunds}")
            except Exception as e:
                logger.error(f"Error processing refunds for node {node_id}: {e}")
            
            # Send offline notification email to owner
            if owner_user_id:
                try:
                    owner = User.query.get(owner_user_id)
                    if owner and owner.email:
                        from utils.email_service import send_node_offline_alert
                        send_node_offline_alert(
                            user_email=owner.email,
                            node_id=node_id,
                            node_name=node_name
                        )
                        logger.info(f"Offline alert email sent to {owner.email} for node {node_id}")
                except Exception as e:
                    logger.error(f"Failed to send offline alert for node {node_id}: {e}")
            
            break
    
    if Config.DEBUG:
        current_app.logger.info(f'Client disconnected: {request.sid}')


@socketio.on('session_started')
def handle_node_session_started(data):
    """Node confirms that session has started."""
    session_id = str(data['session_id'])
    node_id = data.get('node_id')
    
    logger.info(f"Node confirms session {session_id} started")
    
    # Update session started_at timestamp
    try:
        session = Session.query.get(int(session_id))
        if session and not session.started_at:
            session.started_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Session {session_id} started_at set to {session.started_at}")
    except Exception as e:
        logger.error(f"Error updating session started_at: {e}")
    
    # Update node stats
    if node_id:
        update_node_stats_internal(node_id, add_session=True)
    
    # Notify the user client
    emit('session_ready', {'session_id': session_id}, room=session_id)


@socketio.on('session_error')
def handle_node_session_error(data):
    """Node reports error starting session."""
    session_id = str(data['session_id'])
    error = data.get('error', 'Unknown error')
    node_id = data.get('node_id')
    
    logger.error(f"Node error for session {session_id}: {error}")
    
    # Refund the session since it failed
    try:
        session = Session.query.get(int(session_id))
        if session:
            refund_amount = process_session_refund(session, reason=f'node_error: {error}')
            if refund_amount > 0:
                logger.info(f"Refunded {refund_amount} sats for failed session {session_id}")
    except Exception as e:
        logger.error(f"Error processing refund for session {session_id}: {e}")
    
    # Update node stats (failed session)
    if node_id:
        update_node_stats_internal(node_id, add_failed=True)
    
    emit('error', {'message': f'Node error: {error}'}, room=session_id)


@socketio.on('inference_token')
def handle_inference_token(data):
    """Node sends single token (streaming)."""
    session_id = str(data['session_id'])
    token = data.get('token', '')
    is_final = data.get('is_final', False)
    
    logger.info(f"[STREAMING] Token for session {session_id}: '{token[:30] if len(token) > 30 else token}' final={is_final}")
    
    # Forward token to client
    emit('ai_token', {
        'token': token,
        'is_final': is_final,
        'session_id': session_id
    }, room=session_id)


@socketio.on('session_status')
def handle_session_status(data):
    """Node sends session status update (download/loading model)."""
    session_id = str(data['session_id'])
    status = data.get('status', 'unknown')
    message = data.get('message', '')
    
    logger.info(f"Session {session_id} status: {status} - {message}")
    
    # Forward to client
    emit('model_status', {
        'session_id': session_id,
        'status': status,
        'message': message
    }, room=session_id)


@socketio.on('inference_complete')
def handle_inference_complete(data):
    """Node signals streaming completion with clean response."""
    session_id = str(data['session_id'])
    content = data.get('content', '')
    tokens_generated = data.get('tokens_generated', 0)
    response_time_ms = data.get('response_time_ms', 0)
    
    logger.info(f"[STREAMING] inference_complete for session {session_id}, tokens: {tokens_generated}, content length: {len(content) if content else 0}")
    
    # Update node stats
    session = Session.query.get(session_id)
    if session and session.node_id:
        tokens_per_second = 0
        if response_time_ms > 0 and tokens_generated > 0:
            tokens_per_second = tokens_generated / (response_time_ms / 1000)
        
        update_node_stats_internal(
            session.node_id,
            add_request=True,
            add_tokens=tokens_generated
        )
        
        # Update performance if available
        if tokens_per_second > 0 or response_time_ms > 0:
            from models import NodeStats
            stats = NodeStats.query.filter_by(node_id=session.node_id).first()
            if stats:
                if tokens_per_second > 0:
                    if stats.avg_tokens_per_second == 0:
                        stats.avg_tokens_per_second = tokens_per_second
                    else:
                        stats.avg_tokens_per_second = (stats.avg_tokens_per_second + tokens_per_second) / 2
                if response_time_ms > 0:
                    if stats.avg_response_time_ms == 0:
                        stats.avg_response_time_ms = response_time_ms
                    else:
                        stats.avg_response_time_ms = (stats.avg_response_time_ms + response_time_ms) / 2
                db.session.commit()
    
    # Send clean complete response
    emit('ai_response', {
        'response': content,
        'session_id': session_id,
        'streaming_complete': True
    }, room=session_id)


@socketio.on('inference_response')
def handle_inference_response(data):
    """Node sends inference response (non-streaming)."""
    session_id = str(data['session_id'])
    content = data.get('content', '')
    tokens_generated = data.get('tokens_generated', 0)
    response_time_ms = data.get('response_time_ms', 0)
    
    # Update node stats
    session = Session.query.get(session_id)
    if session and session.node_id:
        tokens_per_second = 0
        if response_time_ms > 0 and tokens_generated > 0:
            tokens_per_second = tokens_generated / (response_time_ms / 1000)
        
        update_node_stats_internal(
            session.node_id,
            add_request=True,
            add_tokens=tokens_generated
        )
        
        # Update performance if available
        if tokens_per_second > 0 or response_time_ms > 0:
            from models import NodeStats
            stats = NodeStats.query.filter_by(node_id=session.node_id).first()
            if stats:
                if tokens_per_second > 0:
                    if stats.avg_tokens_per_second == 0:
                        stats.avg_tokens_per_second = tokens_per_second
                    else:
                        stats.avg_tokens_per_second = (stats.avg_tokens_per_second + tokens_per_second) / 2
                if response_time_ms > 0:
                    if stats.avg_response_time_ms == 0:
                        stats.avg_response_time_ms = response_time_ms
                    else:
                        stats.avg_response_time_ms = (stats.avg_response_time_ms + response_time_ms) / 2
                db.session.commit()
    
    emit('ai_response', {
        'response': content,
        'session_id': session_id
    }, room=session_id)


@socketio.on('inference_error')
def handle_inference_error(data):
    """Node reports inference error."""
    session_id = str(data['session_id'])
    error = data.get('error', 'Unknown error')
    
    emit('error', {'message': f'Inference error: {error}'}, room=session_id)


@socketio.on('node_models_update')
def handle_node_models_update(data):
    """Node updates available models list."""
    node_id = data.get('node_id')
    models = data.get('models', [])
    hardware = data.get('hardware')
    
    if not node_id:
        # Search node_id from socket id
        for nid, info in connected_nodes.items():
            if info['sid'] == request.sid:
                node_id = nid
                break
    
    if not node_id or node_id not in connected_nodes:
        emit('error', {'message': 'Node not registered'})
        return
    
    # Update models in connected_nodes
    connected_nodes[node_id]['models'] = models
    if hardware:
        connected_nodes[node_id]['hardware'] = hardware
    
    # Also update in Redis
    nm = get_node_manager()
    update_data = {
        'models': json.dumps(models),
        'last_ping': datetime.utcnow().timestamp()
    }
    if hardware:
        update_data['hardware'] = json.dumps(hardware)
    nm.redis.hset(f"node:{node_id}", mapping=update_data)
    
    logger.info(f"Node {node_id} updated models: {len(models)} available")
    
    emit('models_updated', {'count': len(models)})


@socketio.on('node_heartbeat')
def handle_node_heartbeat(data):
    """Heartbeat from node to keep connection active."""
    node_id = data.get('node_id')
    
    if not node_id:
        for nid, info in connected_nodes.items():
            if info['sid'] == request.sid:
                node_id = nid
                break
    
    if node_id and node_id in connected_nodes:
        nm = get_node_manager()
        nm.redis.hset(f"node:{node_id}", 'last_ping', datetime.utcnow().timestamp())
        emit('heartbeat_ack', {'timestamp': datetime.utcnow().isoformat() + 'Z'})


def get_websocket_node(model_query):
    """
    Find an available WebSocket node for the model.
    Excludes nodes already in use by other users.
    
    model_query can be:
    - Model name (old format)
    - Model ID (new format)
    - Partial name for fuzzy matching
    """
    # Get busy nodes
    busy_nodes = get_busy_node_ids()
    
    for node_id, info in connected_nodes.items():
        # Skip nodes already in use
        if node_id in busy_nodes:
            logger.debug(f"Node {node_id} is busy, skipping")
            continue
            
        node_models = info.get('models', [])
        
        for model in node_models:
            if isinstance(model, dict):
                # New format
                model_id = model.get('id', '')
                model_name = model.get('name', '')
                
                if (model_query == model_id or 
                    model_query == model_name or
                    model_query.lower() in model_name.lower()):
                    return node_id, info['sid']
            else:
                # Old format - string
                if model_query == model or model_query.lower() in str(model).lower():
                    return node_id, info['sid']
    
    return None, None


def get_websocket_node_for_model_id(model_id):
    """
    Find a WebSocket node for a specific model_id.
    Excludes nodes already in use by other users.
    """
    # Get busy nodes
    busy_nodes = get_busy_node_ids()
    
    for node_id, info in connected_nodes.items():
        # Skip nodes already in use
        if node_id in busy_nodes:
            logger.debug(f"Node {node_id} is busy, skipping")
            continue
            
        for model in info.get('models', []):
            if isinstance(model, dict) and model.get('id') == model_id:
                return node_id, info['sid'], model
            elif str(model) == model_id:
                return node_id, info['sid'], {'name': model}
    return None, None, None


# ============================================


# Background job for cleaning up expired sessions
def cleanup_expired_sessions():
    """Clean up expired sessions."""
    with app.app_context():
        expired = Session.query.filter(
            Session.active == True,
            Session.expires_at < datetime.utcnow()
        ).all()
        
        nm = get_node_manager()
        for session in expired:
            current_app.logger.info(f"Cleaning up expired session {session.id}")
            
            # Stop session on node
            if session.node_id and session.node_id != 'pending':
                try:
                    nm.stop_remote_session(session.node_id, session.id)
                except Exception as e:
                    current_app.logger.error(f"Error stopping session on node: {e}")
            
            session.active = False
        
        if expired:
            db.session.commit()
            current_app.logger.info(f"Cleaned up {len(expired)} expired sessions")


def start_cleanup_scheduler():
    """Start the scheduler for periodic cleanup."""
    import threading
    
    def run_cleanup():
        while True:
            try:
                cleanup_expired_sessions()
            except Exception as e:
                print(f"Cleanup error: {e}")
            # Run every minute
            threading.Event().wait(60)
    
    thread = threading.Thread(target=run_cleanup, daemon=True)
    thread.start()


# CLI commands
@app.cli.command('init-db')
def init_db():
    """Initialize the database."""
    db.create_all()
    print('Initialized database.')


@app.cli.command('cleanup-sessions')
def cleanup_sessions_cmd():
    """Manually clean up expired sessions."""
    cleanup_expired_sessions()
    print('Cleanup completed.')


@app.cli.command('create-admin')
@click.argument('username')
@click.argument('password')
def create_admin(username, password):
    """Create an admin user."""
    user = User(username=username, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f'Admin user {username} created.')
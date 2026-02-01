"""
Applicazione Flask principale.

Gestisce autenticazione, API, WebSocket e logica business.
"""
from flask import Flask, render_template, request, jsonify, current_app
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from config import Config
from models import db, User, Session, Node, Transaction
from lightning import LightningManager
from nodemanager import NodeManager
from utils.helpers import validate_model, get_model_price
from utils.decorators import rate_limit, validate_json, validate_model_param, admin_required
from datetime import datetime, timedelta
import httpx
import click
import logging

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configura percorsi per templates e static files
import os
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
template_dir = os.path.join(base_dir, 'web-client')
static_dir = os.path.join(base_dir, 'web-client')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir, static_url_path='')
app.config.from_object(Config)
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
jwt = JWTManager(app)

# Lazy initialization - will be set up in app context
lm = None
node_manager = None

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
    """Pagina principale (web client)."""
    return render_template('index.html')

# Auth routes
@app.route('/api/register', methods=['POST'])
@rate_limit(max_requests=5, window_seconds=60)  # 5 registrazioni/minuto per IP
@validate_json('username', 'password')
def register():
    """Registrazione utente."""
    data = request.get_json()
    
    # Validazione input
    username = data['username'].strip()
    password = data['password']
    
    if len(username) < 3 or len(username) > 80:
        return jsonify({'error': 'Username must be 3-80 characters'}), 400
    
    if not username.replace('_', '').isalnum():
        return jsonify({'error': 'Username can only contain letters, numbers and underscores'}), 400
    
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 400

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'Registered successfully'})

@app.route('/api/login', methods=['POST'])
@rate_limit(max_requests=10, window_seconds=60)  # 10 login/minuto per IP
@validate_json('username', 'password')
def login():
    """Login utente."""
    data = request.get_json()
    user = User.query.filter_by(username=data['username'].strip()).first()
    if not user or not user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify({'access_token': access_token})

# Session routes
@app.route('/api/new_session', methods=['POST'])
@jwt_required()
@rate_limit(max_requests=20, window_seconds=60)  # 20 sessioni/minuto per utente
@validate_json('model', 'minutes')
@validate_model_param
def new_session():
    """Crea una nuova sessione."""
    user_id = get_jwt_identity()
    data = request.get_json()

    # Valida minuti
    try:
        minutes = int(data['minutes'])
    except (ValueError, TypeError):
        return jsonify({'error': 'Minutes must be a number'}), 400
    
    if minutes < 1 or minutes > 120:
        return jsonify({'error': 'Minutes must be between 1 and 120'}), 400

    # Crea fattura
    amount = get_model_price(data['model']) * minutes
    invoice = get_lightning_manager().create_invoice(
        amount,
        f"AI access: {data['model']} for {minutes} minutes"
    )

    # Crea sessione nel DB (pending payment)
    session = Session(
        user_id=user_id,
        node_id='pending',
        model=data['model'],
        payment_hash=invoice['r_hash'],
        expires_at=datetime.utcnow() + timedelta(minutes=minutes)
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'invoice': invoice['payment_request'],
        'session_id': session.id,
        'amount': invoice['amount'],
        'expires_at': session.expires_at.isoformat()
    })

@app.route('/api/register_node', methods=['POST'])
@jwt_required()
def register_node():
    """Registrazione di un nodo host."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if user.balance < Config.NODE_REGISTRATION_FEE:
        return jsonify({'error': 'Insufficient balance'}), 402

    data = request.get_json()
    if not validate_model_list(data['models']):
        return jsonify({'error': 'Invalid models'}), 400

    # Registra nodo
    node_id = get_node_manager().register_node(
        user_id,
        request.remote_addr,
        data['models']
    )

    # Salva nel DB
    node = Node(
        id=node_id,
        user_id=user_id,
        address=request.remote_addr,
        models=data['models']
    )
    db.session.add(node)

    # Addebita fee
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
def handle_connect():
    """Gestione connessione WebSocket."""
    if Config.DEBUG:
        current_app.logger.info(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    """Gestione disconnessione."""
    if Config.DEBUG:
        current_app.logger.info(f'Client disconnected: {request.sid}')

@socketio.on('start_session')
@jwt_required()
def start_session(data):
    """Avvia una sessione dopo pagamento."""
    user_id = get_jwt_identity()
    session = Session.query.get(data['session_id'])

    # Validazioni
    if not session or session.user_id != user_id:
        emit('error', {'message': 'Invalid session'})
        return

    if session.node_id != 'pending':
        emit('error', {'message': 'Session already started'})
        return

    if not get_lightning_manager().check_payment(session.payment_hash):
        emit('error', {'message': 'Payment not received'})
        return

    if session.expired:
        emit('error', {'message': 'Session expired'})
        return

    # Trova un nodo disponibile
    nm = get_node_manager()
    node = nm.get_available_node(session.model)
    if not node:
        emit('error', {'message': 'No available nodes'})
        return

    # Avvia sessione sul nodo
    try:
        node_id_str = node[b'id'].decode() if isinstance(node[b'id'], bytes) else node[b'id']
        node_info = nm.start_remote_session(
            node_id_str,
            session.id,
            session.model,
            Config.AVAILABLE_MODELS[session.model]['context']
        )

        # Aggiorna sessione
        session.node_id = node_id_str
        session.active = True
        db.session.commit()

        # Calcola minuti dalla scadenza
        minutes_purchased = (session.expires_at - session.created_at).total_seconds() / 60
        
        # Paga il nodo
        amount = int(get_model_price(session.model) * minutes_purchased * Config.NODE_PAYMENT_RATIO)
        nm.pay_node(
            session.node_id,
            amount,
            f"Payment for session {session.id}"
        )

        join_room(session.id)
        emit('session_started', {
            'session_id': session.id,
            'node_id': node_id_str,
            'expires_at': session.expires_at.isoformat()
        })

    except Exception as e:
        current_app.logger.error(f"Failed to start session: {e}")
        emit('error', {'message': 'Failed to start session'})

@socketio.on('chat_message')
@jwt_required()
def handle_message(data):
    """Gestione messaggi chat."""
    session = Session.query.get(data['session_id'])

    if not session or not session.active or session.expired:
        emit('error', {'message': 'Invalid session'})
        return

    # Inoltra al nodo
    nm = get_node_manager()
    if not nm.check_node_status(session.node_id):
        emit('error', {'message': 'Node not available'})
        return

    # Inoltra la richiesta al nodo tramite il proxy endpoint
    try:
        node_data = nm.redis.hgetall(f"node:{session.node_id}")
        if not node_data:
            emit('error', {'message': 'Node not found'})
            return
        
        node_address = node_data[b'address'].decode()
        
        # Usa il nuovo endpoint proxy sul nodo (porta 9000)
        # Questo gestisce internamente la comunicazione con llama.cpp
        llama_response = httpx.post(
            f"http://{node_address}:9000/api/completion/{session.id}",
            json={
                'prompt': data['prompt'],
                'max_tokens': data.get('max_tokens', 256),
                'temperature': data.get('temperature', 0.7),
                'stop': data.get('stop', [])
            },
            timeout=180  # 3 minuti per generazioni lunghe
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
@jwt_required()
def end_session(data):
    """Termina sessione manualmente."""
    session = Session.query.get(data['session_id'])
    if session and session.user_id == get_jwt_identity():
        # Ferma la sessione sul nodo
        if session.node_id and session.node_id != 'pending':
            get_node_manager().stop_remote_session(session.node_id, session.id)
        
        session.active = False
        db.session.commit()
        leave_room(session.id)
        emit('session_ended', room=data['session_id'])

# Admin routes
@app.route('/admin/nodes')
@jwt_required()
def list_nodes():
    """Lista tutti i nodi (solo admin)."""
    user_id = get_jwt_identity()
    if not User.query.get(user_id).is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    nodes = get_node_manager().get_all_nodes()
    # Converti bytes in stringhe per JSON serialization
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
    """Riceve heartbeat da un nodo."""
    data = request.get_json()
    node_id = data.get('node_id')
    
    if not node_id:
        return jsonify({'error': 'Missing node_id'}), 400
    
    nm = get_node_manager()
    nm.node_heartbeat(node_id)
    
    # Aggiorna anche il carico se fornito
    if 'load' in data:
        nm.redis.hset(f"node:{node_id}", 'load', data['load'])
    
    return jsonify({'status': 'ok'})


# Background job per cleanup sessioni scadute
def cleanup_expired_sessions():
    """Pulisce le sessioni scadute."""
    with app.app_context():
        expired = Session.query.filter(
            Session.active == True,
            Session.expires_at < datetime.utcnow()
        ).all()
        
        nm = get_node_manager()
        for session in expired:
            current_app.logger.info(f"Cleaning up expired session {session.id}")
            
            # Ferma la sessione sul nodo
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
    """Avvia lo scheduler per il cleanup periodico."""
    import threading
    
    def run_cleanup():
        while True:
            try:
                cleanup_expired_sessions()
            except Exception as e:
                print(f"Cleanup error: {e}")
            # Esegui ogni minuto
            threading.Event().wait(60)
    
    thread = threading.Thread(target=run_cleanup, daemon=True)
    thread.start()


# CLI commands
@app.cli.command('init-db')
def init_db():
    """Inizializza il database."""
    db.create_all()
    print('Initialized database.')


@app.cli.command('cleanup-sessions')
def cleanup_sessions_cmd():
    """Pulisce manualmente le sessioni scadute."""
    cleanup_expired_sessions()
    print('Cleanup completed.')


@app.cli.command('create-admin')
@click.argument('username')
@click.argument('password')
def create_admin(username, password):
    """Crea un utente admin."""
    user = User(username=username, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f'Admin user {username} created.')
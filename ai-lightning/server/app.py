"""
Applicazione Flask principale.

Gestisce autenticazione, API, WebSocket e logica business.
"""
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from .config import Config
from .models import db, User, Session, Node
from .lightning import LightningManager
from .nodemanager import NodeManager
from .utils.helpers import validate_model, get_model_price
import datetime
import httpx

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt = JWTManager(app)
lm = LightningManager()
node_manager = NodeManager()

@app.route('/')
def index():
    """Pagina principale (web client)."""
    return render_template('index.html')

# Auth routes
@app.route('/api/register', methods=['POST'])
def register():
    """Registrazione utente."""
    data = request.get_json()
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already taken'}), 400

    user = User(username=data['username'])
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'Registered successfully'})

@app.route('/api/login', methods=['POST'])
def login():
    """Login utente."""
    data = request.get_json()
    user = User.query.filter_by(username=data['username']).first()
    if not user or not user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify({'access_token': access_token})

# Session routes
@app.route('/api/new_session', methods=['POST'])
@jwt_required()
def new_session():
    """Crea una nuova sessione."""
    user_id = get_jwt_identity()
    data = request.get_json()

    # Valida input
    if data['model'] not in Config.AVAILABLE_MODELS:
        return jsonify({'error': 'Invalid model'}), 400

    minutes = data['minutes']
    if minutes < 1 or minutes > 120:
        return jsonify({'error': 'Minutes must be between 1 and 120'}), 400

    # Crea fattura
    amount = get_model_price(data['model']) * minutes
    invoice = lm.create_invoice(
        amount,
        f"AI access: {data['model']} for {minutes} minutes"
    )

    # Crea sessione nel DB (pending payment)
    session = Session(
        user_id=user_id,
        node_id='pending',
        model=data['model'],
        payment_hash=invoice['r_hash'],
        expires_at=datetime.utcnow() + datetime.timedelta(minutes=minutes)
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
    node_id = node_manager.register_node(
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

    if not lm.check_payment(session.payment_hash):
        emit('error', {'message': 'Payment not received'})
        return

    if session.expired:
        emit('error', {'message': 'Session expired'})
        return

    # Trova un nodo disponibile
    node = node_manager.get_available_node(session.model)
    if not node:
        emit('error', {'message': 'No available nodes'})
        return

    # Avvia sessione sul nodo
    try:
        node_info = node_manager.start_remote_session(
            node[b'id'].decode(),
            session.id,
            session.model,
            Config.AVAILABLE_MODELS[session.model]['context']
        )

        # Aggiorna sessione
        session.node_id = node[b'id'].decode()
        session.active = True
        db.session.commit()

        # Paga il nodo
        amount = int(get_model_price(session.model) * session.minutes * Config.NODE_PAYMENT_RATIO)
        node_manager.pay_node(
            session.node_id,
            amount,
            f"Payment for session {session.id}"
        )

        join_room(session.id)
        emit('session_started', {
            'node_id': node[b'id'].decode(),
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
    node = node_manager.get_all_nodes(session.node_id)
    if not node or not node_manager.check_node_status(session.node_id):
        emit('error', {'message': 'Node not available'})
        return

    # In produzione: inoltra al nodo
    # Per ora simuliamo una risposta
    response = f"Response from {session.model} model: {data['prompt']}"

    emit('ai_response', {
        'response': response,
        'model': session.model
    }, room=data['session_id'])

@socketio.on('end_session')
@jwt_required()
def end_session(data):
    """Termina sessione manualmente."""
    session = Session.query.get(data['session_id'])
    if session and session.user_id == get_jwt_identity():
        session.active = False
        db.session.commit()
        emit('session_ended', room=data['session_id'])

# Admin routes
@app.route('/admin/nodes')
@jwt_required()
def list_nodes():
    """Lista tutti i nodi (solo admin)."""
    user_id = get_jwt_identity()
    if not User.query.get(user_id).is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    nodes = node_manager.get_all_nodes()
    return jsonify([dict(n) for n in nodes])

# CLI commands
@app.cli.command('init-db')
def init_db():
    """Inizializza il database."""
    db.create_all()
    print('Initialized database.')
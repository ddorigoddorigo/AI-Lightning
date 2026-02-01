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
import json

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

    access_token = create_access_token(identity=str(user.id))
    logger.info(f"User {user.username} logged in, token created for id={user.id}")
    return jsonify({'access_token': access_token})


@app.route('/api/me', methods=['GET'])
@jwt_required()
def get_user_profile():
    """Restituisce informazioni sull'utente corrente incluso il balance."""
    user_id = get_jwt_identity()
    logger.info(f"/api/me called with identity: {user_id} (type: {type(user_id).__name__})")
    
    # Converti a int se necessario
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
    
    # Conta sessioni attive
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
        'created_at': user.created_at.isoformat() if user.created_at else None
    })


@app.route('/api/add_test_balance', methods=['POST'])
@jwt_required()
def add_test_balance():
    """
    Aggiunge balance di test (solo per development/testnet).
    In produzione questo endpoint dovrebbe essere disabilitato o protetto.
    """
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        amount = data.get('amount', 10000)  # Default 10000 sats
        
        # Limite per evitare abusi
        if amount > 1000000:  # Max 1M sats per richiesta
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


@app.route('/api/models/available', methods=['GET'])
def get_available_models():
    """
    Restituisce lista aggregata di tutti i modelli disponibili dai nodi online.
    Non richiede autenticazione.
    """
    models_map = {}  # model_id -> model_info + nodes_count
    
    # Raccogli modelli dai nodi WebSocket connessi
    for node_id, info in connected_nodes.items():
        node_models = info.get('models', [])
        hardware = info.get('hardware', {})
        node_name = info.get('name', node_id)
        
        for model in node_models:
            if isinstance(model, dict):
                # Nuovo formato con info complete
                model_id = model.get('id', model.get('name', 'unknown'))
                
                if model_id not in models_map:
                    models_map[model_id] = {
                        'id': model_id,
                        'name': model.get('name', model_id),
                        'parameters': model.get('parameters', 'Unknown'),
                        'quantization': model.get('quantization', 'Unknown'),
                        'context_length': model.get('context_length', 4096),
                        'architecture': model.get('architecture', 'unknown'),
                        'size_gb': model.get('size_gb', 0),
                        'min_vram_mb': model.get('min_vram_mb', 0),
                        'nodes_count': 0,
                        'nodes': []
                    }
                
                models_map[model_id]['nodes_count'] += 1
                models_map[model_id]['nodes'].append({
                    'node_id': node_id,
                    'node_name': node_name,
                    'vram_available': hardware.get('total_vram_mb', 0)
                })
            else:
                # Vecchio formato - solo nome modello
                model_name = str(model)
                if model_name not in models_map:
                    models_map[model_name] = {
                        'id': model_name,
                        'name': model_name,
                        'parameters': 'Unknown',
                        'quantization': 'Unknown',
                        'context_length': 4096,
                        'architecture': 'unknown',
                        'nodes_count': 0,
                        'nodes': []
                    }
                
                models_map[model_name]['nodes_count'] += 1
                models_map[model_name]['nodes'].append({
                    'node_id': node_id,
                    'node_name': node_name
                })
    
    # Converti in lista e ordina per disponibilità (più nodi = più affidabile)
    models_list = list(models_map.values())
    models_list.sort(key=lambda x: (-x['nodes_count'], x['name']))
    
    return jsonify({
        'models': models_list,
        'total_nodes_online': len(connected_nodes),
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/api/nodes/online', methods=['GET'])
def get_online_nodes():
    """
    Restituisce lista dei nodi online con le loro info hardware.
    Non richiede autenticazione.
    """
    nodes = []
    
    for node_id, info in connected_nodes.items():
        hardware = info.get('hardware', {})
        models = info.get('models', [])
        
        nodes.append({
            'node_id': node_id,
            'name': info.get('name', node_id),
            'models_count': len(models),
            'hardware': {
                'cpu': hardware.get('cpu', {}).get('name', 'Unknown'),
                'cpu_cores': hardware.get('cpu', {}).get('cores_logical', 0),
                'ram_gb': hardware.get('ram', {}).get('total_gb', 0),
                'gpus': [
                    {
                        'name': gpu.get('name', 'Unknown'),
                        'vram_mb': gpu.get('vram_total_mb', 0),
                        'type': gpu.get('type', 'unknown')
                    }
                    for gpu in hardware.get('gpus', [])
                ],
                'total_vram_mb': hardware.get('total_vram_mb', 0)
            }
        })
    
    return jsonify({
        'nodes': nodes,
        'count': len(nodes),
        'timestamp': datetime.utcnow().isoformat()
    })

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
    model_requested = data['model']

    # Verifica che ci sia almeno un nodo con questo modello
    node_with_model = None
    model_price = None
    
    for node_id, info in connected_nodes.items():
        node_models = info.get('models', [])
        
        # I modelli possono essere una lista di oggetti o una lista di stringhe
        for model in node_models:
            model_id = None
            found_price = None
            
            if isinstance(model, dict):
                # Nuovo formato: {id, name, path, ...}
                model_id = model.get('id') or model.get('name')
                found_price = model.get('price_per_minute')
            else:
                # Vecchio formato: stringa
                model_id = str(model)
            
            if model_id == model_requested:
                node_with_model = node_id
                model_price = found_price
                break
        
        if node_with_model:
            break
    
    if not node_with_model:
        return jsonify({'error': f'No node available with model: {model_requested}'}), 404

    # Valida minuti
    try:
        minutes = int(data['minutes'])
    except (ValueError, TypeError):
        return jsonify({'error': 'Minutes must be a number'}), 400
    
    if minutes < 1 or minutes > 120:
        return jsonify({'error': 'Minutes must be between 1 and 120'}), 400

    # Crea fattura (usa prezzo dal nodo se disponibile)
    amount = get_model_price(model_requested, model_price) * minutes
    invoice = get_lightning_manager().create_invoice(
        amount,
        f"AI access: {model_requested} for {minutes} minutes"
    )

    # Crea sessione nel DB (pending payment)
    session = Session(
        user_id=user_id,
        node_id='pending',
        model=model_requested,
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

    # Prima cerca un nodo WebSocket disponibile (dietro NAT)
    ws_node_id, ws_sid = get_websocket_node(session.model)
    
    if ws_node_id:
        # Usa nodo WebSocket
        try:
            session.node_id = ws_node_id
            session.active = True
            db.session.commit()
            
            # Ottieni context dalla config o usa default
            context = 4096
            if session.model in Config.AVAILABLE_MODELS:
                context = Config.AVAILABLE_MODELS[session.model].get('context', 4096)
            
            # Invia richiesta al nodo
            socketio.emit('start_session', {
                'session_id': session.id,
                'model': session.model,
                'model_id': session.model,  # Per il nuovo sistema
                'model_name': session.model,
                'context': context
            }, room=f"node_{ws_node_id}")
            
            join_room(str(session.id))
            emit('session_started', {
                'session_id': session.id,
                'node_id': ws_node_id,
                'expires_at': session.expires_at.isoformat()
            })
            
            logger.info(f"Session {session.id} started on WebSocket node {ws_node_id}")
            return
            
        except Exception as e:
            current_app.logger.error(f"Failed to start session on WS node: {e}")
            # Prova con nodo HTTP

    # Fallback: cerca nodo HTTP tradizionale
    nm = get_node_manager()
    node = nm.get_available_node(session.model)
    if not node:
        emit('error', {'message': 'No available nodes'})
        return

    # Avvia sessione sul nodo HTTP
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

    # Verifica se il nodo è connesso via WebSocket
    if session.node_id in connected_nodes:
        # Inoltra al nodo WebSocket
        socketio.emit('inference_request', {
            'session_id': session.id,
            'prompt': data['prompt'],
            'max_tokens': data.get('max_tokens', 256),
            'temperature': data.get('temperature', 0.7),
            'stop': data.get('stop', [])
        }, room=f"node_{session.node_id}")
        return

    # Altrimenti usa HTTP (nodo tradizionale)
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


# ============================================
# WebSocket handlers per nodi dietro NAT
# ============================================

# Dizionario per mappare node_id -> socket_id e info
# node_id -> {'sid': socket_id, 'models': [...], 'hardware': {...}, 'name': str}
connected_nodes = {}  
pending_requests = {}  # request_id -> {'session_id': ..., 'user_sid': ...}


@socketio.on('node_register')
def handle_node_register(data):
    """Registra un nodo connesso via WebSocket."""
    token = data.get('token', '')
    models = data.get('models', [])
    hardware = data.get('hardware', {})
    node_name = data.get('name', '')
    
    # Genera o valida node_id
    node_id = None
    if token:
        # Cerca nodo esistente con questo token
        nm = get_node_manager()
        for nid in nm.redis.smembers(nm.nodes_set_key):
            nid_str = nid.decode() if isinstance(nid, bytes) else nid
            node_data = nm.redis.hgetall(f"node:{nid_str}")
            if node_data.get(b'token', b'').decode() == token:
                node_id = nid_str
                break
    
    if not node_id:
        # Nuovo nodo
        import uuid
        node_id = f"node-ws-{uuid.uuid4().hex[:8]}"
        token = uuid.uuid4().hex
        
        nm = get_node_manager()
        nm.redis.hset(f"node:{node_id}", mapping={
            'id': node_id,
            'token': token,
            'name': node_name or node_id,
            'models': json.dumps(models) if models else '[]',
            'hardware': json.dumps(hardware) if hardware else '{}',
            'status': 'online',
            'type': 'websocket',
            'last_ping': datetime.utcnow().timestamp(),
            'load': 0
        })
        nm.redis.sadd(nm.nodes_set_key, node_id)
    else:
        # Aggiorna nodo esistente
        nm = get_node_manager()
        update_data = {
            'status': 'online',
            'last_ping': datetime.utcnow().timestamp(),
        }
        if models:
            update_data['models'] = json.dumps(models)
        if hardware:
            update_data['hardware'] = json.dumps(hardware)
        if node_name:
            update_data['name'] = node_name
        nm.redis.hset(f"node:{node_id}", mapping=update_data)
    
    # Registra nella mappa connessioni
    connected_nodes[node_id] = {
        'sid': request.sid,
        'models': models,
        'hardware': hardware,
        'name': node_name or node_id
    }
    
    join_room(f"node_{node_id}")
    
    # Calcola VRAM totale
    total_vram = hardware.get('total_vram_mb', 0) if hardware else 0
    gpu_count = len(hardware.get('gpus', [])) if hardware else 0
    
    logger.info(f"Node {node_id} ({node_name}) registered via WebSocket - {len(models)} models, {gpu_count} GPUs, {total_vram}MB VRAM")
    
    emit('node_registered', {
        'node_id': node_id,
        'token': token
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Gestione disconnessione - aggiornata per nodi."""
    # Rimuovi nodo dalla mappa se era connesso
    for node_id, info in list(connected_nodes.items()):
        if info['sid'] == request.sid:
            del connected_nodes[node_id]
            
            # Marca nodo offline
            nm = get_node_manager()
            nm.redis.hset(f"node:{node_id}", 'status', 'offline')
            
            logger.info(f"Node {node_id} disconnected")
            break
    
    if Config.DEBUG:
        current_app.logger.info(f'Client disconnected: {request.sid}')


@socketio.on('session_started')
def handle_node_session_started(data):
    """Nodo conferma che la sessione è partita."""
    session_id = str(data['session_id'])
    
    logger.info(f"Node confirms session {session_id} started")
    
    # Notifica il client utente
    emit('session_ready', {'session_id': session_id}, room=session_id)


@socketio.on('session_error')
def handle_node_session_error(data):
    """Nodo riporta errore nell'avvio sessione."""
    session_id = str(data['session_id'])
    error = data.get('error', 'Unknown error')
    
    logger.error(f"Node error for session {session_id}: {error}")
    
    emit('error', {'message': f'Node error: {error}'}, room=session_id)


@socketio.on('inference_response')
def handle_inference_response(data):
    """Nodo invia risposta inferenza."""
    session_id = str(data['session_id'])
    content = data.get('content', '')
    
    emit('ai_response', {
        'response': content,
        'session_id': session_id
    }, room=session_id)


@socketio.on('inference_error')
def handle_inference_error(data):
    """Nodo riporta errore inferenza."""
    session_id = str(data['session_id'])
    error = data.get('error', 'Unknown error')
    
    emit('error', {'message': f'Inference error: {error}'}, room=session_id)


@socketio.on('node_models_update')
def handle_node_models_update(data):
    """Nodo aggiorna lista modelli disponibili."""
    node_id = data.get('node_id')
    models = data.get('models', [])
    hardware = data.get('hardware')
    
    if not node_id:
        # Cerca node_id dal socket id
        for nid, info in connected_nodes.items():
            if info['sid'] == request.sid:
                node_id = nid
                break
    
    if not node_id or node_id not in connected_nodes:
        emit('error', {'message': 'Node not registered'})
        return
    
    # Aggiorna modelli nel connected_nodes
    connected_nodes[node_id]['models'] = models
    if hardware:
        connected_nodes[node_id]['hardware'] = hardware
    
    # Aggiorna anche in Redis
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
    """Heartbeat dal nodo per mantenere connessione attiva."""
    node_id = data.get('node_id')
    
    if not node_id:
        for nid, info in connected_nodes.items():
            if info['sid'] == request.sid:
                node_id = nid
                break
    
    if node_id and node_id in connected_nodes:
        nm = get_node_manager()
        nm.redis.hset(f"node:{node_id}", 'last_ping', datetime.utcnow().timestamp())
        emit('heartbeat_ack', {'timestamp': datetime.utcnow().isoformat()})


def get_websocket_node(model_query):
    """
    Trova un nodo WebSocket disponibile per il modello.
    
    model_query può essere:
    - Nome modello (vecchio formato)
    - ID modello (nuovo formato)
    - Nome parziale per matching fuzzy
    """
    for node_id, info in connected_nodes.items():
        node_models = info.get('models', [])
        
        for model in node_models:
            if isinstance(model, dict):
                # Nuovo formato
                model_id = model.get('id', '')
                model_name = model.get('name', '')
                
                if (model_query == model_id or 
                    model_query == model_name or
                    model_query.lower() in model_name.lower()):
                    return node_id, info['sid']
            else:
                # Vecchio formato - stringa
                if model_query == model or model_query.lower() in str(model).lower():
                    return node_id, info['sid']
    
    return None, None


def get_websocket_node_for_model_id(model_id):
    """Trova un nodo WebSocket per uno specifico model_id."""
    for node_id, info in connected_nodes.items():
        for model in info.get('models', []):
            if isinstance(model, dict) and model.get('id') == model_id:
                return node_id, info['sid'], model
            elif str(model) == model_id:
                return node_id, info['sid'], {'name': model}
    return None, None, None


# ============================================


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
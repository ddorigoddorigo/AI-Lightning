"""
Applicazione Flask principale.

Gestisce autenticazione, API, WebSocket e logica business.
"""
from flask import Flask, render_template, request, jsonify, current_app
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity,
    decode_token
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
    """Pagina principale (web client)."""
    return render_template('index.html')

# ============================================
# Auto-Update API
# ============================================

# Versione corrente del node-client
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


def get_busy_node_ids():
    """
    Restituisce l'insieme degli ID dei nodi attualmente in uso (con sessioni attive).
    Un nodo è considerato "in uso" se ha almeno una sessione attiva non scaduta.
    """
    busy_nodes = set()
    
    # Query per sessioni attive
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
    Restituisce un dizionario con info sui nodi occupati, incluso il tempo rimanente.
    Returns: {node_id: {'expires_at': datetime, 'seconds_remaining': int, 'model': str}}
    """
    busy_info = {}
    
    # Query per sessioni attive
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
            'expires_at': session.expires_at.isoformat(),
            'seconds_remaining': max(0, seconds_remaining),
            'model': session.model
        }
    
    return busy_info


@app.route('/api/models/available', methods=['GET'])
def get_available_models():
    """
    Restituisce lista aggregata di tutti i modelli disponibili dai nodi online.
    Include sia modelli disponibili che quelli su nodi occupati (con timer).
    Non richiede autenticazione.
    """
    available_models = {}  # model_id -> model_info per modelli disponibili
    busy_models = {}  # model_id -> model_info per modelli su nodi occupati
    
    # Ottieni info sui nodi occupati (con tempo rimanente)
    busy_nodes_info = get_busy_nodes_info()
    busy_node_ids = set(busy_nodes_info.keys())
    available_nodes_count = 0
    
    # Raccogli modelli da TUTTI i nodi WebSocket connessi
    for node_id, info in connected_nodes.items():
        is_busy = node_id in busy_node_ids
        
        if not is_busy:
            available_nodes_count += 1
            
        node_models = info.get('models', [])
        hardware = info.get('hardware', {})
        node_name = info.get('name', node_id)
        
        # Scegli quale dizionario usare
        target_map = busy_models if is_busy else available_models
        
        for model in node_models:
            if isinstance(model, dict):
                # Nuovo formato con info complete
                model_id = model.get('id', model.get('name', 'unknown'))
                
                if model_id not in target_map:
                    target_map[model_id] = {
                        'id': model_id,
                        'name': model.get('name', model_id),
                        'parameters': model.get('parameters', 'Unknown'),
                        'quantization': model.get('quantization', 'Unknown'),
                        'context_length': model.get('context_length', 4096),
                        'architecture': model.get('architecture', 'unknown'),
                        'size_gb': model.get('size_gb', 0),
                        'min_vram_mb': model.get('min_vram_mb', 0),
                        'available': not is_busy,
                        'nodes_count': 0,
                        'nodes': []
                    }
                
                target_map[model_id]['nodes_count'] += 1
                node_info = {
                    'node_id': node_id,
                    'node_name': node_name,
                    'vram_available': hardware.get('total_vram_mb', 0)
                }
                
                # Aggiungi info timer se occupato
                if is_busy and node_id in busy_nodes_info:
                    node_info['busy'] = True
                    node_info['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    node_info['expires_at'] = busy_nodes_info[node_id]['expires_at']
                    # Aggiungi anche al modello stesso per facile accesso
                    target_map[model_id]['seconds_remaining'] = busy_nodes_info[node_id]['seconds_remaining']
                    target_map[model_id]['expires_at'] = busy_nodes_info[node_id]['expires_at']
                
                target_map[model_id]['nodes'].append(node_info)
            else:
                # Vecchio formato - solo nome modello
                model_name = str(model)
                if model_name not in target_map:
                    target_map[model_name] = {
                        'id': model_name,
                        'name': model_name,
                        'parameters': 'Unknown',
                        'quantization': 'Unknown',
                        'context_length': 4096,
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
    
    # Converti in liste e ordina
    available_list = list(available_models.values())
    available_list.sort(key=lambda x: (-x['nodes_count'], x['name']))
    
    busy_list = list(busy_models.values())
    busy_list.sort(key=lambda x: (x.get('seconds_remaining', 0), x['name']))
    
    return jsonify({
        'models': available_list,  # Modelli disponibili (retrocompatibilità)
        'busy_models': busy_list,  # Modelli su nodi occupati con timer
        'total_nodes_online': len(connected_nodes),
        'available_nodes': available_nodes_count,
        'busy_nodes': len(busy_node_ids),
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/api/nodes/online', methods=['GET'])
def get_online_nodes():
    """
    Restituisce lista dei nodi online con le loro info hardware.
    Indica anche se il nodo è attualmente in uso.
    Non richiede autenticazione.
    """
    nodes = []
    busy_nodes_info = get_busy_nodes_info()
    busy_node_ids = set(busy_nodes_info.keys())
    
    for node_id, info in connected_nodes.items():
        hardware = info.get('hardware', {})
        models = info.get('models', [])
        is_busy = node_id in busy_node_ids
        
        # Estrai info RAM
        ram_info = hardware.get('ram', {})
        ram_gb = ram_info.get('total_gb', 0)
        ram_speed = ram_info.get('speed_mhz', 0)
        ram_type = ram_info.get('type', '')
        
        # Estrai info disco
        disk_info = hardware.get('disk', {})
        
        node_data = {
            'node_id': node_id,
            'name': info.get('name', node_id),
            'models': models,  # Lista completa modelli
            'models_count': len(models),
            'status': 'busy' if is_busy else 'available',
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
    try:
        user_id = get_jwt_identity()
        
        # Converti user_id a int
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid token'}), 401
            
        data = request.get_json()
        model_requested = data['model']
        requested_node_id = data.get('node_id')  # Nodo specifico richiesto
        hf_repo = data.get('hf_repo')  # HuggingFace repo per modelli custom
        
        logger.info(f"New session request: user={user_id}, model={model_requested}, node_id={requested_node_id}, hf_repo={hf_repo}")

        # Se è specificato un node_id, verifica che sia online
        node_with_model = None
        model_price = None
        
        if requested_node_id:
            # Nodo specifico richiesto
            if requested_node_id in connected_nodes:
                info = connected_nodes[requested_node_id]
                
                # Se è un modello HuggingFace custom, accetta sempre (verrà scaricato)
                if hf_repo:
                    node_with_model = requested_node_id
                    model_price = None  # Default price
                else:
                    # Verifica che il nodo abbia il modello
                    node_models = info.get('models', [])
                    for model in node_models:
                        model_id = None
                        found_price = None
                        
                        if isinstance(model, dict):
                            model_id = model.get('id') or model.get('name')
                            found_price = model.get('price_per_minute')
                        else:
                            model_id = str(model)
                        
                        if model_id == model_requested:
                            node_with_model = requested_node_id
                            model_price = found_price
                            break
                    
                    if not node_with_model:
                        logger.warning(f"Requested node {requested_node_id} doesn't have model {model_requested}")
                        return jsonify({'error': f'Selected node does not have model: {model_requested}'}), 404
            else:
                logger.warning(f"Requested node {requested_node_id} is not online")
                return jsonify({'error': 'Selected node is not online'}), 404
        else:
            # Nessun nodo specifico: cerca automaticamente
            for node_id, info in connected_nodes.items():
                node_models = info.get('models', [])
                
                for model in node_models:
                    model_id = None
                    found_price = None
                    
                    if isinstance(model, dict):
                        model_id = model.get('id') or model.get('name')
                        found_price = model.get('price_per_minute')
                    else:
                        model_id = str(model)
                    
                    if model_id == model_requested:
                        node_with_model = node_id
                        model_price = found_price
                        break
                
                if node_with_model:
                    break
        
        if not node_with_model:
            logger.warning(f"No node with model {model_requested}")
            return jsonify({'error': f'No node available with model: {model_requested}'}), 404

        # Valida minuti
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

        # Crea fattura (usa prezzo dal nodo se disponibile)
        amount = get_model_price(model_requested, model_price) * minutes
        
        try:
            invoice = get_lightning_manager().create_invoice(
                amount,
                f"AI access: {model_requested} for {minutes} minutes"
            )
        except Exception as e:
            logger.error(f"Lightning invoice creation failed: {e}")
            return jsonify({'error': 'Lightning Network unavailable. Please try again later.'}), 503

        # Crea sessione nel DB (pending payment)
        # Salva il nodo target per l'assegnazione dopo il pagamento
        session = Session(
            user_id=user_id,
            node_id='pending',
            model=model_requested,
            payment_hash=invoice['r_hash'],
            expires_at=datetime.utcnow() + timedelta(minutes=minutes),
            context_length=context_length
        )
        
        # Memorizza il nodo target nel pending_sessions per l'assegnazione
        # dopo il pagamento
        pending_sessions[invoice['r_hash']] = {
            'session_id': None,  # Sarà aggiornato dopo commit
            'target_node_id': node_with_model,
            'hf_repo': hf_repo
        }
        
        db.session.add(session)
        db.session.commit()
        
        # Aggiorna pending_sessions con session_id
        pending_sessions[invoice['r_hash']]['session_id'] = session.id
        
        logger.info(f"Session {session.id} created, invoice amount: {amount} sats, target_node: {node_with_model}")

        return jsonify({
            'invoice': invoice['payment_request'],
            'session_id': session.id,
            'amount': invoice['amount'],
            'expires_at': session.expires_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to create session'}), 500

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
def handle_connect(auth=None):
    """Gestione connessione WebSocket."""
    sid = request.sid
    
    # Try to get token from auth parameter
    token = None
    if auth and 'token' in auth:
        token = auth['token']
    
    # Try to get from query params
    if not token:
        token = request.args.get('token')
    
    if token:
        try:
            decoded = decode_token(token)
            user_id = decoded.get('sub')
            if user_id:
                socket_users[sid] = int(user_id) if isinstance(user_id, str) else user_id
                if Config.DEBUG:
                    current_app.logger.info(f'Client {sid} authenticated as user {user_id}')
        except Exception as e:
            current_app.logger.warning(f'Failed to decode token for {sid}: {e}')
    
    if Config.DEBUG:
        current_app.logger.info(f'Client connected: {sid}')

@socketio.on('disconnect')
def handle_disconnect():
    """Gestione disconnessione."""
    sid = request.sid
    if sid in socket_users:
        del socket_users[sid]
    if Config.DEBUG:
        current_app.logger.info(f'Client disconnected: {sid}')

@socketio.on('start_session')
def start_session(data):
    """Avvia una sessione dopo pagamento."""
    user_id = get_socket_user_id()
    if not user_id:
        emit('error', {'message': 'Authentication required'})
        return
    session = Session.query.get(data['session_id'])

    # Validazioni
    if not session or session.user_id != user_id:
        emit('error', {'message': 'Invalid session'})
        return

    if session.node_id != 'pending':
        emit('error', {'message': 'Session already started'})
        return

    # In DEBUG mode, skip payment check for testing
    payment_verified = Config.DEBUG or get_lightning_manager().check_payment(session.payment_hash)
    if not payment_verified:
        emit('error', {'message': 'Payment not received'})
        return

    if session.expired:
        emit('error', {'message': 'Session expired'})
        return

    # Controlla se c'è un nodo target specifico in pending_sessions
    target_node_id = None
    hf_repo = None
    if session.payment_hash in pending_sessions:
        pending_info = pending_sessions[session.payment_hash]
        target_node_id = pending_info.get('target_node_id')
        hf_repo = pending_info.get('hf_repo')
        # Rimuovi da pending_sessions
        del pending_sessions[session.payment_hash]
    
    # Se c'è un target node specifico, usa quello
    ws_node_id = None
    ws_sid = None
    
    if target_node_id and target_node_id in connected_nodes:
        # Verifica che il nodo target sia ancora disponibile (non occupato)
        busy_nodes = get_busy_node_ids()
        if target_node_id not in busy_nodes:
            ws_node_id = target_node_id
            ws_sid = connected_nodes[target_node_id]['sid']
        else:
            emit('error', {'message': 'Selected node is currently busy'})
            return
    else:
        # Fallback: cerca un nodo WebSocket disponibile (dietro NAT)
        ws_node_id, ws_sid = get_websocket_node(session.model)
    
    if ws_node_id:
        # Usa nodo WebSocket
        try:
            session.node_id = ws_node_id
            session.active = True
            db.session.commit()
            
            # Ottieni context dal modello registrato dal nodo
            context = 4096  # Default
            if ws_node_id in connected_nodes:
                node_models = connected_nodes[ws_node_id].get('models', [])
                for m in node_models:
                    if isinstance(m, dict):
                        model_id = m.get('id', m.get('name', ''))
                        if model_id == session.model or m.get('name') == session.model:
                            context = m.get('context_length', m.get('context', 4096))
                            break
            
            # Usa il context_length della sessione (scelto dall'utente) se disponibile
            if hasattr(session, 'context_length') and session.context_length:
                context = session.context_length
            
            # Invia richiesta al nodo
            start_data = {
                'session_id': session.id,
                'model': session.model,
                'model_id': session.model,  # Per il nuovo sistema
                'model_name': session.model,
                'context': context
            }
            
            # Se è un modello HuggingFace custom, aggiungi il repo
            if hf_repo:
                start_data['hf_repo'] = hf_repo
                logger.info(f"Session {session.id} will download HF model: {hf_repo}")
            
            socketio.emit('start_session', start_data, room=f"node_{ws_node_id}")
            
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

        join_room(str(session.id))
        emit('session_started', {
            'session_id': session.id,
            'node_id': node_id_str,
            'expires_at': session.expires_at.isoformat()
        })

    except Exception as e:
        current_app.logger.error(f"Failed to start session: {e}")
        emit('error', {'message': 'Failed to start session'})

@socketio.on('chat_message')
def handle_message(data):
    """Gestione messaggi chat."""
    user_id = get_socket_user_id()
    if not user_id:
        emit('error', {'message': 'Authentication required'})
        return
    
    session = Session.query.get(data['session_id'])

    if not session or not session.active or session.expired:
        emit('error', {'message': 'Invalid session'})
        return

    # Verifica se il nodo è connesso via WebSocket
    if session.node_id in connected_nodes:
        # Inoltra al nodo WebSocket con streaming abilitato e tutti i parametri LLM
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
                'max_tokens': data.get('max_tokens', 2048),
                'temperature': data.get('temperature', 0.7),
                'top_k': data.get('top_k', 40),
                'top_p': data.get('top_p', 0.95),
                'repeat_penalty': data.get('repeat_penalty', 1.1),
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
def end_session(data):
    """Termina sessione manualmente."""
    user_id = get_socket_user_id()
    if not user_id:
        emit('error', {'message': 'Authentication required'})
        return
    
    session_id = data.get('session_id')
    session = Session.query.get(session_id)
    
    if session and session.user_id == user_id:
        logger.info(f"Ending session {session.id}, node_id={session.node_id}")
        
        # Ferma la sessione sul nodo
        if session.node_id and session.node_id != 'pending':
            node_id = session.node_id
            
            # Debug: mostra i nodi connessi
            logger.info(f"Connected nodes: {list(connected_nodes.keys())}")
            
            # Controlla se è un nodo WebSocket
            if node_id in connected_nodes:
                node_info = connected_nodes[node_id]
                node_sid = node_info.get('sid')
                
                # Invia stop_session direttamente al socket del nodo
                logger.info(f"Sending stop_session to node {node_id} (sid: {node_sid})")
                
                # Usa to= invece di room= per inviare direttamente al sid del nodo
                socketio.emit('stop_session', {
                    'session_id': str(session.id)
                }, to=node_sid)
                
                logger.info(f"Sent stop_session to WebSocket node {node_id} for session {session.id}")
            else:
                # Usa HTTP per nodi tradizionali
                logger.info(f"Node {node_id} not in connected_nodes, trying HTTP")
                get_node_manager().stop_remote_session(node_id, session.id)
        
        # Salva node_id prima di marcare inattiva
        freed_node_id = session.node_id
        
        session.active = False
        db.session.commit()
        
        # Aggiorna statistiche nodo (sessione completata)
        if freed_node_id and freed_node_id != 'pending' and freed_node_id in connected_nodes:
            # Calcola minuti attivi (se abbiamo start time)
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
        
        # Notifica a TUTTI i client che il nodo è ora disponibile
        # Questo aggiorna immediatamente la lista modelli per tutti
        socketio.emit('node_freed', {
            'node_id': freed_node_id,
            'message': 'Node is now available'
        })
        
        logger.info(f"Session {session.id} ended by user {user_id}, node {freed_node_id} freed")

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
# Node Statistics API
# ============================================

@app.route('/api/node/stats/<node_id>', methods=['GET'])
def get_node_stats(node_id):
    """Ottieni statistiche di un nodo."""
    from models import NodeStats
    
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        # Crea statistiche vuote se non esistono
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
    """Aggiorna statistiche di un nodo (chiamato internamente)."""
    from models import NodeStats
    
    data = request.get_json()
    
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        stats = NodeStats(node_id=node_id)
        db.session.add(stats)
    
    # Aggiorna campi se presenti
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
        # Media mobile per performance
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


def update_node_stats_internal(node_id, **kwargs):
    """Helper per aggiornare statistiche internamente."""
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


# ============================================
# WebSocket handlers per nodi dietro NAT
# ============================================

# Dizionario per mappare node_id -> socket_id e info
# node_id -> {'sid': socket_id, 'models': [...], 'hardware': {...}, 'name': str}
connected_nodes = {}  
pending_requests = {}  # request_id -> {'session_id': ..., 'user_sid': ...}
pending_sessions = {}  # payment_hash -> {'session_id': ..., 'target_node_id': ..., 'hf_repo': ...}


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
    
    # Aggiorna statistiche nodo (first_online, last_online)
    from models import NodeStats
    stats = NodeStats.query.filter_by(node_id=node_id).first()
    if not stats:
        stats = NodeStats(node_id=node_id, first_online=datetime.utcnow())
        db.session.add(stats)
    stats.last_online = datetime.utcnow()
    db.session.commit()
    
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
    node_id = data.get('node_id')
    
    logger.info(f"Node confirms session {session_id} started")
    
    # Aggiorna statistiche nodo
    if node_id:
        update_node_stats_internal(node_id, add_session=True)
    
    # Notifica il client utente
    emit('session_ready', {'session_id': session_id}, room=session_id)


@socketio.on('session_error')
def handle_node_session_error(data):
    """Nodo riporta errore nell'avvio sessione."""
    session_id = str(data['session_id'])
    error = data.get('error', 'Unknown error')
    node_id = data.get('node_id')
    
    logger.error(f"Node error for session {session_id}: {error}")
    
    # Aggiorna statistiche nodo (sessione fallita)
    if node_id:
        update_node_stats_internal(node_id, add_failed=True)
    
    emit('error', {'message': f'Node error: {error}'}, room=session_id)


@socketio.on('inference_token')
def handle_inference_token(data):
    """Nodo invia singolo token (streaming)."""
    session_id = str(data['session_id'])
    token = data.get('token', '')
    is_final = data.get('is_final', False)
    
    logger.info(f"[STREAMING] Token for session {session_id}: '{token[:30] if len(token) > 30 else token}' final={is_final}")
    
    # Inoltra token al client
    emit('ai_token', {
        'token': token,
        'is_final': is_final,
        'session_id': session_id
    }, room=session_id)


@socketio.on('session_status')
def handle_session_status(data):
    """Nodo invia aggiornamento stato sessione (download/loading model)."""
    session_id = str(data['session_id'])
    status = data.get('status', 'unknown')
    message = data.get('message', '')
    
    logger.info(f"Session {session_id} status: {status} - {message}")
    
    # Inoltra al client
    emit('model_status', {
        'session_id': session_id,
        'status': status,
        'message': message
    }, room=session_id)


@socketio.on('inference_complete')
def handle_inference_complete(data):
    """Nodo segnala completamento streaming con risposta pulita."""
    session_id = str(data['session_id'])
    content = data.get('content', '')
    tokens_generated = data.get('tokens_generated', 0)
    response_time_ms = data.get('response_time_ms', 0)
    
    logger.info(f"[STREAMING] inference_complete for session {session_id}, tokens: {tokens_generated}, content length: {len(content) if content else 0}")
    
    # Aggiorna statistiche nodo
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
        
        # Aggiorna performance se disponibile
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
    
    # Invia risposta completa pulita
    emit('ai_response', {
        'response': content,
        'session_id': session_id,
        'streaming_complete': True
    }, room=session_id)


@socketio.on('inference_response')
def handle_inference_response(data):
    """Nodo invia risposta inferenza (non-streaming)."""
    session_id = str(data['session_id'])
    content = data.get('content', '')
    tokens_generated = data.get('tokens_generated', 0)
    response_time_ms = data.get('response_time_ms', 0)
    
    # Aggiorna statistiche nodo
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
        
        # Aggiorna performance se disponibile
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
    Esclude i nodi già in uso da altri utenti.
    
    model_query può essere:
    - Nome modello (vecchio formato)
    - ID modello (nuovo formato)
    - Nome parziale per matching fuzzy
    """
    # Ottieni nodi occupati
    busy_nodes = get_busy_node_ids()
    
    for node_id, info in connected_nodes.items():
        # Salta nodi già in uso
        if node_id in busy_nodes:
            logger.debug(f"Node {node_id} is busy, skipping")
            continue
            
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
    """
    Trova un nodo WebSocket per uno specifico model_id.
    Esclude i nodi già in uso da altri utenti.
    """
    # Ottieni nodi occupati
    busy_nodes = get_busy_node_ids()
    
    for node_id, info in connected_nodes.items():
        # Salta nodi già in uso
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
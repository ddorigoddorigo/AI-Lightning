"""
Decorators for the AI Lightning server.

Rate limiting, validation, and other utilities.
"""
from functools import wraps
from flask import request, jsonify, current_app
import time
import threading

# In-memory rate limiter (per production, usare Redis)
_rate_limit_store = {}
_rate_limit_lock = threading.Lock()


def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    """
    Rate limiting decorator.
    
    Args:
        max_requests: Numero massimo di richieste nella finestra
        window_seconds: Durata della finestra in secondi
    
    Usage:
        @rate_limit(max_requests=10, window_seconds=60)
        def my_endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Identifica il client (IP o user ID se autenticato)
            client_id = request.remote_addr
            
            # Chiave per il rate limiting
            key = f"{f.__name__}:{client_id}"
            current_time = time.time()
            
            with _rate_limit_lock:
                if key not in _rate_limit_store:
                    _rate_limit_store[key] = []
                
                # Rimuovi richieste fuori dalla finestra
                _rate_limit_store[key] = [
                    t for t in _rate_limit_store[key]
                    if current_time - t < window_seconds
                ]
                
                # Controlla se siamo sopra il limite
                if len(_rate_limit_store[key]) >= max_requests:
                    return jsonify({
                        'error': 'Rate limit exceeded',
                        'retry_after': window_seconds
                    }), 429
                
                # Registra la richiesta
                _rate_limit_store[key].append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def validate_json(*required_fields):
    """
    Decorator per validare che il JSON contenga i campi richiesti.
    
    Args:
        *required_fields: Nomi dei campi richiesti
    
    Usage:
        @validate_json('username', 'password')
        def register():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            data = request.get_json()
            
            if data is None:
                return jsonify({'error': 'Invalid JSON'}), 400
            
            missing = [field for field in required_fields if field not in data]
            if missing:
                return jsonify({
                    'error': f'Missing required fields: {", ".join(missing)}'
                }), 400
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def validate_model_param(f):
    """
    Decorator per validare il parametro 'model'.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        data = request.get_json()
        if data and 'model' in data:
            from ..config import Config
            if data['model'] not in Config.AVAILABLE_MODELS:
                return jsonify({
                    'error': f'Invalid model. Available: {list(Config.AVAILABLE_MODELS.keys())}'
                }), 400
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """
    Decorator per endpoint solo admin.
    Richiede @jwt_required() prima.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask_jwt_extended import get_jwt_identity
        from ..models import User
        
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        
        if not user or not user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


# Cleanup periodico del rate limit store
def cleanup_rate_limit_store():
    """Rimuove entries scadute dal rate limit store."""
    current_time = time.time()
    max_age = 3600  # 1 ora
    
    with _rate_limit_lock:
        keys_to_remove = []
        for key, timestamps in _rate_limit_store.items():
            # Filtra timestamps vecchi
            fresh = [t for t in timestamps if current_time - t < max_age]
            if not fresh:
                keys_to_remove.append(key)
            else:
                _rate_limit_store[key] = fresh
        
        for key in keys_to_remove:
            del _rate_limit_store[key]
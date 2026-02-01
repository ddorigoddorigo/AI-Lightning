"""
Gestione dei nodi host.

Usa Redis per coordinamento e selezione dei nodi.
"""
import redis
import json
import uuid
import logging
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)

class NodeManager:
    def __init__(self, config):
        """
        Inizializza connessione a Redis.
        
        Args:
            config: Flask config object or dict with Redis URL
        """
        self.config = config
        redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
        self.redis = redis.Redis.from_url(redis_url)
        self.active_sessions = {}  # session_id -> node_info
        
        # Set per tracciare i nodi (più efficiente di KEYS)
        self.nodes_set_key = "registered_nodes"

    def register_node(self, user_id, address, models):
        """
        Registra un nuovo nodo.

        Args:
            user_id: ID dell'utente proprietario
            address: Indirizzo IP del nodo
            models: Dict di modelli offerti {name: path}

        Returns:
            str: ID del nodo
        """
        node_id = f"node-{uuid.uuid4().hex[:8]}"
        self.redis.hset(
            f"node:{node_id}",
            mapping={
                'id': node_id,
                'user_id': user_id,
                'address': address,
                'models': json.dumps(models),
                'status': 'online',
                'last_ping': datetime.utcnow().timestamp(),
                'load': 0
            }
        )
        # Aggiungi al set dei nodi registrati (più efficiente di KEYS)
        self.redis.sadd(self.nodes_set_key, node_id)
        return node_id

    def get_available_node(self, model):
        """
        Trova un nodo disponibile che supporta il modello.

        Args:
            model: Nome del modello

        Returns:
            dict: Informazioni sul nodo, o None
        """
        best_node = None
        best_score = float('-inf')

        # Usa SMEMBERS invece di KEYS per migliore performance
        for node_id in self.redis.smembers(self.nodes_set_key):
            node_id_str = node_id.decode() if isinstance(node_id, bytes) else node_id
            node_data = self.redis.hgetall(f"node:{node_id_str}")
            if not node_data:
                continue
            if (node_data.get(b'status', b'').decode() == 'online' and
                model in json.loads(node_data.get(b'models', b'{}').decode())):
                # Seleziona nodo con minor carico
                load = int(node_data.get(b'load', b'0'))
                score = 1 / (load + 1)
                if score > best_score:
                    best_score = score
                    best_node = node_data
                    best_node[b'id'] = node_id  # Assicura che l'ID sia presente

        return best_node

    def start_remote_session(self, node_id, session_id, model, context):
        """
        Avvia una sessione su un nodo remoto.

        Args:
            node_id: ID del nodo
            session_id: ID della sessione
            model: Nome del modello
            context: Contesto (n_tokens)

        Returns:
            dict: Informazioni sulla sessione
        """
        node = self.redis.hgetall(f"node:{node_id}")
        if not node or node.get(b'status', b'').decode() != 'online':
            raise Exception("Node not available")

        # Ottieni il path del modello dalla config
        available_models = self.config.get('AVAILABLE_MODELS', {})
        if model not in available_models:
            raise Exception(f"Model {model} not configured")
        
        llama_bin = available_models[model].get('path', '')

        # Chiamata al node server
        response = httpx.post(
            f"http://{node[b'address'].decode()}:9000/api/start_session",
            json={
                'session_id': session_id,
                'model': model,
                'context': context,
                'llama_bin': llama_bin
            },
            timeout=120  # llama.cpp può impiegare tempo ad avviarsi
        )
        response.raise_for_status()
        
        # Incrementa il carico del nodo
        self.redis.hincrby(f"node:{node_id}", 'load', 1)
        
        result = response.json()
        
        # Salva le info della sessione per riferimento futuro
        self.active_sessions[str(session_id)] = {
            'node_id': node_id,
            'port': result.get('port'),
            'started_at': datetime.utcnow().timestamp()
        }
        
        return result

    def node_heartbeat(self, node_id):
        """
        Aggiorna stato del nodo.

        Args:
            node_id: ID del nodo
        """
        self.redis.hset(
            f"node:{node_id}",
            {
                'last_ping': datetime.utcnow().timestamp(),
                'status': 'online'
            }
        )

    def check_node_status(self, node_id):
        """
        Verifica stato di un nodo.

        Args:
            node_id: ID del nodo

        Returns:
            bool: True se online
        """
        node_data = self.redis.hgetall(f"node:{node_id}")
        if not node_data:
            return False

        last_ping = node_data[b'last_ping']
        return (datetime.utcnow().timestamp() - float(last_ping)) < 30  # 30 sec timeout

    def get_all_nodes(self):
        """Lista tutti i nodi registrati."""
        nodes = []
        for node_id in self.redis.smembers(self.nodes_set_key):
            node_id_str = node_id.decode() if isinstance(node_id, bytes) else node_id
            node_data = self.redis.hgetall(f"node:{node_id_str}")
            if node_data:
                nodes.append(node_data)
        return nodes
    
    def unregister_node(self, node_id):
        """
        Rimuove un nodo dal sistema.
        
        Args:
            node_id: ID del nodo
        """
        self.redis.delete(f"node:{node_id}")
        self.redis.srem(self.nodes_set_key, node_id)
    
    def stop_remote_session(self, node_id, session_id):
        """
        Ferma una sessione su un nodo remoto.
        
        Args:
            node_id: ID del nodo
            session_id: ID della sessione
        """
        node = self.redis.hgetall(f"node:{node_id}")
        if not node:
            return
        
        try:
            response = httpx.post(
                f"http://{node[b'address'].decode()}:9000/api/stop_session",
                json={'session_id': session_id},
                timeout=5
            )
            response.raise_for_status()
            
            # Decrementa il carico del nodo
            self.redis.hincrby(f"node:{node_id}", 'load', -1)
        except Exception as e:
            logger.error(f"Error stopping session on node {node_id}: {e}")

    def pay_node(self, node_id, amount, description):
        """
        Paga un nodo per una sessione.

        Args:
            node_id: ID del nodo
            amount: Importo in satoshis
            description: Descrizione del pagamento
        """
        node_data = self.redis.hgetall(f"node:{node_id}")
        user_id = int(node_data[b'user_id'])

        from models import db, User, Transaction
        with db.session.begin():
            owner = User.query.get(user_id)
            owner.balance += amount

            db.session.add(Transaction(
                type='deposit',
                user_id=user_id,
                amount=amount,
                description=description
            ))
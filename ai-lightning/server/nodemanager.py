"""
Gestione dei nodi host.

Usa Redis per coordinamento e selezione dei nodi.
"""
import redis
import json
import uuid
from threading import Thread
from datetime import datetime
from flask import current_app

class NodeManager:
    def __init__(self):
        """Inizializza connessione a Redis."""
        self.redis = redis.Redis.from_url(current_app.config['REDIS_URL'])
        self.active_sessions = {}  # session_id -> node_info

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
                'user_id': user_id,
                'address': address,
                'models': json.dumps(models),
                'status': 'online',
                'last_ping': datetime.utcnow().timestamp(),
                'load': 0
            }
        )
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

        for node_id in self.redis.keys("node:*"):
            node_data = self.redis.hgetall(node_id)
            if (node_data[b'status'].decode() == 'online' and
                model in json.loads(node_data[b'models'].decode())):
                # Seleziona nodo con minor carico
                score = 1 / (node_data[b'load'] + 1)
                if score > best_score:
                    best_score = score
                    best_node = node_data

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
        if not node or node[b'status'].decode() != 'online':
            raise Exception("Node not available")

        # Chiamata al node server
        import httpx
        response = httpx.post(
            f"http://{node[b'address'].decode()}:9000/api/start_session",
            json={
                'session_id': session_id,
                'model': model,
                'context': context,
                'llama_bin': current_app.config['AVAILABLE_MODELS'][model]['path']
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json()

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
        for node_id in self.redis.keys("node:*"):
            nodes.append(self.redis.hgetall(node_id))
        return nodes

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

        from .models import db, User, Transaction
        with db.session.begin():
            owner = User.query.get(user_id)
            owner.balance += amount

            db.session.add(Transaction(
                type='deposit',
                user_id=user_id,
                amount=amount,
                description=description
            ))
"""
Host nodes management.

Uses Redis for coordination and node selection.
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
        Initialize Redis connection.
        
        Args:
            config: Flask config object or dict with Redis URL
        """
        self.config = config
        redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
        self.redis = redis.Redis.from_url(redis_url)
        self.active_sessions = {}  # session_id -> node_info
        
        # Set to track nodes (more efficient than KEYS)
        self.nodes_set_key = "registered_nodes"

    def register_node(self, user_id, address, models, payment_address=None):
        """
        Register a new node.

        Args:
            user_id: Owner user ID
            address: Node IP address
            models: Dict of offered models {name: path}
            payment_address: Lightning address for direct payments (LNURL, BOLT12, or node pubkey)

        Returns:
            str: Node ID
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
                'load': 0,
                'payment_address': payment_address or '',
                'total_earned': 0
            }
        )
        # Add to the registered nodes set (more efficient than KEYS)
        self.redis.sadd(self.nodes_set_key, node_id)
        return node_id

    def get_available_node(self, model):
        """
        Find an available node that supports the model.

        Args:
            model: Model name

        Returns:
            dict: Node information, or None
        """
        best_node = None
        best_score = float('-inf')

        # Use SMEMBERS instead of KEYS for better performance
        for node_id in self.redis.smembers(self.nodes_set_key):
            node_id_str = node_id.decode() if isinstance(node_id, bytes) else node_id
            node_data = self.redis.hgetall(f"node:{node_id_str}")
            if not node_data:
                continue
            if (node_data.get(b'status', b'').decode() == 'online' and
                model in json.loads(node_data.get(b'models', b'{}').decode())):
                # Select node with lowest load
                load = int(node_data.get(b'load', b'0'))
                score = 1 / (load + 1)
                if score > best_score:
                    best_score = score
                    best_node = node_data
                    best_node[b'id'] = node_id  # Ensure the ID is present

        return best_node

    def start_remote_session(self, node_id, session_id, model, context):
        """
        Start a session on a remote node.

        Args:
            node_id: Node ID
            session_id: Session ID
            model: Model name
            context: Context (n_tokens)

        Returns:
            dict: Session information
        """
        node = self.redis.hgetall(f"node:{node_id}")
        if not node or node.get(b'status', b'').decode() != 'online':
            raise Exception("Node not available")

        # Get model path from config
        available_models = self.config.get('AVAILABLE_MODELS', {})
        if model not in available_models:
            raise Exception(f"Model {model} not configured")
        
        llama_bin = available_models[model].get('path', '')

        # Call to node server
        response = httpx.post(
            f"http://{node[b'address'].decode()}:9000/api/start_session",
            json={
                'session_id': session_id,
                'model': model,
                'context': context,
                'llama_bin': llama_bin
            },
            timeout=120  # llama.cpp can take time to start
        )
        response.raise_for_status()
        
        # Increment node load
        self.redis.hincrby(f"node:{node_id}", 'load', 1)
        
        result = response.json()
        
        # Save session info for future reference
        self.active_sessions[str(session_id)] = {
            'node_id': node_id,
            'port': result.get('port'),
            'started_at': datetime.utcnow().timestamp()
        }
        
        return result

    def node_heartbeat(self, node_id):
        """
        Update node status.

        Args:
            node_id: Node ID
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
        Check node status.

        Args:
            node_id: Node ID

        Returns:
            bool: True if online
        """
        node_data = self.redis.hgetall(f"node:{node_id}")
        if not node_data:
            return False

        last_ping = node_data[b'last_ping']
        return (datetime.utcnow().timestamp() - float(last_ping)) < 30  # 30 sec timeout

    def get_all_nodes(self):
        """List all registered nodes."""
        nodes = []
        for node_id in self.redis.smembers(self.nodes_set_key):
            node_id_str = node_id.decode() if isinstance(node_id, bytes) else node_id
            node_data = self.redis.hgetall(f"node:{node_id_str}")
            if node_data:
                nodes.append(node_data)
        return nodes
    
    def unregister_node(self, node_id):
        """
        Remove a node from the system.
        
        Args:
            node_id: Node ID
        """
        self.redis.delete(f"node:{node_id}")
        self.redis.srem(self.nodes_set_key, node_id)
    
    def stop_remote_session(self, node_id, session_id):
        """
        Stop a session on a remote node.
        
        Args:
            node_id: Node ID
            session_id: Session ID
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

    def pay_node(self, node_id, amount, description, lightning_manager=None):
        """
        Pay a node for a session.
        
        If the node has a payment_address (Lightning), pay directly via Lightning.
        Otherwise, credit the owner user's balance.
        
        The platform commission is calculated by the caller (Config.NODE_PAYMENT_RATIO).

        Args:
            node_id: Node ID
            amount: Amount in satoshis (net of platform commission)
            description: Payment description
            lightning_manager: LightningManager instance for direct payments
        
        Returns:
            dict: {'success': bool, 'method': 'lightning'|'balance', 'error': str|None}
        """
        node_data = self.redis.hgetall(f"node:{node_id}")
        if not node_data:
            return {'success': False, 'method': None, 'error': 'Node not found'}
        
        user_id = int(node_data[b'user_id'])
        payment_address = node_data.get(b'payment_address', b'').decode()

        from models import db, User, Transaction
        
        # If has a Lightning address, try to pay directly
        if payment_address and lightning_manager:
            try:
                # The payment_address can be:
                # 1. LNURL (lnurl1...) - requires resolution
                # 2. Lightning Address (user@domain.com) - requires resolution
                # 3. Node pubkey + payment request - node generates invoice on-demand
                
                # For now, we assume the node generates an invoice via callback
                # Ask the node to generate an invoice for the amount
                node_address = node_data[b'address'].decode()
                
                try:
                    # Request invoice from node
                    invoice_response = httpx.post(
                        f"http://{node_address}:9000/api/create_invoice",
                        json={'amount': amount, 'description': description},
                        timeout=10
                    )
                    
                    if invoice_response.status_code == 200:
                        invoice_data = invoice_response.json()
                        payment_request = invoice_data.get('payment_request')
                        
                        if payment_request:
                            # Pay the invoice
                            pay_result = lightning_manager.pay_invoice(payment_request)
                            
                            if pay_result.get('success'):
                                # Update node earnings
                                self.redis.hincrby(f"node:{node_id}", 'total_earned', amount)
                                
                                # Record transaction
                                with db.session.begin():
                                    db.session.add(Transaction(
                                        type='node_payment',
                                        user_id=user_id,
                                        amount=amount,
                                        description=f"Lightning payment: {description}"
                                    ))
                                
                                logger.info(f"Paid {amount} sats to node {node_id} via Lightning")
                                return {'success': True, 'method': 'lightning', 'error': None}
                            else:
                                logger.warning(f"Lightning payment failed: {pay_result.get('error')}")
                                # Fallback to balance
                except httpx.RequestError as e:
                    logger.warning(f"Could not request invoice from node: {e}")
                    # Fallback to balance
                    
            except Exception as e:
                logger.warning(f"Lightning payment error: {e}")
                # Fallback to balance
        
        # Fallback: credit user balance
        try:
            with db.session.begin():
                owner = User.query.get(user_id)
                if owner:
                    owner.balance += amount

                    db.session.add(Transaction(
                        type='node_earning',
                        user_id=user_id,
                        amount=amount,
                        description=description
                    ))
                    
                    # Update node earnings
                    self.redis.hincrby(f"node:{node_id}", 'total_earned', amount)
            
            logger.info(f"Credited {amount} sats to node {node_id} owner balance")
            return {'success': True, 'method': 'balance', 'error': None}
            
        except Exception as e:
            logger.error(f"Failed to credit node owner: {e}")
            return {'success': False, 'method': None, 'error': str(e)}
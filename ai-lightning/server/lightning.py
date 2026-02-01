"""
Interfaccia con Lightning Network tramite LND REST API.

Usa l'API REST invece di gRPC per evitare problemi di compatibilità protobuf.
"""
import os
import base64
import logging
import requests
import urllib3

# Disabilita warning SSL per certificati self-signed
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class LightningManager:
    def __init__(self, config):
        """
        Inizializza connessione con LND via REST API.
        
        Args:
            config: Flask config object or dict with LND settings
        """
        self.config = config
        self._macaroon = None
        self._cert_path = None
        self._base_url = None
        self._setup_connection()
        
    def _setup_connection(self):
        """Configura i parametri di connessione."""
        # URL REST di LND (default porta 8080)
        lnd_rest_host = self.config.get('LND_REST_HOST', 'https://localhost:8080')
        self._base_url = lnd_rest_host.rstrip('/')
        
        # Percorso certificato TLS
        self._cert_path = os.path.expanduser(
            self.config.get('LND_CERT_PATH', '~/.lnd/tls.cert')
        )
        
        # Leggi macaroon e converti in hex
        network = self.config.get('LND_NETWORK', 'testnet')
        macaroon_path = os.path.expanduser(
            self.config.get('LND_MACAROON_PATH', f'~/.lnd/data/chain/bitcoin/{network}/admin.macaroon')
        )
        
        try:
            with open(macaroon_path, 'rb') as f:
                self._macaroon = f.read().hex()
            logger.info(f"LND REST API configured: {self._base_url}")
        except FileNotFoundError:
            logger.warning(f"Macaroon not found at {macaroon_path}")
            self._macaroon = None
    
    def _get_headers(self):
        """Restituisce headers per le richieste REST."""
        return {
            'Grpc-Metadata-macaroon': self._macaroon,
            'Content-Type': 'application/json'
        }
    
    def _request(self, method, endpoint, data=None):
        """Esegue una richiesta REST a LND."""
        if not self._macaroon:
            raise Exception("LND macaroon not configured")
        
        url = f"{self._base_url}{endpoint}"
        
        try:
            # Usa verify=False per certificati self-signed locali
            # In produzione, usa verify=self._cert_path
            if method == 'GET':
                response = requests.get(url, headers=self._get_headers(), verify=False, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=self._get_headers(), json=data, verify=False, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code != 200:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_data.get('error', response.text))
                except:
                    pass
                raise Exception(f"LND API error ({response.status_code}): {error_msg}")
            
            return response.json()
            
        except requests.exceptions.ConnectionError:
            raise Exception("Cannot connect to LND. Is it running?")
        except requests.exceptions.Timeout:
            raise Exception("LND request timeout")

    def create_invoice(self, amount_sat, memo):
        """
        Crea una fattura Lightning.

        Args:
            amount_sat: Importo in satoshis
            memo: Descrizione della fattura

        Returns:
            dict: {'payment_request': str, 'r_hash': str, 'amount': int}
        """
        data = {
            'value': str(amount_sat),
            'memo': memo,
            'expiry': '3600'  # 1 ora
        }
        
        response = self._request('POST', '/v1/invoices', data)
        
        # r_hash è in base64, convertiamo in hex
        r_hash_b64 = response.get('r_hash', '')
        r_hash_hex = base64.b64decode(r_hash_b64).hex() if r_hash_b64 else ''
        
        return {
            'payment_request': response.get('payment_request', ''),
            'r_hash': r_hash_hex,
            'amount': amount_sat
        }

    def check_payment(self, r_hash):
        """
        Verifica stato di un pagamento.

        Args:
            r_hash: Hash del pagamento (hex string)

        Returns:
            bool: True se pagato
        """
        try:
            # Converti hex a base64 URL-safe
            r_hash_bytes = bytes.fromhex(r_hash)
            r_hash_b64 = base64.urlsafe_b64encode(r_hash_bytes).decode('utf-8').rstrip('=')
            
            response = self._request('GET', f'/v1/invoice/{r_hash_b64}')
            
            # State: OPEN=0, SETTLED=1, CANCELED=2, ACCEPTED=3
            state = response.get('state', 'OPEN')
            return state == 'SETTLED'
            
        except Exception as e:
            logger.error(f"Error checking payment: {e}")
            return False

    def get_invoice(self, r_hash):
        """Recupera dettagli di una fattura."""
        r_hash_bytes = bytes.fromhex(r_hash)
        r_hash_b64 = base64.urlsafe_b64encode(r_hash_bytes).decode('utf-8').rstrip('=')
        return self._request('GET', f'/v1/invoice/{r_hash_b64}')
    
    def pay_invoice(self, payment_request):
        """
        Paga una fattura Lightning.
        
        Args:
            payment_request: BOLT11 invoice string
            
        Returns:
            dict: Payment result
        """
        try:
            data = {'payment_request': payment_request}
            response = self._request('POST', '/v1/channels/transactions', data)
            
            if response.get('payment_error'):
                return {'success': False, 'error': response['payment_error']}
            
            preimage = response.get('payment_preimage', '')
            if preimage:
                preimage = base64.b64decode(preimage).hex()
            
            return {
                'success': True, 
                'preimage': preimage
            }
        except Exception as e:
            logger.error(f"Error paying invoice: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_info(self):
        """Ottiene informazioni sul nodo LND."""
        return self._request('GET', '/v1/getinfo')
    
    def get_balance(self):
        """Ottiene il bilancio del wallet."""
        return self._request('GET', '/v1/balance/blockchain')
    
    def is_synced(self):
        """Verifica se LND è sincronizzato con la chain."""
        try:
            info = self.get_info()
            return info.get('synced_to_chain', False)
        except:
            return False
    
    def close(self):
        """Chiude la connessione (no-op per REST)."""
        pass
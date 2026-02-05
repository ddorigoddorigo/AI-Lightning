"""
Lightning Network interface via LND REST API.

Uses REST API instead of gRPC to avoid protobuf compatibility issues.
"""
import os
import base64
import logging
import requests
import urllib3
import hashlib
import time

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class LightningManager:
    def __init__(self, config):
        """
        Initialize connection with LND via REST API.
        
        Args:
            config: Flask config object or dict with LND settings
        """
        self.config = config
        self._macaroon = None
        self._cert_path = None
        self._base_url = None
        self._test_mode = config.get('TEST_MODE', 'false').lower() == 'true'
        
        if self._test_mode:
            logger.info("Lightning Manager running in TEST MODE - no real payments")
        else:
            self._setup_connection()
        
    def _setup_connection(self):
        """Configure connection parameters."""
        # LND REST URL (default port 8080)
        lnd_rest_host = self.config.get('LND_REST_HOST', 'https://localhost:8080')
        self._base_url = lnd_rest_host.rstrip('/')
        
        # TLS certificate path
        self._cert_path = os.path.expanduser(
            self.config.get('LND_CERT_PATH', '~/.lnd/tls.cert')
        )
        
        # Read macaroon and convert to hex
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
        """Return headers for REST requests."""
        return {
            'Grpc-Metadata-macaroon': self._macaroon,
            'Content-Type': 'application/json'
        }
    
    def _request(self, method, endpoint, data=None):
        """Execute a REST request to LND."""
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
        Create a Lightning invoice.

        Args:
            amount_sat: Amount in satoshis
            memo: Invoice description

        Returns:
            dict: {'payment_request': str, 'r_hash': str, 'amount': int}
        """
        # TEST MODE: genera invoice fake che risulta sempre pagata
        if self._test_mode:
            r_hash = hashlib.sha256(f"{memo}{time.time()}".encode()).hexdigest()
            fake_invoice = f"lntb{amount_sat}test{r_hash[:20]}"
            logger.info(f"[TEST MODE] Created fake invoice: {r_hash[:16]}...")
            return {
                'payment_request': fake_invoice,
                'r_hash': r_hash,
                'amount': amount_sat
            }
        
        data = {
            'value': str(amount_sat),
            'memo': memo,
            'expiry': '3600'  # 1 hour
        }
        
        response = self._request('POST', '/v1/invoices', data)
        
        # r_hash is in base64, convert to hex for storage
        r_hash_b64 = response.get('r_hash', '')
        try:
            # LND returns standard base64, may need padding
            padding = 4 - len(r_hash_b64) % 4
            if padding != 4:
                r_hash_b64 += '=' * padding
            r_hash_hex = base64.b64decode(r_hash_b64).hex() if r_hash_b64 else ''
        except Exception as e:
            logger.error(f"Error decoding r_hash: {e}, using raw value")
            r_hash_hex = r_hash_b64  # fallback to raw value
        
        logger.info(f"Created invoice: r_hash_b64={r_hash_b64[:20]}..., r_hash_hex={r_hash_hex[:20]}...")
        
        return {
            'payment_request': response.get('payment_request', ''),
            'r_hash': r_hash_hex,
            'amount': amount_sat
        }

    def check_payment(self, r_hash):
        """
        Check payment status.

        Args:
            r_hash: Payment hash (hex string)

        Returns:
            bool: True if paid
        """
        # TEST MODE: pagamenti sempre confermati
        if self._test_mode:
            logger.info(f"[TEST MODE] Payment {r_hash[:16]}... auto-confirmed")
            return True
        
        try:
            # LND REST API expects the r_hash as URL-safe base64
            # Our r_hash is stored as hex, so convert it
            
            # Check if it's hex (only 0-9, a-f characters)
            is_hex = all(c in '0123456789abcdefABCDEF' for c in r_hash)
            
            if is_hex:
                # Convert hex to bytes, then to url-safe base64
                r_hash_bytes = bytes.fromhex(r_hash)
                r_hash_b64 = base64.urlsafe_b64encode(r_hash_bytes).decode('utf-8').rstrip('=')
            else:
                # Already base64, just make it url-safe
                r_hash_b64 = r_hash.replace('+', '-').replace('/', '_').rstrip('=')
            
            logger.info(f"Checking payment: hex={r_hash[:16]}..., b64={r_hash_b64[:16]}...")
            response = self._request('GET', f'/v1/invoice/{r_hash_b64}')
            
            # State: OPEN=0, SETTLED=1, CANCELED=2, ACCEPTED=3
            state = response.get('state', 'OPEN')
            logger.info(f"Payment state for {r_hash[:16]}...: {state}")
            return state == 'SETTLED'
            
        except Exception as e:
            logger.error(f"Error checking payment: {e}")
            return False

    def get_invoice(self, r_hash):
        """Retrieve invoice details."""
        if self._test_mode:
            return {'state': 'SETTLED', 'r_hash': r_hash, 'value': '10000'}
        r_hash_bytes = bytes.fromhex(r_hash)
        r_hash_b64 = base64.urlsafe_b64encode(r_hash_bytes).decode('utf-8').rstrip('=')
        return self._request('GET', f'/v1/invoice/{r_hash_b64}')
    
    def get_invoice_amount(self, r_hash):
        """
        Retrieve invoice amount.
        
        Args:
            r_hash: Payment hash (hex string)
            
        Returns:
            int: Amount in satoshis, or None if not found
        """
        try:
            if self._test_mode:
                # In test mode, use a default value
                return 10000
            
            invoice = self.get_invoice(r_hash)
            # value can be string or int
            value = invoice.get('value', invoice.get('amt_paid_sat', 0))
            return int(value) if value else None
            
        except Exception as e:
            logger.error(f"Error getting invoice amount: {e}")
            return None
    
    def decode_invoice(self, payment_request):
        """
        Decode a BOLT11 Lightning invoice.
        
        Args:
            payment_request: BOLT11 invoice string
            
        Returns:
            dict: Decoded invoice info including num_satoshis, description, etc.
        """
        if self._test_mode:
            # In test mode, extract amount from invoice if possible, or use default
            # Simple parsing for test invoices
            return {
                'num_satoshis': '10000',
                'description': 'Test withdrawal',
                'destination': 'test_pubkey',
                'payment_hash': hashlib.sha256(payment_request.encode()).hexdigest()
            }
        
        try:
            # LND REST API: POST /v1/payreq/{pay_req}
            response = self._request('GET', f'/v1/payreq/{payment_request}')
            return response
        except Exception as e:
            logger.error(f"Error decoding invoice: {e}")
            raise
    
    def pay_invoice(self, payment_request):
        """
        Pay a Lightning invoice.
        
        Args:
            payment_request: BOLT11 invoice string
            
        Returns:
            dict: Payment result
        """
        if self._test_mode:
            logger.info(f"[TEST MODE] Paid invoice: {payment_request[:30]}...")
            return {'success': True, 'preimage': hashlib.sha256(payment_request.encode()).hexdigest()}
        
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
        """Get LND node information."""
        if self._test_mode:
            return {'alias': 'TEST_NODE', 'synced_to_chain': True, 'version': 'test'}
        return self._request('GET', '/v1/getinfo')
    
    def get_balance(self):
        """Get wallet balance."""
        if self._test_mode:
            return {'total_balance': '1000000', 'confirmed_balance': '1000000'}
        return self._request('GET', '/v1/balance/blockchain')
    
    def is_synced(self):
        """Check if LND is synced with the chain."""
        try:
            info = self.get_info()
            return info.get('synced_to_chain', False)
        except:
            return False
    
    def close(self):
        """Close the connection (no-op for REST)."""
        pass
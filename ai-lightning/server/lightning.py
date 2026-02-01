"""
Interfaccia con Lightning Network tramite lnd.

Usa pyln-client per comunicare con lnd.
"""
from pyln.client import Client
from pyln import Millisatoshi
import os
import logging

logger = logging.getLogger(__name__)

class LightningManager:
    def __init__(self, config):
        """
        Inizializza connessione con lnd.
        
        Args:
            config: Flask config object or dict with LND settings
        """
        self.config = config
        self._client = None
    
    @property
    def ln(self):
        """Lazy initialization of Lightning client."""
        if self._client is None:
            self._client = Client(
                network=self.config.get('LND_NETWORK', 'testnet'),
                lnd_dir=os.path.expanduser(self.config.get('LND_DIR', '~/.lnd')),
                cert_file=os.path.expanduser(self.config.get('LND_CERT_FILE', '')),
                macaroon_file=os.path.expanduser(self.config.get('LND_MACAROON_FILE', ''))
            )
        return self._client

    def create_invoice(self, amount_sat, memo):
        """
        Crea una fattura Lightning.

        Args:
            amount_sat: Importo in satoshis
            memo: Descrizione della fattura

        Returns:
            dict: {'payment_request': str, 'r_hash': str, 'amount': int}
        """
        invoice = self.ln.invoice(
            amount=Millisatoshi(amount_sat * 1000),  # pyln usa millisatoshi
            memo=memo,
            expiry=3600  # 1 ora
        )
        return {
            'payment_request': invoice.payment_request,
            'r_hash': invoice.r_hash.hex(),
            'amount': amount_sat
        }

    def check_payment(self, r_hash):
        """
        Verifica stato di un pagamento.

        Args:
            r_hash: Hash del pagamento

        Returns:
            bool: True se pagato
        """
        try:
            invoice = self.ln.lookup_invoice(r_hash)
            return invoice.is_paid
        except Exception as e:
            logger.error(f"Error checking payment: {e}")
            return False

    def get_invoice(self, r_hash):
        """Recupera dettagli di una fattura."""
        return self.ln.lookup_invoice(r_hash)
    
    def pay_invoice(self, payment_request):
        """
        Paga una fattura Lightning.
        
        Args:
            payment_request: BOLT11 invoice string
            
        Returns:
            dict: Payment result
        """
        try:
            result = self.ln.pay(payment_request)
            return {'success': True, 'preimage': result.payment_preimage.hex()}
        except Exception as e:
            logger.error(f"Error paying invoice: {e}")
            return {'success': False, 'error': str(e)}
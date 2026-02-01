"""
Interfaccia con Lightning Network tramite lnd.

Usa pyln-client per comunicare con lnd.
"""
from pyln.client import Client
from pyln import Millisatoshi
import os
from flask import current_app

class LightningManager:
    def __init__(self):
        """Inizializza connessione con lnd."""
        self.ln = Client(
            network=current_app.config['LND_NETWORK'],
            lnd_dir=os.path.expanduser(current_app.config['LND_DIR']),
            cert_file=os.path.expanduser(current_app.config['LND_CERT_FILE']),
            macaroon_file=os.path.expanduser(current_app.config['LND_MACAROON_FILE'])
        )

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
            current_app.logger.error(f"Error checking payment: {e}")
            return False

    def get_invoice(self, r_hash):
        """Recupera dettagli di una fattura."""
        return self.ln.lookup_invoice(r_hash)
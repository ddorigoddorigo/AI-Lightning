"""
Interfaccia con Lightning Network tramite LND.

Usa gRPC per comunicare con LND (compatibile con Neutrino).
"""
import codecs
import os
import logging
import grpc

logger = logging.getLogger(__name__)

# I proto compilati verranno importati dopo l'installazione
lightning_pb2 = None
lightning_pb2_grpc = None
invoices_pb2 = None
invoices_pb2_grpc = None


def _load_grpc_modules():
    """Carica i moduli gRPC di LND."""
    global lightning_pb2, lightning_pb2_grpc, invoices_pb2, invoices_pb2_grpc
    if lightning_pb2 is None:
        try:
            from lndgrpc import lightning_pb2 as lnpb2
            from lndgrpc import lightning_pb2_grpc as lnpb2_grpc
            from lndgrpc import invoices_pb2 as invpb2
            from lndgrpc import invoices_pb2_grpc as invpb2_grpc
            lightning_pb2 = lnpb2
            lightning_pb2_grpc = lnpb2_grpc
            invoices_pb2 = invpb2
            invoices_pb2_grpc = invpb2_grpc
        except ImportError:
            # Fallback: prova a importare direttamente
            import lightning_pb2 as lnpb2
            import lightning_pb2_grpc as lnpb2_grpc
            lightning_pb2 = lnpb2
            lightning_pb2_grpc = lnpb2_grpc


class LightningManager:
    def __init__(self, config):
        """
        Inizializza connessione con LND.
        
        Args:
            config: Flask config object or dict with LND settings
        """
        self.config = config
        self._stub = None
        self._channel = None
        
    def _get_credentials(self):
        """Carica certificato TLS e macaroon."""
        # Leggi certificato TLS
        cert_path = os.path.expanduser(
            self.config.get('LND_CERT_PATH', '~/.lnd/tls.cert')
        )
        with open(cert_path, 'rb') as f:
            cert = f.read()
        
        # Leggi macaroon
        macaroon_path = os.path.expanduser(
            self.config.get('LND_MACAROON_PATH', '~/.lnd/data/chain/bitcoin/mainnet/admin.macaroon')
        )
        with open(macaroon_path, 'rb') as f:
            macaroon_bytes = f.read()
        macaroon = codecs.encode(macaroon_bytes, 'hex')
        
        return cert, macaroon
    
    def _get_stub(self):
        """Ottiene lo stub gRPC con lazy initialization."""
        if self._stub is None:
            _load_grpc_modules()
            
            cert, macaroon = self._get_credentials()
            
            # Crea callback per aggiungere macaroon agli header
            def metadata_callback(context, callback):
                callback([('macaroon', macaroon)], None)
            
            # Crea credenziali
            cert_creds = grpc.ssl_channel_credentials(cert)
            auth_creds = grpc.metadata_call_credentials(metadata_callback)
            combined_creds = grpc.composite_channel_credentials(cert_creds, auth_creds)
            
            # Connetti a LND
            lnd_host = self.config.get('LND_HOST', 'localhost:10009')
            self._channel = grpc.secure_channel(lnd_host, combined_creds)
            self._stub = lightning_pb2_grpc.LightningStub(self._channel)
            
            logger.info(f"Connected to LND at {lnd_host}")
        
        return self._stub

    def create_invoice(self, amount_sat, memo):
        """
        Crea una fattura Lightning.

        Args:
            amount_sat: Importo in satoshis
            memo: Descrizione della fattura

        Returns:
            dict: {'payment_request': str, 'r_hash': str, 'amount': int}
        """
        stub = self._get_stub()
        
        request = lightning_pb2.Invoice(
            value=amount_sat,
            memo=memo,
            expiry=3600  # 1 ora
        )
        
        response = stub.AddInvoice(request)
        
        return {
            'payment_request': response.payment_request,
            'r_hash': response.r_hash.hex(),
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
            stub = self._get_stub()
            
            # Converti hex string a bytes
            r_hash_bytes = bytes.fromhex(r_hash)
            
            request = lightning_pb2.PaymentHash(r_hash=r_hash_bytes)
            invoice = stub.LookupInvoice(request)
            
            # State 1 = SETTLED (pagato)
            return invoice.state == 1
        except Exception as e:
            logger.error(f"Error checking payment: {e}")
            return False

    def get_invoice(self, r_hash):
        """Recupera dettagli di una fattura."""
        stub = self._get_stub()
        r_hash_bytes = bytes.fromhex(r_hash)
        request = lightning_pb2.PaymentHash(r_hash=r_hash_bytes)
        return stub.LookupInvoice(request)
    
    def pay_invoice(self, payment_request):
        """
        Paga una fattura Lightning.
        
        Args:
            payment_request: BOLT11 invoice string
            
        Returns:
            dict: Payment result
        """
        try:
            stub = self._get_stub()
            
            request = lightning_pb2.SendRequest(payment_request=payment_request)
            response = stub.SendPaymentSync(request)
            
            if response.payment_error:
                return {'success': False, 'error': response.payment_error}
            
            return {
                'success': True, 
                'preimage': response.payment_preimage.hex()
            }
        except Exception as e:
            logger.error(f"Error paying invoice: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_info(self):
        """Ottiene informazioni sul nodo LND."""
        stub = self._get_stub()
        request = lightning_pb2.GetInfoRequest()
        return stub.GetInfo(request)
    
    def get_balance(self):
        """Ottiene il bilancio del wallet."""
        stub = self._get_stub()
        request = lightning_pb2.WalletBalanceRequest()
        return stub.WalletBalance(request)
    
    def close(self):
        """Chiude la connessione gRPC."""
        if self._channel:
            self._channel.close()
            self._channel = None
            self._stub = None
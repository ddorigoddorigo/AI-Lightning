"""
AI Lightning Node Client

Client per nodi host dietro NAT.
Si connette al server via WebSocket e riceve richieste di inferenza.
"""
import os
import sys
import json
import time
import base64
import subprocess
import threading
import logging
import signal
import atexit
import socketio
import httpx
import requests
import urllib3
from pathlib import Path
from configparser import ConfigParser
from flask import Flask, request, jsonify

# Disabilita warning SSL per certificati self-signed
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('NodeClient')


class NodeLightning:
    """Gestisce Lightning wallet locale per ricevere pagamenti"""
    
    def __init__(self, config):
        """
        Inizializza connessione con LND locale.
        
        Args:
            config: ConfigParser con sezione [Lightning]
        """
        self.enabled = config.getboolean('Lightning', 'enabled', fallback=False)
        if not self.enabled:
            return
        
        self._base_url = config.get('Lightning', 'lnd_rest_host', fallback='https://127.0.0.1:8080').rstrip('/')
        self._cert_path = os.path.expanduser(
            config.get('Lightning', 'lnd_cert_path', fallback='~/.lnd/tls.cert')
        )
        macaroon_path = os.path.expanduser(
            config.get('Lightning', 'lnd_macaroon_path', fallback='~/.lnd/data/chain/bitcoin/mainnet/invoice.macaroon')
        )
        
        self._macaroon = None
        try:
            with open(macaroon_path, 'rb') as f:
                self._macaroon = f.read().hex()
            logger.info(f"Lightning wallet configured: {self._base_url}")
        except FileNotFoundError:
            logger.warning(f"Lightning macaroon not found at {macaroon_path}")
            self.enabled = False
    
    def create_invoice(self, amount_sat, memo):
        """
        Crea una invoice Lightning per ricevere un pagamento.
        
        Args:
            amount_sat: Importo in satoshis
            memo: Descrizione
            
        Returns:
            dict: {'payment_request': str, 'r_hash': str} or None
        """
        if not self.enabled or not self._macaroon:
            return None
        
        try:
            response = requests.post(
                f"{self._base_url}/v1/invoices",
                headers={
                    'Grpc-Metadata-macaroon': self._macaroon,
                    'Content-Type': 'application/json'
                },
                json={
                    'value': str(amount_sat),
                    'memo': memo,
                    'expiry': '600'  # 10 minuti
                },
                verify=False,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                r_hash_b64 = data.get('r_hash', '')
                r_hash_hex = base64.b64decode(r_hash_b64).hex() if r_hash_b64 else ''
                
                return {
                    'payment_request': data.get('payment_request', ''),
                    'r_hash': r_hash_hex
                }
        except Exception as e:
            logger.error(f"Failed to create Lightning invoice: {e}")
        
        return None


class LlamaProcess:
    """Gestisce un processo llama-server (llama.cpp)"""
    
    def __init__(self, llama_command, model_source, port, context=2048, gpu_layers=99, use_hf=True):
        """
        Args:
            llama_command: Comando per llama-server (es: 'llama-server' o path completo)
            model_source: Repository HuggingFace (es: 'bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M') 
                         o path locale al file GGUF
            port: Porta per il server
            context: Context size
            gpu_layers: Layers da caricare su GPU
            use_hf: Se True, usa -hf per scaricare da HuggingFace
        """
        self.llama_command = llama_command or 'llama-server'
        self.model_source = model_source
        self.port = port
        self.context = context
        self.gpu_layers = gpu_layers
        self.use_hf = use_hf
        self.process = None
        self.is_downloading = False
        self._stop_streaming = False  # Flag per interrompere streaming in corso
        
    def start(self, download_callback=None):
        """
        Avvia il server llama-server.
        
        Args:
            download_callback: Callback chiamata durante il download con (status, progress_msg)
        """
        # Costruisci il comando
        if self.use_hf:
            # Usa -hf per scaricare da HuggingFace
            # Formato: owner/repo:filename.gguf o owner/repo:quantization
            logger.info(f"Using HuggingFace model: {self.model_source}")
            cmd = [
                self.llama_command,
                '-hf', self.model_source,
                '--host', '127.0.0.1',
                '--port', str(self.port),
                '--ctx-size', str(self.context),
                '-ngl', str(self.gpu_layers)
            ]
            
            # Aggiungi HF_TOKEN se presente nell'ambiente (per modelli gated)
            hf_token = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
            if hf_token:
                cmd.extend(['--hf-token', hf_token])
                logger.info("Using HuggingFace token for authentication")
        else:
            # Usa modello locale
            logger.info(f"Checking local model: {self.model_source}")
            if not self.model_source:
                logger.error(f"Model source is None or empty!")
                return False
            if not os.path.exists(self.model_source):
                logger.error(f"Model file not found at path: {self.model_source}")
                logger.error(f"Current working directory: {os.getcwd()}")
                # List files in directory to debug
                parent_dir = os.path.dirname(self.model_source) if self.model_source else '.'
                if os.path.exists(parent_dir):
                    logger.error(f"Files in {parent_dir}: {os.listdir(parent_dir)[:10]}")
                return False
            
            logger.info(f"Model file found, size: {os.path.getsize(self.model_source) / (1024**3):.2f} GB")
            
            cmd = [
                self.llama_command,
                '-m', self.model_source,
                '--host', '127.0.0.1',
                '--port', str(self.port),
                '--ctx-size', str(self.context),
                '-ngl', str(self.gpu_layers)
            ]
        
        logger.info(f"Starting llama-server: {' '.join(cmd)}")
        
        # Su Windows, usa shell=True per trovare llama-server nel PATH
        use_shell = sys.platform == 'win32' and not os.path.exists(self.llama_command)
        
        # Non nascondere la finestra per vedere il progresso del download
        try:
            self.process = subprocess.Popen(
                cmd if not use_shell else ' '.join(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Unisci stderr a stdout per catturare tutto
                shell=use_shell,
                bufsize=1,
                universal_newlines=True
            )
        except FileNotFoundError:
            logger.error(f"llama-server command not found: {self.llama_command}")
            logger.error("Assicurati che llama-server sia installato e nel PATH")
            return False
        except Exception as e:
            logger.error(f"Failed to start llama-server: {e}")
            return False
        
        # Attendi che sia pronto - timeout esteso per download + caricamento
        # Timeout: 600 secondi (10 minuti) per permettere download di modelli grandi
        logger.info(f"Waiting for llama-server (downloading model if needed, this may take several minutes)...")
        
        self.is_downloading = True
        last_log_time = time.time()
        
        # Invia subito stato iniziale di loading
        if download_callback:
            if self.use_hf:
                download_callback('loading', 'Starting model loading...')
            else:
                download_callback('loading', 'Loading model into memory...')
        
        for i in range(600):  # 10 minuti timeout
            # Check if the process is still alive
            if self.process.poll() is not None:
                # Processo terminato, leggi output rimanente
                exit_code = self.process.returncode
                remaining_output = ""
                try:
                    remaining_output = self.process.stdout.read() if self.process.stdout else ""
                except:
                    pass
                
                # Aggiungi output dalla coda se presente (Windows)
                if hasattr(self, '_output_queue'):
                    import queue
                    queued_lines = []
                    try:
                        while True:
                            queued_lines.append(self._output_queue.get_nowait())
                    except queue.Empty:
                        pass
                    if queued_lines:
                        remaining_output += "\n" + "\n".join(queued_lines)
                
                logger.error(f"llama-server crashed with exit code {exit_code}")
                logger.error(f"llama-server output: {remaining_output}")
                
                # Notify specific error
                if download_callback:
                    if 'error' in remaining_output.lower() or 'failed' in remaining_output.lower():
                        download_callback('error', f'Model loading failed: {remaining_output[:200]}')
                    elif 'not found' in remaining_output.lower():
                        download_callback('error', f'Model not found or invalid format')
                    else:
                        download_callback('error', f'llama-server crashed (code {exit_code})')
                
                return False
            
            # Prova a leggere l'output (non bloccante)
            try:
                if sys.platform != 'win32':
                    # Unix: usa select
                    import select
                    readable, _, _ = select.select([self.process.stdout], [], [], 0.1)
                    if readable:
                        line = self.process.stdout.readline()
                        if line:
                            line = line.strip()
                            logger.info(f"[llama-server] {line}")
                            if download_callback:
                                if 'download' in line.lower() or '%' in line:
                                    download_callback('downloading', line)
                                elif 'loading' in line.lower():
                                    download_callback('loading', line)
                else:
                    # Windows: prova lettura con timeout ridotto usando thread
                    import threading
                    import queue
                    
                    # Usa una coda thread-safe per leggere l'output
                    if not hasattr(self, '_output_queue'):
                        self._output_queue = queue.Queue()
                        def read_output():
                            while self.process and self.process.poll() is None:
                                try:
                                    line = self.process.stdout.readline()
                                    if line:
                                        self._output_queue.put(line.strip())
                                except:
                                    break
                        self._reader_thread = threading.Thread(target=read_output, daemon=True)
                        self._reader_thread.start()
                    
                    # Leggi dalla coda senza bloccare
                    try:
                        while True:
                            line = self._output_queue.get_nowait()
                            if line:
                                logger.info(f"[llama-server] {line}")
                                if download_callback:
                                    if 'download' in line.lower() or '%' in line:
                                        download_callback('downloading', line)
                                    elif 'loading' in line.lower():
                                        download_callback('loading', line)
                    except queue.Empty:
                        pass
            except:
                pass
            
            # Check if server is ready
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2)
                if r.status_code == 200:
                    self.is_downloading = False
                    logger.info(f"llama-server ready on port {self.port} after {i+1} seconds")
                    if download_callback:
                        download_callback('ready', f"Server ready on port {self.port}")
                    return True
            except:
                pass
            
            # Log progress ogni 30 secondi
            if time.time() - last_log_time >= 30:
                last_log_time = time.time()
                if self.use_hf:
                    logger.info(f"Still waiting for llama-server (downloading/loading model)... ({i+1}s elapsed)")
                else:
                    logger.info(f"Still loading model... ({i+1}s elapsed)")
                if download_callback:
                    download_callback('waiting', f"Waiting... ({i+1}s elapsed)")
            
            time.sleep(1)
        
        logger.error("llama-server failed to start in 600 seconds (10 minutes)")
        self.stop()
        return False
    
    def stop(self):
        """Ferma il processo e interrompe streaming in corso"""
        self._stop_streaming = True  # Segnala stop allo streaming
        if self.process:
            pid = self.process.pid
            logger.info(f"[STOP] Terminating llama-server process (PID: {pid})...")
            
            try:
                # Su Windows, terminate() non funziona bene - usiamo taskkill
                import platform
                if platform.system() == 'Windows':
                    import subprocess
                    # Killa il processo e tutti i suoi figli
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], 
                                   capture_output=True, timeout=10)
                    logger.info(f"[STOP] Used taskkill to force-terminate PID {pid}")
                else:
                    # Su Linux/Mac usa terminate + kill
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except:
                        self.process.kill()
                        self.process.wait(timeout=5)
            except Exception as e:
                logger.error(f"[STOP] Error terminating process: {e}")
                # Fallback: prova kill diretto
                try:
                    self.process.kill()
                except:
                    pass
            
            self.process = None
            logger.info(f"[STOP] llama-server process terminated successfully")
    
    def request_stop_streaming(self):
        """Request interruption of current streaming without stopping the process"""
        self._stop_streaming = True
        logger.info("Streaming stop requested")
    
    def reset_stop_flag(self):
        """Reset stop flag before a new generation"""
        self._stop_streaming = False
    
    def is_running(self):
        return self.process and self.process.poll() is None
    
    def generate(self, prompt, max_tokens=2048, temperature=0.7, top_k=40, top_p=0.95, 
                 repeat_penalty=1.0, presence_penalty=0.0, frequency_penalty=0.0, 
                 seed=-1, stop=None,
                 # Extended parameters
                 min_p=0.05, typical_p=1.0, 
                 dynatemp_range=0.0, dynatemp_exponent=1.0,
                 repeat_last_n=64,
                 xtc_threshold=0.1, xtc_probability=0.5,
                 dry_multiplier=0.0, dry_base=1.75, dry_allowed_length=2, dry_penalty_last_n=-1,
                 samplers=None):
        """
        Generate a response (non-streaming, for compatibility).
        
        Args:
            prompt: The prompt to process
            max_tokens: Maximum number of tokens to generate (-1 = context length)
            temperature: Controls randomness (0=deterministic, 1+=more creative)
            top_k: Consider only top k most likely tokens (0=disabled)
            top_p: Nucleus sampling - consider tokens up to cumulative probability p
            repeat_penalty: Penalize token repetition (1.0=no penalty)
            presence_penalty: Penalize tokens already appeared (-2.0 to 2.0)
            frequency_penalty: Penalize tokens based on frequency (-2.0 to 2.0)
            seed: Seed for reproducibility (-1=random)
            stop: List of stop strings
            min_p: Minimum probability threshold
            typical_p: Typical sampling (1.0=disabled)
            dynatemp_range: Dynamic temperature range (0=disabled)
            dynatemp_exponent: Dynamic temperature exponent
            repeat_last_n: Tokens to consider for repeat penalty
            xtc_threshold: XTC threshold
            xtc_probability: XTC probability
            dry_multiplier: DRY multiplier (0=disabled)
            dry_base: DRY base
            dry_allowed_length: DRY allowed length
            dry_penalty_last_n: DRY penalty last n (-1=context)
            samplers: Sampler order string (semicolon separated)
        """
        if not self.is_running():
            return None, "Process not running"
        
        try:
            # Build request payload
            payload = {
                'prompt': prompt,
                'n_predict': max_tokens if max_tokens > 0 else -1,
                'temperature': temperature,
                'top_k': top_k,
                'top_p': top_p,
                'min_p': min_p,
                'typical_p': typical_p,
                'repeat_penalty': repeat_penalty,
                'repeat_last_n': repeat_last_n,
                'presence_penalty': presence_penalty,
                'frequency_penalty': frequency_penalty,
                'seed': seed,
                'stop': stop or [],
                'stream': False
            }
            
            # Add dynamic temperature if enabled
            if dynatemp_range > 0:
                payload['dynatemp_range'] = dynatemp_range
                payload['dynatemp_exponent'] = dynatemp_exponent
            
            # Add XTC if threshold > 0
            if xtc_threshold > 0:
                payload['xtc_threshold'] = xtc_threshold
                payload['xtc_probability'] = xtc_probability
            
            # Add DRY if multiplier > 0
            if dry_multiplier > 0:
                payload['dry_multiplier'] = dry_multiplier
                payload['dry_base'] = dry_base
                payload['dry_allowed_length'] = dry_allowed_length
                payload['dry_penalty_last_n'] = dry_penalty_last_n
            
            # Add samplers order if specified
            if samplers:
                payload['samplers'] = samplers.split(';') if isinstance(samplers, str) else samplers
            
            response = httpx.post(
                f"http://127.0.0.1:{self.port}/completion",
                json=payload,
                timeout=180
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('content', '')
                # Pulisci output da markup LaTeX
                content = clean_llm_output(content)
                return content, None
            else:
                return None, f"HTTP {response.status_code}"
        except Exception as e:
            return None, str(e)
    
    def generate_stream(self, prompt, max_tokens=2048, temperature=0.7, top_k=40, top_p=0.95,
                        repeat_penalty=1.0, presence_penalty=0.0, frequency_penalty=0.0,
                        seed=-1, stop=None, token_callback=None,
                        # Extended parameters
                        min_p=0.05, typical_p=1.0, 
                        dynatemp_range=0.0, dynatemp_exponent=1.0,
                        repeat_last_n=64,
                        xtc_threshold=0.1, xtc_probability=0.5,
                        dry_multiplier=0.0, dry_base=1.75, dry_allowed_length=2, dry_penalty_last_n=-1,
                        samplers=None):
        """
        Generate a response in streaming mode, token by token.
        
        Args:
            prompt: The prompt to process
            max_tokens: Maximum number of tokens to generate
            temperature: Controls randomness (0=deterministic, 1+=more creative)
            top_k: Consider only top k most likely tokens (0=disabled)
            top_p: Nucleus sampling - consider tokens up to cumulative probability p
            repeat_penalty: Penalize token repetition (1.0=no penalty)
            presence_penalty: Penalize tokens already appeared (-2.0 to 2.0)
            frequency_penalty: Penalize tokens based on frequency (-2.0 to 2.0)
            seed: Seed for reproducibility (-1=random)
            stop: List of stop strings
            token_callback: Function called for each generated token (token, is_final)
            min_p: Minimum probability threshold
            typical_p: Typical sampling (1.0=disabled)
            dynatemp_range: Dynamic temperature range (0=disabled)
            dynatemp_exponent: Dynamic temperature exponent
            repeat_last_n: Tokens to consider for repeat penalty
            xtc_threshold: XTC threshold
            xtc_probability: XTC probability
            dry_multiplier: DRY multiplier (0=disabled)
            dry_base: DRY base
            dry_allowed_length: DRY allowed length
            dry_penalty_last_n: DRY penalty last n (-1=context)
            samplers: Sampler order string (semicolon separated)
        
        Returns:
            (full_response, error) - The complete response and any error
        """
        if not self.is_running():
            return None, "Process not running"
        
        # Reset flag di stop per nuova generazione
        self.reset_stop_flag()
        
        full_response = ""
        was_stopped = False
        
        try:
            logger.debug(f"Starting stream request to llama-server on port {self.port}")
            
            # Build request payload
            payload = {
                'prompt': prompt,
                'n_predict': max_tokens if max_tokens > 0 else -1,
                'temperature': temperature,
                'top_k': top_k,
                'top_p': top_p,
                'min_p': min_p,
                'typical_p': typical_p,
                'repeat_penalty': repeat_penalty,
                'repeat_last_n': repeat_last_n,
                'presence_penalty': presence_penalty,
                'frequency_penalty': frequency_penalty,
                'seed': seed,
                'stop': stop or [],
                'stream': True
            }
            
            # Add dynamic temperature if enabled
            if dynatemp_range > 0:
                payload['dynatemp_range'] = dynatemp_range
                payload['dynatemp_exponent'] = dynatemp_exponent
            
            # Add XTC if threshold > 0
            if xtc_threshold > 0:
                payload['xtc_threshold'] = xtc_threshold
                payload['xtc_probability'] = xtc_probability
            
            # Add DRY if multiplier > 0
            if dry_multiplier > 0:
                payload['dry_multiplier'] = dry_multiplier
                payload['dry_base'] = dry_base
                payload['dry_allowed_length'] = dry_allowed_length
                payload['dry_penalty_last_n'] = dry_penalty_last_n
            
            # Add samplers order if specified
            if samplers:
                payload['samplers'] = samplers.split(';') if isinstance(samplers, str) else samplers
            
            with httpx.stream(
                'POST',
                f"http://127.0.0.1:{self.port}/completion",
                json=payload,
                timeout=300  # 5 minuti per streaming
            ) as response:
                if response.status_code != 200:
                    logger.error(f"llama-server returned status {response.status_code}")
                    return None, f"HTTP {response.status_code}"
                
                logger.debug("Stream connection established, processing chunks...")
                
                buffer = ""
                for chunk in response.iter_text():
                    # Check if stop was requested
                    if self._stop_streaming:
                        logger.info("Streaming interrupted by stop request")
                        was_stopped = True
                        break
                    
                    buffer += chunk
                    
                    # Processa linee complete (formato SSE: data: {...}\n\n)
                    while '\n' in buffer:
                        # Ricontrolla stop flag durante parsing
                        if self._stop_streaming:
                            was_stopped = True
                            break
                            
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if not line:
                            continue
                        
                        # Rimuovi prefisso "data: " se presente
                        if line.startswith('data: '):
                            line = line[6:]
                        
                        if line == '[DONE]':
                            logger.debug("Received [DONE] marker")
                            continue
                        
                        try:
                            data = json.loads(line)
                            token = data.get('content', '')
                            is_final = data.get('stop', False)
                            
                            if token:
                                full_response += token
                                if token_callback:
                                    # Invia token al callback
                                    token_callback(token, is_final)
                            
                            if is_final:
                                logger.debug("Received final token marker (stop=true)")
                                break
                                
                        except json.JSONDecodeError as e:
                            logger.debug(f"JSON decode error for line: {line[:50]}... - {e}")
                            continue
                    
                    if was_stopped:
                        break
                
                # Processa eventuale buffer rimanente (solo se non stoppato)
                if not was_stopped and buffer.strip():
                    line = buffer.strip()
                    if line.startswith('data: '):
                        line = line[6:]
                    if line and line != '[DONE]':
                        try:
                            data = json.loads(line)
                            token = data.get('content', '')
                            if token:
                                full_response += token
                                if token_callback:
                                    token_callback(token, True)
                        except:
                            pass
            
            if was_stopped:
                logger.info(f"Stream stopped by user, partial response length: {len(full_response)}")
                return full_response, "Stopped by user"
                
            logger.debug(f"Stream completed, total response length: {len(full_response)}")
            return full_response, None
            
        except httpx.TimeoutException as e:
            logger.error(f"Stream timeout: {e}")
            return None, f"Timeout: {str(e)}"
        except Exception as e:
            # If stopped, the error might be due to connection closure
            if self._stop_streaming:
                logger.info(f"Stream interrupted during stop, partial response: {len(full_response)} chars")
                return full_response, "Stopped by user"
            logger.error(f"Stream error: {e}")
            return None, str(e)


class NodeClient:
    """Client principale del nodo"""
    
    def __init__(self, config_path='config.ini'):
        self.config = ConfigParser()
        self.config.read(config_path)
        
        self.server_url = self.config.get('Server', 'URL', fallback='http://localhost:5000')
        self.node_token = self.config.get('Node', 'token', fallback='')
        self.node_name = self.config.get('Node', 'name', fallback='')
        self.price_per_minute = self.config.getint('Node', 'price_per_minute', fallback=100)
        
        # Lightning wallet per ricevere pagamenti
        self.lightning = NodeLightning(self.config)
        
        # Support both new 'command' and old 'bin' for backward compatibility
        self.llama_command = self.config.get('LLM', 'command', fallback='')
        if not self.llama_command:
            self.llama_command = self.config.get('LLM', 'bin', fallback='llama-server')
        
        self.gpu_layers = self.config.getint('LLM', 'gpu_layers', fallback=99)
        
        # Hardware info e modelli (da impostare esternamente)
        self.hardware_info = None
        self.models = []  # Lista modelli per il server
        self.model_manager = None  # Reference to ModelManager for local paths
        
        # Carica modelli da config (legacy)
        self.models_config = {}
        for section in self.config.sections():
            if section.startswith('Model:'):
                name = section[6:]
                self.models_config[name] = {
                    'path': self.config.get(section, 'path', fallback=''),
                    'hf_repo': self.config.get(section, 'hf_repo', fallback=''),
                    'context': self.config.getint(section, 'context', fallback=2048)
                }
        
        self.active_sessions = {}  # session_id -> LlamaProcess
        self.node_id = None
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.running = False
        self._connected = False
        
        # User authentication (set by GUI)
        self.auth_token = None
        self.user_id = None
        
        # GUI callbacks for LLM output visualization
        self.gui_prompt_callback = None  # Called with (session_id, prompt)
        self.gui_token_callback = None   # Called with (token, is_final)
        self.gui_session_ended_callback = None  # Called with (session_id) when session is stopped
        
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        def connect():
            logger.info("Connected to server")
            self._connected = True
            # Registra il nodo con tutte le info
            registration_data = {
                'token': self.node_token,
                'name': self.node_name,
                'models': self.models if self.models else list(self.models_config.keys()),
                'price_per_minute': self.price_per_minute,
            }
            
            # Aggiungi autenticazione utente se disponibile
            if self.auth_token:
                registration_data['auth_token'] = self.auth_token
            if self.user_id:
                registration_data['user_id'] = self.user_id
            
            # Aggiungi hardware info se disponibile
            if self.hardware_info:
                registration_data['hardware'] = self.hardware_info
            
            self.sio.emit('node_register', registration_data)
        
        @self.sio.event
        def disconnect():
            logger.warning("Disconnected from server")
            self._connected = False
        
        @self.sio.on('node_registered')
        def on_registered(data):
            self.node_id = data.get('node_id')
            logger.info(f"Node registered with ID: {self.node_id}")
            # Salva token se nuovo
            if data.get('token'):
                self.node_token = data['token']
                self._save_token(data['token'])
        
        @self.sio.on('start_session')
        def on_start_session(data):
            """Richiesta di avviare una sessione"""
            logger.info(f"=== RECEIVED start_session event ===")
            logger.info(f"start_session data: {data}")
            
            session_id = str(data['session_id'])
            model_id = data.get('model_id') or data.get('model')
            model_name = data.get('model_name', model_id)
            context = data.get('context', 2048)
            hf_repo_direct = data.get('hf_repo')  # HuggingFace repo passato direttamente per download on-demand
            
            logger.info(f"Starting session {session_id} with model {model_name} (id: {model_id})")
            if hf_repo_direct:
                logger.info(f"HuggingFace repo provided directly for on-demand download: {hf_repo_direct}")
            
            # Cerca il modello - supporta sia HuggingFace che locale
            model_source = None
            use_hf = False
            
            # If hf_repo was passed directly, use it for on-demand download
            if hf_repo_direct:
                model_source = hf_repo_direct
                use_hf = True
                logger.info(f"Using direct HuggingFace repo for on-demand download: {model_source}")
            
            # Cerca nei modelli config (legacy) - supporta hf_repo
            elif model_name in self.models_config:
                cfg = self.models_config[model_name]
                if cfg.get('hf_repo'):
                    model_source = cfg['hf_repo']
                    use_hf = True
                elif cfg.get('path'):
                    model_source = cfg['path']
                    use_hf = False
                context = cfg.get('context', context)
            
            # Cerca tramite ModelManager
            elif self.model_manager:
                logger.info(f"Searching ModelManager for model_id={model_id}")
                logger.info(f"Available models in ModelManager: {list(self.model_manager.models.keys())}")
                
                model_info = self.model_manager.get_model_by_id(model_id)
                logger.info(f"get_model_by_id({model_id}) returned: {model_info}")
                
                if not model_info:
                    model_info = self.model_manager.get_model_by_name(model_name)
                    logger.info(f"get_model_by_name({model_name}) returned: {model_info}")
                
                if model_info:
                    # Check if it's a HuggingFace model
                    if hasattr(model_info, 'hf_repo') and model_info.hf_repo:
                        model_source = model_info.hf_repo
                        use_hf = True
                        logger.info(f"Found HuggingFace model: {model_source}")
                    elif hasattr(model_info, 'filepath') and model_info.filepath:
                        model_source = model_info.filepath
                        use_hf = False
                        logger.info(f"Using local model filepath: {model_source}")
                        # Verifica che il filepath sia un file, non una directory
                        if os.path.isdir(model_source):
                            corrected_path = os.path.join(self.model_manager.models_dir, model_info.filename)
                            logger.warning(f"filepath was a directory, correcting to: {corrected_path}")
                            model_source = corrected_path
                        # Verifica che il file esista
                        if not os.path.exists(model_source):
                            logger.error(f"Model file does not exist at: {model_source}")
                        logger.info(f"Found local model: {model_source}, exists={os.path.exists(model_source)}")
                    
                    context = getattr(model_info, 'context_length', context) or context
                else:
                    logger.warning(f"Model not found in ModelManager: id={model_id}, name={model_name}")
            
            # Fallback: cerca per model_id nei modelli sync
            if not model_source and isinstance(self.models, list):
                for m in self.models:
                    if m.get('id') == model_id or m.get('name') == model_name:
                        # Check if it's HuggingFace
                        if m.get('hf_repo'):
                            model_source = m.get('hf_repo')
                            use_hf = True
                        elif m.get('filename'):
                            models_dir = self.config.get('Models', 'directory', fallback='.')
                            potential_path = os.path.join(models_dir, m.get('filename'))
                            if os.path.exists(potential_path):
                                model_source = potential_path
                                use_hf = False
                        context = m.get('context_length', context)
                        break
            
            if not model_source:
                error_msg = f'Model {model_name} (id: {model_id}) not available'
                logger.error(error_msg)
                self.sio.emit('session_error', {
                    'session_id': session_id,
                    'node_id': self.node_id,
                    'error': error_msg
                })
                return
            
            # Per modelli locali, verifica che il file esista
            if not use_hf and not os.path.exists(model_source):
                error_msg = f'Local model file not found: {model_source}'
                logger.error(error_msg)
                self.sio.emit('session_error', {
                    'session_id': session_id,
                    'node_id': self.node_id,
                    'error': error_msg
                })
                return
            
            # IMPORTANT: Close all existing sessions before starting a new one
            # (only one model at a time can be loaded)
            if self.active_sessions:
                logger.info(f"Closing {len(self.active_sessions)} existing session(s) before starting new one")
                for old_session_id, old_llama in list(self.active_sessions.items()):
                    logger.info(f"Stopping existing session {old_session_id}")
                    old_llama.request_stop_streaming()
                    old_llama.stop()
                    # Notify server that session was closed
                    self.sio.emit('session_stopped', {'session_id': old_session_id})
                self.active_sessions.clear()
            
            # Trova porta libera
            port = self._find_free_port()
            
            # Avvia llama-server
            llama = LlamaProcess(
                self.llama_command,
                model_source,
                port,
                context,
                self.gpu_layers,
                use_hf=use_hf
            )
            
            # Notify that we are starting (may require download)
            if use_hf and self.sio.connected:
                self.sio.emit('session_status', {
                    'session_id': session_id,
                    'status': 'downloading',
                    'message': f'Downloading model from HuggingFace: {model_source}'
                })
            
            def status_callback(status, msg):
                """Callback for status updates during download/loading"""
                try:
                    if self.sio.connected:
                        self.sio.emit('session_status', {
                            'session_id': session_id,
                            'status': status,
                            'message': msg
                        })
                except Exception as e:
                    logger.warning(f"Failed to emit status update: {e}")
            
            if llama.start(download_callback=status_callback):
                self.active_sessions[session_id] = llama
                
                # Track model usage - increment use_count
                if self.model_manager and model_id:
                    self.model_manager.mark_model_used(model_id)
                    logger.info(f"Updated usage stats for model {model_id}")
                
                if self.sio.connected:
                    self.sio.emit('session_started', {
                        'session_id': session_id,
                        'node_id': self.node_id,
                        'status': 'ready'
                    })
                else:
                    logger.warning(f"Cannot emit session_started: socket disconnected")
                    # Clean up the session since we can't notify the server
                    llama.stop()
                    del self.active_sessions[session_id]
            else:
                if self.sio.connected:
                    self.sio.emit('session_error', {
                        'session_id': session_id,
                        'node_id': self.node_id,
                        'error': 'Failed to start llama-server (check logs for details)'
                    })
                else:
                    logger.warning(f"Cannot emit session_error: socket disconnected")
        
        @self.sio.on('stop_session')
        def on_stop_session(data):
            """Richiesta di fermare una sessione"""
            session_id = str(data['session_id'])
            logger.info(f"[STOP_SESSION] Received stop_session request for session {session_id}")
            logger.info(f"[STOP_SESSION] Active sessions: {list(self.active_sessions.keys())}")
            
            if session_id in self.active_sessions:
                llama_process = self.active_sessions[session_id]
                logger.info(f"[STOP_SESSION] Found session {session_id}, stopping llama-server process...")
                
                # Prima richiedi lo stop dello streaming (se in corso)
                llama_process.request_stop_streaming()
                
                # Poi ferma il processo
                llama_process.stop()
                
                # Rimuovi dalla lista delle sessioni attive
                del self.active_sessions[session_id]
                
                logger.info(f"[STOP_SESSION] Session {session_id} stopped - llama-server process terminated")
                logger.info(f"[STOP_SESSION] Remaining active sessions: {list(self.active_sessions.keys())}")
                
                # Notify GUI that session was stopped
                if self.gui_session_ended_callback:
                    try:
                        self.gui_session_ended_callback(session_id)
                    except Exception as e:
                        logger.error(f"GUI session ended callback error: {e}")
            else:
                logger.warning(f"[STOP_SESSION] Session {session_id} not found in active sessions")
            
            self.sio.emit('session_stopped', {'session_id': session_id})
        
        @self.sio.on('inference_request')
        def on_inference(data):
            """Inference request with streaming"""
            session_id = str(data['session_id'])
            prompt = data['prompt']
            
            # Basic parameters
            max_tokens = data.get('max_tokens', -1)  # -1 = use model context
            temperature = data.get('temperature', 0.7)
            top_k = data.get('top_k', 40)
            top_p = data.get('top_p', 0.95)
            seed = data.get('seed', -1)
            stop = data.get('stop', [])
            use_streaming = data.get('stream', True)
            
            # Extended sampling parameters
            min_p = data.get('min_p', 0.05)
            typical_p = data.get('typical_p', 1.0)
            dynatemp_range = data.get('dynatemp_range', 0.0)
            dynatemp_exponent = data.get('dynatemp_exponent', 1.0)
            
            # Penalties
            repeat_last_n = data.get('repeat_last_n', 64)
            repeat_penalty = data.get('repeat_penalty', 1.0)
            presence_penalty = data.get('presence_penalty', 0.0)
            frequency_penalty = data.get('frequency_penalty', 0.0)
            
            # DRY parameters
            dry_multiplier = data.get('dry_multiplier', 0.0)
            dry_base = data.get('dry_base', 1.75)
            dry_allowed_length = data.get('dry_allowed_length', 2)
            dry_penalty_last_n = data.get('dry_penalty_last_n', -1)
            
            # XTC parameters
            xtc_threshold = data.get('xtc_threshold', 0.1)
            xtc_probability = data.get('xtc_probability', 0.5)
            
            # Sampler order
            samplers = data.get('samplers', None)
            
            logger.info(f"Inference request for session {session_id}: temp={temperature}, top_k={top_k}, top_p={top_p}, min_p={min_p}")
            
            if session_id not in self.active_sessions:
                self.sio.emit('inference_error', {
                    'session_id': session_id,
                    'error': 'Session not found'
                })
                return
            
            llama = self.active_sessions[session_id]
            
            # Notify GUI of received prompt
            if self.gui_prompt_callback:
                try:
                    self.gui_prompt_callback(session_id, prompt)
                except Exception as e:
                    logger.error(f"GUI prompt callback error: {e}")
            
            # Execute in thread to avoid blocking
            def do_inference():
                if use_streaming:
                    # Streaming: invia token per token
                    token_count = 0
                    start_time = time.time()
                    last_emit_time = time.time()
                    
                    def token_callback(token, is_final):
                        nonlocal token_count, last_emit_time
                        token_count += 1
                        
                        # Log every 10 tokens to avoid spam
                        if token_count <= 3 or token_count % 10 == 0:
                            logger.info(f"[STREAM] Token {token_count} for session {session_id}")
                        
                        # Notify GUI of token
                        if self.gui_token_callback:
                            try:
                                self.gui_token_callback(token, is_final)
                            except Exception as e:
                                logger.error(f"GUI token callback error: {e}")
                        
                        try:
                            self.sio.emit('inference_token', {
                                'session_id': session_id,
                                'token': token,
                                'is_final': is_final
                            })
                            # Piccolo delay per permettere al socket di inviare
                            time.sleep(0.01)
                        except Exception as e:
                            logger.error(f"Error emitting token: {e}")
                    
                    logger.info(f"Starting streaming inference for session {session_id}")
                    result, error = llama.generate_stream(
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_k=top_k,
                        top_p=top_p,
                        min_p=min_p,
                        typical_p=typical_p,
                        dynatemp_range=dynatemp_range,
                        dynatemp_exponent=dynatemp_exponent,
                        repeat_last_n=repeat_last_n,
                        repeat_penalty=repeat_penalty,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty,
                        seed=seed,
                        stop=stop,
                        token_callback=token_callback,
                        xtc_threshold=xtc_threshold,
                        xtc_probability=xtc_probability,
                        dry_multiplier=dry_multiplier,
                        dry_base=dry_base,
                        dry_allowed_length=dry_allowed_length,
                        dry_penalty_last_n=dry_penalty_last_n,
                        samplers=samplers
                    )
                    logger.info(f"Streaming complete for session {session_id}: {token_count} tokens")
                    
                    response_time_ms = (time.time() - start_time) * 1000
                    
                    if error:
                        self.sio.emit('inference_error', {
                            'session_id': session_id,
                            'error': error
                        })
                    else:
                        # Invia token finale esplicito per segnalare fine streaming
                        logger.info(f"Sending final token marker for session {session_id}")
                        try:
                            self.sio.emit('inference_token', {
                                'session_id': session_id,
                                'token': '',
                                'is_final': True
                            })
                            time.sleep(0.05)  # Assicura che arrivi prima di inference_complete
                        except Exception as e:
                            logger.error(f"Error emitting final token: {e}")
                        
                        # Invia anche la risposta completa (pulita) alla fine con metriche
                        self.sio.emit('inference_complete', {
                            'session_id': session_id,
                            'content': result,
                            'tokens_generated': token_count,
                            'response_time_ms': response_time_ms
                        })
                else:
                    # Non-streaming: risposta completa
                    start_time = time.time()
                    result, error = llama.generate(
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_k=top_k,
                        top_p=top_p,
                        repeat_penalty=repeat_penalty,
                        presence_penalty=presence_penalty,
                        frequency_penalty=frequency_penalty,
                        seed=seed,
                        stop=stop
                    )
                    response_time_ms = (time.time() - start_time) * 1000
                    
                    if error:
                        self.sio.emit('inference_error', {
                            'session_id': session_id,
                            'error': error
                        })
                    else:
                        # Stima token generati (approssimazione)
                        estimated_tokens = len(result.split()) if result else 0
                        self.sio.emit('inference_response', {
                            'session_id': session_id,
                            'content': result,
                            'tokens_generated': estimated_tokens,
                            'response_time_ms': response_time_ms
                        })
            
            threading.Thread(target=do_inference, daemon=True).start()
    
    def _find_free_port(self):
        """Trova una porta libera"""
        import socket
        start = self.config.getint('LLM', 'port_start', fallback=11000)
        end = self.config.getint('LLM', 'port_end', fallback=12000)
        
        for port in range(start, end):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    return port
            except:
                continue
        raise Exception("No free ports")
    
    def _save_token(self, token):
        """Save token to config"""
        self.config.set('Node', 'token', token)
        with open('config.ini', 'w') as f:
            self.config.write(f)
    
    def _start_local_http_server(self, port=9000):
        """
        Start a local HTTP server to receive requests from the main server.
        Primarily used for /api/create_invoice endpoint for Lightning payments.
        """
        app = Flask(__name__)
        app.logger.setLevel(logging.WARNING)  # Reduce verbosity
        
        node_client = self  # Reference for routes
        
        @app.route('/api/create_invoice', methods=['POST'])
        def create_invoice():
            """Create a Lightning invoice to receive a payment"""
            if not node_client.lightning.enabled:
                return jsonify({'error': 'Lightning not configured on this node'}), 400
            
            data = request.get_json()
            amount = data.get('amount', 0)
            description = data.get('description', 'AI Lightning node payment')
            
            if amount <= 0:
                return jsonify({'error': 'Invalid amount'}), 400
            
            result = node_client.lightning.create_invoice(amount, description)
            if result:
                return jsonify(result)
            else:
                return jsonify({'error': 'Failed to create invoice'}), 500
        
        @app.route('/api/health', methods=['GET'])
        def health():
            return jsonify({
                'status': 'ok',
                'node_id': node_client.node_id,
                'lightning_enabled': node_client.lightning.enabled,
                'active_sessions': len(node_client.active_sessions)
            })
        
        @app.route('/api/stop_session', methods=['POST'])
        def stop_session():
            """Ferma una sessione (endpoint HTTP legacy)"""
            data = request.get_json()
            session_id = str(data.get('session_id'))
            
            if session_id in node_client.active_sessions:
                node_client.active_sessions[session_id].stop()
                del node_client.active_sessions[session_id]
                logger.info(f"Session {session_id} stopped via HTTP")
                return jsonify({'success': True})
            
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Avvia in thread separato
        def run_server():
            from werkzeug.serving import make_server
            server = make_server('0.0.0.0', port, app, threaded=True)
            logger.info(f"Local HTTP server started on port {port}")
            server.serve_forever()
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        return thread
    
    def connect(self):
        """Connetti al server"""
        try:
            logger.info(f"Connecting to {self.server_url}")
            
            # Avvia server HTTP locale per ricevere richieste (es. create_invoice)
            self._start_local_http_server(port=9000)
            
            self.sio.connect(self.server_url, wait_timeout=10)
            self.running = True
            self._connected = True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            return False
        return True
    
    def is_connected(self):
        """Verifica se connesso"""
        return self._connected and self.sio.connected
    
    def sync_models(self, models):
        """Sincronizza modelli con il server"""
        if not self.is_connected():
            logger.warning("Cannot sync models: not connected")
            return False
        
        self.models = models
        
        sync_data = {
            'node_id': self.node_id,
            'models': models
        }
        
        if self.hardware_info:
            sync_data['hardware'] = self.hardware_info
        
        self.sio.emit('node_models_update', sync_data)
        logger.info(f"Synced {len(models)} models with server")
        return True
    
    def cleanup_all_sessions(self):
        """Ferma tutte le sessioni llama-server attive"""
        if not self.active_sessions:
            return
        
        logger.info(f"Cleaning up {len(self.active_sessions)} active session(s)...")
        for session_id, llama in list(self.active_sessions.items()):
            try:
                logger.info(f"Stopping llama-server for session {session_id}")
                llama.request_stop_streaming()
                llama.stop()
            except Exception as e:
                logger.error(f"Error stopping session {session_id}: {e}")
        self.active_sessions.clear()
        logger.info("All sessions cleaned up")
    
    def disconnect(self):
        """Disconnetti e ferma tutto"""
        self.running = False
        self._connected = False
        
        # Ferma tutte le sessioni
        self.cleanup_all_sessions()
        
        try:
            self.sio.disconnect()
        except:
            pass
    
    def run(self):
        """Main loop con reconnect automatico"""
        while self.running:
            if not self.sio.connected:
                try:
                    self.connect()
                except:
                    pass
            time.sleep(5)
    
    def wait(self):
        """Attendi disconnessione"""
        self.sio.wait()


def detect_gpu():
    """Detect GPU type"""
    # Try NVIDIA
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            return 'nvidia'
    except:
        pass
    
    # Try AMD (Windows)
    try:
        # ROCm on Windows is limited, but let's try
        if sys.platform == 'win32':
            # Check if hip runtime exists
            hip_path = os.environ.get('HIP_PATH', '')
            if hip_path and os.path.exists(hip_path):
                return 'amd'
    except:
        pass
    
    return 'cpu'


def find_llama_binary():
    """
    Trova il comando/binario llama-server.
    Ora supporta sia file .exe che comando nel PATH.
    """
    base_dir = Path(__file__).parent
    
    gpu = detect_gpu()
    logger.info(f"Detected GPU: {gpu}")
    
    # First check if llama-server is in PATH
    try:
        result = subprocess.run(
            ['llama-server', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 or 'llama' in result.stdout.lower() or 'llama' in result.stderr.lower():
            logger.info("Found llama-server in PATH")
            return 'llama-server'  # Usa comando nel PATH
    except:
        pass
    
    # Altrimenti cerca l'eseguibile
    if sys.platform == 'win32':
        if gpu == 'nvidia':
            candidates = [
                base_dir / 'llama-server-cuda.exe',
                base_dir / 'llama-server.exe',
                Path('C:/llama.cpp/llama-server.exe'),
                Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages' / 'ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe' / 'llama-server.exe'
            ]
        elif gpu == 'amd':
            candidates = [
                base_dir / 'llama-server-rocm.exe',
                base_dir / 'llama-server.exe',
                Path('C:/llama.cpp/llama-server.exe')
            ]
        else:
            candidates = [
                base_dir / 'llama-server.exe',
                Path('C:/llama.cpp/llama-server.exe')
            ]
    else:
        candidates = [
            base_dir / 'llama-server',
            Path.home() / 'llama.cpp' / 'llama-server',
            Path('/usr/local/bin/llama-server'),
            Path('/usr/bin/llama-server')
        ]
    
    for path in candidates:
        if path.exists():
            return str(path)
    
    # Default: ritorna 'llama-server' sperando sia nel PATH
    return 'llama-server'


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Lightning Node Client')
    parser.add_argument('--config', default='config.ini', help='Config file path')
    parser.add_argument('--server', help='Server URL override')
    args = parser.parse_args()
    
    # Crea config se non esiste
    if not os.path.exists(args.config):
        logger.info("Creating default config...")
        
        llama_cmd = find_llama_binary()
        
        config = ConfigParser()
        config['Node'] = {
            'token': ''
        }
        config['Server'] = {
            'URL': args.server or 'http://localhost:5000'
        }
        config['LLM'] = {
            'command': llama_cmd or 'llama-server',
            'gpu_layers': '99',
            'port_start': '11000',
            'port_end': '12000'
        }
        # Esempio modello HuggingFace
        config['Model:llama3.2-1b'] = {
            'hf_repo': 'bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M',
            'context': '4096'
        }
        
        with open(args.config, 'w') as f:
            config.write(f)
        
        logger.info(f"Config created at {args.config}")
        logger.info("Edit the config to add your models (HuggingFace repos or local GGUF paths)")
        sys.exit(0)
    
    client = NodeClient(args.config)
    
    if args.server:
        client.server_url = args.server
    
    # Signal handler per terminazione pulita
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        client.cleanup_all_sessions()
        client.disconnect()
        sys.exit(0)
    
    # Registra handlers per SIGINT (Ctrl+C) e SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Registra cleanup anche per atexit (chiusura normale)
    atexit.register(client.cleanup_all_sessions)
    
    try:
        if client.connect():
            client.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt)...")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        client.cleanup_all_sessions()
        client.disconnect()

"""
AI Lightning Node Client

Client per nodi host dietro NAT.
Si connette al server via WebSocket e riceve richieste di inferenza.
"""
import os
import sys
import json
import time
import subprocess
import threading
import logging
import socketio
import httpx
from pathlib import Path
from configparser import ConfigParser

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('NodeClient')

class LlamaProcess:
    """Gestisce un processo llama.cpp"""
    
    def __init__(self, llama_bin, model_path, port, context=2048, gpu_layers=99):
        self.llama_bin = llama_bin
        self.model_path = model_path
        self.port = port
        self.context = context
        self.gpu_layers = gpu_layers
        self.process = None
        
    def start(self):
        """Avvia il server llama.cpp"""
        # Verifica che llama_bin esista
        if not self.llama_bin or not os.path.exists(self.llama_bin):
            logger.error(f"llama.cpp binary not found: {self.llama_bin}")
            return False
        
        # Verifica che il modello esista
        if not self.model_path or not os.path.exists(self.model_path):
            logger.error(f"Model file not found: {self.model_path}")
            return False
        
        cmd = [
            self.llama_bin,
            '-m', self.model_path,
            '--host', '127.0.0.1',
            '--port', str(self.port),
            '--ctx-size', str(self.context),
            '-ngl', str(self.gpu_layers),
            '--log-disable'
        ]
        
        logger.info(f"Starting llama.cpp: {' '.join(cmd)}")
        
        # Nascondi finestra su Windows
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo
        )
        
        # Attendi che sia pronto
        for i in range(60):
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if r.status_code == 200:
                    logger.info(f"llama.cpp ready on port {self.port}")
                    return True
            except:
                pass
            time.sleep(1)
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode()
                logger.error(f"llama.cpp crashed: {stderr}")
                return False
        
        logger.error("llama.cpp failed to start in time")
        self.stop()
        return False
    
    def stop(self):
        """Ferma il processo"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None
    
    def is_running(self):
        return self.process and self.process.poll() is None
    
    def generate(self, prompt, max_tokens=256, temperature=0.7, stop=None):
        """Genera una risposta"""
        if not self.is_running():
            return None, "Process not running"
        
        try:
            response = httpx.post(
                f"http://127.0.0.1:{self.port}/completion",
                json={
                    'prompt': prompt,
                    'n_predict': max_tokens,
                    'temperature': temperature,
                    'stop': stop or [],
                    'stream': False
                },
                timeout=180
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('content', ''), None
            else:
                return None, f"HTTP {response.status_code}"
        except Exception as e:
            return None, str(e)


class NodeClient:
    """Client principale del nodo"""
    
    def __init__(self, config_path='config.ini'):
        self.config = ConfigParser()
        self.config.read(config_path)
        
        self.server_url = self.config.get('Server', 'URL', fallback='http://localhost:5000')
        self.node_token = self.config.get('Node', 'token', fallback='')
        self.node_name = self.config.get('Node', 'name', fallback='')
        self.llama_bin = self.config.get('LLM', 'bin', fallback='')
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
                    'path': self.config.get(section, 'path'),
                    'context': self.config.getint(section, 'context', fallback=2048)
                }
        
        self.active_sessions = {}  # session_id -> LlamaProcess
        self.node_id = None
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.running = False
        self._connected = False
        
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
            }
            
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
            session_id = str(data['session_id'])
            model_id = data.get('model_id') or data.get('model')
            model_name = data.get('model_name', model_id)
            context = data.get('context', 2048)
            
            logger.info(f"Starting session {session_id} with model {model_name} (id: {model_id})")
            
            # Cerca il modello - prima per ID, poi per nome
            model_path = None
            
            # Cerca nei modelli config (legacy)
            if model_name in self.models_config:
                model_path = self.models_config[model_name]['path']
                context = self.models_config[model_name].get('context', context)
            
            # Cerca tramite ModelManager (ha i filepath locali)
            elif self.model_manager:
                model_info = self.model_manager.get_model_by_id(model_id)
                if not model_info:
                    model_info = self.model_manager.get_model_by_name(model_name)
                if model_info:
                    model_path = model_info.filepath
                    context = model_info.context_length or context
                    logger.info(f"Found model via ModelManager: {model_path}")
            
            # Fallback: cerca per model_id nei modelli sync (senza filepath)
            if not model_path and isinstance(self.models, list):
                models_dir = self.config.get('Models', 'directory', fallback='.')
                for m in self.models:
                    if m.get('id') == model_id or m.get('name') == model_name:
                        # Prova a trovare il file nella directory
                        if m.get('filename'):
                            potential_path = os.path.join(models_dir, m.get('filename'))
                            if os.path.exists(potential_path):
                                model_path = potential_path
                                context = m.get('context_length', context)
                        break
            
            if not model_path or not os.path.exists(model_path):
                error_msg = f'Model {model_name} (id: {model_id}) not available or file not found'
                logger.error(error_msg)
                self.sio.emit('session_error', {
                    'session_id': session_id,
                    'error': error_msg
                })
                return
            
            # Trova porta libera
            port = self._find_free_port()
            
            # Avvia llama.cpp
            llama = LlamaProcess(
                self.llama_bin,
                model_path,
                port,
                context,
                self.gpu_layers
            )
            
            if llama.start():
                self.active_sessions[session_id] = llama
                self.sio.emit('session_started', {
                    'session_id': session_id,
                    'status': 'ready'
                })
            else:
                self.sio.emit('session_error', {
                    'session_id': session_id,
                    'error': 'Failed to start llama.cpp'
                })
        
        @self.sio.on('stop_session')
        def on_stop_session(data):
            """Richiesta di fermare una sessione"""
            session_id = str(data['session_id'])
            
            if session_id in self.active_sessions:
                self.active_sessions[session_id].stop()
                del self.active_sessions[session_id]
                logger.info(f"Session {session_id} stopped")
            
            self.sio.emit('session_stopped', {'session_id': session_id})
        
        @self.sio.on('inference_request')
        def on_inference(data):
            """Richiesta di inferenza"""
            session_id = str(data['session_id'])
            prompt = data['prompt']
            max_tokens = data.get('max_tokens', 256)
            temperature = data.get('temperature', 0.7)
            stop = data.get('stop', [])
            
            if session_id not in self.active_sessions:
                self.sio.emit('inference_error', {
                    'session_id': session_id,
                    'error': 'Session not found'
                })
                return
            
            llama = self.active_sessions[session_id]
            
            # Esegui in thread per non bloccare
            def do_inference():
                result, error = llama.generate(prompt, max_tokens, temperature, stop)
                
                if error:
                    self.sio.emit('inference_error', {
                        'session_id': session_id,
                        'error': error
                    })
                else:
                    self.sio.emit('inference_response', {
                        'session_id': session_id,
                        'content': result
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
        """Salva il token nel config"""
        self.config.set('Node', 'token', token)
        with open('config.ini', 'w') as f:
            self.config.write(f)
    
    def connect(self):
        """Connetti al server"""
        try:
            logger.info(f"Connecting to {self.server_url}")
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
    
    def disconnect(self):
        """Disconnetti e ferma tutto"""
        self.running = False
        self._connected = False
        
        # Ferma tutte le sessioni
        for session_id, llama in list(self.active_sessions.items()):
            llama.stop()
        self.active_sessions.clear()
        
        self.sio.disconnect()
    
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
    """Rileva il tipo di GPU"""
    # Prova NVIDIA
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            return 'nvidia'
    except:
        pass
    
    # Prova AMD (Windows)
    try:
        # ROCm su Windows è limitato, ma proviamo
        if sys.platform == 'win32':
            # Controlla se esiste hip runtime
            hip_path = os.environ.get('HIP_PATH', '')
            if hip_path and os.path.exists(hip_path):
                return 'amd'
    except:
        pass
    
    return 'cpu'


def find_llama_binary():
    """Trova il binario llama.cpp appropriato"""
    base_dir = Path(__file__).parent
    
    gpu = detect_gpu()
    logger.info(f"Detected GPU: {gpu}")
    
    if sys.platform == 'win32':
        if gpu == 'nvidia':
            candidates = [
                base_dir / 'llama-server-cuda.exe',
                base_dir / 'llama-server.exe',
                Path('C:/llama.cpp/llama-server.exe')
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
            Path('/usr/local/bin/llama-server')
        ]
    
    for path in candidates:
        if path.exists():
            return str(path)
    
    return None


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Lightning Node Client')
    parser.add_argument('--config', default='config.ini', help='Config file path')
    parser.add_argument('--server', help='Server URL override')
    args = parser.parse_args()
    
    # Crea config se non esiste
    if not os.path.exists(args.config):
        logger.info("Creating default config...")
        
        llama_bin = find_llama_binary()
        
        config = ConfigParser()
        config['Node'] = {
            'token': ''
        }
        config['Server'] = {
            'URL': args.server or 'http://localhost:5000'
        }
        config['LLM'] = {
            'bin': llama_bin or 'llama-server.exe',
            'gpu_layers': '99',
            'port_start': '11000',
            'port_end': '12000'
        }
        config['Model:default'] = {
            'path': 'models/model.gguf',
            'context': '2048'
        }
        
        with open(args.config, 'w') as f:
            config.write(f)
        
        logger.info(f"Config created at {args.config}")
        logger.info("Please edit the config and add your model path, then restart.")
        sys.exit(0)
    
    client = NodeClient(args.config)
    
    if args.server:
        client.server_url = args.server
    
    try:
        if client.connect():
            client.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        client.disconnect()

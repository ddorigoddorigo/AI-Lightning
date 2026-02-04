"""
Server del nodo host.

Espone un'API per il server principale.
"""
from flask import Flask, request, jsonify
import subprocess
import threading
import socket
import time
import logging
import httpx
from .node_config import Config

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
config = Config()
active_sessions = {}  # session_id -> {'process': proc, 'port': port, 'started_at': timestamp}
port_lock = threading.Lock()
heartbeat_thread = None
shutdown_event = threading.Event()


def find_available_port():
    """Find an available port in the configured range."""
    with port_lock:
        for port in range(config.port_range[0], config.port_range[1]):
            try:
                # Prova a creare un socket sulla porta
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                return port
            except OSError:
                continue
    raise Exception("No available ports")


def heartbeat_loop():
    """Thread che invia heartbeat periodici al server principale."""
    while not shutdown_event.is_set():
        try:
            if config.node_id:
                response = httpx.post(
                    f"{config.server_url}/api/node_heartbeat",
                    json={
                        'node_id': config.node_id,
                        'load': len(active_sessions),
                        'models': list(config.models.keys())
                    },
                    timeout=5
                )
                if response.status_code == 200:
                    logger.debug(f"Heartbeat sent successfully")
                else:
                    logger.warning(f"Heartbeat failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        
        # Attendi 10 secondi prima del prossimo heartbeat
        shutdown_event.wait(10)


def start_heartbeat():
    """Avvia il thread di heartbeat."""
    global heartbeat_thread
    if heartbeat_thread is None or not heartbeat_thread.is_alive():
        shutdown_event.clear()
        heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        logger.info("Heartbeat thread started")


def stop_heartbeat():
    """Ferma il thread di heartbeat."""
    shutdown_event.set()
    if heartbeat_thread:
        heartbeat_thread.join(timeout=5)
        logger.info("Heartbeat thread stopped")


def cleanup_stale_sessions():
    """Pulisce sessioni inattive o con processi terminati."""
    to_remove = []
    for session_id, info in active_sessions.items():
        proc = info['process']
        if proc.poll() is not None:  # Processo terminato
            logger.info(f"Cleaning up terminated session {session_id}")
            to_remove.append(session_id)
    
    for session_id in to_remove:
        del active_sessions[session_id]

@app.route('/api/register', methods=['POST'])
def register():
    """
    Registra il nodo sul server principale.

    Request body:
    - node_id: ID del nodo
    - address: Indirizzo del nodo
    - models: Dict di modelli

    Returns:
    - node_id: ID del nodo
    """
    data = request.get_json()
    with open('config.ini', 'w') as f:
        cfg = config.parser
        cfg['Node'] = {
            'id': data['node_id'],
            'address': data['address']
        }
        for name, model in data['models'].items():
            cfg[f'Model:{name}'] = {
                'path': model['path'],
                'context': str(model['context'])
            }
        cfg.write(f)

    return jsonify({
        'status': 'registered',
        'node_id': data['node_id']
    })

@app.route('/api/start_session', methods=['POST'])
def start_session():
    """
    Avvia una nuova sessione.

    Request body:
    - session_id: ID della sessione
    - model: Nome del modello
    - context: Contesto (n_tokens)
    - llama_bin: Path a llama.cpp

    Returns:
    - status: 'started'
    - port: Porta di llama.cpp
    """
    data = request.get_json()
    session_id = data['session_id']
    model = data['model']
    context = data['context']
    llama_bin = data['llama_bin']

    if model not in config.models:
        return jsonify({'error': 'Model not available'}), 400

    try:
        port = find_available_port()
        
        # Usa il path locale del modello invece di quello ricevuto
        model_path = config.models[model]['path']
        llama_bin_path = config.llama_bin
        
        logger.info(f"Starting llama.cpp for session {session_id} on port {port}")
        logger.info(f"Command: {llama_bin_path} -m {model_path} --ctx-size {context} --host 0.0.0.0 --port {port}")
        
        proc = subprocess.Popen(
            [
                llama_bin_path,
                '-m', model_path,
                '--ctx-size', str(context),
                '--host', '0.0.0.0',
                '--port', str(port),
                '--log-disable'  # Riduce output di log
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Verifica che il processo sia partito
        time.sleep(0.5)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode()
            logger.error(f"llama.cpp failed to start: {stderr}")
            return jsonify({'error': f'llama.cpp failed to start: {stderr}'}), 500
        
        # Attendi che il server sia pronto verificando l'endpoint /health
        server_ready = False
        for attempt in range(60):  # Max 60 secondi
            try:
                # llama.cpp server exposes /health when ready
                health_check = httpx.get(f"http://localhost:{port}/health", timeout=1)
                if health_check.status_code == 200:
                    server_ready = True
                    logger.info(f"llama.cpp server ready on port {port} after {attempt+1} seconds")
                    break
            except Exception:
                pass
            time.sleep(1)
            
            # Verifica che il processo sia ancora vivo
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode()
                logger.error(f"llama.cpp process died: {stderr}")
                return jsonify({'error': f'llama.cpp process died: {stderr}'}), 500
        
        if not server_ready:
            proc.terminate()
            return jsonify({'error': 'llama.cpp server failed to start in time'}), 500
        
        # Converti session_id a stringa per consistenza
        session_key = str(session_id)
        
        active_sessions[session_key] = {
            'process': proc,
            'port': port,
            'model': model,
            'started_at': time.time()
        }
        
        logger.info(f"Session {session_key} started successfully on port {port}")
        
        return jsonify({
            'status': 'started',
            'port': port,
            'process_id': proc.pid
        })
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_session', methods=['POST'])
def stop_session():
    """
    Termina una sessione.

    Request body:
    - session_id: ID della sessione
    """
    data = request.get_json()
    session_key = str(data['session_id'])  # Converti a stringa

    if session_key in active_sessions:
        info = active_sessions[session_key]
        proc = info['process']
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        del active_sessions[session_key]
        logger.info(f"Session {session_key} stopped")

    return jsonify({'status': 'stopped'})


@app.route('/api/session_info/<session_id>', methods=['GET'])
def session_info(session_id):
    """
    Restituisce informazioni su una sessione attiva.
    
    Returns:
    - port: Porta del server llama.cpp
    - model: Modello in uso
    - uptime: Secondi dall'avvio
    """
    session_key = str(session_id)  # Converti a stringa
    
    if session_key not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    info = active_sessions[session_key]
    return jsonify({
        'port': info['port'],
        'model': info['model'],
        'uptime': int(time.time() - info['started_at']),
        'status': 'running' if info['process'].poll() is None else 'stopped'
    })


@app.route('/api/completion/<session_id>', methods=['POST'])
def completion(session_id):
    """
    Proxy per le richieste di completamento a llama.cpp.
    Il server principale chiama questo endpoint invece di accedere
    direttamente alla porta di llama.cpp.
    
    Request body:
    - prompt: Il prompt da completare
    - max_tokens: Numero massimo di token da generare (default: 256)
    - temperature: Temperatura (default: 0.7)
    - stop: Lista di stringhe per fermare la generazione (optional)
    
    Returns:
    - content: La risposta generata
    - model: Il modello usato
    - tokens_generated: Numero di token generati
    """
    session_key = str(session_id)
    
    if session_key not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    info = active_sessions[session_key]
    
    # Verifica che il processo sia ancora attivo
    if info['process'].poll() is not None:
        del active_sessions[session_key]
        return jsonify({'error': 'Session process has terminated'}), 500
    
    data = request.get_json()
    prompt = data.get('prompt', '')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400
    
    try:
        # Call llama.cpp server with correct API format
        # Reference: https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md
        llama_response = httpx.post(
            f"http://localhost:{info['port']}/completion",
            json={
                'prompt': prompt,
                'n_predict': data.get('max_tokens', 256),
                'temperature': data.get('temperature', 0.7),
                'stop': data.get('stop', []),
                'stream': False
            },
            timeout=180  # 3 minutes timeout for long generations
        )
        
        if llama_response.status_code != 200:
            logger.error(f"llama.cpp error: {llama_response.text}")
            return jsonify({'error': 'LLM generation failed'}), 500
        
        result = llama_response.json()
        
        return jsonify({
            'content': result.get('content', ''),
            'model': info['model'],
            'tokens_generated': result.get('tokens_predicted', 0),
            'tokens_evaluated': result.get('tokens_evaluated', 0),
            'stopped': result.get('stopped_eos', False) or result.get('stopped_word', False)
        })
        
    except httpx.TimeoutException:
        logger.error(f"Timeout calling llama.cpp for session {session_key}")
        return jsonify({'error': 'Generation timed out'}), 504
    except Exception as e:
        logger.error(f"Error calling llama.cpp: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/completion/<session_id>/stream', methods=['POST'])
def completion_stream(session_id):
    """
    Streaming proxy per le richieste di completamento.
    Usa Server-Sent Events per lo streaming.
    """
    from flask import Response
    
    session_key = str(session_id)
    
    if session_key not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    info = active_sessions[session_key]
    
    if info['process'].poll() is not None:
        return jsonify({'error': 'Session process has terminated'}), 500
    
    data = request.get_json()
    prompt = data.get('prompt', '')
    
    def generate():
        try:
            with httpx.stream(
                'POST',
                f"http://localhost:{info['port']}/completion",
                json={
                    'prompt': prompt,
                    'n_predict': data.get('max_tokens', 256),
                    'temperature': data.get('temperature', 0.7),
                    'stop': data.get('stop', []),
                    'stream': True
                },
                timeout=180
            ) as response:
                for line in response.iter_lines():
                    if line.startswith('data: '):
                        yield f"data: {line[6:]}\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/status', methods=['GET'])
def status():
    """
    Restituisce lo stato del nodo.

    Returns:
    - status: 'online' or 'offline'
    - models: List di modelli disponibili
    - load: Numero di sessioni attive
    """
    # Pulizia sessioni terminate
    cleanup_stale_sessions()
    
    return jsonify({
        'status': 'online',
        'models': list(config.models.keys()),
        'load': len(active_sessions),
        'sessions': [
            {
                'id': sid,
                'port': info['port'],
                'model': info['model'],
                'uptime': int(time.time() - info['started_at'])
            }
            for sid, info in active_sessions.items()
            if info['process'].poll() is None
        ]
    })


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    import atexit
    
    # Avvia heartbeat
    start_heartbeat()
    
    # Registra cleanup all'uscita
    def cleanup():
        logger.info("Shutting down...")
        stop_heartbeat()
        # Termina tutte le sessioni attive
        for session_id, info in list(active_sessions.items()):
            try:
                info['process'].terminate()
                info['process'].wait(timeout=2)
            except:
                info['process'].kill()
        logger.info("Cleanup complete")
    
    atexit.register(cleanup)
    
    logger.info(f"Starting node server on {config.address}:{config.port}")
    app.run(
        host=config.address,
        port=config.port,
        threaded=True
    )
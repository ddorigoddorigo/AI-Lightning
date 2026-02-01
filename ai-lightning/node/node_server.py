"""
Server del nodo host.

Espone un'API per il server principale.
"""
from flask import Flask, request, jsonify
import subprocess
import threading
from .node_config import Config

app = Flask(__name__)
config = Config()
active_sessions = {}  # session_id -> (process, port)
port_lock = threading.Lock()

def find_available_port():
    """Trova una porta disponibile nel range configurato."""
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
        proc = subprocess.Popen(
            [
                llama_bin,
                '-m', config.models[model]['path'],
                '--n_ctx', str(context),
                '--server',
                '--port', str(port)
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        active_sessions[session_id] = (proc, port)
        return jsonify({
            'status': 'started',
            'port': port,
            'process_id': proc.pid
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_session', methods=['POST'])
def stop_session():
    """
    Termina una sessione.

    Request body:
    - session_id: ID della sessione
    """
    data = request.get_json()
    session_id = data['session_id']

    if session_id in active_sessions:
        proc, port = active_sessions[session_id]
        proc.terminate()
        del active_sessions[session_id]

    return jsonify({'status': 'stopped'})

@app.route('/api/status', methods=['GET'])
def status():
    """
    Restituisce lo stato del nodo.

    Returns:
    - status: 'online' or 'offline'
    - models: List di modelli disponibili
    - load: Numero di sessioni attive
    """
    return jsonify({
        'status': 'online',
        'models': list(config.models.keys()),
        'load': len(active_sessions)
    })

if __name__ == '__main__':
    app.run(
        host=config.address,
        port=config.port,
        threaded=True
    )
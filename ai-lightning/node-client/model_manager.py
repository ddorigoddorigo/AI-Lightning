"""
Model Manager for AI Lightning Node Client.

Gestisce i modelli disponibili sul nodo e la sincronizzazione con il server.
"""
import os
import json
import hashlib
import logging
import requests
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger('ModelManager')


@dataclass
class ModelInfo:
    """Informazioni su un modello GGUF."""
    id: str  # Hash del file
    name: str  # Nome leggibile
    filename: str  # Nome file
    filepath: str  # Path completo
    size_bytes: int
    size_gb: float
    parameters: str  # Es: "7B", "13B", "70B"
    quantization: str  # Es: "Q4_K_M", "Q8_0"
    context_length: int  # Default 4096
    architecture: str  # Es: "llama", "mistral", "phi"
    created_at: str
    
    # Requisiti
    min_vram_mb: int
    recommended_vram_mb: int
    
    # Stato
    enabled: bool = True


# Mappatura parametri -> VRAM necessaria (approssimativa per Q4)
VRAM_REQUIREMENTS = {
    '1B': {'min': 1000, 'rec': 2000},
    '3B': {'min': 2500, 'rec': 4000},
    '7B': {'min': 4000, 'rec': 6000},
    '8B': {'min': 5000, 'rec': 8000},
    '13B': {'min': 8000, 'rec': 12000},
    '14B': {'min': 9000, 'rec': 14000},
    '32B': {'min': 20000, 'rec': 32000},
    '34B': {'min': 22000, 'rec': 36000},
    '70B': {'min': 40000, 'rec': 48000},
    '72B': {'min': 42000, 'rec': 50000},
}


def parse_model_name(filename: str) -> Dict:
    """
    Estrae informazioni dal nome del file GGUF.
    
    Formati comuni:
    - llama-2-7b-chat.Q4_K_M.gguf
    - mistral-7b-instruct-v0.2.Q4_K_S.gguf
    - phi-2.Q8_0.gguf
    - deepseek-coder-6.7b-instruct.Q4_K_M.gguf
    """
    info = {
        'name': filename.replace('.gguf', ''),
        'parameters': 'Unknown',
        'quantization': 'Unknown',
        'architecture': 'unknown'
    }
    
    name_lower = filename.lower()
    
    # Rileva architettura
    architectures = [
        'llama', 'mistral', 'mixtral', 'phi', 'qwen', 'gemma', 
        'deepseek', 'codellama', 'starcoder', 'falcon', 'yi',
        'vicuna', 'wizard', 'orca', 'neural', 'openchat'
    ]
    for arch in architectures:
        if arch in name_lower:
            info['architecture'] = arch
            break
    
    # Rileva parametri
    import re
    # Cerca pattern come 7b, 7B, 13b, 70b, 6.7b, etc.
    param_match = re.search(r'(\d+\.?\d*)\s*[bB]', filename)
    if param_match:
        param_num = float(param_match.group(1))
        if param_num < 1:
            info['parameters'] = f"{int(param_num * 1000)}M"
        else:
            info['parameters'] = f"{int(param_num)}B" if param_num == int(param_num) else f"{param_num}B"
    
    # Rileva quantizzazione
    quant_patterns = [
        r'[._-](Q\d+_K_[SMLX]+)', r'[._-](Q\d+_K)', r'[._-](Q\d+_\d+)',
        r'[._-](Q\d+)', r'[._-](F16)', r'[._-](F32)', r'[._-](BF16)',
        r'[._-](IQ\d+_[SMLX]+)', r'[._-](IQ\d+)'
    ]
    for pattern in quant_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            info['quantization'] = match.group(1).upper()
            break
    
    # Crea nome leggibile
    name_parts = []
    if info['architecture'] != 'unknown':
        name_parts.append(info['architecture'].capitalize())
    if info['parameters'] != 'Unknown':
        name_parts.append(info['parameters'])
    if info['quantization'] != 'Unknown':
        name_parts.append(info['quantization'])
    
    if name_parts:
        info['name'] = ' '.join(name_parts)
    
    return info


def calculate_file_hash(filepath: str, chunk_size: int = 8192) -> str:
    """Calcola hash MD5 del file (primi 10MB per velocità)."""
    hasher = hashlib.md5()
    max_bytes = 10 * 1024 * 1024  # 10MB
    bytes_read = 0
    
    with open(filepath, 'rb') as f:
        while bytes_read < max_bytes:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
    
    # Aggiungi size per unicità
    size = os.path.getsize(filepath)
    hasher.update(str(size).encode())
    
    return hasher.hexdigest()[:16]


def get_vram_requirements(parameters: str) -> Dict[str, int]:
    """Ottieni requisiti VRAM in base ai parametri."""
    # Normalizza
    param_upper = parameters.upper().replace(' ', '')
    
    # Cerca match esatto
    if param_upper in VRAM_REQUIREMENTS:
        return VRAM_REQUIREMENTS[param_upper]
    
    # Cerca match parziale
    for key, values in VRAM_REQUIREMENTS.items():
        if key in param_upper or param_upper in key:
            return values
    
    # Stima basata sul numero
    import re
    match = re.search(r'(\d+\.?\d*)', param_upper)
    if match:
        num = float(match.group(1))
        # ~600MB per 1B parametri in Q4
        estimated = int(num * 600)
        return {'min': estimated, 'rec': int(estimated * 1.5)}
    
    return {'min': 4000, 'rec': 8000}  # Default


class ModelManager:
    """Gestisce i modelli disponibili sul nodo."""
    
    def __init__(self, models_dir: str = None):
        self.models_dir = models_dir or os.path.join(os.getcwd(), 'models')
        self.models: Dict[str, ModelInfo] = {}
        self.config_file = os.path.join(self.models_dir, 'models_config.json')
        
        # Crea directory se non esiste
        Path(self.models_dir).mkdir(parents=True, exist_ok=True)
        
        # Carica configurazione
        self.load_config()
    
    def load_config(self):
        """Carica configurazione modelli salvata."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    for model_id, model_data in data.get('models', {}).items():
                        self.models[model_id] = ModelInfo(**model_data)
                logger.info(f"Loaded {len(self.models)} models from config")
            except Exception as e:
                logger.error(f"Error loading config: {e}")
    
    def save_config(self):
        """Salva configurazione modelli."""
        try:
            data = {
                'models': {k: asdict(v) for k, v in self.models.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved config with {len(self.models)} models")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def scan_models(self) -> List[ModelInfo]:
        """Scansiona directory per file GGUF."""
        found_models = []
        
        if not os.path.exists(self.models_dir):
            logger.warning(f"Models directory does not exist: {self.models_dir}")
            return found_models
        
        for filename in os.listdir(self.models_dir):
            if filename.lower().endswith('.gguf'):
                filepath = os.path.join(self.models_dir, filename)
                
                try:
                    # Calcola hash
                    model_id = calculate_file_hash(filepath)
                    
                    # Se già presente, aggiorna solo il path
                    if model_id in self.models:
                        self.models[model_id].filepath = filepath
                        found_models.append(self.models[model_id])
                        continue
                    
                    # Parse nome file
                    parsed = parse_model_name(filename)
                    
                    # Ottieni requisiti VRAM
                    vram_req = get_vram_requirements(parsed['parameters'])
                    
                    # Crea ModelInfo
                    size_bytes = os.path.getsize(filepath)
                    model = ModelInfo(
                        id=model_id,
                        name=parsed['name'],
                        filename=filename,
                        filepath=filepath,
                        size_bytes=size_bytes,
                        size_gb=round(size_bytes / (1024**3), 2),
                        parameters=parsed['parameters'],
                        quantization=parsed['quantization'],
                        context_length=4096,  # Default
                        architecture=parsed['architecture'],
                        created_at=datetime.fromtimestamp(
                            os.path.getctime(filepath)
                        ).isoformat(),
                        min_vram_mb=vram_req['min'],
                        recommended_vram_mb=vram_req['rec'],
                        enabled=True
                    )
                    
                    self.models[model_id] = model
                    found_models.append(model)
                    logger.info(f"Found model: {model.name} ({model.size_gb} GB)")
                    
                except Exception as e:
                    logger.error(f"Error scanning {filename}: {e}")
        
        # Rimuovi modelli non più presenti
        to_remove = []
        for model_id, model in self.models.items():
            if not os.path.exists(model.filepath):
                to_remove.append(model_id)
        
        for model_id in to_remove:
            logger.info(f"Removing missing model: {self.models[model_id].name}")
            del self.models[model_id]
        
        # Salva configurazione
        self.save_config()
        
        return list(self.models.values())
    
    def get_enabled_models(self) -> List[ModelInfo]:
        """Restituisce solo i modelli abilitati."""
        return [m for m in self.models.values() if m.enabled]
    
    def set_model_enabled(self, model_id: str, enabled: bool):
        """Abilita/disabilita un modello."""
        if model_id in self.models:
            self.models[model_id].enabled = enabled
            self.save_config()
            return True
        return False
    
    def set_model_context_length(self, model_id: str, context_length: int):
        """Imposta context length per un modello."""
        if model_id in self.models:
            self.models[model_id].context_length = context_length
            self.save_config()
            return True
        return False
    
    def get_models_for_server(self) -> List[Dict]:
        """
        Prepara lista modelli da inviare al server.
        Include solo i dati necessari.
        """
        models = []
        for model in self.get_enabled_models():
            models.append({
                'id': model.id,
                'name': model.name,
                'parameters': model.parameters,
                'quantization': model.quantization,
                'context_length': model.context_length,
                'architecture': model.architecture,
                'size_gb': model.size_gb,
                'min_vram_mb': model.min_vram_mb,
                'recommended_vram_mb': model.recommended_vram_mb
            })
        return models
    
    def get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        """Ottieni modello per ID."""
        return self.models.get(model_id)
    
    def get_model_by_name(self, name: str) -> Optional[ModelInfo]:
        """Trova modello per nome (parziale)."""
        name_lower = name.lower()
        for model in self.models.values():
            if name_lower in model.name.lower() or name_lower in model.filename.lower():
                return model
        return None


class ModelSyncClient:
    """Client per sincronizzazione modelli con server centrale."""
    
    def __init__(self, server_url: str, node_token: str = None):
        self.server_url = server_url.rstrip('/')
        self.node_token = node_token
    
    def sync_models(self, node_id: str, hardware_info: Dict, models: List[Dict]) -> Dict:
        """
        Sincronizza modelli con il server.
        
        Invia:
        - Info hardware del nodo
        - Lista modelli disponibili
        
        Riceve:
        - Conferma registrazione
        - Eventuali modelli richiesti dalla rete
        """
        try:
            payload = {
                'node_id': node_id,
                'hardware': hardware_info,
                'models': models,
                'timestamp': datetime.now().isoformat()
            }
            
            headers = {'Content-Type': 'application/json'}
            if self.node_token:
                headers['Authorization'] = f'Bearer {self.node_token}'
            
            response = requests.post(
                f'{self.server_url}/api/nodes/sync',
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Sync failed: {response.status_code} - {response.text}")
                return {'error': response.text}
                
        except Exception as e:
            logger.error(f"Sync error: {e}")
            return {'error': str(e)}
    
    def get_network_models(self) -> List[Dict]:
        """Ottieni lista di tutti i modelli disponibili nella rete."""
        try:
            response = requests.get(
                f'{self.server_url}/api/models/available',
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json().get('models', [])
            return []
            
        except Exception as e:
            logger.error(f"Error getting network models: {e}")
            return []


if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.DEBUG)
    
    manager = ModelManager('./test_models')
    models = manager.scan_models()
    
    print(f"\nFound {len(models)} models:")
    for model in models:
        print(f"  - {model.name}")
        print(f"    File: {model.filename}")
        print(f"    Size: {model.size_gb} GB")
        print(f"    Params: {model.parameters}, Quant: {model.quantization}")
        print(f"    VRAM: {model.min_vram_mb}MB min, {model.recommended_vram_mb}MB rec")
        print()

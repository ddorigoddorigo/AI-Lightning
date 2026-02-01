"""
Script per setup di un nodo.

Crea file di configurazione e verifica dipendenze.
"""
from pathlib import Path
import subprocess

def setup():
    # Crea file di configurazione
    config_path = Path('config.ini')
    if not config_path.exists():
        config_path.write_text("""[Server]
URL = http://localhost:5000

[Node]
id = none
address = 0.0.0.0
port = 9000

[LLM]
bin = ../llama.cpp/main
port_start = 11000
port_end = 12000

[Model:tiny]
path = ../llama.cpp/models/3B/ggml-model-q4_0.bin
context = 2048

[Model:base]
path = ../llama.cpp/models/7B/ggml-model-q4_0.bin
context = 4096

[Model:large]
path = ../llama.cpp/models/13B/ggml-model-q4_0.bin
context = 8192
""")
        print('Created config.ini')

    # Verifica llama.cpp
    llama_bin = Path('../llama.cpp/main')
    if not llama_bin.exists():
        print('Warning: llama.cpp not found at ../llama.cpp/main')
        print('Clone llama.cpp and build it first')

    # Verifica modelli
    models = {
        'tiny': Path('../llama.cpp/models/3B/ggml-model-q4_0.bin'),
        'base': Path('../llama.cpp/models/7B/ggml-model-q4_0.bin'),
        'large': Path('../llama.cpp/models/13B/ggml-model-q4_0.bin')
    }
    for name, path in models.items():
        if not path.exists():
            print(f'Warning: model {name} not found at {path}')

if __name__ == '__main__':
    setup()
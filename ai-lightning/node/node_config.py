"""
Configurazione del nodo host.

Caricata da file o variabili d'ambiente.
"""
import os
from configparser import ConfigParser

class Config:
    def __init__(self):
        self.parser = ConfigParser()
        self.parser.read('config.ini')

    @property
    def node_id(self):
        """ID del nodo."""
        return self.parser.get('Node', 'id', fallback=None)

    @property
    def server_url(self):
        """URL del server principale."""
        return self.parser.get('Server', 'URL', fallback='http://localhost:5000')

    @property
    def address(self):
        """Indirizzo del nodo."""
        return self.parser.get('Node', 'address', fallback='0.0.0.0')

    @property
    def port(self):
        """Porta del node server."""
        return self.parser.getint('Node', 'port', fallback=9000)

    @property
    def llama_bin(self):
        """Path a llama.cpp."""
        return self.parser.get('LLM', 'bin', fallback='../llama.cpp/main')

    @property
    def models(self):
        """Modelli disponibili."""
        models = {}
        for section in self.parser.sections():
            if section.startswith('Model:'):
                name = section[6:]
                models[name] = {
                    'path': self.parser.get(section, 'path'),
                    'context': self.parser.getint(section, 'context')
                }
        return models

    @property
    def port_range(self):
        """Range di porte per llama.cpp."""
        start = self.parser.getint('LLM', 'port_start', fallback=11000)
        end = self.parser.getint('LLM', 'port_end', fallback=12000)
        return (start, end)
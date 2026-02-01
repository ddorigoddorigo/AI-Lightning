# AI Lightning

## Descrizione
Sistema decentralizzato per ofere potenza di calcolo LLM a pagamento via Lightning Network.

## Architettura
- **Server Principale**: Coordina utenti, sessioni e nodi
- **Nodi Host**: Forniscono potenza di calcolo con llama.cpp
- **Client**: Interfaccia utente (web o desktop)

## Setup

### Server
1. Copia `server/.env.example` in `.env` e modifica la configurazione
2. Installa dipendenze: `pip install -r server/requirements.txt`
3. Setup database: `python scripts/setup_server.py`
4. Avvia server: `gunicorn --workers 4 --bind 0.0.0.0:5000 server/app:app`

### Nodo Host
1. Copia `node/config.ini.example` in `config.ini` e modifica
2. Installa dipendenze: `pip install -r node/requirements.txt`
3. Setup nodo: `python scripts/setup_node.py`
4. Avvia nodo: `python node/node_server.py`

### Client Web
Basta aprire un browser alla URL del server.

### Client Desktop
1. Copia `client/config.ini.example` in `config.ini`
2. Installa dipendenze: `pip install -r client/requirements.txt`
3. Avvia client: `python client/app.py`

## Deployment
Vedi `docs/deployment.md` per istruzioni dettagliate.

## Licenza
MIT
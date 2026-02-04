# LightPhon ⚡

## Decentralized LLMs with Lightning payments

Decentralized system for offering LLM computing power paid via Lightning Network.

## Architecture
- **Main Server**: Coordinates users, sessions and nodes
- **Host Nodes**: Provide computing power with llama.cpp
- **Client**: User interface (web or desktop)

## Setup

### Server
1. Copy `server/.env.example` to `.env` and edit the configuration
2. Install dependencies: `pip install -r server/requirements.txt`
3. Setup database: `python scripts/setup_server.py`
4. Start server: `gunicorn --workers 4 --bind 0.0.0.0:5000 server/app:app`

### Host Node
1. Copy `node/config.ini.example` to `config.ini` and edit
2. Install dependencies: `pip install -r node/requirements.txt`
3. Setup node: `python scripts/setup_node.py`
4. Start node: `python node/node_server.py`

### Web Client
Just open a browser to the server URL.

### Desktop Client
1. Copy `client/config.ini.example` to `config.ini`
2. Install dependencies: `pip install -r client/requirements.txt`
3. Start client: `python client/app.py`

## Deployment
See `docs/deployment.md` for detailed instructions.

## License
MIT
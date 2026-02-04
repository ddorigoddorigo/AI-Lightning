# AI Lightning Architecture

## Components

### Main Server
- **Responsibilities**:
  - User authentication
  - Session management
  - Request routing to nodes
  - Lightning payments
- **Technologies**:
  - Python (Flask)
  - PostgreSQL
  - Redis
  - lnd (Lightning Node)

### Host Nodes
- **Responsibilities**:
  - LLM model execution
  - Communication with main server
- **Technologies**:
  - Python (Flask)
  - llama.cpp (C++)

### Client
- **Types**:
  - Web (JavaScript)
  - Desktop (Python + Tkinter)
- **Communication**:
  - WebSocket to main server

## Main Flows

### Node Registration
1. Node starts `node_server.py`
2. Node registers on main server
3. Server saves node info in database and Redis
4. Node sends periodic heartbeat

### Session Creation
1. User requests a session
2. Server creates Lightning invoice
3. User pays the invoice
4. Server assigns session to an available node
5. Node starts llama.cpp instance
6. User communicates directly with the node

## Communication

### Client ↔ Server
- Protocol: WebSocket
- Port: 443 (HTTPS)

### Server ↔ Nodes
- Protocol: HTTP
- Port: 9000

### Nodes ↔ llama.cpp
- Protocol: TCP
- Port: 11000-12000
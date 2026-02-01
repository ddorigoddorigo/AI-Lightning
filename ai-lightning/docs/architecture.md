# Architettura AI Lightning

## Componenti

### Server Principale
- **Responsabilità**:
  - Autenticazione utenti
  - Gestione sessioni
  - Routing richieste ai nodi
  - Pagamenti Lightning
- **Tecnologie**:
  - Python (Flask)
  - PostgreSQL
  - Redis
  - lnd (Lightning Node)

### Nodi Host
- **Responsabilità**:
  - Esecuzione modelli LLM
  - Comunicazione con server principale
- **Tecnologie**:
  - Python (Flask)
  - llama.cpp (C++)

### Client
- **Tipologie**:
  - Web (JavaScript)
  - Desktop (Python + Tkinter)
- **Comunicazione**:
  - WebSocket al server principale

## Flussi Principali

### Registrazione Nodo
1. Nodo avvia `node_server.py`
2. Nodo si registra sul server principale
3. Server salva info del nodo in database e Redis
4. Nodo invia heartbeat periodico

### Creazione Sessione
1. Utente richiede una sessione
2. Server crea fattura Lightning
3. Utente paga la fattura
4. Server assegnia la sessione a un nodo disponibile
5. Nodo avvia istanza di llama.cpp
6. Utente comunica direttamente con il nodo

## Comunicazione

### Client ↔ Server
- Protocollo: WebSocket
- Port: 443 (HTTPS)

### Server ↔ Nodi
- Protocollo: HTTP
- Port: 9000

### Nodi ↔ llama.cpp
- Protocollo: TCP
- Port: 11000-12000
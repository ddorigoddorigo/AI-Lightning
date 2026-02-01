"""
Client Socket.IO per comunicare con il server principale.
"""
import socketio
import asyncio

class SocketClient:
    def __init__(self):
        self.sio = socketio.AsyncClient()
        self.callbacks = {}

        # Registra handlers di base
        self.sio.on('connect', self.on_connect)
        self.sio.on('disconnect', self.on_disconnect)

    async def connect(self, server_url, token):
        """Connetti al server."""
        self.sio.connect(
            server_url,
            headers={'Authorization': f'Bearer {token}'}
        )

    async def disconnect(self):
        """Disconnetti."""
        await self.sio.disconnect()

    def on(self, event, handler):
        """Registra un handler per un evento."""
        self.callbacks[event] = handler
        self.sio.on(event, handler)

    async def emit(self, event, data):
        """Invia un evento."""
        await self.sio.emit(event, data)

    # Default handlers
    def on_connect(self):
        print("Connected to server")

    def on_disconnect(self):
        print("Disconnected from server")
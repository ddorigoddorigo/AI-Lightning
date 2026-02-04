"""
Desktop client entry point.

Connects GUI and SocketClient.
"""
import asyncio
from gui import GUI
from socket_client import SocketClient

class App:
    def __init__(self):
        self.gui = GUI()
        self.socket_client = SocketClient()

        # Connect callbacks
        self.socket_client.on('connect', self.on_connected)
        self.socket_client.on('disconnect', self.on_disconnected)
        self.socket_client.on('session_started', self.on_session_started)
        self.socket_client.on('ai_response', self.on_ai_response)
        self.socket_client.on('error', self.on_error)

        # Start interface
        self.gui.run()

    async def connect(self, token):
        """Connect to server."""
        await self.socket_client.connect(
            self.gui.config.get('Server', 'URL'),
            token
        )
        self.gui.token = token
        self.gui.show_chat()

    def on_connected(self):
        self.gui.add_message("System", "Connected to server")

    def on_disconnected(self):
        self.gui.add_message("System", "Disconnected from server")
        self.gui.show_login()

    def on_session_started(self, data):
        self.gui.add_message("System", f"Session started! Expires at {data['expires_at']}")

    def on_ai_response(self, data):
        self.gui.add_message("AI", data['response'])

    def on_error(self, data):
        self.gui.add_message("System", f"Error: {data['message']}")

if __name__ == '__main__':
    app = App()
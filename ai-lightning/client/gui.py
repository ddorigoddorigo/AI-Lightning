"""
User interface for the desktop client.

Uses Tkinter for a native interface.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from ttkthemes import ThemedStyle
import webbrowser
from configparser import ConfigParser

class GUI:
    def __init__(self):
        # Configuration
        self.config = ConfigParser()
        self.config.read('config.ini')
        self.token = None
        self.current_session = None

        # Create window
        self.root = tk.Tk()
        self.root.title("AI Lightning")
        self.root.geometry("800x600")
        if hasattr(self.root, 'wm_iconbitmap'):
            self.root.iconbitmap('assets/logo.ico')

        # Style
        self.style = ThemedStyle(self.root)
        self.style.theme_use(self.config.get('UI', 'Theme', fallback='dark'))

        # Font
        font = (self.config.get('UI', 'Font', fallback='Segoe UI'), 10)

        # Setup UI
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Login frame
        self.login_frame = ttk.Frame(self.main_frame)
        ttk.Label(self.login_frame, text="AI Lightning", font=('Segoe UI', 16)).pack(pady=20)
        ttk.Label(self.login_frame, text="Username").pack()
        self.username_entry = ttk.Entry(self.login_frame)
        self.username_entry.pack(fill=tk.X, padx=20, pady=5)
        ttk.Label(self.login_frame, text="Password").pack()
        self.password_entry = ttk.Entry(self.login_frame, show='*')
        self.password_entry.pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(self.login_frame, text="Login", command=self.login).pack(pady=10)
        ttk.Button(self.login_frame, text="Register", command=self.register).pack(pady=5)
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Chat frame
        self.chat_frame = ttk.Frame(self.main_frame)
        self.model_frame = ttk.Frame(self.chat_frame)
        ttk.Label(self.model_frame, text="Model:").pack(side=tk.LEFT, padx=(20, 10))
        self.model_var = tk.StringVar(value='base')
        for model in ['tiny', 'base', 'large']:
            ttk.Radiobutton(
                self.model_frame,
                text=model,
                variable=self.model_var,
                value=model
            ).pack(side=tk.LEFT)
        ttk.Label(self.model_frame, text="Duration (minutes):").pack(side=tk.RIGHT, padx=(10, 20))
        self.duration_var = tk.StringVar(value='5')
        ttk.Entry(self.model_frame, textvariable=self.duration_var, width=5).pack(side=tk.RIGHT)
        self.model_frame.pack(fill=tk.X, pady=10)

        ttk.Button(self.model_frame, text="Buy Session", command=self.create_session).pack(side=tk.RIGHT)

        self.invoice_frame = ttk.Frame(self.chat_frame)
        self.invoice_label = ttk.Label(self.invoice_frame, text="Pay a Lightning invoice to start")
        self.invoice_label.pack()
        self.invoice_text = tk.Text(self.invoice_frame, height=5, state='disabled')
        self.invoice_text.pack(fill=tk.X)
        ttk.Button(self.invoice_frame, text="I've paid", command=self.check_payment).pack(pady=10)
        self.invoice_frame.pack(fill=tk.X, padx=20, pady=10)

        self.chat_area = scrolledtext.ScrolledText(self.chat_frame, state='disabled', font=font)
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        self.input_frame = ttk.Frame(self.chat_frame)
        self.message_entry = ttk.Entry(self.input_frame, font=font)
        self.message_entry.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.message_entry.bind('<Return>', self.send_message)
        ttk.Button(self.input_frame, text="Send", command=self.send_message).pack(side=tk.RIGHT)
        ttk.Button(self.input_frame, text="End Session", command=self.end_session).pack(side=tk.RIGHT)
        self.input_frame.pack(fill=tk.X, padx=20, pady=10)

        self.chat_frame.pack_forget()  # Hidden initially

        # Menu
        self.menu = tk.Menu(self.root)
        self.root.config(menu=self.menu)
        settings_menu = tk.Menu(self.menu, tearoff=0)
        settings_menu.add_command(label="Settings", command=self.settings)
        settings_menu.add_command(label="About", command=self.about)
        self.menu.add_cascade(label="File", menu=settings_menu)

    def login(self):
        """Handle user login."""
        # Implementa login via API
        pass

    def register(self):
        """Handle user registration."""
        # Implementa registrazione via API
        pass

    def create_session(self):
        """Create a new session."""
        if not hasattr(self, 'socket_client') or not self.token:
            messagebox.showerror("Error", "Not logged in")
            return

        asyncio.create_task(self.do_create_session())

    async def do_create_session(self):
        try:
            response = await self.post('/api/new_session', {
                'model': self.model_var.get(),
                'minutes': int(self.duration_var.get())
            })
            data = response.json()
            self.invoice_text.config(state='normal')
            self.invoice_text.delete(1.0, tk.END)
            self.invoice_text.insert(tk.END, data['invoice'])
            self.invoice_text.config(state='disabled')
            self.current_session = data['session_id']
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def check_payment(self):
        """Verify payment and start session."""
        if not self.current_session:
            messagebox.showerror("Error", "No active session")
            return

        self.socket_client.emit('start_session', {
            'session_id': self.current_session
        })

    def send_message(self, event=None):
        """Send a message."""
        if not self.current_session:
            messagebox.showerror("Error", "No active session")
            return

        message = self.message_entry.get()
        if not message:
            return

        self.add_message("You", message)
        self.message_entry.delete(0, tk.END)
        asyncio.create_task(
            self.socket_client.emit('chat_message', {
                'session_id': self.current_session,
                'prompt': message
            })
        )

    def end_session(self):
        """End the session."""
        if not self.current_session:
            messagebox.showerror("Error", "No active session")
            return

        asyncio.create_task(
            self.socket_client.emit('end_session', {
                'session_id': self.current_session
            })
        )
        self.current_session = None
        self.invoice_text.config(state='normal')
        self.invoice_text.delete(1.0, tk.END)
        self.invoice_text.config(state='disabled')
        self.invoice_label.config(text="Pay a Lightning invoice to start")

    def add_message(self, sender, text):
        """Add a message to the chat."""
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"{sender}: {text}\n")
        self.chat_area.config(state='disabled')
        self.chat_area.yview(tk.END)

    def show_chat(self):
        """Show the chat interface."""
        self.login_frame.pack_forget()
        self.chat_frame.pack(fill=tk.BOTH, expand=True)
        self.add_message("System", "Ready! Buy a session to start chatting.")

    def show_login(self):
        """Show the login interface."""
        self.chat_frame.pack_forget()
        self.login_frame.pack(fill=tk.BOTH, expand=True)

    def settings(self):
        """Open settings panel."""
        # Implementa pannello impostazioni
        pass

    def about(self):
        """Show application information."""
        messagebox.showinfo("About", "AI Lightning Windows Client\nVersion 1.0")

    def post(self, endpoint, data):
        """Helper for HTTP calls."""
        import httpx
        headers = {'Authorization': f'Bearer {self.token}'}
        return httpx.post(f"{self.config.get('Server', 'API_URL')}/{endpoint}", json=data, headers=headers)

    def run(self):
        """Start the interface."""
        self.root.mainloop()
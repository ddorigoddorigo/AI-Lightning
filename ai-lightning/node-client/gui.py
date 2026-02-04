"""
AI Lightning Node Client - GUI

Graphical interface for the host node with hardware detection and model management.
"""
import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from pathlib import Path
from configparser import ConfigParser
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from node_client import NodeClient, detect_gpu, find_llama_binary
from hardware_detect import get_system_info, format_system_info
from model_manager import ModelManager, ModelInfo
from version import VERSION
from updater import AutoUpdater


class NodeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"AI Lightning Node - Host GPU v{VERSION}")
        self.root.geometry("800x650")
        self.root.resizable(True, True)
        
        # Icon (if available)
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass
        
        # Variables
        self.client = None
        self.config_path = 'node_config.ini'
        self.config = ConfigParser()
        self.system_info = None
        self.model_manager = None
        
        # Auto-updater
        self.updater = AutoUpdater(callback=self._on_update_available)
        self.update_pending = False
        
        # Style
        style = ttk.Style()
        style.configure('Connected.TLabel', foreground='green', font=('Arial', 12, 'bold'))
        style.configure('Disconnected.TLabel', foreground='red', font=('Arial', 12, 'bold'))
        style.configure('Header.TLabel', font=('Arial', 10, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 9))
        style.configure('Update.TButton', foreground='orange')
        
        self._create_ui()
        self._load_config()
        
        # Detect hardware at startup
        self.root.after(100, self._detect_hardware)
        
        # Start auto-updater
        self.root.after(5000, self._start_updater)
    
    def _create_ui(self):
        """Create the interface"""
        
        # Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # === Tab 0: Account ===
        self.account_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.account_frame, text="👤 Account")
        self._create_account_tab()
        
        # === Tab 1: Hardware ===
        self.hw_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.hw_frame, text="🖥️ Hardware")
        self._create_hardware_tab()
        
        # === Tab 2: Connection ===
        self.conn_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.conn_frame, text="🔌 Connection")
        self._create_connection_tab()
        
        # === Tab 3: Models ===
        self.models_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.models_frame, text="🧠 Models")
        self._create_models_tab()
        
        # === Tab 4: Sessions ===
        self.sessions_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.sessions_frame, text="📊 Sessions")
        self._create_sessions_tab()
        
        # === Tab 5: Log ===
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="📝 Log")
        self._create_log_tab()
        
        # === Tab 6: LLM Output ===
        self.llm_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.llm_frame, text="🤖 LLM Output")
        self._create_llm_tab()
        
        # === Tab 7: Statistics ===
        self.stats_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_frame, text="📈 Statistics")
        self._create_stats_tab()
        
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar(value="Starting...")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.status_label.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        # Update check button
        self.update_btn = ttk.Button(status_frame, text="🔄", width=3, command=self.check_update_manual)
        self.update_btn.pack(side=tk.RIGHT, padx=2)
        
        # Version label
        version_label = ttk.Label(status_frame, text=f"v{VERSION}", font=('Arial', 8))
        version_label.pack(side=tk.RIGHT, padx=5)
        
        self.conn_indicator = ttk.Label(status_frame, text="● Disconnected", style='Disconnected.TLabel')
        self.conn_indicator.pack(side=tk.RIGHT, padx=10)
        
        # Save config on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _create_account_tab(self):
        """Tab Account - Login and Registration"""
        
        # Account variables
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Frame principale
        main_frame = ttk.Frame(self.account_frame, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = ttk.Label(main_frame, text="👤 LightPhon Account", font=('Arial', 16, 'bold'))
        header.pack(pady=(0, 20))
        
        # === Login Frame (default visible) ===
        self.login_frame = ttk.LabelFrame(main_frame, text="🔐 Login", padding=15)
        self.login_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(self.login_frame, text="Email/Username:").grid(row=0, column=0, sticky='w', pady=5)
        self.login_username = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.login_username, width=40).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.login_frame, text="Password:").grid(row=1, column=0, sticky='w', pady=5)
        self.login_password = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.login_password, show='*', width=40).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        
        btn_frame = ttk.Frame(self.login_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=15)
        
        self.login_btn = ttk.Button(btn_frame, text="🔑 Login", command=self._do_login, width=15)
        self.login_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="📝 Register", command=self._show_register, width=15).pack(side=tk.LEFT, padx=5)
        
        self.login_status = tk.StringVar(value="")
        ttk.Label(self.login_frame, textvariable=self.login_status, foreground='red').grid(row=3, column=0, columnspan=2, pady=5)
        
        self.login_frame.columnconfigure(1, weight=1)
        
        # === Registration Frame (hidden by default) ===
        self.register_frame = ttk.LabelFrame(main_frame, text="📝 Registration", padding=15)
        # Don't pack, will be shown with _show_register
        
        ttk.Label(self.register_frame, text="Username:").grid(row=0, column=0, sticky='w', pady=5)
        self.reg_username = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_username, width=40).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Email:").grid(row=1, column=0, sticky='w', pady=5)
        self.reg_email = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_email, width=40).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Password:").grid(row=2, column=0, sticky='w', pady=5)
        self.reg_password = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_password, show='*', width=40).grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Confirm Password:").grid(row=3, column=0, sticky='w', pady=5)
        self.reg_confirm = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_confirm, show='*', width=40).grid(row=3, column=1, padx=10, pady=5, sticky='ew')
        
        reg_btn_frame = ttk.Frame(self.register_frame)
        reg_btn_frame.grid(row=4, column=0, columnspan=2, pady=15)
        
        ttk.Button(reg_btn_frame, text="✓ Register", command=self._do_register, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(reg_btn_frame, text="← Back to Login", command=self._show_login, width=15).pack(side=tk.LEFT, padx=5)
        
        self.register_status = tk.StringVar(value="")
        ttk.Label(self.register_frame, textvariable=self.register_status, foreground='red').grid(row=5, column=0, columnspan=2, pady=5)
        
        self.register_frame.columnconfigure(1, weight=1)
        
        # === Connected Account Frame (hidden by default) ===
        self.account_info_frame = ttk.LabelFrame(main_frame, text="✓ Connected Account", padding=15)
        # Don't pack, will be shown after login
        
        self.account_user_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="👤 User:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_user_var, font=('Arial', 11)).grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        self.account_email_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="📧 Email:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_email_var, font=('Arial', 10)).grid(row=1, column=1, sticky='w', padx=10, pady=5)
        
        self.account_balance_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="⚡ Balance:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_balance_var, font=('Arial', 11, 'bold'), foreground='orange').grid(row=2, column=1, sticky='w', padx=10, pady=5)
        
        self.account_earnings_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="💰 Node Earnings:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_earnings_var, font=('Arial', 11, 'bold'), foreground='green').grid(row=3, column=1, sticky='w', padx=10, pady=5)
        
        account_btn_frame = ttk.Frame(self.account_info_frame)
        account_btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        ttk.Button(account_btn_frame, text="🔄 Refresh", command=self._refresh_account, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(account_btn_frame, text="🚪 Logout", command=self._do_logout, width=12).pack(side=tk.LEFT, padx=5)
        
        self.account_info_frame.columnconfigure(1, weight=1)
        
        # Note
        note_frame = ttk.Frame(main_frame)
        note_frame.pack(fill=tk.X, pady=20)
        
        note_text = (
            "ℹ️ Log in with the same account you use on lightphon.com\n"
            "   Your node earnings will be credited to your balance.\n"
            "   You can then withdraw satoshis via Lightning Network."
        )
        ttk.Label(note_frame, text=note_text, font=('Arial', 9), foreground='gray', justify='left').pack(anchor='w')
        
        # Load saved credentials
        self._load_account_config()
    
    def _show_register(self):
        """Show registration form"""
        self.login_frame.pack_forget()
        self.register_frame.pack(fill=tk.X, pady=10)
    
    def _show_login(self):
        """Show login form"""
        self.register_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
    
    def _load_account_config(self):
        """Load saved credentials"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            saved_username = self.config.get('Account', 'username', fallback='')
            saved_token = self.config.get('Account', 'token', fallback='')
            
            if saved_username:
                self.login_username.set(saved_username)
            
            # If there's a saved token, try auto-login
            if saved_token:
                self.auth_token = saved_token
                self.root.after(500, self._try_auto_login)
    
    def _try_auto_login(self):
        """Try automatic login with saved token"""
        if not self.auth_token:
            return
        
        self.login_status.set("Auto-login in progress...")
        
        def do_auto():
            try:
                server_url = "http://51.178.142.183:5000"
                response = requests.get(
                    f"{server_url}/api/me",
                    headers={'Authorization': f'Bearer {self.auth_token}'},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.root.after(0, lambda: self._on_login_success(data, auto=True))
                else:
                    # Token expired/invalid
                    self.auth_token = None
                    self.root.after(0, lambda: self.login_status.set("Session expired, please login"))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self.login_status.set(f"Error: {msg}"))
        
        threading.Thread(target=do_auto, daemon=True).start()
    
    def _do_login(self):
        """Execute login"""
        username = self.login_username.get().strip()
        password = self.login_password.get()
        
        if not username or not password:
            self.login_status.set("Enter username and password")
            return
        
        self.login_status.set("Logging in...")
        self.login_btn.config(state='disabled')
        
        def do_login():
            try:
                server_url = "http://51.178.142.183:5000"
                response = requests.post(
                    f"{server_url}/api/login",
                    json={'username': username, 'password': password},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.auth_token = data.get('token')
                    self.root.after(0, lambda: self._on_login_success(data))
                else:
                    error = response.json().get('error', 'Login failed')
                    self.root.after(0, lambda: self.login_status.set(f"❌ {error}"))
                    self.root.after(0, lambda: self.login_btn.config(state='normal'))
            except Exception as e:
                self.root.after(0, lambda: self.login_status.set(f"❌ Error: {e}"))
                self.root.after(0, lambda: self.login_btn.config(state='normal'))
        
        threading.Thread(target=do_login, daemon=True).start()
    
    def _on_login_success(self, data, auto=False):
        """Login success callback"""
        self.logged_in = True
        self.user_info = data
        
        # Save token and username
        if 'Account' not in self.config:
            self.config['Account'] = {}
        self.config['Account']['username'] = self.login_username.get()
        self.config['Account']['token'] = self.auth_token or ''
        self._save_config()
        
        # Update UI
        self.account_user_var.set(data.get('username', ''))
        self.account_email_var.set(data.get('email', ''))
        balance = data.get('balance', 0)
        self.account_balance_var.set(f"{balance:,} sats".replace(',', '.'))
        
        # Hide login, show account info
        self.login_frame.pack_forget()
        self.register_frame.pack_forget()
        self.account_info_frame.pack(fill=tk.X, pady=10)
        
        self.login_btn.config(state='normal')
        self.login_status.set("")
        
        self.log(f"Logged in: {data.get('username')}")
        self.update_status(f"Connected as: {data.get('username')}")
        
        # Load node earnings
        self._load_node_earnings()
    
    def _do_register(self):
        """Execute registration"""
        username = self.reg_username.get().strip()
        email = self.reg_email.get().strip()
        password = self.reg_password.get()
        confirm = self.reg_confirm.get()
        
        if not username or not email or not password:
            self.register_status.set("Fill in all fields")
            return
        
        if password != confirm:
            self.register_status.set("Passwords do not match")
            return
        
        if len(password) < 8:
            self.register_status.set("Password must be at least 8 characters")
            return
        
        self.register_status.set("Registering...")
        
        def do_register():
            try:
                server_url = "http://51.178.142.183:5000"
                response = requests.post(
                    f"{server_url}/api/register",
                    json={'username': username, 'email': email, 'password': password},
                    timeout=10
                )
                
                if response.status_code == 201:
                    self.root.after(0, lambda: self.register_status.set(""))
                    self.root.after(0, lambda: messagebox.showinfo("Registration", "✓ Registration completed!\nYou can now login."))
                    self.root.after(0, self._show_login)
                    self.root.after(0, lambda: self.login_username.set(username))
                else:
                    error = response.json().get('error', 'Registration failed')
                    self.root.after(0, lambda: self.register_status.set(f"❌ {error}"))
            except Exception as e:
                self.root.after(0, lambda: self.register_status.set(f"❌ Error: {e}"))
        
        threading.Thread(target=do_register, daemon=True).start()
    
    def _do_logout(self):
        """Execute logout"""
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Remove saved token
        if 'Account' in self.config:
            self.config['Account']['token'] = ''
            self._save_config()
        
        # Show login
        self.account_info_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
        self.login_password.set('')
        
        self.log("Logged out")
        self.update_status("Disconnected from account")
    
    def _refresh_account(self):
        """Refresh account info"""
        if not self.auth_token:
            return
        
        def do_refresh():
            try:
                server_url = "http://51.178.142.183:5000"
                response = requests.get(
                    f"{server_url}/api/me",
                    headers={'Authorization': f'Bearer {self.auth_token}'},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self.user_info = data
                    self.root.after(0, lambda: self.account_user_var.set(data.get('username', '')))
                    self.root.after(0, lambda: self.account_email_var.set(data.get('email', '')))
                    balance = data.get('balance', 0)
                    self.root.after(0, lambda: self.account_balance_var.set(f"{balance:,} sats".replace(',', '.')))
                    self.root.after(0, lambda: self.update_status("Account updated"))
                    self.root.after(0, self._load_node_earnings)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error updating account: {e}"))
        
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def _load_node_earnings(self):
        """Load node earnings from account"""
        # Earnings are already in balance, but we might want to show separately
        # For now show that balance includes node earnings
        self.account_earnings_var.set("Included in balance ⬆️")
    
    def _create_hardware_tab(self):
        """Hardware information tab"""
        
        # System info frame
        info_frame = ttk.LabelFrame(self.hw_frame, text="System Information", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Text area for hardware info
        self.hw_text = scrolledtext.ScrolledText(info_frame, height=15, font=('Consolas', 10))
        self.hw_text.pack(fill=tk.BOTH, expand=True)
        self.hw_text.insert(tk.END, "Detecting hardware...")
        self.hw_text.config(state='disabled')
        
        # Buttons
        btn_frame = ttk.Frame(self.hw_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="🔄 Detect Hardware", command=self._detect_hardware).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Copy Info", command=self._copy_hw_info).pack(side=tk.LEFT, padx=5)
        
        # Quick summary
        summary_frame = ttk.LabelFrame(self.hw_frame, text="Quick Summary", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Grid info
        self.hw_summary = {}
        labels = [
            ('cpu', 'CPU:', 0, 0),
            ('cores', 'Cores:', 0, 2),
            ('ram', 'RAM:', 1, 0),
            ('gpu', 'GPU:', 2, 0),
            ('vram', 'VRAM:', 2, 2),
            ('max_model', 'Max Model:', 3, 0),
        ]
        
        for key, text, row, col in labels:
            ttk.Label(summary_frame, text=text, style='Header.TLabel').grid(row=row, column=col, sticky='w', padx=5, pady=2)
            self.hw_summary[key] = tk.StringVar(value="-")
            ttk.Label(summary_frame, textvariable=self.hw_summary[key], style='Info.TLabel').grid(row=row, column=col+1, sticky='w', padx=5, pady=2)
        
        # Configura colonne
        for i in range(4):
            summary_frame.columnconfigure(i, weight=1)
    
    def _create_connection_tab(self):
        """Connection tab"""
        
        # Server info (fixed)
        server_frame = ttk.LabelFrame(self.conn_frame, text="LightPhon Server", padding=10)
        server_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Fixed server URL - not editable
        # Use direct IP until DNS is properly configured
        self.server_url = tk.StringVar(value="http://51.178.142.183:5000")
        ttk.Label(server_frame, text="Server:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(server_frame, text="lightphon.com (51.178.142.183)", font=('Arial', 10, 'bold'), foreground='green').grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        ttk.Label(server_frame, text="Node Name:").grid(row=1, column=0, sticky='w', pady=5)
        self.node_name = tk.StringVar(value="")
        ttk.Entry(server_frame, textvariable=self.node_name, width=50).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(optional, to identify the node)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        ttk.Label(server_frame, text="Token:").grid(row=2, column=0, sticky='w', pady=5)
        self.token = tk.StringVar()
        ttk.Entry(server_frame, textvariable=self.token, width=50, show='*').grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(optional, for authentication)", font=('Arial', 8)).grid(row=2, column=2, sticky='w')
        
        server_frame.columnconfigure(1, weight=1)
        
        # Pricing settings
        pricing_frame = ttk.LabelFrame(self.conn_frame, text="💰 Price per Minute", padding=10)
        pricing_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(pricing_frame, text="Satoshi/minute:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        self.price_per_minute = tk.StringVar(value="100")
        price_spin = ttk.Spinbox(pricing_frame, textvariable=self.price_per_minute, from_=1, to=100000, width=15, font=('Arial', 12))
        price_spin.grid(row=0, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(pricing_frame, text="sats", font=('Arial', 10, 'bold')).grid(row=0, column=2, sticky='w')
        
        # Price suggestions
        price_hints = ttk.Frame(pricing_frame)
        price_hints.grid(row=1, column=0, columnspan=4, sticky='w', pady=10)
        
        ttk.Label(price_hints, text="Suggestions:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        ttk.Button(price_hints, text="50 sats (budget)", command=lambda: self.price_per_minute.set("50"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="100 sats (standard)", command=lambda: self.price_per_minute.set("100"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="500 sats (premium)", command=lambda: self.price_per_minute.set("500"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="1000 sats (high-end)", command=lambda: self.price_per_minute.set("1000"), width=15).pack(side=tk.LEFT, padx=3)
        
        ttk.Label(pricing_frame, text="⚡ Users will pay this amount for each minute of using your node", 
                  font=('Arial', 9), foreground='gray').grid(row=2, column=0, columnspan=4, sticky='w', pady=5)
        
        pricing_frame.columnconfigure(1, weight=1)
        
        # Connection buttons
        btn_frame = ttk.Frame(self.conn_frame)
        btn_frame.pack(pady=20)
        
        self.connect_btn = ttk.Button(btn_frame, text="🔌 Connect", command=self.connect, width=15)
        self.connect_btn.pack(side=tk.LEFT, padx=10)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="❌ Disconnect", command=self.disconnect, state='disabled', width=15)
        self.disconnect_btn.pack(side=tk.LEFT, padx=10)
        
        # Connection status
        status_frame = ttk.LabelFrame(self.conn_frame, text="Connection Status", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.conn_status = tk.StringVar(value="Not connected to server")
        ttk.Label(status_frame, textvariable=self.conn_status, font=('Arial', 11)).pack(anchor='w')
        
        self.conn_details = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.conn_details, font=('Arial', 9)).pack(anchor='w', pady=5)
        
        # llama-server settings
        llama_frame = ttk.LabelFrame(self.conn_frame, text="llama-server Configuration", padding=10)
        llama_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(llama_frame, text="llama-server command:").grid(row=0, column=0, sticky='w', pady=5)
        self.llama_command = tk.StringVar(value="llama-server")
        ttk.Entry(llama_frame, textvariable=self.llama_command, width=50).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        ttk.Button(llama_frame, text="...", command=self.browse_llama, width=3).grid(row=0, column=2)
        ttk.Label(llama_frame, text="(leave 'llama-server' if it's in PATH)", font=('Arial', 8)).grid(row=0, column=3, sticky='w', padx=5)
        
        ttk.Label(llama_frame, text="GPU Layers (-ngl):").grid(row=1, column=0, sticky='w', pady=5)
        self.gpu_layers = tk.StringVar(value="99")
        ttk.Spinbox(llama_frame, textvariable=self.gpu_layers, from_=0, to=999, width=10).grid(row=1, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(llama_frame, text="(99 = all layers on GPU)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        llama_frame.columnconfigure(1, weight=1)
    
    def _create_models_tab(self):
        """Models management tab"""
        
        # Toolbar
        toolbar = ttk.Frame(self.models_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="📁 Select Models Folder", command=self._select_models_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🔄 Scan", command=self._scan_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🤗 Add HuggingFace", command=self._add_huggingface_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="☁️ Sync with Server", command=self._sync_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🗑️ Remove", command=self._remove_selected_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🧹 Clean Old", command=self._cleanup_old_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="⚠️ Delete Unused", command=self._delete_unused_models).pack(side=tk.LEFT, padx=5)
        
        # Disk space info
        disk_frame = ttk.LabelFrame(self.models_frame, text="📊 Disk Space", padding=5)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_info_var = tk.StringVar(value="Checking disk space...")
        self.disk_info_label = ttk.Label(disk_frame, textvariable=self.disk_info_var, font=('Arial', 9))
        self.disk_info_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(disk_frame, text="🔄", command=self._update_disk_info, width=3).pack(side=tk.RIGHT, padx=5)
        
        # Models folder
        folder_frame = ttk.Frame(self.models_frame)
        folder_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(folder_frame, text="Models folder:").pack(side=tk.LEFT)
        self.models_folder = tk.StringVar(value="")
        ttk.Label(folder_frame, textvariable=self.models_folder, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        # Models list with checkboxes
        list_frame = ttk.LabelFrame(self.models_frame, text="Available Models (Local and HuggingFace)", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview for models
        columns = ('enabled', 'source', 'name', 'params', 'quant', 'size', 'vram', 'context', 'uses')
        self.models_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.models_tree.heading('enabled', text='✓')
        self.models_tree.heading('source', text='Source')
        self.models_tree.heading('name', text='Name / Filename')
        self.models_tree.heading('params', text='Parameters')
        self.models_tree.heading('quant', text='Quantiz.')
        self.models_tree.heading('size', text='Size')
        self.models_tree.heading('vram', text='VRAM Min')
        self.models_tree.heading('context', text='Context')
        self.models_tree.heading('uses', text='Uses')
        
        self.models_tree.column('enabled', width=30, anchor='center')
        self.models_tree.column('source', width=60, anchor='center')
        self.models_tree.column('name', width=280)
        self.models_tree.column('params', width=70, anchor='center')
        self.models_tree.column('quant', width=70, anchor='center')
        self.models_tree.column('size', width=70, anchor='center')
        self.models_tree.column('vram', width=70, anchor='center')
        self.models_tree.column('context', width=70, anchor='center')
        self.models_tree.column('uses', width=50, anchor='center')
        
        self.models_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.models_tree.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.models_tree.config(yscrollcommand=scrollbar.set)
        
        # Bind click per toggle
        self.models_tree.bind('<Double-1>', self._toggle_model)
        
        # Selected model details
        details_frame = ttk.LabelFrame(self.models_frame, text="Model Details", padding=5)
        details_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.model_details = tk.StringVar(value="Select a model to see details")
        ttk.Label(details_frame, textvariable=self.model_details, font=('Arial', 9)).pack(anchor='w')
        
        # Context length edit
        ctx_frame = ttk.Frame(details_frame)
        ctx_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(ctx_frame, text="Context Length:").pack(side=tk.LEFT)
        self.model_context = tk.StringVar(value="4096")
        ttk.Spinbox(ctx_frame, textvariable=self.model_context, from_=512, to=131072, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(ctx_frame, text="Apply", command=self._apply_context).pack(side=tk.LEFT)
        
        self.models_tree.bind('<<TreeviewSelect>>', self._on_model_select)
    
    def _create_sessions_tab(self):
        """Active sessions tab"""
        
        # Toolbar
        toolbar = ttk.Frame(self.sessions_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🔄 Refresh", command=self._refresh_sessions).pack(side=tk.LEFT, padx=5)
        
        # Statistics
        stats_frame = ttk.LabelFrame(self.sessions_frame, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, padx=10, pady=5)
        
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(fill=tk.X)
        
        self.stats = {
            'total_sessions': tk.StringVar(value="0"),
            'active_sessions': tk.StringVar(value="0"),
            'completed_requests': tk.StringVar(value="0"),
            'total_tokens': tk.StringVar(value="0"),
            'earnings': tk.StringVar(value="0 sats")
        }
        
        labels = [
            ('Total Sessions:', 'total_sessions'),
            ('Active Sessions:', 'active_sessions'),
            ('Completed Requests:', 'completed_requests'),
            ('Generated Tokens:', 'total_tokens'),
            ('Earnings:', 'earnings')
        ]
        
        for i, (label, key) in enumerate(labels):
            ttk.Label(stats_grid, text=label, font=('Arial', 9, 'bold')).grid(row=0, column=i*2, padx=10, pady=5)
            ttk.Label(stats_grid, textvariable=self.stats[key], font=('Arial', 9)).grid(row=0, column=i*2+1, padx=5, pady=5)
        
        # Sessions list
        list_frame = ttk.LabelFrame(self.sessions_frame, text="Active Sessions", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        columns = ('id', 'model', 'status', 'started', 'requests', 'tokens')
        self.sessions_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.sessions_tree.heading('id', text='Session ID')
        self.sessions_tree.heading('model', text='Model')
        self.sessions_tree.heading('status', text='Status')
        self.sessions_tree.heading('started', text='Started')
        self.sessions_tree.heading('requests', text='Requests')
        self.sessions_tree.heading('tokens', text='Tokens')
        
        self.sessions_tree.column('id', width=100)
        self.sessions_tree.column('model', width=150)
        self.sessions_tree.column('status', width=80, anchor='center')
        self.sessions_tree.column('started', width=150)
        self.sessions_tree.column('requests', width=80, anchor='center')
        self.sessions_tree.column('tokens', width=80, anchor='center')
        
        self.sessions_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.sessions_tree.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.sessions_tree.config(yscrollcommand=scrollbar.set)
    
    def _create_log_tab(self):
        """Log tab"""
        
        toolbar = ttk.Frame(self.log_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Clear Log", command=self._clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="💾 Save Log", command=self._save_log).pack(side=tk.LEFT, padx=5)
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=20, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log_text.config(state='disabled')
    
    def _create_llm_tab(self):
        """Tab to display real-time LLM output"""
        
        # Info frame
        info_frame = ttk.Frame(self.llm_frame)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_session_var = tk.StringVar(value="No active session")
        ttk.Label(info_frame, text="Session:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
        ttk.Label(info_frame, textvariable=self.llm_session_var, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        self.llm_tokens_var = tk.StringVar(value="Tokens: 0")
        ttk.Label(info_frame, textvariable=self.llm_tokens_var, font=('Arial', 9)).pack(side=tk.RIGHT, padx=10)
        
        # Toolbar
        toolbar = ttk.Frame(self.llm_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Clear", command=self._clear_llm_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="📋 Copy", command=self._copy_llm_output).pack(side=tk.LEFT, padx=5)
        
        self.llm_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.llm_autoscroll).pack(side=tk.LEFT, padx=10)
        
        # Prompt section
        prompt_frame = ttk.LabelFrame(self.llm_frame, text="📥 Received Prompt", padding=5)
        prompt_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4, font=('Consolas', 9), wrap=tk.WORD)
        self.llm_prompt_text.pack(fill=tk.X, expand=False)
        self.llm_prompt_text.config(state='disabled', bg='#2a2a3a', fg='#aaaaaa')
        
        # Output section
        output_frame = ttk.LabelFrame(self.llm_frame, text="📤 LLM Output (Token by Token)", padding=5)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.llm_output_text = scrolledtext.ScrolledText(output_frame, height=15, font=('Consolas', 10), wrap=tk.WORD)
        self.llm_output_text.pack(fill=tk.BOTH, expand=True)
        self.llm_output_text.config(state='disabled', bg='#1a1a2a', fg='#00ff00')
        
        # Token counter per sessione
        self.llm_token_count = 0

    def _clear_llm_output(self):
        """Clear LLM output"""
        self.llm_prompt_text.config(state='normal')
        self.llm_prompt_text.delete('1.0', tk.END)
        self.llm_prompt_text.config(state='disabled')
        
        self.llm_output_text.config(state='normal')
        self.llm_output_text.delete('1.0', tk.END)
        self.llm_output_text.config(state='disabled')
        
        self.llm_token_count = 0
        self.llm_tokens_var.set("Tokens: 0")
        self.llm_session_var.set("No active session")
    
    def _copy_llm_output(self):
        """Copy LLM output to clipboard"""
        output = self.llm_output_text.get('1.0', tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.update_status("LLM output copied to clipboard")
    
    def llm_set_prompt(self, session_id, prompt):
        """Set the displayed prompt"""
        def update():
            self.llm_session_var.set(f"Session: {session_id}")
            self.llm_token_count = 0
            self.llm_tokens_var.set("Tokens: 0")
            
            self.llm_prompt_text.config(state='normal')
            self.llm_prompt_text.delete('1.0', tk.END)
            self.llm_prompt_text.insert(tk.END, prompt[-2000:] if len(prompt) > 2000 else prompt)  # Limita a 2000 char
            self.llm_prompt_text.config(state='disabled')
            
            self.llm_output_text.config(state='normal')
            self.llm_output_text.delete('1.0', tk.END)
            self.llm_output_text.config(state='disabled')
            
            # Switch to LLM tab
            self.notebook.select(self.llm_frame)
        
        self.root.after(0, update)
    
    def llm_add_token(self, token, is_final=False):
        """Aggiunge un token all'output"""
        def update():
            self.llm_token_count += 1
            self.llm_tokens_var.set(f"Token: {self.llm_token_count}")
            
            self.llm_output_text.config(state='normal')
            self.llm_output_text.insert(tk.END, token)
            self.llm_output_text.config(state='disabled')
            
            if self.llm_autoscroll.get():
                self.llm_output_text.see(tk.END)
            
            if is_final:
                self.llm_output_text.config(state='normal')
                self.llm_output_text.insert(tk.END, "\n\n--- Generation complete ---\n")
                self.llm_output_text.config(state='disabled')
        
        self.root.after(0, update)
    
    def llm_session_ended(self, session_id):
        """Callback when a session is terminated by user"""
        def update():
            self.llm_output_text.config(state='normal')
            self.llm_output_text.insert(tk.END, f"\n\n🛑 Session {session_id} terminated by user.\n")
            self.llm_output_text.insert(tk.END, "The model has been unloaded from memory.\n")
            self.llm_output_text.config(state='disabled')
            
            if self.llm_autoscroll.get():
                self.llm_output_text.see(tk.END)
            
            # Reset prompt state
            self.llm_prompt_text.config(state='normal')
            self.llm_prompt_text.delete('1.0', tk.END)
            self.llm_prompt_text.insert(tk.END, "(Waiting for new session...)")
            self.llm_prompt_text.config(state='disabled')
            
            # Reset token counter
            self.llm_token_count = 0
            self.llm_tokens_var.set("Tokens: 0")
        
        self.root.after(0, update)

    def _create_stats_tab(self):
        """Node statistics tab"""
        
        # Main frame with padding
        main_frame = ttk.Frame(self.stats_frame, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="📈 Node Statistics", style='Header.TLabel', font=('Arial', 14, 'bold'))
        title_label.pack(pady=(0, 15))
        
        # Stats frame
        stats_container = ttk.LabelFrame(main_frame, text="Summary", padding="15")
        stats_container.pack(fill=tk.X, pady=10)
        
        # Grid for stats
        self.stats_vars = {}
        stats_labels = [
            ('total_sessions', '🔗 Total Sessions', '0'),
            ('completed_sessions', '✅ Completed Sessions', '0'),
            ('failed_sessions', '❌ Failed Sessions', '0'),
            ('total_requests', '📤 Processed Requests', '0'),
            ('total_tokens', '🔤 Generated Tokens', '0'),
            ('total_minutes', '⏱️ Active Minutes', '0'),
            ('total_earned', '⚡ Earned Satoshis', '0'),
            ('avg_tokens_sec', '🚀 Tokens/sec (avg)', '0.0'),
            ('avg_response_ms', '⏳ Response Time (avg)', '0 ms'),
            ('first_online', '📅 First Connection', '-'),
            ('last_online', '🕐 Last Activity', '-'),
            ('uptime_hours', '📊 Total Hours Online', '0'),
        ]
        
        for i, (key, label, default) in enumerate(stats_labels):
            row = i // 2
            col = (i % 2) * 2
            
            ttk.Label(stats_container, text=label + ":", style='Info.TLabel').grid(
                row=row, column=col, sticky='e', padx=(10, 5), pady=5
            )
            
            self.stats_vars[key] = tk.StringVar(value=default)
            ttk.Label(stats_container, textvariable=self.stats_vars[key], font=('Arial', 10, 'bold')).grid(
                row=row, column=col+1, sticky='w', padx=(0, 20), pady=5
            )
        
        # Configura colonne
        for col in range(4):
            stats_container.columnconfigure(col, weight=1)
        
        # Auto-refresh frame
        refresh_frame = ttk.LabelFrame(main_frame, text="Auto Refresh", padding="10")
        refresh_frame.pack(fill=tk.X, pady=10)
        
        self.stats_auto_refresh = tk.BooleanVar(value=False)
        self.stats_refresh_interval = tk.StringVar(value="30")
        
        ttk.Checkbutton(refresh_frame, text="Auto-refresh statistics every", 
                       variable=self.stats_auto_refresh, 
                       command=self._toggle_stats_auto_refresh).pack(side=tk.LEFT, padx=5)
        
        ttk.Spinbox(refresh_frame, textvariable=self.stats_refresh_interval, 
                   from_=10, to=300, width=5).pack(side=tk.LEFT)
        ttk.Label(refresh_frame, text="seconds").pack(side=tk.LEFT, padx=5)
        
        # Last update label
        self.stats_last_update = tk.StringVar(value="Never updated")
        ttk.Label(refresh_frame, textvariable=self.stats_last_update, 
                 foreground='gray').pack(side=tk.RIGHT, padx=10)
        
        # Button frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=20)
        
        ttk.Button(btn_frame, text="🔄 Refresh Statistics", command=self._load_stats).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Copy Report", command=self._copy_stats_report).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ Reset Statistics", command=self._reset_stats).pack(side=tk.LEFT, padx=5)
        
        # Note
        note_label = ttk.Label(main_frame, 
            text="ℹ️ Statistics are stored on the server and persist between sessions.\n"
                 "   Enable auto-refresh to keep statistics updated in real-time.",
            style='Info.TLabel', foreground='gray')
        note_label.pack(pady=10)
        
        # Auto-refresh timer ID
        self._stats_refresh_timer = None
    
    # === Hardware Detection ===
    
    def _detect_hardware(self):
        """Detect system hardware"""
        self.update_status("Detecting hardware...")
        
        def detect():
            try:
                self.system_info = get_system_info()
                self.root.after(0, self._update_hw_display)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error detecting hardware: {e}"))
        
        threading.Thread(target=detect, daemon=True).start()
    
    def _update_hw_display(self):
        """Update hardware display"""
        if not self.system_info:
            return
        
        # Update text area
        self.hw_text.config(state='normal')
        self.hw_text.delete('1.0', tk.END)
        self.hw_text.insert(tk.END, format_system_info(self.system_info))
        self.hw_text.config(state='disabled')
        
        # Update summary
        info = self.system_info
        self.hw_summary['cpu'].set(info['cpu']['name'][:40] + '...' if len(info['cpu']['name']) > 40 else info['cpu']['name'])
        self.hw_summary['cores'].set(f"{info['cpu']['cores_physical']} physical / {info['cpu']['cores_logical']} logical")
        self.hw_summary['ram'].set(f"{info['ram']['total_gb']} GB")
        
        if info['gpus']:
            gpu_names = ', '.join([g['name'] for g in info['gpus'][:2]])
            if len(info['gpus']) > 2:
                gpu_names += f" (+{len(info['gpus'])-2})"
            self.hw_summary['gpu'].set(gpu_names[:50])
            self.hw_summary['vram'].set(f"{info['total_vram_mb']} MB")
        else:
            self.hw_summary['gpu'].set("No dedicated GPU")
            self.hw_summary['vram'].set("-")
        
        self.hw_summary['max_model'].set(f"~{info['max_model_params_b']}B params (Q4)")
        
        self.update_status(f"Hardware detected: {len(info['gpus'])} GPU, {info['total_vram_mb']} MB VRAM")
        self.log(f"Hardware detected: CPU {info['cpu']['cores_logical']} cores, {info['ram']['total_gb']} GB RAM, {len(info['gpus'])} GPU")
    
    def _copy_hw_info(self):
        """Copy hardware info to clipboard"""
        self.root.clipboard_clear()
        self.root.clipboard_append(format_system_info(self.system_info))
        self.update_status("Hardware info copied to clipboard")
    
    # === Models Management ===
    
    def _select_models_folder(self):
        """Select models folder"""
        folder = filedialog.askdirectory(title="Select GGUF models folder")
        if folder:
            self.models_folder.set(folder)
            self._init_model_manager(folder)
            self._scan_models()
    
    def _init_model_manager(self, folder):
        """Initialize model manager"""
        self.model_manager = ModelManager(folder)
    
    def _scan_models(self):
        """Scan models"""
        if not self.model_manager:
            folder = self.models_folder.get()
            if not folder:
                messagebox.showwarning("Warning", "Select a models folder first")
                return
            self._init_model_manager(folder)
        
        self.update_status("Scanning models...")
        
        def scan():
            try:
                models = self.model_manager.scan_models()
                self.root.after(0, lambda: self._update_models_list(models))
                self.root.after(0, self._update_disk_info)  # Also update disk space
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Scan error: {e}"))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _update_models_list(self, models):
        """Update models list"""
        # Clear list
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        
        # Sort models: unused first (use_count = 0), then by use_count ascending
        sorted_models = sorted(models, key=lambda m: (getattr(m, 'use_count', 0) > 0, getattr(m, 'use_count', 0)))
        
        # Add models
        unused_count = 0
        for model in sorted_models:
            enabled = '✓' if model.enabled else '✗'
            # Indicate if HuggingFace or local
            source = '🤗 HF' if getattr(model, 'is_huggingface', False) else '📁 Local'
            # Use filename as display name (full GGUF filename)
            display_name = model.filename if model.filename else model.name
            use_count = getattr(model, 'use_count', 0)
            
            # Tag unused models
            tags = ()
            if use_count == 0:
                tags = ('unused',)
                unused_count += 1
            
            self.models_tree.insert('', 'end', iid=model.id, values=(
                enabled,
                source,
                display_name,
                model.parameters,
                model.quantization,
                f"{model.size_gb:.2f} GB",
                f"{model.min_vram_mb} MB",
                model.context_length,
                use_count
            ), tags=tags)
        
        # Configure tag colors
        self.models_tree.tag_configure('unused', foreground='#ff6b6b')
        
        status_msg = f"Found {len(models)} models"
        if unused_count > 0:
            status_msg += f" ({unused_count} never used - highlighted in red)"
        self.update_status(status_msg)
        self.log(f"Scan completed: {len(models)} models found, {unused_count} never used")
    
    def _toggle_model(self, event):
        """Toggle model enabled state"""
        item = self.models_tree.selection()
        if not item:
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                new_state = not model.enabled
                self.model_manager.set_model_enabled(model_id, new_state)
                
                # Update UI (first column is enabled)
                enabled = '✓' if new_state else '✗'
                values = list(self.models_tree.item(model_id, 'values'))
                values[0] = enabled
                self.models_tree.item(model_id, values=values)
    
    def _on_model_select(self, event):
        """Model selection"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        model = self.model_manager.get_model_by_id(item[0])
        if model:
            if getattr(model, 'is_huggingface', False):
                details = f"🤗 HuggingFace: {model.hf_repo}\n"
            else:
                details = f"📁 File: {model.filename}\n"
            details += f"Architecture: {model.architecture}\n"
            details += f"VRAM: {model.min_vram_mb} MB min, {model.recommended_vram_mb} MB recommended\n"
            # Add usage stats
            use_count = getattr(model, 'use_count', 0)
            last_used = getattr(model, 'last_used', '')
            if use_count > 0:
                details += f"📊 Usage: {use_count} times"
                if last_used:
                    details += f" | Last used: {last_used[:10]}"
            else:
                details += f"⚠️ Never used - consider removing to save disk space"
            self.model_details.set(details)
            self.model_context.set(str(model.context_length))
    
    def _add_huggingface_model(self):
        """Open dialog to add HuggingFace model"""
        # Create model_manager if it doesn't exist (use current directory for config)
        if not self.model_manager:
            self._init_model_manager(os.getcwd())
        
        dialog = HuggingFaceModelDialog(self.root, self.model_manager)
        if dialog.result:
            # Model added, update list
            if self.model_manager:
                models = list(self.model_manager.models.values())
                self._update_models_list(models)
                self.log(f"Added HuggingFace model: {dialog.result.name}")
    
    def _remove_selected_model(self):
        """Remove the selected model"""
        item = self.models_tree.selection()
        if not item:
            messagebox.showwarning("Warning", "Select a model to remove")
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                if messagebox.askyesno("Confirm", f"Remove model '{model.name}' from list?\n\n(This does not delete the file from disk)"):
                    self.model_manager.remove_model(model_id)
                    self.models_tree.delete(model_id)
                    self.log(f"Removed model: {model.name}")
    
    def _apply_context(self):
        """Apply context length"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        try:
            context = int(self.model_context.get())
            self.model_manager.set_model_context_length(item[0], context)
            
            # Update UI (context is now column 7, index 7)
            values = list(self.models_tree.item(item[0], 'values'))
            values[7] = context
            self.models_tree.item(item[0], values=values)
            
            self.update_status(f"Context length updated to {context}")
        except ValueError:
            messagebox.showerror("Error", "Invalid context length")
    
    def _sync_models(self):
        """Sync models with server"""
        if not self.client or not self.client.is_connected():
            messagebox.showwarning("Warning", "Connect to server first")
            return
        
        if not self.model_manager:
            messagebox.showwarning("Warning", "Scan models first")
            return
        
        self.update_status("Syncing models...")
        
        def sync():
            try:
                models = self.model_manager.get_models_for_server()
                # Send via WebSocket
                self.client.sync_models(models)
                self.root.after(0, lambda: self.update_status(f"Synced {len(models)} models"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Sync error: {e}"))
        
        threading.Thread(target=sync, daemon=True).start()
    
    def _update_disk_info(self):
        """Update disk space information"""
        if not self.model_manager:
            self.disk_info_var.set("Select a models folder first")
            return
        
        status = self.model_manager.get_disk_space_status()
        
        status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
        status_text = (
            f"{status_icon} Free: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
            f"Models: {status['models_size_gb']:.1f} GB"
        )
        self.disk_info_var.set(status_text)
        
        # Color based on status
        if status['status'] == 'critical':
            self.disk_info_label.config(foreground='red')
            # Warn user
            if messagebox.askyesno("⚠️ Critical Disk Space",
                f"Disk space almost exhausted: only {status['free_gb']:.1f} GB free.\n\n"
                "Do you want to delete old/unused models to free up space?"):
                self._cleanup_old_models()
        elif status['status'] == 'warning':
            self.disk_info_label.config(foreground='orange')
        else:
            self.disk_info_label.config(foreground='green')
    
    def _cleanup_old_models(self):
        """Clean old/unused models"""
        if not self.model_manager:
            messagebox.showwarning("Warning", "Select a models folder first")
            return
        
        # Get unused models
        unused = self.model_manager.get_unused_models(days_threshold=30)
        
        if not unused:
            messagebox.showinfo("Model Cleanup", "No models to clean.\n\nAll models have been used in the last 30 days.")
            return
        
        # Calculate space to be freed
        total_size = sum(m.size_bytes for m in unused if not m.is_huggingface)
        total_size_gb = total_size / (1024 ** 3)
        
        # Show model list
        models_list = "\n".join([f"• {m.name} ({m.size_gb:.2f} GB)" for m in unused[:10]])
        if len(unused) > 10:
            models_list += f"\n... and {len(unused) - 10} more models"
        
        if messagebox.askyesno("🧹 Model Cleanup",
            f"Found {len(unused)} unused models in the last 30 days.\n\n"
            f"Models to delete:\n{models_list}\n\n"
            f"Space to be freed: {total_size_gb:.2f} GB\n\n"
            "Do you want to delete them?"):
            
            deleted = []
            for model in unused:
                if not model.is_huggingface:  # Don't delete HF models (no local file)
                    if self.model_manager.delete_model(model.id, delete_file=True):
                        deleted.append(model.name)
            
            # Update UI
            self._scan_models()
            self._update_disk_info()
            
            if deleted:
                messagebox.showinfo("Cleanup Complete",
                    f"Deleted {len(deleted)} models:\n" + "\n".join([f"• {n}" for n in deleted[:10]]))
                self.log(f"Cleanup: deleted {len(deleted)} models, freed {total_size_gb:.2f} GB")
            else:
                messagebox.showinfo("Cleanup", "No models deleted")
    
    def _delete_unused_models(self):
        """Delete models that have NEVER been used (use_count = 0)"""
        if not self.model_manager:
            messagebox.showwarning("Warning", "Select a models folder first")
            return
        
        # Get models with use_count = 0
        unused = [m for m in self.model_manager.models.values() 
                  if getattr(m, 'use_count', 0) == 0 and not m.is_huggingface]
        
        if not unused:
            messagebox.showinfo("No Unused Models", 
                "All your models have been used at least once!\n\n"
                "✓ Your model collection is optimized.")
            return
        
        # Calculate space to be freed
        total_size = sum(m.size_bytes for m in unused)
        total_size_gb = total_size / (1024 ** 3)
        
        # Show model list with filenames
        models_list = "\n".join([f"• {m.filename} ({m.size_gb:.2f} GB)" for m in unused[:10]])
        if len(unused) > 10:
            models_list += f"\n... and {len(unused) - 10} more models"
        
        if messagebox.askyesno("⚠️ Delete Unused Models",
            f"Found {len(unused)} models that have NEVER been used.\n\n"
            f"Models to delete:\n{models_list}\n\n"
            f"Space to be freed: {total_size_gb:.2f} GB\n\n"
            "These models take up disk space but no user has ever requested them.\n"
            "Do you want to delete them?"):
            
            deleted = []
            freed_space = 0
            for model in unused:
                size_gb = model.size_gb
                if self.model_manager.delete_model(model.id, delete_file=True):
                    deleted.append(model.filename)
                    freed_space += size_gb
            
            # Update UI
            self._scan_models()
            self._update_disk_info()
            
            if deleted:
                messagebox.showinfo("Cleanup Complete",
                    f"✓ Deleted {len(deleted)} unused models\n"
                    f"✓ Freed {freed_space:.2f} GB of disk space\n\n"
                    f"Deleted:\n" + "\n".join([f"• {n}" for n in deleted[:10]]))
                self.log(f"Deleted {len(deleted)} unused models, freed {freed_space:.2f} GB")
            else:
                messagebox.showinfo("Cleanup", "No models deleted")
    
    # === Connection ===
    
    def _load_config(self):
        """Load configuration"""
        # Fixed server - use direct IP
        self.server_url.set("http://51.178.142.183:5000")
        
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            
            self.node_name.set(self.config.get('Node', 'name', fallback=''))
            self.token.set(self.config.get('Node', 'token', fallback=''))
            self.price_per_minute.set(self.config.get('Node', 'price_per_minute', fallback='100'))
            # Supporta sia il nuovo 'command' che il vecchio 'bin'
            llama_cmd = self.config.get('LLM', 'command', fallback='')
            if not llama_cmd:
                llama_cmd = self.config.get('LLM', 'bin', fallback='llama-server')
            self.llama_command.set(llama_cmd)
            self.gpu_layers.set(self.config.get('LLM', 'gpu_layers', fallback='99'))
            
            models_dir = self.config.get('Models', 'directory', fallback='')
            if models_dir:
                self.models_folder.set(models_dir)
                self._init_model_manager(models_dir)
        else:
            # Auto-rileva llama-server
            llama_cmd = find_llama_binary()
            if llama_cmd:
                self.llama_command.set(llama_cmd)
    
    def _save_config(self):
        """Save configuration"""
        for section in ['Node', 'Server', 'LLM', 'Models', 'Account']:
            if section not in self.config:
                self.config[section] = {}
        
        # Server always fixed
        self.config['Server']['URL'] = "http://51.178.142.183:5000"
        self.config['Node']['name'] = self.node_name.get()
        self.config['Node']['token'] = self.token.get()
        self.config['Node']['price_per_minute'] = self.price_per_minute.get()
        self.config['LLM']['command'] = self.llama_command.get()
        self.config['LLM']['gpu_layers'] = self.gpu_layers.get()
        self.config['Models']['directory'] = self.models_folder.get()
        
        # Save account credentials (if variables exist)
        if hasattr(self, 'login_username'):
            self.config['Account']['username'] = self.login_username.get()
        if hasattr(self, 'auth_token') and self.auth_token:
            self.config['Account']['token'] = self.auth_token
        
        with open(self.config_path, 'w') as f:
            self.config.write(f)
    
    def connect(self):
        """Connect to server"""
        # Verify login
        if not hasattr(self, 'logged_in') or not self.logged_in:
            messagebox.showwarning("Login required", 
                "You must login before connecting the node.\n\n"
                "Go to the 'Account' tab and login with your credentials.")
            self.notebook.select(0)  # Go to Account tab
            return
        
        self._save_config()
        
        self.update_status("Connecting...")
        self.connect_btn.config(state='disabled')
        self.log(f"Attempting connection to {self.server_url.get()}...")
        
        def do_connect():
            try:
                self.client = NodeClient(self.config_path)
                self.client.server_url = self.server_url.get()
                self.client.node_name = self.node_name.get()
                
                # Pass user authentication token
                self.client.auth_token = self.auth_token
                self.client.user_id = self.user_info.get('user_id')
                
                # Collega callbacks GUI per visualizzare output LLM
                self.client.gui_prompt_callback = self.llm_set_prompt
                self.client.gui_token_callback = self.llm_add_token
                self.client.gui_session_ended_callback = self.llm_session_ended
                
                # Pass hardware and models info
                if self.system_info:
                    self.client.hardware_info = self.system_info
                if self.model_manager:
                    self.client.models = self.model_manager.get_models_for_server()
                    self.client.model_manager = self.model_manager  # For local file paths
                
                if self.client.connect():
                    self.root.after(0, self._on_connected)
                else:
                    self.root.after(0, lambda: self._on_connection_failed("Connection failed"))
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                self.root.after(0, lambda: self.log(f"Error:\n{err}"))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
        
        threading.Thread(target=do_connect, daemon=True).start()
    
    def _on_connected(self):
        """Connection success callback"""
        self.conn_status.set("✓ Connected to server")
        self.conn_indicator.config(text="● Connected", style='Connected.TLabel')
        self.connect_btn.config(state='disabled')
        self.disconnect_btn.config(state='normal')
        self.conn_details.set(f"Server: {self.server_url.get()}")
        self.update_status("Connected to server")
        self.log("Connection established!")
        
        # Sync models automatically
        if self.model_manager and self.model_manager.models:
            self._sync_models()
    
    def _on_connection_failed(self, error):
        """Connection failed callback"""
        self.conn_status.set("✗ Not connected")
        self.conn_indicator.config(text="● Disconnected", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.update_status(f"Error: {error}")
        messagebox.showerror("Connection Error", f"Connection failed:\n{error}")
    
    def disconnect(self):
        """Disconnect"""
        if self.client:
            self.client.disconnect()
            self.client = None
        
        self.conn_status.set("Not connected")
        self.conn_indicator.config(text="● Disconnected", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.conn_details.set("")
        self.update_status("Disconnected")
        self.log("Disconnected from server")
    
    def browse_llama(self):
        """Browse for llama-server (optional, can be in PATH)"""
        filetypes = [("Executable", "*.exe"), ("All files", "*.*")] if sys.platform == 'win32' else [("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.llama_command.set(path)
    
    # === Sessions ===
    
    def _refresh_sessions(self):
        """Refresh sessions list"""
        if not self.client:
            return
        # TODO: Implement session request from server
    
    # === Log ===
    
    def update_status(self, msg):
        """Update status bar"""
        self.status_var.set(msg)
    
    def log(self, msg):
        """Add to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
    
    def _clear_log(self):
        """Clear log"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')
    
    def _save_log(self):
        """Save log to file"""
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.log_text.config(state='normal')
            with open(path, 'w') as f:
                f.write(self.log_text.get('1.0', tk.END))
            self.log_text.config(state='disabled')
            self.update_status(f"Log saved to {path}")
    
    # === Statistics ===
    
    def _load_stats(self):
        """Load statistics from server"""
        if not self.client or not self.client.is_connected():
            messagebox.showwarning("Not connected", "You must be connected to the server to load statistics.")
            return
        
        if requests is None:
            messagebox.showerror("Missing module", "The 'requests' module is not installed. Run: pip install requests")
            return
        
        # Get node_id from client
        node_id = getattr(self.client, 'node_id', None)
        if not node_id:
            messagebox.showwarning("Missing Node ID", "Node ID not available. Reconnect to server.")
            return
        
        self.update_status("Loading statistics...")
        
        def fetch_stats():
            try:
                server_url = self.client.server_url.replace('/socket.io', '')
                # Remove trailing slashes
                server_url = server_url.rstrip('/')
                
                # Stats API request
                response = requests.get(f"{server_url}/api/node/stats/{node_id}", timeout=10)
                
                if response.status_code == 200:
                    stats = response.json()
                    self.root.after(0, lambda: self._update_stats_display(stats))
                elif response.status_code == 404:
                    # No stats yet
                    self.root.after(0, lambda: self._update_stats_display({}))
                    self.root.after(0, lambda: self.log("No statistics available (new node)"))
                else:
                    self.root.after(0, lambda: self.log(f"Error loading statistics: {response.status_code}"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error loading statistics: {e}"))
                self.root.after(0, lambda: self.update_status("Error loading statistics"))
        
        threading.Thread(target=fetch_stats, daemon=True).start()
    
    def _update_stats_display(self, stats):
        """Update statistics display"""
        try:
            self.stats_vars['total_sessions'].set(str(stats.get('total_sessions', 0)))
            self.stats_vars['completed_sessions'].set(str(stats.get('completed_sessions', 0)))
            self.stats_vars['failed_sessions'].set(str(stats.get('failed_sessions', 0)))
            self.stats_vars['total_requests'].set(str(stats.get('total_requests', 0)))
            
            # Format tokens with thousands separators
            tokens = stats.get('total_tokens_generated', 0)
            self.stats_vars['total_tokens'].set(f"{tokens:,}")
            
            # Format minutes
            minutes = stats.get('total_minutes_active', 0)
            if minutes >= 60:
                hours = minutes // 60
                mins = minutes % 60
                self.stats_vars['total_minutes'].set(f"{hours}h {mins}m")
            else:
                self.stats_vars['total_minutes'].set(f"{minutes} min")
            
            # Earned satoshis
            sats = stats.get('total_earned_sats', 0)
            self.stats_vars['total_earned'].set(f"{sats:,} sats")
            
            # Averages
            avg_tps = stats.get('avg_tokens_per_second', 0)
            self.stats_vars['avg_tokens_sec'].set(f"{avg_tps:.1f}")
            
            avg_ms = stats.get('avg_response_time_ms', 0)
            self.stats_vars['avg_response_ms'].set(f"{avg_ms:.0f} ms")
            
            # Date
            first_online = stats.get('first_online')
            if first_online:
                try:
                    dt = datetime.fromisoformat(first_online.replace('Z', '+00:00'))
                    self.stats_vars['first_online'].set(dt.strftime('%d/%m/%Y %H:%M'))
                except:
                    self.stats_vars['first_online'].set(first_online[:16])
            else:
                self.stats_vars['first_online'].set('-')
            
            last_online = stats.get('last_online')
            if last_online:
                try:
                    dt = datetime.fromisoformat(last_online.replace('Z', '+00:00'))
                    self.stats_vars['last_online'].set(dt.strftime('%d/%m/%Y %H:%M'))
                except:
                    self.stats_vars['last_online'].set(last_online[:16])
            else:
                self.stats_vars['last_online'].set('-')
            
            # Uptime
            uptime = stats.get('total_uptime_hours', 0)
            self.stats_vars['uptime_hours'].set(f"{uptime:.1f}")
            
            self.update_status("Statistics updated")
            self.log("Statistics loaded from server")
            
        except Exception as e:
            self.log(f"Error updating statistics display: {e}")
    
    def _copy_stats_report(self):
        """Copy statistics report to clipboard"""
        report_lines = [
            "=" * 40,
            "  AI LIGHTNING NODE STATS REPORT",
            "=" * 40,
            "",
            f"📊 Total Sessions:         {self.stats_vars['total_sessions'].get()}",
            f"✅ Completed Sessions:     {self.stats_vars['completed_sessions'].get()}",
            f"❌ Failed Sessions:        {self.stats_vars['failed_sessions'].get()}",
            "",
            f"📤 Requests Processed:     {self.stats_vars['total_requests'].get()}",
            f"🔤 Tokens Generated:       {self.stats_vars['total_tokens'].get()}",
            f"⏱️ Active Time:            {self.stats_vars['total_minutes'].get()}",
            "",
            f"⚡ Satoshis Earned:        {self.stats_vars['total_earned'].get()}",
            "",
            f"🚀 Tokens/sec (avg):       {self.stats_vars['avg_tokens_sec'].get()}",
            f"⏳ Response Time (avg):    {self.stats_vars['avg_response_ms'].get()}",
            "",
            f"📅 First Connection:       {self.stats_vars['first_online'].get()}",
            f"🕐 Last Activity:          {self.stats_vars['last_online'].get()}",
            f"📊 Total Hours Online:     {self.stats_vars['uptime_hours'].get()}",
            "",
            "=" * 40,
            f"  Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 40,
        ]
        
        report = "\n".join(report_lines)
        
        # Copy to clipboard
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.root.update()
        
        self.update_status("Report copied to clipboard")
        messagebox.showinfo("Copied", "Statistics report copied to clipboard!")
    
    def _toggle_stats_auto_refresh(self):
        """Toggle auto-refresh of statistics"""
        if self.stats_auto_refresh.get():
            self._start_stats_auto_refresh()
        else:
            self._stop_stats_auto_refresh()
    
    def _start_stats_auto_refresh(self):
        """Start auto-refresh timer"""
        self._stop_stats_auto_refresh()  # Stop any existing timer
        
        try:
            interval = int(self.stats_refresh_interval.get()) * 1000  # Convert to ms
        except ValueError:
            interval = 30000  # Default 30 seconds
        
        def refresh_cycle():
            if self.stats_auto_refresh.get():
                self._load_stats_silent()
                self._stats_refresh_timer = self.root.after(interval, refresh_cycle)
        
        self._stats_refresh_timer = self.root.after(interval, refresh_cycle)
        self.log(f"Auto-refresh enabled: every {interval // 1000} seconds")
    
    def _stop_stats_auto_refresh(self):
        """Stop auto-refresh timer"""
        if hasattr(self, '_stats_refresh_timer') and self._stats_refresh_timer:
            self.root.after_cancel(self._stats_refresh_timer)
            self._stats_refresh_timer = None
    
    def _load_stats_silent(self):
        """Load statistics without showing warnings (for auto-refresh)"""
        if not self.client or not self.client.is_connected():
            return
        
        if requests is None:
            return
        
        node_id = getattr(self.client, 'node_id', None)
        if not node_id:
            return
        
        def fetch_stats():
            try:
                server_url = self.client.server_url.replace('/socket.io', '')
                server_url = server_url.rstrip('/')
                
                response = requests.get(f"{server_url}/api/node/stats/{node_id}", timeout=10)
                
                if response.status_code == 200:
                    stats = response.json()
                    self.root.after(0, lambda: self._update_stats_display_silent(stats))
            except Exception:
                pass  # Silent fail for auto-refresh
        
        threading.Thread(target=fetch_stats, daemon=True).start()
    
    def _update_stats_display_silent(self, stats):
        """Update statistics display without logging (for auto-refresh)"""
        try:
            self._update_stats_display(stats)
            # Update last refresh time
            self.stats_last_update.set(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
        except Exception:
            pass
    
    def _reset_stats(self):
        """Reset statistics (requires confirmation)"""
        if not messagebox.askyesno("Reset Statistics", 
            "Are you sure you want to reset all statistics?\n\n"
            "This action cannot be undone!"):
            return
        
        if not self.client or not self.client.is_connected():
            messagebox.showwarning("Not connected", "You must be connected to the server.")
            return
        
        node_id = getattr(self.client, 'node_id', None)
        if not node_id:
            messagebox.showwarning("Missing Node ID", "Node ID not available.")
            return
        
        def reset():
            try:
                server_url = self.client.server_url.replace('/socket.io', '')
                server_url = server_url.rstrip('/')
                
                response = requests.post(f"{server_url}/api/node/stats/{node_id}/reset", timeout=10)
                
                if response.status_code == 200:
                    self.root.after(0, lambda: self._update_stats_display({}))
                    self.root.after(0, lambda: self.log("Statistics reset successfully"))
                    self.root.after(0, lambda: messagebox.showinfo("Reset", "Statistics have been reset."))
                else:
                    self.root.after(0, lambda: self.log(f"Error resetting stats: {response.status_code}"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Error resetting stats: {e}"))
        
        threading.Thread(target=reset, daemon=True).start()
    
    # === Auto-Updater ===
    
    def _start_updater(self):
        """Start auto-update check"""
        self.updater.start_checking(interval=3600)  # Every hour
        self.log("Auto-updater started")
    
    def _on_update_available(self, version, changelog, download_url):
        """Callback when an update is available"""
        self.update_pending = True
        # Update UI from main thread
        self.root.after(0, lambda: self._show_update_notification(version, changelog))
    
    def _show_update_notification(self, version, changelog):
        """Show update notification"""
        self.log(f"🔄 Update available: v{version}")
        self.status_var.set(f"Update available: v{version}")
        
        # Show dialog
        response = messagebox.askyesno(
            "Update Available",
            f"Version {version} of LightPhon Node is available.\n\n"
            f"Changelog:\n{changelog[:500]}...\n\n"
            f"Do you want to update now?\n"
            f"(The application will be restarted)",
            icon='info'
        )
        
        if response:
            self._download_and_apply_update()
    
    def _download_and_apply_update(self):
        """Download and apply the update"""
        self.log("Downloading update...")
        self.status_var.set("Downloading update...")
        
        def download_thread():
            try:
                # Progress callback
                def progress(downloaded, total):
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        self.root.after(0, lambda p=percent: self.status_var.set(f"Download: {p}%"))
                
                # Download
                update_path = self.updater.download_update(progress_callback=progress)
                
                if update_path:
                    self.root.after(0, lambda: self._apply_update(update_path))
                else:
                    self.root.after(0, lambda: self._update_failed("Download failed"))
                    
            except Exception as e:
                self.root.after(0, lambda: self._update_failed(str(e)))
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def _apply_update(self, update_path):
        """Apply the downloaded update"""
        self.log(f"Applying update from {update_path}...")
        
        response = messagebox.askyesno(
            "Apply Update",
            "The update has been downloaded.\n"
            "The application will close and restart.\n\n"
            "Continue?",
            icon='question'
        )
        
        if response:
            # Disconnect before update
            if self.client:
                self.client.disconnect()
            
            # Apply update
            if self.updater.apply_update(update_path):
                self.log("Updating, closing application...")
                self.root.after(1000, self.root.destroy)
            else:
                self._update_failed("Unable to apply the update")
    
    def _update_failed(self, error):
        """Handle update error"""
        self.log(f"❌ Update failed: {error}")
        self.status_var.set("Update failed")
        messagebox.showerror("Update Error", f"Unable to update:\n{error}")
    
    def check_update_manual(self):
        """Manual update check"""
        self.log("Checking for updates...")
        self.status_var.set("Checking for updates...")
        
        def check_thread():
            update = self.updater.check_for_updates()
            if update:
                self.root.after(0, lambda: self._show_update_notification(
                    update['version'], 
                    update.get('changelog', '')
                ))
            else:
                self.root.after(0, lambda: (
                    self.log("✓ No updates available"),
                    self.status_var.set(f"Version {VERSION} is up to date"),
                    messagebox.showinfo("Updates", f"You are using the latest version (v{VERSION})")
                ))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    # === App Lifecycle ===
    
    def on_close(self):
        """Close app"""
        self._save_config()
        # Stop auto-updater
        if self.updater:
            self.updater.stop_checking()
        if self.client:
            self.client.disconnect()
        self.root.destroy()
    
    def run(self):
        """Start GUI"""
        self.root.mainloop()


class HuggingFaceModelDialog:
    """Dialog for adding a HuggingFace model"""
    
    def __init__(self, parent, model_manager):
        self.result = None
        self.model_manager = model_manager
        self.verified = False
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Add HuggingFace Model")
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Instructions
        info_frame = ttk.LabelFrame(self.dialog, text="Instructions", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """Enter the HuggingFace repository in the format:
owner/repo:quantization

⚠️ IMPORTANT: Only repositories with GGUF files are supported!

Examples:
• bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M
• unsloth/Llama-3.2-3B-Instruct-GGUF:Q4_K_M
• Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M

The model will be downloaded automatically from HuggingFace when you start a session."""
        
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT, font=('Arial', 9)).pack(anchor='w')
        
        # Disk space
        disk_frame = ttk.LabelFrame(self.dialog, text="📊 Disk Space", padding=10)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_status_var = tk.StringVar(value="Checking disk space...")
        self.disk_status_label = ttk.Label(disk_frame, textvariable=self.disk_status_var, font=('Arial', 9))
        self.disk_status_label.pack(anchor='w')
        
        # Update disk info
        self._update_disk_status()
        
        # Input
        input_frame = ttk.LabelFrame(self.dialog, text="HuggingFace Repository", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(input_frame, text="Repo (owner/model:quant):").pack(anchor='w')
        self.repo_var = tk.StringVar()
        self.repo_entry = ttk.Entry(input_frame, textvariable=self.repo_var, width=60)
        self.repo_entry.pack(fill=tk.X, pady=5)
        self.repo_entry.focus_set()
        
        # GGUF note
        ttk.Label(input_frame, text="⚠️ Only .gguf files supported!", foreground='red', font=('Arial', 9, 'bold')).pack(anchor='w')
        
        # Bind for reset verification when text changes
        self.repo_var.trace_add('write', self._on_repo_changed)
        
        ttk.Label(input_frame, text="Context Length:").pack(anchor='w', pady=(10, 0))
        self.context_var = tk.StringVar(value="4096")
        ttk.Spinbox(input_frame, textvariable=self.context_var, from_=512, to=131072, width=15).pack(anchor='w', pady=5)
        
        # Status verifica
        self.verify_status_var = tk.StringVar(value="")
        self.verify_status_label = ttk.Label(input_frame, textvariable=self.verify_status_var, font=('Arial', 9))
        self.verify_status_label.pack(anchor='w', pady=5)
        
        # Preset popular models
        preset_frame = ttk.LabelFrame(self.dialog, text="Popular Models (click to use)", padding=10)
        preset_frame.pack(fill=tk.X, padx=10, pady=10)
        
        presets = [
            ("Llama 3.2 1B", "bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M"),
            ("Llama 3.2 3B", "unsloth/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"),
            ("Qwen 2.5 1.5B", "Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M"),
            ("SmolLM2 1.7B", "HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF:Q4_K_M"),
            ("Phi-3 Mini", "bartowski/Phi-3.5-mini-instruct-GGUF:Q4_K_M"),
        ]
        
        for name, repo in presets:
            btn = ttk.Button(preset_frame, text=name, 
                           command=lambda r=repo: self._set_preset(r))
            btn.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=20)
        
        self.verify_btn = ttk.Button(btn_frame, text="🔍 Verify Model", command=self._verify_model, width=18)
        self.verify_btn.pack(side=tk.LEFT, padx=5)
        
        self.add_btn = ttk.Button(btn_frame, text="✅ Add", command=self._add_model, width=15, state='disabled')
        self.add_btn.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(btn_frame, text="Cancel", command=self.dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
        
        # Bind Enter
        self.repo_entry.bind('<Return>', lambda e: self._verify_model())
        
        # Wait for close
        self.dialog.wait_window()
    
    def _update_disk_status(self):
        """Update disk space info"""
        if self.model_manager:
            status = self.model_manager.get_disk_space_status()
            status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
            self.disk_status_var.set(
                f"{status_icon} Free space: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
                f"Models: {status['models_size_gb']:.1f} GB"
            )
            
            if status['status'] == 'critical':
                self.disk_status_label.config(foreground='red')
            elif status['status'] == 'warning':
                self.disk_status_label.config(foreground='orange')
            else:
                self.disk_status_label.config(foreground='green')
    
    def _set_preset(self, repo):
        """Set a preset and reset verification"""
        self.repo_var.set(repo)
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _on_repo_changed(self, *args):
        """Callback when repo changes - reset verification"""
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _verify_model(self):
        """Verify the HuggingFace model exists"""
        repo = self.repo_var.get().strip()
        if not repo:
            messagebox.showwarning("Warning", "Enter a HuggingFace repository", parent=self.dialog)
            return
        
        # Verify basic format
        if '/' not in repo:
            messagebox.showwarning("Warning", 
                "Invalid format. Use: owner/repo:quantization\nEx: bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M", 
                parent=self.dialog)
            return
        
        # Show verification status
        self.verify_status_var.set("🔄 Verifying repository on HuggingFace...")
        self.verify_btn.config(state='disabled')
        self.dialog.update()
        
        # Verify in thread
        import threading
        def verify_thread():
            try:
                import requests
                
                # Parse repo
                if ':' in repo:
                    repo_name, quant = repo.rsplit(':', 1)
                else:
                    repo_name = repo
                    quant = None
                
                # Verify the repo exists on HuggingFace
                api_url = f"https://huggingface.co/api/models/{repo_name}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    model_id = data.get('id', repo_name)
                    
                    # Check if there are GGUF files
                    siblings = data.get('siblings', [])
                    gguf_files = [f for f in siblings if f.get('rfilename', '').endswith('.gguf')]
                    
                    if gguf_files:
                        # Find file with specified quantization
                        if quant:
                            matching = [f for f in gguf_files if quant.upper() in f.get('rfilename', '').upper()]
                            if matching:
                                file_info = matching[0]
                                size_bytes = file_info.get('size', 0)
                                size_gb = size_bytes / (1024**3) if size_bytes else 0
                                
                                self.dialog.after(0, lambda: self._verify_success(
                                    f"✅ Model found: {model_id}\n"
                                    f"   File: {file_info.get('rfilename', 'N/A')}\n"
                                    f"   Size: {size_gb:.2f} GB"
                                ))
                            else:
                                self.dialog.after(0, lambda: self._verify_warning(
                                    f"⚠️ Repository found but quantization '{quant}' not found.\n"
                                    f"   GGUF files available: {len(gguf_files)}"
                                ))
                        else:
                            self.dialog.after(0, lambda: self._verify_success(
                                f"✅ Model found: {model_id}\n"
                                f"   GGUF files available: {len(gguf_files)}"
                            ))
                    else:
                        self.dialog.after(0, lambda: self._verify_error(
                            f"❌ Repository found but does not contain GGUF files"
                        ))
                elif response.status_code == 404:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ Repository not found: {repo_name}"
                    ))
                else:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ HuggingFace error: HTTP {response.status_code}"
                    ))
                    
            except requests.exceptions.Timeout:
                self.dialog.after(0, lambda: self._verify_error(
                    "❌ Timeout: HuggingFace not responding"
                ))
            except Exception as e:
                self.dialog.after(0, lambda: self._verify_error(
                    f"❌ Error: {str(e)}"
                ))
        
        threading.Thread(target=verify_thread, daemon=True).start()
    
    def _verify_success(self, message):
        """Verification successful"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='green')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')
        self.verified = True
    
    def _verify_warning(self, message):
        """Verification with warning"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='orange')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')  # Allow adding anyway
        self.verified = True
    
    def _verify_error(self, message):
        """Verification failed"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='red')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='disabled')
        self.verified = False
    
    def _add_model(self):
        """Add the model"""
        if not self.verified:
            messagebox.showwarning("Warning", 
                "First verify the model exists by clicking '🔍 Verify Model'", 
                parent=self.dialog)
            return
        
        repo = self.repo_var.get().strip()
        
        # Check disk space
        if self.model_manager:
            disk_status = self.model_manager.get_disk_space_status()
            if disk_status['status'] == 'critical':
                if not messagebox.askyesno("Critical Disk Space",
                    f"Disk space almost full ({disk_status['free_gb']:.1f} GB free).\n\n"
                    "Continue anyway?",
                    parent=self.dialog):
                    return
        
        try:
            context = int(self.context_var.get())
        except ValueError:
            context = 4096
        
        if self.model_manager:
            self.result = self.model_manager.add_huggingface_model(repo, context)
            if self.result:
                messagebox.showinfo("Success", 
                    f"Model added: {self.result.name}\n\n"
                    "The model will be downloaded automatically when you start a session.\n"
                    "NOTE: Download may take several minutes.",
                    parent=self.dialog)
                self.dialog.destroy()
            else:
                messagebox.showerror("Error", "Unable to add the model", parent=self.dialog)
        else:
            messagebox.showerror("Error", "Model Manager not initialized", parent=self.dialog)


if __name__ == '__main__':
    import signal
    import atexit
    
    app = NodeGUI()
    
    # Cleanup function
    def cleanup():
        if app.client:
            print("Cleaning up llama-server processes...")
            app.client.cleanup_all_sessions()
            app.client.disconnect()
    
    # Signal handler per Ctrl+C
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, cleaning up...")
        cleanup()
        sys.exit(0)
    
    # Registra handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup)
    
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        cleanup()

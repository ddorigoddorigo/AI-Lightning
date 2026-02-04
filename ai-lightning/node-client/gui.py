"""
AI Lightning Node Client - GUI

Interfaccia grafica per il nodo host con rilevamento hardware e gestione modelli.
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

# Aggiungi path per imports
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
        
        # Icona (se disponibile)
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass
        
        # Variabili
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
        
        # Rileva hardware all'avvio
        self.root.after(100, self._detect_hardware)
        
        # Avvia auto-updater
        self.root.after(5000, self._start_updater)
    
    def _create_ui(self):
        """Crea l'interfaccia"""
        
        # Notebook per tabs
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
        
        # === Tab 2: Connessione ===
        self.conn_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.conn_frame, text="🔌 Connessione")
        self._create_connection_tab()
        
        # === Tab 3: Modelli ===
        self.models_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.models_frame, text="🧠 Modelli")
        self._create_models_tab()
        
        # === Tab 4: Sessioni ===
        self.sessions_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.sessions_frame, text="📊 Sessioni")
        self._create_sessions_tab()
        
        # === Tab 5: Log ===
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="📝 Log")
        self._create_log_tab()
        
        # === Tab 6: LLM Output ===
        self.llm_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.llm_frame, text="🤖 LLM Output")
        self._create_llm_tab()
        
        # === Tab 7: Statistiche ===
        self.stats_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_frame, text="📈 Statistiche")
        self._create_stats_tab()
        
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar(value="Avvio in corso...")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.status_label.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        # Pulsante controllo aggiornamenti
        self.update_btn = ttk.Button(status_frame, text="🔄", width=3, command=self.check_update_manual)
        self.update_btn.pack(side=tk.RIGHT, padx=2)
        
        # Etichetta versione
        version_label = ttk.Label(status_frame, text=f"v{VERSION}", font=('Arial', 8))
        version_label.pack(side=tk.RIGHT, padx=5)
        
        self.conn_indicator = ttk.Label(status_frame, text="● Disconnesso", style='Disconnected.TLabel')
        self.conn_indicator.pack(side=tk.RIGHT, padx=10)
        
        # Salva config alla chiusura
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _create_account_tab(self):
        """Tab Account - Login e Registrazione"""
        
        # Variabili account
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Frame principale
        main_frame = ttk.Frame(self.account_frame, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header = ttk.Label(main_frame, text="👤 Account LightPhon", font=('Arial', 16, 'bold'))
        header.pack(pady=(0, 20))
        
        # === Frame Login (default visibile) ===
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
        
        ttk.Button(btn_frame, text="📝 Registrati", command=self._show_register, width=15).pack(side=tk.LEFT, padx=5)
        
        self.login_status = tk.StringVar(value="")
        ttk.Label(self.login_frame, textvariable=self.login_status, foreground='red').grid(row=3, column=0, columnspan=2, pady=5)
        
        self.login_frame.columnconfigure(1, weight=1)
        
        # === Frame Registrazione (nascosto di default) ===
        self.register_frame = ttk.LabelFrame(main_frame, text="📝 Registrazione", padding=15)
        # Non facciamo pack, sarà mostrato con _show_register
        
        ttk.Label(self.register_frame, text="Username:").grid(row=0, column=0, sticky='w', pady=5)
        self.reg_username = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_username, width=40).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Email:").grid(row=1, column=0, sticky='w', pady=5)
        self.reg_email = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_email, width=40).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Password:").grid(row=2, column=0, sticky='w', pady=5)
        self.reg_password = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_password, show='*', width=40).grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(self.register_frame, text="Conferma Password:").grid(row=3, column=0, sticky='w', pady=5)
        self.reg_confirm = tk.StringVar()
        ttk.Entry(self.register_frame, textvariable=self.reg_confirm, show='*', width=40).grid(row=3, column=1, padx=10, pady=5, sticky='ew')
        
        reg_btn_frame = ttk.Frame(self.register_frame)
        reg_btn_frame.grid(row=4, column=0, columnspan=2, pady=15)
        
        ttk.Button(reg_btn_frame, text="✓ Registrati", command=self._do_register, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(reg_btn_frame, text="← Torna al Login", command=self._show_login, width=15).pack(side=tk.LEFT, padx=5)
        
        self.register_status = tk.StringVar(value="")
        ttk.Label(self.register_frame, textvariable=self.register_status, foreground='red').grid(row=5, column=0, columnspan=2, pady=5)
        
        self.register_frame.columnconfigure(1, weight=1)
        
        # === Frame Account Connesso (nascosto di default) ===
        self.account_info_frame = ttk.LabelFrame(main_frame, text="✓ Account Connesso", padding=15)
        # Non facciamo pack, sarà mostrato dopo login
        
        self.account_user_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="👤 Utente:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_user_var, font=('Arial', 11)).grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        self.account_email_var = tk.StringVar(value="")
        ttk.Label(self.account_info_frame, text="📧 Email:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_email_var, font=('Arial', 10)).grid(row=1, column=1, sticky='w', padx=10, pady=5)
        
        self.account_balance_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="⚡ Saldo:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_balance_var, font=('Arial', 11, 'bold'), foreground='orange').grid(row=2, column=1, sticky='w', padx=10, pady=5)
        
        self.account_earnings_var = tk.StringVar(value="0 sats")
        ttk.Label(self.account_info_frame, text="💰 Guadagni Nodo:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky='w', pady=5)
        ttk.Label(self.account_info_frame, textvariable=self.account_earnings_var, font=('Arial', 11, 'bold'), foreground='green').grid(row=3, column=1, sticky='w', padx=10, pady=5)
        
        account_btn_frame = ttk.Frame(self.account_info_frame)
        account_btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        ttk.Button(account_btn_frame, text="🔄 Aggiorna", command=self._refresh_account, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(account_btn_frame, text="🚪 Logout", command=self._do_logout, width=12).pack(side=tk.LEFT, padx=5)
        
        self.account_info_frame.columnconfigure(1, weight=1)
        
        # Note
        note_frame = ttk.Frame(main_frame)
        note_frame.pack(fill=tk.X, pady=20)
        
        note_text = (
            "ℹ️ Effettua il login con lo stesso account che usi su lightphon.com\n"
            "   I guadagni del tuo nodo verranno accreditati sul tuo saldo.\n"
            "   Potrai poi prelevare i satoshi tramite Lightning Network."
        )
        ttk.Label(note_frame, text=note_text, font=('Arial', 9), foreground='gray', justify='left').pack(anchor='w')
        
        # Carica credenziali salvate
        self._load_account_config()
    
    def _show_register(self):
        """Mostra form registrazione"""
        self.login_frame.pack_forget()
        self.register_frame.pack(fill=tk.X, pady=10)
    
    def _show_login(self):
        """Mostra form login"""
        self.register_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
    
    def _load_account_config(self):
        """Carica credenziali salvate"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            saved_username = self.config.get('Account', 'username', fallback='')
            saved_token = self.config.get('Account', 'token', fallback='')
            
            if saved_username:
                self.login_username.set(saved_username)
            
            # Se c'è un token salvato, prova auto-login
            if saved_token:
                self.auth_token = saved_token
                self.root.after(500, self._try_auto_login)
    
    def _try_auto_login(self):
        """Prova login automatico con token salvato"""
        if not self.auth_token:
            return
        
        self.login_status.set("Auto-login in corso...")
        
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
                    # Token scaduto/invalido
                    self.auth_token = None
                    self.root.after(0, lambda: self.login_status.set("Sessione scaduta, effettua il login"))
            except Exception as e:
                self.root.after(0, lambda: self.login_status.set(f"Errore: {e}"))
        
        threading.Thread(target=do_auto, daemon=True).start()
    
    def _do_login(self):
        """Esegui login"""
        username = self.login_username.get().strip()
        password = self.login_password.get()
        
        if not username or not password:
            self.login_status.set("Inserisci username e password")
            return
        
        self.login_status.set("Login in corso...")
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
                    error = response.json().get('error', 'Login fallito')
                    self.root.after(0, lambda: self.login_status.set(f"❌ {error}"))
                    self.root.after(0, lambda: self.login_btn.config(state='normal'))
            except Exception as e:
                self.root.after(0, lambda: self.login_status.set(f"❌ Errore: {e}"))
                self.root.after(0, lambda: self.login_btn.config(state='normal'))
        
        threading.Thread(target=do_login, daemon=True).start()
    
    def _on_login_success(self, data, auto=False):
        """Callback login riuscito"""
        self.logged_in = True
        self.user_info = data
        
        # Salva token e username
        if 'Account' not in self.config:
            self.config['Account'] = {}
        self.config['Account']['username'] = self.login_username.get()
        self.config['Account']['token'] = self.auth_token or ''
        self._save_config()
        
        # Aggiorna UI
        self.account_user_var.set(data.get('username', ''))
        self.account_email_var.set(data.get('email', ''))
        balance = data.get('balance', 0)
        self.account_balance_var.set(f"{balance:,} sats".replace(',', '.'))
        
        # Nascondi login, mostra info account
        self.login_frame.pack_forget()
        self.register_frame.pack_forget()
        self.account_info_frame.pack(fill=tk.X, pady=10)
        
        self.login_btn.config(state='normal')
        self.login_status.set("")
        
        self.log(f"Login effettuato: {data.get('username')}")
        self.update_status(f"Connesso come: {data.get('username')}")
        
        # Carica guadagni nodo
        self._load_node_earnings()
    
    def _do_register(self):
        """Esegui registrazione"""
        username = self.reg_username.get().strip()
        email = self.reg_email.get().strip()
        password = self.reg_password.get()
        confirm = self.reg_confirm.get()
        
        if not username or not email or not password:
            self.register_status.set("Compila tutti i campi")
            return
        
        if password != confirm:
            self.register_status.set("Le password non coincidono")
            return
        
        if len(password) < 8:
            self.register_status.set("Password deve essere almeno 8 caratteri")
            return
        
        self.register_status.set("Registrazione in corso...")
        
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
                    self.root.after(0, lambda: messagebox.showinfo("Registrazione", "✓ Registrazione completata!\nOra puoi effettuare il login."))
                    self.root.after(0, self._show_login)
                    self.root.after(0, lambda: self.login_username.set(username))
                else:
                    error = response.json().get('error', 'Registrazione fallita')
                    self.root.after(0, lambda: self.register_status.set(f"❌ {error}"))
            except Exception as e:
                self.root.after(0, lambda: self.register_status.set(f"❌ Errore: {e}"))
        
        threading.Thread(target=do_register, daemon=True).start()
    
    def _do_logout(self):
        """Esegui logout"""
        self.logged_in = False
        self.auth_token = None
        self.user_info = {}
        
        # Rimuovi token salvato
        if 'Account' in self.config:
            self.config['Account']['token'] = ''
            self._save_config()
        
        # Mostra login
        self.account_info_frame.pack_forget()
        self.login_frame.pack(fill=tk.X, pady=10)
        self.login_password.set('')
        
        self.log("Logout effettuato")
        self.update_status("Disconnesso dall'account")
    
    def _refresh_account(self):
        """Aggiorna info account"""
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
                    self.root.after(0, lambda: self.update_status("Account aggiornato"))
                    self.root.after(0, self._load_node_earnings)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Errore aggiornamento account: {e}"))
        
        threading.Thread(target=do_refresh, daemon=True).start()
    
    def _load_node_earnings(self):
        """Carica guadagni nodo dall'account"""
        # I guadagni sono già nel balance, ma potremmo voler mostrare separatamente
        # Per ora mostriamo che il saldo include i guadagni del nodo
        self.account_earnings_var.set("Inclusi nel saldo ⬆️")
    
    def _create_hardware_tab(self):
        """Tab informazioni hardware"""
        
        # Frame info sistema
        info_frame = ttk.LabelFrame(self.hw_frame, text="Informazioni Sistema", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Text area per info hardware
        self.hw_text = scrolledtext.ScrolledText(info_frame, height=15, font=('Consolas', 10))
        self.hw_text.pack(fill=tk.BOTH, expand=True)
        self.hw_text.insert(tk.END, "Rilevamento hardware in corso...")
        self.hw_text.config(state='disabled')
        
        # Bottoni
        btn_frame = ttk.Frame(self.hw_frame)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="🔄 Rileva Hardware", command=self._detect_hardware).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Copia Info", command=self._copy_hw_info).pack(side=tk.LEFT, padx=5)
        
        # Sommario rapido
        summary_frame = ttk.LabelFrame(self.hw_frame, text="Riepilogo Rapido", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Griglia info
        self.hw_summary = {}
        labels = [
            ('cpu', 'CPU:', 0, 0),
            ('cores', 'Core:', 0, 2),
            ('ram', 'RAM:', 1, 0),
            ('gpu', 'GPU:', 2, 0),
            ('vram', 'VRAM:', 2, 2),
            ('max_model', 'Max Modello:', 3, 0),
        ]
        
        for key, text, row, col in labels:
            ttk.Label(summary_frame, text=text, style='Header.TLabel').grid(row=row, column=col, sticky='w', padx=5, pady=2)
            self.hw_summary[key] = tk.StringVar(value="-")
            ttk.Label(summary_frame, textvariable=self.hw_summary[key], style='Info.TLabel').grid(row=row, column=col+1, sticky='w', padx=5, pady=2)
        
        # Configura colonne
        for i in range(4):
            summary_frame.columnconfigure(i, weight=1)
    
    def _create_connection_tab(self):
        """Tab connessione"""
        
        # Server info (fisso)
        server_frame = ttk.LabelFrame(self.conn_frame, text="Server LightPhon", padding=10)
        server_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Server URL fisso - non modificabile
        # Usa IP diretto finché DNS non è configurato correttamente
        self.server_url = tk.StringVar(value="http://51.178.142.183:5000")
        ttk.Label(server_frame, text="Server:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(server_frame, text="lightphon.com (51.178.142.183)", font=('Arial', 10, 'bold'), foreground='green').grid(row=0, column=1, sticky='w', padx=10, pady=5)
        
        ttk.Label(server_frame, text="Nome Nodo:").grid(row=1, column=0, sticky='w', pady=5)
        self.node_name = tk.StringVar(value="")
        ttk.Entry(server_frame, textvariable=self.node_name, width=50).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(opzionale, per identificare il nodo)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        ttk.Label(server_frame, text="Token:").grid(row=2, column=0, sticky='w', pady=5)
        self.token = tk.StringVar()
        ttk.Entry(server_frame, textvariable=self.token, width=50, show='*').grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(opzionale, per autenticazione)", font=('Arial', 8)).grid(row=2, column=2, sticky='w')
        
        server_frame.columnconfigure(1, weight=1)
        
        # Pricing settings
        pricing_frame = ttk.LabelFrame(self.conn_frame, text="💰 Prezzo per Minuto", padding=10)
        pricing_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(pricing_frame, text="Satoshi/minuto:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
        self.price_per_minute = tk.StringVar(value="100")
        price_spin = ttk.Spinbox(pricing_frame, textvariable=self.price_per_minute, from_=1, to=100000, width=15, font=('Arial', 12))
        price_spin.grid(row=0, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(pricing_frame, text="sats", font=('Arial', 10, 'bold')).grid(row=0, column=2, sticky='w')
        
        # Suggerimenti prezzo
        price_hints = ttk.Frame(pricing_frame)
        price_hints.grid(row=1, column=0, columnspan=4, sticky='w', pady=10)
        
        ttk.Label(price_hints, text="Suggerimenti:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        ttk.Button(price_hints, text="50 sats (economico)", command=lambda: self.price_per_minute.set("50"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="100 sats (standard)", command=lambda: self.price_per_minute.set("100"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="500 sats (premium)", command=lambda: self.price_per_minute.set("500"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(price_hints, text="1000 sats (high-end)", command=lambda: self.price_per_minute.set("1000"), width=15).pack(side=tk.LEFT, padx=3)
        
        ttk.Label(pricing_frame, text="⚡ Gli utenti pagheranno questo importo per ogni minuto di utilizzo del tuo nodo", 
                  font=('Arial', 9), foreground='gray').grid(row=2, column=0, columnspan=4, sticky='w', pady=5)
        
        pricing_frame.columnconfigure(1, weight=1)
        
        # Bottoni connessione
        btn_frame = ttk.Frame(self.conn_frame)
        btn_frame.pack(pady=20)
        
        self.connect_btn = ttk.Button(btn_frame, text="🔌 Connetti", command=self.connect, width=15)
        self.connect_btn.pack(side=tk.LEFT, padx=10)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="❌ Disconnetti", command=self.disconnect, state='disabled', width=15)
        self.disconnect_btn.pack(side=tk.LEFT, padx=10)
        
        # Stato connessione
        status_frame = ttk.LabelFrame(self.conn_frame, text="Stato Connessione", padding=10)
        status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.conn_status = tk.StringVar(value="Non connesso al server")
        ttk.Label(status_frame, textvariable=self.conn_status, font=('Arial', 11)).pack(anchor='w')
        
        self.conn_details = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.conn_details, font=('Arial', 9)).pack(anchor='w', pady=5)
        
        # llama-server settings
        llama_frame = ttk.LabelFrame(self.conn_frame, text="Configurazione llama-server", padding=10)
        llama_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(llama_frame, text="Comando llama-server:").grid(row=0, column=0, sticky='w', pady=5)
        self.llama_command = tk.StringVar(value="llama-server")
        ttk.Entry(llama_frame, textvariable=self.llama_command, width=50).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        ttk.Button(llama_frame, text="...", command=self.browse_llama, width=3).grid(row=0, column=2)
        ttk.Label(llama_frame, text="(lascia 'llama-server' se è nel PATH)", font=('Arial', 8)).grid(row=0, column=3, sticky='w', padx=5)
        
        ttk.Label(llama_frame, text="GPU Layers (-ngl):").grid(row=1, column=0, sticky='w', pady=5)
        self.gpu_layers = tk.StringVar(value="99")
        ttk.Spinbox(llama_frame, textvariable=self.gpu_layers, from_=0, to=999, width=10).grid(row=1, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(llama_frame, text="(99 = tutti i layer su GPU)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        llama_frame.columnconfigure(1, weight=1)
    
    def _create_models_tab(self):
        """Tab gestione modelli"""
        
        # Toolbar
        toolbar = ttk.Frame(self.models_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="📁 Seleziona Cartella Modelli", command=self._select_models_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🔄 Scansiona", command=self._scan_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🤗 Aggiungi HuggingFace", command=self._add_huggingface_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="☁️ Sincronizza con Server", command=self._sync_models).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🗑️ Rimuovi", command=self._remove_selected_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="🧹 Pulisci Vecchi", command=self._cleanup_old_models).pack(side=tk.LEFT, padx=5)
        
        # Info spazio disco
        disk_frame = ttk.LabelFrame(self.models_frame, text="📊 Spazio Disco", padding=5)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_info_var = tk.StringVar(value="Verificando spazio disco...")
        self.disk_info_label = ttk.Label(disk_frame, textvariable=self.disk_info_var, font=('Arial', 9))
        self.disk_info_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(disk_frame, text="🔄", command=self._update_disk_info, width=3).pack(side=tk.RIGHT, padx=5)
        
        # Cartella modelli
        folder_frame = ttk.Frame(self.models_frame)
        folder_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(folder_frame, text="Cartella modelli:").pack(side=tk.LEFT)
        self.models_folder = tk.StringVar(value="")
        ttk.Label(folder_frame, textvariable=self.models_folder, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        # Lista modelli con checkbox
        list_frame = ttk.LabelFrame(self.models_frame, text="Modelli Disponibili (Locali e HuggingFace)", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview per modelli
        columns = ('enabled', 'source', 'name', 'params', 'quant', 'size', 'vram', 'context')
        self.models_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.models_tree.heading('enabled', text='✓')
        self.models_tree.heading('source', text='Fonte')
        self.models_tree.heading('name', text='Nome')
        self.models_tree.heading('params', text='Parametri')
        self.models_tree.heading('quant', text='Quantiz.')
        self.models_tree.heading('size', text='Dimensione')
        self.models_tree.heading('vram', text='VRAM Min')
        self.models_tree.heading('context', text='Context')
        
        self.models_tree.column('enabled', width=30, anchor='center')
        self.models_tree.column('source', width=60, anchor='center')
        self.models_tree.column('name', width=180)
        self.models_tree.column('params', width=70, anchor='center')
        self.models_tree.column('quant', width=70, anchor='center')
        self.models_tree.column('size', width=70, anchor='center')
        self.models_tree.column('vram', width=70, anchor='center')
        self.models_tree.column('context', width=70, anchor='center')
        
        self.models_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.models_tree.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.models_tree.config(yscrollcommand=scrollbar.set)
        
        # Bind click per toggle
        self.models_tree.bind('<Double-1>', self._toggle_model)
        
        # Dettagli modello selezionato
        details_frame = ttk.LabelFrame(self.models_frame, text="Dettagli Modello", padding=5)
        details_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.model_details = tk.StringVar(value="Seleziona un modello per vedere i dettagli")
        ttk.Label(details_frame, textvariable=self.model_details, font=('Arial', 9)).pack(anchor='w')
        
        # Context length edit
        ctx_frame = ttk.Frame(details_frame)
        ctx_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(ctx_frame, text="Context Length:").pack(side=tk.LEFT)
        self.model_context = tk.StringVar(value="4096")
        ttk.Spinbox(ctx_frame, textvariable=self.model_context, from_=512, to=131072, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(ctx_frame, text="Applica", command=self._apply_context).pack(side=tk.LEFT)
        
        self.models_tree.bind('<<TreeviewSelect>>', self._on_model_select)
    
    def _create_sessions_tab(self):
        """Tab sessioni attive"""
        
        # Toolbar
        toolbar = ttk.Frame(self.sessions_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🔄 Aggiorna", command=self._refresh_sessions).pack(side=tk.LEFT, padx=5)
        
        # Statistiche
        stats_frame = ttk.LabelFrame(self.sessions_frame, text="Statistiche", padding=10)
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
            ('Sessioni Totali:', 'total_sessions'),
            ('Sessioni Attive:', 'active_sessions'),
            ('Richieste Completate:', 'completed_requests'),
            ('Token Generati:', 'total_tokens'),
            ('Guadagni:', 'earnings')
        ]
        
        for i, (label, key) in enumerate(labels):
            ttk.Label(stats_grid, text=label, font=('Arial', 9, 'bold')).grid(row=0, column=i*2, padx=10, pady=5)
            ttk.Label(stats_grid, textvariable=self.stats[key], font=('Arial', 9)).grid(row=0, column=i*2+1, padx=5, pady=5)
        
        # Lista sessioni
        list_frame = ttk.LabelFrame(self.sessions_frame, text="Sessioni Attive", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        columns = ('id', 'model', 'status', 'started', 'requests', 'tokens')
        self.sessions_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.sessions_tree.heading('id', text='ID Sessione')
        self.sessions_tree.heading('model', text='Modello')
        self.sessions_tree.heading('status', text='Stato')
        self.sessions_tree.heading('started', text='Avviata')
        self.sessions_tree.heading('requests', text='Richieste')
        self.sessions_tree.heading('tokens', text='Token')
        
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
        """Tab log"""
        
        toolbar = ttk.Frame(self.log_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Cancella Log", command=self._clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="💾 Salva Log", command=self._save_log).pack(side=tk.LEFT, padx=5)
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=20, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log_text.config(state='disabled')
    
    def _create_llm_tab(self):
        """Tab per visualizzare l'output LLM in tempo reale"""
        
        # Info frame
        info_frame = ttk.Frame(self.llm_frame)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_session_var = tk.StringVar(value="Nessuna sessione attiva")
        ttk.Label(info_frame, text="Sessione:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)
        ttk.Label(info_frame, textvariable=self.llm_session_var, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        self.llm_tokens_var = tk.StringVar(value="Token: 0")
        ttk.Label(info_frame, textvariable=self.llm_tokens_var, font=('Arial', 9)).pack(side=tk.RIGHT, padx=10)
        
        # Toolbar
        toolbar = ttk.Frame(self.llm_frame)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(toolbar, text="🗑️ Cancella", command=self._clear_llm_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="📋 Copia", command=self._copy_llm_output).pack(side=tk.LEFT, padx=5)
        
        self.llm_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.llm_autoscroll).pack(side=tk.LEFT, padx=10)
        
        # Prompt section
        prompt_frame = ttk.LabelFrame(self.llm_frame, text="📥 Prompt Ricevuto", padding=5)
        prompt_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llm_prompt_text = scrolledtext.ScrolledText(prompt_frame, height=4, font=('Consolas', 9), wrap=tk.WORD)
        self.llm_prompt_text.pack(fill=tk.X, expand=False)
        self.llm_prompt_text.config(state='disabled', bg='#2a2a3a', fg='#aaaaaa')
        
        # Output section
        output_frame = ttk.LabelFrame(self.llm_frame, text="📤 Output LLM (Token per Token)", padding=5)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.llm_output_text = scrolledtext.ScrolledText(output_frame, height=15, font=('Consolas', 10), wrap=tk.WORD)
        self.llm_output_text.pack(fill=tk.BOTH, expand=True)
        self.llm_output_text.config(state='disabled', bg='#1a1a2a', fg='#00ff00')
        
        # Token counter per sessione
        self.llm_token_count = 0

    def _clear_llm_output(self):
        """Cancella l'output LLM"""
        self.llm_prompt_text.config(state='normal')
        self.llm_prompt_text.delete('1.0', tk.END)
        self.llm_prompt_text.config(state='disabled')
        
        self.llm_output_text.config(state='normal')
        self.llm_output_text.delete('1.0', tk.END)
        self.llm_output_text.config(state='disabled')
        
        self.llm_token_count = 0
        self.llm_tokens_var.set("Token: 0")
        self.llm_session_var.set("Nessuna sessione attiva")
    
    def _copy_llm_output(self):
        """Copia l'output LLM negli appunti"""
        output = self.llm_output_text.get('1.0', tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.update_status("Output LLM copiato negli appunti")
    
    def llm_set_prompt(self, session_id, prompt):
        """Imposta il prompt visualizzato"""
        def update():
            self.llm_session_var.set(f"Sessione: {session_id}")
            self.llm_token_count = 0
            self.llm_tokens_var.set("Token: 0")
            
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
                self.llm_output_text.insert(tk.END, "\n\n--- Generazione completata ---\n")
                self.llm_output_text.config(state='disabled')
        
        self.root.after(0, update)
    
    def llm_session_ended(self, session_id):
        """Callback quando una sessione viene terminata dall'utente"""
        def update():
            self.llm_output_text.config(state='normal')
            self.llm_output_text.insert(tk.END, f"\n\n🛑 Sessione {session_id} terminata dall'utente.\n")
            self.llm_output_text.insert(tk.END, "Il modello è stato scaricato dalla memoria.\n")
            self.llm_output_text.config(state='disabled')
            
            if self.llm_autoscroll.get():
                self.llm_output_text.see(tk.END)
            
            # Reset stato prompt
            self.llm_prompt_text.config(state='normal')
            self.llm_prompt_text.delete('1.0', tk.END)
            self.llm_prompt_text.insert(tk.END, "(In attesa di nuova sessione...)")
            self.llm_prompt_text.config(state='disabled')
            
            # Reset token counter
            self.llm_token_count = 0
            self.llm_tokens_var.set("Token: 0")
        
        self.root.after(0, update)

    def _create_stats_tab(self):
        """Tab statistiche nodo"""
        
        # Frame principale con padding
        main_frame = ttk.Frame(self.stats_frame, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Titolo
        title_label = ttk.Label(main_frame, text="📈 Statistiche del Nodo", style='Header.TLabel', font=('Arial', 14, 'bold'))
        title_label.pack(pady=(0, 15))
        
        # Frame statistiche
        stats_container = ttk.LabelFrame(main_frame, text="Riepilogo", padding="15")
        stats_container.pack(fill=tk.X, pady=10)
        
        # Grid per statistiche
        self.stats_vars = {}
        stats_labels = [
            ('total_sessions', '🔗 Sessioni Totali', '0'),
            ('completed_sessions', '✅ Sessioni Completate', '0'),
            ('failed_sessions', '❌ Sessioni Fallite', '0'),
            ('total_requests', '📤 Richieste Elaborate', '0'),
            ('total_tokens', '🔤 Token Generati', '0'),
            ('total_minutes', '⏱️ Minuti di Attività', '0'),
            ('total_earned', '⚡ Satoshi Guadagnati', '0'),
            ('avg_tokens_sec', '🚀 Token/secondo (media)', '0.0'),
            ('avg_response_ms', '⏳ Tempo Risposta (media)', '0 ms'),
            ('first_online', '📅 Prima Connessione', '-'),
            ('last_online', '🕐 Ultima Attività', '-'),
            ('uptime_hours', '📊 Ore Totali Online', '0'),
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
        
        # Frame pulsanti
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=20)
        
        ttk.Button(btn_frame, text="🔄 Aggiorna Statistiche", command=self._load_stats).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📋 Copia Report", command=self._copy_stats_report).pack(side=tk.LEFT, padx=5)
        
        # Nota
        note_label = ttk.Label(main_frame, 
            text="ℹ️ Le statistiche vengono aggiornate automaticamente durante le sessioni.\n"
                 "   Clicca 'Aggiorna' per ottenere i dati più recenti dal server.",
            style='Info.TLabel', foreground='gray')
        note_label.pack(pady=10)
    
    # === Hardware Detection ===
    
    def _detect_hardware(self):
        """Rileva hardware del sistema"""
        self.update_status("Rilevamento hardware...")
        
        def detect():
            try:
                self.system_info = get_system_info()
                self.root.after(0, self._update_hw_display)
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Errore rilevamento hardware: {e}"))
        
        threading.Thread(target=detect, daemon=True).start()
    
    def _update_hw_display(self):
        """Aggiorna display hardware"""
        if not self.system_info:
            return
        
        # Aggiorna text area
        self.hw_text.config(state='normal')
        self.hw_text.delete('1.0', tk.END)
        self.hw_text.insert(tk.END, format_system_info(self.system_info))
        self.hw_text.config(state='disabled')
        
        # Aggiorna sommario
        info = self.system_info
        self.hw_summary['cpu'].set(info['cpu']['name'][:40] + '...' if len(info['cpu']['name']) > 40 else info['cpu']['name'])
        self.hw_summary['cores'].set(f"{info['cpu']['cores_physical']} fisici / {info['cpu']['cores_logical']} logici")
        self.hw_summary['ram'].set(f"{info['ram']['total_gb']} GB")
        
        if info['gpus']:
            gpu_names = ', '.join([g['name'] for g in info['gpus'][:2]])
            if len(info['gpus']) > 2:
                gpu_names += f" (+{len(info['gpus'])-2})"
            self.hw_summary['gpu'].set(gpu_names[:50])
            self.hw_summary['vram'].set(f"{info['total_vram_mb']} MB")
        else:
            self.hw_summary['gpu'].set("Nessuna GPU dedicata")
            self.hw_summary['vram'].set("-")
        
        self.hw_summary['max_model'].set(f"~{info['max_model_params_b']}B parametri (Q4)")
        
        self.update_status(f"Hardware rilevato: {len(info['gpus'])} GPU, {info['total_vram_mb']} MB VRAM")
        self.log(f"Hardware rilevato: CPU {info['cpu']['cores_logical']} core, {info['ram']['total_gb']} GB RAM, {len(info['gpus'])} GPU")
    
    def _copy_hw_info(self):
        """Copia info hardware negli appunti"""
        self.root.clipboard_clear()
        self.root.clipboard_append(format_system_info(self.system_info))
        self.update_status("Info hardware copiate negli appunti")
    
    # === Models Management ===
    
    def _select_models_folder(self):
        """Seleziona cartella modelli"""
        folder = filedialog.askdirectory(title="Seleziona cartella modelli GGUF")
        if folder:
            self.models_folder.set(folder)
            self._init_model_manager(folder)
            self._scan_models()
    
    def _init_model_manager(self, folder):
        """Inizializza model manager"""
        self.model_manager = ModelManager(folder)
    
    def _scan_models(self):
        """Scansiona modelli"""
        if not self.model_manager:
            folder = self.models_folder.get()
            if not folder:
                messagebox.showwarning("Attenzione", "Seleziona prima una cartella modelli")
                return
            self._init_model_manager(folder)
        
        self.update_status("Scansione modelli...")
        
        def scan():
            try:
                models = self.model_manager.scan_models()
                self.root.after(0, lambda: self._update_models_list(models))
                self.root.after(0, self._update_disk_info)  # Aggiorna anche spazio disco
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Errore scansione: {e}"))
        
        threading.Thread(target=scan, daemon=True).start()
    
    def _update_models_list(self, models):
        """Aggiorna lista modelli"""
        # Pulisci lista
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)
        
        # Aggiungi modelli
        for model in models:
            enabled = '✓' if model.enabled else '✗'
            # Indica se è HuggingFace o locale
            source = '🤗 HF' if getattr(model, 'is_huggingface', False) else '📁 Local'
            self.models_tree.insert('', 'end', iid=model.id, values=(
                enabled,
                source,
                model.name,
                model.parameters,
                model.quantization,
                f"{model.size_gb} GB",
                f"{model.min_vram_mb} MB",
                model.context_length
            ))
        
        self.update_status(f"Trovati {len(models)} modelli")
        self.log(f"Scansione completata: {len(models)} modelli trovati")
    
    def _toggle_model(self, event):
        """Toggle abilitazione modello"""
        item = self.models_tree.selection()
        if not item:
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                new_state = not model.enabled
                self.model_manager.set_model_enabled(model_id, new_state)
                
                # Aggiorna UI (prima colonna è enabled)
                enabled = '✓' if new_state else '✗'
                values = list(self.models_tree.item(model_id, 'values'))
                values[0] = enabled
                self.models_tree.item(model_id, values=values)
    
    def _on_model_select(self, event):
        """Selezione modello"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        model = self.model_manager.get_model_by_id(item[0])
        if model:
            if getattr(model, 'is_huggingface', False):
                details = f"🤗 HuggingFace: {model.hf_repo}\n"
            else:
                details = f"📁 File: {model.filename}\n"
            details += f"Architettura: {model.architecture}\n"
            details += f"VRAM: {model.min_vram_mb} MB min, {model.recommended_vram_mb} MB raccomandati"
            self.model_details.set(details)
            self.model_context.set(str(model.context_length))
    
    def _add_huggingface_model(self):
        """Apri dialog per aggiungere modello HuggingFace"""
        # Crea model_manager se non esiste (usa directory corrente per config)
        if not self.model_manager:
            self._init_model_manager(os.getcwd())
        
        dialog = HuggingFaceModelDialog(self.root, self.model_manager)
        if dialog.result:
            # Modello aggiunto, aggiorna lista
            if self.model_manager:
                models = list(self.model_manager.models.values())
                self._update_models_list(models)
                self.log(f"Aggiunto modello HuggingFace: {dialog.result.name}")
    
    def _remove_selected_model(self):
        """Rimuovi il modello selezionato"""
        item = self.models_tree.selection()
        if not item:
            messagebox.showwarning("Attenzione", "Seleziona un modello da rimuovere")
            return
        
        model_id = item[0]
        if self.model_manager:
            model = self.model_manager.get_model_by_id(model_id)
            if model:
                if messagebox.askyesno("Conferma", f"Rimuovere il modello '{model.name}' dalla lista?\n\n(Questo non elimina il file dal disco)"):
                    self.model_manager.remove_model(model_id)
                    self.models_tree.delete(model_id)
                    self.log(f"Rimosso modello: {model.name}")
    
    def _apply_context(self):
        """Applica context length"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        try:
            context = int(self.model_context.get())
            self.model_manager.set_model_context_length(item[0], context)
            
            # Aggiorna UI (context è ora la colonna 7, indice 7)
            values = list(self.models_tree.item(item[0], 'values'))
            values[7] = context
            self.models_tree.item(item[0], values=values)
            
            self.update_status(f"Context length aggiornato a {context}")
        except ValueError:
            messagebox.showerror("Errore", "Context length non valido")
    
    def _sync_models(self):
        """Sincronizza modelli con server"""
        if not self.client or not self.client.is_connected():
            messagebox.showwarning("Attenzione", "Connettiti prima al server")
            return
        
        if not self.model_manager:
            messagebox.showwarning("Attenzione", "Scansiona prima i modelli")
            return
        
        self.update_status("Sincronizzazione modelli...")
        
        def sync():
            try:
                models = self.model_manager.get_models_for_server()
                # Invia via WebSocket
                self.client.sync_models(models)
                self.root.after(0, lambda: self.update_status(f"Sincronizzati {len(models)} modelli"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Errore sync: {e}"))
        
        threading.Thread(target=sync, daemon=True).start()
    
    def _update_disk_info(self):
        """Aggiorna informazioni spazio disco"""
        if not self.model_manager:
            self.disk_info_var.set("Seleziona prima una cartella modelli")
            return
        
        status = self.model_manager.get_disk_space_status()
        
        status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
        status_text = (
            f"{status_icon} Libero: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
            f"Modelli: {status['models_size_gb']:.1f} GB"
        )
        self.disk_info_var.set(status_text)
        
        # Colore in base allo stato
        if status['status'] == 'critical':
            self.disk_info_label.config(foreground='red')
            # Avvisa l'utente
            if messagebox.askyesno("⚠️ Spazio Disco Critico",
                f"Spazio disco quasi esaurito: solo {status['free_gb']:.1f} GB liberi.\n\n"
                "Vuoi eliminare i modelli vecchi/non usati per liberare spazio?"):
                self._cleanup_old_models()
        elif status['status'] == 'warning':
            self.disk_info_label.config(foreground='orange')
        else:
            self.disk_info_label.config(foreground='green')
    
    def _cleanup_old_models(self):
        """Pulisci modelli vecchi/non usati"""
        if not self.model_manager:
            messagebox.showwarning("Attenzione", "Seleziona prima una cartella modelli")
            return
        
        # Ottieni modelli non usati
        unused = self.model_manager.get_unused_models(days_threshold=30)
        
        if not unused:
            messagebox.showinfo("Pulizia Modelli", "Non ci sono modelli da pulire.\n\nTutti i modelli sono stati usati negli ultimi 30 giorni.")
            return
        
        # Calcola spazio che si libererebbe
        total_size = sum(m.size_bytes for m in unused if not m.is_huggingface)
        total_size_gb = total_size / (1024 ** 3)
        
        # Mostra lista modelli
        models_list = "\n".join([f"• {m.name} ({m.size_gb:.2f} GB)" for m in unused[:10]])
        if len(unused) > 10:
            models_list += f"\n... e altri {len(unused) - 10} modelli"
        
        if messagebox.askyesno("🧹 Pulizia Modelli",
            f"Trovati {len(unused)} modelli non usati negli ultimi 30 giorni.\n\n"
            f"Modelli da eliminare:\n{models_list}\n\n"
            f"Spazio che verrà liberato: {total_size_gb:.2f} GB\n\n"
            "Vuoi eliminarli?"):
            
            deleted = []
            for model in unused:
                if not model.is_huggingface:  # Non eliminare modelli HF (non hanno file locale)
                    if self.model_manager.delete_model(model.id, delete_file=True):
                        deleted.append(model.name)
            
            # Aggiorna UI
            self._scan_models()
            self._update_disk_info()
            
            if deleted:
                messagebox.showinfo("Pulizia Completata",
                    f"Eliminati {len(deleted)} modelli:\n" + "\n".join([f"• {n}" for n in deleted[:10]]))
                self.log(f"Pulizia: eliminati {len(deleted)} modelli, liberati {total_size_gb:.2f} GB")
            else:
                messagebox.showinfo("Pulizia", "Nessun modello eliminato")
    
    # === Connection ===
    
    def _load_config(self):
        """Carica configurazione"""
        # Server fisso - usa IP diretto
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
        """Salva configurazione"""
        for section in ['Node', 'Server', 'LLM', 'Models', 'Account']:
            if section not in self.config:
                self.config[section] = {}
        
        # Server sempre fisso
        self.config['Server']['URL'] = "http://51.178.142.183:5000"
        self.config['Node']['name'] = self.node_name.get()
        self.config['Node']['token'] = self.token.get()
        self.config['Node']['price_per_minute'] = self.price_per_minute.get()
        self.config['LLM']['command'] = self.llama_command.get()
        self.config['LLM']['gpu_layers'] = self.gpu_layers.get()
        self.config['Models']['directory'] = self.models_folder.get()
        
        # Salva credenziali account (se esistono le variabili)
        if hasattr(self, 'login_username'):
            self.config['Account']['username'] = self.login_username.get()
        if hasattr(self, 'auth_token') and self.auth_token:
            self.config['Account']['token'] = self.auth_token
        
        with open(self.config_path, 'w') as f:
            self.config.write(f)
    
    def connect(self):
        """Connetti al server"""
        # Verifica login
        if not hasattr(self, 'logged_in') or not self.logged_in:
            messagebox.showwarning("Login richiesto", 
                "Devi effettuare il login prima di connettere il nodo.\n\n"
                "Vai alla tab 'Account' e accedi con le tue credenziali.")
            self.notebook.select(0)  # Vai alla tab Account
            return
        
        self._save_config()
        
        self.update_status("Connessione in corso...")
        self.connect_btn.config(state='disabled')
        self.log(f"Tentativo connessione a {self.server_url.get()}...")
        
        def do_connect():
            try:
                self.client = NodeClient(self.config_path)
                self.client.server_url = self.server_url.get()
                self.client.node_name = self.node_name.get()
                
                # Passa token autenticazione utente
                self.client.auth_token = self.auth_token
                self.client.user_id = self.user_info.get('user_id')
                
                # Collega callbacks GUI per visualizzare output LLM
                self.client.gui_prompt_callback = self.llm_set_prompt
                self.client.gui_token_callback = self.llm_add_token
                self.client.gui_session_ended_callback = self.llm_session_ended
                
                # Passa info hardware e modelli
                if self.system_info:
                    self.client.hardware_info = self.system_info
                if self.model_manager:
                    self.client.models = self.model_manager.get_models_for_server()
                    self.client.model_manager = self.model_manager  # For local file paths
                
                if self.client.connect():
                    self.root.after(0, self._on_connected)
                else:
                    self.root.after(0, lambda: self._on_connection_failed("Connessione fallita"))
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                self.root.after(0, lambda: self.log(f"Errore:\n{err}"))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
        
        threading.Thread(target=do_connect, daemon=True).start()
    
    def _on_connected(self):
        """Callback connessione riuscita"""
        self.conn_status.set("✓ Connesso al server")
        self.conn_indicator.config(text="● Connesso", style='Connected.TLabel')
        self.connect_btn.config(state='disabled')
        self.disconnect_btn.config(state='normal')
        self.conn_details.set(f"Server: {self.server_url.get()}")
        self.update_status("Connesso al server")
        self.log("Connessione stabilita!")
        
        # Sincronizza modelli automaticamente
        if self.model_manager and self.model_manager.models:
            self._sync_models()
    
    def _on_connection_failed(self, error):
        """Callback connessione fallita"""
        self.conn_status.set("✗ Non connesso")
        self.conn_indicator.config(text="● Disconnesso", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.update_status(f"Errore: {error}")
        messagebox.showerror("Errore Connessione", f"Connessione fallita:\n{error}")
    
    def disconnect(self):
        """Disconnetti"""
        if self.client:
            self.client.disconnect()
            self.client = None
        
        self.conn_status.set("Non connesso")
        self.conn_indicator.config(text="● Disconnesso", style='Disconnected.TLabel')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.conn_details.set("")
        self.update_status("Disconnesso")
        self.log("Disconnesso dal server")
    
    def browse_llama(self):
        """Sfoglia per llama-server (opzionale, può essere nel PATH)"""
        filetypes = [("Executable", "*.exe"), ("All files", "*.*")] if sys.platform == 'win32' else [("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.llama_command.set(path)
    
    # === Sessions ===
    
    def _refresh_sessions(self):
        """Aggiorna lista sessioni"""
        if not self.client:
            return
        # TODO: Implementare richiesta sessioni dal server
    
    # === Log ===
    
    def update_status(self, msg):
        """Aggiorna status bar"""
        self.status_var.set(msg)
    
    def log(self, msg):
        """Aggiungi al log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
    
    def _clear_log(self):
        """Cancella log"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')
    
    def _save_log(self):
        """Salva log su file"""
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.log_text.config(state='normal')
            with open(path, 'w') as f:
                f.write(self.log_text.get('1.0', tk.END))
            self.log_text.config(state='disabled')
            self.update_status(f"Log salvato in {path}")
    
    # === Statistiche ===
    
    def _load_stats(self):
        """Carica statistiche dal server"""
        if not self.client or not self.client.connected:
            messagebox.showwarning("Non connesso", "Devi essere connesso al server per caricare le statistiche.")
            return
        
        if requests is None:
            messagebox.showerror("Modulo mancante", "Il modulo 'requests' non è installato. Esegui: pip install requests")
            return
        
        # Ottieni node_id dal client
        node_id = getattr(self.client, 'node_id', None)
        if not node_id:
            messagebox.showwarning("ID Nodo mancante", "ID del nodo non disponibile. Riconnettiti al server.")
            return
        
        self.update_status("Caricamento statistiche...")
        
        def fetch_stats():
            try:
                server_url = self.client.server_url.replace('/socket.io', '')
                # Rimuovi trailing slashes
                server_url = server_url.rstrip('/')
                
                # Richiesta API statistiche
                response = requests.get(f"{server_url}/api/node/stats/{node_id}", timeout=10)
                
                if response.status_code == 200:
                    stats = response.json()
                    self.root.after(0, lambda: self._update_stats_display(stats))
                elif response.status_code == 404:
                    # Nessuna statistica ancora
                    self.root.after(0, lambda: self._update_stats_display({}))
                    self.root.after(0, lambda: self.log("Nessuna statistica disponibile (nodo nuovo)"))
                else:
                    self.root.after(0, lambda: self.log(f"Errore caricamento statistiche: {response.status_code}"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Errore caricamento statistiche: {e}"))
                self.root.after(0, lambda: self.update_status("Errore caricamento statistiche"))
        
        threading.Thread(target=fetch_stats, daemon=True).start()
    
    def _update_stats_display(self, stats):
        """Aggiorna display statistiche"""
        try:
            self.stats_vars['total_sessions'].set(str(stats.get('total_sessions', 0)))
            self.stats_vars['completed_sessions'].set(str(stats.get('completed_sessions', 0)))
            self.stats_vars['failed_sessions'].set(str(stats.get('failed_sessions', 0)))
            self.stats_vars['total_requests'].set(str(stats.get('total_requests', 0)))
            
            # Formatta token con separatori migliaia
            tokens = stats.get('total_tokens_generated', 0)
            self.stats_vars['total_tokens'].set(f"{tokens:,}".replace(',', '.'))
            
            # Formatta minuti
            minutes = stats.get('total_minutes_active', 0)
            if minutes >= 60:
                hours = minutes // 60
                mins = minutes % 60
                self.stats_vars['total_minutes'].set(f"{hours}h {mins}m")
            else:
                self.stats_vars['total_minutes'].set(f"{minutes} min")
            
            # Satoshi guadagnati
            sats = stats.get('total_earned_sats', 0)
            self.stats_vars['total_earned'].set(f"{sats:,} sats".replace(',', '.'))
            
            # Medie
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
            
            self.update_status("Statistiche aggiornate")
            self.log("Statistiche caricate dal server")
            
        except Exception as e:
            self.log(f"Errore aggiornamento display statistiche: {e}")
    
    def _copy_stats_report(self):
        """Copia report statistiche negli appunti"""
        report_lines = [
            "=" * 40,
            "  REPORT STATISTICHE NODO AI LIGHTNING",
            "=" * 40,
            "",
            f"📊 Sessioni Totali:        {self.stats_vars['total_sessions'].get()}",
            f"✅ Sessioni Completate:    {self.stats_vars['completed_sessions'].get()}",
            f"❌ Sessioni Fallite:       {self.stats_vars['failed_sessions'].get()}",
            "",
            f"📤 Richieste Elaborate:    {self.stats_vars['total_requests'].get()}",
            f"🔤 Token Generati:         {self.stats_vars['total_tokens'].get()}",
            f"⏱️ Tempo Attività:         {self.stats_vars['total_minutes'].get()}",
            "",
            f"⚡ Satoshi Guadagnati:     {self.stats_vars['total_earned'].get()}",
            "",
            f"🚀 Token/secondo (media):  {self.stats_vars['avg_tokens_sec'].get()}",
            f"⏳ Tempo Risposta (media): {self.stats_vars['avg_response_ms'].get()}",
            "",
            f"📅 Prima Connessione:      {self.stats_vars['first_online'].get()}",
            f"🕐 Ultima Attività:        {self.stats_vars['last_online'].get()}",
            f"📊 Ore Totali Online:      {self.stats_vars['uptime_hours'].get()}",
            "",
            "=" * 40,
            f"  Report generato: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            "=" * 40,
        ]
        
        report = "\n".join(report_lines)
        
        # Copia negli appunti
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.root.update()
        
        self.update_status("Report copiato negli appunti")
        messagebox.showinfo("Copiato", "Report statistiche copiato negli appunti!")
    
    # === Auto-Updater ===
    
    def _start_updater(self):
        """Avvia il controllo automatico degli aggiornamenti"""
        self.updater.start_checking(interval=3600)  # Ogni ora
        self._log("Auto-updater avviato")
    
    def _on_update_available(self, version, changelog, download_url):
        """Callback chiamato quando è disponibile un aggiornamento"""
        self.update_pending = True
        # Aggiorna UI dal thread principale
        self.root.after(0, lambda: self._show_update_notification(version, changelog))
    
    def _show_update_notification(self, version, changelog):
        """Mostra notifica di aggiornamento disponibile"""
        self._log(f"🔄 Aggiornamento disponibile: v{version}")
        self.status_var.set(f"Aggiornamento disponibile: v{version}")
        
        # Mostra dialog
        response = messagebox.askyesno(
            "Aggiornamento Disponibile",
            f"È disponibile la versione {version} di LightPhon Node.\n\n"
            f"Changelog:\n{changelog[:500]}...\n\n"
            f"Vuoi aggiornare ora?\n"
            f"(L'applicazione verrà riavviata)",
            icon='info'
        )
        
        if response:
            self._download_and_apply_update()
    
    def _download_and_apply_update(self):
        """Scarica e applica l'aggiornamento"""
        self._log("Scaricamento aggiornamento in corso...")
        self.status_var.set("Scaricamento aggiornamento...")
        
        def download_thread():
            try:
                # Progress callback
                def progress(downloaded, total):
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        self.root.after(0, lambda p=percent: self.status_var.set(f"Download: {p}%"))
                
                # Scarica
                update_path = self.updater.download_update(progress_callback=progress)
                
                if update_path:
                    self.root.after(0, lambda: self._apply_update(update_path))
                else:
                    self.root.after(0, lambda: self._update_failed("Download fallito"))
                    
            except Exception as e:
                self.root.after(0, lambda: self._update_failed(str(e)))
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def _apply_update(self, update_path):
        """Applica l'aggiornamento scaricato"""
        self._log(f"Applicazione aggiornamento da {update_path}...")
        
        response = messagebox.askyesno(
            "Applicare Aggiornamento",
            "L'aggiornamento è stato scaricato.\n"
            "L'applicazione verrà chiusa e riavviata.\n\n"
            "Continuare?",
            icon='question'
        )
        
        if response:
            # Disconnetti prima dell'aggiornamento
            if self.client:
                self.client.disconnect()
            
            # Applica update
            if self.updater.apply_update(update_path):
                self._log("Aggiornamento in corso, chiusura applicazione...")
                self.root.after(1000, self.root.destroy)
            else:
                self._update_failed("Impossibile applicare l'aggiornamento")
    
    def _update_failed(self, error):
        """Gestisce errore di aggiornamento"""
        self._log(f"❌ Aggiornamento fallito: {error}")
        self.status_var.set("Aggiornamento fallito")
        messagebox.showerror("Errore Aggiornamento", f"Impossibile aggiornare:\n{error}")
    
    def check_update_manual(self):
        """Controllo manuale degli aggiornamenti"""
        self._log("Controllo aggiornamenti...")
        self.status_var.set("Controllo aggiornamenti...")
        
        def check_thread():
            update = self.updater.check_for_updates()
            if update:
                self.root.after(0, lambda: self._show_update_notification(
                    update['version'], 
                    update.get('changelog', '')
                ))
            else:
                self.root.after(0, lambda: (
                    self._log("✓ Nessun aggiornamento disponibile"),
                    self.status_var.set(f"Versione {VERSION} è la più recente"),
                    messagebox.showinfo("Aggiornamenti", f"Stai usando la versione più recente (v{VERSION})")
                ))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    # === App Lifecycle ===
    
    def on_close(self):
        """Chiusura app"""
        self._save_config()
        # Ferma l'auto-updater
        if self.updater:
            self.updater.stop_checking()
        if self.client:
            self.client.disconnect()
        self.root.destroy()
    
    def run(self):
        """Avvia GUI"""
        self.root.mainloop()


class HuggingFaceModelDialog:
    """Dialog per aggiungere un modello HuggingFace"""
    
    def __init__(self, parent, model_manager):
        self.result = None
        self.model_manager = model_manager
        self.verified = False
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Aggiungi Modello HuggingFace")
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Istruzioni
        info_frame = ttk.LabelFrame(self.dialog, text="Istruzioni", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=10)
        
        info_text = """Inserisci il repository HuggingFace nel formato:
owner/repo:quantizzazione

Esempi:
• bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M
• unsloth/Llama-3.2-3B-Instruct-GGUF:Q4_K_M
• Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M

Il modello verrà scaricato automaticamente da HuggingFace quando avvii una sessione."""
        
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT, font=('Arial', 9)).pack(anchor='w')
        
        # Spazio disco
        disk_frame = ttk.LabelFrame(self.dialog, text="📊 Spazio Disco", padding=10)
        disk_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.disk_status_var = tk.StringVar(value="Verificando spazio disco...")
        self.disk_status_label = ttk.Label(disk_frame, textvariable=self.disk_status_var, font=('Arial', 9))
        self.disk_status_label.pack(anchor='w')
        
        # Aggiorna info disco
        self._update_disk_status()
        
        # Input
        input_frame = ttk.LabelFrame(self.dialog, text="Repository HuggingFace", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(input_frame, text="Repo (owner/model:quant):").pack(anchor='w')
        self.repo_var = tk.StringVar()
        self.repo_entry = ttk.Entry(input_frame, textvariable=self.repo_var, width=60)
        self.repo_entry.pack(fill=tk.X, pady=5)
        self.repo_entry.focus_set()
        
        # Bind per reset verifica quando cambia il testo
        self.repo_var.trace_add('write', self._on_repo_changed)
        
        ttk.Label(input_frame, text="Context Length:").pack(anchor='w', pady=(10, 0))
        self.context_var = tk.StringVar(value="4096")
        ttk.Spinbox(input_frame, textvariable=self.context_var, from_=512, to=131072, width=15).pack(anchor='w', pady=5)
        
        # Status verifica
        self.verify_status_var = tk.StringVar(value="")
        self.verify_status_label = ttk.Label(input_frame, textvariable=self.verify_status_var, font=('Arial', 9))
        self.verify_status_label.pack(anchor='w', pady=5)
        
        # Preset modelli popolari
        preset_frame = ttk.LabelFrame(self.dialog, text="Modelli Popolari (clicca per usare)", padding=10)
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
        
        # Bottoni
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill=tk.X, padx=10, pady=20)
        
        self.verify_btn = ttk.Button(btn_frame, text="🔍 Verifica Modello", command=self._verify_model, width=18)
        self.verify_btn.pack(side=tk.LEFT, padx=5)
        
        self.add_btn = ttk.Button(btn_frame, text="✅ Aggiungi", command=self._add_model, width=15, state='disabled')
        self.add_btn.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(btn_frame, text="Annulla", command=self.dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)
        
        # Bind Enter
        self.repo_entry.bind('<Return>', lambda e: self._verify_model())
        
        # Attendi chiusura
        self.dialog.wait_window()
    
    def _update_disk_status(self):
        """Aggiorna informazioni spazio disco"""
        if self.model_manager:
            status = self.model_manager.get_disk_space_status()
            status_icon = "✅" if status['status'] == 'ok' else "⚠️" if status['status'] == 'warning' else "❌"
            self.disk_status_var.set(
                f"{status_icon} Spazio libero: {status['free_gb']:.1f} GB / {status['total_gb']:.1f} GB | "
                f"Modelli: {status['models_size_gb']:.1f} GB"
            )
            
            if status['status'] == 'critical':
                self.disk_status_label.config(foreground='red')
            elif status['status'] == 'warning':
                self.disk_status_label.config(foreground='orange')
            else:
                self.disk_status_label.config(foreground='green')
    
    def _set_preset(self, repo):
        """Imposta un preset e resetta la verifica"""
        self.repo_var.set(repo)
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _on_repo_changed(self, *args):
        """Callback quando cambia il repo - resetta verifica"""
        self.verified = False
        self.add_btn.config(state='disabled')
        self.verify_status_var.set("")
    
    def _verify_model(self):
        """Verifica che il modello HuggingFace esista"""
        repo = self.repo_var.get().strip()
        if not repo:
            messagebox.showwarning("Attenzione", "Inserisci un repository HuggingFace", parent=self.dialog)
            return
        
        # Verifica formato base
        if '/' not in repo:
            messagebox.showwarning("Attenzione", 
                "Formato non valido. Usa: owner/repo:quantizzazione\nEs: bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M", 
                parent=self.dialog)
            return
        
        # Mostra stato verifica
        self.verify_status_var.set("🔄 Verificando repository su HuggingFace...")
        self.verify_btn.config(state='disabled')
        self.dialog.update()
        
        # Verifica in thread
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
                
                # Verifica che il repo esista su HuggingFace
                api_url = f"https://huggingface.co/api/models/{repo_name}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    model_id = data.get('id', repo_name)
                    
                    # Controlla se ci sono file GGUF
                    siblings = data.get('siblings', [])
                    gguf_files = [f for f in siblings if f.get('rfilename', '').endswith('.gguf')]
                    
                    if gguf_files:
                        # Trova file con la quantizzazione specificata
                        if quant:
                            matching = [f for f in gguf_files if quant.upper() in f.get('rfilename', '').upper()]
                            if matching:
                                file_info = matching[0]
                                size_bytes = file_info.get('size', 0)
                                size_gb = size_bytes / (1024**3) if size_bytes else 0
                                
                                self.dialog.after(0, lambda: self._verify_success(
                                    f"✅ Modello trovato: {model_id}\n"
                                    f"   File: {file_info.get('rfilename', 'N/A')}\n"
                                    f"   Dimensione: {size_gb:.2f} GB"
                                ))
                            else:
                                self.dialog.after(0, lambda: self._verify_warning(
                                    f"⚠️ Repository trovato ma quantizzazione '{quant}' non trovata.\n"
                                    f"   File GGUF disponibili: {len(gguf_files)}"
                                ))
                        else:
                            self.dialog.after(0, lambda: self._verify_success(
                                f"✅ Modello trovato: {model_id}\n"
                                f"   File GGUF disponibili: {len(gguf_files)}"
                            ))
                    else:
                        self.dialog.after(0, lambda: self._verify_error(
                            f"❌ Repository trovato ma non contiene file GGUF"
                        ))
                elif response.status_code == 404:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ Repository non trovato: {repo_name}"
                    ))
                else:
                    self.dialog.after(0, lambda: self._verify_error(
                        f"❌ Errore HuggingFace: HTTP {response.status_code}"
                    ))
                    
            except requests.exceptions.Timeout:
                self.dialog.after(0, lambda: self._verify_error(
                    "❌ Timeout: HuggingFace non risponde"
                ))
            except Exception as e:
                self.dialog.after(0, lambda: self._verify_error(
                    f"❌ Errore: {str(e)}"
                ))
        
        threading.Thread(target=verify_thread, daemon=True).start()
    
    def _verify_success(self, message):
        """Verifica riuscita"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='green')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')
        self.verified = True
    
    def _verify_warning(self, message):
        """Verifica con warning"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='orange')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='normal')  # Permetti comunque di aggiungere
        self.verified = True
    
    def _verify_error(self, message):
        """Verifica fallita"""
        self.verify_status_var.set(message)
        self.verify_status_label.config(foreground='red')
        self.verify_btn.config(state='normal')
        self.add_btn.config(state='disabled')
        self.verified = False
    
    def _add_model(self):
        """Aggiungi il modello"""
        if not self.verified:
            messagebox.showwarning("Attenzione", 
                "Prima verifica che il modello esista cliccando '🔍 Verifica Modello'", 
                parent=self.dialog)
            return
        
        repo = self.repo_var.get().strip()
        
        # Controlla spazio disco
        if self.model_manager:
            disk_status = self.model_manager.get_disk_space_status()
            if disk_status['status'] == 'critical':
                if not messagebox.askyesno("Spazio Disco Critico",
                    f"Spazio disco quasi esaurito ({disk_status['free_gb']:.1f} GB liberi).\n\n"
                    "Vuoi continuare comunque?",
                    parent=self.dialog):
                    return
        
        try:
            context = int(self.context_var.get())
        except ValueError:
            context = 4096
        
        if self.model_manager:
            self.result = self.model_manager.add_huggingface_model(repo, context)
            if self.result:
                messagebox.showinfo("Successo", 
                    f"Modello aggiunto: {self.result.name}\n\n"
                    "Il modello sarà scaricato automaticamente quando avvii una sessione.\n"
                    "NOTA: Il download potrebbe richiedere diversi minuti.",
                    parent=self.dialog)
                self.dialog.destroy()
            else:
                messagebox.showerror("Errore", "Impossibile aggiungere il modello", parent=self.dialog)
        else:
            messagebox.showerror("Errore", "Model Manager non inizializzato", parent=self.dialog)


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

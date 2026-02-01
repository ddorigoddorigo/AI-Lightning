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

# Aggiungi path per imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from node_client import NodeClient, detect_gpu, find_llama_binary
from hardware_detect import get_system_info, format_system_info
from model_manager import ModelManager, ModelInfo


class NodeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Lightning Node - Host GPU")
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
        
        # Style
        style = ttk.Style()
        style.configure('Connected.TLabel', foreground='green', font=('Arial', 12, 'bold'))
        style.configure('Disconnected.TLabel', foreground='red', font=('Arial', 12, 'bold'))
        style.configure('Header.TLabel', font=('Arial', 10, 'bold'))
        style.configure('Info.TLabel', font=('Arial', 9))
        
        self._create_ui()
        self._load_config()
        
        # Rileva hardware all'avvio
        self.root.after(100, self._detect_hardware)
    
    def _create_ui(self):
        """Crea l'interfaccia"""
        
        # Notebook per tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
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
        
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar(value="Avvio in corso...")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.status_label.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        self.conn_indicator = ttk.Label(status_frame, text="● Disconnesso", style='Disconnected.TLabel')
        self.conn_indicator.pack(side=tk.RIGHT, padx=10)
        
        # Salva config alla chiusura
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
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
        
        # Server settings
        server_frame = ttk.LabelFrame(self.conn_frame, text="Impostazioni Server", padding=10)
        server_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(server_frame, text="URL Server:").grid(row=0, column=0, sticky='w', pady=5)
        self.server_url = tk.StringVar(value="http://vps-eecab539.vps.ovh.net")
        ttk.Entry(server_frame, textvariable=self.server_url, width=50).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        
        ttk.Label(server_frame, text="Nome Nodo:").grid(row=1, column=0, sticky='w', pady=5)
        self.node_name = tk.StringVar(value="")
        ttk.Entry(server_frame, textvariable=self.node_name, width=50).grid(row=1, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(opzionale, per identificare il nodo)", font=('Arial', 8)).grid(row=1, column=2, sticky='w')
        
        ttk.Label(server_frame, text="Token:").grid(row=2, column=0, sticky='w', pady=5)
        self.token = tk.StringVar()
        ttk.Entry(server_frame, textvariable=self.token, width=50, show='*').grid(row=2, column=1, padx=10, pady=5, sticky='ew')
        ttk.Label(server_frame, text="(opzionale, per autenticazione)", font=('Arial', 8)).grid(row=2, column=2, sticky='w')
        
        server_frame.columnconfigure(1, weight=1)
        
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
        
        # llama.cpp settings
        llama_frame = ttk.LabelFrame(self.conn_frame, text="Configurazione llama.cpp", padding=10)
        llama_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(llama_frame, text="Percorso llama-server:").grid(row=0, column=0, sticky='w', pady=5)
        self.llama_path = tk.StringVar()
        ttk.Entry(llama_frame, textvariable=self.llama_path, width=50).grid(row=0, column=1, padx=10, pady=5, sticky='ew')
        ttk.Button(llama_frame, text="...", command=self.browse_llama, width=3).grid(row=0, column=2)
        
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
        ttk.Button(toolbar, text="☁️ Sincronizza con Server", command=self._sync_models).pack(side=tk.LEFT, padx=5)
        
        # Cartella modelli
        folder_frame = ttk.Frame(self.models_frame)
        folder_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(folder_frame, text="Cartella modelli:").pack(side=tk.LEFT)
        self.models_folder = tk.StringVar(value="")
        ttk.Label(folder_frame, textvariable=self.models_folder, font=('Arial', 9)).pack(side=tk.LEFT, padx=10)
        
        # Lista modelli con checkbox
        list_frame = ttk.LabelFrame(self.models_frame, text="Modelli Disponibili", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Treeview per modelli
        columns = ('enabled', 'name', 'params', 'quant', 'size', 'vram', 'context')
        self.models_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        
        self.models_tree.heading('enabled', text='✓')
        self.models_tree.heading('name', text='Nome')
        self.models_tree.heading('params', text='Parametri')
        self.models_tree.heading('quant', text='Quantiz.')
        self.models_tree.heading('size', text='Dimensione')
        self.models_tree.heading('vram', text='VRAM Min')
        self.models_tree.heading('context', text='Context')
        
        self.models_tree.column('enabled', width=30, anchor='center')
        self.models_tree.column('name', width=200)
        self.models_tree.column('params', width=80, anchor='center')
        self.models_tree.column('quant', width=80, anchor='center')
        self.models_tree.column('size', width=80, anchor='center')
        self.models_tree.column('vram', width=80, anchor='center')
        self.models_tree.column('context', width=80, anchor='center')
        
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
            self.models_tree.insert('', 'end', iid=model.id, values=(
                enabled,
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
                
                # Aggiorna UI
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
            details = f"File: {model.filename}\n"
            details += f"Architettura: {model.architecture}\n"
            details += f"VRAM: {model.min_vram_mb} MB min, {model.recommended_vram_mb} MB raccomandati"
            self.model_details.set(details)
            self.model_context.set(str(model.context_length))
    
    def _apply_context(self):
        """Applica context length"""
        item = self.models_tree.selection()
        if not item or not self.model_manager:
            return
        
        try:
            context = int(self.model_context.get())
            self.model_manager.set_model_context_length(item[0], context)
            
            # Aggiorna UI
            values = list(self.models_tree.item(item[0], 'values'))
            values[6] = context
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
    
    # === Connection ===
    
    def _load_config(self):
        """Carica configurazione"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            
            self.server_url.set(self.config.get('Server', 'URL', fallback='http://vps-eecab539.vps.ovh.net'))
            self.node_name.set(self.config.get('Node', 'name', fallback=''))
            self.token.set(self.config.get('Node', 'token', fallback=''))
            self.llama_path.set(self.config.get('LLM', 'bin', fallback=''))
            self.gpu_layers.set(self.config.get('LLM', 'gpu_layers', fallback='99'))
            
            models_dir = self.config.get('Models', 'directory', fallback='')
            if models_dir:
                self.models_folder.set(models_dir)
                self._init_model_manager(models_dir)
        else:
            # Auto-rileva llama.cpp
            llama_bin = find_llama_binary()
            if llama_bin:
                self.llama_path.set(llama_bin)
    
    def _save_config(self):
        """Salva configurazione"""
        for section in ['Node', 'Server', 'LLM', 'Models']:
            if section not in self.config:
                self.config[section] = {}
        
        self.config['Server']['URL'] = self.server_url.get()
        self.config['Node']['name'] = self.node_name.get()
        self.config['Node']['token'] = self.token.get()
        self.config['LLM']['bin'] = self.llama_path.get()
        self.config['LLM']['gpu_layers'] = self.gpu_layers.get()
        self.config['Models']['directory'] = self.models_folder.get()
        
        with open(self.config_path, 'w') as f:
            self.config.write(f)
    
    def connect(self):
        """Connetti al server"""
        self._save_config()
        
        self.update_status("Connessione in corso...")
        self.connect_btn.config(state='disabled')
        self.log(f"Tentativo connessione a {self.server_url.get()}...")
        
        def do_connect():
            try:
                self.client = NodeClient(self.config_path)
                self.client.server_url = self.server_url.get()
                self.client.node_name = self.node_name.get()
                
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
        """Sfoglia per llama-server"""
        filetypes = [("Executable", "*.exe"), ("All files", "*.*")] if sys.platform == 'win32' else [("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.llama_path.set(path)
    
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
    
    # === App Lifecycle ===
    
    def on_close(self):
        """Chiusura app"""
        self._save_config()
        if self.client:
            self.client.disconnect()
        self.root.destroy()
    
    def run(self):
        """Avvia GUI"""
        self.root.mainloop()


if __name__ == '__main__':
    app = NodeGUI()
    app.run()

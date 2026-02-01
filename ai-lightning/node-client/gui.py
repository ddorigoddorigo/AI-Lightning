"""
AI Lightning Node Client - GUI

Interfaccia grafica per il nodo host.
"""
import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from configparser import ConfigParser

# Aggiungi path per imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from node_client import NodeClient, detect_gpu, find_llama_binary

class NodeGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Lightning Node")
        self.root.geometry("600x500")
        self.root.resizable(True, True)
        
        # Icona (se disponibile)
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass
        
        self.client = None
        self.config_path = 'config.ini'
        self.config = ConfigParser()
        
        self._create_ui()
        self._load_config()
        
        # Rileva GPU
        self.gpu_type = detect_gpu()
        self.update_status(f"GPU rilevata: {self.gpu_type.upper()}")
    
    def _create_ui(self):
        """Crea l'interfaccia"""
        
        # Notebook per tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab Connessione
        self.conn_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.conn_frame, text="Connessione")
        
        # Server URL
        ttk.Label(self.conn_frame, text="Server URL:").grid(row=0, column=0, sticky='w', padx=10, pady=5)
        self.server_url = tk.StringVar(value="http://localhost:5000")
        ttk.Entry(self.conn_frame, textvariable=self.server_url, width=50).grid(row=0, column=1, padx=10, pady=5)
        
        # Token
        ttk.Label(self.conn_frame, text="Token (opzionale):").grid(row=1, column=0, sticky='w', padx=10, pady=5)
        self.token = tk.StringVar()
        ttk.Entry(self.conn_frame, textvariable=self.token, width=50).grid(row=1, column=1, padx=10, pady=5)
        
        # Bottoni connessione
        btn_frame = ttk.Frame(self.conn_frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=20)
        
        self.connect_btn = ttk.Button(btn_frame, text="Connetti", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnetti", command=self.disconnect, state='disabled')
        self.disconnect_btn.pack(side=tk.LEFT, padx=5)
        
        # Stato connessione
        self.conn_status = tk.StringVar(value="Non connesso")
        ttk.Label(self.conn_frame, textvariable=self.conn_status, font=('Arial', 12, 'bold')).grid(row=3, column=0, columnspan=2, pady=10)
        
        # Tab Modelli
        self.models_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.models_frame, text="Modelli")
        
        # Lista modelli
        ttk.Label(self.models_frame, text="Modelli configurati:").pack(anchor='w', padx=10, pady=5)
        
        self.models_list = tk.Listbox(self.models_frame, height=6)
        self.models_list.pack(fill=tk.X, padx=10, pady=5)
        
        # Bottoni modelli
        model_btn_frame = ttk.Frame(self.models_frame)
        model_btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(model_btn_frame, text="Aggiungi Modello", command=self.add_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(model_btn_frame, text="Rimuovi", command=self.remove_model).pack(side=tk.LEFT, padx=5)
        
        # llama.cpp path
        ttk.Label(self.models_frame, text="Percorso llama-server:").pack(anchor='w', padx=10, pady=(20, 5))
        
        llama_frame = ttk.Frame(self.models_frame)
        llama_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.llama_path = tk.StringVar()
        ttk.Entry(llama_frame, textvariable=self.llama_path, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(llama_frame, text="Sfoglia", command=self.browse_llama).pack(side=tk.RIGHT, padx=5)
        
        # GPU Layers
        ttk.Label(self.models_frame, text="GPU Layers (-ngl):").pack(anchor='w', padx=10, pady=(20, 5))
        self.gpu_layers = tk.StringVar(value="99")
        ttk.Entry(self.models_frame, textvariable=self.gpu_layers, width=10).pack(anchor='w', padx=10)
        ttk.Label(self.models_frame, text="(99 = tutti su GPU, 0 = solo CPU)", font=('Arial', 8)).pack(anchor='w', padx=10)
        
        # Tab Sessioni
        self.sessions_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.sessions_frame, text="Sessioni Attive")
        
        # Lista sessioni
        self.sessions_tree = ttk.Treeview(self.sessions_frame, columns=('ID', 'Modello', 'Stato'), show='headings', height=10)
        self.sessions_tree.heading('ID', text='Session ID')
        self.sessions_tree.heading('Modello', text='Modello')
        self.sessions_tree.heading('Stato', text='Stato')
        self.sessions_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab Log
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="Log")
        
        self.log_text = tk.Text(self.log_frame, height=15, state='disabled')
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Status bar
        self.status_var = tk.StringVar(value="Pronto")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Salva config alla chiusura
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _load_config(self):
        """Carica configurazione"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path)
            
            self.server_url.set(self.config.get('Server', 'URL', fallback='http://localhost:5000'))
            self.token.set(self.config.get('Node', 'token', fallback=''))
            self.llama_path.set(self.config.get('LLM', 'bin', fallback=''))
            self.gpu_layers.set(self.config.get('LLM', 'gpu_layers', fallback='99'))
            
            # Carica modelli
            self.models_list.delete(0, tk.END)
            for section in self.config.sections():
                if section.startswith('Model:'):
                    name = section[6:]
                    path = self.config.get(section, 'path', fallback='')
                    self.models_list.insert(tk.END, f"{name}: {path}")
        else:
            # Auto-rileva llama.cpp
            llama_bin = find_llama_binary()
            if llama_bin:
                self.llama_path.set(llama_bin)
    
    def _save_config(self):
        """Salva configurazione"""
        if 'Node' not in self.config:
            self.config['Node'] = {}
        if 'Server' not in self.config:
            self.config['Server'] = {}
        if 'LLM' not in self.config:
            self.config['LLM'] = {}
        
        self.config['Server']['URL'] = self.server_url.get()
        self.config['Node']['token'] = self.token.get()
        self.config['LLM']['bin'] = self.llama_path.get()
        self.config['LLM']['gpu_layers'] = self.gpu_layers.get()
        
        with open(self.config_path, 'w') as f:
            self.config.write(f)
    
    def update_status(self, msg):
        """Aggiorna status bar"""
        self.status_var.set(msg)
        self.log(msg)
    
    def log(self, msg):
        """Aggiungi al log"""
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
    
    def connect(self):
        """Connetti al server"""
        self._save_config()
        
        self.update_status("Connessione in corso...")
        self.connect_btn.config(state='disabled')
        
        def do_connect():
            try:
                self.client = NodeClient(self.config_path)
                self.client.server_url = self.server_url.get()
                
                if self.client.connect():
                    self.root.after(0, self._on_connected)
                else:
                    self.root.after(0, lambda: self._on_connection_failed("Connessione fallita"))
            except Exception as e:
                self.root.after(0, lambda: self._on_connection_failed(str(e)))
        
        threading.Thread(target=do_connect, daemon=True).start()
    
    def _on_connected(self):
        """Callback connessione riuscita"""
        self.conn_status.set("✓ Connesso")
        self.connect_btn.config(state='disabled')
        self.disconnect_btn.config(state='normal')
        self.update_status("Connesso al server")
    
    def _on_connection_failed(self, error):
        """Callback connessione fallita"""
        self.conn_status.set("✗ Non connesso")
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.update_status(f"Errore: {error}")
        messagebox.showerror("Errore", f"Connessione fallita:\n{error}")
    
    def disconnect(self):
        """Disconnetti"""
        if self.client:
            self.client.disconnect()
            self.client = None
        
        self.conn_status.set("Non connesso")
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.update_status("Disconnesso")
    
    def add_model(self):
        """Aggiungi un modello"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Aggiungi Modello")
        dialog.geometry("500x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Nome modello:").grid(row=0, column=0, sticky='w', padx=10, pady=5)
        name_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=name_var, width=40).grid(row=0, column=1, padx=10, pady=5)
        
        ttk.Label(dialog, text="Percorso file .gguf:").grid(row=1, column=0, sticky='w', padx=10, pady=5)
        path_var = tk.StringVar()
        path_entry = ttk.Entry(dialog, textvariable=path_var, width=40)
        path_entry.grid(row=1, column=1, padx=10, pady=5)
        
        def browse():
            path = filedialog.askopenfilename(
                filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")]
            )
            if path:
                path_var.set(path)
        
        ttk.Button(dialog, text="...", command=browse, width=3).grid(row=1, column=2, padx=5)
        
        ttk.Label(dialog, text="Context size:").grid(row=2, column=0, sticky='w', padx=10, pady=5)
        context_var = tk.StringVar(value="2048")
        ttk.Entry(dialog, textvariable=context_var, width=10).grid(row=2, column=1, sticky='w', padx=10, pady=5)
        
        def save():
            name = name_var.get().strip()
            path = path_var.get().strip()
            context = context_var.get().strip()
            
            if not name or not path:
                messagebox.showwarning("Attenzione", "Inserisci nome e percorso")
                return
            
            section = f"Model:{name}"
            if section not in self.config:
                self.config[section] = {}
            self.config[section]['path'] = path
            self.config[section]['context'] = context
            
            self._save_config()
            self.models_list.insert(tk.END, f"{name}: {path}")
            dialog.destroy()
        
        ttk.Button(dialog, text="Salva", command=save).grid(row=3, column=1, pady=20)
    
    def remove_model(self):
        """Rimuovi modello selezionato"""
        selection = self.models_list.curselection()
        if not selection:
            return
        
        item = self.models_list.get(selection[0])
        name = item.split(':')[0]
        
        section = f"Model:{name}"
        if section in self.config:
            self.config.remove_section(section)
            self._save_config()
        
        self.models_list.delete(selection[0])
    
    def browse_llama(self):
        """Sfoglia per llama-server"""
        if sys.platform == 'win32':
            filetypes = [("Executable", "*.exe"), ("All files", "*.*")]
        else:
            filetypes = [("All files", "*.*")]
        
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.llama_path.set(path)
    
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

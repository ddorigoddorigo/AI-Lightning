/**
 * AI Lightning - Web Client
 * 
 * Client per accesso AI decentralizzato con Lightning Network
 */

// ===========================================
// State
// ===========================================
let socket = null;
let authToken = localStorage.getItem('authToken');
let currentSession = localStorage.getItem('sessionId');
let selectedModel = null;
let availableModels = [];
let onlineNodes = [];
let isWaitingForResponse = false;

// ===========================================
// Initialization
// ===========================================
document.addEventListener('DOMContentLoaded', () => {
    // Carica info rete (disponibile anche senza login)
    loadNetworkInfo();
    
    if (authToken) {
        connectSocket();
        showMain();
        loadModels();
    } else {
        showAuth();
    }
    
    // Refresh periodico network status
    setInterval(loadNetworkInfo, 30000);
});

// ===========================================
// Network Info (Public API)
// ===========================================
async function loadNetworkInfo() {
    try {
        const [modelsRes, nodesRes] = await Promise.all([
            fetch('/api/models/available'),
            fetch('/api/nodes/online')
        ]);
        
        if (modelsRes.ok) {
            const data = await modelsRes.json();
            availableModels = data.models || [];
            updateNetworkStatus(data.total_nodes_online, availableModels.length);
        }
        
        if (nodesRes.ok) {
            const data = await nodesRes.json();
            onlineNodes = data.nodes || [];
            updateNetworkPanel(onlineNodes);
        }
    } catch (error) {
        console.error('Error loading network info:', error);
        updateNetworkStatus(0, 0);
    }
}

function updateNetworkStatus(nodes, models) {
    const statusDot = document.querySelector('.status-dot');
    const nodesCount = document.getElementById('nodes-count');
    
    if (statusDot && nodesCount) {
        if (nodes > 0) {
            statusDot.classList.add('online');
            nodesCount.textContent = `${nodes} node${nodes > 1 ? 's' : ''} online`;
        } else {
            statusDot.classList.remove('online');
            nodesCount.textContent = 'No nodes online';
        }
    }
}

function updateNetworkPanel(nodes) {
    const totalNodesEl = document.getElementById('total-nodes');
    const totalModelsEl = document.getElementById('total-models');
    const totalVramEl = document.getElementById('total-vram');
    
    if (totalNodesEl) totalNodesEl.textContent = nodes.length;
    if (totalModelsEl) totalModelsEl.textContent = availableModels.length;
    
    const totalVram = nodes.reduce((sum, n) => sum + (n.hardware?.total_vram_mb || 0), 0);
    if (totalVramEl) totalVramEl.textContent = (totalVram / 1024).toFixed(1) + ' GB';
}

// ===========================================
// Authentication
// ===========================================
function showAuth() {
    document.getElementById('auth-section').style.display = 'block';
    document.getElementById('main-section').style.display = 'none';
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('register-form').style.display = 'none';
}

function showLoginForm() {
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('register-form').style.display = 'none';
}

function showRegister() {
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('register-form').style.display = 'block';
}

async function login() {
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;

    if (!username || !password) {
        showError('Please enter username and password');
        return;
    }

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });

        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Login failed');
        }

        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        connectSocket();
        showMain();
        loadModels();
    } catch (error) {
        showError(error.message);
    }
}

async function register() {
    const username = document.getElementById('reg-username').value.trim();
    const password = document.getElementById('reg-password').value;

    if (!username || !password) {
        showError('Please enter username and password');
        return;
    }
    
    if (password.length < 8) {
        showError('Password must be at least 8 characters');
        return;
    }

    try {
        const response = await fetch('/api/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });

        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Registration failed');
        }

        showSuccess('Registration successful! Please login.');
        showLoginForm();
    } catch (error) {
        showError(error.message);
    }
}

function logout() {
    authToken = null;
    currentSession = null;
    localStorage.removeItem('authToken');
    localStorage.removeItem('sessionId');
    if (socket) socket.disconnect();
    showAuth();
}

function showMain() {
    document.getElementById('auth-section').style.display = 'none';
    document.getElementById('main-section').style.display = 'block';
    document.getElementById('models-section').style.display = 'block';
    document.getElementById('session-config').style.display = 'none';
    document.getElementById('invoice-section').style.display = 'none';
    document.getElementById('chat-section').style.display = 'none';
    
    // Carica info utente incluso balance
    loadUserProfile();
}

// ===========================================
// User Profile & Balance
// ===========================================
async function loadUserProfile() {
    try {
        const response = await fetch('/api/me', {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                // Token scaduto
                logout();
                return;
            }
            throw new Error('Failed to load profile');
        }
        
        const data = await response.json();
        
        // Aggiorna UI
        document.getElementById('user-info').textContent = `Welcome, ${data.username}!`;
        updateBalanceDisplay(data.balance);
        
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

function updateBalanceDisplay(balance) {
    const balanceEl = document.getElementById('balance-amount');
    if (balanceEl) {
        balanceEl.textContent = balance.toLocaleString();
        
        // Colore in base al balance
        const container = document.getElementById('user-balance');
        if (container) {
            container.classList.remove('low', 'ok', 'good');
            if (balance < 100) {
                container.classList.add('low');
            } else if (balance < 1000) {
                container.classList.add('ok');
            } else {
                container.classList.add('good');
            }
        }
    }
}

async function addTestBalance() {
    try {
        const response = await fetch('/api/add_test_balance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ amount: 10000 })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            // Se token scaduto/invalido, forza logout
            if (response.status === 401 || response.status === 422 || data.code === 'token_expired') {
                showError('Session expired. Please login again.');
                logout();
                return;
            }
            throw new Error(data.error || 'Failed to add balance');
        }
        
        showSuccess(data.message);
        updateBalanceDisplay(data.new_balance);
        
    } catch (error) {
        showError(error.message);
    }
}

// ===========================================
// Models
// ===========================================
async function loadModels() {
    const grid = document.getElementById('models-grid');
    const loading = document.getElementById('models-loading');
    
    if (loading) loading.style.display = 'block';
    if (grid) grid.innerHTML = '';
    
    try {
        const response = await fetch('/api/models/available');
        const data = await response.json();
        
        availableModels = data.models || [];
        if (loading) loading.style.display = 'none';
        
        if (availableModels.length === 0) {
            if (grid) grid.innerHTML = '<div class="no-models">No models available. Waiting for nodes to connect...</div>';
            return;
        }
        
        renderModelsGrid(availableModels);
        
    } catch (error) {
        if (loading) loading.style.display = 'none';
        if (grid) grid.innerHTML = '<div class="error">Failed to load models. <a href="#" onclick="loadModels()">Retry</a></div>';
    }
}

function renderModelsGrid(models) {
    const grid = document.getElementById('models-grid');
    if (!grid) return;
    grid.innerHTML = '';
    
    models.forEach(model => {
        const card = document.createElement('div');
        card.className = 'model-card';
        card.onclick = () => selectModel(model);
        
        // Determina icona in base all'architettura
        const icons = {
            'llama': '🦙',
            'mistral': '🌪️',
            'phi': 'φ',
            'qwen': '🐼',
            'deepseek': '🔍',
            'gemma': '💎',
            'codellama': '💻',
            'default': '🧠'
        };
        const icon = icons[model.architecture] || icons.default;
        
        // Badge disponibilità
        const availBadge = model.nodes_count > 1 
            ? `<span class="badge badge-green">${model.nodes_count} nodes</span>`
            : `<span class="badge badge-yellow">1 node</span>`;
        
        card.innerHTML = `
            <div class="model-icon">${icon}</div>
            <div class="model-name">${model.name}</div>
            <div class="model-info">
                <span class="param">${model.parameters}</span>
                <span class="quant">${model.quantization}</span>
            </div>
            <div class="model-specs">
                <span>Context: ${(model.context_length || 4096).toLocaleString()}</span>
                <span>VRAM: ${model.min_vram_mb ? (model.min_vram_mb/1024).toFixed(1) + 'GB' : '?'}</span>
            </div>
            <div class="model-availability">${availBadge}</div>
        `;
        
        grid.appendChild(card);
    });
}

function refreshModels() {
    loadModels();
    loadNetworkInfo();
}

function selectModel(model) {
    selectedModel = model;
    
    document.getElementById('models-section').style.display = 'none';
    document.getElementById('session-config').style.display = 'block';
    document.getElementById('selected-model-name').textContent = model.name;
    
    updateEstimatedCost();
}

function cancelModelSelection() {
    selectedModel = null;
    document.getElementById('session-config').style.display = 'none';
    document.getElementById('models-section').style.display = 'block';
}

function updateEstimatedCost() {
    const minutesEl = document.getElementById('minutes');
    const costEl = document.getElementById('estimated-cost');
    if (!minutesEl || !costEl) return;
    
    const minutes = parseInt(minutesEl.value) || 5;
    // Prezzo base: 10 sats/minuto, modelli più grandi costano di più
    let basePrice = 10;
    
    if (selectedModel) {
        const params = selectedModel.parameters.toLowerCase();
        if (params.includes('70b') || params.includes('72b')) basePrice = 100;
        else if (params.includes('34b') || params.includes('32b')) basePrice = 50;
        else if (params.includes('13b') || params.includes('14b')) basePrice = 30;
        else if (params.includes('7b') || params.includes('8b')) basePrice = 20;
    }
    
    const cost = basePrice * minutes;
    costEl.textContent = `~${cost} sats`;
}

// Aggiorna costo quando cambia durata
document.addEventListener('DOMContentLoaded', () => {
    const minutesInput = document.getElementById('minutes');
    if (minutesInput) {
        minutesInput.addEventListener('change', updateEstimatedCost);
        minutesInput.addEventListener('input', updateEstimatedCost);
    }
});

// ===========================================
// Session Management
// ===========================================
async function createSession() {
    if (!selectedModel) {
        showError('Please select a model first');
        return;
    }
    
    const minutes = parseInt(document.getElementById('minutes').value);
    if (minutes < 1 || minutes > 120) {
        showError('Duration must be between 1 and 120 minutes');
        return;
    }

    try {
        const response = await fetch('/api/new_session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                model: selectedModel.id || selectedModel.name,
                minutes: minutes
            })
        });

        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to create session');
        }

        // Mostra invoice
        document.getElementById('session-config').style.display = 'none';
        document.getElementById('invoice-section').style.display = 'block';
        document.getElementById('invoice').textContent = data.invoice;
        document.getElementById('invoice-amount').textContent = data.amount;
        
        currentSession = data.session_id;
        localStorage.setItem('sessionId', currentSession);
        
    } catch (error) {
        showError(error.message);
    }
}

function copyInvoice() {
    const invoice = document.getElementById('invoice').textContent;
    navigator.clipboard.writeText(invoice).then(() => {
        showSuccess('Invoice copied to clipboard!');
    }).catch(() => {
        showError('Failed to copy');
    });
}

function checkPayment() {
    if (!currentSession) return;
    socket.emit('start_session', {session_id: currentSession});
}

function cancelPayment() {
    currentSession = null;
    localStorage.removeItem('sessionId');
    document.getElementById('invoice-section').style.display = 'none';
    document.getElementById('session-config').style.display = 'block';
}

function startChatUI() {
    document.getElementById('invoice-section').style.display = 'none';
    document.getElementById('models-section').style.display = 'none';
    document.getElementById('session-config').style.display = 'none';
    document.getElementById('chat-section').style.display = 'block';
    
    document.getElementById('session-model').textContent = `Model: ${selectedModel?.name || 'Unknown'}`;
    document.getElementById('prompt').disabled = false;
    document.getElementById('send-btn').disabled = false;
    document.getElementById('prompt').focus();
    
    // Pulisci chat
    document.getElementById('chat').innerHTML = '<div class="message system">Session started! You can now chat with the AI.</div>';
}

function endSession() {
    if (confirm('Are you sure you want to end this session?')) {
        currentSession = null;
        selectedModel = null;
        localStorage.removeItem('sessionId');
        
        document.getElementById('chat-section').style.display = 'none';
        document.getElementById('models-section').style.display = 'block';
        
        loadModels();
    }
}

// ===========================================
// Socket.IO
// ===========================================
function connectSocket() {
    if (socket && socket.connected) return;
    
    socket = io({
        auth: {token: authToken}
    });

    socket.on('connect', () => {
        console.log('Connected to server');
        if (currentSession) {
            socket.emit('resume_session', {session_id: currentSession});
        }
    });

    socket.on('session_started', (data) => {
        const expiresEl = document.getElementById('session-expires');
        if (expiresEl) {
            expiresEl.textContent = `Expires: ${new Date(data.expires_at).toLocaleTimeString()}`;
        }
        startChatUI();
        addMessage('System', `Connected to node ${data.node_id}`);
    });
    
    socket.on('session_ready', (data) => {
        addMessage('System', 'Session ready!');
    });

    socket.on('ai_response', (data) => {
        addMessage('AI', data.response);
    });

    socket.on('error', (data) => {
        addMessage('System', `Error: ${data.message}`);
        enableInput();
    });

    socket.on('disconnect', () => {
        console.log('Disconnected');
    });
}

// ===========================================
// Chat
// ===========================================
function sendMessage() {
    const promptInput = document.getElementById('prompt');
    const prompt = promptInput.value.trim();
    
    if (!prompt || !currentSession || isWaitingForResponse) return;

    addMessage('You', prompt);
    promptInput.value = '';
    
    isWaitingForResponse = true;
    promptInput.disabled = true;
    document.getElementById('send-btn').disabled = true;
    
    addLoadingIndicator();

    socket.emit('chat_message', {
        session_id: currentSession,
        prompt: prompt,
        max_tokens: 512,
        temperature: 0.7
    });
    
    // Timeout di sicurezza
    setTimeout(() => {
        if (isWaitingForResponse) {
            removeLoadingIndicator();
            enableInput();
            addMessage('System', 'Response timeout. Please try again.');
        }
    }, 180000);
}

function enableInput() {
    isWaitingForResponse = false;
    const promptInput = document.getElementById('prompt');
    const sendBtn = document.getElementById('send-btn');
    if (promptInput) promptInput.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    if (promptInput) promptInput.focus();
}

function addLoadingIndicator() {
    removeLoadingIndicator(); // Rimuovi eventuali precedenti
    const chat = document.getElementById('chat');
    if (!chat) return;
    
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message ai loading';
    loadingDiv.id = 'loading-indicator';
    loadingDiv.innerHTML = '<span class="typing-indicator"><span></span><span></span><span></span></span>';
    chat.appendChild(loadingDiv);
    scrollChat();
}

function removeLoadingIndicator() {
    const loading = document.getElementById('loading-indicator');
    if (loading) loading.remove();
}

function addMessage(sender, text) {
    removeLoadingIndicator();
    
    if (sender === 'AI') {
        enableInput();
    }
    
    const chat = document.getElementById('chat');
    if (!chat) return;
    
    const messageDiv = document.createElement('div');
    
    const senderClass = sender.toLowerCase().replace(' ', '-');
    messageDiv.className = `message ${senderClass}`;
    
    const formattedText = formatMessage(text);
    
    if (sender === 'System') {
        messageDiv.innerHTML = formattedText;
    } else {
        messageDiv.innerHTML = `<strong>${sender}:</strong> ${formattedText}`;
    }
    
    chat.appendChild(messageDiv);
    scrollChat();
}

function scrollChat() {
    const chat = document.getElementById('chat');
    if (chat) chat.scrollTop = chat.scrollHeight;
}

function formatMessage(text) {
    // Escape HTML
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Code blocks
    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code class="$1">$2</code></pre>');
    
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Bold
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Italic
    text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    
    // Newlines
    text = text.replace(/\n/g, '<br>');
    
    return text;
}

// ===========================================
// Nodes Modal
// ===========================================
function showNodesInfo() {
    const modal = document.getElementById('nodes-modal');
    const list = document.getElementById('nodes-list');
    
    if (!modal || !list) return;
    
    if (onlineNodes.length === 0) {
        list.innerHTML = '<p>No nodes online</p>';
    } else {
        list.innerHTML = onlineNodes.map(node => `
            <div class="node-card">
                <div class="node-name">${node.name}</div>
                <div class="node-info">
                    <span>CPU: ${node.hardware?.cpu || 'Unknown'}</span>
                    <span>RAM: ${node.hardware?.ram_gb || 0} GB</span>
                </div>
                <div class="node-gpus">
                    ${(node.hardware?.gpus || []).map(gpu => `
                        <div class="gpu-item">
                            <span class="gpu-name">${gpu.name}</span>
                            <span class="gpu-vram">${(gpu.vram_mb/1024).toFixed(1)} GB</span>
                        </div>
                    `).join('')}
                </div>
                <div class="node-models">Models: ${node.models_count}</div>
            </div>
        `).join('');
    }
    
    modal.style.display = 'flex';
}

function closeNodesModal() {
    const modal = document.getElementById('nodes-modal');
    if (modal) modal.style.display = 'none';
}

// Chiudi modal cliccando fuori
window.onclick = function(event) {
    const modal = document.getElementById('nodes-modal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
};

// ===========================================
// Notifications
// ===========================================
function showError(message) {
    showNotification(message, 'error');
}

function showSuccess(message) {
    showNotification(message, 'success');
}

function showNotification(message, type = 'info') {
    // Rimuovi notifiche esistenti
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();
    
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    // Animazione entrata
    setTimeout(() => notification.classList.add('show'), 10);
    
    // Rimuovi dopo 4 secondi
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

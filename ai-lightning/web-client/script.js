/**
 * LightPhon - Web Client
 * 
 * Decentralized LLMs with Lightning payments
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
let modelsRefreshInterval = null;

// Session configuration
let sessionContextLength = 4096;

// LLM Parameters (with defaults)
let llmParams = {
    // Sampling parameters
    temperature: 0.7,
    dynatemp_range: 0,
    dynatemp_exponent: 1,
    top_p: 0.95,
    top_k: 40,
    min_p: 0.05,
    typical_p: 1,
    xtc_threshold: 0.1,
    xtc_probability: 0.5,
    
    // Penalties
    repeat_last_n: 64,
    repeat_penalty: 1,
    presence_penalty: 0,
    frequency_penalty: 0,
    
    // DRY (Don't Repeat Yourself) parameters
    dry_multiplier: 0,
    dry_base: 1.75,
    dry_allowed_length: 2,
    dry_penalty_last_n: -1,
    
    // Generation
    max_tokens: -1,  // -1 = use model's context length
    seed: -1,
    
    // Sampler order
    samplers: "penalties;dry;top_k;typical_p;top_p;min_p;xtc;temperature"
};

// ===========================================
// Initialization
// ===========================================
document.addEventListener('DOMContentLoaded', () => {
    // Carica info rete (disponibile anche senza login)
    loadNetworkInfo();
    
    // Setup slider listeners per parametri LLM
    setupLLMParamSliders();
    
    // Setup context slider
    setupContextSlider();
    
    if (authToken) {
        connectSocket();
        showMain();
        loadModels();
        startModelsRefresh();
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
    // Verifica che abbiamo un token
    if (!authToken) {
        console.warn('No auth token, skipping profile load');
        return;
    }
    
    try {
        console.log('Loading profile with token:', authToken.substring(0, 20) + '...');
        
        const response = await fetch('/api/me', {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        console.log('Profile response status:', response.status);
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            console.error('Profile error:', errorData);
            
            if (response.status === 401 || response.status === 422) {
                // Token scaduto/invalido - ma solo se non è un login appena fatto
                // Controlliamo se il token è stato appena salvato
                const savedToken = localStorage.getItem('authToken');
                if (savedToken !== authToken) {
                    console.warn('Token mismatch, possible race condition');
                    return;
                }
                showError('Session expired. Please login again.');
                logout();
                return;
            }
            throw new Error(errorData.error || 'Failed to load profile');
        }
        
        const data = await response.json();
        console.log('Profile loaded:', data.username);
        
        // Aggiorna UI
        document.getElementById('user-info').textContent = `Welcome, ${data.username}!`;
        updateBalanceDisplay(data.balance);
        
    } catch (error) {
        console.error('Error loading profile:', error);
        // Non fare logout su errori di rete
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
        const busyModels = data.busy_models || [];
        
        if (loading) loading.style.display = 'none';
        
        if (availableModels.length === 0 && busyModels.length === 0) {
            if (grid) grid.innerHTML = '<div class="no-models">No models available. Waiting for nodes to connect...</div>';
            return;
        }
        
        renderModelsGrid(availableModels, busyModels);
        
    } catch (error) {
        if (loading) loading.style.display = 'none';
        if (grid) grid.innerHTML = '<div class="error">Failed to load models. <a href="#" onclick="loadModels()">Retry</a></div>';
    }
}

function formatTimeRemaining(seconds) {
    if (seconds <= 0) return 'Available soon';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins > 0) {
        return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
}

function renderModelsGrid(models, busyModels = []) {
    const grid = document.getElementById('models-grid');
    if (!grid) return;
    grid.innerHTML = '';
    
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
    
    // Render modelli disponibili
    models.forEach(model => {
        const card = document.createElement('div');
        card.className = 'model-card';
        card.onclick = () => selectModel(model);
        
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
    
    // Render modelli occupati (in grigio con timer)
    busyModels.forEach(model => {
        const card = document.createElement('div');
        card.className = 'model-card model-busy';
        // Non cliccabile quando occupato
        card.style.cursor = 'not-allowed';
        
        const icon = icons[model.architecture] || icons.default;
        const timeRemaining = model.seconds_remaining || 0;
        const timerId = `timer-${model.id}`;
        
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
            <div class="model-busy-overlay">
                <span class="busy-icon">⏳</span>
                <span class="busy-text">In use</span>
                <span class="busy-timer" id="${timerId}" data-seconds="${timeRemaining}">
                    Available in: ${formatTimeRemaining(timeRemaining)}
                </span>
            </div>
        `;
        
        grid.appendChild(card);
    });
    
    // Avvia timer per aggiornare i countdown
    startBusyTimers();
}

function startBusyTimers() {
    // Aggiorna i timer ogni secondo
    const timers = document.querySelectorAll('.busy-timer');
    if (timers.length === 0) return;
    
    const updateTimers = () => {
        timers.forEach(timer => {
            let seconds = parseInt(timer.dataset.seconds) || 0;
            if (seconds > 0) {
                seconds--;
                timer.dataset.seconds = seconds;
                timer.textContent = `Available in: ${formatTimeRemaining(seconds)}`;
            } else {
                timer.textContent = 'Available soon...';
            }
        });
    };
    
    // Aggiorna ogni secondo
    const intervalId = setInterval(() => {
        updateTimers();
        // Controlla se ci sono ancora timer attivi
        const activeTimers = document.querySelectorAll('.busy-timer');
        if (activeTimers.length === 0) {
            clearInterval(intervalId);
        }
    }, 1000);
}

function refreshModels() {
    loadModels();
    loadNetworkInfo();
}

// ===========================================
// Auto-refresh Models (ogni 5 secondi)
// ===========================================
function startModelsRefresh() {
    // Evita duplicati
    if (modelsRefreshInterval) {
        clearInterval(modelsRefreshInterval);
    }
    
    // Refresh ogni 5 secondi solo quando sulla pagina modelli
    modelsRefreshInterval = setInterval(() => {
        const modelsSection = document.getElementById('models-section');
        // Refresh solo se la sezione modelli è visibile
        if (modelsSection && modelsSection.style.display !== 'none') {
            loadModels();
        }
    }, 5000);
}

function stopModelsRefresh() {
    if (modelsRefreshInterval) {
        clearInterval(modelsRefreshInterval);
        modelsRefreshInterval = null;
    }
}

function selectModel(model) {
    selectedModel = model;
    
    document.getElementById('models-section').style.display = 'none';
    document.getElementById('session-config').style.display = 'block';
    document.getElementById('selected-model-name').textContent = model.name;
    
    // Reset parametri LLM ai valori di default
    resetLLMParams();
    
    // Imposta context length dal modello (o default 4096)
    const modelContext = model.context_length || 4096;
    sessionContextLength = Math.min(modelContext, 32768);
    
    // Aggiorna slider context
    const contextSlider = document.getElementById('context-slider');
    const contextValue = document.getElementById('context-value');
    if (contextSlider) {
        contextSlider.max = modelContext;
        contextSlider.value = sessionContextLength;
    }
    if (contextValue) {
        contextValue.textContent = sessionContextLength;
    }
    
    updateEstimatedCost();
}

function setupContextSlider() {
    const slider = document.getElementById('context-slider');
    const valueEl = document.getElementById('context-value');
    
    if (slider && valueEl) {
        slider.addEventListener('input', () => {
            sessionContextLength = parseInt(slider.value);
            valueEl.textContent = sessionContextLength;
        });
    }
}

function cancelModelSelection() {
    selectedModel = null;
    document.getElementById('session-config').style.display = 'none';
    document.getElementById('models-section').style.display = 'block';
}

// ===========================================
// LLM Settings Modal
// ===========================================
function openLLMSettings() {
    const modal = document.getElementById('llm-settings-modal');
    if (modal) {
        modal.style.display = 'flex';
        // Re-sync UI with current params
        setupLLMParamSliders();
    }
}

function closeLLMSettings() {
    const modal = document.getElementById('llm-settings-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Close modal when clicking outside
document.addEventListener('click', (e) => {
    const modal = document.getElementById('llm-settings-modal');
    if (e.target === modal) {
        closeLLMSettings();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLLMSettings();
    }
});

// ===========================================
// LLM Parameters
// ===========================================
function setupLLMParamSliders() {
    // Helper function to setup a slider with value display
    function setupSlider(sliderId, valueId, paramName, decimals = 2) {
        const slider = document.getElementById(sliderId);
        const valueEl = document.getElementById(valueId);
        if (slider && valueEl) {
            // Set initial value
            slider.value = llmParams[paramName];
            valueEl.textContent = decimals > 0 ? llmParams[paramName].toFixed(decimals) : llmParams[paramName];
            
            slider.addEventListener('input', () => {
                llmParams[paramName] = parseFloat(slider.value);
                valueEl.textContent = decimals > 0 ? llmParams[paramName].toFixed(decimals) : llmParams[paramName];
            });
        }
    }
    
    // Helper function to setup a number input
    function setupNumberInput(inputId, paramName) {
        const input = document.getElementById(inputId);
        if (input) {
            input.value = llmParams[paramName];
            input.addEventListener('change', () => {
                llmParams[paramName] = parseInt(input.value) || llmParams[paramName];
            });
        }
    }
    
    // Helper function to setup a text input
    function setupTextInput(inputId, paramName) {
        const input = document.getElementById(inputId);
        if (input) {
            input.value = llmParams[paramName];
            input.addEventListener('change', () => {
                llmParams[paramName] = input.value;
            });
        }
    }
    
    // Sampling parameters
    setupSlider('param-temperature', 'temp-value', 'temperature', 2);
    setupSlider('param-dynatemp-range', 'dynatemp-range-value', 'dynatemp_range', 1);
    setupSlider('param-dynatemp-exp', 'dynatemp-exp-value', 'dynatemp_exponent', 1);
    setupSlider('param-top-k', 'topk-value', 'top_k', 0);
    setupSlider('param-top-p', 'topp-value', 'top_p', 2);
    setupSlider('param-min-p', 'minp-value', 'min_p', 2);
    setupSlider('param-typical-p', 'typicalp-value', 'typical_p', 2);
    setupSlider('param-xtc-threshold', 'xtc-threshold-value', 'xtc_threshold', 2);
    setupSlider('param-xtc-prob', 'xtc-prob-value', 'xtc_probability', 2);
    
    // Penalties
    setupNumberInput('param-repeat-last-n', 'repeat_last_n');
    setupSlider('param-repeat-penalty', 'repeat-value', 'repeat_penalty', 2);
    setupSlider('param-presence-penalty', 'presence-value', 'presence_penalty', 1);
    setupSlider('param-frequency-penalty', 'frequency-value', 'frequency_penalty', 1);
    
    // DRY parameters
    setupSlider('param-dry-multiplier', 'dry-mult-value', 'dry_multiplier', 1);
    setupSlider('param-dry-base', 'dry-base-value', 'dry_base', 2);
    setupNumberInput('param-dry-allowed-length', 'dry_allowed_length');
    setupNumberInput('param-dry-penalty-last-n', 'dry_penalty_last_n');
    
    // Generation
    setupNumberInput('param-max-tokens', 'max_tokens');
    setupNumberInput('param-seed', 'seed');
    
    // Sampler order
    setupTextInput('param-samplers', 'samplers');
}

// Default LLM parameters
const defaultLLMParams = {
    // Sampling parameters
    temperature: 0.7,
    dynatemp_range: 0,
    dynatemp_exponent: 1,
    top_p: 0.95,
    top_k: 40,
    min_p: 0.05,
    typical_p: 1,
    xtc_threshold: 0.1,
    xtc_probability: 0.5,
    
    // Penalties
    repeat_last_n: 64,
    repeat_penalty: 1,
    presence_penalty: 0,
    frequency_penalty: 0,
    
    // DRY (Don't Repeat Yourself) parameters
    dry_multiplier: 0,
    dry_base: 1.75,
    dry_allowed_length: 2,
    dry_penalty_last_n: -1,
    
    // Generation
    max_tokens: -1,
    seed: -1,
    
    // Sampler order
    samplers: "penalties;dry;top_k;typical_p;top_p;min_p;xtc;temperature"
};

function resetLLMParams() {
    // Reset ai valori di default
    llmParams = {...defaultLLMParams};
    
    // Reinitialize all UI elements
    setupLLMParamSliders();
}

function getLLMParams() {
    return {...llmParams};
}

// ===========================================
// Session Cost
// ===========================================

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
                minutes: minutes,
                context_length: sessionContextLength
            })
        });

        const data = await response.json();
        
        console.log('new_session response:', data);
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to create session');
        }

        // IMPORTANTE: Salva session_id PRIMA di tutto il resto
        currentSession = data.session_id;
        localStorage.setItem('sessionId', currentSession);
        console.log('Session created, currentSession:', currentSession);

        // Mostra invoice
        document.getElementById('session-config').style.display = 'none';
        document.getElementById('invoice-section').style.display = 'block';
        document.getElementById('invoice').textContent = data.invoice;
        document.getElementById('invoice-amount').textContent = data.amount;
        
        // Genera QR code (può fallire senza bloccare)
        try {
            generateQRCode(data.invoice);
        } catch (qrError) {
            console.error('QR code generation failed:', qrError);
        }
        
    } catch (error) {
        showError(error.message);
    }
}

// Genera QR code per l'invoice Lightning
function generateQRCode(invoice) {
    const canvas = document.getElementById('qr-code');
    
    // Usa il prefisso lightning: per compatibilità con i wallet
    const lightningUri = `lightning:${invoice.toUpperCase()}`;
    
    // Opzioni QR code
    QRCode.toCanvas(canvas, lightningUri, {
        width: 280,
        margin: 2,
        color: {
            dark: '#1a1a2e',  // Colore scuro (sfondo del tema)
            light: '#ffffff'  // Sfondo bianco per leggibilità
        },
        errorCorrectionLevel: 'M'
    }, function(error) {
        if (error) {
            console.error('QR Code generation error:', error);
            // Fallback: nascondi QR se fallisce
            document.getElementById('qr-container').style.display = 'none';
        }
    });
}

// Apri invoice nel wallet Lightning
function openInWallet() {
    const invoice = document.getElementById('invoice').textContent;
    if (invoice) {
        // Usa lightning: URI scheme per aprire nel wallet
        window.location.href = `lightning:${invoice}`;
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
    console.log('checkPayment called, currentSession:', currentSession);
    
    if (!currentSession) {
        showError('No active session');
        return;
    }
    
    if (!socket || !socket.connected) {
        showError('Not connected to server. Reconnecting...');
        connectSocket();
        setTimeout(checkPayment, 1000);  // Retry after 1s
        return;
    }
    
    console.log('Checking payment for session:', currentSession);
    
    // Mostra messaggio di attesa con timer
    showLoadingOverlay('Connecting to node... Waiting for model to load.');
    
    socket.emit('start_session', {session_id: currentSession});
}

// Mostra overlay di caricamento con opzione skip e stato aggiornabile
function showLoadingOverlay(message) {
    // Rimuovi overlay precedente se esiste
    hideLoadingOverlay();
    
    const overlay = document.createElement('div');
    overlay.id = 'loading-overlay';
    overlay.innerHTML = `
        <div class="loading-content">
            <div class="loading-spinner"></div>
            <p class="loading-message" id="loading-message">${message}</p>
            <p class="loading-status" id="loading-status"></p>
            <p class="loading-timer">Elapsed: <span id="loading-time">0</span>s</p>
            <button class="btn btn-secondary" onclick="skipLoading()">Cancel & Go Back</button>
        </div>
    `;
    document.body.appendChild(overlay);
    
    // Timer
    let seconds = 0;
    window.loadingInterval = setInterval(() => {
        seconds++;
        const timeEl = document.getElementById('loading-time');
        if (timeEl) timeEl.textContent = seconds;
    }, 1000);
}

// Aggiorna messaggio e status dell'overlay di caricamento
function updateLoadingOverlay(message, status) {
    const msgEl = document.getElementById('loading-message');
    const statusEl = document.getElementById('loading-status');
    
    if (msgEl && message) {
        msgEl.textContent = message;
    }
    if (statusEl) {
        statusEl.textContent = status || '';
        
        // Colore in base allo stato
        if (status && status.toLowerCase().includes('download')) {
            statusEl.style.color = '#f7931a';  // Arancione per download
        } else if (status && status.toLowerCase().includes('loading')) {
            statusEl.style.color = '#00d4ff';  // Azzurro per caricamento
        } else if (status && status.toLowerCase().includes('ready')) {
            statusEl.style.color = '#00ff88';  // Verde per pronto
        }
    }
}

function hideLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.remove();
    if (window.loadingInterval) {
        clearInterval(window.loadingInterval);
        window.loadingInterval = null;
    }
}

function skipLoading() {
    hideLoadingOverlay();
    showError('Cancelled. You can try again or choose a smaller model.');
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
    
    // Reset dello stato e abilita input
    isWaitingForResponse = false;
    currentStreamingMessageId = null;
    streamingContent = '';
    
    document.getElementById('prompt').disabled = false;
    document.getElementById('send-btn').disabled = false;
    document.getElementById('prompt').focus();
    
    // Pulisci chat
    document.getElementById('chat').innerHTML = '<div class="message system">Session started! You can now chat with the AI.</div>';
}

function endSession() {
    if (confirm('Are you sure you want to end this session? This will stop the AI model on the node.')) {
        // Invia end_session al server per fermare llama-server sul nodo
        if (socket && currentSession) {
            socket.emit('end_session', { session_id: currentSession });
        }
        
        currentSession = null;
        selectedModel = null;
        localStorage.removeItem('sessionId');
        
        // Reset streaming state
        currentStreamingMessageId = null;
        streamingContent = '';
        
        document.getElementById('chat-section').style.display = 'none';
        document.getElementById('models-section').style.display = 'block';
        
        loadModels();
    }
}

// ===========================================
// Socket.IO
// ===========================================

// Variabile per tracciare il messaggio in streaming corrente
let currentStreamingMessageId = null;
let streamingContent = '';

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
        hideLoadingOverlay();
        const expiresEl = document.getElementById('session-expires');
        if (expiresEl) {
            expiresEl.textContent = `Expires: ${new Date(data.expires_at).toLocaleTimeString()}`;
        }
        startChatUI();
        addMessage('System', `Connected to node ${data.node_id}. Model ready!`);
    });
    
    // Aggiornamenti stato caricamento modello
    socket.on('model_status', (data) => {
        const status = data.status;
        const message = data.message;
        
        console.log('Model status:', status, message);
        
        let displayMessage = 'Loading model...';
        let displayStatus = message;
        
        switch(status) {
            case 'downloading':
                displayMessage = '⬇️ Downloading model from HuggingFace...';
                displayStatus = message || 'This may take several minutes for large models.';
                break;
            case 'loading':
                displayMessage = '🔄 Loading model into GPU memory...';
                displayStatus = message || 'Almost ready...';
                break;
            case 'ready':
                displayMessage = '✅ Model loaded!';
                displayStatus = 'Starting session...';
                break;
            case 'waiting':
                displayMessage = '⏳ Preparing model...';
                displayStatus = message;
                break;
            default:
                displayStatus = message || status;
        }
        
        updateLoadingOverlay(displayMessage, displayStatus);
    });
    
    socket.on('session_ready', (data) => {
        hideLoadingOverlay();
        addMessage('System', 'Session ready!');
        enableInput();
    });

    // Streaming: ricevi token singoli
    socket.on('ai_token', (data) => {
        const token = data.token;
        const isFinal = data.is_final;
        
        console.log('ai_token received:', {token: token.substring(0, 20), isFinal});
        
        // Rimuovi loading indicator alla prima token
        if (!currentStreamingMessageId) {
            removeLoadingIndicator();
            currentStreamingMessageId = createStreamingMessage();
            streamingContent = '';
        }
        
        // Aggiungi token al contenuto
        streamingContent += token;
        updateStreamingMessage(currentStreamingMessageId, streamingContent);
        
        if (isFinal) {
            // Token finale ricevuto - finalizza il messaggio
            console.log('Final token received, finalizing...');
            if (currentStreamingMessageId) {
                finalizeStreamingMessage(currentStreamingMessageId, streamingContent);
                currentStreamingMessageId = null;
                streamingContent = '';
            }
            enableInput();
        }
    });

    socket.on('ai_response', (data) => {
        console.log('ai_response received:', data);
        removeLoadingIndicator();
        
        if (data.streaming_complete && currentStreamingMessageId) {
            // Streaming completato - aggiorna con contenuto pulito finale
            finalizeStreamingMessage(currentStreamingMessageId, data.response);
            currentStreamingMessageId = null;
            streamingContent = '';
        } else if (!currentStreamingMessageId) {
            // Risposta non-streaming normale
            addMessage('AI', data.response);
        }
        
        enableInput();
        console.log('Input enabled after ai_response');
    });

    socket.on('error', (data) => {
        console.error('Socket error:', data);
        hideLoadingOverlay();
        removeLoadingIndicator();
        
        // Reset streaming state
        if (currentStreamingMessageId) {
            finalizeStreamingMessage(currentStreamingMessageId, '[Error occurred]');
            currentStreamingMessageId = null;
            streamingContent = '';
        }
        
        showError(data.message);
        // Also add to chat if visible
        const chatSection = document.getElementById('chat-section');
        if (chatSection && chatSection.style.display !== 'none') {
            addMessage('System', `Error: ${data.message}`);
            enableInput();
        }
    });

    socket.on('session_ended', (data) => {
        console.log('Session ended by server');
        // La sessione è stata chiusa (potrebbe essere stata chiusa dal server)
        addMessage('System', 'Session ended. The AI model has been stopped.');
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
    
    console.log('sendMessage called:', {prompt, currentSession, isWaitingForResponse, disabled: promptInput.disabled});
    
    if (!prompt || !currentSession || isWaitingForResponse) {
        console.log('sendMessage blocked:', {noPrompt: !prompt, noSession: !currentSession, waiting: isWaitingForResponse});
        return;
    }

    addMessage('You', prompt);
    promptInput.value = '';
    
    isWaitingForResponse = true;
    promptInput.disabled = true;
    document.getElementById('send-btn').disabled = true;
    console.log('Input disabled, waiting for response');
    
    addLoadingIndicator();

    // Invia messaggio con tutti i parametri LLM configurati
    const params = getLLMParams();
    socket.emit('chat_message', {
        session_id: currentSession,
        prompt: prompt,
        // Basic parameters
        max_tokens: params.max_tokens,
        temperature: params.temperature,
        top_p: params.top_p,
        top_k: params.top_k,
        seed: params.seed,
        // Extended sampling parameters
        min_p: params.min_p,
        typical_p: params.typical_p,
        dynatemp_range: params.dynatemp_range,
        dynatemp_exponent: params.dynatemp_exponent,
        // Penalties
        repeat_last_n: params.repeat_last_n,
        repeat_penalty: params.repeat_penalty,
        presence_penalty: params.presence_penalty,
        frequency_penalty: params.frequency_penalty,
        // DRY parameters
        dry_multiplier: params.dry_multiplier,
        dry_base: params.dry_base,
        dry_allowed_length: params.dry_allowed_length,
        dry_penalty_last_n: params.dry_penalty_last_n,
        // XTC parameters
        xtc_threshold: params.xtc_threshold,
        xtc_probability: params.xtc_probability,
        // Sampler order
        samplers: params.samplers
    });
    
    // Timeout di sicurezza
    setTimeout(() => {
        if (isWaitingForResponse) {
            console.log('Response timeout triggered');
            removeLoadingIndicator();
            enableInput();
            addMessage('System', 'Response timeout. Please try again.');
        }
    }, 180000);
}

function enableInput() {
    console.log('enableInput called, current isWaitingForResponse:', isWaitingForResponse);
    isWaitingForResponse = false;
    const promptInput = document.getElementById('prompt');
    const sendBtn = document.getElementById('send-btn');
    if (promptInput) {
        promptInput.disabled = false;
        console.log('promptInput.disabled set to false');
    }
    if (sendBtn) {
        sendBtn.disabled = false;
        console.log('sendBtn.disabled set to false');
    }
    if (promptInput) promptInput.focus();
    console.log('enableInput complete');
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

// Crea un messaggio per lo streaming e ritorna il suo ID
function createStreamingMessage() {
    const chat = document.getElementById('chat');
    if (!chat) return null;
    
    const messageId = 'streaming-' + Date.now();
    const messageDiv = document.createElement('div');
    messageDiv.id = messageId;
    messageDiv.className = 'message ai streaming';
    messageDiv.innerHTML = `<strong>AI:</strong> <span class="content"></span><span class="cursor">▌</span>`;
    
    chat.appendChild(messageDiv);
    scrollChat();
    
    return messageId;
}

// Aggiorna il contenuto del messaggio in streaming
function updateStreamingMessage(messageId, content) {
    const messageDiv = document.getElementById(messageId);
    if (!messageDiv) return;
    
    const contentSpan = messageDiv.querySelector('.content');
    if (contentSpan) {
        // Formatta il contenuto mentre arriva
        contentSpan.innerHTML = formatMessage(content);
    }
    scrollChat();
}

// Finalizza il messaggio streaming con il contenuto pulito finale
function finalizeStreamingMessage(messageId, finalContent) {
    const messageDiv = document.getElementById(messageId);
    if (!messageDiv) return;
    
    // Rimuovi classe streaming e cursore
    messageDiv.classList.remove('streaming');
    const cursor = messageDiv.querySelector('.cursor');
    if (cursor) cursor.remove();
    
    // Aggiorna con contenuto finale formattato
    const contentSpan = messageDiv.querySelector('.content');
    if (contentSpan) {
        contentSpan.innerHTML = formatMessage(finalContent);
    }
    
    // Aggiorna l'intera struttura per consistenza
    messageDiv.innerHTML = `<strong>AI:</strong> ${formatMessage(finalContent)}`;
    
    scrollChat();
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
    if (!text) return '';
    
    // Escape HTML (ma preserva i delimitatori LaTeX)
    let escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Proteggi i blocchi LaTeX prima del processing markdown
    const latexBlocks = [];
    let blockIndex = 0;
    
    // Proteggi display math $$...$$
    escaped = escaped.replace(/\$\$([\s\S]*?)\$\$/g, (match, content) => {
        latexBlocks.push({ type: 'display', content: content });
        return `%%LATEX_BLOCK_${blockIndex++}%%`;
    });
    
    // Proteggi inline math $...$  (non greedy, no newlines)
    escaped = escaped.replace(/\$([^\$\n]+?)\$/g, (match, content) => {
        latexBlocks.push({ type: 'inline', content: content });
        return `%%LATEX_BLOCK_${blockIndex++}%%`;
    });
    
    // Proteggi \[...\] display math
    escaped = escaped.replace(/\\\[([\s\S]*?)\\\]/g, (match, content) => {
        latexBlocks.push({ type: 'display', content: content });
        return `%%LATEX_BLOCK_${blockIndex++}%%`;
    });
    
    // Proteggi \(...\) inline math
    escaped = escaped.replace(/\\\(([\s\S]*?)\\\)/g, (match, content) => {
        latexBlocks.push({ type: 'inline', content: content });
        return `%%LATEX_BLOCK_${blockIndex++}%%`;
    });
    
    // Code blocks ```
    escaped = escaped.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code class="$1">$2</code></pre>');
    
    // Inline code `
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Bold **text**
    escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Italic *text*
    escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    
    // Newlines
    escaped = escaped.replace(/\n/g, '<br>');
    
    // Ripristina i blocchi LaTeX con rendering KaTeX
    for (let i = 0; i < latexBlocks.length; i++) {
        const block = latexBlocks[i];
        const placeholder = `%%LATEX_BLOCK_${i}%%`;
        
        try {
            if (typeof katex !== 'undefined') {
                const rendered = katex.renderToString(block.content, {
                    displayMode: block.type === 'display',
                    throwOnError: false,
                    trust: true
                });
                escaped = escaped.replace(placeholder, rendered);
            } else {
                // Fallback se KaTeX non è caricato
                const wrapper = block.type === 'display' 
                    ? `<div class="math-display">\\[${block.content}\\]</div>`
                    : `<span class="math-inline">\\(${block.content}\\)</span>`;
                escaped = escaped.replace(placeholder, wrapper);
            }
        } catch (e) {
            // In caso di errore, mostra il LaTeX raw
            escaped = escaped.replace(placeholder, `<code class="latex-error">${block.content}</code>`);
        }
    }
    
    return escaped;
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

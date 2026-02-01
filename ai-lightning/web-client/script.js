// Stato dell'applicazione
let socket = io();
let authToken = localStorage.getItem('authToken');
let currentSession = localStorage.getItem('sessionId');

// DOM ready
document.addEventListener('DOMContentLoaded', () => {
    if (authToken) {
        connect(new URL(window.location.href));
        showMain();
    } else {
        showLogin();
    }
});

// Auth
async function login() {
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });

        if (!response.ok) {
            throw new Error('Login failed');
        }

        const data = await response.json();
        authToken = data.access_token;
        localStorage.setItem('authToken', authToken);
        connect(new URL(window.location.href));
        showMain();
    } catch (error) {
        alert(error.message);
    }
}

function showLogin() {
    document.getElementById('auth-section').style.display = 'block';
    document.getElementById('main-section').style.display = 'none';
}

function showRegister() {
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('register-form').style.display = 'block';
}

async function register() {
    const username = document.getElementById('reg-username').value;
    const password = document.getElementById('reg-password').value;

    try {
        const response = await fetch('/api/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });

        if (!response.ok) {
            throw new Error('Registration failed');
        }

        alert('Registration successful! Please login.');
        showLogin();
    } catch (error) {
        alert(error.message);
    }
}

function showMain() {
    document.getElementById('auth-section').style.display = 'none';
    document.getElementById('main-section').style.display = 'block';
}

// Socket.IO
function connect(url) {
    socket = io(url, {
        auth: {token: authToken}
    });

    socket.on('connect', () => {
        addMessage('System', 'Connected');
        if (currentSession) {
            socket.emit('resume_session', {session_id: currentSession});
        }
    });

    socket.on('session_started', (data) => {
        currentSession = data.session_id;
        localStorage.setItem('sessionId', currentSession);
        document.getElementById('invoice-section').style.display = 'none';
        addMessage('System', `Session started! Expires at ${new Date(data.expires_at).toLocaleString()}`);
    });

    socket.on('ai_response', (data) => {
        addMessage('AI', data.response);
    });

    socket.on('error', (data) => {
        addMessage('System', `Error: ${data.message}`);
    });

    socket.on('disconnect', () => {
        addMessage('System', 'Disconnected');
    });
}

// Session management
let selectedModel = 'base';

function selectModel(model) {
    selectedModel = model;
    document.querySelector('.model-option.selected').classList.remove('selected');
    document.querySelector(`[data-model="${model}"]`).classList.add('selected');
}

async function createSession() {
    const minutes = document.getElementById('minutes').value;

    try {
        const response = await fetch('/api/new_session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({model: selectedModel, minutes})
        });

        if (!response.ok) {
            throw new Error('Failed to create session');
        }

        const data = await response.json();
        document.getElementById('invoice').textContent = data.invoice;
        document.getElementById('invoice-section').style.display = 'block';
        document.querySelector('#invoice-section button').style.display = 'block';
        currentSession = data.session_id;
        localStorage.setItem('sessionId', currentSession);
    } catch (error) {
        addMessage('System', `Error: ${error.message}`);
    }
}

function checkPayment() {
    socket.emit('start_session', {session_id: currentSession});
}

// Chat
function sendMessage() {
    const prompt = document.getElementById('prompt').value;
    if (!prompt.trim() || !currentSession) return;

    addMessage('You', prompt);
    document.getElementById('prompt').value = '';

    socket.emit('chat_message', {
        session_id: currentSession,
        prompt: prompt
    });
}

function addMessage(sender, text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender.toLowerCase()}`;
    messageDiv.textContent = `${sender}: ${text}`;
    document.getElementById('chat').appendChild(messageDiv);
    document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
}
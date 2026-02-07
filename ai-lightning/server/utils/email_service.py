"""
Email Service for AI Lightning.

Handles sending notification emails to users.
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger(__name__)

# Track sent alerts to avoid spamming (node_id -> last_alert_time)
_disk_alerts_sent = {}
_offline_alerts_sent = {}


def send_email(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """
    Send an email using SMTP.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body of the email
        text_content: Plain text version (optional)
    
    Returns:
        True if sent successfully, False otherwise
    """
    from config import Config
    
    if not Config.SMTP_PASSWORD:
        logger.warning("SMTP_PASSWORD not configured, skipping email")
        return False
    
    if not to_email:
        logger.warning("No recipient email provided")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = Config.SMTP_FROM
        msg['To'] = to_email
        
        # Plain text version
        if text_content:
            part1 = MIMEText(text_content, 'plain')
            msg.attach(part1)
        
        # HTML version
        part2 = MIMEText(html_content, 'html')
        msg.attach(part2)
        
        # Connect and send
        if Config.SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, context=context) as server:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM, to_email, msg.as_string())
        else:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM, to_email, msg.as_string())
        
        logger.info(f"Email sent successfully to {to_email}: {subject}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_disk_full_alert(user_email: str, node_id: str, node_name: str, 
                         disk_percent: float, disk_free_gb: float) -> bool:
    """
    Send disk full alert email to node owner.
    
    Args:
        user_email: Node owner's email
        node_id: Node identifier
        node_name: Node display name
        disk_percent: Disk usage percentage
        disk_free_gb: Free disk space in GB
    """
    import time
    from config import Config
    
    # Check if we already sent an alert recently (1 hour cooldown)
    last_alert = _disk_alerts_sent.get(node_id, 0)
    if time.time() - last_alert < 3600:  # 1 hour cooldown
        logger.debug(f"Disk alert for node {node_id} already sent recently, skipping")
        return False
    
    subject = f"⚠️ AI Lightning - Disco Pieno sul Nodo {node_name}"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 10px; padding: 30px; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .logo {{ font-size: 24px; color: #f39c12; }}
            .alert-box {{ background-color: #c0392b; color: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .info {{ background-color: #0f3460; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .footer {{ text-align: center; margin-top: 30px; color: #888; font-size: 12px; }}
            h1 {{ color: #f39c12; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">⚡ AI Lightning</div>
            </div>
            
            <h1>⚠️ Attenzione: Disco Pieno</h1>
            
            <div class="alert-box">
                <strong>Il disco del tuo nodo sta esaurendo lo spazio!</strong>
            </div>
            
            <div class="info">
                <p><strong>Nodo:</strong> {node_name} ({node_id})</p>
                <p><strong>Spazio usato:</strong> {disk_percent:.1f}%</p>
                <p><strong>Spazio libero:</strong> {disk_free_gb:.1f} GB</p>
            </div>
            
            <p>Ti consigliamo di:</p>
            <ul>
                <li>Rimuovere i modelli non utilizzati</li>
                <li>Liberare spazio su disco</li>
                <li>Aumentare lo spazio disponibile</li>
            </ul>
            
            <p>Se il disco si riempie completamente, il nodo non sarà in grado di scaricare nuovi modelli 
            e potrebbe avere problemi di funzionamento.</p>
            
            <div class="footer">
                <p>AI Lightning - Decentralized LLM Network</p>
                <p>Questa email è stata inviata automaticamente. Non rispondere a questo indirizzo.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    AI Lightning - Attenzione: Disco Pieno
    
    Il disco del tuo nodo sta esaurendo lo spazio!
    
    Nodo: {node_name} ({node_id})
    Spazio usato: {disk_percent:.1f}%
    Spazio libero: {disk_free_gb:.1f} GB
    
    Ti consigliamo di:
    - Rimuovere i modelli non utilizzati
    - Liberare spazio su disco
    - Aumentare lo spazio disponibile
    
    Se il disco si riempie completamente, il nodo non sarà in grado di scaricare nuovi modelli.
    """
    
    result = send_email(user_email, subject, html_content, text_content)
    
    if result:
        _disk_alerts_sent[node_id] = time.time()
    
    return result


def send_node_offline_alert(user_email: str, node_id: str, node_name: str) -> bool:
    """
    Send node offline alert email to node owner.
    
    Args:
        user_email: Node owner's email
        node_id: Node identifier
        node_name: Node display name
    """
    import time
    
    # Check if we already sent an alert recently (1 hour cooldown)
    last_alert = _offline_alerts_sent.get(node_id, 0)
    if time.time() - last_alert < 3600:  # 1 hour cooldown
        logger.debug(f"Offline alert for node {node_id} already sent recently, skipping")
        return False
    
    subject = f"🔴 AI Lightning - Nodo {node_name} Offline"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 10px; padding: 30px; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .logo {{ font-size: 24px; color: #f39c12; }}
            .alert-box {{ background-color: #7f8c8d; color: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .info {{ background-color: #0f3460; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .footer {{ text-align: center; margin-top: 30px; color: #888; font-size: 12px; }}
            h1 {{ color: #e74c3c; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">⚡ AI Lightning</div>
            </div>
            
            <h1>🔴 Nodo Offline</h1>
            
            <div class="alert-box">
                <strong>Il tuo nodo si è disconnesso dalla rete AI Lightning.</strong>
            </div>
            
            <div class="info">
                <p><strong>Nodo:</strong> {node_name}</p>
                <p><strong>ID:</strong> {node_id}</p>
            </div>
            
            <p>Possibili cause:</p>
            <ul>
                <li>Problemi di connessione internet</li>
                <li>Il software del nodo è stato chiuso</li>
                <li>Riavvio del sistema</li>
                <li>Errore nel software</li>
            </ul>
            
            <p>Se non hai interrotto il nodo intenzionalmente, ti consigliamo di verificare 
            lo stato del tuo sistema e riavviare il software del nodo.</p>
            
            <div class="footer">
                <p>AI Lightning - Decentralized LLM Network</p>
                <p>Questa email è stata inviata automaticamente. Non rispondere a questo indirizzo.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    AI Lightning - Nodo Offline
    
    Il tuo nodo si è disconnesso dalla rete AI Lightning.
    
    Nodo: {node_name}
    ID: {node_id}
    
    Possibili cause:
    - Problemi di connessione internet
    - Il software del nodo è stato chiuso
    - Riavvio del sistema
    - Errore nel software
    
    Se non hai interrotto il nodo intenzionalmente, verifica lo stato del tuo sistema.
    """
    
    result = send_email(user_email, subject, html_content, text_content)
    
    if result:
        _offline_alerts_sent[node_id] = time.time()
    
    return result


def clear_alert_cooldown(node_id: str, alert_type: str = 'all'):
    """
    Clear alert cooldown for a node (e.g., when it comes back online).
    
    Args:
        node_id: Node identifier
        alert_type: 'disk', 'offline', or 'all'
    """
    if alert_type in ('disk', 'all') and node_id in _disk_alerts_sent:
        del _disk_alerts_sent[node_id]
    if alert_type in ('offline', 'all') and node_id in _offline_alerts_sent:
        del _offline_alerts_sent[node_id]


def send_verification_email(to_email: str, username: str, verification_link: str) -> bool:
    """
    Send email verification link to new user.
    
    Args:
        to_email: User's email address
        username: User's username
        verification_link: URL to verify email
    
    Returns:
        True if sent successfully, False otherwise
    """
    subject = "✉️ AI Lightning - Verifica la tua email"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #1a1a2e; color: #e0e0e0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #16213e; border-radius: 10px; padding: 30px; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .logo {{ font-size: 28px; color: #f39c12; }}
            .welcome-box {{ background-color: #0f3460; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center; }}
            .btn {{ display: inline-block; background-color: #f39c12; color: #1a1a2e !important; padding: 15px 40px; 
                    text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; margin: 20px 0; }}
            .btn:hover {{ background-color: #e67e22; }}
            .info {{ background-color: #0f3460; padding: 15px; border-radius: 8px; margin: 15px 0; font-size: 12px; }}
            .footer {{ text-align: center; margin-top: 30px; color: #888; font-size: 12px; }}
            h1 {{ color: #f39c12; text-align: center; }}
            .link-text {{ word-break: break-all; color: #888; font-size: 11px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">⚡ AI Lightning</div>
            </div>
            
            <h1>Benvenuto, {username}!</h1>
            
            <div class="welcome-box">
                <p>Grazie per esserti registrato su AI Lightning!</p>
                <p>Per completare la registrazione e attivare il tuo account, clicca sul pulsante qui sotto:</p>
                
                <a href="{verification_link}" class="btn">✅ Verifica Email</a>
                
                <p style="color: #888; font-size: 13px; margin-top: 15px;">
                    Il link scade tra 24 ore.
                </p>
            </div>
            
            <div class="info">
                <p>Se il pulsante non funziona, copia e incolla questo link nel tuo browser:</p>
                <p class="link-text">{verification_link}</p>
            </div>
            
            <p style="text-align: center; color: #888;">
                Se non hai creato un account su AI Lightning, ignora questa email.
            </p>
            
            <div class="footer">
                <p>AI Lightning - Decentralized LLM Network</p>
                <p>Questa email è stata inviata automaticamente. Non rispondere a questo indirizzo.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    AI Lightning - Verifica la tua email
    
    Benvenuto, {username}!
    
    Grazie per esserti registrato su AI Lightning!
    Per completare la registrazione e attivare il tuo account, visita questo link:
    
    {verification_link}
    
    Il link scade tra 24 ore.
    
    Se non hai creato un account su AI Lightning, ignora questa email.
    
    ---
    AI Lightning - Decentralized LLM Network
    """
    
    return send_email(to_email, subject, html_content, text_content)

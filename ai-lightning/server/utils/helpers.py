"""
Utility functions for the AI Lightning server.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

# Prezzo di default per modelli dinamici (sats/minuto)
DEFAULT_DYNAMIC_MODEL_PRICE = 100


def validate_model(model_name):
    """
    Validate that a model name is valid.
    Accetta sia modelli statici che dinamici.
    
    Args:
        model_name: Name of the model to validate
        
    Returns:
        bool: True if valid (non-empty string)
    """
    # Per i modelli dinamici, accetta qualsiasi stringa non vuota
    # La validazione effettiva avviene quando si cerca un nodo
    return bool(model_name and isinstance(model_name, str))


def get_model_price(model_name, price_from_node=None):
    """
    Get the price per minute for a model.
    Supports both static models (from Config) and dynamic models (from nodes).
    
    Args:
        model_name: Name of the model
        price_from_node: Optional price provided by node for dynamic models
        
    Returns:
        int: Price in satoshis per minute
    """
    # First check if it's a static model
    if model_name in Config.AVAILABLE_MODELS:
        return Config.AVAILABLE_MODELS[model_name]['price_per_minute']
    
    # Per modelli dinamici, usa il prezzo dal nodo o il default
    if price_from_node is not None:
        return int(price_from_node)
    
    return DEFAULT_DYNAMIC_MODEL_PRICE


def format_satoshis(amount):
    """
    Format satoshi amount for display.
    
    Args:
        amount: Amount in satoshis
        
    Returns:
        str: Formatted string
    """
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.8f} BTC"
    elif amount >= 1000:
        return f"{amount:,} sats"
    else:
        return f"{amount} sats"


def validate_username(username):
    """
    Validate username format.
    
    Args:
        username: Username to validate
        
    Returns:
        bool: True if valid
    """
    if not username or len(username) < 3 or len(username) > 80:
        return False
    # Allow alphanumeric and underscore
    return username.replace('_', '').isalnum()


def validate_password(password):
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        
    Returns:
        bool: True if valid
    """
    if not password or len(password) < 8:
        return False
    return True
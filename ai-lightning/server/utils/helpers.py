"""
Utility functions for the AI Lightning server.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


def validate_model(model_name):
    """
    Validate that a model name is valid.
    
    Args:
        model_name: Name of the model to validate
        
    Returns:
        bool: True if valid
    """
    return model_name in Config.AVAILABLE_MODELS


def get_model_price(model_name):
    """
    Get the price per minute for a model.
    
    Args:
        model_name: Name of the model
        
    Returns:
        int: Price in satoshis per minute
    """
    if model_name not in Config.AVAILABLE_MODELS:
        raise ValueError(f"Unknown model: {model_name}")
    return Config.AVAILABLE_MODELS[model_name]['price_per_minute']


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
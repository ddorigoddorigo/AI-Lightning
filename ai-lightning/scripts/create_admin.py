#!/usr/bin/env python
"""
Script per creare un utente admin.

Usage:
    python scripts/create_admin.py <username> <password>
    
Or via Flask CLI:
    flask create-admin <username> <password>
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_admin(username: str, password: str) -> bool:
    """
    Crea un utente admin nel database.
    
    Args:
        username: Nome utente
        password: Password
        
    Returns:
        True se creato con successo
    """
    from server.app import app, db
    from server.models import User
    
    with app.app_context():
        # Verifica se l'utente esiste già
        existing = User.query.filter_by(username=username).first()
        if existing:
            print(f"Error: User '{username}' already exists")
            if not existing.is_admin:
                existing.is_admin = True
                db.session.commit()
                print(f"User '{username}' promoted to admin")
                return True
            return False
        
        # Crea nuovo admin
        user = User(username=username, is_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        print(f"Admin user '{username}' created successfully")
        return True


def main():
    if len(sys.argv) != 3:
        print("Usage: python create_admin.py <username> <password>")
        print("Example: python create_admin.py admin MySecurePassword123")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    
    # Validazione base
    if len(username) < 3:
        print("Error: Username must be at least 3 characters")
        sys.exit(1)
    
    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        sys.exit(1)
    
    success = create_admin(username, password)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
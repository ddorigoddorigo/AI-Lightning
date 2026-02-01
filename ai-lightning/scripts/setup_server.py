"""
Script per setup del server.

Crea database, utente admin, ecc.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'server'))

from server.app import app, db
from server.models import User

def setup():
    with app.app_context():
        db.create_all()

        # Crea utente admin
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', is_admin=True)
            admin.set_password('adminpassword')
            db.session.add(admin)
            db.session.commit()

        print('Server setup complete.')
        print('Admin user created: username=admin, password=adminpassword')

if __name__ == '__main__':
    setup()
#!/usr/bin/env python3
"""
Migration script to add email verification fields to users table.

This adds the following columns:
- email_verified: Boolean flag indicating if email has been verified
- verification_token: Token sent via email for verification
- verification_token_expires: Expiration timestamp for the token

Run from server directory:
    python ../scripts/migrate_email_verification.py
"""
import sys
import os

# Add parent directory to path to import server modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from app import app, db
from sqlalchemy import text


def migrate():
    """Add email verification columns to users table."""
    with app.app_context():
        # Check if columns already exist
        result = db.session.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'email_verified'
        """))
        
        if result.fetchone():
            print("✓ email_verified column already exists")
        else:
            print("Adding email_verified column...")
            db.session.execute(text("""
                ALTER TABLE users 
                ADD COLUMN email_verified BOOLEAN DEFAULT FALSE
            """))
            print("✓ email_verified column added")
        
        # Check verification_token
        result = db.session.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'verification_token'
        """))
        
        if result.fetchone():
            print("✓ verification_token column already exists")
        else:
            print("Adding verification_token column...")
            db.session.execute(text("""
                ALTER TABLE users 
                ADD COLUMN verification_token VARCHAR(100)
            """))
            print("✓ verification_token column added")
        
        # Check verification_token_expires
        result = db.session.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'verification_token_expires'
        """))
        
        if result.fetchone():
            print("✓ verification_token_expires column already exists")
        else:
            print("Adding verification_token_expires column...")
            db.session.execute(text("""
                ALTER TABLE users 
                ADD COLUMN verification_token_expires TIMESTAMP
            """))
            print("✓ verification_token_expires column added")
        
        # Set existing users as verified (they registered before verification was required)
        print("\nSetting existing users as email_verified=True...")
        result = db.session.execute(text("""
            UPDATE users 
            SET email_verified = TRUE 
            WHERE email_verified IS NULL OR email_verified = FALSE
        """))
        print(f"✓ Updated {result.rowcount} existing users to verified")
        
        db.session.commit()
        print("\n✅ Migration completed successfully!")


if __name__ == '__main__':
    migrate()

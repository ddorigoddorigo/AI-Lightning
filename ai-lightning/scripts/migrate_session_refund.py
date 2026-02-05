#!/usr/bin/env python3
"""
Migration script to add refund-related columns to sessions table.

Run this script on the server to add the new columns:
    python scripts/migrate_session_refund.py

This adds:
    - started_at: When the node confirmed session was ready
    - ended_at: When the session ended
    - refunded: Boolean flag if user was refunded
    - refund_amount: Amount refunded in satoshis
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.app import app, db


def migrate():
    """Add refund columns to sessions table."""
    with app.app_context():
        # Get raw connection for ALTER TABLE
        connection = db.engine.raw_connection()
        cursor = connection.cursor()
        
        try:
            # Check if columns already exist
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'sessions' AND column_name = 'started_at'
            """)
            
            if cursor.fetchone():
                print("Columns already exist. Nothing to do.")
                return
            
            print("Adding new columns to sessions table...")
            
            # Add started_at column
            cursor.execute("""
                ALTER TABLE sessions 
                ADD COLUMN IF NOT EXISTS started_at TIMESTAMP NULL
            """)
            print("  - Added started_at column")
            
            # Add ended_at column
            cursor.execute("""
                ALTER TABLE sessions 
                ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP NULL
            """)
            print("  - Added ended_at column")
            
            # Add refunded column
            cursor.execute("""
                ALTER TABLE sessions 
                ADD COLUMN IF NOT EXISTS refunded BOOLEAN DEFAULT FALSE
            """)
            print("  - Added refunded column")
            
            # Add refund_amount column
            cursor.execute("""
                ALTER TABLE sessions 
                ADD COLUMN IF NOT EXISTS refund_amount INTEGER DEFAULT 0
            """)
            print("  - Added refund_amount column")
            
            connection.commit()
            print("\nMigration completed successfully!")
            
        except Exception as e:
            connection.rollback()
            print(f"Error during migration: {e}")
            raise
        finally:
            cursor.close()
            connection.close()


if __name__ == '__main__':
    migrate()

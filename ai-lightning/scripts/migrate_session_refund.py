#!/usr/bin/env python3
"""
Migration script to add refund-related columns to sessions table.

Run this script on the server:
    cd /opt/AI-Lightning/ai-lightning/server
    source venv/bin/activate
    python -c "import psycopg2; conn = psycopg2.connect('postgresql://ailightning:ailightning@localhost/ailightning'); cur = conn.cursor(); cur.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMP NULL'); cur.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMP NULL'); cur.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refunded BOOLEAN DEFAULT FALSE'); cur.execute('ALTER TABLE sessions ADD COLUMN IF NOT EXISTS refund_amount INTEGER DEFAULT 0'); conn.commit(); print('Migration done!')"

Or run this script directly with environment variables:
    DATABASE_URL=postgresql://ailightning:ailightning@localhost/ailightning python scripts/migrate_session_refund.py
"""
import os
import sys

# Try to get database URL from environment or use default
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://ailightning:ailightning@localhost/ailightning')

try:
    import psycopg2
except ImportError:
    print("psycopg2 not found. Install with: pip install psycopg2-binary")
    sys.exit(1)


def migrate():
    """Add refund columns to sessions table."""
    print(f"Connecting to database...")
    
    connection = psycopg2.connect(DATABASE_URL)
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
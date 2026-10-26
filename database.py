import sqlite3

DB_FILE = 'eventpulse.db'


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_db(c):
    """Safely adds missing columns to existing tables without deleting data."""
    # Check Events table
    c.execute("PRAGMA table_info(events)")
    columns = [column[1] for column in c.fetchall()]

    if 'event_type' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN event_type TEXT DEFAULT 'Conference'")
    if 'invite_image' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN invite_image TEXT")
    if 'hall' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN hall TEXT")

    # Check Guests table
    c.execute("PRAGMA table_info(guests)")
    g_columns = [column[1] for column in c.fetchall()]
    if 'ticket_hash' not in g_columns:
        c.execute("ALTER TABLE guests ADD COLUMN ticket_hash TEXT")


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT, assigned_event_id INTEGER)''')

    c.execute('''CREATE TABLE IF NOT EXISTS events 
                 (id INTEGER PRIMARY KEY, title TEXT, date TEXT, time TEXT, location TEXT, hall TEXT, host TEXT, event_type TEXT, invite_image TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS guests 
                 (id INTEGER PRIMARY KEY, event_id INTEGER, name TEXT, phone TEXT, channel TEXT, 
                 status TEXT DEFAULT 'Pending', ticket_hash TEXT UNIQUE, checked_in BOOLEAN DEFAULT 0, 
                 reminder_sent BOOLEAN DEFAULT 0, invite_sent BOOLEAN DEFAULT 0)''')

    # Run the migration to fix old databases
    migrate_db(c)

    c.execute("SELECT * FROM users WHERE email='admin@eventpulse.com'")
    if not c.fetchone():
        c.execute("INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                  ('Super Admin', 'admin@eventpulse.com', 'admin123', 'admin'))
        c.execute("INSERT INTO users (name, email, password, role, assigned_event_id) VALUES (?, ?, ?, ?, ?)",
                  ('Gate Scanner', 'scanner@eventpulse.com', 'scan123', 'verifier', 1))

    conn.commit()
    conn.close()
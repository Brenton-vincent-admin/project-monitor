import sqlite3
from pathlib import Path
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token TEXT NOT NULL,
                in_rotation INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 0,
                cooldown_until TEXT,
                last_used_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        # Migration: add is_active column if missing
        try:
            self.conn.execute("SELECT is_active FROM accounts LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0")
        columns = {row[1] for row in self.conn.execute('PRAGMA table_info(accounts)')}
        for name in ('usage_json', 'usage_checked_at', 'usage_error', 'usage_attempted_at'):
            if name not in columns:
                self.conn.execute(f'ALTER TABLE accounts ADD COLUMN {name} TEXT')
        self.conn.commit()

    def add_account(self, name, token):
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO accounts (name, token, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, token, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def remove_account(self, account_id):
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()

    def update_account(self, account_id, **kwargs):
        allowed = {"name", "token", "in_rotation", "is_active", "cooldown_until", "last_used_at",
                   "usage_json", "usage_checked_at", "usage_error", "usage_attempted_at"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if 'token' in fields:
            fields.update(usage_json=None, usage_checked_at=None, usage_error=None, usage_attempted_at=None)
        if not fields:
            return
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [account_id]
        self.conn.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)
        self.conn.commit()

    def set_active(self, account_id):
        """Mark one account as active, all others as inactive."""
        self.conn.execute("UPDATE accounts SET is_active = 0")
        self.conn.execute("UPDATE accounts SET is_active = 1 WHERE id = ?", (account_id,))
        self.conn.commit()

    def clear_active(self):
        self.conn.execute("UPDATE accounts SET is_active = 0")
        self.conn.commit()

    def get_active_account(self):
        return self.conn.execute(
            "SELECT * FROM accounts WHERE is_active = 1 LIMIT 1"
        ).fetchone()

    def get_next_available(self):
        """Prefer fresh capacity, excluding known limits and local cooldowns."""
        candidates = self.conn.execute(
            """SELECT * FROM accounts
               WHERE in_rotation = 1
                 AND is_active = 0
               ORDER BY
                 CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END,
                 last_used_at ASC
               """,
        ).fetchall()
        from app.usage import usage_view
        ranked = []
        for account in candidates:
            usage = usage_view(account)
            if usage['blocked']:
                continue
            rank = {'Ready': 0, 'Nearly used up': 1}.get(usage['state'], 2)
            ranked.append((rank, -usage['remaining'] if rank < 2 else 0, account))
        ranked.sort(key=lambda value: value[:2])
        return ranked[0][2] if ranked else None

    def toggle_rotation(self, account_id):
        row = self.conn.execute(
            "SELECT in_rotation FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row:
            new_val = 0 if row["in_rotation"] else 1
            self.update_account(account_id, in_rotation=new_val)

    def get_account(self, account_id):
        return self.conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()

    def get_all_accounts(self):
        return self.conn.execute(
            "SELECT * FROM accounts ORDER BY is_active DESC, name"
        ).fetchall()

    def get_accounts_in_rotation(self):
        return self.conn.execute(
            "SELECT * FROM accounts WHERE in_rotation = 1 ORDER BY name"
        ).fetchall()

    def mark_used(self, account_id):
        now = datetime.now(timezone.utc).isoformat()
        self.update_account(account_id, last_used_at=now)

    def close(self):
        self.conn.close()

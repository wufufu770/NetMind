from __future__ import annotations
import sqlite3, json
from pathlib import Path
from typing import Any

class SQLiteEventStore:
    """Optional lightweight SQLite store for deployments that want a real DB file.
    The default packaged app uses JSON persistence for zero setup; this class is
    ready to be wired by replacing STORE in app.store or by later SQLAlchemy migration.
    """
    def __init__(self, path: str = 'data/netmind.sqlite3'):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn=sqlite3.connect(self.path)
        self.conn.execute('create table if not exists kv (namespace text, key text, value text, primary key(namespace,key))')
        self.conn.commit()
    def put(self, namespace: str, key: str, value: Any):
        self.conn.execute('replace into kv(namespace,key,value) values(?,?,?)',(namespace,key,json.dumps(value,ensure_ascii=False)))
        self.conn.commit()
    def get(self, namespace: str, key: str, default=None):
        row=self.conn.execute('select value from kv where namespace=? and key=?',(namespace,key)).fetchone()
        return json.loads(row[0]) if row else default
    def list(self, namespace: str):
        return [json.loads(r[0]) for r in self.conn.execute('select value from kv where namespace=?',(namespace,)).fetchall()]

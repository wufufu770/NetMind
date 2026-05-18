
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from ..store import STORE, DATA_PATH

class RepositoryStatus:
    def status(self):
        mode=os.getenv('NETMIND_STORE','json')
        return {
            'active_store': mode,
            'json_store_path': str(DATA_PATH),
            'json_store_exists': DATA_PATH.exists(),
            'postgres_ready': bool(os.getenv('DATABASE_URL')),
            'sqlalchemy_adapter': 'documented_optional',
            'redis_ready': bool(os.getenv('REDIS_URL')),
            'fallback': 'json-store + in-process event bus',
        }
    def sqlite_probe(self):
        path=Path(os.getenv('NETMIND_SQLITE_FILE','/tmp/netmind_probe.sqlite3'))
        con=sqlite3.connect(path)
        con.execute('create table if not exists health(id integer primary key, ok integer)')
        con.execute('insert into health(ok) values(1)')
        con.commit()
        count=con.execute('select count(*) from health').fetchone()[0]
        con.close()
        return {'ok': True, 'path': str(path), 'rows': count}

REPOSITORY_STATUS=RepositoryStatus()

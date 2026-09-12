"""Small durable experiment ledger; cached failures never imply new measurements."""
import hashlib
import json
import sqlite3
import time
import threading
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock=threading.RLock()
        self.db = sqlite3.connect(path,check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, payload TEXT, created REAL, PRIMARY KEY(kind,key))')
        self.db.commit()

    def put(self, kind, key, value):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?)', (kind, key, json.dumps(value), time.time()))
            self.db.commit()

    def get(self, kind, key, max_age=None):
        row = self.db.execute('SELECT payload,created FROM records WHERE kind=? AND key=?', (kind,key)).fetchone()
        if not row or (max_age is not None and time.time()-row[1] > max_age):
            return None
        return json.loads(row[0])

    def failure(self, key, versioned=False):
        result = self.get('failure', key, None if versioned else 7*86400)
        return result if result and result.get('status') == 'quality_failure' else None

    def close(self):
        self.db.close()

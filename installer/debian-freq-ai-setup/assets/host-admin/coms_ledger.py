"""Fixed read-only Discord metadata queries, executed as freq-discord."""
import json
from pathlib import Path
import sqlite3
import sys

def query(action,filename=None):
    path=Path('/var/lib/freq-discord/deliveries.sqlite')
    if path.is_symlink():raise ValueError('Unsafe ledger')
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=3)
    try:
        if action=='health':return dict(db.execute('SELECT substr(status,1,40),count(*) FROM deliveries GROUP BY status LIMIT 10'))
        row=db.execute('SELECT substr(digest,1,64),substr(status,1,40) FROM deliveries WHERE name=?',(filename,)).fetchone()
        result={'filename':filename,'state':'DISCORD_POSTED' if row and row[1]=='posted' else 'DELIVERY_UNCERTAIN' if row else 'NO_ATTEMPT_RECORDED',
                'envelope_sha256':row[0] if row else None,'human_read_claimed':False}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_receipts'").fetchone():
            r=db.execute('SELECT substr(remote_id,1,80),substr(boundary,1,80),substr(updated_at,1,80) FROM delivery_receipts WHERE name=?',(filename,)).fetchone()
            if r:result.update(discord_message_id=r[0],discord_boundary=r[1],discord_updated_at=r[2])
        return result
    finally:db.close()

if __name__=='__main__':print(json.dumps(query(*sys.argv[1:])))

"""Rebuild the isolated remote-test client from reviewed readable sources."""
from pathlib import Path
import hashlib
import sys
ROOT=Path(__file__).resolve().parent
NAMES=('phase_event_fixture','phase_reader_fixture','phase_client_fixture','visibility_model','_freq_payload_client')
def render():
    specs=[]
    for name in NAMES:
        text=(ROOT/'source'/(name+'.py')).read_text(encoding='utf-8')
        compile(text,name,'exec')
        specs.append((name,hashlib.sha256(text.encode()).hexdigest(),text))
    return (ROOT/'loader.py.in').read_text(encoding='utf-8').replace('@SPECS@',repr(specs)).encode()
if __name__=='__main__':
    data=render();target=ROOT/'client.py'
    if '--check' in sys.argv:
        if target.read_bytes()!=data: raise SystemExit('Embedded client differs from source; rebuild required')
    else: target.write_bytes(data)

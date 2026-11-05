"""A changed header must invalidate objects even when every mtime is unchanged."""
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from compiler_cache import prepare,complete,guest_abi
class ContentCache(unittest.TestCase):
 def test_content_and_failed_build_boundaries(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   p=Path(tmp);h=p/'host.o';g=p/'guest.o';header=p/'cpu.h';header.write_text('old')
   current=dict(host='host1',guest=guest_abi(p,['cpu.h']))
   h.write_bytes(b'old');g.write_bytes(b'old')
   state=prepare(p,current,[h],[g]);self.assertFalse(h.exists() or g.exists());complete(state,current)
   h.write_bytes(b'good');g.write_bytes(b'good');state=prepare(p,current,[h],[g]);self.assertTrue(h.exists() and g.exists());complete(state,current)
   changed=dict(current,host='host2');state=prepare(p,changed,[h],[g]);self.assertFalse(h.exists());self.assertTrue(g.exists())
   # Simulate interruption: no complete() call; both caches must be invalid next time.
   h.write_bytes(b'partial');state=prepare(p,changed,[h],[g]);self.assertFalse(h.exists() or g.exists());complete(state,changed)
   h.write_bytes(b'good');g.write_bytes(b'good');header.write_text('new')
   changed=dict(changed,guest=guest_abi(p,['cpu.h']));state=prepare(p,changed,[h],[g]);self.assertTrue(h.exists());self.assertFalse(g.exists());complete(state,changed)

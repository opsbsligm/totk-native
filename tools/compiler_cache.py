"""Invalidate compiler objects by content, including deterministic source archives."""
# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path


def guest_abi(root, names):
    h=hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode()+b'\0'+hashlib.sha256((root/name).read_bytes()).digest())
    return h.hexdigest()


def prepare(out, current, host_objects, guest_objects):
    state=out/'compiler-inputs.json'
    try: previous=json.loads(state.read_text())
    except (OSError,ValueError): previous={}
    # An interrupted build must never leave a valid reuse marker.
    state.unlink(missing_ok=True)
    stale=[]
    if previous.get('host')!=current['host']:stale.extend(host_objects)
    if previous.get('guest')!=current['guest']:stale.extend(guest_objects)
    for p in set(stale):
        if p.is_symlink():raise ValueError('Compiler cache contains a symlink')
        p.unlink(missing_ok=True)
    return state


def complete(state, current):
    temp=state.with_suffix('.json.new')
    temp.write_text(json.dumps(current,sort_keys=True)+'\n');temp.replace(state)

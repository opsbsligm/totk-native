"""Fetch, authenticate, restore and rebuild one personal game on a Linux host."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import shutil

ROOT=Path(__file__).resolve().parents[1]
PROJECT=20


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='https://gitlab.example.com:8445')
    p.add_argument('--version',required=True)
    p.add_argument('--token-file',required=True,type=Path)
    p.add_argument('--identity',required=True,type=Path)
    p.add_argument('--work',required=True,type=Path)
    p.add_argument('--jobs',type=int,choices=(1,2,3,4),default=2)
    a=p.parse_args()
    work=a.work.absolute()
    if work.exists() or work.is_symlink(): p.error('Choose a new external work directory; no existing state is overwritten')
    if ROOT==work or ROOT in work.parents or work in ROOT.parents:p.error('Work must be outside the checkout')
    if any(v.is_symlink() for v in work.parents):p.error('Symlink output parent refused')
    existing=next(parent for parent in work.parents if parent.exists())
    if shutil.disk_usage(existing).free < 160*1024**3:p.error('Recovery plus build needs at least 160 GiB free on the work volume')
    os.umask(0o077);work.mkdir(parents=True,mode=0o700)
    def run(*args):subprocess.run([sys.executable,*map(str,args)],check=True)
    run(ROOT/'tools/recovery_gitlab.py','fetch','--url',a.url,'--project',PROJECT,'--version',a.version,
        '--token-file',a.token_file,'--bundle',work/'encrypted')
    index=json.loads((work/'encrypted/index.json').read_text())
    if index.get('schema')==2:
        restored={}
        for item in index['components']:
            role=item['role'];bundle=work/('encrypted-'+role);target=work/('restored-'+role)
            run(ROOT/'tools/recovery_gitlab.py','fetch','--url',a.url,'--project',PROJECT,'--version',item['version'],
                '--token-file',a.token_file,'--bundle',bundle)
            if hashlib.sha256((bundle/'index.json').read_bytes()).hexdigest()!=item['index_sha256']:
                raise SystemExit('Recovery component index differs from the selected immutable set')
            run(ROOT/'tools/recovery.py','restore','--bundle',bundle,'--identity',a.identity,'--destination',target)
            restored[role]=target
        base=restored['base'];receipt=json.loads((base/'recovery-receipt.json').read_text())
        missing=set(receipt['missing'])
        for role,condition in (('fonts','system-shared-fonts-6'),('romfs','healthy-complete-romfs')):
            if role not in restored:continue
            supplement=json.loads((restored[role]/'recovery-receipt.json').read_text())
            if supplement['missing']:raise SystemExit('Recovery supplement is incomplete')
            source=restored[role]/role;destination=base/'dump'/role
            if destination.exists() or destination.is_symlink():raise SystemExit('Recovery components overlap')
            os.rename(source,destination)
            missing.discard(condition)
        os.rename(base,work/'restored')
        if missing:raise SystemExit('Recovery is still missing: '+', '.join(sorted(missing)))
    else:
        run(ROOT/'tools/recovery.py','restore','--bundle',work/'encrypted','--identity',a.identity,'--destination',work/'restored')
        receipt=json.loads((work/'restored/recovery-receipt.json').read_text())
        if receipt['missing']:
            raise SystemExit('Recovery authenticated and restored; build blocked by recorded missing inputs: '+', '.join(receipt['missing']))
    # The include label is part of the authenticated archive: production bundles
    # use dump/, while standalone runtime bundles can use runtime/ or the root.
    entries = [work/'restored'/prefix/'run.sh' for prefix in ('', 'dump', 'runtime')]
    entries = [entry for entry in entries if entry.exists() or entry.is_symlink()]
    if len(entries) > 1:
        raise SystemExit('Ambiguous portable runtime entries; select a bundle with one run.sh')
    if entries:
        entry = entries[0]
        if entry.is_symlink() or not entry.is_file() or not os.access(entry, os.X_OK):
            raise SystemExit('Portable runtime entry is not a regular executable; reseal with schema 3')
        subprocess.run([str(entry), '--verify'], check=True)
        print(str(entry))
        return
    dump=work/'restored/dump'
    run(ROOT/'build.py','doctor','--dump',dump,'--work',work/'build')
    run(ROOT/'build.py','build','--dump',dump,'--work',work/'build','--jobs',a.jobs)
    subprocess.run([str(work/'build/package/run.sh'),'--verify'],check=True)
    print(str(work/'build/package/run.sh'))


if __name__=='__main__':main()

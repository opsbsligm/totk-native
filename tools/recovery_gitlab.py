"""Fetch/publish encrypted generic packages with streaming readback validation.

Only HTTPS, a private GitLab project and an authenticated user are accepted.
Tokens are read from owner-only files, never arguments, archive members or logs.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from urllib.parse import urlsplit, quote

BLOCK=1024*1024


def payload_schema(index):
    if not isinstance(index,dict):
        raise ValueError('Invalid recovery payload schema')
    version=index.get('schema')
    if type(version) is not int or version not in (1,3) or (version==3 and index.get('kind')!='native-recovery-bundle'):
        raise ValueError('Unsupported recovery payload schema')
    return version


class GitLab:
    def __init__(self,url,token_file,project):
        self.url=urlsplit(url)
        if self.url.scheme!='https' or not self.url.hostname or self.url.path not in ('','/') or self.url.username or self.url.query or self.url.fragment:
            raise ValueError('Expected an HTTPS GitLab origin, without credentials or a path')
        path=Path(token_file)
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid!=os.geteuid():
            raise ValueError('Token file must be a regular owner-only file')
        self.token=path.read_text().strip();self.project=project
        if not self.token or '\n' in self.token or '\r' in self.token:
            raise ValueError('Invalid token file')
        user=json.loads(self.get('/user',limit=1024*1024))
        if not isinstance(user.get('id'),int): raise ValueError('Identity verification failed')
        details=json.loads(self.get(f'/projects/{project}',limit=1024*1024))
        if details.get('id')!=project or details.get('visibility')!='private':
            raise ValueError('Recovery packages require a verified private project')

    def connection(self):
        return http.client.HTTPSConnection(self.url.hostname,self.url.port or 443,timeout=120)

    def get(self,path,output=None,limit=1024**4):
        connection=self.connection()
        try:
            connection.request('GET','/api/v4'+path,headers={'PRIVATE-TOKEN':self.token})
            response=connection.getresponse()
            if response.status!=200: raise ValueError('GitLab download failed (HTTP '+str(response.status)+')')
            result=bytearray();sha=hashlib.sha256();size=0
            while block:=response.read(BLOCK):
                size+=len(block)
                if size>limit: raise ValueError('Download exceeds expected size')
                sha.update(block)
                if output: output.write(block)
                else: result.extend(block)
            return (size,sha.hexdigest()) if output else bytes(result)
        finally:
            connection.close()

    def put(self,path,file):
        connection=self.connection()
        try:
            size=file.stat().st_size
            connection.putrequest('PUT','/api/v4'+path)
            connection.putheader('PRIVATE-TOKEN',self.token)
            connection.putheader('Content-Type','application/octet-stream')
            connection.putheader('Content-Length',str(size));connection.endheaders()
            with file.open('rb') as stream:
                while block:=stream.read(BLOCK): connection.send(block)
            response=connection.getresponse();response.read(4096)
            if response.status!=201: raise ValueError('GitLab upload failed (HTTP '+str(response.status)+')')
        finally:
            connection.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('fetch','publish'))
    p.add_argument('--url',required=True);p.add_argument('--project',required=True,type=int)
    p.add_argument('--version',required=True);p.add_argument('--token-file',required=True)
    p.add_argument('--bundle',required=True,type=Path)
    a=p.parse_args()
    if not re.fullmatch('[a-zA-Z0-9._-]{1,120}',a.version): p.error('Invalid version')
    api=GitLab(a.url,a.token_file,a.project)
    prefix=f'/projects/{a.project}/packages/generic/private-recovery/{quote(a.version)}/'
    os.umask(0o077)
    if a.command=='fetch':
        if a.bundle.exists() or a.bundle.is_symlink(): raise ValueError('Use a new bundle directory')
        a.bundle.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.download-',dir=a.bundle.parent))
        try:
            raw=api.get(prefix+'index.json',limit=1024*1024);index=json.loads(raw)
            if not isinstance(index,dict): raise ValueError('Invalid bundle index')
            if index.get('schema')==2 and index.get('kind')=='native-recovery-set':
                components=index.get('components',[])
                if not 1<=len(components)<=3 or components[0].get('role')!='base':
                    raise ValueError('Invalid recovery set')
                roles=set()
                for item in components:
                    if item.get('role') not in ('base','fonts','romfs') or item['role'] in roles or not re.fullmatch('[a-zA-Z0-9._-]{1,120}',item.get('version','')) or not re.fullmatch('[0-9a-f]{64}',item.get('index_sha256','')):
                        raise ValueError('Invalid recovery component')
                    roles.add(item['role'])
                (stage/'index.json').write_bytes(raw)
                os.rename(stage,a.bundle)
                return
            payload_schema(index)
            if not 0<len(index.get('parts',[]))<=10000:
                raise ValueError('Invalid bundle index')
            total=0
            for i,item in enumerate(index['parts']):
                if item['name']!=f'payload-{i:05d}.age.part' or not 0<item['bytes']<=512*1024*1024:
                    raise ValueError('Invalid bundle part')
                total+=item['bytes']
            if shutil.disk_usage(stage).free < total+1024**3: raise ValueError('Insufficient free disk space')
            for i,item in enumerate(index['parts']):
                with (stage/item['name']).open('xb') as output:
                    size,sha=api.get(prefix+item['name'],output,limit=item['bytes'])
                if size!=item['bytes'] or sha!=item['sha256']: raise ValueError('Download checksum mismatch')
                print(json.dumps(dict(phase='downloaded',part=i+1,total=len(index['parts']))),flush=True)
            (stage/'index.json').write_bytes(raw)
            os.rename(stage,a.bundle)
        finally:
            if stage.exists(): shutil.rmtree(stage)
    else:
        raw=(a.bundle/'index.json').read_bytes();index=json.loads(raw)
        payload_schema(index)
        for i,item in enumerate(index['parts']):
            if item['name']!=f'payload-{i:05d}.age.part': raise ValueError('Invalid bundle part')
            path=a.bundle/item['name']
            with path.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=item['bytes'] or sha!=item['sha256']: raise ValueError('Local bundle changed')
            api.put(prefix+item['name'],path)
            # Read back every ciphertext byte, without a second disk copy.
            with open(os.devnull,'wb') as output: size,sha=api.get(prefix+item['name'],output,limit=item['bytes'])
            if (size,sha)!=(item['bytes'],item['sha256']): raise ValueError('Published package checksum mismatch')
            print(json.dumps(dict(phase='published-verified',part=i+1,total=len(index['parts']))),flush=True)
        api.put(prefix+'index.json',a.bundle/'index.json')
        if api.get(prefix+'index.json',limit=1024*1024)!=raw: raise ValueError('Index readback mismatch')


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError) as error: raise SystemExit(str(error))

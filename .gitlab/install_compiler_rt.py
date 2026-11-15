import subprocess,os,json,pathlib,urllib.parse,shlex,hashlib,shutil,resource
resource.setrlimit(resource.RLIMIT_CORE,(0,0));assert os.geteuid()==0;os.environ['DEBIAN_FRONTEND']='noninteractive'
def run(args,timeout=75):
 r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if r.returncode:print(r.stdout[-3000:]+r.stderr[-3000:],flush=True);raise SystemExit(r.returncode)
 return r.stdout
version_field='$'+'{Version}'
version=run(['dpkg-query','-W','-f',version_field,'clang-18']).strip();assert version=='1:18.1.3-1ubuntu1'
source=pathlib.Path('/etc/apt/sources.list.d/ubuntu.sources');raw=source.read_text();new=raw.replace('http://archive.ubuntu.com/ubuntu','https://archive.ubuntu.com/ubuntu').replace('http://security.ubuntu.com/ubuntu','https://security.ubuntu.com/ubuntu')
urls=[u for l in new.splitlines()if l.startswith('URIs:')for u in l.split()[1:]]
assert urls and all(urllib.parse.urlsplit(u).scheme=='https'and urllib.parse.urlsplit(u).hostname in ['archive.ubuntu.com','security.ubuntu.com']and urllib.parse.urlsplit(u).username is None for u in urls)
source.write_text(new);apt=['apt-get','-o','Acquire::Retries=2','-o','Acquire::https::Timeout=20','-o','APT::Update::Error-Mode=any'];run(apt+['update'])
package='libclang-rt-18-dev='+version;plan=run(apt+['--print-uris','--yes','--no-install-recommends','install',package],timeout=15);downloads=[]
for line in plan.splitlines():
 if line.startswith("'"):
  items=shlex.split(line);u=urllib.parse.urlsplit(items[0]);assert u.scheme=='https'and u.hostname in ['archive.ubuntu.com','security.ubuntu.com'];downloads.append(int(items[2]))
assert downloads and sum(downloads)<=128*2**20
run(apt+['install','--yes','--no-install-recommends',package])
installed=run(['dpkg-query','-W','-f',version_field,'libclang-rt-18-dev']).strip();assert installed==version==run(['dpkg-query','-W','-f',version_field,'clang-18']).strip()
root=pathlib.Path(run(['clang','-print-resource-dir']).strip())/'lib/linux';libraries={}
for name in ['libclang_rt.asan_static-x86_64.a','libclang_rt.asan-x86_64.a','libclang_rt.ubsan_standalone-x86_64.a']:
 p=root/name;assert p.is_file();libraries[name]=hashlib.sha256(p.read_bytes()).hexdigest()
for folder in ['/var/lib/apt/lists','/var/cache/apt/archives']:
 for child in pathlib.Path(folder).iterdir():
  if child.is_dir()and not child.is_symlink():shutil.rmtree(child)
  else:child.unlink()
print('PROVIDER_RESULT '+json.dumps({'compiler_version':version,'runtime_version':installed,'download_bytes':sum(downloads),'libraries_sha256':libraries,'source_https':True}),flush=True)

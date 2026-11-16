"""Discover hook definitions in an installed Codex app-server; no model or hook execution.

CLI overrides supply definitions for this process only. Hook trust is not granted.
"""
import argparse, json, pathlib, queue, shutil, subprocess, sys, tempfile, threading, time
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--codex', default=shutil.which('codex'), help='Installed Codex executable')
args=parser.parse_args()
if not args.codex: parser.error('Use --codex /path/to/codex')
binary=args.codex
version=subprocess.check_output([binary,'--version'],text=True).strip()
repo=pathlib.Path(__file__).resolve().parents[1]
temporary=tempfile.TemporaryDirectory(prefix='experience-codex-discovery-')
project=pathlib.Path(temporary.name).resolve()
subprocess.run([sys.executable,str(repo/'adapters/codex/install.py'),'--root',str(project)],check=True,stdout=subprocess.DEVNULL)
def toml(v):
 if isinstance(v,str): return json.dumps(v)
 if isinstance(v,bool): return 'true' if v else 'false'
 if isinstance(v,(int,float)): return str(v)
 if isinstance(v,list): return '['+', '.join(toml(x) for x in v)+']'
 if isinstance(v,dict): return '{'+', '.join(json.dumps(k)+' = '+toml(x) for k,x in v.items())+'}'
 raise ValueError(type(v))
config=json.loads((project/'.codex/hooks.json').read_text())
args=[binary,'app-server','--stdio','-c','hooks='+toml(config['hooks'])]
proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(project))
messages=queue.Queue(); logs=[]
def read():
 for line in proc.stdout:
  try: messages.put(json.loads(line))
  except ValueError: pass
def stderr():
 for line in proc.stderr: logs.append(line)
threading.Thread(target=read,daemon=True).start(); threading.Thread(target=stderr,daemon=True).start()
def send(message):
 proc.stdin.write(json.dumps(message)+'\n');proc.stdin.flush()
def until(id):
 limit=time.monotonic()+25
 while time.monotonic()<limit:
  if proc.poll() is not None: raise RuntimeError('Server exited: '+repr(logs[-3:]))
  try: item=messages.get(timeout=1)
  except queue.Empty: continue
  if item.get('id')==id:return item
 raise RuntimeError('RPC timeout; process='+str(proc.poll())+' stderr='+repr(logs[-3:]))
try:
 send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'experience_harness_discovery_test','version':'0.2.0'},'capabilities':{'experimentalApi':True}}})
 init=until(1)
 if 'error' in init: raise RuntimeError(init['error'])
 send({'method':'initialized','params':{}})
 send({'id':2,'method':'hooks/list','params':{'cwds':[str(project)]}})
 result=until(2)
 if 'error' in result: raise RuntimeError(result['error'])
 entry=result['result']['data'][0]
 hooks=[h for h in entry['hooks'] if '--adapter-id=experience-strategy-harness' in h.get('command','')]
 report={'host':version,'fixture':'temporary project; hook definitions passed as CLI inline config; no project or hook trust granted','method':'hooks/list','events':sorted(h['eventName'] for h in hooks),'trust_statuses':sorted(set(h['trustStatus'] for h in hooks)),'errors':entry['errors'],'hooks_executed':False,'model_calls':0,'global_config_modified':False}
 assert len(hooks)==7,report
 assert not entry['errors'],report
 assert all(h['trustStatus']=='untrusted' for h in hooks),report
 print(json.dumps(report,ensure_ascii=False,indent=2))

finally:
 proc.terminate()
 try:proc.wait(timeout=5)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()

 temporary.cleanup()

#!/usr/bin/env python3
"""Optional read-only operator probe. Never emits raw logs, argv or configs."""
import collections,datetime,json,pathlib,re,time
LOGS=pathlib.Path('/etc/smite-node/frp')
patterns={
 'control_close':re.compile(r'control.*(?:clos|exit)|(?:clos|exit).*control',re.I),
 'relogin':re.compile(r'login to server success|try to reconnect|reconnect to server',re.I),
 'dispatcher':re.compile(r'dispatcher',re.I),
 'req_work_conn':re.compile(r'ReqWorkConn|request.*work connection',re.I),
 'heartbeat_timeout':re.compile(r'heartbeat.*timeout',re.I),
 'write_timeout':re.compile(r'connection write timeout',re.I),
 'work_conn_unavailable':re.compile(r'failed to get work connection',re.I),
 'network_error':re.compile(r'connection reset|broken pipe|no route to host|i/o timeout',re.I)}
offsets={}
# Establish offsets; do not reprint historical events as new incident evidence.
for path in LOGS.glob('*.log'):
 if path.is_file() and not path.is_symlink():
  st=path.stat();offsets[path]=(st.st_ino,st.st_size)
for _ in range(24):
 time.sleep(30)
 counts=collections.Counter();rotated=0;truncated=0
 for path in LOGS.glob('*.log'):
  if not path.is_file() or path.is_symlink():continue
  try:
   st=path.stat();inode,pos=offsets.get(path,(st.st_ino,0))
   if inode!=st.st_ino or st.st_size<pos:pos=0;rotated+=1
   if st.st_size-pos>1048576:pos=st.st_size-1048576;truncated+=1
   with path.open('rb') as f:f.seek(pos);raw=f.read(1048576);end=f.tell()
   offsets[path]=(st.st_ino,end)
   for line in raw.decode(errors='replace').splitlines():
    for label,pattern in patterns.items():counts[label]+=bool(pattern.search(line))
  except OSError:counts['log_read_errors']+=1
 processes=collections.Counter()
 for path in pathlib.Path('/proc').glob('[0-9]*/comm'):
  try:name=path.read_text().strip()
  except OSError:continue
  if name in ('frpc','frps'):processes[name]+=1
 net=[0,0,0,0]
 for line in pathlib.Path('/proc/net/dev').read_text().splitlines()[2:]:
  fields=line.split(':',1)[1].split()
  for i,j in enumerate((2,3,10,11)):net[i]+=int(fields[j])
 print(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'new_log_counts':dict(counts),'rotations':rotated,'truncated_windows':truncated,
  'process_counts':dict(processes),'load_1_5_15':pathlib.Path('/proc/loadavg').read_text().split()[:3],
  'net_rx_errors_drops_tx_errors_drops':net}),flush=True)

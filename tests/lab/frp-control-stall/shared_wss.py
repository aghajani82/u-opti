#!/usr/bin/env python3
"""Disposable network:none container. Real FRPS + two FRPCs + Nginx WSS/443.

Fault builds inject a retained WriteMsg error for one control only. The actual
crypto retention/real yamux timeout are tested separately by upstream tests.
No production addresses, credentials, images, config or services are used here.
"""
import hashlib,json,os,pathlib,socket,socketserver,subprocess,sys,tempfile,threading,time
assert os.environ.get('UOPTI_DISPOSABLE_FRP_LAB')=='YES'
assert not pathlib.Path('/etc/u-opti/smite/state.env').exists()
BINS=pathlib.Path('/binaries')
class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(60)
        try:
            while data:=self.request.recv(4096):self.request.sendall(data)
        except (OSError,TimeoutError):pass
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True;daemon_threads=True
backend=Server(('127.0.0.1',18000),Echo)
threading.Thread(target=backend.serve_forever,daemon=True).start()
procs=[]
def stop(p):
    if p.poll() is None:
        p.terminate()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
def connect(port):
    c=socket.create_connection(('127.0.0.1',port),timeout=1);c.settimeout(1);return c
def exchange(c):
    c.sendall(b'isolated-echo\n')
    raw=b''
    while len(raw)<14:
        part=c.recv(14-len(raw))
        if not part:raise OSError('EOF')
        raw+=part
    assert raw==b'isolated-echo\n'
def probe(port):
    try:
        with connect(port) as c:exchange(c)
        return True
    except (OSError,AssertionError):return False
def ready(port,timeout=25):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if probe(port):return
        time.sleep(.15)
    raise AssertionError('PROXY_NOT_READY_'+str(port))
with tempfile.TemporaryDirectory(prefix='frp-wss-lab-') as temp:
    root=pathlib.Path(temp)
    def start(binary,config,label,env=None):
        log=root/(label+'.log')
        with log.open('ab') as out:
            p=subprocess.Popen([str(binary),'-c',str(config)],stdout=out,stderr=subprocess.STDOUT,env=env)
        procs.append(p);return p,log
    def conf(name,text):
        path=root/name;path.write_text(text);return path
    cert=root/'cert.pem';key=root/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
                    '-addext','subjectAltName=DNS:localhost','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    nginx=conf('nginx.conf',f'''pid {root}/nginx.pid;
error_log {root}/nginx.log warn;
events {{ worker_connections 128; }}
http {{ access_log off; client_body_temp_path {root}/body; proxy_temp_path {root}/proxy;
fastcgi_temp_path {root}/fastcgi; uwsgi_temp_path {root}/uwsgi; scgi_temp_path {root}/scgi; server {{ listen 127.0.0.1:443 ssl;
ssl_certificate {cert}; ssl_certificate_key {key};
location = /~!frp {{ proxy_pass http://127.0.0.1:17000; proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";
proxy_read_timeout 3600s; proxy_send_timeout 3600s; proxy_buffering off; }}
}} }}''')
    ng=subprocess.Popen(['nginx','-c',str(nginx),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);procs.append(ng)
    servercfg=conf('frps.toml','''bindAddr = "127.0.0.1"
bindPort = 17000
proxyBindAddr = "127.0.0.1"
userConnTimeout = 2
auth.method = "token"
auth.token = "public-isolated-lab-token"
''')
    def clientcfg(user,port,token='public-isolated-lab-token',sni='localhost'):
        return conf(user+'.toml',f'''user = "{user}"
serverAddr = "127.0.0.1"
serverPort = 443
loginFailExit = false
auth.method = "token"
auth.token = "{token}"
transport.protocol = "wss"
transport.tls.enable = true
transport.tls.trustedCaFile = "{cert}"
transport.tls.serverName = "{sni}"
[[proxies]]
name = "echo"
type = "tcp"
localIP = "127.0.0.1"
localPort = 18000
remotePort = {port}
''')
    ca=clientcfg('lab-a',18001);cb=clientcfg('lab-b',18002)
    config_hashes={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (servercfg,ca,cb)}
    try:
        for version in ('0.71.0','0.71.1'):
            marker=root/'fault';marker.unlink(missing_ok=True);marker.with_name('fault.fired').unlink(missing_ok=True)
            env=dict(os.environ,UOPTI_FRP_LAB_FAULT=str(marker))
            owner,_=start(BINS/version/'frps-fault',servercfg,'owner-'+version,env)
            a,alog=start(BINS/version/'amd64/frpc',ca,'a-'+version)
            b,_=start(BINS/version/'amd64/frpc',cb,'b-'+version)
            ready(18001);ready(18002)
            with connect(18002) as persistent:
                exchange(persistent);marker.write_text('arm')
                # Drain the default prefilled work connection and force refill.
                deadline=time.monotonic()+15
                while not marker.with_name('fault.fired').exists() and time.monotonic()<deadline:probe(18001)
                assert marker.with_name('fault.fired').exists(),'FAULT_NOT_INJECTED'
                owner_pid=owner.pid;client_pid=a.pid
                if version=='0.71.0':
                    failures=0
                    for _ in range(5):
                        failures+=not probe(18001)
                        exchange(persistent);assert probe(18002),'OTHER_CHILD_DISRUPTED'
                    assert failures>=3,'OLD_STALL_NOT_REPRODUCED'
                    assert owner.poll() is None and a.poll() is None,'OLD_PROCESS_EXITED'
                    # Explicit test-only recovery; no owner or other child restart.
                    stop(a);a,_=start(BINS/version/'amd64/frpc',ca,'a-old-recovered')
                    ready(18001)
                    recovery='explicit_child_restart'
                else:
                    ready(18001)
                    deadline=time.monotonic()+15
                    while alog.read_text().count('login to server success')<2 and time.monotonic()<deadline:time.sleep(.1)
                    assert alog.read_text().count('login to server success')>=2,'NO_AUTOMATIC_RELOGIN'
                    assert a.pid==client_pid and a.poll() is None,'CLIENT_PROCESS_RESTARTED'
                    for _ in range(5):assert probe(18001)
                    recovery='automatic_control_reconnect'
                exchange(persistent);assert probe(18002)
                assert owner.pid==owner_pid and owner.poll() is None and b.poll() is None
                print(json.dumps({'version':version,'fault_injected':True,'recovery':recovery,
                                  'shared_owner_pid_preserved':True,'other_child_stream_preserved':True}),flush=True)
            for p in (a,b,owner):stop(p)
            time.sleep(.5)
        # Authentic release binaries, mixed pairs + sequential upgrade/rollback.
        for server_version,client_version in (('0.71.0','0.71.1'),('0.71.1','0.71.0')):
            owner,_=start(BINS/server_version/'amd64/frps',servercfg,'mixed-owner')
            a,_=start(BINS/client_version/'amd64/frpc',ca,'mixed-a')
            b,_=start(BINS/client_version/'amd64/frpc',cb,'mixed-b')
            ready(18001);ready(18002)
            for _ in range(5):assert probe(18001) and probe(18002)
            print(json.dumps({'official_mixed_pair':[server_version,client_version],'wss_two_children':'PASS'}),flush=True)
            for p in (a,b,owner):stop(p)
            time.sleep(.5)
        owner,_=start(BINS/'0.71.0/amd64/frps',servercfg,'rollback-owner-old')
        a,_=start(BINS/'0.71.1/amd64/frpc',ca,'rollback-a')
        b,_=start(BINS/'0.71.1/amd64/frpc',cb,'rollback-b')
        ready(18001);ready(18002)
        # These are disposable owner restarts and cause service interruption.
        for version in ('0.71.1','0.71.0','0.71.1'):
            stop(owner);owner,_=start(BINS/version/'amd64/frps',servercfg,'rollback-owner-'+version)
            ready(18001);ready(18002)
            assert a.poll() is None and b.poll() is None
        for label,token,sni in [('bad-token','wrong','localhost'),('bad-tls','public-isolated-lab-token','wrong.invalid')]:
            bad=clientcfg(label,18003,token,sni)
            subprocess.run([str(BINS/'0.71.1/amd64/frpc'),'verify','-c',str(bad)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            negative,negative_log=start(BINS/'0.71.1/amd64/frpc',bad,label)
            time.sleep(2);assert not probe(18003),'INVALID_AUTH_ACCEPTED'
            rejection=negative_log.read_text().lower()
            assert ('token' in rejection and 'match' in rejection) if label=='bad-token' else 'x509' in rejection, 'WRONG_NEGATIVE_FAILURE_REASON'
            stop(negative)
        assert config_hashes=={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in (servercfg,ca,cb)}
        print('OFFICIAL_UPGRADE_ROLLBACK_RECOVERY=PASS_CONFIG_TOKEN_RETAINED',flush=True)
        print('INVALID_TOKEN_AND_TLS_HOSTNAME=REJECTED',flush=True)
    finally:
        for p in reversed(procs):stop(p)
        backend.shutdown();backend.server_close()

#!/usr/bin/env python3
"""Real Nginx SNI/TLS + real Smite Panel pairing API on isolated PR runner.

Only loopback ports; never modifies system Nginx, Docker, firewall or VPS.
"""
import base64
import http.client
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time

if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_EVENT_NAME") != "pull_request":
    raise SystemExit("HOLD: Only disposable GitHub pull-request runners")
ROOT = Path(__file__).resolve().parents[1]
SMITE = ROOT/".stage20-smite-src"
if not (SMITE/"panel/app/routers/node_pairing.py").is_file():
    raise SystemExit("HOLD: Reviewed Smite source not present")
spec = importlib.util.spec_from_file_location("stage19", ROOT/"modules/smite-stage19-pairing-443-plan.py")
stage19 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage19)
HOST = "ir.stage20.test"

def run(*args, ok=True):
    r = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if ok and r.returncode:
        raise RuntimeError("Isolated command failed: "+str(args[:3])+": "+r.stderr[-400:])
    return r

def check(value, detail):
    if not value: raise AssertionError(detail)

def wait_for(fn, name):
    for _ in range(80):
        try:
            if fn(): return
        except (OSError, ssl.SSLError, ValueError):
            pass
        time.sleep(.2)
    raise AssertionError("Timeout: "+name)

def request(method, path, ctx, data=None, headers=None, name=HOST):
    class Routed(http.client.HTTPSConnection):
        def connect(self):
            s=socket.create_connection(("127.0.0.1",19443),timeout=3)
            self.sock=self._context.wrap_socket(s,server_hostname=self.host)
    c=Routed(name,19443,context=ctx,timeout=5)
    try:
        h=dict(headers or {})
        payload=None if data is None else json.dumps(data).encode()
        if payload is not None: h["Content-Type"]="application/json"
        c.request(method,path,body=payload,headers=h)
        r=c.getresponse()
        raw=r.read()
        try: decoded=json.loads(raw)
        except (ValueError,UnicodeError): decoded=raw.decode("utf-8","replace")
        return r.status,decoded,{k.lower():v for k,v in r.getheaders()}
    finally:
        c.close()

def direct(data, header=""):
    c=http.client.HTTPConnection("127.0.0.1",8000,timeout=5)
    try:
        c.request("POST","/api/node-pairing/redeem",body=json.dumps(data),headers={
            "Content-Type":"application/json","X-Smite-Pairing-Ingress":header})
        r=c.getresponse();r.read();return r.status
    finally: c.close()

def main():
    processes=[]
    with tempfile.TemporaryDirectory(prefix="stage20-sandbox-") as temp:
        root=Path(temp)
        (root/"private").mkdir(mode=0o700)
        candidate=root/"private"/"pairing"
        check(stage19.prepare(domain=HOST,output=candidate)=="PRIVATE_OFFLINE_PAIRING_443_PLAN","stage19")
        envvars={}
        for row in (candidate/"panel-pairing.env").read_text().splitlines():
            if row.startswith("SMITE_") and "=" in row:
                k,v=row.split("=",1);envvars[k]=v
        check(envvars["SMITE_NODE_PAIRING_PREVIEW_ENABLED"]=="false","Preview accidentally enabled")
        envvars["SMITE_NODE_PAIRING_PREVIEW_ENABLED"]="true" # CI process only
        envvars["SMITE_NODE_REGISTRATION_MODE"]="signed"  # CI process only, legacy closed
        env=dict(os.environ)
        env.update(envvars)
        env.update({"PYTHONPATH":str(SMITE/"panel")+os.pathsep+str(ROOT/"tests"/"fixtures"),
                    "DB_PATH":str(root/"data"/"smite.db"),
                    "SECRET_KEY":"stage20-temporary-jwt-"+"e"*32})
        panel=subprocess.Popen([sys.executable,"-m","uvicorn","stage20_pairing_panel:app",
                               "--host","127.0.0.1","--port","8000","--no-access-log",
                               "--log-level","error"],env=env,stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        processes.append(panel)
        try:
            def panel_ready():
                check(panel.poll() is None,"Actual Smite Panel failed startup")
                c=http.client.HTTPConnection("127.0.0.1",8000,timeout=1)
                try:
                    c.request("GET","/api/status")
                    r=c.getresponse();r.read();return r.status==200
                finally:c.close()
            wait_for(panel_ready,"real Panel")
            cert,key=root/"test.crt",root/"test.key"
            run("openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1",
                "-keyout",str(key),"-out",str(cert),"-subj",f"/CN={HOST}",
                "-addext",f"subjectAltName=DNS:{HOST}")
            location=(candidate/"nginx-pairing-location.conf").read_text()
            conf=root/"nginx.conf"
            def config(canary="original"):
                return f"""load_module /usr/lib/nginx/modules/ngx_stream_module.so;
pid {root}/nginx.pid;
error_log {root}/nginx.err warn;
events {{ worker_connections 256; }}
stream {{
    map $ssl_preread_server_name $upstream_sni {{
        {HOST} 127.0.0.1:18443;
        default 127.0.0.1:19444;
    }}
    server {{ listen 127.0.0.1:19443; ssl_preread on;
              proxy_connect_timeout 2s; proxy_pass $upstream_sni; }}
}}
http {{
    access_log off;
    server {{
        listen 127.0.0.1:18443 ssl;
        server_name {HOST};
        ssl_certificate {cert};
        ssl_certificate_key {key};
        location = /stage20-canary {{ return 200 '{canary}'; }}
        {location}
        location / {{
            proxy_http_version 1.1;
            proxy_set_header X-Smite-Pairing-Ingress "";
            proxy_set_header Host $host;
            proxy_pass http://127.0.0.1:8000;
        }}
    }}
}}
"""
            base=config()
            conf.write_text(base)
            def nginx(*argv,ok=True):
                return run("nginx",*argv,"-p",str(root)+"/","-c",str(conf),ok=ok)
            nginx("-t")
            proxy=subprocess.Popen(["nginx","-p",str(root)+"/","-c",str(conf),
                                    "-g","daemon off;"],
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            processes.append(proxy)
            ctx=ssl.create_default_context(cafile=str(cert))
            wait_for(lambda:request("GET","/api/status",ctx)[0]==200,"real TLS/SNI")
            status,body,_=request("GET","/api/status",ctx)
            check(status==200 and body["source"]=="actual-smite-pairing-routers","Panel fallback")
            print("STAGE20_SNI_TLS_AND_REAL_PANEL=PASS")
            status,_,_=request("POST","/api/node-pairing/reserve",ctx,{"name":"node-kh-01"})
            check(status in (401,403),"Anonymous reserve accepted")
            status,login,_=request("POST","/api/auth/login",ctx,{
                "username":"stage20-admin","password":"stage20-disposable-secret"})
            check(status==200 and "access_token" in login,"JWT login")
            auth={"Authorization":"Bearer "+login["access_token"]}
            status,node,_=request("POST","/api/node-pairing/reserve",ctx,
                                   {"name":"node-kh-01"},auth)
            check(status==201 and node["status"]=="pending","Admin reserve")
            status,issued,_=request("POST","/api/node-pairing/issue",ctx,{
                "node_id":node["node_id"],"role":"foreign","ttl_seconds":600},auth)
            check(status==200 and issued["pairing_code"].startswith("smn1_"),"Issue")
            redeem={"node_id":node["node_id"],"role":"foreign",
                    "pairing_code":issued["pairing_code"]}
            check(direct(redeem)==403,"Direct backend proof missing")
            check(direct(redeem,"forged")==403,"Backend forged header")
            status,credential,headers=request("POST","/api/node-pairing/redeem",ctx,
                redeem,{"X-Smite-Pairing-Ingress":"forged"})
            check(status==200 and credential["node_id"]==node["node_id"]
                  and len(credential["node_secret"])==64,"Nginx proof replacement")
            check(headers.get("cache-control")=="no-store","Secret caching")
            check(request("POST","/api/node-pairing/redeem",ctx,redeem)[0]==403,
                  "One-time code replay")
            check(request("GET","/api/node-pairing/redeem",ctx)[0] in (403,405),
                  "Non-POST method")
            check(request("POST","/api/node-pairing/redeem",ctx,{"junk":"x"*20000})[0]==413,
                  "Body size")
            check(request("GET","/nginx-ingress-secret.conf",ctx)[0]==404,
                  "Secret include served publicly")
            try:
                request("GET","/api/status",ctx,name="wrong.stage20.test")
            except (OSError,ssl.SSLError): pass
            else: raise AssertionError("Wrong TLS SNI was accepted")
            print("STAGE20_ADMIN_AND_ONE_TIME_INGRESS_SECURITY=PASS")

            # Stage21: real Smite Node HMAC signer over unchanged Nginx TLS
            # bytes to the real Smite signed inbound route. This does not
            # enable any IR/KH host or replace a paused container.
            node_file = SMITE/"node"/"app"/"node_auth.py"
            signer_spec = importlib.util.spec_from_file_location(
                "stage21_real_smite_node_signer", node_file)
            signer = importlib.util.module_from_spec(signer_spec)
            signer_spec.loader.exec_module(signer)
            register_path = "/api/node-control/register"
            identity = node["node_id"]
            key = credential["node_secret"]
            reg = {"node_id": identity, "role": "foreign"}

            def get_node_record():
                with sqlite3.connect(root/"data"/"smite.db") as db:
                    row = db.execute(
                        "SELECT status, metadata FROM nodes WHERE id = ?", (identity,)
                    ).fetchone()
                    return row[0], json.loads(row[1])

            initial_status, initial_meta = get_node_record()
            check(initial_status == "pending"
                  and initial_meta["provisioning"] == "reserved_for_pairing",
                  "Pairing alone should not mark the Node connected")
            check(request("POST", register_path, ctx, reg)[0] == 401,
                  "Unsigned Node registration succeeded")

            def signed_request(data, *, key_used=key, target=register_path,
                               signed_body=None, timestamp=None):
                canonical = json.dumps(data if signed_body is None else signed_body).encode()
                sig = signer.sign_request(
                    secret=key_used, node_id=identity, method="POST",
                    target=target, body=canonical, timestamp=timestamp)
                return request("POST", target, ctx, data, headers=sig)

            check(signed_request(reg, key_used="f"*64)[0] == 401,
                  "Forged HMAC signature was accepted")
            check(signed_request({"node_id":identity,"role":"iran"})[0] == 403,
                  "Wrong Node role was accepted")
            check(signed_request(reg, signed_body={"node_id":identity,
                  "role":"iran"})[0] == 401,
                  "Modified signed payload was accepted")
            check(signed_request(reg, timestamp=int(time.time())-300)[0] == 401,
                  "Stale HMAC was accepted")

            wire = json.dumps(reg).encode()
            hmac_header = signer.sign_request(
                secret=key, node_id=identity, method="POST",
                target=register_path, body=wire)
            code, signed_answer, head = request(
                "POST", register_path, ctx, reg, headers=hmac_header)
            check(code == 200 and signed_answer["id"] == identity,
                  "Signed Node check-in was not accepted")
            check(head.get("cache-control") == "no-store",
                  "Signed reply must not be cached")
            status_after, meta_after = get_node_record()
            check(status_after == "active"
                  and meta_after["provisioning"] == "signed_checkin",
                  "Signed HMAC check-in did not update pending Node")
            check(request("POST", register_path, ctx, reg,
                  headers=hmac_header)[0] == 401, "Replayed signed request worked")
            check(signed_request(reg, target=register_path+"?changed=1")[0] == 404,
                  "Unapproved signed HTTP target was accepted")
            print("STAGE21_ACTUAL_NODE_HMAC_AND_SIGNED_PANEL=PASS")
            print("STAGE21_PENDING_ONLY_TO_AUTHENTICATED_CHECKIN=PASS")
            print("STAGE21_FORGERY_BODY_ROLE_TIME_REPLAY=BLOCKED")
            conf.write_text(base+"\ninvalid_stage20_test_directive;\n")
            check(nginx("-t",ok=False).returncode!=0,"Invalid configuration passed preflight")
            check(request("GET","/api/status",ctx)[0]==200,"Invalid draft harmed active lab")
            conf.write_text(config("temporary"))
            nginx("-t"); nginx("-s","reload")
            wait_for(lambda:request("GET","/stage20-canary",ctx)[1]=="temporary","Lab reload")
            conf.write_text(base)
            nginx("-t"); nginx("-s","reload")
            wait_for(lambda:request("GET","/stage20-canary",ctx)[1]=="original","Lab rollback")
            check(request("GET","/api/status",ctx)[0]==200,"Rollback Panel health")
            print("STAGE20_INVALID_CONFIG_HOLD_AND_NGINX_ROLLBACK=PASS")
            print("STAGE20_IR_KH_PRODUCTION=UNTOUCHED")
        finally:
            for p in reversed(processes):
                if p.poll() is None:p.terminate()
            for p in reversed(processes):
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill();p.wait(timeout=5)

if __name__=="__main__":main()

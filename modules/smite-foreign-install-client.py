"""Trial enrollment library; no CLI, runtime activation or identity promotion.

The orchestrator must call enroll as root with a private staging directory and
known live identity path. Codes are memory-only; one scoped secret is durable
before any request. Enrollment proof does not mean Gateway/Node is connected.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import stat
import time
from urllib.parse import urlsplit

STATUS = '/api/node-control/installation-status'
REDEEM = '/api/foreign-install/redeem'
FIELDS = {'protocol','panel_url','node_id','node_name','origin','control_url','installation_code','expires_at'}

class Hold(ValueError):
    pass


def deny():
    raise Hold('Installation enrollment unavailable; retain staged identity')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: deny()
        result[key] = value
    return result


def decode(raw):
    try:
        if len(raw) > 8192: deny()
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict): deny()
        return value
    except (ValueError, TypeError, UnicodeError):
        deny()


def domain(host):
    if (not isinstance(host,str) or not re.fullmatch(r'(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',host)
            or host.endswith(('.local','.localhost','.internal','.home','.lan','.test','.invalid','.example','.onion'))): deny()
    return host


def origin(value):
    try:
        if not isinstance(value,str) or any(c.isspace() for c in value): deny()
        p=urlsplit(value)
        if (p.scheme!='https' or p.port not in (None,443) or p.username is not None
                or p.password is not None or p.path or p.query or p.fragment): deny()
        host=domain(p.hostname)
        if value not in ('https://'+host,'https://'+host+':443'): deny()
        return 'https://'+host+':443'
    except (ValueError,TypeError): deny()


@dataclass(frozen=True)
class Packet:
    scope: dict
    expires_at: int
    code: str = field(repr=False)


def parse_packet(raw):
    d=decode(raw)
    if set(d)!=FIELDS or d['protocol']!='smi1': deny()
    if not isinstance(d['node_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',d['node_id']): deny()
    if not isinstance(d['node_name'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,63}',d['node_name']): deny()
    panel=origin(d['panel_url']); gateway=origin(d['origin'])
    if (not isinstance(d['control_url'],str) or not d['control_url'].startswith(gateway)
            or not re.fullmatch(r'/smite-node/[0-9a-f]{32}',d['control_url'][len(gateway):])): deny()
    if (type(d['expires_at']) is not int or not 0 < d['expires_at'] < 10**11
            or not isinstance(d['installation_code'],str) or not re.fullmatch(r'smi1_[A-Za-z0-9_-]{43}',d['installation_code'])): deny()
    return Packet(dict(panel_url=panel,node_id=d['node_id'],node_name=d['node_name'],
                       origin=gateway,control_url=d['control_url']),d['expires_at'],d['installation_code'])


def private_file(fd):
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o600 or s.st_nlink!=1: deny()


@contextmanager
def locked_directory(directory):
    # Walk with directory FDs and O_NOFOLLOW so no ancestor symlink is followed.
    path=Path(directory)
    if not path.is_absolute() or '..' in path.parts: deny()
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    lock=None
    try:
        for part in path.parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        s=os.fstat(fd)
        if s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o700: deny()
        lock=os.open('enrollment.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
        private_file(lock)
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield fd
    finally:
        if lock is not None: os.close(lock)
        os.close(fd)


def stage(fd, packet, live_identity, now):
    # Never adopt or overwrite a live/legacy identity. Integration/promotion is
    # a separate future transaction, not inferred from equal Node IDs.
    if os.path.lexists(live_identity): deny()
    name='foreign-install-identity.json'
    try:
        current=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    except FileNotFoundError:
        current=None
    if current is not None:
        try:
            private_file(current)
            with os.fdopen(current,'rb',closefd=False) as stream: record=decode(stream.read(8193))
            if (set(record)!= {'schema','scope','node_secret'} or record['schema']!=1
                    or record['scope']!=packet.scope or not isinstance(record['node_secret'],str)
                    or not re.fullmatch(r'[0-9a-f]{64}',record['node_secret'])): deny()
            # A prior directory fsync may have failed after a successful link.
            os.fsync(current);os.fsync(fd)
            return record['node_secret']
        finally: os.close(current)
    if not now < packet.expires_at <= now+7200: deny()
    secret=secrets.token_hex(32)
    encoded=json.dumps({'schema':1,'scope':packet.scope,'node_secret':secret},sort_keys=True).encode()
    temp='.stage-'+secrets.token_hex(12)
    created=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        with os.fdopen(created,'wb') as stream:
            stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        # Link rather than replace: even a non-cooperating writer cannot be
        # silently overwritten. Crash leaves a complete record or no record.
        os.link(temp,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
        os.fsync(fd)
    finally:
        os.unlink(temp,dir_fd=fd)
    return secret


def post(panel, target, body, headers):
    """Bounded verified HTTPS/443; vetted literal dial, original SNI, no proxies."""
    if target not in (REDEEM,STATUS): deny()
    host=urlsplit(origin(panel)).hostname
    connection=None
    try:
        answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP)
        ips=[]
        for family,kind,proto,_,addr in answers:
            ip=ipaddress.ip_address(addr[0])
            if (family not in (socket.AF_INET,socket.AF_INET6) or '%' in addr[0] or addr[1]!=443
                    or not ip.is_global or ip.is_reserved or ip.is_multicast
                    or (ip.version==4 and any(ip in ipaddress.ip_network(n) for n in ('192.0.0.0/24','192.88.99.0/24')))
                    or (ip.version==6 and (ip not in ipaddress.ip_network('2000::/3') or any(ip in ipaddress.ip_network(n) for n in ('2001::/23','2002::/16','3fff::/20'))))): deny()
            ips.append(str(ip))
        if not ips: deny()
        class Pinned(http.client.HTTPSConnection):
            def connect(self):
                sock=socket.create_connection((ips[0],443),timeout=self.timeout)
                try: self.sock=self._context.wrap_socket(sock,server_hostname=host)
                except BaseException: sock.close();raise
        connection=Pinned(host,443,timeout=15,context=ssl.create_default_context())
        connection.request('POST',target,body=body,headers={**headers,'Content-Type':'application/json','Cache-Control':'no-store'})
        response=connection.getresponse()
        raw=response.read(8193)
        if response.status!=200: deny()
        return decode(raw)
    except (OSError,ValueError,http.client.HTTPException):
        deny()
    finally:
        if connection is not None: connection.close()


def signed_headers(scope,secret,body,now):
    nonce=secrets.token_hex(16);timestamp=str(now)
    canonical='\n'.join(('smite-node-hmac-v1',scope['node_id'],'POST',STATUS,timestamp,nonce,hashlib.sha256(body).hexdigest())).encode()
    return {'X-Smite-Node-ID':scope['node_id'],'X-Smite-Timestamp':timestamp,
            'X-Smite-Nonce':nonce,'X-Smite-Signature':hmac.new(secret.encode(),canonical,'sha256').hexdigest()}


def enroll(raw, *, directory, live_identity, transport=post, now=None):
    """Persist then redeem/prove; return nonsecret proof, never activate runtime.

    Production caller must run as root. All files must belong to the effective
    user, allowing offline unprivileged tests. No credentials in argv or output.
    """
    packet=parse_packet(raw)
    moment=int(time.time()) if now is None else now
    try:
        with locked_directory(directory) as fd:
            secret=stage(fd,packet,live_identity,moment)
            if moment < packet.expires_at <= moment+7200:
                request={'node_id':packet.scope['node_id'],'node_name':packet.scope['node_name'],
                         'control_url':packet.scope['control_url'],'installation_code':packet.code,'node_secret':secret}
                try:
                    result=transport(packet.scope['panel_url'],REDEEM,json.dumps(request).encode(),{})
                    if result!={'status':'enrolled','node_id':packet.scope['node_id']}: deny()
                except (Hold,OSError,TimeoutError):
                    # May have committed. A signed proof is authoritative;
                    # never regenerate the secret or assume failure means no commit.
                    pass
            body=json.dumps({'node_id':packet.scope['node_id']},separators=(',',':')).encode()
            proof=transport(packet.scope['panel_url'],STATUS,body,signed_headers(packet.scope,secret,body,int(time.time()) if now is None else now))
            expected={'status':'enrolled',**{k:v for k,v in packet.scope.items() if k!='panel_url'}}
            if proof!=expected: deny()
            return expected
    except (OSError,ValueError,http.client.HTTPException):
        deny()

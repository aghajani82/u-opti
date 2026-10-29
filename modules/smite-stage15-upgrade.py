#!/usr/bin/env python3
"""Controlled old Stage15 -> reviewed FRP071 pair upgrade, before engine setup.

Snapshot/console and explicit interactive grant required. SQLite backup retained;
rollback restores images only, NEVER overwrites identity, Replay or live DB.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import shutil
import sys
import time

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('upgrade_wss',HERE/'smite-stage15-wss.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
h=w.host;need=h.require
STATE=Path('/var/lib/u-opti/smite-stage15-image-upgrade')
OLD={'panel':'sha256:51f7e45e06e8cc59f4f04972090962b9c8d6db8aad2ec1591fc5ede0da112ae9',
     'node':'sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991'}
SOURCE='6981bd91b43811fad8847da9abd81ef99a921003'
MANIFEST='0b34ee3fbd9174e6bf7ef6ddf145f7ebcd606c9bbeae176bb3d6a38b8a2a7840'
verify_bundle=w.load('upgrade_bundle','smite-stage15-bundle-verify.py')


def save(doc):w.write_atomic(STATE/'record.json',(json.dumps(doc,sort_keys=True)+'\n').encode())

def canonical_runtime(result):
    """Ignore ONLY Docker's reorder of identical HostConfig.Binds entries.

    Mount source, target, flags, duplicates, other HostConfig fields, and
    the independently checked container Mounts must remain unchanged.
    Canonicalize saved PREPARED journals too, without editing journal bytes.
    """
    need(isinstance(result,dict) and isinstance(result.get('host'),dict),
         'INVALID_RUNTIME_SIGNATURE')
    host=dict(result['host'])
    if 'Binds' in host and isinstance(host['Binds'],list):
        need(all(isinstance(entry,str) for entry in host['Binds']),
             'INVALID_HOST_BINDS')
        host['Binds']=sorted(host['Binds'])
    return dict(result,host=host)


def normal(obj):
    result=w.signature(obj);result.pop('image')
    return canonical_runtime(result)


def record():
    h.directory(STATE,private=True)
    doc=json.loads(h.file(STATE/'record.json',mode=0o600,limit=262144))
    need(doc.get('schema')==1 and doc.get('roles') in (['node'],['panel','node'])
         and doc.get('state') in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK'),'INVALID_UPGRADE_JOURNAL')
    need(w.protected(doc['roles'],False)==doc['protected'],'UPGRADE_PROTECTED_STATE_DRIFT')
    return doc


def base_command(role,args):
    cmd=['docker','compose']
    for path in w.service_files(role,False):cmd+=['-f',str(path)]
    return cmd+args


def validate(role,obj,doc=None,healthy=True):
    w.runtime(role,obj,False,healthy,enrolled=False,allowed_images={OLD[role],w.REVIEWED_IMAGES[role]})
    if doc is not None:
        need(normal(obj)==canonical_runtime(doc['runtime'][role]),
             'UPGRADE_RUNTIME_SECURITY_DRIFT')


def health(doc,new):
    for role in doc['roles']:
        for attempt in range(20):
            try:
                obj=w.inspect(role);validate(role,obj,doc)
                need(obj['Image']==(w.REVIEWED_IMAGES[role] if new else OLD[role]),'UPGRADE_IMAGE_DRIFT');break
            except h.Hold:
                if attempt==19:raise
                time.sleep(3)
    h.signed_inventory('not-installed')


def plan(role,folder):
    need(not STATE.exists() and not STATE.is_symlink(),'EXISTING_UPGRADE_JOURNAL')
    roles=['panel','node'] if role=='IR' else ['node'];w.no_tunnels()
    for component in roles:
        for path in (w.overlay(component),w.NODE/'docker-compose.frp-stage15.yml'):
            need(not path.exists() and not path.is_symlink(),'ROLLBACK_FRP_WSS_BEFORE_IMAGE_UPGRADE')
    bundle=verify_bundle.verify(folder=folder,source_sha=SOURCE,manifest_sha=MANIFEST)
    doc={'schema':1,'state':'PREPARED','roles':roles,'protected':w.protected(roles,False),'runtime':{}}
    for component in roles:
        obj=w.inspect(component);validate(component,obj)
        need(obj['Image']==OLD[component],'UPGRADE_REQUIRES_REVIEWED_ORIGINAL_IMAGE')
        need(bundle['images'][component]['local_image_id']==w.REVIEWED_IMAGES[component],'NEW_IMAGE_NOT_REVIEWED')
        need(h.run(['docker','image','inspect',OLD[component],'--format','{{.Id}}'])==OLD[component],'ROLLBACK_IMAGE_MISSING')
        doc['runtime'][component]=normal(obj)
    h.signed_inventory('not-installed')
    return doc,bundle


def copy_archive(source,target,expected):
    # Hash the same bytes loaded later from the root-only transaction directory.
    h.trusted_parents(source);st=source.lstat()
    need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==0 and not st.st_mode&0o022,'UNTRUSTED_IMAGE_ARCHIVE')
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    out=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    sha=hashlib.sha256();count=0
    with os.fdopen(fd,'rb') as src,os.fdopen(out,'wb') as dst:
        need((os.fstat(src.fileno()).st_ino,os.fstat(src.fileno()).st_dev)==(st.st_ino,st.st_dev),'IMAGE_ARCHIVE_REPLACED')
        while block:=src.read(1048576):
            count+=len(block);need(count<=5_000_000_000,'IMAGE_ARCHIVE_TOO_LARGE')
            sha.update(block);dst.write(block)
        dst.flush();os.fsync(dst.fileno())
    need(sha.hexdigest()==expected,'IMAGE_COPY_CHECKSUM_MISMATCH');h.flush(target.parent)


def restore(doc):
    w.no_tunnels();need(w.protected(doc['roles'],False)==doc['protected'],'UPGRADE_PROTECTED_STATE_DRIFT')
    for role in doc['roles']:validate(role,w.inspect(role),doc,healthy=False)
    w.discard_partial(STATE/'record.json',[(json.dumps(dict(doc,state=s),sort_keys=True)+'\n').encode() for s in ('PREPARED','COMMITTED','RECOVERING','ROLLED_BACK')])
    doc['state']='RECOVERING';save(doc)
    for role in reversed(doc['roles']):
        need(h.run(['docker','image','inspect',OLD[role],'--format','{{.Id}}'])==OLD[role],'ROLLBACK_IMAGE_MISSING')
        h.run(['docker','tag',OLD[role],'smite-'+role+':stage15-local'])
        if w.inspect(role)['Image']!=OLD[role]:
            h.run(base_command(role,['up','-d','--no-build','--no-deps','--pull','never','--force-recreate','smite-'+role]),timeout=150)
    health(doc,False);doc['state']='ROLLED_BACK';save(doc)


def resume_prepared(role):
    """Finalize a previously completed-image transaction, without recreating.

    Only the exact reviewed new images, untouched signed state, complete
    private backups, and current Signed HMAC/replay checks may be committed.
    A mixed/unknown runtime remains PREPARED for manual review.
    """
    roles=['panel','node'] if role=='IR' else ['node']
    with h.exclusive(w.LOCK):
        doc=record()
        need(doc['state']=='PREPARED' and doc['roles']==roles,
             'RESUME_REQUIRES_MATCHING_PREPARED_JOURNAL')
        w.no_tunnels()
        for component in roles:
            for path in (w.overlay(component),w.NODE/'docker-compose.frp-stage15.yml'):
                need(not path.exists() and not path.is_symlink(),
                     'RESUME_REQUIRES_NO_FRP_WSS')
        # An operator-requested recovery must never hide missing rollback data.
        backup_names=['node-identity.before.json','replay.before.sqlite3']
        if role=='IR':backup_names.append('panel.before.sqlite3')
        backup_names += [component+'.image-before.tar' for component in roles]
        for name in backup_names:
            path=STATE/name
            h.trusted_parents(path)
            need(path.is_file() and not path.is_symlink(),
                 'MISSING_OR_UNSAFE_RESUME_BACKUP')
            st=path.lstat()
            need(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1
                 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size>0,
                 'MISSING_OR_UNSAFE_RESUME_BACKUP')
        for name in ('replay.before.sqlite3',)+(('panel.before.sqlite3',) if role=='IR' else ()):
            db=sqlite3.connect((STATE/name).as_uri()+'?mode=ro',uri=True)
            try:
                need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok',
                     'CORRUPT_RESUME_SQLITE_BACKUP')
            finally:
                db.close()
        for component in roles:
            need(h.run(['docker','image','inspect',OLD[component],
                        '--format','{{.Id}}'])==OLD[component],
                 'ROLLBACK_IMAGE_MISSING')
            need(h.run(['docker','image','inspect','smite-'+component+':stage15-local',
                        '--format','{{.Id}}'])==w.REVIEWED_IMAGES[component],
                 'RESUME_IMAGE_TAG_DRIFT')
        # health() enforces complete runtime signature, exact reviewed images,
        # healthy containers, signed auth mode, and durable Replay nonce probe.
        health(doc,True)
        need(w.protected(roles,False)==doc['protected'],
             'UPGRADE_PROTECTED_STATE_DRIFT')
        doc['state']='COMMITTED'
        save(doc)


def backup_state(doc):
    p=h.Paths()
    h.new_file(STATE/'node-identity.before.json',h.file(p.identity,mode=0o600),0o600)
    replay=STATE/'replay.before.sqlite3';h.new_file(replay,b'',0o600)
    with sqlite3.connect(p.replay.as_uri()+'?mode=ro',uri=True) as source:
        with sqlite3.connect(replay) as target:
            source.backup(target)
            need(target.execute('PRAGMA integrity_check').fetchone()[0]=='ok','REPLAY_BACKUP_INTEGRITY_FAILED')
    with replay.open('rb') as stream:os.fsync(stream.fileno())
    for role in doc['roles']:
        backup=STATE/(role+'.image-before.tar')
        h.new_file(backup,b'',0o600)
        h.run(['docker','save','-o',str(backup),OLD[role]],timeout=240)
        need(backup.stat().st_size>0,'IMAGE_BACKUP_EMPTY')
    h.flush(STATE)


def apply(role,folder):
    with h.exclusive(w.LOCK):
        need(shutil.disk_usage(STATE.parent).free>=4*1024**3,'FOUR_GIB_FREE_FOR_IMAGE_BACKUPS_REQUIRED')
        doc,bundle=plan(role,folder);h.new_dir(STATE);save(doc)
        try:
            backup_state(doc)
            if role=='IR':w.backup_panel(STATE/'panel.before.sqlite3')
            for component in doc['roles']:
                item=bundle['images'][component];archive=STATE/item['file']
                copy_archive(folder/item['file'],archive,item['archive_sha256'])
                h.run(['docker','load','-i',str(archive)],timeout=240)
                need(h.run(['docker','image','inspect','smite-'+component+':stage15-local','--format','{{.Id}}'])==w.REVIEWED_IMAGES[component],'LOADED_IMAGE_ID_MISMATCH')
            for component in doc['roles']:
                h.run(base_command(component,['up','-d','--no-build','--no-deps','--pull','never','--force-recreate','smite-'+component]),timeout=150)
            health(doc,True);need(w.protected(doc['roles'],False)==doc['protected'],'UPGRADE_PROTECTED_STATE_DRIFT')
            doc['state']='COMMITTED';save(doc)
        except Exception:
            restore(doc);raise h.Hold('IMAGE_UPGRADE_ROLLED_BACK')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['plan','apply','verify','rollback','recover','resume']);ap.add_argument('--images',type=Path);a=ap.parse_args()
    try:
        role=os.uname().nodename.split('.')[0].upper();need(os.geteuid()==0 and role in ('IR','KH'),'DISPOSABLE_ROOT_ONLY')
        if a.action in ('apply','rollback','recover','resume'):
            need(sys.stdin.isatty(),'INTERACTIVE_CONFIRMATION_REQUIRED')
            value=a.action.upper()+'-IMAGES-'+role+'-SNAPSHOT-CONSOLE'
            need(input('Type '+value+': ').strip()==value,'OPERATOR_CANCELLED')
        if a.action in ('plan','apply'):need(a.images is not None and a.images.is_absolute(),'ABSOLUTE_IMAGE_FOLDER_REQUIRED')
        if a.action=='apply':apply(role,a.images)
        elif a.action=='resume':resume_prepared(role)
        else:
            with h.exclusive(w.LOCK):
                if a.action=='plan':plan(role,a.images)
                elif a.action=='verify':
                    doc=record();need(doc['state']=='COMMITTED','UPGRADE_NOT_COMMITTED');health(doc,True)
                else:restore(record())
        print('STAGE15_IMAGE_'+a.action.upper()+'=PASS');print('IDENTITY_REPLAY_DB_OVERWRITTEN=NO');return 0
    except (h.Hold,verify_bundle.BundleHold,OSError,ValueError,KeyError,TypeError) as exc:
        msg=str(exc);print('HOLD: '+(msg if re.fullmatch('[A-Z0-9_]{1,100}',msg) else 'UNTRUSTED_UPGRADE_STATE'),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())

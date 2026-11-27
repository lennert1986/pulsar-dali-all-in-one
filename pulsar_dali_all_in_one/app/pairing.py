"""Opt-in LAN pairing with explicit certificate-bound code comparison."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
import uuid
from urllib.parse import urlparse

TTL=300
LIMIT=16
WIRE="/api/pairing/wire/"
TRUSTED={"127.0.0.1","::1","172.30.32.2"}
LAN=[ipaddress.ip_network(x) for x in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","169.254.0.0/16")]
HEX=re.compile(r"[0-9a-f]{64}")
PID=re.compile(r"[0-9a-f]{32}")
UID=re.compile(r"[A-Za-z0-9_.-]{1,128}")

def check(v,pattern):
    if not isinstance(v,str) or not pattern.fullmatch(v):
        raise ValueError("Ugyldige parringsoplysninger")
    return v

def lan(v):
    addr=ipaddress.IPv4Address(v)
    if not any(addr in net for net in LAN):
        raise ValueError("Kun lokale IPv4-adresser")
    return str(addr)

def fingerprint(v):
    return check(str(v).replace(":","").lower(),HEX)

def digest(v):
    return hashlib.sha256(v.encode("ascii")).hexdigest()

def code(secret,pid,source,target,fp):
    msg="|".join(("pulsar-pair-v1",pid,source,target,fingerprint(fp)))
    raw=hmac.new(bytes.fromhex(secret),msg.encode("ascii"),hashlib.sha256).hexdigest()[:16].upper()
    return "-".join(raw[i:i+4] for i in range(0,16,4))

def wire(host,action,data,pin=None):
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    ctx.check_hostname=False
    ctx.verify_mode=ssl.CERT_NONE
    conn=http.client.HTTPSConnection(lan(host),8443,timeout=6,context=ctx)
    try:
        conn.connect()
        fp=hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        if pin is not None and not hmac.compare_digest(fp,fingerprint(pin)):
            raise ValueError("TLS-certifikat ændret; par igen")
        conn.request("POST",WIRE+action,body=json.dumps(data).encode(),headers={"Content-Type":"application/json"})
        response=conn.getresponse()
        raw=response.read(8193)
        if len(raw)>8192 or response.status!=200:
            raise ValueError("Parring afvist eller ikke aktiveret")
        result=json.loads(raw)
        if not isinstance(result,dict) or result.get("ok") is not True:
            raise ValueError("Ugyldigt parringssvar")
        return result,fp
    finally:
        conn.close()

class Service:
    def __init__(self,uid,path="/data/remote/paired_grants.json"):
        self.uid=check(uid,UID)
        self.path=Path(path)
        self.lock=threading.RLock()
        self.until=0
        self.incoming={}
        self.outgoing={}
    def prune(self):
        now=time.monotonic()
        for store in (self.incoming,self.outgoing):
            for k in list(store):
                if store[k]["expires"]<=now:
                    del store[k]
    def grants(self):
        try:
            v=json.loads(self.path.read_text())
            return v if isinstance(v,dict) else {}
        except FileNotFoundError:
            return {}
    def save(self,grants):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(".tmp")
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(grants,f)
        os.replace(tmp,self.path)
    def authorized(self,header):
        if not header.startswith("Bearer ") or not HEX.fullmatch(header[7:]):
            return False
        hashed=digest(header[7:])
        try:
            with self.lock:
                return any(hmac.compare_digest(hashed,g.get("hash","")) for g in self.grants().values() if isinstance(g,dict))
        except (OSError,ValueError,TypeError):
            return False
    def status(self,listening):
        with self.lock:
            self.prune()
            now=time.monotonic()
            def public(store):
                return [dict(id=k,host=v["host"],controller_id=v["controller_id"],code=v["code"],
                        state=v["state"],remaining=max(0,int(v["expires"]-now))) for k,v in store.items()]
            return dict(ok=True,listening=listening,remaining=max(0,int(self.until-now)) if listening else 0,
                        incoming=public(self.incoming),outgoing=public(self.outgoing),
                        grants=[dict(id=k,controller_id=v["controller_id"],host=v["host"]) for k,v in self.grants().items()])
    def allow(self,listening):
        if not listening:
            raise ValueError("Aktiver remote HTTPS først")
        with self.lock:
            self.until=time.monotonic()+TTL
    def close(self):
        with self.lock:
            self.until=0
            self.incoming.clear()
    def decision(self,pid,accept):
        with self.lock:
            self.prune()
            row=self.incoming.get(check(pid,PID))
            if not row or row["state"]!="pending" or (accept and time.monotonic()>=self.until):
                raise ValueError("Udløbet eller behandlet")
            row["state"]="approved" if accept else "denied"
    def revoke(self,pid):
        with self.lock:
            grants=self.grants()
            if grants.pop(check(pid,PID),None) is None:
                raise ValueError("Ukendt adgang")
            self.save(grants)
            self.incoming.pop(pid,None)
    def receive(self,action,data,host,fp):
        host=lan(host)
        pid=check(data.get("id"),PID)
        secret=check(data.get("secret"),HEX)
        with self.lock:
            self.prune()
            now=time.monotonic()
            if action=="start":
                source=check(data.get("requester"),UID)
                if now>=self.until or source==self.uid or data.get("target")!=self.uid or pid in self.incoming or len(self.incoming)>=LIMIT:
                    raise ValueError("Parring lukket eller ugyldig")
                self.incoming[pid]=dict(host=host,controller_id=source,secret_hash=digest(secret),
                    code=code(secret,pid,source,self.uid,fp),state="pending",expires=min(now+TTL,self.until),
                    pin=fingerprint(fp))
                return dict(ok=True,controller_id=self.uid)
            row=self.incoming.get(pid)
            if action!="finish" or not row or row["host"]!=host or not hmac.compare_digest(row["secret_hash"],digest(secret)) or row["pin"]!=fingerprint(fp):
                raise ValueError("Ukendt anmodning")
            if row["state"]=="approved":
                grants=self.grants()
                if len(grants)>=128:
                    raise ValueError("For mange parringer")
                token=secrets.token_hex(32)
                grants[pid]=dict(hash=digest(token),controller_id=row["controller_id"],host=host)
                self.save(grants)
                row.update(state="complete",token=token)
            if row["state"]=="complete":
                return dict(ok=True,state="complete",token=row["token"],controller_id=self.uid)
            return dict(ok=True,state=row["state"])
    def begin(self,candidate,name):
        host=lan(candidate["host"])
        target=check(candidate["controller_id"],UID)
        if target==self.uid or candidate.get("port")!=8443:
            raise ValueError("Ugyldig controller")
        pid=secrets.token_hex(16)
        secret=secrets.token_hex(32)
        with self.lock:
            self.prune()
            if len(self.outgoing)>=LIMIT or any(v["controller_id"]==target for v in self.outgoing.values()):
                raise ValueError("Afslut eksisterende parring")
            self.outgoing[pid]=dict(host=host,controller_id=target,secret=secret,name=name,
                                     code="",state="connecting",expires=time.monotonic()+TTL)
        try:
            result,fp=wire(host,"start",dict(id=pid,secret=secret,requester=self.uid,target=target))
            if result.get("controller_id")!=target:
                raise ValueError("Controller-ID stemmer ikke")
            with self.lock:
                self.outgoing[pid].update(pin=fp,code=code(secret,pid,self.uid,target,fp),state="pending")
            return pid
        except Exception:
            with self.lock:
                self.outgoing.pop(pid,None)
            raise
    def finish(self,pid,register):
        pid=check(pid,PID)
        with self.lock:
            self.prune()
            row=self.outgoing.get(pid)
            if not row or row["state"]!="pending":
                raise ValueError("Anmodningen er udløbet")
            row["state"]="finishing"
            item=dict(row)
        try:
            reply,_=wire(item["host"],"finish",dict(id=pid,secret=item["secret"]),item["pin"])
            state=reply.get("state")
            if state=="pending":
                return dict(ok=True,state=state)
            if state=="denied":
                with self.lock:self.outgoing.pop(pid,None)
                return dict(ok=True,state=state)
            if state!="complete" or reply.get("controller_id")!=item["controller_id"]:
                raise ValueError("Ugyldigt parringssvar")
            register(item,check(reply.get("token"),HEX))
            with self.lock:self.outgoing.pop(pid,None)
            return dict(ok=True,state="complete")
        finally:
            with self.lock:
                if pid in self.outgoing:self.outgoing[pid]["state"]="pending"
    def cancel(self,pid):
        with self.lock:
            row=self.outgoing.get(check(pid,PID))
            if row and row["state"]=="finishing":
                raise ValueError("Afvent forbindelse")
            self.outgoing.pop(pid,None)

_service=None
_service_lock=threading.Lock()
def service(h):
    global _service
    with _service_lock:
        if _service is None:
            _service=Service(h.server.controller.controller_id)
        return _service

def install(handler,app):
    old_get,old_post=handler.do_GET,handler.do_POST
    def dispatch(h,method,fallback):
        path=urlparse(h.path).path.rstrip("/")
        remote=bool(getattr(h.server,"is_remote",False))
        match=re.search(r"/api/pairing/([a-z]+)$",path)
        if not path.startswith(WIRE) and not match:
            return fallback(h)
        try:
            svc=service(h)
            if remote:
                if method!="POST" or path not in (WIRE+"start",WIRE+"finish"):
                    return h._json(dict(ok=False,error="not found"),404)
            elif h.client_address[0] not in TRUSTED or not match or h.headers.get("X-Pulsar-Pairing")!="1":
                return h._json(dict(ok=False,error="forbidden"),403)
            action=path.rsplit("/",1)[-1]
            listening=getattr(h.server,"remote_server",None) is not None
            if method=="GET":
                if action!="status":
                    return h._json(dict(ok=False,error="not found"),404)
                return h._json(svc.status(listening))
            if h.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
                raise ValueError("JSON required")
            size=int(h.headers.get("Content-Length","0"))
            if not 0<size<=4096:raise ValueError("Invalid size")
            h.connection.settimeout(8)
            data=json.loads(h.rfile.read(size))
            if not isinstance(data,dict):raise ValueError("Invalid JSON")
            if remote:
                return h._json(svc.receive(action,data,h.client_address[0],h.server.remote_credentials["fingerprint"]))
            if action=="allow":svc.allow(listening)
            elif action=="close":svc.close()
            elif action in ("approve","deny"):svc.decision(data.get("id"),action=="approve")
            elif action=="revoke":svc.revoke(data.get("id"))
            elif action=="cancel":svc.cancel(data.get("id"))
            elif action=="begin":
                worker=getattr(h.server,"discovery_worker",None)
                found=worker.status()["candidates"] if worker else []
                matches=[c for c in found if c["host"]==data.get("host") and c["controller_id"]==data.get("controller_id")]
                if len(matches)!=1:raise ValueError("Controller ikke fundet")
                target=matches[0]
                with app["CONTROLLERS_LOCK"]:
                    if any(x.get("remote_controller_id")==target["controller_id"] for x in app["load_controller_registry"]().values()):
                        raise ValueError("Controller er allerede tilføjet")
                name=str(data.get("name") or target["host"]).strip()[:80]
                if not name or any(ord(c)<32 or c in "<>&\"'" for c in name):raise ValueError("Ugyldigt navn")
                return h._json(dict(ok=True,id=svc.begin(target,name)))
            elif action=="finish":
                def register(item,token):
                    now=time.strftime("%Y-%m-%d %H:%M:%S")
                    record=dict(name=item["name"],host=item["host"],port=8443,token=token,
                                fingerprint=item["pin"],created_at=now,remote_controller_id=item["controller_id"])
                    test=app["test_remote_controller"](record)
                    if test.get("controller_id")!=item["controller_id"]:raise ValueError("Controller-ID stemmer ikke")
                    record.update(last_ok=now,last_error="",firmware=test.get("firmware"))
                    with app["CONTROLLERS_LOCK"]:
                        registry=app["load_controller_registry"]()
                        if any(v.get("remote_controller_id")==item["controller_id"] for v in registry.values()):
                            raise ValueError("Controller er allerede tilføjet")
                        registry[str(uuid.uuid4())]=record
                        app["save_controller_registry"](registry)
                return h._json(svc.finish(data.get("id"),register))
            else:return h._json(dict(ok=False,error="not found"),404)
            return h._json(dict(ok=True))
        except (ValueError,KeyError,OSError,RuntimeError,TypeError,http.client.HTTPException):
            return h._json(dict(ok=False,error="Parring kunne ikke gennemføres. Kontrollér parringsvinduet, koden og HTTPS."),400)
    def get(h):return dispatch(h,"GET",old_get)
    def post(h):return dispatch(h,"POST",old_post)
    handler.do_GET,handler.do_POST=get,post

"""Verify LAN address changes independently of browser, MQTT or DALI traffic."""
import threading
import time
import ipaddress

def local_ipv4(host):
    try:
        addr=ipaddress.IPv4Address(host)
        return any(addr in ipaddress.IPv4Network(net) for net in
                   ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","169.254.0.0/16"))
    except (ValueError,TypeError):
        return False

# Compare the identity/credentials and address, not transient status metadata.
def identity(item):
    return tuple(item.get(k) for k in ("remote_controller_id","host","port","fingerprint","token"))

class Reconnect:
    def __init__(self,discovery,load,save,lock,request,log):
        self.discovery=discovery
        self.load=load
        self.save=save
        self.lock=lock
        self.request=request
        self.log=log
        self.stop_event=threading.Event()
        self.thread=None
        self.retry={}
    def start(self):
        if self.discovery.enabled:
            self.thread=threading.Thread(target=self.run,daemon=True,name="controller-reconnect")
            self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def verified(self,item):
        try:
            result=self.request(item,"GET","/api/status",timeout=3)
            return result.get("ok") is True and result.get("controller_id")==item["remote_controller_id"]
        except Exception:
            return False
    def step(self):
        now=time.monotonic()
        candidates=self.discovery.status()["candidates"]
        with self.lock:
            registry={k:dict(v) for k,v in self.load().items()}
        self.retry={k:v for k,v in self.retry.items() if k in registry}
        for rid,item in registry.items():
            if self.stop_event.is_set():return
            uid=item.get("remote_controller_id")
            if not uid or not item.get("token") or not item.get("fingerprint") or item.get("port",8443)!=8443:
                continue
            # Preserve custom DNS and WAN addresses; only migrate LAN IPv4 registrations.
            if not local_ipv4(item.get("host")):continue
            hosts=sorted({c["host"] for c in candidates
                          if c.get("controller_id")==uid and c.get("port")==8443 and
                          c.get("host")!=item.get("host") and local_ipv4(c.get("host"))})
            if not hosts:continue
            if now<self.retry.get(rid,0):continue
            self.retry[rid]=now+15
            # Never switch a still-working address based on unauthenticated discovery.
            if self.verified(item):continue
            # Reject ambiguous verified identities; probe at most 4 advertised addresses.
            if len(hosts)>4:continue
            verified=[]
            for host in hosts:
                if self.stop_event.is_set():return
                candidate=dict(item,host=host)
                if self.verified(candidate):verified.append(host)
            if len(verified)!=1:continue
            host=verified[0]
            with self.lock:
                current=self.load()
                existing=current.get(rid)
                if not existing or identity(existing)!=identity(item):continue
                existing.update(host=host,last_ok=time.strftime("%Y-%m-%d %H:%M:%S"),
                                last_error="")
                current[rid]=existing
                self.save(current)
            self.log("Verified controller address changed: "+str(uid)+" "+item["host"]+" -> "+host)
    def run(self):
        while not self.stop_event.is_set():
            try:self.step()
            except Exception:
                self.log("Controller address recovery deferred")
            self.stop_event.wait(5)

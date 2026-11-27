"""Opt-in IPv4 LAN discovery; unauthenticated hints, never trusted registration."""
import ipaddress,json,socket,threading,time
from pathlib import Path
PORT=38443
GROUP="239.255.84.43"
MAGIC="pulsar-dali-discovery-v1"
TTL=100
LIMIT=128
def parse(raw,host,own):
    if len(raw)>1024:return None
    try:
        addr=ipaddress.IPv4Address(host)
        if not (addr.is_private or addr.is_link_local) or addr.is_loopback or addr.is_multicast or addr.is_unspecified:return None
        d=json.loads(raw)
        if not isinstance(d,dict) or d.get("protocol")!=MAGIC:return None
        uid=d.get("controller_id")
        if not isinstance(uid,str) or not 1<=len(uid)<=128 or uid==own or not all(c.isalnum() or c in "-_." for c in uid):return None
        if d.get("port")!=8443:return None
        name=d.get("name","")
        version=d.get("version","")
        return {"controller_id":uid,"host":str(addr),"port":8443,"verified":False,
                "name":name[:80] if isinstance(name,str) else "",
                "version":version[:32] if isinstance(version,str) else ""}
    except (ValueError,TypeError,UnicodeError):return None
class Discovery:
    def __init__(self,controller,settings,log):
        self.uid=str(controller.controller_id);self.log=log
        self.name=socket.gethostname()
        try:o=json.loads(Path("/data/options.json").read_text())
        except (OSError,ValueError):o={}
        self.enabled=bool(o.get("controller_discovery_enabled",False))
        self.advertise=bool(settings.remote_api_enabled)
        self.stop_event=threading.Event();self.lock=threading.Lock();self.items={};self.error="";self.thread=None
    def start(self):
        if self.enabled:
            self.thread=threading.Thread(target=self.run,daemon=True,name="controller-discovery");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def accept(self,raw,host,now):
        item=parse(raw,host,self.uid)
        if item is None:return
        key=(item["controller_id"],item["host"])
        with self.lock:
            self.items={k:v for k,v in self.items.items() if now-v["last_seen"]<=TTL}
            if key not in self.items and len(self.items)>=LIMIT:return
            self.items[key]=dict(item,last_seen=now)
    def status(self):
        now=time.monotonic()
        with self.lock:
            items=[dict(v,age_seconds=round(now-v["last_seen"])) for v in self.items.values() if now-v["last_seen"]<=TTL]
        for x in items:x.pop("last_seen",None)
        return {"ok":True,"enabled":self.enabled,"advertising":self.enabled and self.advertise,"error":self.error,"candidates":sorted(items,key=lambda x:(x["host"],x["controller_id"]))}
    def run(self):
        while not self.stop_event.is_set():
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP) as s:
                    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    s.bind(("",PORT))
                    s.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton(GROUP)+socket.inet_aton("0.0.0.0"))
                    s.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,1)
                    s.settimeout(0.5);self.error="";next_send=0
                    payload=json.dumps({"protocol":MAGIC,"controller_id":self.uid,"port":8443,"name":self.name,"version":"0.21.0"}).encode()
                    while not self.stop_event.is_set():
                        now=time.monotonic()
                        if self.advertise and now>=next_send:
                            s.sendto(payload,(GROUP,PORT));next_send=now+15
                        try:
                            raw,source=s.recvfrom(1025);self.accept(raw,source[0],time.monotonic())
                        except socket.timeout:pass
            except OSError as e:
                self.error=str(e);self.log("Controller discovery unavailable: "+str(e));self.stop_event.wait(15)

"""Application UTC synchronized to a pinned, explicitly selected peer.
Does not set Linux time or alter TLS, DALI polling, or safety timers."""
import time,threading,json,math
from pathlib import Path
MAX_RTT=2.0
MAX_AGE=900.0
def sample(t0,t1,remote):
    if type(remote) not in (int,float) or not math.isfinite(remote) or not 1577836800<=remote<=4102444800:raise ValueError("Invalid reference UTC")
    if not 0<=t1-t0<=MAX_RTT:raise ValueError("Reference RTT too high")
    return remote+(t1-t0)/2,t1,(t1-t0)/2
class Clock:
    def __init__(self,controller,registry,request,log):
        self.uid=controller.controller_id;self.registry=registry;self.request=request;self.log=log
        try:o=json.loads(Path("/data/options.json").read_text())
        except (OSError,ValueError):o={}
        self.reference=str(o.get("clock_reference_controller_id","")).strip()
        self.interval=max(30,min(300,int(o.get("clock_sync_interval",60))))
        self.lock=threading.Lock();self.anchor=None;self.error="";self.stop_event=threading.Event();self.thread=None
    def start(self):
        if self.reference:
            self.thread=threading.Thread(target=self.run,daemon=True,name="clock-sync");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def step(self):
        matches=[dict(v) for v in self.registry().values() if v.get("remote_controller_id")==self.reference]
        if len(matches)!=1 or self.reference==self.uid:raise ValueError("Select exactly one registered remote reference")
        t0=time.monotonic()
        result=self.request(matches[0],"GET","/api/admin/clock",timeout=5)
        t1=time.monotonic()
        if result.get("controller_id")!=self.reference or result.get("ok") is not True:raise ValueError("Reference identity mismatch")
        if result.get("reference_controller_id"):raise ValueError("Reference must use its own system clock; chained clocks disabled")
        anchor=sample(t0,t1,result.get("system_utc"))
        with self.lock:self.anchor=anchor;self.error=""
    def run(self):
        while not self.stop_event.is_set():
            try:self.step()
            except Exception as e:
                with self.lock:self.error=str(e)
                self.log("Clock synchronization deferred: "+str(e))
            self.stop_event.wait(self.interval)
    def status(self):
        with self.lock:a=self.anchor;err=self.error
        mono=time.monotonic();system=time.time()
        age=mono-a[1] if a else None
        valid=a is not None and 0<=age<=MAX_AGE
        corrected=a[0]+age if valid else system
        return {"ok":True,"controller_id":self.uid,"system_utc":system,"application_utc":corrected,"reference_controller_id":self.reference,"synchronized":bool(valid),"age_seconds":age,"offset_seconds":corrected-system if valid else None,"uncertainty_seconds":a[2]+age*0.0001 if valid else None,"error":err,"mode":"reference" if self.reference else "system"}

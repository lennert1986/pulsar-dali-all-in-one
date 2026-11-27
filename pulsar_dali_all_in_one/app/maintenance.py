"""Low-priority, bounded local enrichment and telemetry. No automatic persistent gear writes."""
import json,threading,time
from pathlib import Path
import advanced

def options():
    try: return json.loads(Path("/data/options.json").read_text())
    except (OSError,ValueError): return {}

def audit(record,path=Path("/data/emergency_history.jsonl")):
    row=dict(record,utc=time.time())
    # Cap file size; retain most recent complete lines. Audit is a command
    # history, never a certified emergency test report.
    if path.exists() and path.stat().st_size>512000:
        lines=path.read_text().splitlines()[-500:]
        tmp=path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines)+"\n")
        tmp.replace(path)
    with path.open("a") as f: f.write(json.dumps(row,separators=(",",":"))+"\n")

def candidates(snapshot,o,now,attempts):
    if snapshot.get("scan_running"): return []
    out=[]
    for g in snapshot.get("gear",[]):
        if not g.get("online") or g.get("address_conflict") or not g.get("ha_uid") or g.get("random_address") is None: continue
        b,a,uid=g["bus"],g["address"],g["ha_uid"]
        if not snapshot.get("buses",{}).get(str(b),{}).get("online"): continue
        jobs=[]
        if o.get("auto_identify",True):
            jobs += [("memory",0,86400,g.get("identity_read_at",0)),("inspect",None,86400,g.get("capabilities_read_at",0))]
        if o.get("d4i_poll_enabled",False):
            period=max(300,min(3600,int(o.get("d4i_poll_interval",900))))
            for bank in (202,205,206):
                if g.get("last_memory_bank",0)>=bank:
                    jobs.append(("memory",bank,period,g.get("sampled_bank_"+str(bank),0)))
        if o.get("dt8_mqtt_enabled",False) and 8 in g.get("device_types",[]):
            jobs.append(("color_read",None,60,g.get("color_read_at",0)))
        for action,bank,period,stamp in jobs:
            k=(uid,b,a,g["random_address"],action,bank)
            due=max(stamp+period,attempts.get(k,0))
            if due<=now: out.append((due,k,dict(controller_id=snapshot["controller_id"],bus=b,address=a,uid=uid,action=action,bank=bank)))
    return sorted(out,key=lambda x:(x[0],str(x[1])))

class Worker:
    def __init__(self,c,log,o=None):
        self.c=c; self.log=log; self.o=options() if o is None else o
        self.stop_event=threading.Event(); self.attempts={}; self.thread=None
    def start(self):
        if not self.c.settings.local_dali_enabled: return
        self.thread=threading.Thread(target=self.run,daemon=True,name="DALI-maintenance")
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=2)
    def step(self):
        c=self.c; now=time.time()
        jobs=candidates(c.snapshot(),self.o,now,self.attempts)
        if not jobs or not c.operation_lock.acquire(blocking=False): return False
        _,k,d=jobs[0]
        try:
            if c.scan_running or self.stop_event.is_set(): return False
            g=advanced.gear(c,d["bus"],d["address"],d["uid"])
            if g.get("random_address")!=k[3]: return False
            self.attempts[k]=now+300
            b,a=d["bus"],d["address"]
            if d["action"]=="color_read":
                if 8 not in advanced.types(c,b,a): return False
                result=advanced.color_state(c,b,a)
                if result:
                    advanced.cache(c,b,a,dict(result,color_read_at=now))
                else: self.attempts[k]=now+300
            else:
                result=advanced.execute(c,d)
                if d["action"]=="inspect" and result.get("device_types"):
                    advanced.cache(c,b,a,{"capabilities_read_at":now})
                if d["action"]=="memory" and d["bank"]==0 and result.get("memory_banks",{}).get("0"):
                    advanced.cache(c,b,a,{"identity_read_at":now})
            return True
        except Exception as e:
            self.attempts[k]=now+900
            self.log("Advanced read deferred: "+str(e))
            return False
        finally: c.operation_lock.release()
    def run(self):
        # At most one job per 30 s, no immediate retry; users and ordinary
        # polling can acquire the operation lock between jobs.
        while not self.stop_event.wait(30):
            try: self.step()
            except Exception as e: self.log("Maintenance cycle failed: "+str(e))

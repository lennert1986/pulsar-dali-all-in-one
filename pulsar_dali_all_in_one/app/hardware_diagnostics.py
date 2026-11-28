"""Read-only, bounded host-visible hardware metadata.
Never read SPI payloads, key files, device-mapper tables or decrypted content.
No device access grants, mounts, unlocks, driver changes or bus probing.
"""
import os,re,stat,subprocess,time,threading,shutil
from pathlib import Path
import dashboards

def read(path,limit=4096):
    try:
        with Path(path).open("rb") as f:return f.read(limit).decode("utf-8","replace").replace("\0","").strip()
    except OSError:return None

def number(path):
    try:return int(read(path))
    except (TypeError,ValueError):return None

def entries(path,pattern):
    try:return sorted(Path(path).glob(pattern))[:64]
    except OSError:return []

def safe_text(v):
    return v[:160] if isinstance(v,str) else None

def identity():
    out={}
    for key,name in (("model","model"),("serial","serial-number"),("compatible","compatible")):
        v=read("/proc/device-tree/"+name)
        if v:out[key]=safe_text(v)
    for line in (read("/proc/cpuinfo",16384) or "").splitlines():
        if ":" not in line:continue
        k,v=(x.strip() for x in line.split(":",1))
        if k in ("Revision","Hardware","Serial"):
            out.setdefault(k.lower(),safe_text(v))
    out["machine"]=os.uname().machine
    out["kernel"]=os.uname().release
    return out

def spi():
    items=[]
    for p in entries("/sys/bus/spi/devices","spi*"):
        if not re.fullmatch(r"spi\d+\.\d+",p.name):continue
        bus,cs=map(int,p.name[3:].split("."))
        node=Path(f"/dev/spidev{bus}.{cs}")
        try:visible=stat.S_ISCHR(node.stat().st_mode)
        except OSError:visible=False
        try:driver=p.joinpath("driver").resolve(strict=True).name
        except OSError:driver=None
        items.append(dict(device=p.name,bus=bus,chip_select=cs,driver=driver,
                          modalias=safe_text(read(p/"modalias")),device_node=str(node),
                          node_visible=visible,metadata_source="sysfs"))
    # Linux may expose a node without the corresponding sysfs directory.
    for p in entries("/dev","spidev*"):
        if not re.fullmatch(r"spidev\d+\.\d+",p.name):continue
        if any(x["device_node"]==str(p) for x in items):continue
        try:
            if not stat.S_ISCHR(p.stat().st_mode):continue
        except OSError:continue
        bus,cs=map(int,p.name[6:].split("."))
        items.append(dict(device=f"spi{bus}.{cs}",bus=bus,chip_select=cs,device_node=str(p),node_visible=True,metadata_source="device node"))
    return dict(devices=items,payload_read=False,key_material="not collected",
                note="Chip model, contents, speed and mode are not inferred from node presence.")

def parse_luks(text):
    """Allowlist summary fields from cryptsetup luksDump, discard all other text."""
    result={}
    for line in text.splitlines():
        if not line or line[0].isspace() or ":" not in line:continue
        key,value=(x.strip() for x in line.split(":",1))
        if key=="Version" and value in ("1","2"):result["version"]=int(value)
        elif key=="UUID" and re.fullmatch(r"[a-fA-F0-9-]{36}",value):result["uuid"]=value
        elif key in ("Cipher name","Cipher mode") and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}",value):result[key.lower().replace(" ","_")]=value
        elif key=="MK bits" and value.isdigit() and 0<int(value)<=4096:result["key_bits"]=int(value)
    # LUKS2 header has indented segment cipher and keyslot key size.
    section="";ciphers=set();sizes=set();slots=0;pbkdf=set()
    for line in text.splitlines():
        if line and not line[0].isspace():
            section=line.split(":",1)[0].strip()
        if section=="Data segments":
            m=re.fullmatch(r"\s*cipher:\s*([a-zA-Z0-9_-]{1,64})\s*",line)
            if m:ciphers.add(m.group(1))
        elif section=="Keyslots":
            if re.fullmatch(r"\s+\d+:\s+luks2\s*",line):slots+=1
            m=re.fullmatch(r"\s*Key:\s*(\d+)\s+bits\s*",line)
            if m and 0<int(m.group(1))<=4096:sizes.add(int(m.group(1)))
            m=re.fullmatch(r"\s*PBKDF:\s*(argon2id|argon2i|pbkdf2)\s*",line,re.I)
            if m:pbkdf.add(m.group(1).lower())
    if result.get("version")==2:
        result.update(ciphers=sorted(ciphers),key_bits_reported=sorted(sizes),keyslots=slots,kdf=sorted(pbkdf))
    return result

def partitions():
    rows=[];encrypted=[];probes=0
    for p in entries("/sys/class/block","*"):
        n=p.name
        if not re.fullmatch(r"(?:mmcblk\d+(?:p\d+)?|sd[a-z]+\d*|nvme\d+n\d+(?:p\d+)?|dm-\d+)",n):continue
        size=number(p/"size")
        row=dict(name=n,bytes=size*512 if size is not None else None,partition=number(p/"partition"),read_only=number(p/"ro"))
        # Device-mapper UUID only classified by prefix, never expose dm tables.
        uuid=read(p/"dm/uuid")
        if uuid and uuid.startswith(("CRYPT-LUKS1-","CRYPT-LUKS2-")):
            row["mapping"]="LUKS mapping";encrypted.append(dict(device=n,status="active mapping",version=2 if uuid.startswith("CRYPT-LUKS2-") else 1))
        # Probe only already exposed block nodes; never grant raw device access.
        node=Path("/dev")/n
        try:visible=stat.S_ISBLK(node.stat().st_mode)
        except OSError:visible=False
        row["block_node_visible"]=visible
        if visible and row["partition"] is not None and shutil.which("cryptsetup") and probes<4:
            probes+=1
            try:
                cp=subprocess.run(["cryptsetup","luksDump",str(node)],capture_output=True,text=True,timeout=2,check=False)
                if cp.returncode==0:
                    info=parse_luks(cp.stdout)
                    if info.get("version"):encrypted.append(dict(device=n,status="LUKS header readable",**info))
            except (OSError,subprocess.TimeoutExpired):pass
        rows.append(row)
    return dict(partitions=rows,encryption=encrypted,scope="Container-visible block devices only",
                note="No readable LUKS header does not establish that the host is unencrypted.")

def emmc():
    out=[]
    for p in entries("/sys/class/mmc_host","mmc*"):
        for dev in entries(p,"mmc*:*"):
            if read(dev/"type")!="MMC":continue
            def hex_values(name):
                v=read(dev/name)
                if not v:return None
                try:return [int(x,16) for x in v.split()]
                except ValueError:return None
            out.append(dict(device=dev.name,name=safe_text(read(dev/"name")),life_time_raw=hex_values("life_time"),pre_eol_raw=hex_values("pre_eol_info"),
                            revision=safe_text(read(dev/"rev"))))
    return out

def rtc():
    return [dict(device=p.name,name=safe_text(read(p/"name")),date=safe_text(read(p/"date")),time=safe_text(read(p/"time")),
                 hctosys=number(p/"hctosys"),battery_status="not measured") for p in entries("/sys/class/rtc","rtc*")]

def thermal():
    out=[]
    for p in entries("/sys/class/thermal","thermal_zone*"):
        value=number(p/"temp")
        if value is not None and -40000<=value<=200000:
            out.append(dict(zone=p.name,type=safe_text(read(p/"type")),temperature_c=value/1000))
    return out

def cpu_sample():
    s=read("/proc/stat")
    try:
        v=list(map(int,s.splitlines()[0].split()[1:9]))
        return sum(v),v[3]+v[4]
    except (AttributeError,ValueError,IndexError):return None

class Monitor:
    def __init__(self,c,log):
        self.c=c;self.log=log;self.lock=threading.Lock();self.stop_event=threading.Event()
        self.thread=None;self.cached={};self.history=[];self.last_buses={};self.cpu=None;self.slow_at=0;self.slow={}
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name="hardware-monitor");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def step(self):
        now=time.monotonic();c=self.c
        sample=cpu_sample();usage=None
        if sample and self.cpu and sample[0]>self.cpu[0]:
            usage=max(0,min(100,round(100*(1-(sample[1]-self.cpu[1])/(sample[0]-self.cpu[0])),1)))
        self.cpu=sample
        if now>=self.slow_at:
            self.slow=dict(identity=identity(),spi=spi(),storage=partitions(),emmc=emmc(),rtc=rtc())
            self.slow_at=now+120
        s=c.snapshot();buses={}
        for b,v in s.get("buses",{}).items():
            buses[str(b)]={k:v.get(k) for k in ("online","uart_ready","firmware","device") if k in v}
            current=(v.get("online"),v.get("uart_ready"))
            if b in self.last_buses and current!=self.last_buses[b]:
                self.history.append(dict(timestamp=time.time(),bus=b,online=current[0],uart_ready=current[1]))
                self.history=self.history[-100:]
            self.last_buses[b]=current
        with dashboards.LOCK:stats={k:dict(v) for k,v in dashboards.STATS.items()}
        resources=dashboards.resources()
        up=read("/proc/uptime")
        try:resources["host_uptime_s"]=int(float(up.split()[0]))
        except (AttributeError,ValueError,IndexError):pass
        resources["cpu_percent"]=usage
        with self.lock:
            self.cached=dict(ok=True,controller_id=c.controller_id,sampled_at=time.time(),
                             scope="Host information visible inside the app container",
                             hardware_profile=getattr(c.settings,"hardware_model",None),
                             hardware_error=getattr(c.settings,"hardware_error",None),
                             resources=resources,thermal=thermal(),buses=buses,transactions=stats,
                             history=list(self.history),**self.slow)
    def status(self):
        with self.lock:return dict(self.cached) if self.cached else dict(ok=True,controller_id=self.c.controller_id,pending=True)
    def run(self):
        while not self.stop_event.is_set():
            try:self.step()
            except Exception:self.log("Hardware metadata collection deferred")
            self.stop_event.wait(10)

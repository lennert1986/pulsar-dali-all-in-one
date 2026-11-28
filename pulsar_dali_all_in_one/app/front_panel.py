"""Vertex front panel: known pin masks only, active-low buttons.
No reset, commissioning, broadcast or other actions on button presses.
Existing DALI activity driver owns OLATB; this worker never writes that register.
"""
import json,time,threading
from pathlib import Path

PINS={"vertex_g3":{"status_red":5,"status_green":6,"network_blue":7},
      "vertex_g4":{"status_red":5,"status_green":6,"network_red":7,"network_blue":3,"network_green":2}}
BUTTONS=("DALI 1","DALI 2","DALI 3","GP / Reset")

class Debounce:
    def __init__(self):
        self.raw=None;self.since=0;self.stable=None;self.down=None
    def update(self,value,now):
        if value!=self.raw:self.raw=value;self.since=now
        if now-self.since<.06 or self.stable==value:return None
        old=self.stable;self.stable=value
        if value:self.down=now if old is False else None
        elif self.down is not None:
            duration=now-self.down;self.down=None
            if duration>=.06:return ("long" if duration>=1.8 else "short",round(duration,2))
        return None

class Panel:
    def __init__(self,c,log):
        self.c=c;self.log=log;self.stop_event=threading.Event();self.lock=threading.Lock();self.thread=None
        self.profile=getattr(c.settings,"hardware_profile","")
        self.pins=PINS.get(self.profile,{})
        self.active_high=self.profile=="vertex_g3"
        self.address=getattr(c.settings,"mcp_address",32)
        self.bus_number=getattr(c.settings,"i2c_bus",1)
        try:opts=json.loads(Path("/data/options.json").read_text())
        except (OSError,ValueError):opts={}
        self.enabled=opts.get("front_panel_enabled") is True and bool(self.pins) and getattr(c.settings,"local_dali_enabled",False) and self.address==32 and self.bus_number==(0 if self.active_high else 1)
        self.state={"status":"disabled" if not self.enabled else "starting"}
        self.buttons=[Debounce() for _ in BUTTONS];self.events=[]
    def status(self):
        with self.lock:return dict(self.state)
    def start(self):
        if self.enabled:
            self.thread=threading.Thread(target=self.run,daemon=True,name="front-panel");self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
    def mask_write(self,bus,reg,mask,value):
        old=bus.read_byte_data(self.address,reg)
        new=(old&~mask)|(value&mask)
        if old!=new:bus.write_byte_data(self.address,reg,new)
    def leds(self,bus,active):
        mask=sum(1<<p for p in self.pins.values())
        bits=sum(1<<self.pins[k] for k in active if k in self.pins)
        self.mask_write(bus,0x14,mask,bits if self.active_high else mask^bits)
    def run(self):
        bus=None
        try:
            from smbus import SMBus
            bus=SMBus(self.bus_number)
            # Known BANK=0 layout only; never change IOCON.
            if bus.read_byte_data(self.address,0x0a)&0x80:raise RuntimeError("Unexpected MCP bank")
            mask=sum(1<<p for p in self.pins.values())
            self.leds(bus,set())
            self.mask_write(bus,0x00,mask|0x10,0x10)
            # The existing activity driver uses only B1/B3/B5 direction and latch.
            self.mask_write(bus,0x01,0x15,0x15)
            self.mask_write(bus,0x0c,0x10,0x10)
            self.mask_write(bus,0x0d,0x15,0x15)
            self.mask_write(bus,0x02,0x10,0)
            self.mask_write(bus,0x03,0x15,0)
            active=set();next_status=0
            while not self.stop_event.is_set():
                now=time.monotonic()
                a=bus.read_byte_data(self.address,0x12);b=bus.read_byte_data(self.address,0x13)
                values=[not bool(b&(1<<i)) for i in (4,2,0)]+[not bool(a&16)]
                for name,deb,value in zip(BUTTONS,self.buttons,values):
                    event=deb.update(value,now)
                    if event:self.events.append({"button":name,"press":event[0],"duration_s":event[1],"timestamp":time.time()})
                self.events=self.events[-100:]
                if now>=next_status:
                    next_status=now+1
                    snap=self.c.snapshot();rows=snap.get("buses",{})
                    healthy=all(rows.get(str(i),rows.get(i,{})).get("online") is True for i in (1,2,3))
                    active={"status_green" if healthy else "status_red"}
                    hw=getattr(self.c,"hardware_monitor",None)
                    eth=hw.status().get("ethernet",{}) if hw else {}
                    ports=eth.get("ports",[])
                    if self.profile=="vertex_g4" and eth.get("status")=="identified":
                        active.add("network_green" if any(p.get("link") for p in ports if p.get("port") in (2,3)) else "network_red")
                    self.leds(bus,active)
                with self.lock:self.state=dict(status="active",profile=self.profile,active_high=self.active_high,buttons=dict(zip(BUTTONS,[d.stable for d in self.buttons])),leds=sorted(active),events=list(self.events),actions="monitor only")
                self.stop_event.wait(.03)
        except Exception as exc:
            with self.lock:self.state={"status":"error","error":type(exc).__name__}
            self.log("Front panel stopped: "+type(exc).__name__)
        finally:
            if bus is not None:
                try:self.leds(bus,set())
                except OSError:pass
                bus.close()

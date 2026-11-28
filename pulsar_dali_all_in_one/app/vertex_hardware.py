"""Bounded read-only diagnostics. No reset, key extraction or switch writes."""
import time
from datetime import datetime, timezone
from pathlib import Path
import spi_identity

def switch(transport=None):
    out=dict(device="/dev/spidev1.0",speed_hz=100000,mode=0,ports=[])
    try:
        spi=transport() if transport else spi_identity.Spi(out["device"],out["speed_hz"])
    except OSError:
        return dict(out,status="unavailable")
    try:
        def reg(a):
            return spi._transfer(bytes([0x60|(a>>7),(a<<1)&255,0]))[2]
        ids=(reg(0),reg(1))
        if ids!=(reg(0),reg(1)) or ids[0]!=0x87 or ids[1]>>4!=9:
            return dict(out,status="no_valid_id")
        out.update(status="identified",family_id=ids[0],chip_id=ids[1],revision=(ids[1]>>1)&7,switch_started=bool(ids[1]&1))
        for port in range(1,5):
            link=reg(port*16+14); speed=reg(port*16+9)
            up=bool(link&0x20)
            out["ports"].append(dict(port=port,label={1:"PHY 1 (ukendt)",2:"Venstre LAN",3:"Højre LAN",4:"PHY 4 (formodet intern)"}[port],link=up,autoneg_done=bool(link&0x40),speed_mbps=(100 if speed&4 else 10) if up else None,duplex=("full" if speed&2 else "half") if up else None))
        out["note"]="Vertex G4 cable test: PHY 2 left, PHY 3 right; PHY 4 presumed internal, PHY 1 unknown. No EEE or MIB indirect access."
        return out
    except (OSError,ValueError,IndexError):
        return dict(out,status="communication_error",ports=[])
    finally:
        spi.close()

def watchdog(read,number,entries):
    return [dict(device=p.name,identity=read(p/"identity"),state=read(p/"state"),timeout_s=number(p/"timeout"),timeleft_s=number(p/"timeleft"),bootstatus=read(p/"bootstatus"),nowayout=read(p/"nowayout")) for p in entries("/sys/class/watchdog","watchdog*")]

def network(number,entries):
    fields=("rx_bytes","tx_bytes","rx_packets","tx_packets","rx_errors","tx_errors","rx_crc_errors","rx_dropped","tx_dropped")
    return [dict(interface=p.name,**{k:number(p/"statistics"/k) for k in fields}) for p in entries("/sys/class/net","*") if p.name!="lo"]

def bootloader(read):
    root=Path("/proc/device-tree/chosen/bootloader")
    result={"scope":"Device tree only"}
    for key in ("version","build-timestamp","capabilities"):
        try:
            with (root/key).open("rb") as f:raw=f.read(128)
            if key=="version":
                v=raw.rstrip(b"\0").decode("ascii")
                if v and all(c.isalnum() or c in ".-_ " for c in v):result[key]=v
            elif len(raw)==4:result[key]=int.from_bytes(raw,"big")
        except (OSError,UnicodeError):pass
    return result

def rtc_offset(rows):
    for row in rows:
        try:
            stamp=datetime.fromisoformat(row["date"]+"T"+row["time"]).replace(tzinfo=timezone.utc).timestamp()
            row["offset_s"]=round(stamp-time.time(),1)
        except (TypeError,ValueError,KeyError):row["offset_s"]=None
    return rows

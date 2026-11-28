"""Opt-in identification of the known Vertex G4 SPI1/CS1 device.
Fixed JEDEC/SFDP transactions only. No array, OTP, UID or security-register reads.
Linux spidev ioctl ABI, no external Python SPI package required.
"""
import ctypes
import fcntl
import os
import stat
import struct
from pathlib import Path

DEVICE="/dev/spidev1.1"
SPEED=500000
MANUFACTURERS={0xEF:"Winbond",0xC2:"Macronix",0x20:"Micron / ST",0xC8:"GigaDevice",0x1F:"Adesto / Atmel",0x01:"Infineon / Cypress",0x9D:"ISSI",0xBF:"Microchip / SST"}
# Capacity inference is deliberately restricted to familiar NOR families.
FAMILIES={(0xEF,0x40):"W25Q", (0xEF,0x60):"W25Q", (0xC2,0x20):"MX25L", (0xC8,0x40):"GD25Q"}
def jedec(raw):
    if len(raw)!=3 or raw[0] in (0,255,0x7f) or raw[1:] in (b"\0\0",b"\xff\xff"):
        return dict(status="no_valid_id",note="No valid three-byte JEDEC ID; device may be EEPROM or unsupported.")
    m,t,n=raw
    out=dict(status="identified",jedec_id=raw.hex(" ").upper(),manufacturer=MANUFACTURERS.get(m,"Unknown"),memory_type=f"{t:02X}",capacity_code=f"{n:02X}")
    if (m,t) in FAMILIES:
        out["family"]=FAMILIES[m,t]
        if 0x10<=n<=0x20:out["jedec_capacity_bytes"]=1<<n
    return out

def density(raw):
    if len(raw)!=4:return None
    n=int.from_bytes(raw,"little")
    if n==0xffffffff:return None
    if n&0x80000000:
        power=n&0x7fffffff
        if not 3<=power<=43:return None
        bits=1<<power
    else:bits=n+1
    return bits//8 if bits>=8 and bits%8==0 else None

class Spi:
    def __init__(self):
        if not stat.S_ISCHR(os.stat(DEVICE).st_mode):raise OSError("Not a character device")
        self.fd=os.open(DEVICE,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW)
        self.old={}
        try:
            # Save and restore volatile Linux SPI settings, not chip registers.
            for nr,fmt,value in ((1,"B",0),(3,"B",8),(4,"I",SPEED)):
                size=struct.calcsize(fmt);read=0x80000000|(size<<16)|(ord("k")<<8)|nr
                write=0x40000000|(size<<16)|(ord("k")<<8)|nr
                buf=bytearray(size);fcntl.ioctl(self.fd,read,buf,True)
                self.old[write]=bytes(buf)
                fcntl.ioctl(self.fd,write,struct.pack(fmt,value))
        except BaseException:
            self.close();raise
    def close(self):
        try:
            for cmd,data in reversed(tuple(self.old.items())):
                try:fcntl.ioctl(self.fd,cmd,data)
                except OSError:pass
        finally:os.close(self.fd)
    def _transfer(self,tx):
        # Linux struct spi_ioc_transfer has fixed 32-byte layout on both supported architectures.
        n=len(tx)
        src=ctypes.create_string_buffer(bytes(tx),n);dst=ctypes.create_string_buffer(n)
        desc=struct.pack("=QQIIHBBBBBB",ctypes.addressof(src),ctypes.addressof(dst),n,SPEED,0,8,0,0,0,0,0)
        fcntl.ioctl(self.fd,0x40206b00,desc)
        return dst.raw
    def id(self):return self._transfer(b"\x9f\0\0\0")[1:]
    def sfdp(self,address,count):
        # SFDP parameter space, not flash array. Strictly bounded.
        if not 0<=address<=0xffffff or not 1<=count<=128 or address+count>0x1000000:raise ValueError("Invalid SFDP bounds")
        return self._transfer(b"\x5a"+address.to_bytes(3,"big")+b"\0"+bytes(count))[5:]

def identify(transport=Spi):
    result=dict(device=DEVICE,speed_hz=SPEED,mode=0,payload_read=False)
    try:spi=transport()
    except PermissionError:return dict(result,status="permission_denied")
    except FileNotFoundError:return dict(result,status="device_missing")
    except OSError:return dict(result,status="open_failed")
    try:
        raw=spi.id()
        if raw!=spi.id():return dict(result,status="unstable_response")
        result.update(jedec(raw))
        if result["status"]!="identified":return result
        # Probe SFDP only after a stable, known NOR family ID.
        if "family" not in result:
            result["sfdp_status"]="not_probed_unknown_family";return result
        header=spi.sfdp(0,8)
        if len(header)!=8 or header[:4]!=b"SFDP" or header[5]!=1:
            result["sfdp_status"]="not_detected";return result
        result.update(sfdp_status="detected",sfdp_revision=f"{header[5]}.{header[4]}")
        count=min(header[6]+1,16)
        headers=spi.sfdp(8,count*8)
        for i in range(0,len(headers),8):
            h=headers[i:i+8]
            if len(h)!=8 or h[0]!=0 or h[7]!=255 or h[2]!=1 or h[3]<2:continue
            pointer=int.from_bytes(h[4:7],"little")
            if pointer<8+count*8 or pointer>0xfffff8:continue
            size=density(spi.sfdp(pointer+4,4))
            if size:
                result["sfdp_capacity_bytes"]=size
                result["capacity_mismatch"]=bool(result.get("jedec_capacity_bytes") and result["jedec_capacity_bytes"]!=size)
                break
        return result
    except (OSError,ValueError,struct.error):return dict(result,status="communication_error")
    finally:spi.close()

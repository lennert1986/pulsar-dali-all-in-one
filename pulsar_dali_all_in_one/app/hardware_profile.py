"""Resolve Vertex hardware without probing or transmitting to unrelated serial devices."""
from pathlib import Path
import os

G4 = ("/dev/ttyAMA3", "/dev/ttyAMA4", "/dev/ttyAMA5")
PROFILES = ("auto", "vertex_g3", "vertex_g4", "remote_only", "manual")

def read(path):
    try:
        return Path(path).read_text(errors="replace").strip("\x00\r\n ")
    except OSError:
        return ""

def board_model():
    for path in ("/device-tree/model", "/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        model = read(path)
        if model:
            return model
    for line in read("/proc/cpuinfo").splitlines():
        if line.partition(":")[0].strip()=="Revision":
            try:
                code=int(line.partition(":")[2].strip(),16)
                if code & (1<<23):
                    model=(code>>4)&255
                    if model==0x14:return "Raspberry Pi Compute Module 4"
                    if model in (0x0a,0x10):return "Raspberry Pi Compute Module 3"
            except ValueError:pass
    return ""

def ftdi_interfaces(sys_tty="/sys/class/tty", dev_dir="/dev", present=None):
    """Return {physical USB parent: {interface number: [device paths]}}.
    Use USB bInterfaceNumber, not ttyUSB enumeration order or port labels.
    """
    present = present or (lambda path: Path(path).is_char_device())
    groups = {}
    for entry in sorted(Path(sys_tty).glob("ttyUSB*")):
        port = str(Path(dev_dir) / entry.name)
        if not present(port):
            continue
        try:
            path = (entry / "device").resolve(strict=True)
        except OSError:
            continue
        interface = None
        for parent in (path, *path.parents):
            number = read(parent / "bInterfaceNumber")
            if number:
                try:
                    interface = int(number, 16)
                except ValueError:
                    break
            vid, pid = read(parent / "idVendor"), read(parent / "idProduct")
            if vid or pid:
                if vid.lower() == "0403" and pid.lower() == "6011" and interface is not None:
                    groups.setdefault(str(parent), {}).setdefault(interface, []).append(port)
                break
    return groups

def g3_ports(groups):
    # Reject multiple matching adapters, partial enumeration and duplicate interfaces.
    if len(groups) != 1:
        raise ValueError("Expected exactly one FTDI 0403:6011 USB adapter; found %d" % len(groups))
    mapping = next(iter(groups.values()))
    if any(len(mapping.get(i, [])) != 1 for i in (0, 1, 2)):
        raise ValueError("FTDI interfaces 00, 01 and 02 are not uniquely mapped")
    paths = tuple(mapping[i][0] for i in (0, 1, 2))
    if len(set(paths)) != 3:
        raise ValueError("Duplicate FTDI device paths")
    return paths

def resolve(options, *, model=None, groups=None, present=None):
    """Apply a profile in memory. Never rewrite options.json."""
    result = dict(options)
    requested = str(result.get("hardware_model", "auto"))
    model = board_model() if model is None else model
    present = present or (lambda path: Path(path).is_char_device())
    result.update(hardware_requested=requested, hardware_board=model,
                  hardware_profile="remote_only", hardware_error="")
    if requested == "remote_only" or not result.get("local_dali_enabled", True):
        result.update(local_dali_enabled=False, led_enabled=False)
        return result
    try:
        if requested not in PROFILES:
            raise ValueError("Unknown hardware profile")
        profile = requested
        manual = tuple(str(result.get("dali%d_device" % i, G4[i-1])).strip() for i in (1, 2, 3))
        if profile == "auto":
            # Preserve installations with custom v0.13 UART settings.
            if manual != G4:
                profile = "manual"
            elif "compute module 3" in model.lower():
                profile = "vertex_g3"
            elif "compute module 4" in model.lower():
                profile = "vertex_g4"
            else:
                raise ValueError("Unknown board; select vertex_g3, vertex_g4 or manual")
        if profile == "vertex_g3":
            paths = g3_ports(ftdi_interfaces(present=present) if groups is None else groups)
            bus = 0
        elif profile == "vertex_g4":
            paths, bus = G4, 1
        else:
            paths, bus = manual, int(result.get("i2c_bus", 1))
        if len(set(paths)) != 3 or len({os.path.realpath(x) for x in paths}) != 3:
            raise ValueError("Three distinct serial device paths are required")
        if not all(path.startswith("/dev/") and present(path) for path in paths):
            raise ValueError("One or more selected serial devices are missing: " + ", ".join(paths))
        result.update(hardware_profile=profile, local_dali_enabled=True, i2c_bus=bus)
        for i, path in enumerate(paths, 1):
            result["dali%d_device" % i] = path
        return result
    except (ValueError, OSError) as exc:
        # Keep remote API/management available, but don't open guessed local ports.
        result.update(hardware_profile="unavailable", hardware_error=str(exc),
                      local_dali_enabled=False, led_enabled=False, auto_scan=False)
        return result

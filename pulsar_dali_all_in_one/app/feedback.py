"""IEC 62386-332 feedback, corrected query opcodes (COR1:2019).
Explicit parameter writes, with readback; active mode is not proof of LED light.
"""
QUERY_CAPABILITY=0x4F
QUERY_ACTIVE=0x4E
QUERY_TIMING=0x4D
QUERY_ACTIVE_BRIGHTNESS=0x4C
QUERY_ACTIVE_COLOUR=0x4B
QUERY_INACTIVE_BRIGHTNESS=0x4A
QUERY_INACTIVE_COLOUR=0x49
ACTIVATE=0x10
STOP=0x11

def address(c,a,inst):
    if type(a) is not int or not 0<=a<=63 or type(inst) is not int or not 0<=inst<=31:
        raise ValueError("Invalid feedback address")
    return 0x20|inst,c._control_device_address(a)

def query(c,b,a,inst,opcode):
    feature,addr=address(c,a,inst)
    return c._s2or(b,opcode,feature,addr)

def decode(cap):
    if cap is None:return None
    if type(cap) is not int or not 0<=cap<=63:
        raise ValueError("Invalid feedback capability reply")
    return dict(visible=bool(cap&1),brightness=bool(cap&2),colour=bool(cap&4),
                audible=bool(cap&8),volume=bool(cap&16),pitch=bool(cap&32))

def active(raw):
    # YES is 0xff; NO is silence. Silence may also be a lost reply.
    if raw is None:return None
    if raw==255:return True
    raise ValueError("Unexpected QUERY FEEDBACK ACTIVE reply")

def inspect(c,b,a,inst):
    cap=query(c,b,a,inst,QUERY_CAPABILITY)
    features=decode(cap)
    r=dict(feedback_capability=cap,feedback_features=features)
    if features is None or not cap:return r
    r["feedback_active"]=active(query(c,b,a,inst,QUERY_ACTIVE))
    r["feedback_timing"]=query(c,b,a,inst,QUERY_TIMING)
    if features["visible"]:
        r["active_brightness"]=query(c,b,a,inst,QUERY_ACTIVE_BRIGHTNESS)
        r["inactive_brightness"]=query(c,b,a,inst,QUERY_INACTIVE_BRIGHTNESS)
    if features["colour"]:
        r["active_colour"]=query(c,b,a,inst,QUERY_ACTIVE_COLOUR)
        r["inactive_colour"]=query(c,b,a,inst,QUERY_INACTIVE_COLOUR)
    return r

def command(c,b,a,inst,value):
    if type(value) is not int or value not in (0,1):
        raise ValueError("Feedback value must be 0 or 1")
    feature,addr=address(c,a,inst)
    cap=query(c,b,a,inst,QUERY_CAPABILITY)
    features=decode(cap)
    # This operation is for visible indicators only, not audible alarms.
    if not features or not features["visible"] or features["audible"]:
        raise ValueError("Visible-only feedback capability not confirmed")
    c._s2on(b,ACTIVATE if value else STOP,feature,addr)
    state=active(query(c,b,a,inst,QUERY_ACTIVE))
    # Confirm the target still responds; a silent active query never proves OFF.
    after=query(c,b,a,inst,QUERY_CAPABILITY)
    return dict(feedback_capability=cap,requested_active=bool(value),feedback_active=state,
                command_sent=True,readback_verified=bool(value and state is True and after==cap),
                target_responded=after==cap,persistent_writes=False,
                note="Active mode is not proof of visible light. No reply is not proof of inactive mode.")

PARAMS={
    "active_brightness":(0x13,QUERY_ACTIVE_BRIGHTNESS,0,255),
    "active_colour":(0x14,QUERY_ACTIVE_COLOUR,1,63),
    "inactive_brightness":(0x15,QUERY_INACTIVE_BRIGHTNESS,0,255),
    "inactive_colour":(0x16,QUERY_INACTIVE_COLOUR,1,63),
    "feedback_timing":(0x12,QUERY_TIMING,0,255),
}

def visible(c,b,a,inst):
    cap=query(c,b,a,inst,QUERY_CAPABILITY)
    features=decode(cap)
    if not features or not features["visible"] or features["audible"]:
        raise ValueError("Visible-only feedback capability not confirmed")
    return features

def configure(c,b,a,inst,parameter,value):
    if parameter not in PARAMS:raise ValueError("Unknown feedback parameter")
    op,readback,lo,hi=PARAMS[parameter]
    if type(value) is not int or not lo<=value<=hi:raise ValueError("Invalid feedback value")
    features=visible(c,b,a,inst)
    if parameter.endswith("colour") and not features["colour"]:
        raise ValueError("Colour not supported")
    if parameter.endswith("brightness") and not features["brightness"] and value not in (0,255):
        raise ValueError("Only on/off brightness supported")
    current=query(c,b,a,inst,readback)
    if current is None:raise ValueError("Feedback parameter not readable")
    if current!=value:
        feature,addr=address(c,a,inst)
        c._dali2_dtr0(b,value)
        c._s2tn(b,op,feature,addr)
    actual=query(c,b,a,inst,readback)
    if actual!=value:raise RuntimeError("Feedback parameter readback mismatch; write may have occurred")
    return dict(parameter=parameter,requested=value,readback=actual,changed=current!=value,persistent_writes=current!=value)

def steady(c,b,a,inst):
    visible(c,b,a,inst)
    timing=query(c,b,a,inst,QUERY_TIMING)
    if timing is None or timing&0xC7!=0xC7:
        raise ValueError("Set feedback timing to steady (255) before automatic or MQTT control")

"""Read-only probe of a Commander CORE. Wakes it, reads, returns it to hardware mode."""
import json, sys, time
sys.path.insert(0, __file__.rsplit('/tools/', 1)[0])
from neorgb.hidraw import enumerate_hidraw
from neorgb.devices.commander_core import CommanderCore, MODELS, VID

infos = [i for i in enumerate_hidraw(VID) if i.pid in MODELS and i.interface == 0]
print(infos)
cc = CommanderCore(infos[0])
try:
    cc.open()
    print("fw", cc.firmware, "aio", cc.aio)
    cc.enter_software()
    print("leds", cc.read_led_counts())
    print("connected", cc.read_connected())
    print("rpm", cc.read_speeds())
    print("temps", cc.read_temps())
    print("hw", json.dumps(cc.read_hw_config()))
finally:
    cc.close()

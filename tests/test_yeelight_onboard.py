"""Tests for yeelight_onboard.py with a fake python-miio (no lamp and no python-miio needed).

Run: python3 tests/test_yeelight_onboard.py
"""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import types

TOKEN = bytes.fromhex("00112233445566778899aabbccddeeff")
calls = []


class FakeHeader:
    def __init__(self):
        self.value = types.SimpleNamespace(device_id=bytes.fromhex("1234abcd"))


class FakeProtocol:
    reveal = TOKEN

    def __init__(self, ip=None, token=None, timeout=5, **kw):
        calls.append(("handshake-to", ip))

    def send_handshake(self, **kw):
        return types.SimpleNamespace(checksum=FakeProtocol.reveal, header=FakeHeader())


class FakeInfo:
    model, firmware_version, mac_address, token = "yeelink.light.ceiling3", "1.5.9", "5C:E5:0C:00:00:01", TOKEN.hex()

    def __repr__(self):  # like python-miio: the repr contains the token
        return f"{self.model} v{self.firmware_version} - token: {self.token}"


class FakeDevice:
    wifi_raises = False

    def __init__(self, ip=None, token=None, **kw):
        calls.append(("device", ip, token))

    def info(self):
        calls.append(("info",))
        return FakeInfo()

    def send(self, command, parameters=None, **kw):
        calls.append(("send", command, parameters))
        return ["ok"]

    def configure_wifi(self, ssid, password, uid=0, extra_params=None):
        calls.append(("configure_wifi", ssid, password))
        if FakeDevice.wifi_raises:
            raise TimeoutError("lamp left its network")
        return "ok"


miio = types.ModuleType("miio"); miio.Device = FakeDevice
proto = types.ModuleType("miio.miioprotocol"); proto.MiIOProtocol = FakeProtocol
sys.modules.update({"miio": miio, "miio.miioprotocol": proto})

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("yo", HERE.parent / "yeelight_onboard.py")
yo = importlib.util.module_from_spec(spec); spec.loader.exec_module(yo)


def run(argv, stdin=""):
    calls.clear()
    out, code = io.StringIO(), 0
    old, sys.stdin = sys.stdin, io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            yo.main(argv)
    except SystemExit as e:
        code = e.code
    finally:
        sys.stdin = old
    return code, out.getvalue() + (code if isinstance(code, str) else "")


tmp = tempfile.mkdtemp()
tokenfile = pathlib.Path(tmp) / "yeelight-1234abcd.json"

# 1. normal setup: token saved privately, never printed; LAN Control before WiFi
code, out = run(["Joe's net", "--ip", "192.168.1.1", "--out", tmp], "!pass word\n")
assert code == 0, out
assert TOKEN.hex() not in out and "pass word" not in out, out
record = json.loads(tokenfile.read_text())
assert record["token"] == TOKEN.hex() and record["model"] == "yeelink.light.ceiling3" and record["firmware"] == "1.5.9"
assert stat.S_IMODE(os.stat(tokenfile).st_mode) == 0o600
names = [c[0] if c[0] != "send" else c[1] for c in calls]
assert names.index("set_ps") < names.index("configure_wifi"), names
assert ("send", "set_ps", ["cfg_lan_ctrl", "1"]) in calls
assert ("configure_wifi", "Joe's net", "!pass word") in calls
print("1 setup: token in 0600 file and not printed; LAN Control sent before WiFi settings")

# 2. --no-lan-control skips it
code, out = run(["Net", "pw123456", "--ip", "192.168.1.1", "--out", tmp, "--no-lan-control"])
assert code == 0 and not any(c[0] == "send" for c in calls), calls
print("2 --no-lan-control: no set_ps")

# 3. lamp leaves its network before answering: still a normal exit with a clear message
FakeDevice.wifi_raises = True
code, out = run(["Net", "pw123456", "--ip", "192.168.1.1", "--out", tmp])
FakeDevice.wifi_raises = False
assert code == 0 and "no answer from the lamp (TimeoutError)" in out, out
print("3 no answer after WiFi settings: reported as normal")

# 4. a lamp that hides its token is refused, nothing saved
FakeProtocol.reveal = b"\xff" * 16
tokenfile.unlink()
code, out = run(["Net", "pw123456", "--ip", "192.168.1.1", "--out", tmp])
FakeProtocol.reveal = TOKEN
assert isinstance(code, str) and "does not reveal its token" in code and not tokenfile.exists(), out
print("4 hidden token: refused, no file written")

# 5. --lan-control on/off uses the saved token and the given address, then checks port 55443
run(["Net", "pw123456", "--ip", "192.168.1.1", "--out", tmp])
for state, port_state in (("on", True), ("off", False)):
    yo.port_open = lambda ip, port=55443, timeout=3, s=port_state: s
    code, out = run(["--lan-control", state, "--ip", "192.168.0.50", "--token-file", str(tokenfile)])
    assert code in (0, None), out
    assert ("device", "192.168.0.50", TOKEN.hex()) in calls
    assert ("send", "set_ps", ["cfg_lan_ctrl", "1" if state == "on" else "0"]) in calls, calls
    assert f"port 55443 is {'open' if state == 'on' else 'closed'}" in out and TOKEN.hex() not in out
yo.port_open = lambda ip, port=55443, timeout=3: False  # lamp accepts "on" but the port stays closed
code, out = run(["--lan-control", "on", "--ip", "192.168.0.50", "--token-file", str(tokenfile)])
assert isinstance(code, str) and "still closed" in code, out
print("5 --lan-control on/off: set_ps 1/0 to the new address with the saved token; port check reported, mismatch is an error")

# 5b. the port check waits between attempts (the lamp needs a few seconds)
sleeps, answers = [], iter([False, False, True])
yo.time.sleep = lambda s: sleeps.append(s)
yo.port_open = lambda ip, port=55443, timeout=3: next(answers)
code, out = run(["--lan-control", "on", "--ip", "192.168.0.50", "--token-file", str(tokenfile)])
assert code in (0, None) and sleeps == [1, 1] and "port 55443 is open" in out, (code, sleeps, out)
sleeps.clear(); yo.port_open = lambda ip, port=55443, timeout=3: True
code, out = run(["--lan-control", "off", "--ip", "192.168.0.50", "--token-file", str(tokenfile)])
assert isinstance(code, str) and "still open" in code and len(sleeps) == 9, (code, sleeps)
print("5b port check: waits 1 s between attempts (2 waits until open; 9 waits before giving up)")

# 6. input checks and the guessed address
code, out = run(["x" * 33, "pw123456", "--ip", "192.168.1.1", "--out", tmp])
assert isinstance(code, str) and "1-32 bytes" in code
code, out = run(["--lan-control", "on", "--ip", "1.2.3.4"])
assert isinstance(code, str) and "needs --ip and --token-file" in code
assert yo.guess_lamp_ip().endswith(".1")
print("6 input checks ok; guessed address ends in .1:", yo.guess_lamp_ip())

print(f"all Yeelight tests passed (Python {sys.version.split()[0]})")

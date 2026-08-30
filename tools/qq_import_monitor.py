#!/usr/bin/env python3
"""Monitor a desktop-to-phone QQ migration to see what the import actually carries.

Why this exists: a desktop-to-phone import can look broken, showing only file transfer entries on the
phone with the text gone. This attaches to the phone client during a live import and logs what its
native backup library decrypts, which answers two questions at once: does the text ever reach the
phone (and if so we capture it before the client drops it), and what is the desktop store path (the
decrypted requests carry it, which is how we found the desktop archive on disk).

It only hooks; it never force loads a library and never writes to the client. Forcing the native
library to load out of band crashes the client, so we wait for the import to load it naturally and
hook the methods once they register.

Requirements: frida 16.x on both sides (frida 17 removed the Java bridge, so `Java` is undefined and
this cannot run). Attach by PID, since attach by name calls process enumeration internally and that
call hangs on some emulators.

Usage: python qq_import_monitor.py --host 127.0.0.1:27044 --pid <phone QQ pid>
Then start the import on the desktop. Watch the printed events. No real data appears in this file; the
example account below is the synthetic 123456789.
"""
import argparse
import sys
import time

MAIN_PACKAGE = "com.tencent.mobileqq"

# Hooks: the native decrypt entry points, the imported-message entity, and the library load event.
JS = r"""
Java.perform(function () {
  function asAscii(a, n) {
    if (!a) return "null";
    var o = "", L = Math.min(n || 120, a.length);
    for (var i = 0; i < L; i++) { var b = a[i] & 0xff; o += (b >= 32 && b < 127) ? String.fromCharCode(b) : "."; }
    return o;
  }
  var hooked = false;
  function hookNatives() {
    if (hooked) return;
    try {
      var P = Java.use("com.tencent.mobileqq.msgbackup.transport.MsgBackupJniProxy");
      try { P.setEncryptKey.implementation = function (a, key, b) { send({tag: "KEY", key: "" + key}); return this.setEncryptKey(a, key, b); }; } catch (e) {}
      try { P.decryptFromByteArray.implementation = function (data, key) { var r = this.decryptFromByteArray(data, key); send({tag: "DEC", key: "" + key, len: data ? data.length : 0, out: asAscii(r)}); return r; }; } catch (e) {}
      try { P.decryptFromString.implementation = function (s, key) { var r = this.decryptFromString(s, key); send({tag: "DECS", key: "" + key, out: ("" + r).slice(0, 80)}); return r; }; } catch (e) {}
      hooked = true; send({tag: "hooked-native"});
    } catch (e) { send({tag: "hookerr", e: "" + e}); }
  }
  // Each imported message becomes a MsgBackupMsgEntity; its byte fields may carry the content.
  try {
    var E = Java.use("com.tencent.mobileqq.msgbackup.data.MsgBackupMsgEntity");
    E.postRead.implementation = function () {
      try {
        var js = Java.use("java.lang.String");
        function u(a) { try { return a ? js.$new(a, "UTF-8").toString().slice(0, 150) : null; } catch (e) { return asAscii(a, 120); } }
        send({tag: "ENTITY", mt: this.msgType.value, uin: "" + this.chatUin.value,
              extra: u(this.extraData.value), ext: u(this.extensionData.value)});
      } catch (e) {}
      return this.postRead();
    };
    send({tag: "entity-hooked"});
  } catch (e) { send({tag: "entity-err", e: ("" + e).slice(0, 60)}); }
  // Android 9 has one overload of loadLibrary0. Detect the backup library load, then hook the natives.
  try {
    var RT = Java.use("java.lang.Runtime");
    RT.loadLibrary0.overload("java.lang.ClassLoader", "java.lang.String").implementation = function (cl, n) {
      var r = this.loadLibrary0(cl, n);
      if (/msgbackup/i.test(n)) { send({tag: "LIBLOADED", name: "" + n}); hookNatives(); }
      return r;
    };
  } catch (e) {}
  hookNatives();
  send({tag: "ready"});
});
"""


def main():
    ap = argparse.ArgumentParser(description="monitor a QQ desktop-to-phone import")
    ap.add_argument("--host", default="127.0.0.1:27044", help="frida remote device host:port")
    ap.add_argument("--pid", type=int, required=True, help="phone QQ main process pid")
    a = ap.parse_args()
    try:
        import frida
    except ImportError:
        sys.stderr.write("ERROR: needs frida 16.x. pip install frida==16.7.19\n")
        return 2
    dev = frida.get_device_manager().add_remote_device(a.host)
    session = dev.attach(a.pid)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print(m.get("payload") if m.get("type") == "send" else m.get("description"), flush=True))
    script.load()
    print("ARMED. Start the import on the desktop now.", flush=True)
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()

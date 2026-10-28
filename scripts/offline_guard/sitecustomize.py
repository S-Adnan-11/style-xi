"""Socket audit guard inherited by Python children of check_offline.py.

This is a verification aid for the public Python entry points, not an OS sandbox.
Blocked attempts are recorded even if a library catches the resulting exception.
"""

import ipaddress
import os
from pathlib import Path
import sys


ACTIVE = False
log = os.environ.get("STYLE_XI_NETWORK_LOG")

if log:
    log_path = Path(log)

    def loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def audit(event, args):
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
            host = args[0]
        elif event == "socket.getnameinfo":
            host = args[0][0]
        elif event in ("socket.connect", "socket.bind", "socket.sendto"):
            address = args[1]
            # Unix-domain sockets stay local to the machine.
            if not isinstance(address, tuple):
                return
            host = address[0]
        else:
            return
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        if loopback(host):
            return
        # Do not log addresses, URLs, headers or environment values.
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(event + "\n")
        raise RuntimeError("offline verification blocked non-loopback transport")

    sys.addaudithook(audit)
    ACTIVE = True

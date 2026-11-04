"""Start the agent on the address of one network interface: python -m adapter.serve

    AGENT_BIND_IFACE=wg0 AGENT_PORT=9001

In k3s the agent runs with hostNetwork and must answer on the WireGuard address only. That address differs per host,
and a manifest cannot know it; the interface name is the same everywhere. A missing interface stops the agent:
listening on every address instead would publish it to the internet.
"""
from __future__ import annotations

import fcntl
import os
import socket
import struct

import uvicorn

SIOCGIFADDR = 0x8915


def interface_address(name: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        packed = fcntl.ioctl(probe.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()[:15]))
    return socket.inet_ntoa(packed[20:24])


if __name__ == "__main__":
    iface = os.environ.get("AGENT_BIND_IFACE")
    host = interface_address(iface) if iface else os.environ.get("AGENT_HOST", "127.0.0.1")
    uvicorn.run("adapter.main:app", host=host, port=int(os.environ.get("AGENT_PORT", "9000")))

"""Network monitoring: throughput, interfaces, connections and listening ports."""

from __future__ import annotations

import socket
import time

import psutil

from core.base import Metric, Monitor, MonitorResult
from utils.formatting import human_bytes


class NetworkMonitor(Monitor):
    name = "network"

    def __init__(self, thresholds=None) -> None:
        super().__init__(thresholds)
        self._prev: tuple[float, int, int] | None = None

    def _collect(self, result: MonitorResult) -> None:
        self._collect_throughput(result)
        self._collect_interfaces(result)
        self._collect_connections(result)

    def _collect_throughput(self, result: MonitorResult) -> None:
        io = psutil.net_io_counters()
        now = time.monotonic()
        if self._prev is None:
            self._prev = (now, io.bytes_sent, io.bytes_recv)
            time.sleep(0.2)
            io = psutil.net_io_counters()
            now = time.monotonic()
        prev_t, prev_sent, prev_recv = self._prev
        elapsed = max(now - prev_t, 1e-6)
        up_rate = max(io.bytes_sent - prev_sent, 0) / elapsed
        down_rate = max(io.bytes_recv - prev_recv, 0) / elapsed
        self._prev = (now, io.bytes_sent, io.bytes_recv)

        total_mbps = (up_rate + down_rate) * 8 / 1_000_000
        result.add(
            Metric(
                name="upload_rate_bytes",
                value=round(up_rate),
                unit="B/s",
                tags={"human": f"{human_bytes(up_rate)}/s"},
            )
        )
        result.add(
            Metric(
                name="download_rate_bytes",
                value=round(down_rate),
                unit="B/s",
                tags={"human": f"{human_bytes(down_rate)}/s"},
            )
        )
        result.add(
            Metric(
                name="throughput_mbps",
                value=round(total_mbps, 2),
                unit="Mbps",
                severity=self.severity_for("throughput_mbps", total_mbps),
            )
        )
        result.add(Metric(name="total_sent_bytes", value=io.bytes_sent, unit="B"))
        result.add(Metric(name="total_recv_bytes", value=io.bytes_recv, unit="B"))
        result.add(Metric(name="packets_sent", value=io.packets_sent, unit="count"))
        result.add(Metric(name="packets_recv", value=io.packets_recv, unit="count"))
        errors = io.errin + io.errout + io.dropin + io.dropout
        result.add(Metric(name="packet_errors", value=errors, unit="count"))

    def _collect_interfaces(self, result: MonitorResult) -> None:
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except OSError:
            return
        active = 0
        for name, st in stats.items():
            if st.isup:
                active += 1
                ipv4 = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
                result.add(
                    Metric(
                        name="interface_up",
                        value=name,
                        unit="",
                        tags={"speed_mbps": st.speed, "addresses": ipv4},
                    )
                )
        result.add(Metric(name="active_interfaces", value=active, unit="count"))

    def _collect_connections(self, result: MonitorResult) -> None:
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError):
            result.error("Listing network connections requires elevated privileges")
            return
        except OSError as exc:
            result.error(f"net_connections failed: {exc}")
            return
        established = sum(1 for c in connections if c.status == "ESTABLISHED")
        listening_ports = sorted({c.laddr.port for c in connections if c.status == "LISTEN" and c.laddr})
        result.add(Metric(name="connection_count", value=len(connections), unit="count"))
        result.add(Metric(name="established_count", value=established, unit="count"))
        result.add(
            Metric(
                name="listening_ports",
                value=len(listening_ports),
                unit="count",
                tags={"ports": listening_ports[:50]},
            )
        )

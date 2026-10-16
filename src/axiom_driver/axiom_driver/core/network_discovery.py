"""Browse the HTTP mDNS service already advertised by Axiom firmware."""

import threading

from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf


class NetworkDiscovery(ServiceListener):

    def __init__(self):
        self._lock = threading.Lock()
        self._services = {}
        self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        try:
            self._browser = ServiceBrowser(self._zeroconf, '_http._tcp.local.', self)
        except Exception:
            self._zeroconf.close()
            raise

    def add_service(self, zeroconf, service_type, name):
        self.update_service(zeroconf, service_type, name)

    def update_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name, timeout=1000)
        if info is None:
            return
        # Raft advertises board=esp32; the /api/v probe establishes Axiom identity.
        addresses = info.parsed_addresses(IPVersion.V4Only)
        candidate = info.properties.get(b'board') == b'esp32' or name.lower().startswith('axiom')
        with self._lock:
            if candidate and addresses:
                self._services[name] = f'ws://{addresses[0]}:{info.port}/ws'
            else:
                self._services.pop(name, None)

    def remove_service(self, zeroconf, service_type, name):
        with self._lock:
            self._services.pop(name, None)

    def snapshot(self):
        """Copy the current endpoints without waiting for network operations."""
        with self._lock:
            return tuple(sorted(set(self._services.values())))

    def close(self):
        self._browser.cancel()
        self._zeroconf.close()

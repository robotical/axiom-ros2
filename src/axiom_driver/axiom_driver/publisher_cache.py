"""Publishers owned by the ROS adapter, with explicit QoS and lifetime."""

import threading


class PublisherCache:
    def __init__(self, node, default_qos=10):
        self._node = node
        self._qos = default_qos
        self._cache = {}
        self._lock = threading.RLock()

    def get(self, topic, msg_type, qos=None):
        key = (topic, msg_type)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = self._node.create_publisher(
                    msg_type, topic, self._qos if qos is None else qos
                )
            return self._cache[key]

    def remove(self, prefix):
        with self._lock:
            for key in list(self._cache):
                if key[0] == prefix or key[0].startswith(prefix + '/'):
                    self._node.destroy_publisher(self._cache.pop(key))

    def clear(self):
        with self._lock:
            for publisher in self._cache.values():
                self._node.destroy_publisher(publisher)
            self._cache.clear()

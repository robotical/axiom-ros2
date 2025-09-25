from typing import Dict, Tuple, Type
from rclpy.node import Node

class PublisherCache:
    def __init__(self, node: Node):
        self._node = node
        self._cache: Dict[Tuple[str, Type], object] = {}

    def get(self, topic: str, msg_type: type, qos=None):
        key = (topic, msg_type)
        pub = self._cache.get(key)
        if pub is None:
            pub = self._node.create_publisher(msg_type, topic, qos or 10)
            self._cache[key] = pub
        return pub
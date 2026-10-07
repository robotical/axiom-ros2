"""Optional observer: subscribes to ROS state and exposes read-only HTTP snapshots."""

import json
import time

from axiom_interfaces.srv import GetConnectionState
import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from .commands import recipes
from .catalogue import catalogue
from .scenarios import walkthroughs
from .web import Panel
from .workstation import WorkstationReset

try:
    from marty_interfaces.msg import DriverStatus
except ModuleNotFoundError as exc:
    if exc.name not in ("marty_interfaces", "marty_interfaces.msg"):
        raise
    DriverStatus = None


class Dashboard(Node):
    def __init__(self, **kwargs):
        super().__init__("dashboard", **kwargs)
        for key, value in dict(
            host="127.0.0.1",
            port=8083,
            workstation_reset_dir="",
        ).items():
            self.declare_parameter(key, value, ParameterDescriptor(read_only=True))
        self.boards = {}
        self.marty_status, self.marty_seen = {}, None
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.marty_subscription = (
            self.create_subscription(DriverStatus, "/marty/status", self._marty_status, retained)
            if DriverStatus is not None else None
        )
        self.graph = {"available": False, "nodes": [], "topics": [], "services": []}
        reset_dir = self.get_parameter("workstation_reset_dir").value
        self.panel = Panel(
            self.get_parameter("host").value,
            self.get_parameter("port").value,
            reset=WorkstationReset(reset_dir) if reset_dir else None,
        )
        self._add_board("/axiom")
        self.create_timer(0.5, self._check_connection)
        self.create_timer(1.0, self._graph)
        self.create_timer(0.25, self._publish)
        self._publish()

    def _add_board(self, root):
        if root in self.boards:
            return
        board = dict(root=root, status={}, seen=None, error="", future=None, sent=0.0, devices=[])
        board["client"] = self.create_client(GetConnectionState, root + "/get_connection_state")
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

        def inventory(msg):
            try:
                devices = json.loads(msg.data)
                if isinstance(devices, list):
                    board["devices"] = devices
            except (ValueError, TypeError):
                pass

        board["subscription"] = self.create_subscription(
            String, root + "/devices", inventory, retained
        )
        self.boards[root] = board

    def _check_connection(self):
        for board in self.boards.values():
            client, future = board["client"], board["future"]
            if future is not None:
                if time.monotonic() - board["sent"] < 1.5:
                    continue
                client.remove_pending_request(future)
                future.cancel()
                board["future"] = None
                board["error"] = "Connection status query timed out"
            if not client.service_is_ready():
                continue
            board["sent"] = time.monotonic()
            board["future"] = client.call_async(GetConnectionState.Request())
            board["future"].add_done_callback(
                lambda result, b=board: self._connection_result(b, result)
            )

    def _connection_result(self, board, future):
        if future is not board["future"]:
            return
        board["future"] = None
        try:
            response = future.result()
            board["status"] = dict(
                connected=response.connected,
                state="connected" if response.connected else "disconnected",
                error=response.last_error,
                device_uri=response.device_uri,
            )
            board["seen"], board["error"] = time.monotonic(), ""
        except Exception as exc:
            board["error"] = str(exc)

    def _board_status(self, board):
        if not board["client"].service_is_ready():
            return dict(available=False, connected=False, state="driver offline", error="")
        if board["seen"] is None or time.monotonic() - board["seen"] >= 2:
            return dict(
                available=False, connected=False, state="status unavailable", error=board["error"]
            )
        return dict(available=True, **board["status"])

    def _marty_status(self, msg):
        self.marty_status = dict(
            connected=msg.connected,
            state="connected" if msg.connected else "disconnected",
            error=msg.last_error,
        )
        self.marty_seen = time.monotonic()

    def _connections(self):
        if not self.count_publishers("/marty/status"):
            marty = dict(available=False, connected=False, state="driver offline", error="")
        elif self.marty_seen is None or time.monotonic() - self.marty_seen >= 2:
            marty = dict(available=False, connected=False, state="status unavailable", error="")
        else:
            marty = dict(available=True, **self.marty_status)
        return dict(axiom=self._board_status(next(iter(self.boards.values()))), marty=marty)

    def _graph(self):
        # DDS discovery supplies actual publishers/subscribers, including late nodes.
        for name, types in self.get_service_names_and_types():
            if (
                name.endswith("/get_connection_state")
                and "axiom_interfaces/srv/GetConnectionState" in types
            ):
                self._add_board(name.removesuffix("/get_connection_state"))
        topics = []
        nodes = sorted(
            set(ns.rstrip("/") + "/" + name for name, ns in self.get_node_names_and_namespaces())
        )
        for name, types in self.get_topic_names_and_types():

            def endpoints(rows):
                return [
                    dict(
                        node=e.node_namespace.rstrip("/") + "/" + e.node_name,
                        type=e.topic_type,
                        reliability=e.qos_profile.reliability.name,
                        durability=e.qos_profile.durability.name,
                    )
                    for e in rows
                ]

            publishers = endpoints(self.get_publishers_info_by_topic(name))
            subscribers = endpoints(self.get_subscriptions_info_by_topic(name))
            topics.append(
                dict(
                    name=name,
                    types=types,
                    publishers=sorted({e["node"] for e in publishers}),
                    subscribers=sorted({e["node"] for e in subscribers}),
                    publisher_endpoints=publishers,
                    subscriber_endpoints=subscribers,
                    infrastructure=name in ("/rosout", "/parameter_events", "/tf", "/tf_static")
                    or "/_action/" in name
                    or any(p.startswith("_") for p in name.split("/")),
                )
            )
        self.graph = {
            "available": True,
            "nodes": nodes,
            "topics": sorted(topics, key=lambda t: t["name"]),
            "services": [
                {
                    "name": name,
                    "types": types,
                    "descriptor": next(
                        (
                            command["descriptor"]
                            for root, board in self.boards.items()
                            for device in board["devices"]
                            if device.get("online") and not device.get("stale")
                            for command in device.get("commands", [])
                            if root + "/" + command["service"] == name
                        ),
                        None,
                    ),
                }
                for name, types in self.get_service_names_and_types()
                if not name.endswith(
                    (
                        "/get_parameters",
                        "/set_parameters",
                        "/set_parameters_atomically",
                        "/list_parameters",
                        "/describe_parameters",
                        "/get_parameter_types",
                    )
                )
            ],
        }

    def _publish(self):
        visible = {
            root: board
            for root, board in self.boards.items()
            if root != "/axiom" or board["client"].service_is_ready() or len(self.boards) == 1
        }
        guides = {}
        for root, board in visible.items():
            devices = board["devices"] if self._board_status(board)["connected"] else []
            commands = recipes({"devices": devices, "graph": self.graph}, root)
            guides[root] = dict(
                commands=commands,
                catalogue=catalogue(root),
                scenarios=walkthroughs(commands, self.graph, root, devices),
            )
        default = next(iter(guides.values()))
        self.panel.publish(
            dict(
                connections=self._connections(),
                graph=self.graph,
                boards=[
                    dict(
                        namespace=root,
                        **self._board_status(board),
                        devices=board["devices"] if self._board_status(board)["connected"] else [],
                    )
                    for root, board in visible.items()
                ],
                guides=guides,
                **default,
            )
        )

    def close(self):
        self.panel.close()


def main(args=None):
    rclpy.init(args=args)
    node = Dashboard()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

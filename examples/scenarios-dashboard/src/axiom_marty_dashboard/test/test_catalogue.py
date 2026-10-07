"""The reference is usable without a running device or demo state."""

from axiom_marty_dashboard.catalogue import catalogue


def test_reference_connections_resolve_to_declared_interfaces():
    reference = catalogue()
    nodes = {n["name"]: n for n in reference["nodes"]}
    assert len(nodes) == len(reference["nodes"])
    assert {"/axiom/axiom_bridge_node", "/sensing/sensor_view", "/dashboard"} <= nodes.keys()
    for topic in reference["topics"]:
        for name in topic["publishers"]:
            assert topic["name"] in [t["name"] for t in nodes[name]["publications"]]
        for name in topic["subscribers"]:
            assert topic["name"] in [t["name"] for t in nodes[name]["subscriptions"]]
    assert "autosub:=false" in nodes["/axiom/axiom_bridge_node"]["command"]
    assert {t["name"] for t in nodes["/dashboard"]["subscriptions"]} == {
        "/axiom/devices",
        "/marty/status",
    }
    assert nodes["/dashboard"]["services"][0]["name"] == "/axiom/get_connection_state"
    assert {t["name"] for t in nodes["/sensing/accelerometer_view"]["subscriptions"]} == {
        "/axiom/imu/data_raw",
        "/marty/imu/data_raw",
    }
    assert all(
        n["help"]["description"] and n["help"]["arguments"] for n in nodes.values() if n["command"]
    )

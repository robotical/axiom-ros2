"""The guide teaches manual setup and hot swapping without controlling ROS."""

import os
import subprocess

import pytest

from axiom_marty_dashboard.commands import recipes
from axiom_marty_dashboard.scenarios import walkthroughs


def test_manual_scenarios_have_help_and_cleanup():
    rows = walkthroughs(recipes({}), {})
    assert {r["id"] for r in rows} == {
        "accelerometer",
        "distance",
        "thermal",
        "distance-hotplug",
        "descriptor-config",
        "dual-accelerometers",
        "multiple-axioms",
        "marty",
    }
    for row in rows:
        assert row["requires"] and row["cleanup"] and row["troubleshooting"]
        for step in row["steps"] + row["cleanup"]:
            assert step["expected"]
            if step["recipe"]:
                assert step["recipe"]["help"]["description"]
                assert step["recipe"]["help"]["arguments"]
                assert "sensor_demo" not in step["recipe"]["command"]
                assert "send_goal" not in step["recipe"]["command"]
            else:
                assert step["instruction"]
    hotplug = next(r for r in rows if r["id"] == "distance-hotplug")
    commands = [s["recipe"]["command"] for s in hotplug["steps"] if s["recipe"]]
    assert sum("/axiom/connect " in c for c in commands) == 1
    assert sum("/axiom/publish_data_subscription " in c for c in commands) == 1
    assert any("topic echo /axiom/range" in c for c in commands)
    assert any("Publisher count: 0" in s["expected"] for s in hotplug["steps"])
    assert "Reconnect" in hotplug["steps"][-1]["title"]


def test_board_guidance_uses_its_namespace_and_live_descriptor_service():
    root = "/axiom/rear"
    devices = [
        dict(
            online=True,
            type="LSM6DS",
            commands=[
                dict(
                    name="_conf.rate",
                    service="bus_2/device_76a/commands/set_sample_rate",
                    descriptor={
                        "n": "_conf.rate",
                        "t": "B",
                        "d": 104,
                        "map": {"52": {}, "104": {}},
                    },
                )
            ],
        )
    ]
    commands = recipes({"devices": devices}, axiom_namespace=root)
    rows = walkthroughs(commands, {}, root, devices)
    hotplug = next(r for r in rows if r["id"] == "distance-hotplug")
    assert all(
        "/axiom/" not in s["recipe"]["command"].replace(root, "")
        for s in hotplug["steps"]
        if s["recipe"]
    )
    config = next(r for r in rows if r["id"] == "descriptor-config")
    assert any(
        root + "/bus_2/device_76a/commands/set_sample_rate" in s["recipe"]["command"]
        for s in config["steps"]
        if s["recipe"]
    )


@pytest.mark.parametrize("count", [0, 1, 2])
def test_thermal_scenario_selects_only_an_unambiguous_live_camera(count):
    root = "/axiom/rear"

    def topic(path, publishers=None):
        return dict(name=path, types=["axiom_interfaces/msg/ThermalGrid"],
                    publishers=publishers or [], subscribers=[])

    live = [topic(f"{root}/bus_{bus}/device_169/thermal/grid", [root + "/axiom_bridge_node"])
            for bus in range(1, count + 1)]
    graph = dict(topics=[*live,
                        topic("/axiom/front/bus_1/device_169/thermal/grid", ["/other"]),
                        topic(root + "/bus_5/device_169/thermal/grid")])
    commands = recipes({"graph": graph}, root)
    scenario = next(r for r in walkthroughs(commands, graph, root) if r["id"] == "thermal")
    selected = live[0]["name"] if count == 1 else root + "/bus_BUS/device_ADDRESS/thermal/grid"
    for title in ("Thermal grid readings", "Read thermal frame", "Thermal heatmap adapter"):
        command = next(r["command"] for r in commands if r["title"] == title)
        assert selected in command
        assert "/axiom/front/" not in command
        subprocess.run(["bash", "-n"], input=command, text=True, check=True)
    assert scenario["topics"] == [t["name"] for t in live]
    assert scenario["steps"][5]["check"]["topic"] == selected
    assert scenario["steps"][6]["check"]["nodes"] == ["/sensing/thermal_grid_visualizer"]
    assert scenario["steps"][5]["terminal"] == scenario["steps"][7]["terminal"] == 4
    assert "-f \"${THERMAL_FRAME:?" in scenario["steps"][7]["recipe"]["command"]
    driver = scenario["steps"][0]["recipe"]["command"]
    assert "auto_connect:=false" in driver and "autosub:=false" in driver


@pytest.mark.parametrize("frame", [None, ""])
def test_thermal_rviz_rejects_missing_frame_before_launch(frame):
    command = next(r["command"] for r in recipes({}) if r["title"] == "Thermal camera RViz")
    env = dict(os.environ)
    env.pop("THERMAL_FRAME", None)
    if frame is not None:
        env["THERMAL_FRAME"] = frame
    result = subprocess.run(["bash", "-c", command], env=env, capture_output=True,
                            text=True, timeout=5)
    assert result.returncode != 0
    assert "Run Read thermal frame in this terminal first" in result.stderr


@pytest.mark.parametrize("mac", [False, True])
def test_usb_wifi_scenario_autoconnects_and_visualizes_both_boards(
    tmp_path, monkeypatch, mac
):
    yaml = pytest.importorskip("yaml")
    for key in ("AXIOM_ROS_TRANSPORT", "AXIOM_ROS_URI", "AXIOM_ROS_SERIAL_PORT", "AXIOM_WIFI_IP"):
        monkeypatch.delenv(key, raising=False)
    if mac:
        monkeypatch.setenv("AXIOM_ROS_TRANSPORT", "ws")
        monkeypatch.setenv("AXIOM_ROS_URI", "ws://host.docker.internal:8765/ws")
    else:
        monkeypatch.setenv("AXIOM_ROS_SERIAL_PORT", "/dev/serial/by-id/usb-Axiom-front")
        monkeypatch.setenv("AXIOM_WIFI_IP", "192.168.1.12")
    scenario = next(r for r in walkthroughs(recipes({}), {}) if r["id"] == "multiple-axioms")
    commands = [s["recipe"]["command"] for s in scenario["steps"] if s["recipe"]]
    # Exercise the actual copied shell block without replacing the process's HOME.
    subprocess.run(["bash", "-c", commands[0].replace("$HOME", str(tmp_path))], check=True)
    config = yaml.safe_load((tmp_path / "usb_wifi_axioms.yaml").read_text())["axioms"]
    front, rear = config["axiom/front"], config["axiom/rear"]
    assert front["transport"] == ("ws" if mac else "serial")
    if mac:
        assert front["device_uri"] == "ws://host.docker.internal:8765/ws"
    else:
        assert front["serial.port"] == "/dev/serial/by-id/usb-Axiom-front"
    assert rear["transport"] == "ws"
    assert rear["device_uri"] == f"ws://192.168.1.{11 if mac else 12}/ws"
    for board in config.values():
        assert board["auto_connect"] and board["autosub"]
        assert not board["auto_reconnect"]
        assert board["publish_rate_hz"] == 20.0
        assert board["topic_aliases"]["imu/data_raw"]["type"] == "LSM6DS"
    assert 'boards_file:="$HOME/usb_wifi_axioms.yaml"' in commands[1]
    for name in ("front", "rear"):
        assert not any(f"/axiom/{name}/connect " in c for c in commands)
        assert not any(f"/axiom/{name}/publish_data_subscription " in c for c in commands)
        assert any(f"topic echo /axiom/{name}/imu/data_raw " in c for c in commands)
    adapter = next(s for s in scenario["steps"] if s["title"] == "Two Axiom accelerometer adapter")
    assert adapter["terminal"] == 3
    assert "axiom_topic:=/axiom/front/imu/data_raw" in adapter["recipe"]["command"]
    assert "marty_topic:=/axiom/rear/imu/data_raw" in adapter["recipe"]["command"]
    assert 'axiom_label:="Axiom USB"' in adapter["recipe"]["command"]
    assert 'marty_label:="Axiom Wi-Fi"' in adapter["recipe"]["command"]
    assert scenario["steps"][-1]["title"] == "Two Axiom RViz"
    assert scenario["steps"][-1]["terminal"] == 4


def test_step_evidence_uses_the_actual_topic_namespace():
    rows = walkthroughs(recipes({}), {})
    two = next(r for r in rows if r["id"] == "multiple-axioms")
    usb = next(s for s in two["steps"] if s["title"] == "USB accelerometer readings")
    wifi = next(s for s in two["steps"] if s["title"] == "Wi-Fi accelerometer readings")
    assert usb["check"]["topic"] == "/axiom/front/imu/data_raw"
    assert wifi["check"]["topic"] == "/axiom/rear/imu/data_raw"
    assert wifi["flow"][0]["name"] == "/axiom/rear/axiom_bridge_node"
    assert two["mode"] == "Auto connect + acquire"
    for step in two["cleanup"]:
        if step["title"] in ("Stop acquisition on rear", "Disconnect rear"):
            assert step["check"]["namespace"] == "/axiom/rear"
            assert step["flow"][-1]["name"] == "/axiom/rear/axiom_bridge_node"
    hotplug = next(r for r in rows if r["id"] == "distance-hotplug")
    unplug = next(s for s in hotplug["steps"] if s["title"] == "Unplug the sensor")
    assert unplug["check"] == {"kind": "range", "namespace": "/axiom", "present": False}
    assert hotplug["mode"] == "Manual console"
    assert hotplug["prerequisites"]

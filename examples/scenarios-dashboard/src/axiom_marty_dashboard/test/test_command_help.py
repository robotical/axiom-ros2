"""Every guide recipe has teaching notes for its actual command and request fields."""

import json
import shlex

import pytest

from axiom_marty_dashboard.command_help import explain
from axiom_marty_dashboard.commands import recipes


@pytest.mark.parametrize("topic", ["/axiom/front", "/axiom/rear"])
@pytest.mark.parametrize(
    "state",
    [
        {},
        {
            "devices": [{"topic": "bus_3/device_29", "capabilities": ["range"]}],
            "selected": {"range": "bus_3/device_29", "thermal": "bus_2/device_69"},
        },
    ],
)
def test_all_recipes_explain_their_arguments_and_current_request_values(topic, state):
    for row in recipes(state, topic):
        help_text = row["help"]
        assert help_text["description"], row["title"]
        assert help_text["arguments"], row["title"]
        assert all(arg["name"] and arg["description"] for arg in help_text["arguments"])
        tokens = shlex.split(row["command"])
        if tokens[:3] in (["ros2", "service", "call"], ["ros2", "action", "send_goal"]):
            names = {arg["name"] for arg in help_text["arguments"]}
            for key, value in json.loads(tokens[5]).items():
                assert f"{key}: {json.dumps(value)}" in names


def test_firmware_delivery_and_ros_subscription_have_distinct_explanations():
    rows = {row["title"]: row for row in recipes({})}
    assert (
        "separate from a ROS topic subscription"
        in rows["Start Axiom acquisition"]["help"]["description"]
    )
    assert "ROS subscription" in rows["Distance readings"]["help"]["description"]
    request = "python3 /demo/platforms/macos/session_reset.py request"
    assert (
        "no ROS commands are replayed"
        in explain("Start from scratch", request)["arguments"][-1]["description"]
    )

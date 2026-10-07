"""Copied commands must be valid requests for the actual ROS interfaces."""

import json
import shlex

import pytest

pytest.importorskip("rclpy")
from axiom_marty_dashboard.commands import recipes  # noqa: E402
from axiom_marty_dashboard.scenarios import walkthroughs  # noqa: E402
from rosidl_runtime_py.utilities import get_action, get_service  # noqa: E402

try:
    from marty_driver.motion import Motion
except ModuleNotFoundError as exc:
    if exc.name not in ("marty_driver", "marty_driver.motion"):
        raise
    Motion = None


def test_all_console_recipes_construct_valid_requests_and_motion_goals():
    rows = recipes({}, "/sensing/state")
    rows += [
        step["recipe"]
        for scenario in walkthroughs(rows, {})
        for step in scenario["steps"] + scenario["cleanup"]
        if step["recipe"]
    ]
    motion_commands = set()
    for row in rows:
        args = shlex.split(row["command"])
        if args[:3] == ["ros2", "service", "call"]:
            get_service(args[4]).Request(**json.loads(args[5]))
        elif args[:3] == ["ros2", "action", "send_goal"] and Motion is not None:
            fields = json.loads(args[5])
            goal = get_action(args[4]).Goal(**fields)
            # Driver validators include requirements not present in IDL schemas.
            Motion(**fields).validate()
            motion_commands.add(goal.command)
    assert motion_commands == ({0, 1, 2, 3, 4} if Motion is not None else set())
    assert all("curl " not in row["command"] for row in rows)
    driver = next(row["command"] for row in rows if row["title"] == "Axiom driver")
    assert "autosub:=false" in driver and "auto_reconnect:=false" in driver


def test_scenario_topic_commands_parse_with_installed_ros_cli():
    import argparse

    from ros2topic.verb.echo import EchoVerb
    from ros2topic.verb.info import InfoVerb
    from ros2topic.verb.list import ListVerb

    verbs = {"echo": EchoVerb, "info": InfoVerb, "list": ListVerb}
    for scenario in walkthroughs(recipes({}, "/sensing/state"), {}):
        for step in scenario["steps"] + scenario["cleanup"]:
            if not step["recipe"]:
                continue
            tokens = shlex.split(step["recipe"]["command"])
            if tokens[:2] == ["ros2", "topic"]:
                parser = argparse.ArgumentParser()
                verbs[tokens[2]]().add_arguments(parser, "ros2 topic")
                args = parser.parse_args(tokens[3:])
                if tokens[2] == "echo" and "--field" in tokens:
                    assert args.field in ("linear_acceleration", "range")

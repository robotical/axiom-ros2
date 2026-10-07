from glob import glob
from setuptools import find_packages, setup

setup(
    name="axiom_marty_dashboard",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/axiom_marty_dashboard"]),
        ("share/axiom_marty_dashboard", ["package.xml"]),
        ("share/axiom_marty_dashboard/launch", glob("launch/*.launch.py")),
    ],
    package_data={
        "axiom_marty_dashboard": [
            "dashboard.html",
            "graph.js",
            "graph.css",
            "session.js",
            "command-info.js",
            "scenarios.js",
            "scenario-state.js",
            "scenarios.css",
            "interface-info.js",
        ]
    },
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Robotical",
    maintainer_email="hello@robotical.io",
    description="Optional read-only ROS teaching dashboard",
    license="Apache-2.0",
    entry_points={"console_scripts": ["dashboard = axiom_marty_dashboard.node:main"]},
)

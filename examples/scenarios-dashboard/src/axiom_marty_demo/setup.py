from glob import glob

from setuptools import find_packages, setup

setup(
    name="axiom_marty_demo",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/axiom_marty_demo"]),
        ("share/axiom_marty_demo", ["package.xml"]),
        ("share/axiom_marty_demo/launch", glob("launch/*.launch.py")),
        ("share/axiom_marty_demo/config", glob("config/*.rviz")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Robotical",
    maintainer_email="hello@robotical.io",
    description="Axiom sensor expansion for Marty through ROS 2",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "sensor_view = axiom_marty_demo.sensor_view:main",
            "accelerometer_view = axiom_marty_demo.accelerometer_view:main",
        ]
    },
)

"""Install the joint slider adapter and its launch/model assets."""

from glob import glob

from setuptools import find_packages, setup

setup(
    name='axiom_servo_demo',
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/axiom_servo_demo']),
        ('share/axiom_servo_demo', ['package.xml']),
        ('share/axiom_servo_demo/launch', glob('launch/*.launch.py')),
        ('share/axiom_servo_demo/urdf', glob('urdf/*.urdf')),
        ('share/axiom_servo_demo/config', glob('config/*.rviz')),
    ],
    install_requires=['setuptools'],
    extras_require={'test': ['pytest']},
    zip_safe=True,
    maintainer='Robotical',
    maintainer_email='info@robotical.io',
    description='Marty-style joint sliders driving Axiom descriptor command services',
    license='MIT',
    entry_points={'console_scripts': ['servo_adapter = axiom_servo_demo.node:main']},
)

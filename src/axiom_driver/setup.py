from glob import glob

from setuptools import find_packages, setup

package_name = 'axiom_driver'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools', 'pyserial>=3.5', 'websocket-client>=1.6'],
    zip_safe=True,
    maintainer='Nikos',
    maintainer_email='nikos@robotical.io',
    description='Axiom firmware session, device discovery and ROS 2 sensor bridge',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
        'serial': [
            'pyserial>=3.5',
        ],
    },
    entry_points={
        'console_scripts': [
            'axiom_bridge_node = axiom_driver.axiom_bridge_node:main',
        ],
    },
)

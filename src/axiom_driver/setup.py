from setuptools import find_packages, setup

package_name = 'axiom_driver'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/axiom_minimal_launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Nikos',
    maintainer_email='nikos@robotical.io',
    description='A minimal Axiom ROS2 bridge with connection services',
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

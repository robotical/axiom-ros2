from setuptools import find_packages, setup

package_name = 'axiom_debug_tools'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='NikTheGeek1',
    maintainer_email='ntheodoropoulos@outlook.com',
    description='Debug subscriber nodes for Axiom topics',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'axiom_topic_sniff = axiom_debug_tools.topic_sniff:main',
            'axiom_imu_monitor = axiom_debug_tools.imu_monitor:main',
            'axiom_range_monitor = axiom_debug_tools.range_monitor:main',
            'axiom_env_monitor = axiom_debug_tools.env_monitor:main',
        ],
    },
)

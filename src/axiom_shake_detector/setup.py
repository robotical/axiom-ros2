"""Install the movement lab node, page and launch file."""

from glob import glob

from setuptools import find_packages, setup

setup(
    name='axiom_shake_detector',
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={'axiom_shake_detector': ['dashboard.html', 'teaching.html']},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/axiom_shake_detector']),
        ('share/axiom_shake_detector', ['package.xml']),
        ('share/axiom_shake_detector/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    extras_require={'test': ['pytest']},
    zip_safe=True,
    maintainer='Robotical',
    maintainer_email='info@robotical.io',
    description='Axiom movement lab: IMU shake detection, plotting and replay',
    license='MIT',
    entry_points={
        'console_scripts': [
            'shake_detector = axiom_shake_detector.node:main',
            'robot_face = axiom_shake_detector.face:main',
            'teaching_dashboard = axiom_shake_detector.presentation:main',
        ]
    },
)

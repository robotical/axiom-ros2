from setuptools import find_packages, setup

package_name = 'axiom_thermal_viz'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Nikos Theodoropoulos',
    maintainer_email='nikos@robotical.io',
    description='Axiom Thermal Visualization Node',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'thermal_heatmap = axiom_thermal_viz.thermal_viz_node:main',
        ],
    },
)

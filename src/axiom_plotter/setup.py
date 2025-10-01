from setuptools import find_packages, setup

package_name = 'axiom_plotter'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/plot_dynamic.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='NikTheGeek1',
    maintainer_email='nikos@robotical.io',
    description='Plotting package for Axiom',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'dynamic_grapher = axiom_plotter.dynamic_grapher:main',
        ],
    },
)

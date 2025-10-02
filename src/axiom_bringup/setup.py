from setuptools import find_packages, setup

package_name = 'axiom_bringup'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/bringup.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Nikos',
    maintainer_email='nikos@robotical.io',
    description='Launch files and configs for Axiom.',
    license='MIT',
    entry_points={
        'console_scripts': [
        ],
    },
)

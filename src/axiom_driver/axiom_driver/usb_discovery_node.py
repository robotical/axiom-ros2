"""USB-only entry point retained alongside normal USB/Wi-Fi discovery."""

from .discovery_node import AxiomDiscoveryNode, run


class UsbDiscoveryNode(AxiomDiscoveryNode):

    default_wifi = False

    def __init__(self, **kwargs):
        super().__init__(node_name='axiom_usb_discovery', **kwargs)


def main(args=None):
    run(UsbDiscoveryNode, args)

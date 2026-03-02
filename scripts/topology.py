#!/usr/bin/env python3
"""
SDN QoS Project - Mininet Topology
RSX217 - CNAM Paris
Author: GAVI Holali David

Topology: Partial mesh with 7 switches and 3 hosts
- s1 (edge) -- s2 -- s4 (core/hub) -- s5 -- s7 (edge)
-              s3 --/            /-- s6
- h1 connected to s1 (GOLD traffic source)
- h2 connected to s7 (GOLD traffic destination)  
- h3 connected to s4 (SILVER/BRONZE traffic)
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import argparse


def create_topology(controller_ip='127.0.0.1', controller_port=6633):
    """
    Create the SDN topology with QoS support.
    
    Topology diagram:
    
        h1                                      h2
         |                                       |
        [s1]---[s2]---[s4]---[s5]---[s7]
                |      |      |
               [s3]----+-----[s6]
                       |
                      h3
    
    Links:
    - s1-s2, s2-s4, s4-s5, s5-s7 (main path)
    - s2-s3, s3-s4 (alternate path)
    - s4-s6, s5-s6 (redundancy)
    """
    
    info('*** Creating network\n')
    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True
    )
    
    # Add remote controller (Ryu)
    info('*** Adding Ryu controller\n')
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip=controller_ip,
        port=controller_port,
        protocols='OpenFlow13'
    )
    
    # Add switches (OpenFlow 1.3)
    info('*** Adding switches\n')
    switches = {}
    for i in range(1, 8):
        switches[f's{i}'] = net.addSwitch(
            f's{i}',
            cls=OVSKernelSwitch,
            protocols='OpenFlow13'
        )
    
    s1, s2, s3, s4, s5, s6, s7 = [switches[f's{i}'] for i in range(1, 8)]
    
    # Add hosts with specific IPs
    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')  # GOLD source
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')  # GOLD destination
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')  # SILVER/BRONZE
    
    # Add links between switches (1 Gbps bandwidth)
    info('*** Creating switch links\n')
    # Main path: s1 - s2 - s4 - s5 - s7
    net.addLink(s1, s2, bw=1000)  # s1:eth2 - s2:eth1
    net.addLink(s2, s4, bw=1000)  # s2:eth2 - s4:eth1
    net.addLink(s4, s5, bw=1000)  # s4:eth2 - s5:eth1
    net.addLink(s5, s7, bw=1000)  # s5:eth2 - s7:eth1
    
    # Alternate path: s2 - s3 - s4
    net.addLink(s2, s3, bw=1000)  # s2:eth3 - s3:eth1
    net.addLink(s3, s4, bw=1000)  # s3:eth2 - s4:eth3
    
    # Redundancy: s4 - s6, s5 - s6
    net.addLink(s4, s6, bw=1000)  # s4:eth4 - s6:eth1
    net.addLink(s5, s6, bw=1000)  # s5:eth3 - s6:eth2
    
    # Add links between hosts and switches
    info('*** Creating host links\n')
    net.addLink(h1, s1, bw=1000)  # h1:eth0 - s1:eth1
    net.addLink(h2, s7, bw=1000)  # h2:eth0 - s7:eth2
    net.addLink(h3, s4, bw=1000)  # h3:eth0 - s4:eth5
    
    return net


def configure_qos(net):
    """
    Configure QoS queues on all switches using ovs-vsctl.
    
    Queue configuration:
    - Queue 0 (GOLD):   min_rate=500Mbps, max_rate=1Gbps, priority=0
    - Queue 1 (SILVER): min_rate=200Mbps, max_rate=500Mbps, priority=1
    - Queue 2 (BRONZE): min_rate=0, max_rate=200Mbps, priority=2
    """
    info('*** Configuring QoS queues on switches\n')
    
    for sw in net.switches:
        sw_name = sw.name
        info(f'  Configuring {sw_name}...\n')
        
        # Get all interfaces of the switch
        interfaces = sw.intfList()
        
        for intf in interfaces:
            intf_name = intf.name
            if intf_name == 'lo':
                continue
                
            # Create QoS configuration with HTB queues
            # First, clear any existing QoS config
            sw.cmd(f'ovs-vsctl -- --if-exists destroy qos {intf_name}')
            sw.cmd(f'ovs-vsctl -- --if-exists clear port {intf_name} qos')
            
            # Create QoS with 3 queues
            qos_cmd = f'''ovs-vsctl -- set port {intf_name} qos=@newqos -- \
                --id=@newqos create qos type=linux-htb \
                other-config:max-rate=1000000000 \
                queues:0=@q0 queues:1=@q1 queues:2=@q2 -- \
                --id=@q0 create queue other-config:min-rate=500000000 other-config:max-rate=1000000000 other-config:priority=0 -- \
                --id=@q1 create queue other-config:min-rate=200000000 other-config:max-rate=500000000 other-config:priority=1 -- \
                --id=@q2 create queue other-config:min-rate=0 other-config:max-rate=200000000 other-config:priority=2'''
            
            sw.cmd(qos_cmd)
    
    info('*** QoS configuration complete\n')


def print_topology_info(net):
    """Print topology information."""
    info('\n*** Topology Information ***\n')
    info('Hosts:\n')
    for host in net.hosts:
        info(f'  {host.name}: IP={host.IP()}, MAC={host.MAC()}\n')
    
    info('\nSwitches:\n')
    for sw in net.switches:
        info(f'  {sw.name}: dpid={sw.dpid}\n')
        for intf in sw.intfList():
            if intf.name != 'lo':
                info(f'    - {intf.name}\n')
    
    info('\nQoS Classes:\n')
    info('  GOLD   (Queue 0): h1 -> h2, Priority 0, 500Mbps-1Gbps\n')
    info('  SILVER (Queue 1): h1 -> h3, Priority 1, 200Mbps-500Mbps\n')
    info('  BRONZE (Queue 2): Default,  Priority 2, Best Effort\n')


def run_tests(net):
    """Run basic connectivity tests."""
    info('\n*** Running connectivity tests ***\n')
    
    h1, h2, h3 = net.get('h1', 'h2', 'h3')
    
    # Ping tests
    info('Testing h1 -> h2 (GOLD path):\n')
    result = h1.cmd('ping -c 3 10.0.0.2')
    info(result)
    
    info('\nTesting h1 -> h3 (SILVER path):\n')
    result = h1.cmd('ping -c 3 10.0.0.3')
    info(result)
    
    info('\nTesting h2 -> h3 (BRONZE path):\n')
    result = h2.cmd('ping -c 3 10.0.0.3')
    info(result)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='SDN QoS Mininet Topology')
    parser.add_argument('--controller-ip', default='127.0.0.1',
                        help='Ryu controller IP (default: 127.0.0.1)')
    parser.add_argument('--controller-port', type=int, default=6633,
                        help='Ryu controller port (default: 6633)')
    parser.add_argument('--no-qos', action='store_true',
                        help='Skip QoS configuration')
    parser.add_argument('--test', action='store_true',
                        help='Run connectivity tests')
    parser.add_argument('--no-cli', action='store_true',
                        help='Exit without CLI')
    args = parser.parse_args()
    
    setLogLevel('info')
    
    # Create network
    net = create_topology(args.controller_ip, args.controller_port)
    
    try:
        # Start network
        info('*** Starting network\n')
        net.start()
        
        # Wait for switches to connect to controller
        info('*** Waiting for switches to connect to controller...\n')
        import time
        time.sleep(3)
        
        # Configure QoS
        if not args.no_qos:
            configure_qos(net)
        
        # Print topology info
        print_topology_info(net)
        
        # Run tests if requested
        if args.test:
            run_tests(net)
        
        # Start CLI or exit
        if not args.no_cli:
            info('\n*** Starting CLI ***\n')
            info('Useful commands:\n')
            info('  h1 ping h2              - Test connectivity\n')
            info('  h1 iperf -s &           - Start iperf server on h1\n')
            info('  h2 iperf -c 10.0.0.1    - Run iperf client from h2\n')
            info('  dpctl dump-flows s1     - Show flow rules on s1\n')
            info('  exit                    - Stop network\n\n')
            CLI(net)
        
    finally:
        # Stop network
        info('*** Stopping network\n')
        net.stop()


if __name__ == '__main__':
    main()

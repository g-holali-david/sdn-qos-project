#!/usr/bin/env python3
"""
SDN QoS Project - Controller Application
RSX217 - CNAM Paris
Author: GAVI Holali David

This application implements QoS-aware switching with 3 service classes:
- GOLD:   High priority, guaranteed bandwidth (h1 <-> h2)
- SILVER: Medium priority, moderate bandwidth (h1 <-> h3)
- BRONZE: Best effort, no guarantees (default)

Compatible with both os-ken (Python 3.12+) and ryu (older Python).
"""

# Try os-ken first (Python 3.12 compatible), fall back to ryu
try:
    from os_ken.base import app_manager
    from os_ken.controller import ofp_event
    from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
    from os_ken.controller.handler import set_ev_cls
    from os_ken.ofproto import ofproto_v1_3
    from os_ken.lib.packet import packet, ethernet, ipv4, ether_types
    from os_ken.lib import hub
    print("[QoS Switch] Using os-ken (Python 3.12 compatible)")
except ImportError:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
    from ryu.controller.handler import set_ev_cls
    from ryu.ofproto import ofproto_v1_3
    from ryu.lib.packet import packet, ethernet, ipv4, ether_types
    from ryu.lib import hub
    print("[QoS Switch] Using ryu (original)")

import logging


class QoSSwitch(app_manager.RyuApp):
    """
    QoS-aware OpenFlow 1.3 Switch Application.
    
    Implements traffic classification based on source/destination IP
    and assigns packets to appropriate QoS queues.
    """
    
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    # QoS Class definitions
    QOS_CLASSES = {
        'GOLD': {
            'queue_id': 0,
            'priority': 100,
            'src_ip': '10.0.0.1',
            'dst_ip': '10.0.0.2',
            'description': 'High priority - Video/VoIP'
        },
        'SILVER': {
            'queue_id': 1,
            'priority': 50,
            'src_ip': '10.0.0.1',
            'dst_ip': '10.0.0.3',
            'description': 'Medium priority - Web/Business'
        },
        'BRONZE': {
            'queue_id': 2,
            'priority': 1,
            'src_ip': None,  # Default
            'dst_ip': None,
            'description': 'Best effort - Background'
        }
    }
    
    # Host to switch port mapping (learned dynamically)
    # Format: {dpid: {mac: port}}
    mac_to_port = {}
    
    # IP to MAC mapping
    IP_TO_MAC = {
        '10.0.0.1': '00:00:00:00:00:01',  # h1
        '10.0.0.2': '00:00:00:00:00:02',  # h2
        '10.0.0.3': '00:00:00:00:00:03',  # h3
    }
    
    def __init__(self, *args, **kwargs):
        super(QoSSwitch, self).__init__(*args, **kwargs)
        self.logger.setLevel(logging.INFO)
        self.logger.info("QoS Switch Application Started")
        self.logger.info("=" * 50)
        self.logger.info("QoS Classes configured:")
        for name, config in self.QOS_CLASSES.items():
            self.logger.info(f"  {name}: Queue {config['queue_id']}, "
                           f"Priority {config['priority']}")
        self.logger.info("=" * 50)
    
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Handle switch connection and install table-miss flow entry.
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        
        self.logger.info(f"Switch connected: dpid={dpid:016x}")
        
        # Initialize MAC table for this switch
        self.mac_to_port.setdefault(dpid, {})
        
        # Install table-miss flow entry (send to controller)
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        
        # Install QoS classification rules
        self._install_qos_rules(datapath)
    
    def _install_qos_rules(self, datapath):
        """
        Install QoS classification flow rules.
        
        These rules match on IP src/dst and set the appropriate queue.
        """
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        dpid = datapath.id
        
        self.logger.info(f"Installing QoS rules on switch {dpid:016x}")
        
        # GOLD class: h1 (10.0.0.1) -> h2 (10.0.0.2)
        gold = self.QOS_CLASSES['GOLD']
        match_gold = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=gold['src_ip'],
            ipv4_dst=gold['dst_ip']
        )
        # Action: set queue 0 (GOLD) and forward normally
        # Note: actual output port will be added in packet_in handler
        self.logger.info(f"  GOLD rule: {gold['src_ip']} -> {gold['dst_ip']} => Queue {gold['queue_id']}")
        
        # GOLD reverse: h2 -> h1 (bidirectional)
        match_gold_rev = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=gold['dst_ip'],
            ipv4_dst=gold['src_ip']
        )
        
        # SILVER class: h1 (10.0.0.1) -> h3 (10.0.0.3)
        silver = self.QOS_CLASSES['SILVER']
        match_silver = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=silver['src_ip'],
            ipv4_dst=silver['dst_ip']
        )
        self.logger.info(f"  SILVER rule: {silver['src_ip']} -> {silver['dst_ip']} => Queue {silver['queue_id']}")
        
        # SILVER reverse: h3 -> h1
        match_silver_rev = parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP,
            ipv4_src=silver['dst_ip'],
            ipv4_dst=silver['src_ip']
        )
    
    def add_flow(self, datapath, priority, match, actions, buffer_id=None, 
                 idle_timeout=0, hard_timeout=0):
        """
        Add a flow entry to the switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    idle_timeout=idle_timeout,
                                    hard_timeout=hard_timeout,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match,
                                    idle_timeout=idle_timeout,
                                    hard_timeout=hard_timeout,
                                    instructions=inst)
        
        datapath.send_msg(mod)
    
    def _get_qos_class(self, src_ip, dst_ip):
        """
        Determine QoS class based on source and destination IP.
        
        Returns: (class_name, queue_id, priority)
        """
        # Check GOLD
        gold = self.QOS_CLASSES['GOLD']
        if ((src_ip == gold['src_ip'] and dst_ip == gold['dst_ip']) or
            (src_ip == gold['dst_ip'] and dst_ip == gold['src_ip'])):
            return 'GOLD', gold['queue_id'], gold['priority']
        
        # Check SILVER
        silver = self.QOS_CLASSES['SILVER']
        if ((src_ip == silver['src_ip'] and dst_ip == silver['dst_ip']) or
            (src_ip == silver['dst_ip'] and dst_ip == silver['src_ip'])):
            return 'SILVER', silver['queue_id'], silver['priority']
        
        # Default to BRONZE
        bronze = self.QOS_CLASSES['BRONZE']
        return 'BRONZE', bronze['queue_id'], bronze['priority']
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handle packets sent to the controller.
        
        This handler:
        1. Learns MAC addresses
        2. Determines output port
        3. Classifies traffic into QoS classes
        4. Installs flow rules with appropriate queue
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        dpid = datapath.id
        
        # Parse packet
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        
        # Ignore LLDP packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        
        dst_mac = eth.dst
        src_mac = eth.src
        
        # Learn MAC address
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port
        
        # Determine output port
        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
        else:
            out_port = ofproto.OFPP_FLOOD
        
        # Default actions (no QoS)
        actions = [parser.OFPActionOutput(out_port)]
        
        # Check if this is an IP packet for QoS classification
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        qos_class = 'BRONZE'
        queue_id = 2
        flow_priority = 1
        
        if ip_pkt:
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst
            qos_class, queue_id, flow_priority = self._get_qos_class(src_ip, dst_ip)
            
            # Add queue action for QoS
            if out_port != ofproto.OFPP_FLOOD:
                actions = [
                    parser.OFPActionSetQueue(queue_id),
                    parser.OFPActionOutput(out_port)
                ]
                
                self.logger.debug(f"Packet: {src_ip} -> {dst_ip}, "
                                f"Class: {qos_class}, Queue: {queue_id}")
        
        # Install flow rule if we know the output port
        if out_port != ofproto.OFPP_FLOOD:
            if ip_pkt:
                # IP flow with QoS
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=dst_mac,
                    eth_src=src_mac,
                    eth_type=ether_types.ETH_TYPE_IP,
                    ipv4_src=ip_pkt.src,
                    ipv4_dst=ip_pkt.dst
                )
                
                # Log QoS assignment
                if qos_class != 'BRONZE':
                    self.logger.info(f"[{qos_class}] Flow installed: "
                                   f"{ip_pkt.src} -> {ip_pkt.dst} "
                                   f"(switch={dpid}, queue={queue_id})")
            else:
                # Non-IP flow (L2 only)
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=dst_mac,
                    eth_src=src_mac
                )
            
            # Add flow with idle timeout (flows expire after 60s of inactivity)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, flow_priority, match, actions,
                             buffer_id=msg.buffer_id, idle_timeout=60)
                return
            else:
                self.add_flow(datapath, flow_priority, match, actions,
                             idle_timeout=60)
        
        # Send packet out
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)


class QoSStatsCollector(app_manager.RyuApp):
    """
    Companion application to collect QoS statistics.
    
    Periodically queries switches for flow and queue statistics.
    """
    
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(QoSStatsCollector, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.stats_interval = 10  # seconds
        self.monitor_thread = hub.spawn(self._monitor)
    
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def state_change_handler(self, ev):
        """Track switch connections/disconnections."""
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info(f"Stats collector registered switch: {datapath.id:016x}")
                self.datapaths[datapath.id] = datapath
        elif ev.state == 'DEAD_DISPATCHER':
            if datapath.id in self.datapaths:
                self.logger.info(f"Stats collector unregistered switch: {datapath.id:016x}")
                del self.datapaths[datapath.id]
    
    def _monitor(self):
        """Periodically request statistics from switches."""
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(self.stats_interval)
    
    def _request_stats(self, datapath):
        """Request flow and port statistics."""
        parser = datapath.ofproto_parser
        
        # Request flow stats
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        
        # Request port stats
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)
    
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """Handle flow statistics reply."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        
        self.logger.debug(f"Flow stats for switch {dpid:016x}:")
        for stat in body:
            if stat.priority > 0:  # Skip table-miss entry
                self.logger.debug(f"  Match: {stat.match}, "
                                f"Packets: {stat.packet_count}, "
                                f"Bytes: {stat.byte_count}")
    
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Handle port statistics reply."""
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        
        self.logger.debug(f"Port stats for switch {dpid:016x}:")
        for stat in body:
            self.logger.debug(f"  Port {stat.port_no}: "
                            f"RX={stat.rx_packets} pkts, "
                            f"TX={stat.tx_packets} pkts")

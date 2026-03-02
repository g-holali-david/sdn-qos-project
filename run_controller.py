#!/usr/bin/env python3
"""
Simple SDN Controller Launcher
Works with os-ken and ryu
"""
import sys
import os
import signal
import socket
import time

def main():
    # Get port from argument or default
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 6633
    
    print(f"[Launcher] Starting SDN Controller on port {port}")
    
    # Try os-ken first
    try:
        from os_ken.base import app_manager
        from os_ken.controller.controller import OpenFlowController
        from os_ken.lib import hub
        from os_ken import cfg
        using = "os-ken"
    except ImportError:
        from ryu.base import app_manager
        from ryu.controller.controller import OpenFlowController
        from ryu.lib import hub
        from ryu import cfg
        using = "ryu"
    
    print(f"[Launcher] Using {using}")
    
    # Import our QoS app
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    
    from ryu_apps.qos_switch import QoSSwitch
    
    # Configure
    CONF = cfg.CONF
    CONF.ofp_tcp_listen_port = port
    
    print(f"[Launcher] Loading QoSSwitch application...")
    
    # Create app manager and load app
    app_mgr = app_manager.AppManager.get_instance()
    app_mgr.load_app('os_ken.controller.ofp_handler' if using == 'os-ken' else 'ryu.controller.ofp_handler')
    
    contexts = app_mgr.create_contexts()
    services = app_mgr.instantiate_apps(**contexts)
    
    # Instantiate our app
    qos_app = QoSSwitch(**contexts)
    
    print(f"[Launcher] Controller running on port {port}")
    print(f"[Launcher] Waiting for switch connections...")
    
    # Handle shutdown
    def signal_handler(sig, frame):
        print("\n[Launcher] Shutting down...")
        hub.kill()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run
    try:
        hub.joinall(services)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()

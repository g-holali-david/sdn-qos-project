#!/bin/bash
#
# SDN QoS Project - Main Runner Script
# RSX217 - CNAM Paris
# Author: GAVI Holali David
#
# This script orchestrates the entire QoS demonstration:
# 1. Starts the Ryu controller
# 2. Creates the Mininet topology
# 3. Configures QoS
# 4. Runs traffic tests
# 5. Collects metrics
#
# Usage:
#   ./run.sh                    # Full demo
#   ./run.sh --controller-only  # Start only the controller
#   ./run.sh --topology-only    # Start only Mininet
#   ./run.sh --test             # Run tests on existing network
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RYU_APP="$PROJECT_DIR/ryu_apps/qos_switch.py"
TOPOLOGY_SCRIPT="$PROJECT_DIR/scripts/topology.py"
TRAFFIC_SCRIPT="$PROJECT_DIR/scripts/traffic_generator.py"
METRICS_SCRIPT="$PROJECT_DIR/scripts/metrics_collector.py"
RESULTS_DIR="$PROJECT_DIR/results"

# Controller settings
CONTROLLER_IP="127.0.0.1"
CONTROLLER_PORT=6633

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
    print_header "Checking Dependencies"
    
    local missing=0
    
    # Check for required commands
    for cmd in ryu-manager mn ovs-vsctl iperf3 python3; do
        if command -v $cmd &> /dev/null; then
            print_info "$cmd: OK"
        else
            print_error "$cmd: NOT FOUND"
            missing=1
        fi
    done
    
    # Check Python packages
    python3 -c "from ryu.base import app_manager" 2>/dev/null && \
        print_info "ryu package: OK" || \
        { print_error "ryu package: NOT FOUND"; missing=1; }
    
    python3 -c "from mininet.net import Mininet" 2>/dev/null && \
        print_info "mininet package: OK" || \
        { print_error "mininet package: NOT FOUND"; missing=1; }
    
    if [ $missing -eq 1 ]; then
        print_error "Missing dependencies. Please install them first."
        exit 1
    fi
    
    print_info "All dependencies satisfied!"
}

start_controller() {
    print_header "Starting Ryu Controller"
    
    # Kill any existing Ryu process
    pkill -f "ryu-manager" 2>/dev/null || true
    sleep 1
    
    print_info "Starting Ryu controller with QoS application..."
    print_info "Controller: $CONTROLLER_IP:$CONTROLLER_PORT"
    
    # Start Ryu in background
    ryu-manager --ofp-tcp-listen-port $CONTROLLER_PORT \
                --verbose \
                "$RYU_APP" &
    
    RYU_PID=$!
    echo $RYU_PID > /tmp/ryu_qos.pid
    
    print_info "Ryu controller started (PID: $RYU_PID)"
    print_info "Waiting for controller to initialize..."
    sleep 3
}

start_topology() {
    print_header "Starting Mininet Topology"
    
    # Clean up any existing Mininet
    print_info "Cleaning up previous Mininet instances..."
    mn -c 2>/dev/null || true
    sleep 1
    
    print_info "Starting Mininet topology..."
    print_info "Topology: 7 switches, 3 hosts (partial mesh)"
    
    # Start topology
    python3 "$TOPOLOGY_SCRIPT" \
        --controller-ip $CONTROLLER_IP \
        --controller-port $CONTROLLER_PORT
}

run_basic_test() {
    print_header "Running Basic Connectivity Test"
    
    print_info "Testing ping between hosts..."
    
    # These commands would run inside Mininet CLI
    cat << 'EOF'
    
Run these commands in the Mininet CLI:

1. Test GOLD path (h1 -> h2):
   mininet> h1 ping -c 5 h2

2. Test SILVER path (h1 -> h3):
   mininet> h1 ping -c 5 h3

3. Test BRONZE path (h2 -> h3):
   mininet> h2 ping -c 5 h3

4. Start iperf server on h2:
   mininet> h2 iperf3 -s &

5. Run throughput test from h1:
   mininet> h1 iperf3 -c 10.0.0.2 -t 10

EOF
}

run_qos_demo() {
    print_header "Running QoS Demonstration"
    
    cat << 'EOF'
    
=== QoS Demonstration Steps ===

In Terminal 1 (Controller):
  ryu-manager --ofp-tcp-listen-port 6633 ryu_apps/qos_switch.py

In Terminal 2 (Mininet):
  sudo python3 scripts/topology.py

In Mininet CLI:

1. Start iperf servers on all hosts:
   mininet> h2 iperf3 -s -p 5201 &
   mininet> h3 iperf3 -s -p 5202 &

2. Generate GOLD traffic (h1 -> h2):
   mininet> h1 iperf3 -c 10.0.0.2 -p 5201 -t 30 -b 500M &

3. Generate SILVER traffic (h1 -> h3):
   mininet> h1 iperf3 -c 10.0.0.3 -p 5202 -t 30 -b 200M &

4. Generate BRONZE traffic (h2 -> h3):
   mininet> h2 iperf3 -c 10.0.0.3 -p 5202 -t 30 -b 100M &

5. Monitor QoS queues:
   mininet> sh ovs-vsctl list queue

6. Check flow rules:
   mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s4

EOF
}

stop_all() {
    print_header "Stopping All Services"
    
    # Stop Ryu
    if [ -f /tmp/ryu_qos.pid ]; then
        PID=$(cat /tmp/ryu_qos.pid)
        if kill -0 $PID 2>/dev/null; then
            print_info "Stopping Ryu controller (PID: $PID)..."
            kill $PID
        fi
        rm -f /tmp/ryu_qos.pid
    fi
    
    # Kill any remaining Ryu processes
    pkill -f "ryu-manager" 2>/dev/null || true
    
    # Clean up Mininet
    print_info "Cleaning up Mininet..."
    mn -c 2>/dev/null || true
    
    # Clean up OVS
    print_info "Cleaning up OVS QoS configurations..."
    for br in $(ovs-vsctl list-br 2>/dev/null); do
        ovs-vsctl --if-exists del-br $br 2>/dev/null || true
    done
    
    print_info "Cleanup complete!"
}

show_usage() {
    cat << EOF
SDN QoS Project - Runner Script

Usage: $0 [OPTIONS]

Options:
    --help              Show this help message
    --check             Check dependencies only
    --controller-only   Start only the Ryu controller
    --topology-only     Start only the Mininet topology (requires running controller)
    --demo              Show QoS demonstration steps
    --test              Run basic connectivity tests
    --stop              Stop all services and cleanup
    --full              Run complete demo (controller + topology)

Examples:
    $0 --check              # Verify all dependencies
    $0 --controller-only    # Start Ryu in background
    $0 --topology-only      # Start Mininet (in a new terminal)
    $0 --full               # Run complete demo
    $0 --stop               # Clean up everything

Project Structure:
    ryu_apps/qos_switch.py      - Ryu QoS controller application
    scripts/topology.py          - Mininet topology script
    scripts/traffic_generator.py - Traffic generation tool
    scripts/metrics_collector.py - Metrics collection and visualization
    results/                     - Test results and graphs

EOF
}

# Main
main() {
    case "${1:-}" in
        --help|-h)
            show_usage
            ;;
        --check)
            check_dependencies
            ;;
        --controller-only)
            check_dependencies
            start_controller
            print_info "Controller running. Start topology in another terminal:"
            print_info "  sudo python3 $TOPOLOGY_SCRIPT"
            # Wait for controller
            wait
            ;;
        --topology-only)
            start_topology
            ;;
        --demo)
            run_qos_demo
            ;;
        --test)
            run_basic_test
            ;;
        --stop)
            stop_all
            ;;
        --full)
            check_dependencies
            trap stop_all EXIT
            start_controller
            start_topology
            ;;
        *)
            show_usage
            ;;
    esac
}

main "$@"

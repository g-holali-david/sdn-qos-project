#!/usr/bin/env python3
"""
SDN QoS Project - Metrics Collector and Visualizer
RSX217 - CNAM Paris
Author: GAVI Holali David

Collects and visualizes QoS metrics:
- Throughput (Mbps)
- Latency (ms)
- Jain's Fairness Index

Usage:
    python3 metrics_collector.py --collect --output results/
    python3 metrics_collector.py --visualize --input results/
    python3 metrics_collector.py --realtime --duration 60
"""

import subprocess
import argparse
import json
import time
import os
import re
from datetime import datetime
from collections import defaultdict
import threading

# Try to import matplotlib (may not be available in Mininet)
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("[WARNING] matplotlib not available, visualization disabled")


class MetricsCollector:
    """Collects QoS metrics from the network."""
    
    def __init__(self, output_dir='results'):
        self.output_dir = output_dir
        self.metrics = {
            'throughput': defaultdict(list),
            'latency': defaultdict(list),
            'timestamps': []
        }
        os.makedirs(output_dir, exist_ok=True)
    
    def collect_throughput(self, source_host, target_ip, duration=10, 
                          bandwidth='100M', qos_class='BRONZE'):
        """
        Measure throughput using iperf3.
        
        Returns throughput in Mbps.
        """
        cmd = [
            'iperf3',
            '-c', target_ip,
            '-t', str(duration),
            '-b', bandwidth,
            '-J'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=duration + 10)
            data = json.loads(result.stdout)
            
            # Extract throughput from iperf3 JSON output
            if 'end' in data and 'sum_sent' in data['end']:
                bits_per_second = data['end']['sum_sent']['bits_per_second']
                mbps = bits_per_second / 1e6
                
                self.metrics['throughput'][qos_class].append({
                    'timestamp': datetime.now().isoformat(),
                    'value': mbps,
                    'source': source_host,
                    'target': target_ip
                })
                
                return mbps
        except Exception as e:
            print(f"[ERROR] Throughput measurement failed: {e}")
        
        return None
    
    def collect_latency(self, target_ip, count=10, qos_class='BRONZE'):
        """
        Measure latency using ping.
        
        Returns RTT statistics (min, avg, max, mdev) in ms.
        """
        cmd = ['ping', '-c', str(count), '-q', target_ip]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=count + 5)
            
            # Parse ping output
            # Example: rtt min/avg/max/mdev = 0.123/0.456/0.789/0.111 ms
            match = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)', 
                            result.stdout)
            
            if match:
                rtt = {
                    'min': float(match.group(1)),
                    'avg': float(match.group(2)),
                    'max': float(match.group(3)),
                    'mdev': float(match.group(4))
                }
                
                self.metrics['latency'][qos_class].append({
                    'timestamp': datetime.now().isoformat(),
                    'value': rtt,
                    'target': target_ip
                })
                
                return rtt
        except Exception as e:
            print(f"[ERROR] Latency measurement failed: {e}")
        
        return None
    
    def calculate_fairness(self, throughputs):
        """
        Calculate Jain's Fairness Index.
        
        Formula: J(x) = (sum(xi))^2 / (n * sum(xi^2))
        
        Returns value between 0 and 1 (1 = perfectly fair).
        """
        if not throughputs or len(throughputs) == 0:
            return None
        
        n = len(throughputs)
        sum_x = sum(throughputs)
        sum_x2 = sum(x**2 for x in throughputs)
        
        if sum_x2 == 0:
            return 1.0  # All zero = perfectly fair
        
        fairness = (sum_x ** 2) / (n * sum_x2)
        return fairness
    
    def collect_flow_stats(self, switch='s1'):
        """
        Collect flow statistics from OVS switch.
        
        Returns flow table entries with packet/byte counts.
        """
        cmd = ['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', switch]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            flows = []
            
            for line in result.stdout.split('\n'):
                if 'n_packets=' in line:
                    # Parse flow entry
                    match_packets = re.search(r'n_packets=(\d+)', line)
                    match_bytes = re.search(r'n_bytes=(\d+)', line)
                    
                    if match_packets and match_bytes:
                        flows.append({
                            'packets': int(match_packets.group(1)),
                            'bytes': int(match_bytes.group(1)),
                            'raw': line.strip()
                        })
            
            return flows
        except Exception as e:
            print(f"[ERROR] Flow stats collection failed: {e}")
        
        return []
    
    def collect_queue_stats(self, switch='s1'):
        """
        Collect queue statistics from OVS switch.
        
        Returns queue configurations and statistics.
        """
        cmd = ['ovs-vsctl', 'list', 'queue']
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            print(f"[ERROR] Queue stats collection failed: {e}")
        
        return None
    
    def save_metrics(self, filename='metrics.json'):
        """Save collected metrics to JSON file."""
        filepath = os.path.join(self.output_dir, filename)
        
        # Convert defaultdict to regular dict for JSON serialization
        data = {
            'throughput': dict(self.metrics['throughput']),
            'latency': dict(self.metrics['latency']),
            'collected_at': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[SAVED] Metrics saved to {filepath}")
        return filepath
    
    def load_metrics(self, filename='metrics.json'):
        """Load metrics from JSON file."""
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        self.metrics['throughput'] = defaultdict(list, data.get('throughput', {}))
        self.metrics['latency'] = defaultdict(list, data.get('latency', {}))
        
        print(f"[LOADED] Metrics loaded from {filepath}")
        return data


class MetricsVisualizer:
    """Visualizes collected QoS metrics."""
    
    def __init__(self, output_dir='results'):
        self.output_dir = output_dir
        
        if not MATPLOTLIB_AVAILABLE:
            print("[ERROR] matplotlib required for visualization")
    
    def plot_throughput_comparison(self, metrics, filename='throughput_comparison.png'):
        """
        Plot throughput comparison between QoS classes.
        """
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        classes = ['GOLD', 'SILVER', 'BRONZE']
        colors = ['#FFD700', '#C0C0C0', '#CD7F32']
        
        for i, qos_class in enumerate(classes):
            if qos_class in metrics['throughput']:
                data = metrics['throughput'][qos_class]
                values = [d['value'] for d in data]
                timestamps = range(len(values))
                
                ax.plot(timestamps, values, 'o-', label=qos_class, 
                       color=colors[i], linewidth=2, markersize=8)
        
        ax.set_xlabel('Measurement #', fontsize=12)
        ax.set_ylabel('Throughput (Mbps)', fontsize=12)
        ax.set_title('Throughput Comparison by QoS Class', fontsize=14, fontweight='bold')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"[PLOT] Throughput comparison saved to {filepath}")
        return filepath
    
    def plot_latency_comparison(self, metrics, filename='latency_comparison.png'):
        """
        Plot latency comparison between QoS classes.
        """
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        classes = ['GOLD', 'SILVER', 'BRONZE']
        colors = ['#FFD700', '#C0C0C0', '#CD7F32']
        
        bar_width = 0.25
        x = range(len(classes))
        
        avg_latencies = []
        min_latencies = []
        max_latencies = []
        
        for qos_class in classes:
            if qos_class in metrics['latency'] and metrics['latency'][qos_class]:
                data = metrics['latency'][qos_class]
                avgs = [d['value']['avg'] for d in data]
                mins = [d['value']['min'] for d in data]
                maxs = [d['value']['max'] for d in data]
                
                avg_latencies.append(sum(avgs) / len(avgs))
                min_latencies.append(sum(mins) / len(mins))
                max_latencies.append(sum(maxs) / len(maxs))
            else:
                avg_latencies.append(0)
                min_latencies.append(0)
                max_latencies.append(0)
        
        bars = ax.bar(x, avg_latencies, bar_width * 2, color=colors, 
                     edgecolor='black', linewidth=1.5)
        
        # Add error bars for min/max
        for i, (bar, min_val, max_val) in enumerate(zip(bars, min_latencies, max_latencies)):
            ax.errorbar(bar.get_x() + bar.get_width()/2, avg_latencies[i],
                       yerr=[[avg_latencies[i] - min_val], [max_val - avg_latencies[i]]],
                       fmt='none', color='black', capsize=5)
        
        ax.set_xlabel('QoS Class', fontsize=12)
        ax.set_ylabel('Latency (ms)', fontsize=12)
        ax.set_title('Latency by QoS Class (Avg with Min/Max)', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(classes)
        ax.grid(True, alpha=0.3, axis='y')
        
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"[PLOT] Latency comparison saved to {filepath}")
        return filepath
    
    def plot_fairness_over_time(self, metrics, filename='fairness_timeline.png'):
        """
        Plot Jain's Fairness Index over time.
        """
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Calculate fairness at each measurement point
        classes = ['GOLD', 'SILVER', 'BRONZE']
        max_len = max(len(metrics['throughput'].get(c, [])) for c in classes)
        
        fairness_values = []
        
        for i in range(max_len):
            throughputs = []
            for qos_class in classes:
                if qos_class in metrics['throughput'] and i < len(metrics['throughput'][qos_class]):
                    throughputs.append(metrics['throughput'][qos_class][i]['value'])
            
            if throughputs:
                n = len(throughputs)
                sum_x = sum(throughputs)
                sum_x2 = sum(x**2 for x in throughputs)
                if sum_x2 > 0:
                    fairness = (sum_x ** 2) / (n * sum_x2)
                else:
                    fairness = 1.0
                fairness_values.append(fairness)
        
        if fairness_values:
            ax.plot(range(len(fairness_values)), fairness_values, 'b-o', 
                   linewidth=2, markersize=8)
            ax.axhline(y=1.0, color='g', linestyle='--', label='Perfect Fairness')
            ax.axhline(y=0.5, color='r', linestyle='--', alpha=0.5, label='50% Fairness')
        
        ax.set_xlabel('Measurement #', fontsize=12)
        ax.set_ylabel("Jain's Fairness Index", fontsize=12)
        ax.set_title("Fairness Index Over Time", fontsize=14, fontweight='bold')
        ax.set_ylim(0, 1.1)
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"[PLOT] Fairness timeline saved to {filepath}")
        return filepath
    
    def generate_report(self, metrics, filename='qos_report.txt'):
        """
        Generate a text report summarizing the metrics.
        """
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w') as f:
            f.write("=" * 60 + "\n")
            f.write("SDN QoS Metrics Report\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            
            # Throughput summary
            f.write("THROUGHPUT SUMMARY (Mbps)\n")
            f.write("-" * 40 + "\n")
            for qos_class in ['GOLD', 'SILVER', 'BRONZE']:
                if qos_class in metrics['throughput'] and metrics['throughput'][qos_class]:
                    values = [d['value'] for d in metrics['throughput'][qos_class]]
                    avg = sum(values) / len(values)
                    min_val = min(values)
                    max_val = max(values)
                    f.write(f"{qos_class:8} Avg: {avg:8.2f}  Min: {min_val:8.2f}  Max: {max_val:8.2f}\n")
            f.write("\n")
            
            # Latency summary
            f.write("LATENCY SUMMARY (ms)\n")
            f.write("-" * 40 + "\n")
            for qos_class in ['GOLD', 'SILVER', 'BRONZE']:
                if qos_class in metrics['latency'] and metrics['latency'][qos_class]:
                    avgs = [d['value']['avg'] for d in metrics['latency'][qos_class]]
                    overall_avg = sum(avgs) / len(avgs)
                    f.write(f"{qos_class:8} Avg RTT: {overall_avg:8.3f} ms\n")
            f.write("\n")
            
            # Fairness calculation
            f.write("FAIRNESS INDEX\n")
            f.write("-" * 40 + "\n")
            throughputs = []
            for qos_class in ['GOLD', 'SILVER', 'BRONZE']:
                if qos_class in metrics['throughput'] and metrics['throughput'][qos_class]:
                    values = [d['value'] for d in metrics['throughput'][qos_class]]
                    throughputs.append(sum(values) / len(values))
            
            if throughputs:
                n = len(throughputs)
                sum_x = sum(throughputs)
                sum_x2 = sum(x**2 for x in throughputs)
                if sum_x2 > 0:
                    fairness = (sum_x ** 2) / (n * sum_x2)
                else:
                    fairness = 1.0
                f.write(f"Jain's Fairness Index: {fairness:.4f}\n")
                f.write(f"(1.0 = perfectly fair, lower = less fair)\n")
            
            f.write("\n" + "=" * 60 + "\n")
        
        print(f"[REPORT] QoS report saved to {filepath}")
        return filepath


def run_full_test(collector, duration=60):
    """
    Run a complete QoS test campaign.
    """
    print("\n" + "=" * 60)
    print("Starting Full QoS Test Campaign")
    print("=" * 60 + "\n")
    
    # Test configurations
    tests = [
        {'class': 'GOLD', 'source': 'h1', 'target': '10.0.0.2', 'bw': '500M'},
        {'class': 'SILVER', 'source': 'h1', 'target': '10.0.0.3', 'bw': '200M'},
        {'class': 'BRONZE', 'source': 'h2', 'target': '10.0.0.3', 'bw': '100M'},
    ]
    
    num_iterations = 5
    test_duration = duration // (len(tests) * num_iterations)
    
    for iteration in range(num_iterations):
        print(f"\n--- Iteration {iteration + 1}/{num_iterations} ---\n")
        
        for test in tests:
            print(f"[{test['class']}] Testing {test['source']} -> {test['target']} @ {test['bw']}")
            
            # Throughput test
            throughput = collector.collect_throughput(
                source_host=test['source'],
                target_ip=test['target'],
                duration=test_duration,
                bandwidth=test['bw'],
                qos_class=test['class']
            )
            if throughput:
                print(f"  Throughput: {throughput:.2f} Mbps")
            
            # Latency test
            latency = collector.collect_latency(
                target_ip=test['target'],
                count=10,
                qos_class=test['class']
            )
            if latency:
                print(f"  Latency: avg={latency['avg']:.3f} ms")
            
            time.sleep(1)
    
    # Save results
    collector.save_metrics()
    
    print("\n" + "=" * 60)
    print("Test Campaign Complete!")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description='SDN QoS Metrics Collector')
    
    parser.add_argument('--collect', action='store_true',
                        help='Run metrics collection')
    parser.add_argument('--visualize', action='store_true',
                        help='Generate visualizations from collected data')
    parser.add_argument('--report', action='store_true',
                        help='Generate text report')
    parser.add_argument('--full-test', action='store_true',
                        help='Run complete test campaign')
    
    parser.add_argument('--output', default='results',
                        help='Output directory (default: results)')
    parser.add_argument('--input', default='results/metrics.json',
                        help='Input metrics file for visualization')
    parser.add_argument('--duration', type=int, default=60,
                        help='Test duration in seconds (default: 60)')
    
    args = parser.parse_args()
    
    collector = MetricsCollector(args.output)
    visualizer = MetricsVisualizer(args.output)
    
    if args.full_test:
        run_full_test(collector, args.duration)
        
        # Auto-generate visualizations and report
        if MATPLOTLIB_AVAILABLE:
            visualizer.plot_throughput_comparison(collector.metrics)
            visualizer.plot_latency_comparison(collector.metrics)
            visualizer.plot_fairness_over_time(collector.metrics)
        visualizer.generate_report(collector.metrics)
        
    elif args.collect:
        # Simple collection mode
        print("[COLLECT] Starting metrics collection...")
        run_full_test(collector, args.duration)
        
    elif args.visualize:
        # Visualization mode
        print(f"[VISUALIZE] Loading metrics from {args.input}")
        
        # Load existing metrics
        input_dir = os.path.dirname(args.input)
        input_file = os.path.basename(args.input)
        collector.output_dir = input_dir
        collector.load_metrics(input_file)
        
        if MATPLOTLIB_AVAILABLE:
            visualizer.output_dir = input_dir
            visualizer.plot_throughput_comparison(collector.metrics)
            visualizer.plot_latency_comparison(collector.metrics)
            visualizer.plot_fairness_over_time(collector.metrics)
        else:
            print("[ERROR] matplotlib required for visualization")
        
    elif args.report:
        # Report generation
        print(f"[REPORT] Loading metrics from {args.input}")
        
        input_dir = os.path.dirname(args.input)
        input_file = os.path.basename(args.input)
        collector.output_dir = input_dir
        collector.load_metrics(input_file)
        
        visualizer.output_dir = input_dir
        visualizer.generate_report(collector.metrics)
        
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

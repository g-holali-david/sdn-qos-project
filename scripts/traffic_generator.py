#!/usr/bin/env python3
"""
SDN QoS Project - Traffic Generator
RSX217 - CNAM Paris
Author: GAVI Holali David

Generates different traffic patterns for QoS testing:
- Static:      Constant bitrate
- Bursty:      ON/OFF pattern with configurable duty cycle
- Oscillating: Sinusoidal rate variation

Usage:
    python3 traffic_generator.py --pattern static --target 10.0.0.2 --rate 100M --duration 60
    python3 traffic_generator.py --pattern bursty --target 10.0.0.2 --rate 100M --on 5 --off 2
    python3 traffic_generator.py --pattern oscillating --target 10.0.0.2 --min-rate 10M --max-rate 100M
"""

import subprocess
import argparse
import time
import threading
import signal
import sys
import math
import os
from datetime import datetime


class TrafficGenerator:
    """Base class for traffic generation."""
    
    def __init__(self, target_ip, duration=60, port=5201):
        self.target_ip = target_ip
        self.duration = duration
        self.port = port
        self.process = None
        self.running = False
        self.start_time = None
        self.results = []
        
    def start(self):
        """Start traffic generation."""
        raise NotImplementedError
    
    def stop(self):
        """Stop traffic generation."""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
    
    def _run_iperf(self, bandwidth, duration, label=""):
        """Run iperf3 with specified bandwidth."""
        cmd = [
            'iperf3',
            '-c', self.target_ip,
            '-p', str(self.port),
            '-b', bandwidth,
            '-t', str(duration),
            '-J'  # JSON output
        ]
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {label} Starting iperf3: {bandwidth} for {duration}s")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
            return result.stdout
        except subprocess.TimeoutExpired:
            print(f"[WARNING] iperf3 timeout")
            return None
        except Exception as e:
            print(f"[ERROR] iperf3 failed: {e}")
            return None


class StaticTraffic(TrafficGenerator):
    """
    Static traffic pattern - constant bitrate.
    
    Generates continuous traffic at a fixed rate.
    """
    
    def __init__(self, target_ip, rate='100M', duration=60, port=5201):
        super().__init__(target_ip, duration, port)
        self.rate = rate
    
    def start(self):
        """Start static traffic generation."""
        self.running = True
        self.start_time = time.time()
        
        print(f"\n{'='*60}")
        print(f"STATIC Traffic Generator")
        print(f"Target: {self.target_ip}:{self.port}")
        print(f"Rate: {self.rate}")
        print(f"Duration: {self.duration}s")
        print(f"{'='*60}\n")
        
        result = self._run_iperf(self.rate, self.duration, "[STATIC]")
        self.results.append(result)
        
        self.running = False
        return self.results


class BurstyTraffic(TrafficGenerator):
    """
    Bursty traffic pattern - ON/OFF cycles.
    
    Alternates between active (ON) and idle (OFF) periods.
    """
    
    def __init__(self, target_ip, rate='100M', duration=60, 
                 on_time=5, off_time=2, port=5201):
        super().__init__(target_ip, duration, port)
        self.rate = rate
        self.on_time = on_time
        self.off_time = off_time
    
    def start(self):
        """Start bursty traffic generation."""
        self.running = True
        self.start_time = time.time()
        
        print(f"\n{'='*60}")
        print(f"BURSTY Traffic Generator")
        print(f"Target: {self.target_ip}:{self.port}")
        print(f"Rate: {self.rate}")
        print(f"Pattern: {self.on_time}s ON / {self.off_time}s OFF")
        print(f"Duration: {self.duration}s")
        print(f"{'='*60}\n")
        
        cycle = 0
        elapsed = 0
        
        while elapsed < self.duration and self.running:
            cycle += 1
            
            # ON period
            on_duration = min(self.on_time, self.duration - elapsed)
            if on_duration > 0:
                result = self._run_iperf(self.rate, on_duration, f"[BURST {cycle}]")
                self.results.append(result)
                elapsed += on_duration
            
            # OFF period
            if elapsed < self.duration and self.running:
                off_duration = min(self.off_time, self.duration - elapsed)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [IDLE] Sleeping for {off_duration}s")
                time.sleep(off_duration)
                elapsed += off_duration
        
        self.running = False
        return self.results


class OscillatingTraffic(TrafficGenerator):
    """
    Oscillating traffic pattern - sinusoidal rate variation.
    
    Rate varies between min and max following a sine wave.
    """
    
    def __init__(self, target_ip, min_rate='10M', max_rate='100M', 
                 duration=60, period=20, steps=10, port=5201):
        super().__init__(target_ip, duration, port)
        self.min_rate = self._parse_rate(min_rate)
        self.max_rate = self._parse_rate(max_rate)
        self.period = period  # Full sine wave period in seconds
        self.steps = steps    # Number of rate changes per period
    
    def _parse_rate(self, rate_str):
        """Parse rate string (e.g., '100M') to bits per second."""
        rate_str = rate_str.upper()
        if rate_str.endswith('G'):
            return int(float(rate_str[:-1]) * 1e9)
        elif rate_str.endswith('M'):
            return int(float(rate_str[:-1]) * 1e6)
        elif rate_str.endswith('K'):
            return int(float(rate_str[:-1]) * 1e3)
        else:
            return int(rate_str)
    
    def _format_rate(self, rate_bps):
        """Format rate in bits/s to human readable."""
        if rate_bps >= 1e9:
            return f"{rate_bps/1e9:.1f}G"
        elif rate_bps >= 1e6:
            return f"{rate_bps/1e6:.1f}M"
        elif rate_bps >= 1e3:
            return f"{rate_bps/1e3:.1f}K"
        else:
            return f"{rate_bps}"
    
    def _calculate_rate(self, t):
        """Calculate rate at time t using sine function."""
        # Sine oscillates between -1 and 1
        # Map to [min_rate, max_rate]
        amplitude = (self.max_rate - self.min_rate) / 2
        midpoint = (self.max_rate + self.min_rate) / 2
        
        rate = midpoint + amplitude * math.sin(2 * math.pi * t / self.period)
        return int(rate)
    
    def start(self):
        """Start oscillating traffic generation."""
        self.running = True
        self.start_time = time.time()
        
        print(f"\n{'='*60}")
        print(f"OSCILLATING Traffic Generator")
        print(f"Target: {self.target_ip}:{self.port}")
        print(f"Rate range: {self._format_rate(self.min_rate)} - {self._format_rate(self.max_rate)}")
        print(f"Period: {self.period}s")
        print(f"Duration: {self.duration}s")
        print(f"{'='*60}\n")
        
        step_duration = self.period / self.steps
        elapsed = 0
        step = 0
        
        while elapsed < self.duration and self.running:
            step += 1
            
            # Calculate current rate based on elapsed time
            current_rate = self._calculate_rate(elapsed)
            rate_str = self._format_rate(current_rate)
            
            # Calculate step duration (don't exceed total duration)
            actual_duration = min(step_duration, self.duration - elapsed)
            
            if actual_duration > 0:
                result = self._run_iperf(rate_str, int(actual_duration), f"[WAVE {step}]")
                self.results.append(result)
                elapsed += actual_duration
        
        self.running = False
        return self.results


class TrafficServer:
    """iperf3 server wrapper."""
    
    def __init__(self, port=5201):
        self.port = port
        self.process = None
    
    def start(self):
        """Start iperf3 server in background."""
        cmd = ['iperf3', '-s', '-p', str(self.port)]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[SERVER] iperf3 server started on port {self.port}")
        return self.process
    
    def stop(self):
        """Stop iperf3 server."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print(f"[SERVER] iperf3 server stopped")


def main():
    parser = argparse.ArgumentParser(
        description='SDN QoS Traffic Generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Static traffic at 100 Mbps for 60 seconds:
    python3 traffic_generator.py --pattern static --target 10.0.0.2 --rate 100M --duration 60

  Bursty traffic with 5s ON / 2s OFF:
    python3 traffic_generator.py --pattern bursty --target 10.0.0.2 --rate 100M --on 5 --off 2

  Oscillating traffic between 10-100 Mbps:
    python3 traffic_generator.py --pattern oscillating --target 10.0.0.2 --min-rate 10M --max-rate 100M

  Start iperf3 server:
    python3 traffic_generator.py --server --port 5201
        """
    )
    
    parser.add_argument('--pattern', choices=['static', 'bursty', 'oscillating'],
                        help='Traffic pattern type')
    parser.add_argument('--target', default='10.0.0.2',
                        help='Target IP address (default: 10.0.0.2)')
    parser.add_argument('--port', type=int, default=5201,
                        help='iperf3 port (default: 5201)')
    parser.add_argument('--duration', type=int, default=60,
                        help='Total duration in seconds (default: 60)')
    
    # Static options
    parser.add_argument('--rate', default='100M',
                        help='Bandwidth rate for static/bursty (default: 100M)')
    
    # Bursty options
    parser.add_argument('--on', type=int, default=5,
                        help='ON period for bursty pattern (default: 5s)')
    parser.add_argument('--off', type=int, default=2,
                        help='OFF period for bursty pattern (default: 2s)')
    
    # Oscillating options
    parser.add_argument('--min-rate', default='10M',
                        help='Minimum rate for oscillating (default: 10M)')
    parser.add_argument('--max-rate', default='100M',
                        help='Maximum rate for oscillating (default: 100M)')
    parser.add_argument('--period', type=int, default=20,
                        help='Sine wave period for oscillating (default: 20s)')
    
    # Server mode
    parser.add_argument('--server', action='store_true',
                        help='Start iperf3 server mode')
    
    args = parser.parse_args()
    
    # Handle server mode
    if args.server:
        server = TrafficServer(args.port)
        server.start()
        try:
            print("Press Ctrl+C to stop server...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
        return
    
    # Validate pattern argument
    if not args.pattern:
        parser.error("--pattern is required (unless using --server)")
    
    # Create appropriate generator
    if args.pattern == 'static':
        generator = StaticTraffic(
            target_ip=args.target,
            rate=args.rate,
            duration=args.duration,
            port=args.port
        )
    elif args.pattern == 'bursty':
        generator = BurstyTraffic(
            target_ip=args.target,
            rate=args.rate,
            duration=args.duration,
            on_time=args.on,
            off_time=args.off,
            port=args.port
        )
    elif args.pattern == 'oscillating':
        generator = OscillatingTraffic(
            target_ip=args.target,
            min_rate=args.min_rate,
            max_rate=args.max_rate,
            duration=args.duration,
            period=args.period,
            port=args.port
        )
    
    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print("\n[INTERRUPTED] Stopping traffic generator...")
        generator.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start traffic generation
    try:
        results = generator.start()
        print(f"\n{'='*60}")
        print(f"Traffic generation completed!")
        print(f"Total results collected: {len(results)}")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"[ERROR] Traffic generation failed: {e}")
        generator.stop()


if __name__ == '__main__':
    main()

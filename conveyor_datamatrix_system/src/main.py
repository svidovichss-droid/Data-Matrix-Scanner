#!/usr/bin/env python3
"""
Industrial DataMatrix Recognition System - Main Entry Point

Real-time DataMatrix code detection and decoding for conveyor belt applications.
"""

import argparse
import logging
import signal
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import yaml

from src.camera_interface import create_camera, CameraConfig
from src.pipeline import ProcessingPipeline, ProcessingResult
from src.datamatrix_decoder import DataMatrixResult


# Configure logging
def setup_logging(config: Dict[str, Any]) -> None:
    """Setup logging configuration"""
    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', 'logs/system.log')
    
    # Create logs directory
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


class DataMatrixSystem:
    """Main system controller for DataMatrix recognition"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.pipeline: ProcessingPipeline = None
        self.running = False
        
        # Output configuration
        self.output_config = config.get('output', {})
        self.output_format = self.output_config.get('format', 'console')
        
        # Setup output handlers
        if self.output_format == 'file':
            self._setup_file_output()
        elif self.output_format == 'mqtt':
            self._setup_mqtt_output()
        elif self.output_format == 'tcp':
            self._setup_tcp_output()
        
        logger = logging.getLogger(__name__)
        logger.info("DataMatrixSystem initialized")
    
    def _setup_file_output(self):
        """Setup file output handler"""
        file_config = self.output_config.get('file', {})
        output_path = Path(file_config.get('path', './results'))
        output_path.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(__name__)
        logger.info(f"File output configured: {output_path}")
    
    def _setup_mqtt_output(self):
        """Setup MQTT output handler"""
        # MQTT implementation would go here
        logger = logging.getLogger(__name__)
        logger.info("MQTT output configured (not implemented in demo)")
    
    def _setup_tcp_output(self):
        """Setup TCP output handler"""
        # TCP implementation would go here
        logger = logging.getLogger(__name__)
        logger.info("TCP output configured (not implemented in demo)")
    
    def _handle_result(self, result: ProcessingResult) -> None:
        """Handle processing results"""
        if not result.success:
            return
        
        # Format output based on configuration
        if self.output_format == 'console':
            self._output_console(result)
        elif self.output_format == 'json':
            self._output_json(result)
        elif self.output_format == 'file':
            self._output_file(result)
        elif self.output_format == 'mqtt':
            self._output_mqtt(result)
        elif self.output_format == 'tcp':
            self._output_tcp(result)
    
    def _output_console(self, result: ProcessingResult) -> None:
        """Output results to console"""
        if result.decode_results:
            for dm_result in result.decode_results:
                timestamp = datetime.fromtimestamp(dm_result.timestamp).strftime(
                    self.output_config.get('timestamp_format', '%Y-%m-%d %H:%M:%S.%f')
                )
                print(f"\n[{timestamp}] DataMatrix Detected:")
                print(f"  Data: {dm_result.data}")
                print(f"  Confidence: {dm_result.confidence:.2f}")
                print(f"  Decode Time: {dm_result.decode_time_ms:.2f}ms")
                print(f"  Location: {dm_result.location}")
    
    def _output_json(self, result: ProcessingResult) -> None:
        """Output results as JSON"""
        output_dict = result.to_dict()
        print(json.dumps(output_dict, indent=2))
    
    def _output_file(self, result: ProcessingResult) -> None:
        """Output results to file"""
        if not result.decode_results:
            return
        
        file_config = self.output_config.get('file', {})
        output_path = Path(file_config.get('path', './results'))
        filename_pattern = file_config.get('filename_pattern', 'datamatrix_{timestamp}.json')
        
        timestamp = datetime.fromtimestamp(result.process_timestamp).strftime('%Y%m%d_%H%M%S_%f')
        filename = filename_pattern.replace('{timestamp}', timestamp)
        filepath = output_path / filename
        
        output_dict = result.to_dict()
        with open(filepath, 'w') as f:
            json.dump(output_dict, f, indent=2)
        
        logger = logging.getLogger(__name__)
        logger.debug(f"Result saved to {filepath}")
    
    def _output_mqtt(self, result: ProcessingResult) -> None:
        """Output results via MQTT"""
        # MQTT implementation would go here
        pass
    
    def _output_tcp(self, result: ProcessingResult) -> None:
        """Output results via TCP"""
        # TCP implementation would go here
        pass
    
    def start(self) -> None:
        """Start the system"""
        logger = logging.getLogger(__name__)
        logger.info("Starting DataMatrix Recognition System...")
        
        # Create camera
        camera_config_data = self.config.get('camera', {})
        camera_config = CameraConfig(
            camera_type=camera_config_data.get('type', 'test'),
            camera_id=camera_config_data.get('id', 0),
            width=camera_config_data.get('settings', {}).get('width', 2448),
            height=camera_config_data.get('settings', {}).get('height', 2048),
            exposure_time=camera_config_data.get('settings', {}).get('exposure_time', 5000),
            gain=camera_config_data.get('settings', {}).get('gain', 10.0),
            trigger_enabled=camera_config_data.get('trigger', {}).get('enabled', True),
            trigger_mode=camera_config_data.get('trigger', {}).get('mode', 'hardware')
        )
        
        camera = create_camera(camera_config)
        
        # Open camera
        if not camera.open():
            logger.error("Failed to open camera")
            return
        
        logger.info(f"Camera opened: {camera_config.camera_type}")
        
        # Create and start pipeline
        processing_config = self.config.get('processing', {})
        self.pipeline = ProcessingPipeline(camera, processing_config)
        self.pipeline.set_result_callback(self._handle_result)
        self.pipeline.start()
        
        self.running = True
        logger.info("System started successfully")
        
        # Start monitoring loop
        self._monitoring_loop()
    
    def stop(self) -> None:
        """Stop the system"""
        logger = logging.getLogger(__name__)
        logger.info("Stopping system...")
        
        self.running = False
        
        if self.pipeline:
            self.pipeline.stop()
        
        logger.info("System stopped")
    
    def _monitoring_loop(self) -> None:
        """Monitoring and statistics loop"""
        logger = logging.getLogger(__name__)
        monitoring_config = self.config.get('monitoring', {})
        interval = monitoring_config.get('metrics_interval_sec', 5)
        
        try:
            while self.running:
                time.sleep(interval)
                
                if monitoring_config.get('log_performance', True):
                    stats = self.pipeline.get_statistics()
                    logger.info(
                        f"Performance: {stats['fps_process']:.1f} FPS, "
                        f"Avg Process Time: {stats['avg_processing_time_ms']:.2f}ms, "
                        f"Codes Found: {stats['codes_found']}"
                    )
        except KeyboardInterrupt:
            pass
    
    def run_demo(self, duration_sec: int = 10) -> None:
        """Run a demonstration for specified duration"""
        logger = logging.getLogger(__name__)
        logger.info(f"Running demo for {duration_sec} seconds...")
        
        # Start in background thread
        import threading
        start_thread = threading.Thread(target=self.start)
        start_thread.daemon = True
        start_thread.start()
        
        # Wait for duration
        time.sleep(duration_sec)
        
        # Stop
        self.stop()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Industrial DataMatrix Recognition System'
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='config/camera_config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help='Run in test mode without camera hardware'
    )
    parser.add_argument(
        '--camera-id',
        type=int,
        default=None,
        help='Camera device ID or index'
    )
    parser.add_argument(
        '--demo-duration',
        type=int,
        default=10,
        help='Demo duration in seconds'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Configuration file not found: {args.config}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)
    
    # Override config for test mode
    if args.test_mode:
        config['camera']['type'] = 'test'
    
    # Override camera ID if specified
    if args.camera_id is not None:
        config['camera']['id'] = args.camera_id
    
    # Setup logging
    setup_logging(config)
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Industrial DataMatrix Recognition System")
    logger.info("=" * 60)
    
    # Create system instance
    system = DataMatrixSystem(config)
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("\nReceived interrupt signal, shutting down...")
        system.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run system
    try:
        if args.demo_duration > 0:
            system.run_demo(args.demo_duration)
        else:
            system.start()
    except Exception as e:
        logger.error(f"System error: {e}")
        system.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()

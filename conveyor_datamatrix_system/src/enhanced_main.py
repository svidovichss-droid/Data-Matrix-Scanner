#!/usr/bin/env python3
"""
Industrial DataMatrix Recognition System - Enhanced Version
with History Tracking and Quality Assessment

Real-time DataMatrix code detection and decoding for conveyor belt applications.
Features:
- Instant capture and processing
- History recording of all detected codes
- Quality assessment for each decode
- Support for sequential DataMatrix codes on conveyor
"""

import argparse
import logging
import signal
import sys
import time
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
import threading

import numpy as np
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


@dataclass
class QualityAssessment:
    """Quality assessment for a decoded DataMatrix"""
    overall_score: float  # 0.0 - 1.0
    confidence: float
    contrast_score: float
    sharpness_score: float
    size_score: float
    position_score: float
    grade: str  # A, B, C, D, F
    issues: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HistoryEntry:
    """Historical record of a detected DataMatrix"""
    entry_id: int
    timestamp: float
    frame_id: int
    data: str
    confidence: float
    quality_assessment: QualityAssessment
    location: List[tuple]
    decode_time_ms: float
    image_width: int
    image_height: int
    conveyor_position: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['quality_assessment'] = self.quality_assessment.to_dict()
        return result


class HistoryManager:
    """Manages history of detected DataMatrix codes"""
    
    def __init__(self, db_path: str = "datamatrix_history.db", max_entries: int = 10000):
        self.db_path = db_path
        self.max_entries = max_entries
        self.memory_cache = deque(maxlen=1000)  # Keep last 1000 in memory
        self.entry_counter = 0
        self.lock = threading.Lock()
        
        # Initialize database
        self._init_database()
        
        logger = logging.getLogger(__name__)
        logger.info(f"HistoryManager initialized with DB: {db_path}")
    
    def _init_database(self):
        """Initialize SQLite database for history storage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS datamatrix_history (
                entry_id INTEGER PRIMARY KEY,
                timestamp REAL NOT NULL,
                frame_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                confidence REAL NOT NULL,
                overall_score REAL NOT NULL,
                grade TEXT NOT NULL,
                location TEXT NOT NULL,
                decode_time_ms REAL NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                conveyor_position REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index for fast queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON datamatrix_history(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_data ON datamatrix_history(data)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_grade ON datamatrix_history(grade)')
        
        conn.commit()
        conn.close()
    
    def add_entry(self, result: DataMatrixResult, quality: QualityAssessment, 
                  frame_id: int, conveyor_position: Optional[float] = None) -> HistoryEntry:
        """Add a new entry to history"""
        with self.lock:
            self.entry_counter += 1
            
            entry = HistoryEntry(
                entry_id=self.entry_counter,
                timestamp=result.timestamp,
                frame_id=frame_id,
                data=result.data,
                confidence=result.confidence,
                quality_assessment=quality,
                location=result.location,
                decode_time_ms=result.decode_time_ms,
                image_width=result.image_width,
                image_height=result.image_height,
                conveyor_position=conveyor_position
            )
            
            # Add to memory cache
            self.memory_cache.append(entry)
            
            # Add to database
            self._save_to_db(entry)
            
            return entry
    
    def _save_to_db(self, entry: HistoryEntry):
        """Save entry to SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO datamatrix_history 
            (entry_id, timestamp, frame_id, data, confidence, overall_score, grade,
             location, decode_time_ms, image_width, image_height, conveyor_position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry.entry_id,
            entry.timestamp,
            entry.frame_id,
            entry.data,
            entry.confidence,
            entry.quality_assessment.overall_score,
            entry.quality_assessment.grade,
            json.dumps(entry.location),
            entry.decode_time_ms,
            entry.image_width,
            entry.image_height,
            entry.conveyor_position
        ))
        
        # Cleanup old entries if needed
        cursor.execute('SELECT COUNT(*) FROM datamatrix_history')
        count = cursor.fetchone()[0]
        if count > self.max_entries:
            cursor.execute('''
                DELETE FROM datamatrix_history 
                WHERE entry_id IN (
                    SELECT entry_id FROM datamatrix_history 
                    ORDER BY timestamp ASC 
                    LIMIT ?
                )
            ''', (count - self.max_entries,))
        
        conn.commit()
        conn.close()
    
    def get_recent_entries(self, limit: int = 100) -> List[HistoryEntry]:
        """Get recent history entries from memory cache"""
        return list(self.memory_cache)[-limit:]
    
    def query_by_data(self, data: str, limit: int = 50) -> List[HistoryEntry]:
        """Query history by DataMatrix content"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT entry_id, timestamp, frame_id, data, confidence, overall_score, grade,
                   location, decode_time_ms, image_width, image_height, conveyor_position
            FROM datamatrix_history
            WHERE data = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (data, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        entries = []
        for row in rows:
            quality = QualityAssessment(
                overall_score=row[5],
                confidence=0.0,
                contrast_score=0.0,
                sharpness_score=0.0,
                size_score=0.0,
                position_score=0.0,
                grade=row[6],
                issues=[]
            )
            entry = HistoryEntry(
                entry_id=row[0],
                timestamp=row[1],
                frame_id=row[2],
                data=row[3],
                confidence=row[4],
                quality_assessment=quality,
                location=json.loads(row[7]),
                decode_time_ms=row[8],
                image_width=row[9],
                image_height=row[10],
                conveyor_position=row[11]
            )
            entries.append(entry)
        
        return entries
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics from history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total count
        cursor.execute('SELECT COUNT(*) FROM datamatrix_history')
        total_count = cursor.fetchone()[0]
        
        # Count by grade
        cursor.execute('''
            SELECT grade, COUNT(*) 
            FROM datamatrix_history 
            GROUP BY grade 
            ORDER BY grade
        ''')
        grade_counts = dict(cursor.fetchall())
        
        # Average quality score
        cursor.execute('SELECT AVG(overall_score) FROM datamatrix_history')
        avg_score = cursor.fetchone()[0] or 0.0
        
        # Recent detections (last hour)
        hour_ago = time.time() - 3600
        cursor.execute('SELECT COUNT(*) FROM datamatrix_history WHERE timestamp > ?', (hour_ago,))
        recent_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_detections': total_count,
            'grade_distribution': grade_counts,
            'average_quality_score': avg_score,
            'recent_detections_last_hour': recent_count,
            'memory_cache_size': len(self.memory_cache)
        }


class QualityAssessor:
    """Assesses quality of DataMatrix decoding"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.min_size = config.get('min_size', 20)
        self.max_size = config.get('max_size', 500)
        self.optimal_size = (self.min_size + self.max_size) / 2
        
        # Thresholds for grading
        self.grade_thresholds = {
            'A': 0.9,  # Excellent
            'B': 0.8,  # Good
            'C': 0.7,  # Acceptable
            'D': 0.6,  # Marginal
            'F': 0.0   # Fail
        }
        
        logger = logging.getLogger(__name__)
        logger.info("QualityAssessor initialized")
    
    def assess(self, result: DataMatrixResult, image: Optional[np.ndarray] = None) -> QualityAssessment:
        """Perform comprehensive quality assessment"""
        issues = []
        
        # Confidence score (already provided by decoder)
        confidence_score = result.confidence
        
        # Size score
        if result.location and len(result.location) >= 2:
            # Calculate approximate size from location
            x_coords = [p[0] for p in result.location]
            y_coords = [p[1] for p in result.location]
            width = max(x_coords) - min(x_coords)
            height = max(y_coords) - min(y_coords)
            avg_size = (width + height) / 2
            
            size_ratio = min(avg_size / self.optimal_size, self.optimal_size / avg_size)
            size_score = max(0.0, min(1.0, size_ratio))
            
            if avg_size < self.min_size:
                issues.append(f"Code too small ({avg_size:.1f}px < {self.min_size}px)")
            elif avg_size > self.max_size:
                issues.append(f"Code too large ({avg_size:.1f}px > {self.max_size}px)")
        else:
            size_score = 0.5
            issues.append("Unable to determine code size")
        
        # Contrast score (if image is provided)
        contrast_score = 0.8  # Default if no image analysis
        if image is not None:
            contrast_score = self._analyze_contrast(image, result.location)
            if contrast_score < 0.5:
                issues.append("Low contrast detected")
        
        # Sharpness score (estimated from decode time and confidence)
        sharpness_score = min(1.0, confidence_score * 1.2)
        if sharpness_score < 0.6:
            issues.append("Possible motion blur or poor focus")
        
        # Position score (center of image is optimal for conveyor systems)
        position_score = self._assess_position(result.location, result.image_width, result.image_height)
        if position_score < 0.5:
            issues.append("Code at edge of field of view")
        
        # Calculate overall score (weighted average)
        weights = {
            'confidence': 0.35,
            'size': 0.20,
            'contrast': 0.20,
            'sharpness': 0.15,
            'position': 0.10
        }
        
        overall_score = (
            confidence_score * weights['confidence'] +
            size_score * weights['size'] +
            contrast_score * weights['contrast'] +
            sharpness_score * weights['sharpness'] +
            position_score * weights['position']
        )
        
        # Determine grade
        grade = 'F'
        for grade_name, threshold in sorted(self.grade_thresholds.items(), 
                                            key=lambda x: x[1], reverse=True):
            if overall_score >= threshold:
                grade = grade_name
                break
        
        return QualityAssessment(
            overall_score=overall_score,
            confidence=confidence_score,
            contrast_score=contrast_score,
            sharpness_score=sharpness_score,
            size_score=size_score,
            position_score=position_score,
            grade=grade,
            issues=issues
        )
    
    def _analyze_contrast(self, image: np.ndarray, location: List[tuple]) -> float:
        """Analyze contrast in the code region"""
        import cv2
        import numpy as np
        
        if not location or len(location) < 2:
            return 0.5
        
        try:
            # Get bounding box
            x_coords = [p[0] for p in location]
            y_coords = [p[1] for p in location]
            x_min, x_max = min(x_coords), max(x_coords)
            y_min, y_max = min(y_coords), max(y_coords)
            
            # Extract ROI
            roi = image[y_min:y_max, x_min:x_max]
            if roi.size == 0:
                return 0.5
            
            # Calculate contrast
            if len(roi.shape) == 3:
                roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            
            contrast = np.std(roi) / (np.mean(roi) + 1e-6)
            return min(1.0, contrast / 0.5)  # Normalize
        except Exception:
            return 0.5
    
    def _assess_position(self, location: List[tuple], img_width: int, 
                         img_height: int) -> float:
        """Assess if code is in optimal position"""
        if not location:
            return 0.5
        
        # Calculate center of code
        x_coords = [p[0] for p in location]
        y_coords = [p[1] for p in location]
        code_center_x = sum(x_coords) / len(x_coords)
        code_center_y = sum(y_coords) / len(y_coords)
        
        # Optimal position is center of image
        img_center_x = img_width / 2
        img_center_y = img_height / 2
        
        # Calculate normalized distance from center
        dx = abs(code_center_x - img_center_x) / (img_width / 2)
        dy = abs(code_center_y - img_center_y) / (img_height / 2)
        distance = (dx + dy) / 2
        
        # Score decreases with distance from center
        return max(0.0, 1.0 - distance)


class EnhancedDataMatrixSystem:
    """Enhanced system with instant capture, history, and quality assessment"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.pipeline: ProcessingPipeline = None
        self.running = False
        
        # Initialize components
        self.quality_assessor = QualityAssessor(config.get('processing', {}))
        
        # History manager
        history_config = config.get('history', {})
        db_path = history_config.get('database', 'datamatrix_history.db')
        max_entries = history_config.get('max_entries', 10000)
        self.history_manager = HistoryManager(db_path=db_path, max_entries=max_entries)
        
        # Output configuration
        self.output_config = config.get('output', {})
        self.output_format = self.output_config.get('format', 'console')
        
        # Statistics
        self.stats = {
            'total_detected': 0,
            'grades': {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0},
            'start_time': None
        }
        
        # Setup output handlers
        if self.output_format == 'file':
            self._setup_file_output()
        elif self.output_format == 'mqtt':
            self._setup_mqtt_output()
        elif self.output_format == 'tcp':
            self._setup_tcp_output()
        
        logger = logging.getLogger(__name__)
        logger.info("EnhancedDataMatrixSystem initialized with history tracking")
    
    def _setup_file_output(self):
        """Setup file output handler"""
        file_config = self.output_config.get('file', {})
        output_path = Path(file_config.get('path', './results'))
        output_path.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(__name__)
        logger.info(f"File output configured: {output_path}")
    
    def _setup_mqtt_output(self):
        """Setup MQTT output handler"""
        logger = logging.getLogger(__name__)
        logger.info("MQTT output configured (not implemented in demo)")
    
    def _setup_tcp_output(self):
        """Setup TCP output handler"""
        logger = logging.getLogger(__name__)
        logger.info("TCP output configured (not implemented in demo)")
    
    def _handle_result(self, result: ProcessingResult) -> None:
        """Handle processing results with quality assessment and history"""
        if not result.success:
            return
        
        logger = logging.getLogger(__name__)
        
        if result.decode_results:
            for dm_result in result.decode_results:
                # Perform quality assessment
                quality = self.quality_assessor.assess(dm_result)
                
                # Add to history
                history_entry = self.history_manager.add_entry(
                    result=dm_result,
                    quality=quality,
                    frame_id=result.frame_id
                )
                
                # Update statistics
                self.stats['total_detected'] += 1
                self.stats['grades'][quality.grade] += 1
                
                # Output based on format
                if self.output_format == 'console':
                    self._output_console(history_entry, result)
                elif self.output_format == 'json':
                    self._output_json(history_entry, result)
                elif self.output_format == 'file':
                    self._output_file(history_entry, result)
    
    def _output_console(self, entry: HistoryEntry, result: ProcessingResult) -> None:
        """Output results to console with quality assessment"""
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime(
            self.output_config.get('timestamp_format', '%Y-%m-%d %H:%M:%S.%f')[:-3]
        )
        
        print(f"\n{'='*60}")
        print(f"[{timestamp}] DataMatrix #{entry.entry_id} Detected")
        print(f"{'='*60}")
        print(f"  Data: {entry.data}")
        print(f"  Quality Grade: {entry.quality_assessment.grade}")
        print(f"  Overall Score: {entry.quality_assessment.overall_score:.2f}")
        print(f"  Confidence: {entry.confidence:.2f}")
        print(f"  Decode Time: {entry.decode_time_ms:.2f}ms")
        print(f"  Location: {entry.location}")
        
        if entry.quality_assessment.issues:
            print(f"  Issues:")
            for issue in entry.quality_assessment.issues:
                print(f"    - {issue}")
        
        # Show summary
        stats = self.history_manager.get_statistics()
        print(f"\n  Session Stats: Total={stats['total_detections']}, "
              f"A:{stats['grade_distribution'].get('A', 0)}, "
              f"B:{stats['grade_distribution'].get('B', 0)}, "
              f"C:{stats['grade_distribution'].get('C', 0)}, "
              f"D:{stats['grade_distribution'].get('D', 0)}, "
              f"F:{stats['grade_distribution'].get('F', 0)}")
    
    def _output_json(self, entry: HistoryEntry, result: ProcessingResult) -> None:
        """Output results as JSON"""
        output_dict = entry.to_dict()
        output_dict['frame_processing_time_ms'] = result.processing_time_ms
        print(json.dumps(output_dict, indent=2))
    
    def _output_file(self, entry: HistoryEntry, result: ProcessingResult) -> None:
        """Output results to file"""
        file_config = self.output_config.get('file', {})
        output_path = Path(file_config.get('path', './results'))
        filename_pattern = file_config.get('filename_pattern', 'datamatrix_{timestamp}.json')
        
        timestamp = datetime.fromtimestamp(result.process_timestamp).strftime('%Y%m%d_%H%M%S_%f')
        filename = filename_pattern.replace('{timestamp}', timestamp)
        filepath = output_path / filename
        
        output_dict = entry.to_dict()
        output_dict['frame_processing_time_ms'] = result.processing_time_ms
        with open(filepath, 'w') as f:
            json.dump(output_dict, f, indent=2)
        
        logger = logging.getLogger(__name__)
        logger.debug(f"Result saved to {filepath}")
    
    def start(self) -> None:
        """Start the system"""
        logger = logging.getLogger(__name__)
        logger.info("Starting Enhanced DataMatrix Recognition System...")
        
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
        self.stats['start_time'] = time.time()
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
        
        # Final statistics
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            logger.info(f"Final Statistics:")
            logger.info(f"  Total Runtime: {elapsed:.1f}s")
            logger.info(f"  Total Detections: {self.stats['total_detected']}")
            logger.info(f"  Grade Distribution: {self.stats['grades']}")
        
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
                    history_stats = self.history_manager.get_statistics()
                    
                    logger.info(
                        f"Performance: {stats['fps_process']:.1f} FPS, "
                        f"Avg Process Time: {stats['avg_processing_time_ms']:.2f}ms"
                    )
                    logger.info(
                        f"History: Total={history_stats['total_detections']}, "
                        f"Avg Quality={history_stats['average_quality_score']:.2f}"
                    )
        except KeyboardInterrupt:
            pass
    
    def run_demo(self, duration_sec: int = 10) -> None:
        """Run a demonstration for specified duration"""
        logger = logging.getLogger(__name__)
        logger.info(f"Running demo for {duration_sec} seconds...")
        
        import threading
        start_thread = threading.Thread(target=self.start)
        start_thread.daemon = True
        start_thread.start()
        
        time.sleep(duration_sec)
        
        self.stop()
    
    def export_history(self, output_file: str, format: str = 'json') -> None:
        """Export history to file"""
        entries = self.history_manager.get_recent_entries(limit=10000)
        
        if format == 'json':
            with open(output_file, 'w') as f:
                json.dump([e.to_dict() for e in entries], f, indent=2)
        elif format == 'csv':
            import csv
            with open(output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Timestamp', 'Data', 'Grade', 'Score', 'Confidence'])
                for e in entries:
                    writer.writerow([
                        e.entry_id,
                        datetime.fromtimestamp(e.timestamp).isoformat(),
                        e.data,
                        e.quality_assessment.grade,
                        f"{e.quality_assessment.overall_score:.3f}",
                        f"{e.confidence:.3f}"
                    ])
        
        logger = logging.getLogger(__name__)
        logger.info(f"Exported {len(entries)} entries to {output_file}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Enhanced Industrial DataMatrix Recognition System'
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
    parser.add_argument(
        '--export-history',
        type=str,
        default=None,
        help='Export history to file (JSON or CSV)'
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
    logger.info("Enhanced Industrial DataMatrix Recognition System")
    logger.info("Features: Instant Capture, History Tracking, Quality Assessment")
    logger.info("=" * 60)
    
    # Create system instance
    system = EnhancedDataMatrixSystem(config)
    
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

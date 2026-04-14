"""
Processing Pipeline Module

Multi-threaded pipeline for high-throughput image processing
on industrial conveyor systems.
"""

import time
import logging
import threading
import queue
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from collections import deque
from datetime import datetime

import numpy as np

from .camera_interface import CapturedFrame, BaseCamera
from .datamatrix_decoder import DataMatrixDecoder, DataMatrixResult


logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Complete processing result with metadata"""
    frame_id: int
    capture_timestamp: float
    process_timestamp: float
    decode_results: list[DataMatrixResult]
    processing_time_ms: float
    success: bool
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'frame_id': self.frame_id,
            'capture_timestamp': self.capture_timestamp,
            'process_timestamp': self.process_timestamp,
            'decode_results': [r.to_dict() for r in self.decode_results],
            'processing_time_ms': self.processing_time_ms,
            'success': self.success,
            'error_message': self.error_message
        }


class RingBuffer:
    """Thread-safe ring buffer for image frames"""
    
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self.lock = threading.Lock()
        self.not_empty = threading.Condition(self.lock)
        
    def put(self, item: CapturedFrame) -> None:
        """Add item to buffer, dropping oldest if full"""
        with self.lock:
            self.buffer.append(item)
            self.not_empty.notify()
            
    def get(self, timeout: Optional[float] = None) -> Optional[CapturedFrame]:
        """Get oldest item from buffer"""
        with self.not_empty:
            if not self.buffer:
                if timeout is not None:
                    self.not_empty.wait(timeout)
                if not self.buffer:
                    return None
            return self.buffer.popleft()
    
    def size(self) -> int:
        """Current buffer size"""
        with self.lock:
            return len(self.buffer)
    
    def clear(self) -> None:
        """Clear the buffer"""
        with self.lock:
            self.buffer.clear()


class ProcessingPipeline:
    """
    Multi-threaded processing pipeline for real-time DataMatrix detection.
    
    Architecture:
    - Capture thread: Acquires images from camera
    - Processing threads: Decode DataMatrix codes
    - Output thread: Handles results and notifications
    """
    
    def __init__(self, camera: BaseCamera, config: Dict[str, Any]):
        self.camera = camera
        self.config = config
        
        # Configuration
        self.num_workers = config.get('num_workers', 4)
        self.buffer_size = config.get('buffer_size', 10)
        
        # Initialize decoder
        decoder_config = config.get('decoder', {})
        preprocessing_config = config.get('preprocessing', {})
        detection_config = config.get('detection', {})
        
        full_decoder_config = {
            **decoder_config,
            **preprocessing_config,
            **detection_config
        }
        
        self.decoder = DataMatrixDecoder(full_decoder_config)
        
        # Buffers and queues
        self.frame_buffer = RingBuffer(self.buffer_size)
        self.result_queue = queue.Queue(maxsize=self.buffer_size * 2)
        
        # Control flags
        self.running = False
        self.pause_processing = False
        
        # Threads
        self.capture_thread: Optional[threading.Thread] = None
        self.worker_threads: list[threading.Thread] = []
        self.output_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_result_callback: Optional[Callable[[ProcessingResult], None]] = None
        
        # Statistics
        self.stats = {
            'frames_captured': 0,
            'frames_processed': 0,
            'codes_found': 0,
            'total_processing_time_ms': 0.0,
            'start_time': None
        }
        self.stats_lock = threading.Lock()
        
        logger.info(f"ProcessingPipeline initialized with {self.num_workers} workers")
    
    def set_result_callback(self, callback: Callable[[ProcessingResult], None]) -> None:
        """Set callback function for processing results"""
        self.on_result_callback = callback
    
    def start(self) -> None:
        """Start the processing pipeline"""
        if self.running:
            logger.warning("Pipeline already running")
            return
        
        logger.info("Starting processing pipeline...")
        self.running = True
        self.pause_processing = False
        self.stats['start_time'] = time.time()
        
        # Start capture thread
        self.capture_thread = threading.Thread(target=self._capture_loop, name="CaptureThread")
        self.capture_thread.daemon = True
        self.capture_thread.start()
        
        # Start worker threads
        for i in range(self.num_workers):
            thread = threading.Thread(target=self._worker_loop, name=f"WorkerThread-{i}")
            thread.daemon = True
            thread.start()
            self.worker_threads.append(thread)
        
        # Start output thread
        self.output_thread = threading.Thread(target=self._output_loop, name="OutputThread")
        self.output_thread.daemon = True
        self.output_thread.start()
        
        logger.info("Processing pipeline started")
    
    def stop(self) -> None:
        """Stop the processing pipeline"""
        if not self.running:
            return
        
        logger.info("Stopping processing pipeline...")
        self.running = False
        
        # Wait for threads to finish
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
        
        for thread in self.worker_threads:
            thread.join(timeout=2.0)
        
        if self.output_thread:
            self.output_thread.join(timeout=2.0)
        
        self.worker_threads.clear()
        self.frame_buffer.clear()
        
        # Clear queue
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break
        
        logger.info("Processing pipeline stopped")
    
    def pause(self) -> None:
        """Pause processing without stopping capture"""
        self.pause_processing = True
        logger.info("Processing paused")
    
    def resume(self) -> None:
        """Resume processing"""
        self.pause_processing = False
        logger.info("Processing resumed")
    
    def _capture_loop(self) -> None:
        """Continuous image capture loop"""
        logger.debug("Capture loop started")
        
        while self.running:
            try:
                # Capture frame
                frame = self.camera.capture()
                
                if frame.success:
                    with self.stats_lock:
                        self.stats['frames_captured'] += 1
                    
                    # Add to buffer
                    self.frame_buffer.put(frame)
                else:
                    logger.warning(f"Frame capture failed: {frame.error_message}")
                
                # Small delay to prevent CPU spinning
                time.sleep(0.001)
                
            except Exception as e:
                logger.error(f"Capture error: {e}")
                time.sleep(0.1)
        
        logger.debug("Capture loop ended")
    
    def _worker_loop(self) -> None:
        """Worker thread for processing frames"""
        logger.debug("Worker loop started")
        
        while self.running:
            try:
                # Get frame from buffer
                frame = self.frame_buffer.get(timeout=0.1)
                
                if frame is None:
                    continue
                
                if self.pause_processing:
                    # Put frame back if processing is paused
                    self.frame_buffer.put(frame)
                    time.sleep(0.01)
                    continue
                
                # Process frame
                start_time = time.time()
                
                try:
                    decode_results = self.decoder.decode(frame.image)
                    
                    processing_time = (time.time() - start_time) * 1000
                    
                    result = ProcessingResult(
                        frame_id=frame.frame_id,
                        capture_timestamp=frame.timestamp,
                        process_timestamp=time.time(),
                        decode_results=decode_results,
                        processing_time_ms=processing_time,
                        success=True
                    )
                    
                    with self.stats_lock:
                        self.stats['frames_processed'] += 1
                        self.stats['codes_found'] += len(decode_results)
                        self.stats['total_processing_time_ms'] += processing_time
                    
                    # Put result in queue
                    try:
                        self.result_queue.put(result, timeout=0.1)
                    except queue.Full:
                        logger.warning("Result queue full, dropping result")
                    
                except Exception as e:
                    logger.error(f"Processing error: {e}")
                    
                    result = ProcessingResult(
                        frame_id=frame.frame_id,
                        capture_timestamp=frame.timestamp,
                        process_timestamp=time.time(),
                        decode_results=[],
                        processing_time_ms=0,
                        success=False,
                        error_message=str(e)
                    )
                    
                    try:
                        self.result_queue.put(result, timeout=0.1)
                    except queue.Full:
                        pass
                
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(0.01)
        
        logger.debug("Worker loop ended")
    
    def _output_loop(self) -> None:
        """Output thread for handling results"""
        logger.debug("Output loop started")
        
        while self.running:
            try:
                # Get result from queue
                result = self.result_queue.get(timeout=0.1)
                
                if result is None:
                    continue
                
                # Call callback if set
                if self.on_result_callback:
                    try:
                        self.on_result_callback(result)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Output error: {e}")
                time.sleep(0.01)
        
        logger.debug("Output loop ended")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        with self.stats_lock:
            elapsed_time = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
            
            avg_processing_time = (
                self.stats['total_processing_time_ms'] / self.stats['frames_processed']
                if self.stats['frames_processed'] > 0 else 0
            )
            
            return {
                'frames_captured': self.stats['frames_captured'],
                'frames_processed': self.stats['frames_processed'],
                'codes_found': self.stats['codes_found'],
                'fps_capture': self.stats['frames_captured'] / elapsed_time if elapsed_time > 0 else 0,
                'fps_process': self.stats['frames_processed'] / elapsed_time if elapsed_time > 0 else 0,
                'avg_processing_time_ms': avg_processing_time,
                'buffer_size': self.frame_buffer.size(),
                'running': self.running,
                'paused': self.pause_processing,
                'elapsed_time_sec': elapsed_time
            }

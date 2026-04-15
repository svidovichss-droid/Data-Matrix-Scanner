#!/usr/bin/env python3
"""
Test script for Enhanced DataMatrix System
Simulates DataMatrix codes appearing on conveyor belt
"""

import sys
import time
import numpy as np
import cv2
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.camera_interface import CameraConfig, TestCamera, CapturedFrame
from src.datamatrix_decoder import DataMatrixDecoder
from src.enhanced_main import QualityAssessor, HistoryManager


class SimulatedCamera(TestCamera):
    """Test camera that generates simulated DataMatrix codes"""
    
    def __init__(self, config: CameraConfig):
        super().__init__(config)
        self.code_sequence = 0
        self.code_visible = False
        self.code_timer = 0
        self.code_interval = 2.0  # New code every 2 seconds
        
    def capture(self) -> CapturedFrame:
        """Capture frame with simulated DataMatrix codes"""
        if not self.is_open:
            return CapturedFrame(
                image=np.array([]),
                timestamp=time.time(),
                frame_id=self.frame_count,
                exposure_time=self.config.exposure_time,
                gain=self.config.gain,
                success=False,
                error_message="Camera not open"
            )
        
        # Create base image
        image = np.zeros((self.config.height, self.config.width), dtype=np.uint8)
        
        # Add gradient background
        for i in range(self.config.height):
            image[i, :] = int(50 + 50 * i / self.config.height)
        
        # Simulate DataMatrix appearance based on timing
        current_time = time.time()
        
        if not self.code_visible:
            if current_time - self.code_timer > self.code_interval:
                self.code_visible = True
                self.code_sequence += 1
                self.code_timer = current_time
        else:
            # Show code for 1.5 seconds
            if current_time - self.code_timer > 1.5:
                self.code_visible = False
        
        # Draw simulated DataMatrix (simplified pattern)
        if self.code_visible:
            self._draw_simulated_datamatrix(image, self.code_sequence)
        
        self.frame_count += 1
        
        return CapturedFrame(
            image=image,
            timestamp=time.time(),
            frame_id=self.frame_count,
            exposure_time=self.config.exposure_time,
            gain=self.config.gain,
            success=True
        )
    
    def _draw_simulated_datamatrix(self, image: np.ndarray, sequence_num: int):
        """Draw a real QR code (as DataMatrix substitute for testing)"""
        import qrcode
        
        try:
            # Generate actual QR code that pyzbar can decode
            code_data = f"PART-{sequence_num:06d}-REV-A"
            
            # Create QR code
            qr = qrcode.QRCode(
                version=5,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=4,
                border=2,
            )
            qr.add_data(code_data)
            qr.make(fit=True)
            
            # Convert to numpy array
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_array = np.array(qr_img.convert('L'))
            
            # Position in center of image
            cx, cy = self.config.width // 2, self.config.height // 2
            h, w = qr_array.shape
            
            # Calculate placement coordinates
            x_start = max(0, cx - w // 2)
            y_start = max(0, cy - h // 2)
            
            # Place QR code on the image
            image[y_start:y_start+h, x_start:x_start+w] = qr_array
            
            # Add text label below
            cv2.putText(image, code_data, (x_start, y_start + h + 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, 200, 2)
            
        except Exception as e:
            print(f"Error drawing QR code: {e}")


def run_test():
    """Run comprehensive test of the enhanced system"""
    print("=" * 70)
    print("Enhanced DataMatrix Recognition System - Test Demo")
    print("=" * 70)
    print("\nFeatures being tested:")
    print("  ✓ Instant capture and processing")
    print("  ✓ History recording (SQLite database)")
    print("  ✓ Quality assessment with grading (A-F)")
    print("  ✓ Sequential code detection on conveyor")
    print("=" * 70)
    
    # Initialize components
    config = {
        'min_size': 20,
        'max_size': 500,
        'strategy': 'balanced',
        'backend': 'zbar',
        'multiple_codes': True,
        'confidence_threshold': 0.5,
        'max_attempts': 3,
        'contrast_enhancement': True,
        'denoise': True,
        'binarization': 'adaptive'
    }
    
    decoder = DataMatrixDecoder(config)
    assessor = QualityAssessor(config)
    history = HistoryManager(db_path='test_history.db', max_entries=1000)
    
    # Setup camera
    camera_config = CameraConfig(
        camera_type='test',
        width=640,
        height=480
    )
    
    camera = SimulatedCamera(camera_config)
    camera.open()
    
    print("\nStarting simulation (10 seconds)...")
    print("DataMatrix codes will appear every ~2 seconds\n")
    
    start_time = time.time()
    detected_count = 0
    
    try:
        while time.time() - start_time < 10:
            # Capture frame
            frame = camera.capture()
            
            if frame.success:
                # Decode
                results = decoder.decode(frame.image)
                
                if results:
                    for result in results:
                        # Quality assessment
                        quality = assessor.assess(result)
                        
                        # Add to history
                        entry = history.add_entry(result, quality, frame.frame_id)
                        
                        detected_count += 1
                        
                        # Display result
                        timestamp = time.strftime('%H:%M:%S')
                        print(f"\n[{timestamp}] Code #{entry.entry_id} Detected!")
                        print(f"  Data: {result.data}")
                        print(f"  Grade: {quality.grade} (Score: {quality.overall_score:.2f})")
                        print(f"  Confidence: {result.confidence:.2f}")
                        print(f"  Decode Time: {result.decode_time_ms:.2f}ms")
                        
                        if quality.issues:
                            print(f"  Issues: {', '.join(quality.issues)}")
                
                # Small delay
                time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    # Final statistics
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    
    stats = history.get_statistics()
    print(f"\nTotal Detections: {stats['total_detections']}")
    print(f"Average Quality Score: {stats['average_quality_score']:.2f}")
    print(f"\nGrade Distribution:")
    for grade in ['A', 'B', 'C', 'D', 'F']:
        count = stats['grade_distribution'].get(grade, 0)
        bar = '█' * count
        print(f"  {grade}: {count:3d} {bar}")
    
    # Show recent entries
    print(f"\nRecent History (last 5 entries):")
    recent = history.get_recent_entries(5)
    for entry in recent:
        print(f"  #{entry.entry_id}: {entry.data} - Grade {entry.quality_assessment.grade}")
    
    # Cleanup
    camera.close()
    
    print("\n" + "=" * 70)
    print("Test completed successfully!")
    print(f"History database saved to: test_history.db")
    print("=" * 70)


if __name__ == '__main__':
    run_test()

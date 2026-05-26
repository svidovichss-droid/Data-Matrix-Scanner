"""
Example script demonstrating GoPro camera connection and usage
"""

import logging
import sys
import time

# Add src to path
sys.path.insert(0, '/workspace/conveyor_datamatrix_system/src')

from camera_interface import CameraConfig, create_camera

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def connect_gopro():
    """Connect to GoPro camera and capture frames"""
    
    # Create configuration for GoPro
    config = CameraConfig(
        camera_type='gopro',
        camera_id=0,  # USB device index (usually 0 for first camera)
        width=1920,
        height=1080,
        fps=30
    )
    
    logger.info("Creating GoPro camera instance...")
    camera = create_camera(config)
    
    logger.info("Opening GoPro camera...")
    if not camera.open():
        logger.error("Failed to open GoPro camera")
        logger.info("Make sure:")
        logger.info("  1. GoPro is connected via USB cable")
        logger.info("  2. GoPro is powered on")
        logger.info("  3. GoPro is in Webcam mode (not Media mode)")
        logger.info("  4. OpenCV is installed (pip install opencv-python)")
        return False
    
    logger.info("GoPro connected successfully!")
    logger.info(f"Camera status: connected={camera.is_connected()}")
    
    try:
        # Capture and display some frames
        logger.info("Capturing frames...")
        for i in range(5):
            frame = camera.capture()
            
            if frame.success:
                logger.info(
                    f"Frame {i+1}: "
                    f"size={frame.image.shape}, "
                    f"timestamp={frame.timestamp:.3f}, "
                    f"frame_id={frame.frame_id}"
                )
            else:
                logger.error(f"Frame {i+1} failed: {frame.error_message}")
            
            time.sleep(0.1)  # Small delay between frames
        
        # Example: Change resolution
        if hasattr(camera, 'set_resolution'):
            logger.info("Testing resolution change to 720p...")
            camera.set_resolution('720p')
            time.sleep(0.5)
            
            # Capture one more frame at new resolution
            frame = camera.capture()
            if frame.success:
                logger.info(f"New resolution frame size: {frame.image.shape}")
    
    finally:
        # Always close the camera
        logger.info("Closing GoPro camera...")
        camera.close()
        logger.info("GoPro camera closed")
    
    return True


if __name__ == '__main__':
    success = connect_gopro()
    
    if success:
        print("\n✅ GoPro connection test completed successfully!")
    else:
        print("\n❌ GoPro connection test failed!")
        print("\nTroubleshooting tips:")
        print("  • Check that GoPro is connected via USB")
        print("  • Ensure GoPro is in 'Webcam' mode (check GoPro documentation)")
        print("  • Try a different USB cable or port")
        print("  • Install required dependencies: pip install opencv-python numpy")
        sys.exit(1)

"""
Industrial Camera Interface Module

Provides unified interface for various industrial camera types
(GigE Vision, USB3 Vision, Basler, FLIR, etc.)
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass

import numpy as np


logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """Camera configuration parameters"""
    camera_type: str = 'test'
    camera_id: Any = 0
    width: int = 2448
    height: int = 2048
    pixel_format: str = 'Mono8'
    exposure_time: int = 5000  # microseconds
    gain: float = 10.0  # dB
    fps: int = 30
    trigger_enabled: bool = True
    trigger_mode: str = 'hardware'
    roi_enabled: bool = False
    roi_x: int = 0
    roi_y: int = 0
    roi_width: int = 2448
    roi_height: int = 2048


@dataclass
class CapturedFrame:
    """Represents a captured image frame"""
    image: np.ndarray
    timestamp: float
    frame_id: int
    exposure_time: int
    gain: float
    success: bool
    error_message: Optional[str] = None


class BaseCamera(ABC):
    """Abstract base class for industrial cameras"""
    
    def __init__(self, config: CameraConfig):
        self.config = config
        self.is_open = False
        self.frame_count = 0
        
    @abstractmethod
    def open(self) -> bool:
        """Initialize and open the camera"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the camera"""
        pass
    
    @abstractmethod
    def capture(self) -> CapturedFrame:
        """Capture a single frame"""
        pass
    
    @abstractmethod
    def set_exposure(self, exposure_us: int) -> bool:
        """Set exposure time in microseconds"""
        pass
    
    @abstractmethod
    def set_gain(self, gain_db: float) -> bool:
        """Set gain in dB"""
        pass
    
    def is_connected(self) -> bool:
        """Check if camera is connected and ready"""
        return self.is_open


class TestCamera(BaseCamera):
    """Test camera for development without hardware"""
    
    def __init__(self, config: CameraConfig):
        super().__init__(config)
        self.test_pattern = None
        
    def open(self) -> bool:
        """Initialize test camera"""
        logger.info("Opening test camera...")
        
        # Create a test pattern with simulated DataMatrix code area
        self.test_pattern = np.zeros((self.config.height, self.config.width), dtype=np.uint8)
        
        # Add some gradient for realism
        for i in range(self.config.height):
            self.test_pattern[i, :] = int(255 * i / self.config.height)
            
        self.is_open = True
        self.frame_count = 0
        logger.info("Test camera opened successfully")
        return True
    
    def close(self) -> None:
        """Close test camera"""
        self.is_open = False
        logger.info("Test camera closed")
    
    def capture(self) -> CapturedFrame:
        """Capture a test frame"""
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
        
        # Simulate slight variations between frames
        image = self.test_pattern.copy()
        
        # Add some noise
        noise = np.random.normal(0, 2, image.shape).astype(np.int16)
        image = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        
        self.frame_count += 1
        
        return CapturedFrame(
            image=image,
            timestamp=time.time(),
            frame_id=self.frame_count,
            exposure_time=self.config.exposure_time,
            gain=self.config.gain,
            success=True
        )
    
    def set_exposure(self, exposure_us: int) -> bool:
        """Set exposure time"""
        self.config.exposure_time = exposure_us
        logger.debug(f"Exposure set to {exposure_us} µs")
        return True
    
    def set_gain(self, gain_db: float) -> bool:
        """Set gain"""
        self.config.gain = gain_db
        logger.debug(f"Gain set to {gain_db} dB")
        return True


def create_camera(config: CameraConfig) -> BaseCamera:
    """Factory function to create appropriate camera instance"""
    
    camera_types = {
        'test': TestCamera,
        # 'basler': BaslerCamera,  # Implement when pypylon is available
        # 'flir': FLIRCamera,      # Implement when Spinnaker is available
        # 'gige': GigECamera,      # Implement using Harvesters
        # 'usb3': USB3Camera,      # Implement using Harvesters
    }
    
    camera_class = camera_types.get(config.camera_type.lower())
    
    if camera_class is None:
        raise ValueError(f"Unsupported camera type: {config.camera_type}")
    
    return camera_class(config)

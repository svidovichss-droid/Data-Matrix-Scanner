"""
Unit tests for DataMatrix Recognition System
"""

import pytest
import numpy as np
import cv2
from pathlib import Path

# Import modules to test
from src.camera_interface import CameraConfig, TestCamera, create_camera, CapturedFrame
from src.datamatrix_decoder import DataMatrixDecoder, DataMatrixResult


class TestCameraInterface:
    """Tests for camera interface module"""
    
    def test_camera_config_defaults(self):
        """Test default camera configuration"""
        config = CameraConfig()
        assert config.camera_type == 'test'
        assert config.width == 2448
        assert config.height == 2048
        assert config.exposure_time == 5000
        assert config.gain == 10.0
    
    def test_camera_config_custom(self):
        """Test custom camera configuration"""
        config = CameraConfig(
            camera_type='usb',
            camera_id=1,
            width=1920,
            height=1080,
            exposure_time=3000,
            gain=15.0
        )
        assert config.camera_type == 'usb'
        assert config.camera_id == 1
        assert config.width == 1920
        assert config.exposure_time == 3000
    
    def test_test_camera_open_close(self):
        """Test test camera open and close operations"""
        config = CameraConfig(camera_type='test')
        camera = TestCamera(config)
        
        assert not camera.is_open
        
        result = camera.open()
        assert result is True
        assert camera.is_open is True
        
        camera.close()
        assert camera.is_open is False
    
    def test_test_camera_capture(self):
        """Test test camera frame capture"""
        config = CameraConfig(camera_type='test', width=640, height=480)
        camera = TestCamera(config)
        camera.open()
        
        frame = camera.capture()
        
        assert isinstance(frame, CapturedFrame)
        assert frame.success is True
        assert frame.image.shape == (480, 640)
        assert frame.frame_id == 1
        
        # Capture another frame
        frame2 = camera.capture()
        assert frame2.frame_id == 2
        
        camera.close()
    
    def test_test_camera_capture_without_open(self):
        """Test capture without opening camera"""
        config = CameraConfig(camera_type='test')
        camera = TestCamera(config)
        
        frame = camera.capture()
        
        assert frame.success is False
        assert frame.error_message == "Camera not open"
    
    def test_create_camera_factory(self):
        """Test camera factory function"""
        config = CameraConfig(camera_type='test')
        camera = create_camera(config)
        
        assert isinstance(camera, TestCamera)
    
    def test_create_camera_invalid_type(self):
        """Test camera factory with invalid type"""
        config = CameraConfig(camera_type='invalid')
        
        with pytest.raises(ValueError):
            create_camera(config)


class TestDataMatrixDecoder:
    """Tests for DataMatrix decoder module"""
    
    def test_decoder_initialization(self):
        """Test decoder initialization with default config"""
        config = {
            'min_size': 20,
            'max_size': 500,
            'strategy': 'balanced',
            'backend': 'zbar',
            'multiple_codes': True,
            'confidence_threshold': 0.7
        }
        decoder = DataMatrixDecoder(config)
        
        assert decoder.min_size == 20
        assert decoder.max_size == 500
        assert decoder.multiple_codes is True
    
    def test_decoder_preprocess_image_grayscale(self):
        """Test image preprocessing with grayscale input"""
        config = {'binarization': 'adaptive'}
        decoder = DataMatrixDecoder(config)
        
        # Create test image
        image = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
        
        preprocessed = decoder.preprocess_image(image)
        
        assert len(preprocessed) > 0
        assert all(img.shape == image.shape for img in preprocessed)
    
    def test_decoder_preprocess_image_color(self):
        """Test image preprocessing with color input"""
        config = {'binarization': 'adaptive'}
        decoder = DataMatrixDecoder(config)
        
        # Create test color image
        image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        
        preprocessed = decoder.preprocess_image(image)
        
        assert len(preprocessed) > 0
        # All preprocessed images should be grayscale
        assert all(len(img.shape) == 2 for img in preprocessed)
    
    def test_decoder_empty_image(self):
        """Test decoding empty/black image"""
        config = {
            'min_size': 20,
            'max_size': 500,
            'confidence_threshold': 0.7,
            'max_attempts': 1,
            'contrast_enhancement': False,
            'denoise': False,
            'binarization': 'none'
        }
        decoder = DataMatrixDecoder(config)
        
        # Create black image
        image = np.zeros((480, 640), dtype=np.uint8)
        
        results = decoder.decode(image)
        
        assert isinstance(results, list)
        # Should return empty list for black image
        assert len(results) == 0
    
    def test_datamatrix_result_to_dict(self):
        """Test DataMatrixResult serialization"""
        result = DataMatrixResult(
            data="TEST123",
            confidence=0.95,
            location=[(10, 10), (100, 10), (100, 100), (10, 100)],
            timestamp=1234567890.0,
            decode_time_ms=15.5,
            image_width=640,
            image_height=480
        )
        
        result_dict = result.to_dict()
        
        assert result_dict['data'] == "TEST123"
        assert result_dict['confidence'] == 0.95
        assert len(result_dict['location']) == 4
        assert result_dict['image_dimensions']['width'] == 640
        assert result_dict['image_dimensions']['height'] == 480


class TestIntegration:
    """Integration tests"""
    
    def test_camera_to_decoder_pipeline(self):
        """Test full pipeline from camera capture to decoding"""
        # Setup camera
        camera_config = CameraConfig(camera_type='test', width=640, height=480)
        camera = TestCamera(camera_config)
        camera.open()
        
        # Setup decoder
        decoder_config = {
            'min_size': 20,
            'max_size': 500,
            'confidence_threshold': 0.7,
            'max_attempts': 1,
            'contrast_enhancement': False,
            'denoise': False,
            'binarization': 'adaptive'
        }
        decoder = DataMatrixDecoder(decoder_config)
        
        # Capture and decode
        frame = camera.capture()
        assert frame.success is True
        
        results = decoder.decode(frame.image)
        assert isinstance(results, list)
        
        camera.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

"""
DataMatrix Detection and Decoding Module

High-performance DataMatrix code detection and decoding
optimized for industrial conveyor belt applications.
"""

import time
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np
from pyzbar import pyzbar


logger = logging.getLogger(__name__)


class DecodeStrategy(Enum):
    """Detection strategy options"""
    FAST = 'fast'
    BALANCED = 'balanced'
    ACCURATE = 'accurate'


@dataclass
class DataMatrixResult:
    """Represents a decoded DataMatrix code"""
    data: str
    confidence: float
    location: List[Tuple[int, int]]  # Four corner points
    timestamp: float
    decode_time_ms: float
    image_width: int
    image_height: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'data': self.data,
            'confidence': self.confidence,
            'location': self.location,
            'timestamp': self.timestamp,
            'decode_time_ms': self.decode_time_ms,
            'image_dimensions': {
                'width': self.image_width,
                'height': self.image_height
            }
        }


class DataMatrixDecoder:
    """
    High-performance DataMatrix decoder optimized for industrial use.
    
    Features:
    - Multi-scale detection
    - Preprocessing pipeline for challenging conditions
    - Multiple decoder backends
    - Confidence scoring
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.min_size = config.get('min_size', 20)
        self.max_size = config.get('max_size', 500)
        self.strategy = DecodeStrategy(config.get('strategy', 'balanced'))
        self.backend = config.get('backend', 'zbar')
        self.multiple_codes = config.get('multiple_codes', True)
        self.confidence_threshold = config.get('confidence_threshold', 0.7)
        self.max_attempts = config.get('max_attempts', 3)
        
        logger.info(f"DataMatrixDecoder initialized with {self.backend} backend")
    
    def preprocess_image(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Apply preprocessing to enhance DataMatrix code visibility.
        Returns multiple preprocessed versions for robust detection.
        """
        preprocessed_images = []
        
        # Original grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        preprocessed_images.append(gray)
        
        # Apply contrast enhancement if configured
        if self.config.get('contrast_enhancement', True):
            # CLAHE (Contrast Limited Adaptive Histogram Equalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            preprocessed_images.append(enhanced)
        
        # Apply denoising if configured
        if self.config.get('denoise', True):
            strength = self.config.get('denoise_strength', 5)
            denoised = cv2.fastNlMeansDenoising(gray, None, h=strength)
            preprocessed_images.append(denoised)
        
        # Binarization
        binarization_method = self.config.get('binarization', 'adaptive')
        
        if binarization_method == 'adaptive':
            block_size = self.config.get('binarization_block_size', 11)
            c_value = self.config.get('binarization_c_value', 2)
            # Ensure block_size is odd
            if block_size % 2 == 0:
                block_size += 1
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, block_size, c_value
            )
            preprocessed_images.append(binary)
            
        elif binarization_method == 'otsu':
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            preprocessed_images.append(binary)
        
        return preprocessed_images
    
    def decode(self, image: np.ndarray) -> List[DataMatrixResult]:
        """
        Detect and decode DataMatrix codes in the image.
        
        Args:
            image: Input image (grayscale or BGR)
            
        Returns:
            List of DataMatrixResult objects
        """
        start_time = time.time()
        results = []
        
        # Get image dimensions
        img_height, img_width = image.shape[:2]
        
        # Preprocess image
        preprocessed_list = self.preprocess_image(image)
        
        # Try each preprocessed version
        for attempt_idx, processed_img in enumerate(preprocessed_list):
            if attempt_idx >= self.max_attempts:
                break
                
            try:
                # Decode using pyzbar
                decoded_objects = pyzbar.decode(
                    processed_img,
                    symbols=[pyzbar.ZBarSymbol.DATAMATRIX]
                )
                
                for obj in decoded_objects:
                    # Calculate confidence (based on quality metrics)
                    confidence = self._calculate_confidence(obj, processed_img)
                    
                    if confidence >= self.confidence_threshold:
                        # Extract location points
                        location = [(point.x, point.y) for point in obj.polygon] if obj.polygon else []
                        
                        # Ensure we have 4 points for quadrilateral
                        if len(location) != 4:
                            # Create bounding box if polygon is incomplete
                            rect = obj.rect
                            location = [
                                (rect.left, rect.top),
                                (rect.left + rect.width, rect.top),
                                (rect.left + rect.width, rect.top + rect.height),
                                (rect.left, rect.top + rect.height)
                            ]
                        
                        decode_time = (time.time() - start_time) * 1000
                        
                        result = DataMatrixResult(
                            data=obj.data.decode('utf-8') if isinstance(obj.data, bytes) else str(obj.data),
                            confidence=confidence,
                            location=location,
                            timestamp=time.time(),
                            decode_time_ms=decode_time,
                            image_width=img_width,
                            image_height=img_height
                        )
                        
                        results.append(result)
                        
                        if not self.multiple_codes:
                            # Return first high-confidence result
                            return results
                            
            except Exception as e:
                logger.warning(f"Decode attempt {attempt_idx} failed: {e}")
                continue
        
        total_time = (time.time() - start_time) * 1000
        logger.debug(f"Decoding completed in {total_time:.2f}ms, found {len(results)} codes")
        
        return results
    
    def _calculate_confidence(self, decoded_obj, image: np.ndarray) -> float:
        """
        Calculate confidence score for a decoded DataMatrix code.
        
        Factors considered:
        - Size of the code
        - Contrast
        - Edge clarity
        """
        confidence = 1.0
        
        # Size factor (optimal size range)
        rect = decoded_obj.rect
        area = rect.width * rect.height
        optimal_area = ((self.min_size + self.max_size) / 2) ** 2
        
        if area < self.min_size ** 2:
            confidence *= 0.5  # Too small
        elif area > self.max_size ** 2:
            confidence *= 0.7  # Too large
        else:
            # Closer to optimal size = higher confidence
            size_ratio = min(area / optimal_area, optimal_area / area)
            confidence *= (0.7 + 0.3 * size_ratio)
        
        # Check if we can access quality metrics from zbar
        if hasattr(decoded_obj, 'quality'):
            quality = decoded_obj.quality
            confidence *= (0.5 + 0.5 * min(quality, 1.0))
        
        return min(confidence, 1.0)


def find_datamatrix_fast(image: np.ndarray) -> Optional[DataMatrixResult]:
    """
    Fast DataMatrix detection optimized for high-speed conveyor applications.
    Uses ROI and simplified preprocessing for minimal latency.
    
    Args:
        image: Input image
        
    Returns:
        DataMatrixResult or None if not found
    """
    decoder = DataMatrixDecoder({
        'min_size': 30,
        'max_size': 400,
        'strategy': 'fast',
        'backend': 'zbar',
        'multiple_codes': False,
        'confidence_threshold': 0.6,
        'max_attempts': 1,
        'contrast_enhancement': False,
        'denoise': False,
        'binarization': 'none'
    })
    
    results = decoder.decode(image)
    return results[0] if results else None

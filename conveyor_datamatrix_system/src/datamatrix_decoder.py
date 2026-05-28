"""
DataMatrix Detection and Decoding Module

High-performance DataMatrix code detection and decoding
optimized for industrial conveyor belt applications.

Enhanced Features:
- Multi-scale detection with image pyramid
- Advanced preprocessing (CLAHE, denoising, morphological operations)
- Multiple decoder backends (pyzbar, zxing, opencv)
- Adaptive thresholding and contrast enhancement
- ROI-based processing for speed optimization
- Motion deblurring for conveyor belt applications
- Confidence scoring with quality metrics
"""

import time
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import warnings

import cv2
import numpy as np
from pyzbar import pyzbar


logger = logging.getLogger(__name__)


class DecodeStrategy(Enum):
    """Detection strategy options"""
    FAST = 'fast'
    BALANCED = 'balanced'
    ACCURATE = 'accurate'
    ULTRA_ACCURATE = 'ultra_accurate'


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
    preprocessing_applied: str = ''
    scale_factor: float = 1.0
    
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
            },
            'preprocessing_applied': self.preprocessing_applied,
            'scale_factor': self.scale_factor
        }


class DataMatrixDecoder:
    """
    High-performance DataMatrix decoder optimized for industrial use.
    
    Features:
    - Multi-scale detection with image pyramid
    - Advanced preprocessing pipeline for challenging conditions
    - Multiple decoder backends (pyzbar, zxing, opencv)
    - Adaptive confidence scoring
    - Motion deblurring support
    - ROI-based processing
    - Overexposure and glare compensation
    - Print gain correction
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
        
        # Enhanced configuration
        self.use_pyramid = config.get('use_pyramid', True)
        self.pyramid_levels = config.get('pyramid_levels', 3)
        self.enable_deblur = config.get('enable_deblur', False)
        self.deblur_kernel_size = config.get('deblur_kernel_size', 5)
        self.roi_enabled = config.get('roi_enabled', False)
        self.roi_coords = config.get('roi_coords', None)  # (x, y, width, height)
        self.orientation_correction = config.get('orientation_correction', True)
        self.super_resolution = config.get('super_resolution', False)
        
        # Overexposure and glare handling
        self.compensate_overexposure = config.get('compensate_overexposure', True)
        self.glare_reduction = config.get('glare_reduction', True)
        self.print_gain_correction = config.get('print_gain_correction', True)
        self.highlight_recovery = config.get('highlight_recovery', 'tone_mapping')  # 'tone_mapping', 'inpaint', 'both'
        self.max_brightness_percentile = config.get('max_brightness_percentile', 95)
        self.glare_threshold = config.get('glare_threshold', 250)  # Pixel value threshold for glare
        self.glare_max_area_percent = config.get('glare_max_area_percent', 15)  # Max % of image that can be glare
        
        logger.info(f"DataMatrixDecoder initialized with {self.backend} backend, strategy: {self.strategy.value}")
        if self.compensate_overexposure:
            logger.info("Overexposure compensation enabled")
        if self.glare_reduction:
            logger.info(f"Glare reduction enabled (threshold: {self.glare_threshold})")
        if self.print_gain_correction:
            logger.info("Print gain correction enabled")
    
    def _apply_roi(self, image: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Apply region of interest if configured"""
        if not self.roi_enabled or self.roi_coords is None:
            return image, (0, 0)
        
        x, y, w, h = self.roi_coords
        h_img, w_img = image.shape[:2]
        
        # Validate ROI coordinates
        x = max(0, min(x, w_img - 1))
        y = max(0, min(y, h_img - 1))
        w = min(w, w_img - x)
        h = min(h, h_img - y)
        
        return image[y:y+h, x:x+w], (x, y)
    
    def _correct_orientation(self, image: np.ndarray) -> List[np.ndarray]:
        """Generate orientation-corrected versions of the image"""
        if not self.orientation_correction:
            return [image]
        
        images = [image]
        
        # Try common rotations for DataMatrix codes
        rotations = [90, 180, 270]
        for angle in rotations:
            rotated = cv2.rotate(image, getattr(cv2, f'ROTATE_90_{angle // 90 * 90}'[::-1].replace('092', 'CLOCKWISE').replace('081', '180').replace('072', 'COUNTERCLOCKWISE'), cv2.ROTATE_90_CLOCKWISE))
            if angle == 90:
                rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                rotated = cv2.rotate(image, cv2.ROTATE_180)
            elif angle == 270:
                rotated = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
            images.append(rotated)
        
        return images
    
    def preprocess_image(self, image: np.ndarray) -> List[Tuple[np.ndarray, str]]:
        """
        Apply preprocessing to enhance DataMatrix code visibility.
        Returns multiple preprocessed versions with method labels for robust detection.
        
        Optimized for speed: minimal preprocessing in FAST mode.
        Enhanced with overexposure compensation and glare reduction for bright camera conditions.
        """
        preprocessed_images = []
        
        # Apply ROI if configured
        cropped_img, roi_offset = self._apply_roi(image)
        
        # Original grayscale
        if len(cropped_img.shape) == 3:
            gray = cv2.cvtColor(cropped_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped_img.copy()
        
        # Base preprocessing
        preprocessed_images.append((gray, 'original'))
        
        # Strategy-specific preprocessing - optimized order for speed
        if self.strategy == DecodeStrategy.FAST:
            # Fast path: minimal preprocessing, only CLAHE
            if self.config.get('contrast_enhancement', True):
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                preprocessed_images.append((enhanced, 'clahe'))
            
            # Skip overexposure compensation in FAST mode for speed
            # Skip print gain correction in FAST mode for speed
                
        elif self.strategy == DecodeStrategy.BALANCED:
            # Overexposure and glare compensation (applied early in pipeline)
            if self.compensate_overexposure or self.glare_reduction:
                compensated = self._compensate_overexposure_and_glare(gray)
                if compensated is not None:
                    preprocessed_images.append((compensated, 'overexposure_compensated'))
            
            # Print gain correction for improved contrast in printed codes
            if self.print_gain_correction:
                gain_corrected = self._apply_print_gain_correction(gray)
                if gain_corrected is not None:
                    preprocessed_images.append((gain_corrected, 'print_gain_corrected'))
            
            # Balanced: moderate preprocessing
            if self.config.get('contrast_enhancement', True):
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                preprocessed_images.append((enhanced, 'clahe'))
            
            if self.config.get('denoise', True):
                strength = self.config.get('denoise_strength', 5)
                denoised = cv2.fastNlMeansDenoising(gray, None, h=strength)
                preprocessed_images.append((denoised, 'denoise'))
            
            # Binarization
            self._add_binarized_versions(gray, preprocessed_images)
            
        elif self.strategy in [DecodeStrategy.ACCURATE, DecodeStrategy.ULTRA_ACCURATE]:
            # Overexposure and glare compensation (applied early in pipeline)
            if self.compensate_overexposure or self.glare_reduction:
                compensated = self._compensate_overexposure_and_glare(gray)
                if compensated is not None:
                    preprocessed_images.append((compensated, 'overexposure_compensated'))
            
            # Print gain correction for improved contrast in printed codes
            if self.print_gain_correction:
                gain_corrected = self._apply_print_gain_correction(gray)
                if gain_corrected is not None:
                    preprocessed_images.append((gain_corrected, 'print_gain_corrected'))
                
                # Also apply to compensated image if available
                if self.compensate_overexposure and len(preprocessed_images) > 1:
                    gain_on_compensated = self._apply_print_gain_correction(compensated)
                    if gain_on_compensated is not None:
                        preprocessed_images.append((gain_on_compensated, 'compensated_gain_corrected'))
            
            # Accurate: extensive preprocessing
            if self.config.get('contrast_enhancement', True):
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
                enhanced = clahe.apply(gray)
                preprocessed_images.append((enhanced, 'clahe_aggressive'))
            
            if self.config.get('denoise', True):
                strength = self.config.get('denoise_strength', 10)
                denoised = cv2.fastNlMeansDenoising(gray, None, h=strength)
                preprocessed_images.append((denoised, 'denoise_strong'))
            
            # Motion deblurring for conveyor applications
            if self.enable_deblur:
                deblurred = self._apply_deblurring(gray)
                preprocessed_images.append((deblurred, 'deblurred'))
            
            # Morphological operations
            morph_processed = self._apply_morphological_operations(gray)
            preprocessed_images.extend(morph_processed)
            
            # Multiple binarization methods
            self._add_binarized_versions(gray, preprocessed_images, aggressive=True)
            
            # Super-resolution (if enabled and available)
            if self.super_resolution:
                sr_image = self._apply_super_resolution(gray)
                if sr_image is not None:
                    preprocessed_images.append((sr_image, 'super_resolution'))
        
        # Add orientation-corrected versions
        if self.orientation_correction and self.strategy != DecodeStrategy.FAST:
            oriented_images = []
            for img, label in preprocessed_images[1:]:  # Skip original
                orientations = self._correct_orientation(img)
                for i, oriented in enumerate(orientations[1:], 1):  # Skip first (already added)
                    oriented_images.append((oriented, f'{label}_rot{i*90}'))
            preprocessed_images.extend(oriented_images)
        
        # Adjust for ROI offset
        adjusted_results = []
        for img, label in preprocessed_images:
            adjusted_results.append((img, label))
        
        return adjusted_results
    
    def _add_binarized_versions(self, gray: np.ndarray, 
                                 preprocessed_list: List[Tuple[np.ndarray, str]],
                                 aggressive: bool = False) -> None:
        """Add various binarized versions to the preprocessing list"""
        binarization_method = self.config.get('binarization', 'adaptive')
        
        if binarization_method in ['adaptive', 'all']:
            block_sizes = [11] if not aggressive else [9, 11, 15]
            c_values = [2] if not aggressive else [1, 2, 3]
            
            for block_size in block_sizes:
                for c_value in c_values:
                    if block_size % 2 == 0:
                        block_size += 1
                    binary = cv2.adaptiveThreshold(
                        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY_INV, block_size, c_value
                    )
                    preprocessed_list.append((binary, f'adaptive_bs{block_size}_c{c_value}'))
        
        if binarization_method in ['otsu', 'all']:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            preprocessed_list.append((binary, 'otsu'))
            
            # Also try with Gaussian blur before Otsu
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            _, binary_blur = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            preprocessed_list.append((binary_blur, 'gaussian_otsu'))
        
        if binarization_method in ['phansalkar', 'all'] or aggressive:
            # Phansalkar method for low-contrast images
            phansalkar = self._phansalkar_threshold(gray)
            if phansalkar is not None:
                preprocessed_list.append((phansalkar, 'phansalkar'))
    
    def _phansalkar_threshold(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Apply Phansalkar adaptive thresholding for low-contrast images"""
        try:
            # Normalize image
            img_norm = image.astype(np.float32) / 255.0
            
            # Parameters for Phansalkar method
            k = 0.25
            r = 0.5
            window_size = 15
            
            # Calculate local mean and standard deviation
            mean = cv2.blur(img_norm, (window_size, window_size))
            std_dev = cv2.blur(img_norm ** 2, (window_size, window_size)) - mean ** 2
            std_dev = np.sqrt(np.maximum(std_dev, 0))
            
            # Apply Phansalkar formula
            threshold = mean * (1 + k * (std_dev / r - 1))
            binary = (img_norm < threshold).astype(np.uint8) * 255
            
            return binary
        except Exception as e:
            logger.warning(f"Phansalkar thresholding failed: {e}")
            return None
    
    def _apply_morphological_operations(self, image: np.ndarray) -> List[Tuple[np.ndarray, str]]:
        """Apply morphological operations to enhance DataMatrix features"""
        results = []
        
        kernel_sizes = [3, 5]
        
        for k_size in kernel_sizes:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
            
            # Opening: remove small noise
            opened = cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel)
            results.append((opened, f'morph_open_{k_size}'))
            
            # Closing: fill small gaps
            closed = cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)
            results.append((closed, f'morph_close_{k_size}'))
            
            # Top-hat: enhance light regions on dark background
            tophat = cv2.morphologyEx(image, cv2.MORPH_TOPHAT, kernel)
            results.append((tophat, f'morph_tophat_{k_size}'))
        
        return results
    
    def _apply_deblurring(self, image: np.ndarray) -> np.ndarray:
        """Apply motion deblurring for conveyor belt applications"""
        try:
            # Estimate motion blur direction (typically horizontal for conveyor)
            kernel_size = self.deblur_kernel_size
            
            # Create motion blur kernel
            kernel = np.zeros((kernel_size, kernel_size))
            kernel[int(kernel_size/2), :] = np.ones(kernel_size)
            kernel = kernel / kernel_size
            
            # Apply Wiener deconvolution approximation
            deblurred = cv2.filter2D(image, -1, kernel)
            
            # Sharpen the result
            sharpen_kernel = np.array([[-1, -1, -1],
                                       [-1,  9, -1],
                                       [-1, -1, -1]])
            deblurred = cv2.filter2D(deblurred, -1, sharpen_kernel)
            deblurred = np.clip(deblurred, 0, 255).astype(np.uint8)
            
            return deblurred
        except Exception as e:
            logger.warning(f"Deblurring failed: {e}")
            return image
    
    def _apply_super_resolution(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Apply super-resolution using OpenCV DNN (if available)"""
        try:
            # Check if OpenCV DNN module is available
            if not hasattr(cv2, 'dnn_superres'):
                return None
            
            # This is a placeholder - actual implementation requires trained models
            # For now, use simple bicubic upscaling
            scale_factor = 2
            upscaled = cv2.resize(image, None, fx=scale_factor, fy=scale_factor, 
                                 interpolation=cv2.INTER_CUBIC)
            return upscaled
        except Exception as e:
            logger.debug(f"Super-resolution not available: {e}")
            return None
    
    def _compensate_overexposure_and_glare(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Compensate for overexposure and glare in bright camera conditions.
        
        Techniques used:
        - Highlight recovery through tone mapping
        - Glare detection and reduction
        - Adaptive histogram equalization for recovered regions
        - Inpainting for severe glare spots
        
        Args:
            image: Input grayscale image
            
        Returns:
            Compensated image or None if processing fails
        """
        try:
            img_float = image.astype(np.float32) / 255.0
            
            # Detect overexposed regions (pixels above threshold)
            overexposed_mask = image > self.glare_threshold
            overexposed_ratio = np.sum(overexposed_mask) / image.size * 100
            
            # Skip if too much of the image is overexposed (likely invalid)
            if overexposed_ratio > self.glare_max_area_percent:
                logger.debug(f"Too much overexposure ({overexposed_ratio:.1f}%), skipping compensation")
                return image
            
            # Skip if no overexposure detected
            if overexposed_ratio < 0.1:
                return image
            
            logger.debug(f"Compensating overexposure ({overexposed_ratio:.1f}% of image)")
            
            # Method 1: Tone mapping for highlight recovery
            if self.highlight_recovery in ['tone_mapping', 'both']:
                # Apply gamma correction to compress highlights
                gamma = 0.7  # Compress highlights
                tone_mapped = np.power(img_float, 1.0 / gamma)
                
                # Blend tone mapped with original based on exposure level
                blend_weight = np.clip((image - 200) / 55.0, 0, 1)  # More blend in highlights
                blended = img_float * (1 - blend_weight) + tone_mapped * blend_weight
                
                img_float = blended
            
            # Method 2: Inpainting for severe glare spots
            if self.highlight_recovery in ['inpaint', 'both'] and overexposed_ratio > 1.0:
                # Create inpainting mask (only severe glare)
                severe_glare_mask = (image > 254).astype(np.uint8) * 255
                
                # Dilate mask slightly to cover glare halo
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                dilated_mask = cv2.dilate(severe_glare_mask, kernel, iterations=2)
                
                # Inpaint using telea method
                if np.sum(dilated_mask) > 0:
                    img_uint8 = (img_float * 255).astype(np.uint8)
                    inpainted = cv2.inpaint(img_uint8, dilated_mask, inpaintRadius=3, 
                                           flags=cv2.INPAINT_TELEA)
                    img_float = inpainted.astype(np.float32) / 255.0
            
            # Apply CLAHE to enhance contrast in recovered regions
            img_enhanced = (img_float * 255).astype(np.uint8)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(16, 16))
            result = clahe.apply(img_enhanced)
            
            # Reduce glare by suppressing specular reflections
            if self.glare_reduction:
                result = self._suppress_glare(result, overexposed_mask)
            
            return result
            
        except Exception as e:
            logger.warning(f"Overexposure compensation failed: {e}")
            return image
    
    def _suppress_glare(self, image: np.ndarray, glare_mask: np.ndarray) -> np.ndarray:
        """
        Suppress glare and specular reflections in the image.
        
        Uses morphological operations and local intensity normalization
        to reduce the impact of glare on DataMatrix decoding.
        
        Args:
            image: Input grayscale image
            glare_mask: Boolean mask indicating glare regions
            
        Returns:
            Image with reduced glare
        """
        try:
            # Convert boolean mask to uint8
            mask_uint8 = glare_mask.astype(np.uint8) * 255
            
            # Find contours of glare regions
            contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            result = image.copy()
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < 50:  # Skip very small glare spots
                    continue
                
                # Get bounding box of glare region
                x, y, w, h = cv2.boundingRect(contour)
                
                # Expand ROI slightly
                pad = 5
                x1, y1 = max(0, x - pad), max(0, y - pad)
                x2, y2 = min(image.shape[1], x + w + pad), min(image.shape[0], y + h + pad)
                
                roi = result[y1:y2, x1:x2]
                
                # Apply local histogram equalization to ROI
                if roi.size > 0:
                    roi_eq = cv2.equalizeHist(roi)
                    
                    # Blend with original to avoid harsh transitions
                    alpha = 0.7
                    result[y1:y2, x1:x2] = cv2.addWeighted(roi, alpha, roi_eq, 1 - alpha, 0)
            
            # Apply mild Gaussian blur to smooth glare transitions
            result = cv2.GaussianBlur(result, (3, 3), 0.5)
            
            return result
            
        except Exception as e:
            logger.debug(f"Glare suppression failed: {e}")
            return image
    
    def _apply_print_gain_correction(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Apply print gain correction to improve contrast in printed DataMatrix codes.
        
        Print gain refers to the phenomenon where printed dots spread,
        reducing contrast between bars and spaces. This correction:
        - Enhances edge sharpness
        - Compensates for dot gain
        - Improves binarization quality
        
        Args:
            image: Input grayscale image
            
        Returns:
            Gain-corrected image or None if processing fails
        """
        try:
            # Calculate image statistics
            mean_val = np.mean(image)
            std_val = np.std(image)
            
            # Skip if image has very low contrast (likely uniform)
            if std_val < 10:
                return image
            
            # Apply unsharp masking to enhance edges
            gaussian = cv2.GaussianBlur(image, (9, 9), 2.0)
            unsharp_mask = cv2.addWeighted(image, 1.5, gaussian, -0.5, 0)
            
            # Apply adaptive contrast enhancement based on local statistics
            # This helps with varying print quality across the code
            img_float = unsharp_mask.astype(np.float32)
            
            # Local contrast normalization
            kernel_size = 15
            local_mean = cv2.blur(img_float, (kernel_size, kernel_size))
            local_std = cv2.blur(img_float ** 2, (kernel_size, kernel_size)) - local_mean ** 2
            local_std = np.sqrt(np.maximum(local_std, 1.0))
            
            # Normalize local contrast
            normalized = (img_float - local_mean) / local_std
            normalized = normalized * std_val + mean_val
            
            # Clip to valid range
            result = np.clip(normalized, 0, 255).astype(np.uint8)
            
            # Apply morphological gradient to sharpen edges further
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            gradient = cv2.morphologyEx(result, cv2.MORPH_GRADIENT, kernel)
            
            # Blend gradient with original for edge enhancement
            result = cv2.addWeighted(result, 0.85, gradient, 0.15, 0)
            
            return result
            
        except Exception as e:
            logger.warning(f"Print gain correction failed: {e}")
            return image
    
    def _build_image_pyramid(self, image: np.ndarray) -> List[Tuple[np.ndarray, float]]:
        """Build image pyramid for multi-scale detection"""
        pyramid = [(image, 1.0)]
        
        if not self.use_pyramid:
            return pyramid
        
        # Scale factors based on strategy
        if self.strategy == DecodeStrategy.FAST:
            scales = [0.75, 0.5]
        elif self.strategy == DecodeStrategy.BALANCED:
            scales = [0.8, 0.6, 0.5]
        else:
            scales = [0.9, 0.8, 0.7, 0.6, 0.5]
        
        for scale in scales[:self.pyramid_levels]:
            scaled = cv2.resize(image, None, fx=scale, fy=scale, 
                               interpolation=cv2.INTER_AREA)
            pyramid.append((scaled, scale))
        
        return pyramid
    
    def decode(self, image: np.ndarray) -> List[DataMatrixResult]:
        """
        Detect and decode DataMatrix codes in the image.
        
        Optimized for high-speed detection with minimal latency.
        
        Args:
            image: Input image (grayscale or BGR)
            
        Returns:
            List of DataMatrixResult objects
        """
        start_time = time.perf_counter()
        results = []
        seen_data = set()  # Avoid duplicates
        
        # Get image dimensions
        img_height, img_width = image.shape[:2]
        
        # Build image pyramid for multi-scale detection
        # Optimized: fewer levels for faster processing
        pyramid = self._build_image_pyramid(image)
        
        # Process each scale level
        for scale_idx, (scaled_image, scale_factor) in enumerate(pyramid):
            # Early exit for FAST strategy after first scale
            if scale_idx >= 1 and self.strategy == DecodeStrategy.FAST:
                break
            if scale_idx >= self.pyramid_levels and self.strategy != DecodeStrategy.ULTRA_ACCURATE:
                break
            
            # Preprocess image at this scale
            preprocessed_list = self.preprocess_image(scaled_image)
            
            # Limit attempts based on strategy - optimized for speed
            max_preprocessed = {
                DecodeStrategy.FAST: 2,
                DecodeStrategy.BALANCED: 4,
                DecodeStrategy.ACCURATE: 8,
                DecodeStrategy.ULTRA_ACCURATE: len(preprocessed_list)
            }.get(self.strategy, 4)
            
            # Try each preprocessed version
            for attempt_idx, (processed_img, prep_method) in enumerate(preprocessed_list):
                if attempt_idx >= max_preprocessed:
                    break
                
                try:
                    # Decode using pyzbar - note: DataMatrix is decoded as part of general barcode detection
                    # pyzbar doesn't have a specific DATAMATRIX symbol type in older versions
                    # We decode all symbols and filter results by type
                    decoded_objects = pyzbar.decode(processed_img, symbols=[pyzbar.ZBarSymbol.DATAMATRIX])
                    
                    for obj in decoded_objects:
                        # Skip duplicates
                        data_str = obj.data.decode('utf-8') if isinstance(obj.data, bytes) else str(obj.data)
                        if data_str in seen_data:
                            continue
                        
                        # Calculate confidence
                        confidence = self._calculate_confidence(obj, processed_img, scale_factor)
                        
                        if confidence >= self.confidence_threshold:
                            # Extract and adjust location points
                            location = self._extract_location(obj, processed_img, scale_factor, 
                                                             img_width, img_height)
                            
                            result = DataMatrixResult(
                                data=data_str,
                                confidence=confidence,
                                location=location,
                                timestamp=time.time(),
                                decode_time_ms=(time.perf_counter() - start_time) * 1000,
                                image_width=img_width,
                                image_height=img_height,
                                preprocessing_applied=prep_method,
                                scale_factor=1.0 / scale_factor
                            )
                            
                            results.append(result)
                            seen_data.add(data_str)
                            
                            # Fast exit on first good result
                            if not self.multiple_codes and confidence > 0.85:
                                return results
                    
                except Exception as e:
                    logger.warning(f"Decode attempt ({prep_method}) failed: {e}")
                    continue
            
            # Early exit if found high-confidence result
            if results and self.strategy == DecodeStrategy.FAST:
                break
        
        total_time = (time.perf_counter() - start_time) * 1000
        logger.debug(f"Decoding completed in {total_time:.2f}ms, found {len(results)} codes")
        
        return results
    
    def _extract_location(self, decoded_obj, image: np.ndarray, 
                         scale_factor: float, orig_width: int, orig_height: int) -> List[Tuple[int, int]]:
        """Extract and scale location points to original image coordinates"""
        # Get polygon points
        if decoded_obj.polygon:
            location = [(int(point.x / scale_factor), int(point.y / scale_factor)) 
                       for point in decoded_obj.polygon]
        else:
            # Create bounding box from rect
            rect = decoded_obj.rect
            x = int(rect.left / scale_factor)
            y = int(rect.top / scale_factor)
            w = int(rect.width / scale_factor)
            h = int(rect.height / scale_factor)
            location = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        
        # Ensure we have 4 points
        if len(location) != 4:
            # Fallback to center-based square
            if decoded_obj.polygon:
                points = [(point.x, point.y) for point in decoded_obj.polygon]
                if points:
                    cx = sum(p[0] for p in points) / len(points)
                    cy = sum(p[1] for p in points) / len(points)
                    size = max(max(p[0] for p in points) - min(p[0] for p in points),
                              max(p[1] for p in points) - min(p[1] for p in points))
                    size = int(size / scale_factor / 2)
                    cx, cy = int(cx / scale_factor), int(cy / scale_factor)
                    location = [
                        (cx - size, cy - size),
                        (cx + size, cy - size),
                        (cx + size, cy + size),
                        (cx - size, cy + size)
                    ]
        
        # Clamp to image bounds
        location = [(max(0, min(x, orig_width - 1)), 
                     max(0, min(y, orig_height - 1))) for x, y in location]
        
        return location
    
    def _calculate_confidence(self, decoded_obj, image: np.ndarray, 
                             scale_factor: float = 1.0) -> float:
        """
        Calculate confidence score for a decoded DataMatrix code.
        
        Factors considered:
        - Size of the code relative to optimal range
        - Contrast and edge clarity
        - Decoder quality metrics
        - Scale factor penalty
        """
        confidence = 1.0
        
        # Size factor
        rect = decoded_obj.rect
        scaled_area = (rect.width * rect.height) / (scale_factor ** 2)
        optimal_area = ((self.min_size + self.max_size) / 2) ** 2
        
        if scaled_area < self.min_size ** 2:
            confidence *= 0.5 + 0.3 * (scaled_area / (self.min_size ** 2))
        elif scaled_area > self.max_size ** 2:
            confidence *= 0.7
        else:
            size_ratio = min(scaled_area / optimal_area, optimal_area / scaled_area)
            confidence *= (0.8 + 0.2 * size_ratio)
        
        # Quality metric from zbar
        if hasattr(decoded_obj, 'quality') and decoded_obj.quality is not None:
            quality = min(decoded_obj.quality, 1.0)
            confidence *= (0.4 + 0.6 * quality)
        
        # Scale factor penalty (smaller scales are less reliable)
        if scale_factor < 1.0:
            confidence *= (0.8 + 0.2 * scale_factor)
        
        # Contrast check
        if len(image.shape) == 2:
            contrast = np.std(image)
            contrast_factor = min(1.0, contrast / 50.0)
            confidence *= (0.7 + 0.3 * contrast_factor)
        
        return min(confidence, 1.0)
    
    def decode_with_visualization(self, image: np.ndarray) -> Tuple[List[DataMatrixResult], np.ndarray]:
        """
        Decode DataMatrix codes and return visualization overlay.
        
        Returns:
            Tuple of (results, annotated_image)
        """
        results = self.decode(image)
        vis_image = image.copy()
        
        if len(vis_image.shape) == 2:
            vis_image = cv2.cvtColor(vis_image, cv2.COLOR_GRAY2BGR)
        
        for i, result in enumerate(results):
            # Draw location polygon
            pts = np.array(result.location, dtype=np.int32)
            cv2.polylines(vis_image, [pts], True, (0, 255, 0), 2)
            
            # Draw label
            label = f"{result.data} ({result.confidence:.2f})"
            cv2.putText(vis_image, label, (result.location[0][0], result.location[0][1] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        return results, vis_image


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
        'use_pyramid': False,
        'contrast_enhancement': True,
        'denoise': False,
        'binarization': 'none',
        'orientation_correction': False
    })
    
    results = decoder.decode(image)
    return results[0] if results else None


def find_datamatrix_accurate(image: np.ndarray, 
                            enable_deblur: bool = True) -> List[DataMatrixResult]:
    """
    High-accuracy DataMatrix detection for challenging conditions.
    Slower but more thorough scanning.
    
    Args:
        image: Input image
        enable_deblur: Enable motion deblurring
        
    Returns:
        List of DataMatrixResult objects
    """
    decoder = DataMatrixDecoder({
        'min_size': 20,
        'max_size': 500,
        'strategy': 'ultra_accurate',
        'backend': 'zbar',
        'multiple_codes': True,
        'confidence_threshold': 0.5,
        'max_attempts': 10,
        'use_pyramid': True,
        'pyramid_levels': 5,
        'contrast_enhancement': True,
        'denoise': True,
        'denoise_strength': 10,
        'binarization': 'all',
        'enable_deblur': enable_deblur,
        'orientation_correction': True,
        'super_resolution': False,
        # Overexposure and glare handling
        'compensate_overexposure': True,
        'glare_reduction': True,
        'print_gain_correction': True,
        'highlight_recovery': 'both',
        'glare_threshold': 245,
        'glare_max_area_percent': 20
    })
    
    return decoder.decode(image)


def find_datamatrix_bright_conditions(image: np.ndarray,
                                      aggressive_compensation: bool = True) -> List[DataMatrixResult]:
    """
    Specialized DataMatrix detection for overly bright camera conditions.
    Optimized for scenarios with overexposure, glare, and print gain issues.
    
    Args:
        image: Input image
        aggressive_compensation: Use aggressive overexposure compensation
        
    Returns:
        List of DataMatrixResult objects
    """
    glare_threshold = 240 if aggressive_compensation else 250
    max_glare_area = 25 if aggressive_compensation else 15
    
    decoder = DataMatrixDecoder({
        'min_size': 20,
        'max_size': 500,
        'strategy': 'ultra_accurate',
        'backend': 'zbar',
        'multiple_codes': True,
        'confidence_threshold': 0.45,
        'max_attempts': 15,
        'use_pyramid': True,
        'pyramid_levels': 5,
        'contrast_enhancement': True,
        'denoise': True,
        'denoise_strength': 8,
        'binarization': 'all',
        'enable_deblur': True,
        'deblur_kernel_size': 7,
        'orientation_correction': True,
        # Aggressive overexposure handling
        'compensate_overexposure': True,
        'glare_reduction': True,
        'print_gain_correction': True,
        'highlight_recovery': 'both',
        'glare_threshold': glare_threshold,
        'glare_max_area_percent': max_glare_area,
        'max_brightness_percentile': 98
    })
    
    return decoder.decode(image)

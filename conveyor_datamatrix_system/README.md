# Industrial DataMatrix Recognition System for Conveyor Belt

## Overview
This system provides real-time DataMatrix code detection and decoding for industrial conveyor belt applications using high-speed industrial cameras.

## Features
- **Instant Capture**: Optimized for minimal latency image acquisition
- **High-Speed Processing**: Multi-threaded pipeline for continuous flow processing
- **Industrial Camera Support**: Compatible with GigE Vision, USB3 Vision cameras
- **Robust Decoding**: Handles damaged, low-contrast, and distorted codes
- **Real-time Output**: Immediate results with timestamp and metadata

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   Camera    │ -> │ Image Buffer │ -> │  Detector   │ -> │   Decoder    │
│ (Industrial)│    │  (Ring Buf)  │    │ (DataMatrix)│    │ (ZBar/ZXing) │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
       |                                                        |
       v                                                        v
┌─────────────┐                                          ┌──────────────┐
│   Trigger   │                                          │   Results    │
│  (Sensor)   │                                          │  (Output)    │
└─────────────┘                                          └──────────────┘
```

## Requirements

### Hardware
- Industrial camera (Basler, FLIR, IDS, etc.) with global shutter
- External trigger sensor (photoelectric sensor recommended)
- Adequate lighting (strobe or continuous)
- Minimum: Intel i7/Ryzen 7, 16GB RAM, SSD

### Software Dependencies
```bash
pip install -r requirements.txt
```

## Installation

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure camera settings in `config/camera_config.yaml`
4. Run: `python src/main.py`

## Configuration

Edit `config/camera_config.yaml` to set:
- Camera exposure time
- Gain settings
- Trigger mode
- ROI (Region of Interest)
- Network settings (for GigE cameras)

## Usage

```bash
# Start the system
python src/main.py --config config/camera_config.yaml

# With specific camera
python src/main.py --camera-id 0 --config config/camera_config.yaml

# Test mode (without camera)
python src/main.py --test-mode
```

## Performance Optimization

- Use hardware triggers for precise timing
- Enable GPU acceleration if available
- Adjust ROI to reduce processing area
- Tune exposure for optimal contrast

## License

MIT License

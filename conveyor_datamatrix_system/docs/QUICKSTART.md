# Quick Start Guide

## Installation

1. **Install system dependencies:**
```bash
# For Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y libzbar0

# For RHEL/CentOS/Fedora
sudo dnf install zbar
```

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

## Running the System

### Test Mode (No Camera Required)
```bash
cd conveyor_datamatrix_system
python src/main.py --test-mode --demo-duration 10
```

### With Real Camera
```bash
# Edit configuration first
nano config/camera_config.yaml

# Run with your camera
python src/main.py --config config/camera_config.yaml
```

### Command Line Options
```bash
python src/main.py --help

# Options:
#   --config, -c     Path to configuration file (default: config/camera_config.yaml)
#   --test-mode      Run without camera hardware
#   --camera-id      Camera device ID
#   --demo-duration  Demo duration in seconds (0 for continuous)
```

## Configuration

Edit `config/camera_config.yaml` to customize:

- **Camera settings**: exposure, gain, resolution
- **Trigger mode**: hardware, software, or continuous
- **Processing**: number of workers, buffer size
- **Output format**: console, JSON, file, MQTT, TCP

Example for Basler camera:
```yaml
camera:
  type: basler
  id: "YOUR_CAMERA_SERIAL"
  settings:
    exposure_time: 5000
    gain: 10.0
  trigger:
    enabled: true
    mode: hardware
```

## Testing

Run unit tests:
```bash
pytest tests/test_system.py -v
```

## Performance Tips

1. **Enable hardware trigger** for precise timing
2. **Set ROI** to reduce processing area
3. **Use multiple workers** (4-8 threads recommended)
4. **Optimize lighting** for better contrast
5. **Reduce exposure** to minimize motion blur

## Troubleshooting

**ImportError: Unable to find zbar shared library**
```bash
# Install libzbar
sudo apt-get install libzbar0
```

**Camera not found**
- Check camera connection
- Verify permissions: `ls -l /dev/video*`
- Install camera SDK if required

**Poor decode rate**
- Adjust exposure time
- Improve lighting
- Clean lens and surface
- Check focus

## Next Steps

- See `docs/camera_setup.md` for detailed camera installation
- Review `config/camera_config.yaml` for all options
- Check logs in `logs/system.log`

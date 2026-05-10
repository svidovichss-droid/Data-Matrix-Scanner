# Industrial Camera Setup Guide

## Supported Camera Types

### 1. Basler Cameras (pylon SDK)

**Installation:**
```bash
# Install pylon SDK from Basler website first
# Then install Python wrapper
pip install pypylon
```

**Configuration:**
```yaml
camera:
  type: basler
  id: "serial_number_or_index"
  settings:
    exposure_time: 5000
    gain: 10.0
  trigger:
    enabled: true
    mode: hardware
```

**Wiring for Hardware Trigger:**
- Connect photoelectric sensor to Camera Input Line 1
- Sensor output: 24V logic (use level shifter if 5V)
- Configure sensor for NPN or PNP based on camera input

### 2. FLIR Cameras (Spinnaker SDK)

**Installation:**
```bash
# Install Spinnaker SDK from FLIR website
pip install flir-spinnaker
```

**Configuration:**
```yaml
camera:
  type: flir
  id: "serial_number"
  settings:
    exposure_time: 5000
    gain: 10.0
```

### 3. GigE Vision Cameras (Generic)

**Installation:**
```bash
pip install harvesters
```

**Configuration:**
```yaml
camera:
  type: gige
  id: "MAC_address_or_IP"
  network:
    mtu: 1500
    packet_delay: 0
```

**Network Setup:**
- Set static IP on same subnet as camera
- Disable firewall or add exception
- Use jumbo frames if supported (MTU 9000)

### 4. USB3 Vision Cameras

**Configuration:**
```yaml
camera:
  type: usb3
  id: 0
```

**Tips:**
- Use USB 3.0 ports (blue)
- Avoid USB hubs
- Check cable quality

## Lighting Recommendations

### For DataMatrix Reading:

1. **Direct Brightfield**: Light source at same angle as camera
   - Good for reflective surfaces
   - Creates high contrast codes

2. **Darkfield**: Light at low angle (10-45°)
   - Highlights surface texture
   - Good for DPM (Direct Part Mark) codes

3. **Dome Light**: Diffused omnidirectional lighting
   - Eliminates reflections
   - Best for curved or shiny surfaces

### Strobe Lighting:
- Synchronize with camera trigger
- Reduces motion blur
- Extends LED lifetime

## Trigger Sensor Setup

### Photoelectric Sensor Selection:
- Response time: < 1ms
- Detection range: appropriate for conveyor
- Output type: NPN or PNP matching camera

### Wiring Diagram:
```
[Sensor] ----(Signal)---- [Camera Trigger In]
   |                         |
[24V PSU] ------------------+
   |
[GND]   --------------------+
```

### Debounce Settings:
```yaml
trigger:
  debounce_ms: 5  # Adjust based on sensor stability
```

## Performance Tuning

### Exposure Time:
- Start with 5000 µs
- Reduce for faster conveyor speeds
- Increase for better image quality
- Balance with lighting

### Region of Interest (ROI):
```yaml
roi:
  enabled: true
  x: 500
  y: 500
  width: 1000
  height: 800
```
Reduces processing time by limiting image area.

### Gain:
- Keep as low as possible (reduces noise)
- Increase only if lighting is insufficient
- Typical range: 0-20 dB

## Troubleshooting

### No Images:
1. Check camera connection
2. Verify permissions (USB cameras)
3. Check network configuration (GigE)
4. Install camera SDK

### Poor Decode Rate:
1. Adjust exposure for better contrast
2. Improve lighting
3. Clean lens and part surface
4. Check focus
5. Reduce conveyor speed

### Motion Blur:
1. Reduce exposure time
2. Add strobe lighting
3. Use hardware trigger
4. Increase camera distance

### Multiple Reads:
```python
# Implement debouncing in your application
last_code = None
last_read_time = 0
code_timeout = 0.5  # seconds

if code != last_code or (time.time() - last_read_time) > code_timeout:
    process_code(code)
    last_code = code
    last_read_time = time.time()
```

## Environment Variables

```bash
# OpenCV optimization
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4

# For GigE cameras
export MV_GIGE_MTU=1500
```

## Maintenance

### Regular Tasks:
- Clean camera lens weekly
- Check lighting intensity monthly
- Verify trigger sensor alignment
- Monitor system performance logs

### Log Analysis:
```bash
# View recent errors
tail -f logs/system.log | grep ERROR

# Check performance metrics
grep "Performance:" logs/system.log
```

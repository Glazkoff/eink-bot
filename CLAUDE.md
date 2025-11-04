# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram bot application that displays images and text on a tri-color e-ink display (800x480) connected to an Orange Pi Zero 2W. The bot receives messages via Telegram and renders them on the hardware display.

## Core Architecture

- **Main Application**: `telegram_bot.py` (793 lines) - Async Telegram bot using `python-telegram-bot`
- **Hardware Driver**: `libs/adafruit_uc8179.py` - Custom UC8179 chipset driver for e-ink display
- **Environment Configuration**: `.env` file with `TELEGRAM_BOT_TOKEN`
- **System Service**: systemd integration via `eink-bot.service.template`

## Development Commands

### Running the Bot
```bash
# Quick start (handles dependencies automatically)
./run_telegram_bot.sh

# Manual execution with virtual environment
source /home/orangepi/venv/bin/activate
cd /home/orangepi/develop/eink_bot
python telegram_bot.py
```

### System Service Management
```bash
# Setup and start as systemd service (requires sudo)
sudo ./manage-bot.sh setup

# Check service status
./manage-bot.sh status

# View live logs
./manage-bot.sh logs

# Restart service
sudo ./manage-bot.sh restart
```

### Dependencies
The bot automatically installs missing Python packages via `run_telegram_bot.sh`. Key dependencies:
- `python-telegram-bot` - Telegram Bot API framework
- `Pillow` - Image processing
- `adafruit-circuitpython-*` - Hardware libraries
- `python-dotenv` - Environment management
- `loguru` - Logging

## Hardware Configuration

### Display Settings
- **Resolution**: 800x480 pixels
- **Colors**: Tri-color (black, white, red)
- **Chipset**: UC8179
- **Rotation**: 2 (180 degrees)

### GPIO Pin Mapping (Orange Pi Zero 2W)
- SPI1_SCLK: PH6 (pin 23)
- SPI1_MOSI: PH7 (pin 19)
- SPI1_MISO: PH8 (pin 21)
- CS: PC12 (pin 36)
- DC: PI4 (pin 38)
- RST: PI16 (pin 37)
- BUSY: PH4

## Bot Commands

- `/start` - Initialize bot and display welcome message
- `/help` - Show usage instructions
- `/clear` - Clear the e-ink display
- `/text <message>` - Display text with automatic wrapping and font sizing
- `/debug` - Toggle debug mode (sends rendered images back to user)
- Send photos directly - Automatic scaling and optimization for display

## Key Features

### Image Processing
- Automatic scaling to fit display while maintaining aspect ratio
- Centered cropping for optimal placement
- Color quantization for tri-color display
- Dithering for smooth gradients

### Text Rendering
- Automatic font sizing based on text length
- Word wrapping with hyphenation support
- Color markup using `RED{text}` syntax for red text
- Uses Inter font from `fonts/Inter.ttf`

### Debug Mode
When enabled (`debug_mode = True`), the bot sends rendered images back to users for verification. This is useful for troubleshooting display output.

## Code Structure

### Main Components
- `init_display()` - Hardware initialization
- `process_and_display_image()` - Image processing pipeline
- `process_and_display_text()` - Text rendering engine
- Async command handlers for bot functionality

### Configuration
- Environment variables loaded via `python-dotenv`
- Display settings in global `DISPLAY` dictionary
- Debug mode flag for development

## Development Notes

### No Build Process
This is a pure Python application with no compilation step. Changes take effect immediately when the bot is restarted.

### Logging
Uses `loguru` for advanced logging. Logs are written to systemd journal when running as service.

### Error Handling
Comprehensive exception handling throughout. Hardware failures are logged but don't crash the bot.

### Testing
No formal test framework is configured. Manual testing via Telegram is the primary method.

## Environment Setup

1. Create `.env` file from `.env.example`:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```

2. Ensure virtual environment exists:
   ```bash
   # The bot script will create this if needed
   /home/orangepi/venv/
   ```

3. Hardware should be connected via SPI to the configured GPIO pins.

## Service Deployment

The bot is designed to run as a systemd service with automatic restart on failure. The service runs as root user for hardware access and uses the virtual environment for Python dependencies.
#!/usr/bin/env python3
import os
import asyncio
import logging
from io import BytesIO
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import board
import busio
import digitalio
from adafruit_epd.epd import Adafruit_EPD
from adafruit_epd.uc8179 import Adafruit_UC8179
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()

# --- SPI pins (SPI1 hardware bus on Orange Pi Zero 2W) ---
BOARD_SCK  = board.SPI1_SCLK   # PH6, physical pin 23
BOARD_MOSI = board.SPI1_MOSI   # PH7, physical pin 19
BOARD_MISO = board.SPI1_MISO   # PH8, physical pin 21
BOARD_CS   = board.PC12    # Physical pin 36

# --- Control pins for eInk display ---
DC_PIN    = board.PI4   # DC, physical pin 38
RESET_PIN = board.PI16  # RST, physical pin 37
BUSY_PIN = board.PH4

# --- Display configuration ---
DISPLAY = {"WIDTH": 800, "HEIGHT": 480, "rotation": 0}

# Global display object
display = None

# Global debug mode flag
debug_mode = True

def init_display():
    """Initialize the e-ink display"""
    global display
    try:
        # create the spi device and pins we will need
        spi = busio.SPI(BOARD_SCK, MOSI=BOARD_MOSI, MISO=BOARD_MISO)
        ecs = digitalio.DigitalInOut(BOARD_CS)
        dc = digitalio.DigitalInOut(DC_PIN)
        srcs = None  # can be None to use internal memory
        rst = digitalio.DigitalInOut(RESET_PIN)  # can be None to not use this pin
        busy = digitalio.DigitalInOut(BUSY_PIN)  # can be None to not use this pin

        # give them all to our drivers
        logger.info("Creating display")
        display = Adafruit_UC8179(
            DISPLAY['WIDTH'],
            DISPLAY['HEIGHT'],
            spi,
            cs_pin=ecs,
            dc_pin=dc,
            sramcs_pin=srcs,
            rst_pin=rst,
            busy_pin=busy,
            tri_color=True
        )

        display.rotation = 2
        logger.info("Display initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize display: {e}")
        return False

def process_and_display_image(image_data):
    """Process and display image on e-ink display"""
    global display
    if display is None:
        logger.error("Display not initialized")
        return False

    try:
        # Open image from bytes
        image = Image.open(BytesIO(image_data))

        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Scale the image to the smaller screen dimension
        image_ratio = image.width / image.height
        screen_ratio = display.width / display.height
        if screen_ratio < image_ratio:
            scaled_width = image.width * display.height // image.height
            scaled_height = display.height
        else:
            scaled_width = display.width
            scaled_height = image.height * display.width // image.width
        image = image.resize((scaled_width, scaled_height), Image.BICUBIC)

        # Crop and center the image
        x = scaled_width // 2 - display.width // 2
        y = scaled_height // 2 - display.height // 2
        image = image.crop((x, y, x + display.width, y + display.height)).convert("RGB")

        # Create palette for tri-color display
        palette = []
        # We'll map the 256 palette indices to our 3 colors
        # 0-63: Black, 64-127: Red, 128-255: White
        for i in range(256):
            if i < 64:
                palette.extend([0, 0, 0])  # Black
            elif i < 127:
                palette.extend([255, 0, 0])  # Red
            else:
                palette.extend([255, 255, 255])  # White

        # Create a palette image
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(palette)

        # Quantize the image using Floyd-Steinberg dithering
        image = image.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)

        # Convert back to RGB for the display driver
        image = image.convert("RGB")

        # Clear the buffer and display the image
        display.fill(Adafruit_EPD.WHITE)
        display.image(image)
        display.display()

        logger.info("Image displayed successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to process image: {e}")
        return False

def parse_colored_text(text):
    """Parse text with RED{...} syntax and return list of (text, color) tuples."""
    import re

    parts = []
    current_pos = 0
    pattern = r'RED\{(.*?)\}'

    for match in re.finditer(pattern, text):
        # Add text before RED{...} in black
        if match.start() > current_pos:
            black_text = text[current_pos:match.start()]
            if black_text:
                parts.append((black_text, 'BLACK'))

        # Add text inside RED{...} in red
        red_text = match.group(1)
        if red_text:
            parts.append((red_text, 'RED'))

        current_pos = match.end()

    # Add remaining text in black
    if current_pos < len(text):
        remaining_text = text[current_pos:]
        if remaining_text:
            parts.append((remaining_text, 'BLACK'))

    return parts if parts else [(text, 'BLACK')]

def wrap_text(text, font, max_width):
    """Wrap text to fit within max_width using word boundaries."""
    import textwrap

    # Use Python's textwrap for better word handling
    wrapper = textwrap.TextWrapper(width=max_width)

    # But we need to check actual text width since characters have different widths
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        # Test if adding this word exceeds the width
        if current_line:
            test_line = ' '.join(current_line + [word])
        else:
            test_line = word

        bbox = font.getbbox(test_line)
        test_width = bbox[2] - bbox[0]

        if test_width <= max_width:
            current_line.append(word)
        else:
            # If current line has content, add it and start new line
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                # Single word is too long, try to break it character by character
                if len(word) > 1:
                    # Try to find the longest prefix that fits
                    best_prefix = ""
                    for i in range(1, len(word) + 1):
                        test_prefix = word[:i]
                        bbox = font.getbbox(test_prefix)
                        if bbox[2] - bbox[0] <= max_width:
                            best_prefix = test_prefix
                        else:
                            break

                    if best_prefix:
                        lines.append(best_prefix)
                        current_line = [word[len(best_prefix):]]
                    else:
                        lines.append(word[0])  # At least one character
                        current_line = [word[1:]]
                else:
                    lines.append(word)

    # Add the last line
    if current_line:
        lines.append(' '.join(current_line))

    return lines

def find_font_size(text, max_width, max_height, font_path):
    """Find optimal font size for text, considering text wrapping."""
    fontsize = 10
    best_size = 10

    while True:
        font = ImageFont.truetype(font_path, fontsize)

        # Calculate uniform line height
        try:
            sample_bbox = font.getbbox("Ay")
            uniform_line_height = sample_bbox[3] - sample_bbox[1]
        except:
            # Fallback for older PIL versions
            font_size_calc = fontsize * 1.2  # Approximate height
            uniform_line_height = int(font_size_calc)

        # Try to wrap the text
        lines = wrap_text(text, font, max_width)

        # Calculate total height using uniform line height with safety margins
        total_height = uniform_line_height * len(lines)

        # Add spacing between lines (20% of font size) and safety margin
        if len(lines) > 1:
            spacing = int(fontsize * 0.2)
            total_height += spacing * (len(lines) - 1)

        # Add 10% safety margin for display variations
        total_height = int(total_height * 1.1)

        # Check if it fits
        if total_height > max_height:
            return best_size  # Return previous successful size

        best_size = fontsize
        fontsize += 1

        # Prevent infinite loop
        if fontsize > 300:
            break

    return best_size

def generate_wrapped_colored_text(text, font, max_width):
    """Generate wrapped text lines with color information preserved."""
    # First, parse the colored text parts
    text_parts = parse_colored_text(text)

    # Reconstruct text without color tags for wrapping
    clean_text = ""
    part_positions = []
    current_pos = 0

    for part_text, color in text_parts:
        clean_text += part_text
        part_positions.append({
            'start': current_pos,
            'end': current_pos + len(part_text),
            'color': color,
            'text': part_text
        })
        current_pos += len(part_text)

    # Wrap the clean text using words
    wrapped_lines = wrap_text(clean_text, font, max_width)

    # Map colors back to wrapped lines
    result_lines = []
    global_char_pos = 0

    for line_index, line in enumerate(wrapped_lines):
        line_parts = []
        line_start_pos = global_char_pos
        line_end_pos = global_char_pos + len(line)

        # Find which parts overlap with this line
        for part_info in part_positions:
            part_start = part_info['start']
            part_end = part_info['end']

            # Check if this part overlaps with the current line
            if part_end > line_start_pos and part_start < line_end_pos:
                # Calculate overlap
                overlap_start = max(part_start, line_start_pos)
                overlap_end = min(part_end, line_end_pos)

                # Convert to relative positions within the line and part
                start_in_line = overlap_start - line_start_pos
                end_in_line = overlap_end - line_start_pos
                start_in_part = overlap_start - part_start
                end_in_part = overlap_end - part_start

                # Extract the text segment
                text_segment = part_info['text'][start_in_part:end_in_part]
                line_text_segment = line[start_in_line:end_in_line]

                # Use the segment from the original part (should be the same)
                if text_segment:
                    line_parts.append((text_segment, part_info['color']))

        if line_parts:
            result_lines.append(line_parts)

        # Update global position (only add 1 for space if this is not the last line)
        global_char_pos += len(line)
        if line_index < len(wrapped_lines) - 1:  # Add space between lines
            global_char_pos += 1

    return result_lines

def generate_text_image(text, font_size=30):
    """Generate a PIL image with centered text on white background with text wrapping."""
    if display is None:
        logger.error("Display not initialized")
        return None

    try:
        # Create a black and white image
        image = Image.new("RGB", (display.width, display.height), (255, 255, 255))
        draw = ImageDraw.Draw(image)

        # Try to load a font, fallback to default if not available
        try:
            font = ImageFont.truetype("/home/orangepi/develop/eink_bot/fonts/Inter.ttf", font_size)
        except:
            try:
                logger.warning(f'ERROR TO LOAD INTER FONT WITH SIZE {font_size}!')
                font = ImageFont.load_default()
            except:
                logger.error('ERROR TO LOAD DEFAULT FONT!')
                font = ImageFont.load_default()

        # Generate wrapped colored text lines
        max_text_width = display.width - 40  # 20px padding on each side
        wrapped_lines = generate_wrapped_colored_text(text, font, max_text_width)

        logger.debug(f"DEBUG WRAPPED LINES: {wrapped_lines}")

        # Calculate uniform line height based on font metrics
        try:
            # Get a sample text to determine consistent line height
            sample_bbox = font.getbbox("Ay")
            uniform_line_height = sample_bbox[3] - sample_bbox[1]
        except:
            # Fallback for older PIL versions
            _, uniform_line_height = draw.textsize("Ay", font=font)
            uniform_line_height = int(uniform_line_height)

        # Calculate line widths (use uniform height)
        line_widths = []

        for line_parts in wrapped_lines:
            line_width = 0

            for part_text, color in line_parts:
                try:
                    bbox = font.getbbox(part_text)
                    part_width = bbox[2] - bbox[0]
                except:
                    # Fallback for older PIL versions
                    part_width, _ = draw.textsize(part_text, font=font)

                line_width += part_width

            line_widths.append(line_width)

        # Calculate total height with line spacing and safety margin
        line_spacing = int(font_size * 0.2)  # 20% of font size
        total_height = uniform_line_height * len(wrapped_lines)
        if len(wrapped_lines) > 1:
            total_height += line_spacing * (len(wrapped_lines) - 1)

        # Add small safety margin to prevent text from going off-screen
        total_height = int(total_height * 1.05)

        # Find the maximum line width for centering
        max_line_width = max(line_widths) if line_widths else 0

        # Center the text block with margin to ensure it fits on screen
        start_y = max(10, (display.height - total_height) // 2)

        # Draw each line with uniform height
        current_y = start_y
        for i, (line_parts, line_width) in enumerate(zip(wrapped_lines, line_widths)):
            # Center this line horizontally
            start_x = (display.width - line_width) // 2

            logger.debug(f"DEBUG LINE {i}: start_y={current_y}, line_width={line_width}, start_x={start_x}, uniform_line_height={uniform_line_height}")

            # Draw each part in the line
            current_x = start_x
            for j, (part_text, color) in enumerate(line_parts):
                if color == 'RED':
                    text_color = (255, 0, 0)
                else:
                    text_color = (0, 0, 0)

                # Calculate text dimensions for debugging
                try:
                    bbox = font.getbbox(part_text)
                    part_width = bbox[2] - bbox[0]
                    part_height = bbox[3] - bbox[1]
                except:
                    # Fallback for older PIL versions
                    part_width, part_height = draw.textsize(part_text, font=font)

                # Simple approach: position all parts at the same Y coordinate for the line
                # This ensures proper alignment across different character heights
                part_y = current_y

                logger.debug(f"  PART {j}: '{part_text}' color={color} x={current_x}, y={part_y}, width={part_width}, height={part_height}")

                draw.text((current_x, part_y), part_text, font=font, fill=text_color)

                # Move to next part position
                current_x += part_width

            # Move to next line using uniform height
            current_y += uniform_line_height
            if i < len(wrapped_lines) - 1:  # Add spacing except for last line
                current_y += line_spacing

        return image

    except Exception as e:
        logger.error(f"Failed to generate text image: {e}")
        return None

def display_text(text, font_size=30):
    """Display text on the e-ink display."""
    global display
    if display is None:
        logger.error("Display not initialized")
        return False

    try:
        # Generate the text image
        image = generate_text_image(text, font_size)
        if image is None:
            return False

        # Clear the display first to ensure a clean white background
        display.fill(Adafruit_EPD.WHITE)

        # Display the image
        display.image(image)
        display.display()

        logger.info(f"Text displayed successfully: '{text}' with font size {font_size}")
        return True

    except Exception as e:
        logger.error(f"Failed to display text: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! Send me an image and I'll display it on the e-ink screen.",
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "Send me an image (photo or document) and I'll display it on the e-ink screen.\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/clear - Clear the display\n"
        "/text <message> [font_size] - Display text on the screen (optional font size, auto if not specified)\n"
        "/debug - Toggle debug mode (send displayed images back to you)\n\n"
        "Text Features:\n"
        "• Auto text wrapping - Long messages automatically wrap to multiple lines\n"
        "• Auto font sizing - Automatically finds optimal font size to fit text\n"
        "• Use RED{text} to make text appear in red color\n"
        "• Multiple RED{...} sections supported in wrapped text\n"
        "• Font size range: 1-200 pixels (when specified manually)\n\n"
        "Examples:\n"
        "/text Hello World - Auto-size 'Hello World' to fit screen\n"
        "/text This is a very long message that will wrap - Auto-wraps long text\n"
        "/text Hello World 48 - Display 'Hello World' with font size 48\n"
        "/text Hello RED{World} from RED{Bot} - Multi-color text with wrapping\n"
        "/text RED{Error:} Something went wrong - Auto-wrapped error message"
    )

async def clear_display(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the e-ink display."""
    global display
    if display is None:
        await update.message.reply_text("Display not initialized.")
        return

    try:
        display.fill(Adafruit_EPD.WHITE)
        display.display()
        await update.message.reply_text("Display cleared!")
        logger.info("Display cleared")
    except Exception as e:
        await update.message.reply_text(f"Failed to clear display: {e}")
        logger.error(f"Failed to clear display: {e}")

async def text_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /text command to display text on the e-ink screen."""
    # Check if text was provided
    if not context.args:
        await update.message.reply_text("Please provide text to display. Usage: /text <your message> [font_size]")
        return

    # Parse font size from arguments (check if last argument is a number)
    font_size = None  # Will be auto-calculated if not provided
    text_args = context.args
    auto_sized = False

    try:
        # Try to parse the last argument as font size
        potential_font_size = int(context.args[-1])
        if potential_font_size > 0 and potential_font_size <= 200:  # reasonable font size range
            font_size = potential_font_size
            text_args = context.args[:-1]  # Remove font size from text
    except (ValueError, IndexError):
        # Last argument is not a number, use auto font sizing
        auto_sized = True

    # Join remaining arguments to form the complete message
    text_message = " ".join(text_args)

    # Auto-calculate font size if not provided
    if auto_sized or font_size is None:
        try:
            font_path = "/home/orangepi/develop/eink_bot/fonts/Inter.ttf"
            # Remove RED{...} tags for accurate text measurement
            clean_text = text_message.replace("RED{", "").replace("}", "")
            font_size = find_font_size(clean_text, display.width - 40, display.height - 40, font_path)
            auto_sized = True
            logger.info(f"Auto-calculated font size: {font_size} for text: '{text_message}'")
        except Exception as e:
            logger.error(f"Failed to auto-calculate font size: {e}")
            font_size = 30  # fallback to default
            auto_sized = False

    # Display the text
    if display_text(text_message, font_size):
        if auto_sized:
            font_info = f" (auto font size: {font_size})"
        elif font_size != 30:
            font_info = f" (font size: {font_size})"
        else:
            font_info = ""

        await update.message.reply_text(f"Text displayed on e-ink screen: '{text_message}'{font_info}")

        if debug_mode:
            # Send the rendered text image back to user in debug mode
            try:
                # Generate the text image using the new function
                image = generate_text_image(text_message, font_size)
                if image is not None:
                    # Convert to bytes for sending
                    img_byte_arr = BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)
                    await update.message.reply_photo(photo=img_byte_arr)
                else:
                    logger.error("Failed to generate text image for debug mode")
            except Exception as e:
                logger.error(f"Failed to send debug text image: {e}")
    else:
        await update.message.reply_text("Failed to display text. Please try again.")

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle debug mode on/off."""
    global debug_mode
    debug_mode = not debug_mode

    if debug_mode:
        await update.message.reply_text("Debug mode ON - I'll send you copies of what I display on the screen.")
    else:
        await update.message.reply_text("Debug mode OFF - I won't send images back.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages."""
    await update.message.reply_text("Processing photo...")

    # Get the largest photo size
    photo = update.message.photo[-1]

    try:
        # Download the photo
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()

        # Display the image
        if process_and_display_image(photo_bytes):
            await update.message.reply_text("Photo displayed on e-ink screen!")
            if debug_mode:
                # Send the processed image back to user in debug mode
                try:
                    # Recreate the final image for sending
                    image = Image.open(BytesIO(photo_bytes))

                    # Convert to RGB if necessary
                    if image.mode != 'RGB':
                        image = image.convert('RGB')

                    # Scale the image to the smaller screen dimension
                    image_ratio = image.width / image.height
                    screen_ratio = display.width / display.height
                    if screen_ratio < image_ratio:
                        scaled_width = image.width * display.height // image.height
                        scaled_height = display.height
                    else:
                        scaled_width = display.width
                        scaled_height = image.height * display.width // image.width
                    image = image.resize((scaled_width, scaled_height), Image.BICUBIC)

                    # Crop and center the image
                    x = scaled_width // 2 - display.width // 2
                    y = scaled_height // 2 - display.height // 2
                    image = image.crop((x, y, x + display.width, y + display.height)).convert("RGB")

                    # Create palette for tri-color display
                    palette = []
                    for i in range(256):
                        if i < 64:
                            palette.extend([0, 0, 0])  # Black
                        elif i < 127:
                            palette.extend([255, 0, 0])  # Red
                        else:
                            palette.extend([255, 255, 255])  # White

                    # Create a palette image
                    palette_img = Image.new("P", (1, 1))
                    palette_img.putpalette(palette)

                    # Quantize the image using Floyd-Steinberg dithering
                    image = image.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)
                    image = image.convert("RGB")

                    # Convert to bytes for sending
                    img_byte_arr = BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)

                    await update.message.reply_photo(photo=img_byte_arr)
                except Exception as e:
                    logger.error(f"Failed to send debug image: {e}")
        else:
            await update.message.reply_text("Failed to display photo. Please try again.")

    except Exception as e:
        await update.message.reply_text(f"Failed to process photo: {e}")
        logger.error(f"Failed to process photo: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document messages (images sent as documents)."""
    # Check if document is an image
    if not update.message.document.mime_type.startswith('image/'):
        await update.message.reply_text("Please send an image file.")
        return

    await update.message.reply_text("Processing image document...")

    try:
        # Download the document
        file = await context.bot.get_file(update.message.document.file_id)
        file_bytes = await file.download_as_bytearray()

        # Display the image
        if process_and_display_image(file_bytes):
            await update.message.reply_text("Image displayed on e-ink screen!")
            if debug_mode:
                # Send the processed image back to user in debug mode
                try:
                    # Recreate the final image for sending
                    image = Image.open(BytesIO(file_bytes))

                    # Convert to RGB if necessary
                    if image.mode != 'RGB':
                        image = image.convert('RGB')

                    # Scale the image to the smaller screen dimension
                    image_ratio = image.width / image.height
                    screen_ratio = display.width / display.height
                    if screen_ratio < image_ratio:
                        scaled_width = image.width * display.height // image.height
                        scaled_height = display.height
                    else:
                        scaled_width = display.width
                        scaled_height = image.height * display.width // image.width
                    image = image.resize((scaled_width, scaled_height), Image.BICUBIC)

                    # Crop and center the image
                    x = scaled_width // 2 - display.width // 2
                    y = scaled_height // 2 - display.height // 2
                    image = image.crop((x, y, x + display.width, y + display.height)).convert("RGB")

                    # Create palette for tri-color display
                    palette = []
                    for i in range(256):
                        if i < 64:
                            palette.extend([0, 0, 0])  # Black
                        elif i < 127:
                            palette.extend([255, 0, 0])  # Red
                        else:
                            palette.extend([255, 255, 255])  # White

                    # Create a palette image
                    palette_img = Image.new("P", (1, 1))
                    palette_img.putpalette(palette)

                    # Quantize the image using Floyd-Steinberg dithering
                    image = image.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)
                    image = image.convert("RGB")

                    # Convert to bytes for sending
                    img_byte_arr = BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)

                    await update.message.reply_photo(photo=img_byte_arr)
                except Exception as e:
                    logger.error(f"Failed to send debug image: {e}")
        else:
            await update.message.reply_text("Failed to display image. Please try again.")

    except Exception as e:
        await update.message.reply_text(f"Failed to process image: {e}")
        logger.error(f"Failed to process image: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    """Start the bot."""
    # Get Telegram bot token from environment variable
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        logger.error("Please create a .env file with your Telegram bot token:")
        logger.error("TELEGRAM_BOT_TOKEN=your_bot_token_here")
        return

    # Initialize the display
    if not init_display():
        logger.error("Failed to initialize display. Bot will start but display functions won't work.")

    # Create the Application
    application = Application.builder().token(token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_display))
    application.add_handler(CommandHandler("text", text_command))
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the Bot
    logger.info("Starting Telegram bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
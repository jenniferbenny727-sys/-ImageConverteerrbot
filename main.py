import os
import io
import logging
from datetime import datetime
from PIL import Image, ImageOps, ImageSequence

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing.")

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
SUPPORT_USERNAME = "@YourSupportUsername"  # <-- change this
ALLOWED_INPUT_FORMATS = {"JPEG", "JPG", "PNG", "WEBP", "BMP", "GIF", "TIFF"}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MENUS
# ---------------------------------------------------------------------------
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🖼️ Convert Image", callback_data="menu_convert")],
    [InlineKeyboardButton("📄 Image to PDF", callback_data="menu_pdf")],
    [InlineKeyboardButton("🗜️ Compress Image", callback_data="menu_compress")],
    [InlineKeyboardButton("📐 Resize Image", callback_data="menu_resize")],
    [InlineKeyboardButton("📊 Supported Formats", callback_data="menu_formats")],
    [InlineKeyboardButton("ℹ️ Help & Instructions", callback_data="menu_help")],
    [InlineKeyboardButton("👨‍💻 About Bot", callback_data="menu_about")],
    [InlineKeyboardButton("💬 Contact Support", callback_data="menu_support")],
])

CONVERT_FORMATS = {
    "convert_png": "PNG",
    "convert_jpg": "JPEG",
    "convert_webp": "WEBP",
    "convert_bmp": "BMP",
}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def validate_image(data: bytes) -> str:
    """Return detected Pillow format name, or raise ValueError."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            img.verify()
        if fmt not in ALLOWED_INPUT_FORMATS:
            raise ValueError(f"Unsupported format: {fmt}")
        return fmt
    except Exception as exc:
        raise ValueError(f"Invalid or corrupted image: {exc}") from exc


def convert_image(data: bytes, target: str, quality: int = 92) -> bytes:
    """Convert image bytes to target format. Handles transparency safely."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)

        # Transparency handling
        if target in ("JPEG", "JPG"):
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
        else:
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA")

        out = io.BytesIO()
        save_kwargs = {}
        if target == "JPEG":
            save_kwargs = {"quality": quality, "optimize": True}
        elif target == "WEBP":
            save_kwargs = {"quality": quality}
        elif target == "PNG":
            save_kwargs = {"optimize": True}

        img.save(out, format=target, **save_kwargs)
        return out.getvalue()


def compress_image(data: bytes) -> bytes:
    """Reduce file size by re-encoding with lower quality."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=60, optimize=True)
        return out.getvalue()


def resize_image(data: bytes, width: int, height: int) -> bytes:
    """Resize while preserving aspect ratio and quality."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        fmt = img.format or "PNG"
        resized = img.resize((width, height), Image.LANCZOS)
        out = io.BytesIO()
        if fmt in ("JPEG", "JPG"):
            if resized.mode != "RGB":
                resized = resized.convert("RGB")
            resized.save(out, format="JPEG", quality=92, optimize=True)
        else:
            resized.save(out, format=fmt if fmt in ("PNG", "WEBP", "BMP") else "PNG")
        return out.getvalue()


def images_to_pdf(image_list: list[bytes]) -> bytes:
    """Combine multiple images into one PDF."""
    pil_images = []
    for data in image_list:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            pil_images.append(img.copy())

    if not pil_images:
        raise ValueError("No valid images to convert to PDF.")

    out = io.BytesIO()
    first, rest = pil_images[0], pil_images[1:]
    first.save(out, format="PDF", save_all=True, append_images=rest)
    return out.getvalue()


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 **Welcome to Image Converter Bot!**\n\n"
        "I can convert, compress, and resize images right here in Telegram, "
        "and turn your photos into PDFs.\n\n"
        "**How to use:**\n"
        "1. Tap a button below or send me an image directly.\n"
        "2. Choose the output format.\n"
        "3. Receive your converted file.\n\n"
        "Use /help for detailed instructions."
    )
    await update.message.reply_text(text, reply_markup=MAIN_MENU, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 **Help & Instructions**\n\n"
        "• **Convert Image** – Send a photo, then pick a format (PNG, JPG, WEBP, BMP).\n"
        "• **Image to PDF** – Send one or more images; I combine them into a PDF.\n"
        "• **Compress** – Reduce file size while keeping quality.\n"
        "• **Resize** – Change dimensions by pixels.\n\n"
        "**Commands:**\n"
        "/start – Main menu\n"
        "/convert – Start conversion\n"
        "/formats – List supported formats\n"
        "/cancel – Cancel current operation\n"
        "/help – This message\n"
        "/about – About the bot\n\n"
        f"⚠️ **Limits:** Max file size {human_size(MAX_FILE_SIZE)}.\n"
        "Supported input: JPG, PNG, WEBP, BMP, GIF, TIFF."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def formats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📊 **Supported Formats**\n\n"
        "**Input:** JPG, JPEG, PNG, WEBP, BMP, GIF, TIFF\n"
        "**Output:** JPG, PNG, WEBP, BMP, PDF\n\n"
        "**Conversion Rules:**\n"
        "• Transparent images → JPG get a **white background**.\n"
        "• Grayscale images are supported.\n"
        f"• Max file size: {human_size(MAX_FILE_SIZE)}."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👨‍💻 **About Image Converter Bot**\n\n"
        "Built with Python, `python-telegram-bot`, and Pillow.\n"
        "Deployed on Render as a background worker.\n\n"
        "Version: 1.0.0\n"
        f"Support: {SUPPORT_USERNAME}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again.",
        reply_markup=MAIN_MENU,
    )


# ---------------------------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_convert":
        context.user_data["mode"] = "convert"
        await query.edit_message_text(
            "🖼️ **Send me an image** to convert.\n\n"
            "I'll detect the format and show you conversion options.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_formats":
        await formats_command(update, context)

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_about":
        await about_command(update, context)

    elif data == "menu_support":
        await query.edit_message_text(
            f"💬 **Contact Support**\n\nFor issues or feature requests, contact: {SUPPORT_USERNAME}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_pdf":
        context.user_data["mode"] = "pdf"
        context.user_data["pdf_images"] = []
        await query.edit_message_text(
            "📄 **Image to PDF**\n\n"
            "Send one or more images. I'll combine them into a single PDF in the order received.\n\n"
            "When you're done sending, tap the button below.\n"
            "Use /cancel to stop.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Finish & Make PDF", callback_data="pdf_done")],
                [InlineKeyboardButton("❌ Cancel", callback_data="pdf_cancel")],
            ]),
        )

    elif data == "menu_compress":
        context.user_data["mode"] = "compress"
        await query.edit_message_text(
            "🗜️ **Compress Image**\n\n"
            "Send me an image. I'll reduce its file size while keeping good quality.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_resize":
        context.user_data["mode"] = "resize"
        await query.edit_message_text(
            "📐 **Resize Image**\n\n"
            "Send me an image first. Then tell me the new dimensions, e.g. `800x600`.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data in CONVERT_FORMATS:
        target = CONVERT_FORMATS[data]
        input_bytes = context.user_data.get("pending_image")
        if not input_bytes:
            await query.edit_message_text("⚠️ No image found. Please send an image first.")
            return

        await query.edit_message_text("⏳ Your image is being converted. Please wait...")

        try:
            output_bytes = convert_image(input_bytes, target)
            orig_fmt = context.user_data.get("pending_image_info", {}).get("format", "Unknown")
            summary = (
                "✅ **Conversion completed successfully!**\n\n"
                f"📁 Original format: `{orig_fmt}`\n"
                f"📁 Converted format: `{target}`\n"
                f"📦 File size: `{human_size(len(output_bytes))}`"
            )
            ext = target.lower().replace("jpeg", "jpg")
            await query.message.reply_document(
                document=io.BytesIO(output_bytes),
                filename=f"converted_{int(datetime.now().timestamp())}.{ext}",
                caption=summary,
                parse_mode=ParseMode.MARKDOWN,
            )
            await query.delete_message()
        except Exception as e:
            logger.exception("Conversion failed")
            await query.edit_message_text(
                f"❌ Conversion failed. The file may be corrupted or unsupported.\n"
                f"Error: `{str(e)[:120]}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        finally:
            context.user_data.pop("pending_image", None)
            context.user_data.pop("pending_image_info", None)

    elif data == "pdf_done":
        images = context.user_data.get("pdf_images", [])
        if not images:
            await query.edit_message_text("⚠️ You haven't sent any images yet.")
            return
        await query.edit_message_text("⏳ Building your PDF, please wait...")
        try:
            pdf_bytes = images_to_pdf(images)
            await query.message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename=f"images_{int(datetime.now().timestamp())}.pdf",
                caption=f"✅ **PDF created!**\n\n📄 Pages: `{len(images)}`\n📦 Size: `{human_size(len(pdf_bytes))}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            await query.delete_message()
        except Exception as e:
            logger.exception("PDF creation failed")
            await query.edit_message_text(f"❌ PDF creation failed: `{str(e)[:120]}`", parse_mode=ParseMode.MARKDOWN)
        finally:
            context.user_data.pop("pdf_images", None)
            context.user_data.pop("mode", None)

    elif data == "pdf_cancel":
        context.user_data.pop("pdf_images", None)
        context.user_data.pop("mode", None)
        await query.edit_message_text("❌ PDF creation cancelled.")


# ---------------------------------------------------------------------------
# IMAGE RECEIVER
# ---------------------------------------------------------------------------
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    mode = context.user_data.get("mode")

    # Download the file
    if message.photo:
        file_obj = await message.photo[-1].get_file()
        data = bytes(await file_obj.download_as_bytearray())
        guessed_fmt = "JPEG"
    elif message.document:
        doc = message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await message.reply_text("⚠️ Please send an image file.")
            return
        if doc.file_size and doc.file_size > MAX_FILE_SIZE:
            await message.reply_text(f"⚠️ File too large. Max is {human_size(MAX_FILE_SIZE)}.")
            return
        file_obj = await doc.get_file()
        data = bytes(await file_obj.download_as_bytearray())
        guessed_fmt = doc.mime_type.split("/")[-1].upper()
    else:
        await message.reply_text("⚠️ Please send an image as a photo or file.")
        return

    if len(data) > MAX_FILE_SIZE:
        await message.reply_text(f"⚠️ File too large. Max is {human_size(MAX_FILE_SIZE)}.")
        return

    # Validate
    try:
        real_fmt = validate_image(data)
    except ValueError as e:
        await message.reply_text(f"❌ {e}")
        return

    # Route based on mode
    if mode == "pdf":
        context.user_data.setdefault("pdf_images", []).append(data)
        count = len(context.user_data["pdf_images"])
        await message.reply_text(
            f"📥 Image {count} received. Send another, or tap **Finish & Make PDF**.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Finish & Make PDF", callback_data="pdf_done")],
                [InlineKeyboardButton("❌ Cancel", callback_data="pdf_cancel")],
            ]),
        )
        return

    if mode == "compress":
        await message.reply_text("⏳ Compressing your image...")
        try:
            out = compress_image(data)
            await message.reply_document(
                document=io.BytesIO(out),
                filename=f"compressed_{int(datetime.now().timestamp())}.jpg",
                caption=(
                    "✅ **Compression complete!**\n\n"
                    f"📁 Original: `{human_size(len(data))}`\n"
                    f"📦 Compressed: `{human_size(len(out))}`\n"
                    f"📉 Saved: `{human_size(max(0, len(data) - len(out)))}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.exception("Compress failed")
            await message.reply_text(f"❌ Compression failed: `{str(e)[:120]}`", parse_mode=ParseMode.MARKDOWN)
        finally:
            context.user_data.pop("mode", None)
        return

    if mode == "resize":
        context.user_data["pending_resize"] = data
        await message.reply_text(
            f"📥 Image received ({real_fmt}).\n\n"
            "Now send the new dimensions as `WIDTHxHEIGHT` (e.g. `800x600`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Default: convert flow
    context.user_data["pending_image"] = data
    context.user_data["pending_image_info"] = {"format": real_fmt}
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("PNG", callback_data="convert_png"),
         InlineKeyboardButton("JPG", callback_data="convert_jpg")],
        [InlineKeyboardButton("WEBP", callback_data="convert_webp"),
         InlineKeyboardButton("BMP", callback_data="convert_bmp")],
    ])
    await message.reply_text(
        f"📥 Received image ({real_fmt}, {human_size(len(data))}).\n\n"
        "**Choose output format:**",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# TEXT HANDLER (for resize dimensions)
# ---------------------------------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("mode") != "resize":
        return
    data = context.user_data.get("pending_resize")
    if not data:
        return

    text = update.message.text.strip().lower()
    try:
        if "x" in text:
            w_str, h_str = text.split("x", 1)
            w, h = int(w_str), int(h_str)
        else:
            raise ValueError("Use format WIDTHxHEIGHT")
        if w <= 0 or h <= 0 or w > 10000 or h > 10000:
            raise ValueError("Dimensions must be between 1 and 10000.")
    except Exception:
        await update.message.reply_text("⚠️ Please send dimensions like `800x600`.", parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text("⏳ Resizing your image...")
    try:
        out = resize_image(data, w, h)
        await update.message.reply_document(
            document=io.BytesIO(out),
            filename=f"resized_{w}x{h}_{int(datetime.now().timestamp())}.jpg",
            caption=(
                "✅ **Resize complete!**\n\n"
                f"📐 New size: `{w}x{h}px`\n"
                f"📦 File size: `{human_size(len(out))}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.exception("Resize failed")
        await update.message.reply_text(f"❌ Resize failed: `{str(e)[:120]}`", parse_mode=ParseMode.MARKDOWN)
    finally:
        context.user_data.pop("pending_resize", None)
        context.user_data.pop("mode", None)


# ---------------------------------------------------------------------------
# ERROR HANDLER
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Something went wrong. Please try again or use /start."
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("formats", formats_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("convert", start))

    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_error_handler(error_handler)

    logger.info("Bot started. Polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

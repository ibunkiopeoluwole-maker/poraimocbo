import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Check if ffmpeg is available
FFMPEG_PATH = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"

AUDIO_FORMATS = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "ogg": "libvorbis",
    "m4a": "aac",
    "flac": "flac",
    "wma": "wmav2",
    "aac": "aac",
    "opus": "libopus",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 Send me a video file (MP4, MKV, AVI, etc.) and I'll extract the audio.\n\n"
        "Default format: MP3\n"
        "To change format: /format <type>\n"
        f"Available formats: {', '.join(AUDIO_FORMATS.keys())}\n\n"
        "You can also send a voice/video note to extract audio."
    )

async def set_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            f"Usage: /format <type>\nAvailable: {', '.join(AUDIO_FORMATS.keys())}"
        )
        return
    fmt = context.args[0].lower()
    if fmt not in AUDIO_FORMATS:
        await update.message.reply_text(f"❌ Unsupported format. Use: {', '.join(AUDIO_FORMATS.keys())}")
        return
    context.user_data["audio_format"] = fmt
    await update.message.reply_text(f"✅ Output format set to: {fmt.upper()}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the video file
    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("Please send a valid video file.")
        return

    # Check file size (Telegram bots limit: 20MB, but we'll try up to 50MB)
    if video.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("❌ File too large. Max size: 50MB")
        return

    status_msg = await update.message.reply_text("⏳ Downloading video...")

    # Download video
    file = await context.bot.get_file(video.file_id)
    video_filename = video.file_name or f"video_{video.file_id}.mp4"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / video_filename
        await file.download_to_drive(video_path)
        
        # Determine output format
        out_fmt = context.user_data.get("audio_format", "mp3")
        out_filename = f"{video_path.stem}.{out_fmt}"
        out_path = Path(tmpdir) / out_filename

        await status_msg.edit_text("🔄 Extracting audio...")

        # Run ffmpeg
        codec = AUDIO_FORMATS.get(out_fmt, "libmp3lame")
        cmd = [
            FFMPEG_PATH, "-i", str(video_path),
            "-vn",  # No video
            "-acodec", codec,
            "-q:a", "2",  # High quality
            "-y",  # Overwrite output
            str(out_path)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as e:
            await status_msg.edit_text(f"❌ FFmpeg error:\n{e.stderr.decode()[:500]}")
            return
        except subprocess.TimeoutExpired:
            await status_msg.edit_text("❌ Extraction timed out. File may be too large.")
            return

        if not out_path.exists() or out_path.stat().st_size == 0:
            await status_msg.edit_text("❌ Failed to extract audio.")
            return

        await status_msg.edit_text("📤 Uploading audio...")

        # Send audio file
        with open(out_path, "rb") as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                filename=out_filename,
                caption=f"🎵 Extracted from: {video_filename}\nFormat: {out_fmt.upper()}"
            )

        await status_msg.delete()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages - just forward as audio."""
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    
    out_fmt = context.user_data.get("audio_format", "mp3")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        voice_path = Path(tmpdir) / f"voice.ogg"
        await file.download_to_drive(voice_path)
        
        if out_fmt == "mp3":
            out_path = Path(tmpdir) / f"voice.{out_fmt}"
            cmd = [
                FFMPEG_PATH, "-i", str(voice_path),
                "-acodec", "libmp3lame",
                "-q:a", "2", "-y", str(out_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            out_path = voice_path

        with open(out_path, "rb") as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                filename=f"voice.{out_fmt}",
                caption=f"🎵 Extracted voice note as {out_fmt.upper()}"
            )

def main():
    # Create tmp directory for ffmpeg
    os.makedirs("/tmp/ffmpeg", exist_ok=True)
    
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("format", set_format))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.run_polling()

if __name__ == '__main__':
    main()

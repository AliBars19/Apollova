"""
Audio Processing - Download, trim, beat detection, and audio preprocessing
Shared across Aurora, Mono, and Onyx templates

- download_audio: YouTube download via yt-dlp
- trim_audio: Clip extraction based on MM:SS timestamps
- detect_beats: Beat detection via librosa (Aurora only)
- normalize_audio: Normalize to -20 dBFS for consistent Whisper input
- reduce_noise: Stationary noise reduction (optional, requires noisereduce)
"""
import os
import re
import time
import subprocess
import wave
from pydub import AudioSegment

_YT_ID_RE = re.compile(r'(?:youtube\.com/watch\?.*v=|youtu\.be/)([A-Za-z0-9_-]{11})')
_COOKIE_BROWSERS = ('chrome', 'edge', 'firefox', 'brave', 'chromium')


def _find_cookies_file():
    """Look for cookies.txt in install root (next to Apollova.exe) or alongside script."""
    here = os.path.dirname(os.path.abspath(__file__))
    # Walk up: assets/scripts/ -> assets/ -> install root
    candidates = [
        os.path.join(here, 'cookies.txt'),
        os.path.join(os.path.dirname(here), 'cookies.txt'),
        os.path.join(os.path.dirname(os.path.dirname(here)), 'cookies.txt'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _validate_youtube_url(url):
    """Raise a user-friendly ValueError if the URL is not a valid YouTube video link."""
    if not url or not isinstance(url, str) or url.strip() == "":
        raise ValueError(
            "No YouTube URL was provided for this song.\n\n"
            "How to fix: Open the database editor in Settings, find this song, "
            "and paste in a valid YouTube URL."
        )
    if url.strip().lower() == "unknown":
        raise ValueError(
            "This song has a placeholder URL ('unknown') stored in the database — "
            "it was never given a real YouTube link.\n\n"
            "How to fix: Open the database editor in Settings, find this song, "
            "and replace 'unknown' with a real YouTube URL "
            "(e.g. https://www.youtube.com/watch?v=XXXXXXXXXXX)."
        )
    if not _YT_ID_RE.search(url):
        raise ValueError(
            f"The URL stored for this song is not a valid YouTube video link:\n"
            f"  '{url}'\n\n"
            "Expected format: https://www.youtube.com/watch?v=XXXXXXXXXXX\n\n"
            "How to fix: Open the database editor in Settings, find this song, "
            "and update the URL to a direct YouTube watch link."
        )


def download_audio(url, job_folder, max_retries=3, use_oauth=True):
    """Download audio from YouTube URL using yt-dlp"""
    import yt_dlp  # Deferred: slow import, only needed on actual download

    mp3_path = os.path.join(job_folder, 'audio_source.mp3')

    if os.path.exists(mp3_path):
        print(f"✓ Audio already downloaded")
        return mp3_path

    _validate_youtube_url(url)
    print(f"Downloading audio...")

    temp_base = os.path.join(job_folder, 'yt_temp')

    base_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': temp_base + '.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '2',
        }],
        'quiet': True,
        'no_warnings': True,
        'retries': max_retries,
        # YouTube ships JS signature/n-sig challenges that must be solved by an external JS runtime.
        # 'ejs:github' tells yt-dlp to download the EJS solver script from the official repo.
        'remote_components': ['ejs:github'],
    }

    cookies_file = _find_cookies_file()
    if cookies_file:
        base_opts['cookiefile'] = cookies_file
        print(f"  Using cookies from {os.path.basename(cookies_file)}")

    def _run(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        temp_mp3 = temp_base + '.mp3'
        if os.path.exists(temp_mp3):
            os.rename(temp_mp3, mp3_path)
        if not os.path.exists(mp3_path):
            raise Exception("MP3 file not found after download")
        return mp3_path

    def _is_bot_check(e):
        msg = str(e).lower()
        return "sign in" in msg or "confirm you" in msg or "not a bot" in msg

    def _raise_if_fatal(e):
        msg = str(e).lower()
        if "music premium" in msg or "premium members" in msg:
            raise ValueError(
                "This song requires a YouTube Music Premium subscription and cannot be downloaded.\n\n"
                "How to fix: Replace the YouTube URL with a free (non-Music Premium) upload of the same song."
            ) from None
        if any(x in msg for x in ["age-restricted", "private video", "unavailable", "copyright"]):
            raise ValueError(
                f"This video cannot be downloaded: {str(e)[:100]}\n\n"
                "How to fix: Replace the YouTube URL with a different upload of the same song."
            ) from None

    # Phase 1: attempt without cookies
    last_exc = None
    for attempt in range(max_retries):
        try:
            return _run(base_opts)
        except Exception as e:
            _raise_if_fatal(e)
            if _is_bot_check(e):
                last_exc = e
                break  # go straight to cookie phase, retrying bare won't help
            msg = str(e).lower()
            if "429" in msg or "rate" in msg:
                print(f"⚠️  Rate limited, waiting 15s...")
                time.sleep(15)
            elif "403" in msg or "forbidden" in msg:
                print(f"⚠️  Access denied, waiting 5s...")
                time.sleep(5)
            last_exc = e
            if attempt < max_retries - 1:
                print(f"  Download failed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(2)

    # Phase 2: bot check — retry with browser cookies
    if last_exc and _is_bot_check(last_exc):
        print(f"  Bot check triggered, retrying with browser cookies...")
        for browser in _COOKIE_BROWSERS:
            try:
                opts = {**base_opts, 'cookiesfrombrowser': (browser,)}
                result = _run(opts)
                print(f"✓ Downloaded using {browser} cookies")
                return result
            except Exception as e:
                _raise_if_fatal(e)
                if _is_bot_check(e):
                    continue  # this browser didn't satisfy YouTube, try next
                last_exc = e
                break  # non-bot error, stop trying browsers
        raise ValueError(
            "YouTube requires sign-in but no browser cookies worked.\n\n"
            "How to fix: Sign into YouTube in Chrome or Edge, then retry."
        ) from None

    print(f"❌ Download failed after {max_retries} attempts: {last_exc}")
    raise last_exc


def mmss_to_milliseconds(time_str):
    """Convert MM:SS to milliseconds"""
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError("Time must be in MM:SS format")
        
        minutes, seconds = map(int, parts)
        return (minutes * 60 + seconds) * 1000
    except Exception as e:
        print(f"❌ Invalid time format '{time_str}': {e}")
        raise


def trim_audio(job_folder, start_time, end_time):
    """Trim audio file to specified timestamps (MM:SS format)"""
    audio_path = os.path.join(job_folder, 'audio_source.mp3')
    
    if not os.path.exists(audio_path):
        print(f"❌ Audio source not found: {audio_path}")
        return None
    
    try:
        song = AudioSegment.from_file(audio_path, format="mp3")
        
        start_ms = mmss_to_milliseconds(start_time)
        end_ms = mmss_to_milliseconds(end_time)
        
        if start_ms >= end_ms:
            print("❌ Start time must be before end time")
            return None
        
        clip = song[start_ms:end_ms]
        
        export_path = os.path.join(job_folder, "audio_trimmed.wav")
        clip.export(export_path, format="wav")
        
        duration = (end_ms - start_ms) / 1000
        print(f"✓ Trimmed audio: {duration:.1f}s clip created")
        
        return export_path
        
    except Exception as e:
        print(f"❌ Audio trimming failed: {e}")
        raise


def detect_beats(job_folder):
    """
    Detect beats in trimmed audio using librosa.
    Used by Aurora for beat-synced effects. Mono/Onyx don't need this.
    """
    import librosa
    
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print(f"❌ Trimmed audio not found: {audio_path}")
        return []
    
    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        beats_list = [float(t) for t in beat_times]
        
        if hasattr(tempo, '__len__'):
            tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
        else:
            tempo_val = float(tempo)
        
        print(f"✓ Detected {len(beats_list)} beats (tempo ≈ {tempo_val:.1f} BPM)")
        
        return beats_list
        
    except Exception as e:
        print(f"⚠️  Beat detection failed: {e}")
        return []


def normalize_audio(audio_path):
    """
    Normalize audio to -20 dBFS for consistent Whisper input levels.
    Caches result as *_norm.wav to avoid re-processing.
    Returns (normalized_path, duration_seconds).
    """
    base, _ = os.path.splitext(audio_path)
    norm_path = base + '_norm.wav'
    if os.path.exists(norm_path):
        try:
            with wave.open(norm_path, 'rb') as wf:
                duration = wf.getnframes() / wf.getframerate()
            return norm_path, duration
        except Exception:
            # Corrupt cache — delete and re-normalize
            os.remove(norm_path)
    try:
        audio = AudioSegment.from_file(audio_path)
        duration = len(audio) / 1000.0
        if audio.dBFS == float('-inf'):
            return audio_path, duration
        change = -20.0 - audio.dBFS
        normalized = audio.apply_gain(change)
        normalized.export(norm_path, format='wav')
        print("  Audio normalized to -20 dBFS")
        return norm_path, duration
    except Exception as e:
        print(f"  Normalization failed: {e}")
        return audio_path, None


def reduce_noise(audio_path):
    """
    Apply stationary noise reduction to remove reverb tails and recording noise.
    Caches result as *_clean.wav. Falls back to original if noisereduce unavailable.
    """
    base, _ = os.path.splitext(audio_path)
    clean_path = base + '_clean.wav'
    if os.path.exists(clean_path):
        return clean_path
    try:
        import noisereduce as nr
        import librosa
        import soundfile as sf
        y, sr = librosa.load(audio_path, sr=16000)
        y_clean = nr.reduce_noise(y=y, sr=sr, stationary=True, prop_decrease=0.75)
        sf.write(clean_path, y_clean, sr)
        print("  Noise reduction applied")
        return clean_path
    except ImportError:
        print("  noisereduce not installed, skipping noise reduction")
        return audio_path
    except Exception as e:
        print(f"  Noise reduction failed: {e}")
        return audio_path

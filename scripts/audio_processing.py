import os
import time
import yt_dlp
from pydub import AudioSegment
import librosa


def download_audio(url, job_folder, max_retries=3):
    output_path = os.path.join(job_folder, 'audio_source.%(ext)s')
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }]
    }
    
    for attempt in range(max_retries):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            mp3_path = os.path.join(job_folder, 'audio_source.mp3')
            
            if os.path.exists(mp3_path):
                return mp3_path
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Download failed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f" Download failed after {max_retries} attempts: {e}")
                raise
    
    return None


def mmss_to_milliseconds(time_str):
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            raise ValueError("Time must be in MM:SS format")
        
        minutes, seconds = map(int, parts)
        return (minutes * 60 + seconds) * 1000
    except Exception as e:
        print(f" Invalid time format '{time_str}': {e}")
        raise


def trim_audio(job_folder, start_time, end_time):
    audio_path = os.path.join(job_folder, 'audio_source.mp3')
    
    if not os.path.exists(audio_path):
        print(f" Audio source not found: {audio_path}")
        return None
    
    try:
        # Load audio
        song = AudioSegment.from_file(audio_path, format="mp3")
        
        # Convert timestamps
        start_ms = mmss_to_milliseconds(start_time)
        end_ms = mmss_to_milliseconds(end_time)
        
        if start_ms >= end_ms:
            print(" Start time must be before end time")
            return None
        
        # Trim
        clip = song[start_ms:end_ms]
        
        # Export
        export_path = os.path.join(job_folder, "audio_trimmed.wav")
        clip.export(export_path, format="wav")
        
        duration = (end_ms - start_ms) / 1000
        print(f" Trimmed audio: {duration:.1f}s clip created")
        
        return export_path
        
    except Exception as e:
        print(f" Audio trimming failed: {e}")
        raise


def detect_beats(job_folder):
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print(f" Trimmed audio not found: {audio_path}")
        return []
    
    try:
        # Load audio
        y, sr = librosa.load(audio_path, sr=None)
        
        # Detect beats
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        beats_list = [float(t) for t in beat_times]
        
        # Extract tempo value
        if hasattr(tempo, '__len__'):
            tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
        else:
            tempo_val = float(tempo)
        
        print(f" Detected {len(beats_list)} beats (tempo ≈ {tempo_val:.1f} BPM)")
        
        return beats_list
        
    except Exception as e:
        print(f"  Beat detection failed: {e}")
        return []
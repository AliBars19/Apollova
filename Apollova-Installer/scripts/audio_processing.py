"""Audio processing with pytubefix and OAuth login"""
import os
import time
from pytubefix import YouTube
from pydub import AudioSegment
import librosa
import subprocess


def download_audio(url, job_folder, max_retries=3, use_oauth=True):
    """Download audio from YouTube URL using pytubefix with OAuth"""
    mp3_path = os.path.join(job_folder, 'audio_source.mp3')
    
    if os.path.exists(mp3_path):
        print(f"✓ Audio already downloaded")
        return mp3_path
    
    print(f"Downloading audio...")
    
    for attempt in range(max_retries):
        try:
            yt = YouTube(
                url,
                use_oauth=use_oauth,
                allow_oauth_cache=True
            )
            
            audio_stream = yt.streams.filter(
                only_audio=True
            ).order_by('abr').desc().first()
            
            if not audio_stream:
                print(f"❌ No audio streams available")
                return None
            
            temp_file = os.path.join(job_folder, f"temp_audio_{yt.video_id}.{audio_stream.subtype}")
            audio_stream.download(output_path=job_folder, filename=f"temp_audio_{yt.video_id}.{audio_stream.subtype}")
            
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", temp_file,
                "-vn",
                "-acodec", "libmp3lame",
                "-q:a", "2",
                mp3_path
            ]
            subprocess.run(cmd, check=True)
            
            if os.path.exists(temp_file):
                os.remove(temp_file)
            
            if os.path.exists(mp3_path):
                print(f"✓ Audio downloaded")
                return mp3_path
            else:
                raise Exception("MP3 conversion failed")
                
        except Exception as e:
            error_msg = str(e).lower()
            
            if "bot" in error_msg:
                if attempt == 0 and not use_oauth:
                    print(f"⚠️ Bot detected, retrying with login...")
                    return download_audio(url, job_folder, max_retries=max_retries-1, use_oauth=True)
                else:
                    print(f"⚠️ Bot detection, waiting 30s...")
                    time.sleep(30)
            elif "400" in error_msg:
                print(f"⚠️ HTTP 400 error, waiting 5s...")
                time.sleep(5)
            elif "429" in error_msg:
                print(f"⚠️ Rate limited, waiting 15s...")
                time.sleep(15)
            
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries}...")
                time.sleep(2)
            else:
                print(f"❌ Download failed: {e}")
                raise
    
    return None


def mmss_to_milliseconds(time_str):
    """Convert MM:SS to milliseconds"""
    parts = time_str.split(':')
    if len(parts) != 2:
        raise ValueError("Time must be in MM:SS format")
    minutes, seconds = map(int, parts)
    return (minutes * 60 + seconds) * 1000


def trim_audio(job_folder, start_time, end_time):
    """Trim audio file to specified timestamps"""
    audio_path = os.path.join(job_folder, 'audio_source.mp3')
    
    if not os.path.exists(audio_path):
        print(f"❌ Audio source not found")
        return None
    
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
    print(f"✓ Trimmed: {duration:.1f}s")
    
    return export_path


def detect_beats(job_folder):
    """Detect beats in trimmed audio"""
    audio_path = os.path.join(job_folder, "audio_trimmed.wav")
    
    if not os.path.exists(audio_path):
        print(f"❌ Trimmed audio not found")
        return []
    
    y, sr = librosa.load(audio_path, sr=None)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    beats_list = [float(t) for t in beat_times]
    
    if hasattr(tempo, '__len__'):
        tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        tempo_val = float(tempo)
    
    print(f"✓ {len(beats_list)} beats ({tempo_val:.0f} BPM)")
    
    return beats_list

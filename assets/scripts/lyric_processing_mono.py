"""
Mono Lyric Processing - Word-level timestamp extraction
For minimal text-only lyric videos with word-by-word reveal.
Delegates to the shared whisper_common.transcribe_word_level pipeline.

Output: markers with {time, text, words[], color, end_time}
"""
from scripts import whisper_common


def transcribe_audio_mono(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Mono style videos.

    Returns dict with:
        - markers: list of marker objects for JSX
        - total_markers: count of markers
    """
    return whisper_common.transcribe_word_level(
        job_folder=job_folder,
        song_title=song_title,
        template_name="Mono",
        regroup_passes=[True, True, True, True],
    )

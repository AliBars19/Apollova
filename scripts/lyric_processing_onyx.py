"""
Onyx Lyric Processing - Word-level timestamp extraction
For hybrid template: word-by-word lyrics + spinning disc.
Delegates to the shared whisper_common.transcribe_word_level pipeline
with additional regrouping for shorter segments.

Output: markers with {time, text, words[], color, end_time}
"""
from scripts import whisper_common


def _onyx_regroup(result):
    """Post-transcription regrouping — Onyx benefits from shorter segments."""
    original = result
    try:
        result = result.split_by_gap(0.5)
        result = result.split_by_punctuation(['.', '?', '!', ','])
        result = result.split_by_length(max_chars=50)
    except Exception as e:
        print(f"  \u26a0 Regrouping failed (using defaults): {e}")
        return original
    return result


def transcribe_audio_onyx(job_folder, song_title=None):
    """
    Transcribe audio with word-level timestamps for Onyx style videos.

    Returns dict with:
        - markers: list of marker objects for JSX
        - total_markers: count of markers
    """
    return whisper_common.transcribe_word_level(
        job_folder=job_folder,
        song_title=song_title,
        template_name="Onyx",
        regroup_passes=[False, False, False, True],
        post_transcribe_fn=_onyx_regroup,
    )

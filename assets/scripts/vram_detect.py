"""GPU VRAM detection and Whisper model recommendation."""


def detect_gpu_vram() -> int | None:
    """Return GPU VRAM in MB, or None if no CUDA GPU available."""
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return props.total_mem // (1024 * 1024)
    except ImportError:
        pass
    return None


def recommend_whisper_model(vram_mb: int | None) -> str:
    """Recommend a Whisper model based on available VRAM.

    Returns one of: 'small', 'medium', 'large-v3'
    """
    if vram_mb is None:
        return "small"
    if vram_mb < 4096:
        return "small"
    if vram_mb < 8192:
        return "medium"
    return "large-v3"


def get_recommendation_label(vram_mb: int | None) -> str:
    """Human-readable label for the settings UI."""
    if vram_mb is None:
        return "No GPU detected — Recommended: small"
    model = recommend_whisper_model(vram_mb)
    gb = vram_mb / 1024
    return f"Detected: {gb:.1f} GB VRAM — Recommended: {model}"

import os
import re
from markupsafe import Markup

from app.classes import AudioProfile

filters = {}

def template_filter(name):
    """Decorator to register a Jinja2 filter."""
    def decorator(func):
        filters[name] = func
        return func
    return decorator

@template_filter('highlight')
def highlight_search(text: str, search_query: str) -> Markup:
    if not search_query:
        return text
    
    search_query_escaped = re.escape(search_query)

    # If the text matches the search query exactly, apply a different highlight
    if text.strip().lower() == search_query.strip().lower():
        return Markup(f'<mark style="background-color: lightgreen; color: black;">{text}</mark>')
    
    # Highlight partial matches in the text
    highlighted_text = re.sub(
        f"({search_query_escaped})",
        r'<mark>\1</mark>',
        text,
        flags=re.IGNORECASE
    )
    return Markup(highlighted_text)


@template_filter('audioprofile')
def audioprofile(text: str, path: str) -> Markup:
    if not path or not os.path.exists(path):
        return Markup()  # Return the original text if the file does not exist

    # Create the AudioProfile instance using the static method
    audio_profile = AudioProfile.analyze_audio_quality_with_ffprobe(path)
    if not audio_profile:
        return Markup(f"<span style='color: red;'>ERROR</span>")

    # Create a nicely formatted HTML representation
    audio_profile_html = (
        f"<strong>Bitrate:</strong> {audio_profile.bitrate} kbps<br>"
        f"<strong>Sample Rate:</strong> {audio_profile.sample_rate} Hz<br>"
        f"<strong>Channels:</strong> {audio_profile.channels}<br>"
        f"<strong>Quality Score:</strong> {audio_profile.compute_quality_score()}"
        f"</div>"
    )
    return Markup(audio_profile_html)

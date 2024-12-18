import os
import re
from markupsafe import Markup

from app.classes import AudioProfile
from app import app, functions, read_dev_build_file
from .version import __version__

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
        
    )
    return Markup(audio_profile_html)

@template_filter('version_check')
def version_check(version: str) -> Markup:
    version = f"{__version__}{read_dev_build_file()}"
    # if version contains a dash and the text after the dash is LOCAL, return version as a blue badge
    if app.config['CHECK_FOR_UPDATES']:
        if '-' in version and version.split('-')[1] == 'LOCAL':
            return Markup(f"<span class='badge rounded-pill bg-primary'>{version}</span>")
        # else if the version string contains a dash and the text after the dash is not LOCAL, check whether it contains another dash (like in e.g. v0.1.7-dev-89a1bc2) and split both parts 
        elif '-' in version and version.split('-')[1] != 'LOCAL' :
            branch, commit_sha = version.split('-')[1], version.split('-')[2]
            nra,url =  functions.get_latest_dev_releases(branch_name = branch, commit_sha = commit_sha)
            if nra:
                return Markup(f"<a href='{url}' target='_blank'><span class='badge rounded-pill text-bg-warning btn-pulsing' data-bs-toggle='tooltip' title='An update for the {branch} branch is available.'>{version}</span></a>")
            else:
                return Markup(f"<span class='badge rounded-pill text-bg-secondary'>{version}</span>")
        else:
            nra,url = functions.get_latest_release(version)
            if nra:
                return Markup(f"<a href='{url}' target='_blank'><span class='badge rounded-pill text-bg-warning btn-pulsing' data-bs-toggle='tooltip' title='An update is available.'>{version}</span></a>")
            
            
        return Markup(f"<span class='badge rounded-pill text-bg-primary'>{version}</span>")
    else:
        return Markup(f"<span class='badge rounded-pill text-bg-info'>{version}</span>")
        
        
        
    
    
    
    

@template_filter('jellyfin_link')
def jellyfin_link(jellyfin_id: str) -> Markup:

    jellyfin_server_url = app.config.get('JELLYFIN_SERVER_URL')
    if not jellyfin_server_url:
        return Markup(f"<span style='color: red;'>JELLYFIN_SERVER_URL not configured</span>")

    link = f"{jellyfin_server_url}/web/#/details?id={jellyfin_id}"
    return Markup(f'<a href="{link}" target="_blank">{jellyfin_id}</a>')

# A template filter for displaying a datetime in a human-readable format
@template_filter('human_datetime')
def human_datetime(dt) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S')
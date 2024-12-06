import json
from typing import List, Optional
from flask import flash, redirect, session, url_for,g
import requests
from app.classes import CombinedPlaylistData, CombinedTrackData
from app.models import JellyfinUser, Playlist,Track  
from app import  sp, cache, app, jellyfin  ,jellyfin_admin_token, jellyfin_admin_id,device_id, cache, redis_client
from functools import  wraps
from celery.result import AsyncResult
from app.providers import base
from app.providers.base import PlaylistTrack
from app.registry.music_provider_registry import MusicProviderRegistry
from lidarr.classes import Album, Artist
from . import tasks
from jellyfin.objects import PlaylistMetadata
from spotipy.exceptions import SpotifyException

import re

def prepPlaylistData(playlist: base.Playlist) -> Optional[CombinedPlaylistData]:
    jellyfin_user = JellyfinUser.query.filter_by(jellyfin_user_id=session['jellyfin_user_id']).first()
    if not jellyfin_user:
        app.logger.error(f"jellyfin_user not set: session user id: {session['jellyfin_user_id']}. Logout and Login again")
        return None

    # Fetch the playlist from the database if it exists
    db_playlist : Playlist = Playlist.query.filter_by(provider_playlist_id=playlist.id).first() if playlist else None

    # Initialize default values
    track_count = db_playlist.track_count if db_playlist else 0
    tracks_available = db_playlist.tracks_available if db_playlist else 0
    tracks_linked = len([track for track in db_playlist.tracks if track.jellyfin_id]) if db_playlist else 0
    percent_available = (tracks_available / track_count * 100) if track_count > 0 else 0

    # Determine playlist status
    if tracks_available == track_count and track_count > 0:
        status = 'green'  # Fully available
    elif tracks_available > 0:
        status = 'yellow'  # Partially available
    else:
        status = 'red'  # Not available

    # Build and return the PlaylistResponse object
    return CombinedPlaylistData(
        name=playlist.name,
        description=playlist.description,
        image=playlist.images[0].url if playlist.images else '/static/images/placeholder.png',
        url=playlist.external_urls[0].url if playlist.external_urls else '',
        id=playlist.id,
        jellyfin_id=db_playlist.jellyfin_id if db_playlist else '',
        can_add=(db_playlist not in jellyfin_user.playlists) if db_playlist else True,
        can_remove=(db_playlist in jellyfin_user.playlists) if db_playlist else False,
        last_updated=db_playlist.last_updated if db_playlist else None,
        last_changed=db_playlist.last_changed if db_playlist else None,
        tracks_available=tracks_available,
        track_count=track_count,
        tracks_linked=tracks_linked,
        percent_available=percent_available,
        status=status
    )

def lidarr_quality_profile_id(profile_id=None):
    if app.config['LIDARR_API_KEY'] and app.config['LIDARR_URL']:
        from app import lidarr_client    
        if profile_id:
            redis_client.set('lidarr_quality_profile_id', profile_id)
        else:
            value = redis_client.get('lidarr_quality_profile_id')
            if not value:
                value = lidarr_client.get_quality_profiles()[0]
                lidarr_quality_profile_id(value.id)
                return value
            return value

def lidarr_root_folder_path(folder_path=None):
    if app.config['LIDARR_API_KEY'] and app.config['LIDARR_URL']:
        from app import lidarr_client   
        if folder_path:
            redis_client.set('lidarr_root_folder_path', folder_path)
        else:
            value = redis_client.get('lidarr_root_folder_path')
            if not value:
                value = lidarr_client.get_root_folders()[0]
                lidarr_root_folder_path(value.path)
                return value.path
            return value
            
# a function which takes a lidarr.class.Artist object as a parameter, and applies the lidarr_quality_profile_id to the artist if its 0
def apply_default_profile_and_root_folder(object : Artist ) -> Artist:
    if object.qualityProfileId == 0:
        object.qualityProfileId = int(lidarr_quality_profile_id())
    if object.rootFolderPath == '' or object.rootFolderPath == None:
        object.rootFolderPath = str(lidarr_root_folder_path())
    if object.metadataProfileId == 0:
        object.metadataProfileId = 1
    return object

@cache.memoize(timeout=3600*24*10) 
def get_cached_provider_track(track_id : str,provider_id : str)-> base.Track:
    """
    Fetches a Spotify track by its ID, utilizing caching to minimize API calls.

    :param track_id: The Spotify playlist ID.
    :return: Track data as a dictionary, or None if an error occurs.
    """
    try:
        # get the provider from the registry
        provider = MusicProviderRegistry.get_provider(provider_id)
        track_data = provider.get_track(track_id)
        return track_data
    except Exception as e:
        app.logger.error(f"Error fetching track {track_id} from {provider_id}: {str(e)}")
        return None


def get_tracks_for_playlist(data: List[PlaylistTrack], provider_id : str ) -> List[CombinedTrackData]:
    is_admin = session.get('is_admin', False)
    tracks = []

    for idx, item in enumerate(data):
        track_data = item.track
        if track_data:
            duration_ms = track_data.duration_ms
            minutes = duration_ms // 60000
            seconds = (duration_ms % 60000) // 1000

            # Query track from the database
            track_db = Track.query.filter_by(provider_track_id=track_data.id).first()

            if track_db:
                downloaded = track_db.downloaded
                filesystem_path = track_db.filesystem_path if is_admin else None
                jellyfin_id = track_db.jellyfin_id
                download_status = track_db.download_status
            else:
                downloaded = False
                filesystem_path = None
                jellyfin_id = None
                download_status = None

            # Append a TrackResponse object
            tracks.append(
                CombinedTrackData(
                    title=track_data.name,
                    artist=[a.name for a in track_data.artists],
                    url=[url.url for url in track_data.external_urls],
                    duration=f'{minutes}:{seconds:02d}',
                    downloaded=downloaded,
                    filesystem_path=filesystem_path,
                    jellyfin_id=jellyfin_id,
                    provider_track_id=track_data.id,
                    provider_id = provider_id,
                    duration_ms=duration_ms,
                    download_status=download_status,
                    provider=provider_id
                )
            )
    
    return tracks

def jellyfin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'jellyfin_user_name' not in session:
            flash('You need to log in using your Jellyfin Credentials to access this page.', 'warning')
            return redirect(url_for('login'))  
        return f(*args, **kwargs)
    return decorated_function

def jellyfin_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session['is_admin']:
            flash('You need to be a Jellyfin admin.', 'warning')
            return 404  # Redirect to your login route
        return f(*args, **kwargs)
    return decorated_function




def update_playlist_metadata(playlist,provider_playlist_data : base.Playlist):
    metadata = PlaylistMetadata()
    metadata.Tags = [f'jellyplist:playlist:{playlist.id}',f'{playlist.tracks_available} of {playlist.track_count} Tracks available']
    metadata.Overview = provider_playlist_data.description
    jellyfin.update_playlist_metadata(session_token=_get_api_token(),playlist_id=playlist.jellyfin_id,updates= metadata , user_id= _get_admin_id())
    if provider_playlist_data.images:
        jellyfin.set_playlist_cover_image(session_token= _get_api_token(),playlist_id= playlist.jellyfin_id,provider_image_url= provider_playlist_data.images[0].url)



def _get_token_from_sessioncookie() -> str:
    return session['jellyfin_access_token']
def _get_api_token() -> str:
    #return app.config['JELLYFIN_ACCESS_TOKEN']
    return jellyfin_admin_token
def _get_logged_in_user() -> JellyfinUser:
    return JellyfinUser.query.filter_by(jellyfin_user_id=session['jellyfin_user_id']).first()  
def _get_admin_id():
    #return JellyfinUser.query.filter_by(is_admin=True).first().jellyfin_user_id
    return jellyfin_admin_id


def get_longest_substring(input_string):
    special_chars = ["'", "’", "‘", "‛", "`", "´", "‘"]
    pattern = "[" + re.escape("".join(special_chars)) + "]"
    substrings = re.split(pattern, input_string)
    longest_substring = max(substrings, key=len, default="")
    return longest_substring

@cache.memoize(timeout=3600*2)
def get_latest_dev_releases(branch_name :str, commit_sha : str):
    try:
        response = requests.get('https://api.github.com/repos/kamilkosek/jellyplist/releases')
        if response.status_code == 200:
            data = response.json()
            latest_release = None
            for release in data:
                if branch_name in release['tag_name']:
                    if latest_release is None or release['published_at'] > latest_release['published_at']:
                        latest_release = release
                        
            if latest_release:
                response = requests.get(f'https://api.github.com/repos/kamilkosek/jellyplist/git/ref/tags/{latest_release["tag_name"]}')
                if response.status_code == 200:
                    data = response.json()
                    if commit_sha != data['object']['sha'][:7]:
                        return True, latest_release['html_url']
                            
                        
        return False, ''
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching latest version: {str(e)}")
    return False, ''

@cache.memoize(timeout=3600*2)
def get_latest_release(tag_name :str):
    try:
        response = requests.get('https://api.github.com/repos/kamilkosek/jellyplist/releases/latest')
        if response.status_code == 200:
            data = response.json()
            if data['tag_name'] != tag_name:
                return True, data['html_url']
        return False, ''
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching latest version: {str(e)}")
    return False,''
import json
from typing import Optional
from flask import flash, redirect, session, url_for
import requests
from app.models import JellyfinUser, Playlist,Track  
from app import sp, cache, app, jellyfin  ,jellyfin_admin_token, jellyfin_admin_id,device_id, cache
from functools import  wraps
from celery.result import AsyncResult
from app.tasks import download_missing_tracks,check_for_playlist_updates, update_all_playlists_track_status, update_jellyfin_id_for_downloaded_tracks
from jellyfin.objects import PlaylistMetadata
from spotipy.exceptions import SpotifyException

import re

TASK_STATUS = {
    'update_all_playlists_track_status': None,
    'download_missing_tracks': None,
    'check_for_playlist_updates': None,
    'update_jellyfin_id_for_downloaded_tracks' : None
}
LOCK_KEYS = [
    'update_all_playlists_track_status_lock',    
    'download_missing_tracks_lock',
    'check_for_playlist_updates_lock',
    'update_jellyfin_id_for_downloaded_tracks_lock' ,
    'full_update_jellyfin_ids' 

]

def manage_task(task_name):
    task_id = TASK_STATUS.get(task_name)
    
    if task_id:
        result = AsyncResult(task_id)
        if result.state in ['PENDING', 'STARTED']: 
            return result.state, result.info if result.info else {}
    if task_name == 'update_all_playlists_track_status':
        result = update_all_playlists_track_status.delay()
    elif task_name == 'download_missing_tracks':
        result = download_missing_tracks.delay()
    elif task_name == 'check_for_playlist_updates':
        result = check_for_playlist_updates.delay()
    elif task_name == 'update_jellyfin_id_for_downloaded_tracks':
        result = update_jellyfin_id_for_downloaded_tracks.delay()

    TASK_STATUS[task_name] = result.id  
    return result.state, result.info if result.info else {}


def prepPlaylistData(data):
    playlists = []
    jellyfin_user = JellyfinUser.query.filter_by(jellyfin_user_id=session['jellyfin_user_id']).first()
    if not jellyfin_user:
        app.logger.error(f"jellyfin_user not set: session user id: {session['jellyfin_user_id']}. Logout and Login again")
        return None
    if not data.get('playlists'):
        
        data['playlists']= {}
        data['playlists']['items'] = [data]
        
    for playlist_data in data['playlists']['items']:
        # Fetch the playlist from the database if it exists
        if playlist_data:
            db_playlist = Playlist.query.filter_by(provider_playlist_id=playlist_data['id']).first()

            if db_playlist:
                # If the playlist is in the database, use the stored values
                if playlist_data.get('tracks'):
                    if isinstance(playlist_data['tracks'],list):
                        track_count = len(playlist_data['tracks']    )
                    else:
                        track_count = playlist_data['tracks']['total'] or 0
                else:
                    track_count = 0
                tracks_available = db_playlist.tracks_available or 0
                tracks_linked = len([track for track in db_playlist.tracks if track.jellyfin_id]) or 0
                percent_available = (tracks_available / track_count * 100) if track_count > 0 else 0
                
                # Determine playlist status
                if not playlist_data.get('status'):
                    if tracks_available == track_count and track_count > 0:
                        playlist_data['status'] = 'green'  # Fully available
                    elif tracks_available > 0:
                        playlist_data['status'] = 'yellow'  # Partially available
                    else:
                        playlist_data['status'] = 'red'  # Not available
                 
            else:
                # If the playlist is not in the database, initialize with 0
                track_count = 0
                tracks_available = 0
                tracks_linked  = 0 
                percent_available = 0
                playlist_data['status'] = 'red'  # Not requested yet

            # Append playlist data to the list
            playlists.append({
                'name': playlist_data['name'],
                'description': playlist_data['description'],
                'image': playlist_data['images'][0]['url'] if playlist_data.get('images') else '/static/images/placeholder.png',
                'url': playlist_data['external_urls']['spotify'] if playlist_data.get('external_urls') else '',
                'id': playlist_data['id'] if playlist_data['id'] else '',
                'jellyfin_id': db_playlist.jellyfin_id if db_playlist else '',
                'can_add': (db_playlist not in jellyfin_user.playlists) if db_playlist else True,
                'can_remove' : (db_playlist in jellyfin_user.playlists) if db_playlist else False, 
                'last_updated':db_playlist.last_updated if db_playlist else '',
                'last_changed':db_playlist.last_changed if db_playlist else '',
                'tracks_available': tracks_available,
                'track_count': track_count,
                'tracks_linked': tracks_linked,
                'percent_available': percent_available,
                'status': playlist_data['status']  # Red, yellow, or green based on availability
            })
    
    return playlists

def get_cached_spotify_playlists(playlist_ids):
    """
    Fetches multiple Spotify playlists by their IDs, utilizing individual caching.

    :param playlist_ids: A list of Spotify playlist IDs.
    :return: A dictionary containing the fetched playlists.
    """
    spotify_data = {'playlists': {'items': []}}
    
    for playlist_id in playlist_ids:
        playlist_data = None
        not_found = False
        try:
            playlist_data = get_cached_spotify_playlist(playlist_id)
            
        except SpotifyException as e:
            app.logger.error(f"Error Fetching Playlist {playlist_id}: {e}")
            not_found = 'http status: 404' in str(e)
        if not_found:
            playlist_data = {
                'status':'red',
                'description': 'Playlist has most likely been removed. You can keep it, but won´t receive Updates.',
                'id': playlist_id,
                'name' : ''
                
            }

        if playlist_data:
            spotify_data['playlists']['items'].append(playlist_data)
    
    return spotify_data

@cache.memoize(timeout=3600)
def get_cached_playlist(playlist_id):
    """
    Fetches a Spotify playlist by its ID, utilizing caching to minimize API calls.

    :param playlist_id: The Spotify playlist ID.
    :return: Playlist data as a dictionary, or None if an error occurs.
    """
    # When the playlist_id starts with 37i9dQZF1, we need to use the new function
    # as the standard Spotify API endpoints are deprecated for these playlists.
    # Reference: https://github.com/kamilkosek/jellyplist/issues/25
    
    if playlist_id.startswith("37i9dQZF1"):
        app.logger.warning(f"Algorithmic or Spotify-owned editorial playlist, using custom Implementation to fetch details")
        # Use the custom implementation for these playlists
        try:
            data = fetch_spotify_playlist(playlist_id)
            return transform_playlist_response(data)
        except Exception as e:
            print(f"Error fetching playlist with custom method: {e}")
            return None

    # Otherwise, use the standard Spotipy API
    try:
        playlist_data = sp.playlist(playlist_id)  # Fetch data using Spotipy
        return playlist_data
    except Exception as e:
        print(f"Error fetching playlist with Spotipy: {e}")
        return None

@cache.memoize(timeout=3600*24*10)  
def get_cached_spotify_track(track_id):
    """
    Fetches a Spotify track by its ID, utilizing caching to minimize API calls.

    :param track_id: The Spotify playlist ID.
    :return: Track data as a dictionary, or None if an error occurs.
    """
    try:
        track_data = sp.track(track_id=track_id)  # Fetch data from Spotify API
        return track_data
    except Exception as e:
        app.logger.error(f"Error fetching track {track_id} from Spotify: {str(e)}")
        return None


def prepAlbumData(data):
    items = []
    for item in data['albums']['items']:
        items.append({
            'name': item['name'],
            'description': f"Released: {item['release_date']}",
            'image': item['images'][0]['url'] if item['images'] else 'default-image.jpg',
            'url': item['external_urls']['spotify'],
            'id' : item['id'],
            'can_add' : False
        })
    return items

def prepArtistData(data):
    items = []
    for item in data['artists']['items']:
        items.append({
            'name': item['name'],
            'description': f"Popularity: {item['popularity']}",
            'image': item['images'][0]['url'] if item['images'] else 'default-image.jpg',
            'url': item['external_urls']['spotify'],
            'id' : item['id'],
            'can_add' : False
            
        })
    return items



def getFeaturedPlaylists(country: str, offset: int):
    try:
        playlists_data = sp.featured_playlists(country=country, limit=16, offset=offset)
        return prepPlaylistData(playlists_data), playlists_data['playlists']['total'], 'Featured Playlists'
    except SpotifyException as e:
        app.logger.error(f"Spotify API error in getFeaturedPlaylists: {e}")
        return [], e, f'Error: Could not load featured playlists. Please try again later. This is most likely due to an Error in the Spotify API or an rate limit has been reached.'

def getCategoryPlaylists(category: str, offset: int):
    try:
        playlists_data = sp.category_playlists(category_id=category, country=app.config['SPOTIFY_COUNTRY_CODE'], limit=16, offset=offset)
        return prepPlaylistData(playlists_data), playlists_data['playlists']['total'], f"Category {playlists_data['message']}"
    except SpotifyException as e:
        app.logger.error(f"Spotify API error in getCategoryPlaylists: {e}")
        return [], e, 'Error: Could not load category playlists. Please try again later. This is most likely due to an Error in the Spotify API or an rate limit has been reached.'

def getCategories(country,offset):
    categories_data = sp.categories(limit=16, offset= offset)
    categories = []

    for cat in categories_data['categories']['items']:
        categories.append({
            'name': cat['name'],
            'description': '',
            'image': cat['icons'][0]['url'] if cat['icons'] else 'default-image.jpg',
            'url': f"/playlists?cat={cat['id']}",
            'id' : cat['id'],
            'type':'category'
        })
    return categories, categories_data['categories']['total'],'Browse Categories'

def get_tracks_for_playlist(data):
    results = data
    tracks = []
    is_admin = session.get('is_admin', False)

    for idx, item in enumerate(results['tracks']['items']):
        track_data = item['track']
        if track_data:
            duration_ms = track_data['duration_ms']
            minutes = duration_ms // 60000
            seconds = (duration_ms % 60000) // 1000

            track_db = Track.query.filter_by(provider_track_id=track_data['id']).first()

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

            tracks.append({
                'title': track_data['name'],
                'artist': ', '.join([artist['name'] for artist in track_data['artists']]),
                'url': track_data['external_urls']['spotify'],
                'duration': f'{minutes}:{seconds:02d}', 
                'preview_url': track_data['preview_url'],
                'downloaded': downloaded,  
                'filesystem_path': filesystem_path,  
                'jellyfin_id': jellyfin_id,
                'spotify_id': track_data['id'],
                'duration_ms': duration_ms,
                'download_status'  : download_status
            })
        
    return tracks

def get_full_playlist_data(playlist_id):
    playlist_data = get_cached_spotify_playlist(playlist_id)
    all_tracks = []

    offset = 0
    while True:
        response = sp.playlist_items(playlist_id, offset=offset, limit=100)
        items = response['items']
        all_tracks.extend(items)
        
        if len(items) < 100:
            break
        offset += 100  

    playlist_data['tracks'] = all_tracks
    playlist_data['prepped_data'] = prepPlaylistData(playlist_data)
    return playlist_data

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




def update_playlist_metadata(playlist,spotify_playlist_data):
    metadata = PlaylistMetadata()
    metadata.Tags = [f'jellyplist:playlist:{playlist.id}',f'{playlist.tracks_available} of {playlist.track_count} Tracks available']
    metadata.Overview = spotify_playlist_data['description']
    jellyfin.update_playlist_metadata(session_token=_get_api_token(),playlist_id=playlist.jellyfin_id,updates= metadata , user_id= _get_admin_id())
    if spotify_playlist_data['images'] != None:
            jellyfin.set_playlist_cover_image(session_token= _get_api_token(),playlist_id= playlist.jellyfin_id,spotify_image_url= spotify_playlist_data['images'][0]['url'])



def _get_token_from_sessioncookie() -> str:
    return session['jellyfin_access_token']
def _get_api_token() -> str:
    #return app.config['JELLYFIN_ACCESS_TOKEN']
    return jellyfin_admin_token
def _get_logged_in_user():
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
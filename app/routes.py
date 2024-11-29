import json
import re
from flask import Flask, Response, jsonify, render_template, request, redirect, url_for, session, flash, Blueprint, g
from app import app, db, functions, sp, jellyfin, celery, jellyfin_admin_token, jellyfin_admin_id,device_id,  cache, read_dev_build_file, tasks
from app.models import JellyfinUser,Playlist,Track
from celery.result import AsyncResult

from app.providers import base
from app.providers.base import MusicProviderClient
from app.providers.spotify import SpotifyClient
from app.registry.music_provider_registry import MusicProviderRegistry
from .version import __version__
from spotipy.exceptions import SpotifyException

pl_bp = Blueprint('playlist', __name__)
@pl_bp.before_request
def set_active_provider():
    """
    Middleware to select the active provider based on request parameters.
    """
    provider_id = request.args.get('provider', 'Spotify')  # Default to Spotify
    try:
        g.music_provider = MusicProviderRegistry.get_provider(provider_id)
    except ValueError as e:
        return {"error": str(e)}, 400

@app.context_processor
def add_context():
    unlinked_track_count = len(Track.query.filter_by(downloaded=True,jellyfin_id=None).all())
    version = f"v{__version__}{read_dev_build_file()}"
    return dict(unlinked_track_count = unlinked_track_count, version = version, config = app.config)


# this feels wrong 
skip_endpoints = ['task_status']
@app.after_request
def render_messages(response: Response) -> Response:
    if request.headers.get("HX-Request"):
        if request.endpoint not in skip_endpoints:
            messages = render_template("partials/alerts.jinja2")
            response.headers['HX-Trigger'] = 'showToastMessages'
            response.data = response.data + messages.encode("utf-8")
    return response



@app.route('/admin/tasks')
@functions.jellyfin_admin_required
def task_manager():
    statuses = {}
    for task_name, task_id in functions.TASK_STATUS.items():
        if task_id:
            result = AsyncResult(task_id)
            statuses[task_name] = {'state': result.state, 'info': result.info if result.info else {}}
        else:
            statuses[task_name] = {'state': 'NOT STARTED', 'info': {}}
    
    return render_template('admin/tasks.html', tasks=statuses,lock_keys  = functions.LOCK_KEYS)

@app.route('/admin')
@app.route('/admin/link_issues')
@functions.jellyfin_admin_required
def link_issues():
    unlinked_tracks = Track.query.filter_by(downloaded=True,jellyfin_id=None).all()
    tracks = []
    for ult in unlinked_tracks: 
        sp_track = functions.get_cached_spotify_track(ult.provider_track_id)
        duration_ms = sp_track['duration_ms']
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) // 1000
        tracks.append({
                'title': sp_track['name'],
                'artist': ', '.join([artist['name'] for artist in sp_track['artists']]),
                'url': sp_track['external_urls']['spotify'],
                'duration': f'{minutes}:{seconds:02d}', 
                'preview_url': sp_track['preview_url'],
                'downloaded': ult.downloaded,  
                'filesystem_path': ult.filesystem_path,  
                'jellyfin_id': ult.jellyfin_id,
                'spotify_id': sp_track['id'],
                'duration_ms': duration_ms,
                'download_status'  : ult.download_status
            })

    return render_template('admin/link_issues.html' , tracks = tracks )



@app.route('/run_task/<task_name>', methods=['POST'])
@functions.jellyfin_admin_required
def run_task(task_name):
    status, info = functions.manage_task(task_name)
    
    # Rendere nur die aktualisierte Zeile der Task
    task_info = {task_name: {'state': status, 'info': info}}
    return render_template('partials/_task_status.html', tasks=task_info)


@app.route('/task_status')
@functions.jellyfin_admin_required
def task_status():
    statuses = {}
    for task_name, task_id in functions.TASK_STATUS.items():
        if task_id:
            result = AsyncResult(task_id)
            statuses[task_name] = {'state': result.state, 'info': result.info if result.info else {}}
        else:
            statuses[task_name] = {'state': 'NOT STARTED', 'info': {}}

    # Render the HTML partial template instead of returning JSON
    return render_template('partials/_task_status.html', tasks=statuses)



@app.route('/')
@functions.jellyfin_login_required 
def index():
    users = JellyfinUser.query.all()
    return render_template('index.html', user=session['jellyfin_user_name'], users=users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            jellylogin = jellyfin.login_with_password(username=username, password=password)
            if jellylogin:
                session['jellyfin_access_token'], session['jellyfin_user_id'], session['jellyfin_user_name'],session['is_admin'] = jellylogin
                session['debug'] = app.debug
                # Check if the user already exists
                user = JellyfinUser.query.filter_by(jellyfin_user_id=session['jellyfin_user_id']).first()
                if not user:
                    # Add the user to the database if they don't exist
                    new_user = JellyfinUser(name=session['jellyfin_user_name'], jellyfin_user_id=session['jellyfin_user_id'], is_admin = session['is_admin'])
                    db.session.add(new_user)
                    db.session.commit()

                return redirect('/')
        except:
            flash('Login failed. Please check your Jellyfin credentials and try again.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('jellyfin_user_name', None)
    session.pop('jellyfin_access_token', None)
    return redirect(url_for('login'))

@app.route('/add_single',methods=['GET'])
@functions.jellyfin_login_required
def add_single():
    playlist = request.args.get('playlist')
    error = None
    errdata= None
    if playlist:
        parsed = sp._get_id(type='playlist',id=playlist)
        if parsed:
            try:
                functions.get_cached_spotify_playlist(parsed)
                
                return redirect(f'/playlist/view/{parsed}')
            except SpotifyException as e:
                url_match = re.search(sp._regex_spotify_url, playlist)
                if url_match is not None:
                    resp = functions.fetch_spotify_playlist(playlist,None)
                    parsed_data = functions.parse_spotify_playlist_html(resp)
                error = (f'Playlist can´t be fetched')
                
                errdata = str(e)
            
    return render_template('index.html',error_message = error, error_data = errdata)

    
    

@app.route('/playlists')
@app.route('/categories')
@app.route('/playlists/monitored')
@functions.jellyfin_login_required
def loaditems():
    country = app.config['SPOTIFY_COUNTRY_CODE']
    offset = int(request.args.get('offset', 0))  # Get the offset (default to 0 for initial load)
    limit = 20  # Define a limit for pagination
    additional_query = ''
    items_subtitle = ''
    error_message = None  # Placeholder for error messages
    error_data = ''
    if request.path == '/playlists/monitored':
        try:
            db_playlists = db.session.query(Playlist).offset(offset).limit(limit).all()
            max_items = db.session.query(Playlist).count()
            
            provider_playlist_ids = [playlist.provider_playlist_id for playlist in db_playlists]
            spotify_data = functions.get_cached_spotify_playlists(tuple(provider_playlist_ids))
            for x in spotify_data['playlists']['items']:
                for from_db in db_playlists:
                    if x['id'] == from_db.provider_playlist_id:
                        x['name'] = from_db.name
            data = functions.prepPlaylistData(spotify_data)
            items_title = "Monitored Playlists"
            items_subtitle = "These playlists are already monitored by the Server. If you add one to your Jellyfin account, they will be available immediately."
        except SpotifyException as e:
            app.logger.error(f"Error fetching monitored playlists: {e}")
            data, max_items, items_title = [], e, f'Could not retrieve monitored Playlists. Please try again later. This is most likely due to an Error in the Spotify API or an rate limit has been reached.'
            error_message = items_title
            error_data = max_items

    elif request.path == '/playlists':
        cat = request.args.get('cat', None)
        if cat is not None:
            data, max_items, items_title = functions.getCategoryPlaylists(category=cat, offset=offset)
            if not data:  # Check if data is empty
                error_message = items_title  # Set the error message from the function
                error_data = max_items
            additional_query += f"&cat={cat}"
        else:
            data, max_items, items_title = functions.getFeaturedPlaylists(country=country, offset=offset)
            if not data:  # Check if data is empty
                error_message = items_title  # Set the error message from the function
                error_data = max_items

    elif request.path == '/categories':
        try:
            data, max_items, items_title = functions.getCategories(country=country, offset=offset)
        except Exception as e:
            app.logger.error(f"Error fetching categories: {e}")
            data, max_items, items_title = [], e, f'Error: Could not load categories. Please try again later. '
            error_message = items_title
            error_data = max_items
            

    next_offset = offset + len(data)
    total_items = max_items
    context = {
        'items': data,
        'next_offset': next_offset,
        'total_items': total_items,
        'endpoint': request.path,
        'items_title': items_title,
        'items_subtitle': items_subtitle,
        'additional_query': additional_query,
        'error_message': error_message,  # Pass error message to the template
        'error_data': error_data,  # Pass error message to the template
    }

    if request.headers.get('HX-Request'):  # Check if the request is from HTMX
        return render_template('partials/_spotify_items.html', **context)
    else:
        return render_template('items.html', **context)


@app.route('/search')
@functions.jellyfin_login_required
def searchResults():
    query = request.args.get('query')
    context = {}
    if query:
        # Add your logic here to perform the search on Spotify (or Jellyfin)
        search_result = sp.search(q = query, type= 'playlist',limit= 50, market=app.config['SPOTIFY_COUNTRY_CODE'])
        context = {
            #'artists' : functions.prepArtistData(search_result ),
            'playlists' : functions.prepPlaylistData(search_result ),
            #'albums' : functions.prepAlbumData(search_result ),
            'query' : query
        }
        return render_template('search.html', **context)
    else:
        return render_template('search.html', query=None, results={})


@pl_bp.route('/playlist/view/<playlist_id>')
@functions.jellyfin_login_required
def get_playlist_tracks(playlist_id):
    provider: MusicProviderClient = g.music_provider  # Explicit type hint for g.music_provider
    playlist: base.Playlist = provider.get_playlist(playlist_id)
    tracks = functions.get_tracks_for_playlist(playlist.tracks)  # Deine Funktion, um Tracks zu holen
    # Berechne die gesamte Dauer der Playlist
    total_duration_ms = sum([track['track']['duration_ms'] for track in data['tracks']['items'] if track['track']])

    # Konvertiere die Gesamtdauer in ein lesbares Format
    hours, remainder = divmod(total_duration_ms // 1000, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Formatierung der Dauer
    if hours > 0:
        total_duration = f"{hours}h {minutes}min"
    else:
        total_duration = f"{minutes}min"
    
    return render_template(
        'tracks_table.html',
        tracks=tracks,
        total_duration=total_duration,
        track_count=len(data['tracks']),
        playlist_name=data['name'],
        playlist_cover=data['images'][0]['url'],
        playlist_description=data['description'],
        last_updated = data['prepped_data'][0]['last_updated'],
        last_changed = data['prepped_data'][0]['last_changed'],
        item = data['prepped_data'][0],
        
    )
@app.route('/associate_track', methods=['POST'])
@functions.jellyfin_login_required
def associate_track():
    jellyfin_id = request.form.get('jellyfin_id')
    spotify_id = request.form.get('spotify_id')

    if not jellyfin_id or not spotify_id:
        flash('Missing Jellyfin or Spotify ID')

    # Retrieve the track by Spotify ID
    track = Track.query.filter_by(provider_track_id=spotify_id).first()

    if not track:
        flash('Track not found')
        return ''

    # Associate the Jellyfin ID with the track
    track.jellyfin_id = jellyfin_id

    try:
        # Commit the changes to the database
        db.session.commit()
        flash("Track associated","success")
        return ''
    except Exception as e:
        db.session.rollback()  # Roll back the session in case of an error
        flash(str(e))
        return ''
        

@app.route("/unlock_key",methods = ['POST'])
@functions.jellyfin_admin_required
def unlock_key():
     
    key_name = request.form.get('inputLockKey')
    if key_name:
        tasks.release_lock(key_name)
        flash(f'Lock {key_name} released', category='success')
    return ''


@app.route('/test')
def test():
    playlist_id = "37i9dQZF1DX12qgyzUprB6"
    client = SpotifyClient(cookie_file='/jellyplist/open.spotify.com_cookies.txt')
    client.authenticate()
    pl = client.get_playlist(playlist_id=playlist_id)
    browse = client.browse_all()
    page = client.browse_page(browse[0].items[12])
    return ''
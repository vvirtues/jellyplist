from flask import Flask, Response, jsonify, render_template, request, redirect, url_for, session, flash
from app import app, db, functions, sp, jellyfin, celery, jellyfin_admin_token, jellyfin_admin_id,device_id,  cache
from app.models import JellyfinUser,Playlist,Track
from celery.result import AsyncResult
from .version import __version__

@app.context_processor
def add_context():
    unlinked_track_count = len(Track.query.filter_by(downloaded=True,jellyfin_id=None).all())
    version = f"v{__version__}"
    return dict(unlinked_track_count = unlinked_track_count, version = version)

@app.after_request
def render_messages(response: Response) -> Response:
    if request.headers.get("HX-Request"):
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
    
    return render_template('admin/tasks.html', tasks=statuses)

@app.route('/admin')
@app.route('/admin/link_issues')
@functions.jellyfin_admin_required
def link_issues():
    unlinked_tracks = Track.query.filter_by(downloaded=True,jellyfin_id=None).all()
    tracks = []
    # for ult in unlinked_tracks: 
    #     sp_track = functions.get_cached_spotify_track(ult.spotify_track_id)
        
    #     tracks.append({
    #             'title': sp_track['name'],
    #             'artist': ', '.join([artist['name'] for artist in sp_track['artists']]),
    #             'url': sp_track['external_urls']['spotify'],
    #             'duration': f'{minutes}:{seconds:02d}', 
    #             'preview_url': sp_track['preview_url'],
    #             'downloaded': ult.downloaded,  
    #             'filesystem_path': utl.filesystem_path,  
    #             'jellyfin_id': ult.jellyfin_id,
    #             'spotify_id': sp_track['id'],
    #             'duration_ms': duration_ms,
    #             'download_status'  : download_status
    #         })

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

                return redirect('/playlists')
        except:
            flash('Login failed. Please check your Jellyfin credentials and try again.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('jellyfin_user_name', None)
    session.pop('jellyfin_access_token', None)
    return redirect(url_for('login'))


@app.route('/playlists')
@app.route('/categories')
@app.route('/playlists/monitored')
@functions.jellyfin_login_required
def loaditems():
    country = 'DE'
    offset = int(request.args.get('offset', 0))  # Get the offset (default to 0 for initial load)
    limit = 20  # Define a limit for pagination
    additional_query = ''
    items_subtitle = ''

    if request.path == '/playlists/monitored':
        # Step 1: Query the database for monitored playlists
        db_playlists = db.session.query(Playlist).offset(offset).limit(limit).all()
        max_items = db.session.query(Playlist).count()
        
        # Collect Spotify Playlist IDs from the database
        spotify_playlist_ids = [playlist.spotify_playlist_id for playlist in db_playlists]
      
        spotify_data = functions.get_cached_spotify_playlists(tuple(spotify_playlist_ids))

        # Step 3: Pass the Spotify data to prepPlaylistData for processing
        data = functions.prepPlaylistData(spotify_data)
        items_title = "Monitored Playlists"
        items_subtitle = "This playlists are already monitored by the Server, if you add one of these to your Jellyfin account, they will be available immediately."

    elif request.path == '/playlists':
        cat = request.args.get('cat', None)
        if cat is not None:
            data, max_items, items_title = functions.getCategoryPlaylists(category=cat, offset=offset)
            additional_query += f"&cat={cat}"
        else:
            data, max_items, items_title = functions.getFeaturedPlaylists(country=country, offset=offset)

    elif request.path == '/categories':
        data, max_items, items_title = functions.getCategories(country=country, offset=offset)

    next_offset = offset + len(data)
    total_items = max_items
    context = {
        'items': data,
        'next_offset': next_offset,
        'total_items': total_items,
        'endpoint': request.path,
        'items_title': items_title,
        'items_subtitle' : items_subtitle,
        'additional_query': additional_query
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
        search_result = sp.search(q = query, type= 'track,album,artist,playlist')
        context = {
            'artists' : functions.prepArtistData(search_result ),
            'playlists' : functions.prepPlaylistData(search_result ),
            'albums' : functions.prepAlbumData(search_result ),
            'query' : query
        }
        return render_template('search.html', **context)
    else:
        return render_template('search.html', query=None, results={})


@app.route('/playlist/view/<playlist_id>')
@functions.jellyfin_login_required
def get_playlist_tracks(playlist_id):
    # Hol dir alle Tracks für die Playlist
    data = functions.get_full_playlist_data(playlist_id)  # Diese neue Funktion holt alle Tracks der Playlist
    tracks = functions.get_tracks_for_playlist(data)  # Deine Funktion, um Tracks zu holen
    # Berechne die gesamte Dauer der Playlist
    total_duration_ms = sum([track['track']['duration_ms'] for track in data['tracks'] if track['track']])

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
    track = Track.query.filter_by(spotify_track_id=spotify_id).first()

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
        

@app.route('/test')
def test():
    return ''
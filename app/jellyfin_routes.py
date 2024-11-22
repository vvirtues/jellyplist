import time
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from sqlalchemy import insert
from app import app, db,  jellyfin, functions, device_id
from app.models import Playlist,Track,  playlist_tracks



from jellyfin.objects import PlaylistMetadata



@app.route('/jellyfin_playlists')
@functions.jellyfin_login_required
def jellyfin_playlists():
    try:
        # Fetch playlists from Jellyfin
        playlists = jellyfin.get_playlists(session_token=functions._get_token_from_sessioncookie())
        
        # Extract Spotify playlist IDs from the database
        spotify_playlist_ids = []
        for pl in playlists:
            # Retrieve the playlist from the database using Jellyfin ID
            from_db = Playlist.query.filter_by(jellyfin_id=pl['Id']).first()
            if from_db and from_db.spotify_playlist_id:
                spotify_playlist_ids.append(from_db.spotify_playlist_id)
            else:
                app.logger.warning(f"No database entry found for Jellyfin playlist ID: {pl['Id']}")

        if not spotify_playlist_ids:
            flash('No Spotify playlists found to display.', 'warning')
            return render_template('jellyfin_playlists.html', playlists=functions.prepPlaylistData({'playlists': {'items': []}}))
        
        # Use the cached function to fetch Spotify playlists
        spotify_data = functions.get_cached_spotify_playlists(spotify_playlist_ids)
        
        # Prepare the data for the template
        prepared_data = functions.prepPlaylistData(spotify_data)
        
        return render_template('jellyfin_playlists.html', playlists=prepared_data)
    
    except Exception as e:
        app.logger.error(f"Error in /jellyfin_playlists route: {str(e)}")
        flash('An error occurred while fetching playlists.', 'danger')
        return render_template('jellyfin_playlists.html', playlists=functions.prepPlaylistData({'playlists': {'items': []}}))
    

@app.route('/addplaylist', methods=['POST'])
@functions.jellyfin_login_required
def add_playlist():
    playlist_id = request.form.get('item_id')  # HTMX sends the form data
    playlist_name = request.form.get('item_name')  # Optionally retrieve playlist name from the form
    if not playlist_id:
        flash('No playlist ID provided')
        return ''

    try:
        # Fetch playlist from Spotify API (or any relevant API)
        playlist_data = functions.get_cached_spotify_playlist(playlist_id)

        # Check if playlist already exists in the database
        playlist = Playlist.query.filter_by(spotify_playlist_id=playlist_id).first()

        if not playlist:
            # Add new playlist if it doesn't exist
            # create the playlist via api key, with the first admin as 'owner' 
            fromJellyfin = jellyfin.create_music_playlist(functions._get_api_token(),playlist_data['name'],[],functions._get_admin_id())['Id']
            playlist = Playlist(name=playlist_data['name'], spotify_playlist_id=playlist_id,spotify_uri=playlist_data['uri'],track_count = playlist_data['tracks']['total'], tracks_available=0, jellyfin_id = fromJellyfin)
            db.session.add(playlist)
            db.session.commit()
            if app.config['START_DOWNLOAD_AFTER_PLAYLIST_ADD']:
                functions.manage_task('download_missing_tracks')


        # Get the logged-in user
        user = functions._get_logged_in_user()
        playlist.tracks_available = 0
        
        # Add tracks to the playlist with track order
        for idx, track_data in enumerate(playlist_data['tracks']['items']):
            track_info = track_data['track']
            if not track_info:
                continue
            track = Track.query.filter_by(spotify_track_id=track_info['id']).first()

            if not track:
                # Add new track if it doesn't exist
                track = Track(name=track_info['name'], spotify_track_id=track_info['id'], spotify_uri=track_info['uri'], downloaded=False)
                db.session.add(track)
                db.session.commit()
            elif track.downloaded:
                playlist.tracks_available += 1
                db.session.commit()

            # Add track to playlist with order if it's not already associated
            if track not in playlist.tracks:
                # Insert into playlist_tracks with track order
                stmt = insert(playlist_tracks).values(
                    playlist_id=playlist.id,
                    track_id=track.id,
                    track_order=idx  # Maintain the order of tracks
                )
                db.session.execute(stmt)
                db.session.commit()
        
        functions.update_playlist_metadata(playlist,playlist_data)
        
        if playlist not in user.playlists:
            user.playlists.append(playlist)
            db.session.commit()
            jellyfin.add_users_to_playlist(session_token=functions._get_api_token(), user_id=functions._get_admin_id(),playlist_id = playlist.jellyfin_id,user_ids= [user.jellyfin_user_id])
            flash(f'Playlist "{playlist_data["name"]}" successfully added','success')
            
        else:
            flash(f'Playlist "{playlist_data["name"]}" already in your list')
        item = {
            "name" : playlist_data["name"],
            "id" : playlist_id,
            "can_add":False,
            "can_remove":True,
            "jellyfin_id" : playlist.jellyfin_id
        }
        return render_template('partials/_add_remove_button.html',item= item)
            
            


    except Exception as e:
        flash(str(e))
     

@app.route('/delete_playlist/<playlist_id>', methods=['DELETE'])
@functions.jellyfin_login_required
def delete_playlist(playlist_id):
    # Logic to delete the playlist using JellyfinClient
    try:
        user = functions._get_logged_in_user()
        for pl in user.playlists:
            if pl.jellyfin_id == playlist_id:
                user.playlists.remove(pl)
                playlist = pl
        jellyfin.remove_user_from_playlist(session_token= functions._get_api_token(), playlist_id= playlist_id, user_id=user.jellyfin_user_id)
        db.session.commit()
        flash('Playlist removed')
        item = {
            "name" : playlist.name,
            "id" : playlist.spotify_playlist_id,
            "can_add":True,
            "can_remove":False,
            "jellyfin_id" : playlist.jellyfin_id
        }
        return render_template('partials/_add_remove_button.html',item= item)
    except Exception as e:
        flash(f'Failed to remove item: {str(e)}')
    



@functions.jellyfin_login_required
@app.route('/get_jellyfin_stream/<string:jellyfin_id>')
def get_jellyfin_stream(jellyfin_id):
    user_id = session['jellyfin_user_id']  # Beispiel: dynamischer Benutzer
    api_key = functions._get_token_from_sessioncookie()  # Beispiel: dynamischer API-Schlüssel
    stream_url = f"{app.config['JELLYFIN_SERVER_URL']}/Audio/{jellyfin_id}/universal?UserId={user_id}&DeviceId={device_id}&MaxStreamingBitrate=140000000&Container=opus,webm|opus,mp3,aac,m4a|aac,m4b|aac,flac,webma,webm|webma,wav,ogg&TranscodingContainer=mp4&TranscodingProtocol=hls&AudioCodec=aac&api_key={api_key}&PlaySessionId={int(time.time())}&StartTimeTicks=0&EnableRedirection=true&EnableRemoteMedia=false"
    return jsonify({'stream_url': stream_url})

@app.route('/search_jellyfin', methods=['GET'])
@functions.jellyfin_login_required
def search_jellyfin():
    search_query = request.args.get('search_query')
    spotify_id = request.args.get('spotify_id')
    if search_query:
        results = jellyfin.search_music_tracks(functions._get_token_from_sessioncookie(), search_query)
        # Render only the search results section as response
        return render_template('partials/_jf_search_results.html', results=results,spotify_id=  spotify_id)
    return jsonify({'error': 'No search query provided'}), 400